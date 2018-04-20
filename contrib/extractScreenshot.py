#!/usr/bin/env python3

# Copyright (c) 2017 crocoite contributors
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
Extract page screenshots from a WARC generated by crocoite into files
"""

import shutil, sys, re, os
from warcio.archiveiterator import ArchiveIterator

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Extract screenshots.')
    parser.add_argument('-f', '--force', action='store_true', help='Overwrite existing files')
    parser.add_argument('input', type=argparse.FileType ('rb'), help='Input WARC')
    parser.add_argument('prefix', help='Output file prefix')

    args = parser.parse_args()

    screenshotRe = re.compile (r'^urn:crocoite:screenshot-(\d+)-(\d+).png$', re.I)
    with args.input:
        for record in ArchiveIterator(args.input):
            uri = record.rec_headers.get_header('WARC-Target-URI')
            if record.rec_type == 'resource':
                m = screenshotRe.match (uri)
                xoff, yoff = m.groups ()
                if m:
                    outpath = '{}-{}-{}.png'.format (args.prefix, xoff, yoff)
                    if args.force or not os.path.exists (outpath):
                        with open (outpath, 'wb') as out:
                            shutil.copyfileobj (record.raw_stream, out)
                    else:
                        print ('not overwriting {}'.format (outpath))
