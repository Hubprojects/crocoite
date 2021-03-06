# Copyright (c) 2017–2018 crocoite contributors
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

"""
IRC bot “chromebot”
"""

import asyncio, argparse, uuid, json, tempfile
from datetime import datetime
from urllib.parse import urlsplit
from enum import IntEnum, Enum
from collections import defaultdict
from abc import abstractmethod
from functools import wraps
import bottom

### helper functions ###
def prettyTimeDelta (seconds):
    """
    Pretty-print seconds to human readable string 1d 1h 1m 1s
    """
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    s = [(days, 'd'), (hours, 'h'), (minutes, 'm'), (seconds, 's')]
    s = filter (lambda x: x[0] != 0, s)
    return ' '.join (map (lambda x: '{}{}'.format (*x), s))

def prettyBytes (b):
    """
    Pretty-print bytes
    """
    prefixes = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
    while b >= 1024 and len (prefixes) > 1:
        b /= 1024
        prefixes.pop (0)
    return '{:.1f} {}'.format (b, prefixes[0])

def isValidUrl (s):
    url = urlsplit (s)
    if url.scheme and url.netloc and url.scheme in {'http', 'https'}:
        return s
    raise TypeError ()

class NonExitingArgumentParser (argparse.ArgumentParser):
    """ Argument parser that does not call exit(), suitable for interactive use """

    def exit (self, status=0, message=None):
        # should never be called
        pass

    def error (self, message):
        # if we use subparsers it’s important to return self, so we can show
        # the correct help
        raise Exception (self, message)

    def format_usage (self):
        return super().format_usage ().replace ('\n', ' ')

class Status(IntEnum):
    """ Job status """
    undefined = 0
    pending = 1
    running = 2
    aborted = 3
    finished = 4

class Job:
    """ Archival job """

    __slots__ = ('id', 'stats', 'rstats', 'started', 'finished', 'nick', 'status', 'process', 'url')

    def __init__ (self, url, nick):
        self.id = str (uuid.uuid4 ())
        self.stats = {}
        self.rstats = {}
        self.started = datetime.utcnow ()
        self.finished = None
        self.url = url
        # user who scheduled this job
        self.nick = nick
        self.status = Status.pending
        self.process = None

    def formatStatus (self):
        stats = self.stats
        rstats = self.rstats
        return '{} ({}) {}. {} pages finished, {} pending; {} crashed, {} requests, {} failed, {} received.'.format (
                self.url,
                self.id,
                self.status.name,
                rstats.get ('have', 0),
                rstats.get ('pending', 0),
                stats.get ('crashed', 0),
                stats.get ('requests', 0),
                stats.get ('failed', 0),
                prettyBytes (stats.get ('bytesRcv', 0)))

class NickMode(Enum):
    operator = '@'
    voice = '+'

    @classmethod
    def fromMode (cls, mode):
        return {'v': cls.voice, 'o': cls.operator}[mode]

class User:
    """ IRC user """
    __slots__ = ('name', 'modes')

    def __init__ (self, name, modes=set ()):
        self.name = name
        self.modes = modes

    def __eq__ (self, b):
        return self.name == b.name

    def __hash__ (self):
        return hash (self.name)

    def __repr__ (self):
        return '<User {} {}>'.format (self.name, self.modes)

    @classmethod
    def fromName (cls, name):
        """ Get mode and name from NAMES command """
        try:
            modes = {NickMode(name[0])}
            name = name[1:]
        except ValueError:
            modes = set ()
        return cls (name, modes)

class ReplyContext:
    __slots__ = ('client', 'target', 'user')

    def __init__ (self, client, target, user):
        self.client = client
        self.target = target
        self.user = user

    def __call__ (self, message):
        self.client.send ('PRIVMSG', target=self.target, message='{}: {}'.format (self.user.name, message))

class ArgparseBot (bottom.Client):
    """
    Simple IRC bot using argparse
    
    Tracks user’s modes, reconnects on disconnect
    """

    __slots__ = ('channels', 'nick', 'parser', 'users')

    def __init__ (self, host, port, ssl, nick, logger, channels=[]):
        super().__init__ (host=host, port=port, ssl=ssl)
        self.channels = channels
        self.nick = nick
        # map channel -> nick -> user
        self.users = defaultdict (dict)
        self.logger = logger
        self.parser = self.getParser ()

        # register bottom event handler
        self.on('CLIENT_CONNECT', self.onConnect)
        self.on('PING', self.onKeepalive)
        self.on('PRIVMSG', self.onMessage)
        self.on('CLIENT_DISCONNECT', self.onDisconnect)
        self.on('RPL_NAMREPLY', self.onNameReply)
        self.on('CHANNELMODE', self.onMode)
        self.on('PART', self.onPart)
        self.on('JOIN', self.onJoin)
        # XXX: we would like to handle KICK, but bottom does not support that at the moment

    @abstractmethod
    def getParser (self):
        pass

    async def onConnect (self, **kwargs):
        self.logger.info ('connect', nick=self.nick)

        self.send('NICK', nick=self.nick)
        self.send('USER', user=self.nick, realname='https://github.com/PromyLOPh/crocoite')

        # Don't try to join channels until the server has
        # sent the MOTD, or signaled that there's no MOTD.
        done, pending = await asyncio.wait(
            [self.wait('RPL_ENDOFMOTD'), self.wait('ERR_NOMOTD')],
            loop=self.loop, return_when=asyncio.FIRST_COMPLETED)

        # Cancel whichever waiter's event didn't come in.
        for future in pending:
            future.cancel()

        for c in self.channels:
            self.logger.info ('join', channel=c)
            self.send ('JOIN', channel=c)
            # no need for NAMES here, server sends this automatically

    async def onNameReply (self, target, channel_type, channel, users, **kwargs):
        self.users[channel] = dict (map (lambda x: (x.name, x), map (User.fromName, users)))

    @staticmethod
    def parseMode (mode):
        """ Parse mode strings like +a, -b, +a-b, -b+a, … """
        action = '+'
        ret = []
        for c in mode:
            if c in {'+', '-'}:
                action = c
            else:
                ret.append ((action, c))
        return ret

    async def onMode (self, nick, user, host, channel, modes, params, **kwargs):
        if channel not in self.channels:
            return

        for (action, mode), nick in zip (self.parseMode (modes), params):
            try:
                m = NickMode.fromMode (mode)
                u = self.users[channel].get (nick, User (nick))
                if action == '+':
                    u.modes.add (m)
                elif action == '-':
                    u.modes.remove (m)
            except KeyError:
                # unknown mode, ignore
                pass

    async def onPart (self, nick, user, host, message, channel, **kwargs):
        if channel not in self.channels:
            return

        try:
            self.users[channel].pop (nick)
        except KeyError:
            # gone already
            pass

    async def onJoin (self, nick, channel, **kwargs):
        if channel not in self.channels:
            return

        self.users[channel][nick] = User (nick)

    async def onKeepalive (self, message, **kwargs):
        """ Ping received """
        self.send('PONG', message=message)

    async def onMessage (self, nick, target, message, **kwargs):
        """ Message received """
        if target in self.channels and message.startswith (self.nick):
            user = self.users[target].get (nick, User (nick))
            reply = ReplyContext (client=self, target=target, user=user)

            # channel message that starts with our nick
            command = message.split (' ')[1:]
            try:
                args = self.parser.parse_args (command)
            except Exception as e:
                reply ('{} -- {}'.format (e.args[1], e.args[0].format_usage ()))
                return
            if not args:
                reply ('Sorry, I don’t understand {}'.format (command))
                return

            await args.func (user=user, args=args, reply=reply)

    async def onDisconnect (**kwargs):
        """ Auto-reconnect """
        self.logger.info ('disconnect')
        await asynio.sleep (10, loop=self.loop)
        self.logger.info ('reconnect')
        await self.connect ()

def voice (func):
    """ Calling user must have voice or ops """
    @wraps (func)
    async def inner (self, *args, **kwargs):
        user = kwargs.get ('user')
        reply = kwargs.get ('reply')
        if not user.modes.intersection ({NickMode.operator, NickMode.voice}):
            reply ('Sorry, you must have voice to use this command.')
        else:
            ret = await func (self, *args, **kwargs)
            return ret
    return inner

def jobExists (func):
    """ Chromebot job exists """
    @wraps (func)
    async def inner (self, **kwargs):
        # XXX: not sure why it works with **kwargs, but not (user, args, reply)
        args = kwargs.get ('args')
        reply = kwargs.get ('reply')
        j = self.jobs.get (args.id, None)
        if not j:
            reply ('Job {} is unknown'.format (args.id))
        else:
            ret = await func (self, job=j, **kwargs)
            return ret
    return inner

class Chromebot (ArgparseBot):
    __slots__ = ('jobs', 'tempdir', 'destdir', 'processLimit')

    def __init__ (self, host, port, ssl, nick, logger, channels=[],
            tempdir=tempfile.gettempdir(), destdir='.', processLimit=1):
        super().__init__ (host=host, port=port, ssl=ssl, nick=nick,
                logger=logger, channels=channels)

        self.jobs = {}
        self.tempdir = tempdir
        self.destdir = destdir
        self.processLimit = asyncio.Semaphore (processLimit)

    def getParser (self):
        parser = NonExitingArgumentParser (prog=self.nick + ': ', add_help=False)
        subparsers = parser.add_subparsers(help='Sub-commands')

        archiveparser = subparsers.add_parser('a', help='Archive a site', add_help=False)
        #archiveparser.add_argument('--timeout', default=1*60*60, type=int, help='Maximum time for archival', metavar='SEC', choices=[60, 1*60*60, 2*60*60])
        #archiveparser.add_argument('--idle-timeout', default=10, type=int, help='Maximum idle seconds (i.e. no requests)', dest='idleTimeout', metavar='SEC', choices=[1, 10, 20, 30, 60])
        #archiveparser.add_argument('--max-body-size', default=None, type=int, dest='maxBodySize', help='Max body size', metavar='BYTES', choices=[1*1024*1024, 10*1024*1024, 100*1024*1024])
        archiveparser.add_argument('--concurrency', '-j', default=1, type=int, help='Parallel workers for this job', choices=range (1, 5))
        archiveparser.add_argument('--recursive', '-r', help='Enable recursion', choices=['0', '1', 'prefix'], default='0')
        archiveparser.add_argument('url', help='Website URL', type=isValidUrl, metavar='URL')
        archiveparser.set_defaults (func=self.handleArchive)

        statusparser = subparsers.add_parser ('s', help='Get job status', add_help=False)
        statusparser.add_argument('id', help='Job id', metavar='UUID')
        statusparser.set_defaults (func=self.handleStatus)

        abortparser = subparsers.add_parser ('r', help='Revoke/abort job', add_help=False)
        abortparser.add_argument('id', help='Job id', metavar='UUID')
        abortparser.set_defaults (func=self.handleAbort)

        return parser

    @voice
    async def handleArchive (self, user, args, reply):
        """ Handle the archive command """

        j = Job (args.url, user.name)
        assert j.id not in self.jobs, 'duplicate job id'
        self.jobs[j.id] = j

        logger = self.logger.bind (id=j.id, user=user.name, url=args.url)

        cmdline = ['crocoite-recursive', args.url, '--tempdir', self.tempdir,
                '--prefix', j.id + '-{host}-{date}-', '--policy',
                args.recursive, '--concurrency', str (args.concurrency),
                self.destdir]

        showargs = {
                'recursive': args.recursive,
                'concurrency': args.concurrency,
                }
        strargs = ', '.join (map (lambda x: '{}={}'.format (*x), showargs.items ()))
        reply ('{} has been queued as {} with {}'.format (args.url, j.id, strargs))
        logger.info ('queue', cmdline=cmdline)

        async with self.processLimit:
            if j.status == Status.pending:
                # job was not aborted
                j.process = await asyncio.create_subprocess_exec (*cmdline,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL,
                        stdin=asyncio.subprocess.DEVNULL)
                while True:
                    data = await j.process.stdout.readline ()
                    if not data:
                        break

                    # job is marked running after the first message is received from it
                    if j.status == Status.pending:
                        logger.info ('start')
                        j.status = Status.running

                    data = json.loads (data)
                    msgid = data.get ('uuid')
                    if msgid == '24d92d16-770e-4088-b769-4020e127a7ff':
                        j.stats = data
                    elif msgid == '5b8498e4-868d-413c-a67e-004516b8452c':
                        j.rstats = data
                code = await j.process.wait ()

        if j.status == Status.running:
            logger.info ('finish')
            j.status = Status.finished
        j.finished = datetime.utcnow ()

        stats = j.stats
        rstats = j.rstats
        reply (j.formatStatus ())

    @jobExists
    async def handleStatus (self, user, args, reply, job):
        """ Handle status command """

        rstats = job.rstats
        reply (job.formatStatus ())

    @voice
    @jobExists
    async def handleAbort (self, user, args, reply, job):
        """ Handle abort command """

        if job.status not in {Status.pending, Status.running}:
            reply ('This job is not running.')
            return

        job.status = Status.aborted
        self.logger.info ('abort', id=job.id, user=user.name)
        if job.process and job.process.returncode is None:
            job.process.terminate ()

