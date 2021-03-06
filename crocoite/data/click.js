/*	Generic clicking
 *
 *  We can’t just click every clickable object, since there may be side-effects
 *  like navigating to a different location. Thus whitelist known elements.
 */

(function(){
const selectorFlag = Object.freeze ({
	none: 0,
	multi: 1, /* click item multiple times */
});
const defaultClickThrottle = 50; /* in ms */
const discoverInterval = 1000; /* 1 second */
const sites = Object.freeze ([
	{
		hostname: /^www\.facebook\.com$/i,
		selector: [
			/* show more comments */
			{s: 'a.UFIPagerLink[role=button]', flags: selectorFlag.none},
			/* show nested comments*/
			{s: 'a.UFICommentLink[role=button]', flags: selectorFlag.none},
			/* initially show comments below a single post/video, i.e. /user/post/123 */
			{s: 'form.commentable_item a[data-comment-prelude-ref=action_link_bling][rel=ignore]', flags: selectorFlag.none},
			/* close the “register now” nag screen. for better screen shots */
			{s: 'div#headerArea a#expanding_cta_close_button[role=button]', flags: selectorFlag.none},
			],
	}, {
		hostname: /^twitter\.com$/i,
		selector: [
			/* expand threads */
			{s: 'a.ThreadedConversation-moreRepliesLink', flags: selectorFlag.none},
			/* show hidden profiles */
			{s: 'button.ProfileWarningTimeline-button', flags: selectorFlag.none},
			/* show hidden/sensitive media */
			{s: 'button.Tombstone-action.js-display-this-media', flags: selectorFlag.none},
			],
	}, {
		hostname: /^disqus\.com$/i,
		selector: [
			/* load more comments */
			{s: 'a.load-more__button', flags: selectorFlag.multi},
			],
	}, {
		hostname: /^(www|np)\.reddit\.com$/i,
		selector: [
			/* show more comments, reddit’s javascript ignores events if too
			 * frequent */
			{s: 'span.morecomments a', flags: selectorFlag.none, throttle: 500},
			],
	}, {
		hostname: /^www\.instagram\.com$/i,
		selector: [
			/* posts may have multiple images that load dynamically, click the arrow */
			{s: 'a[role=button].coreSpriteRightChevron', flags: selectorFlag.multi, throttle: 500},
			/* load more comments */
			{s: 'article div ul li a[role=button]', flags: selectorFlag.multi},
			],
	}, {
		hostname: /^www\.youtube\.com$/i,
		selector: [
			/* expand comment thread */
			{s: 'ytd-comment-thread-renderer div.more-button', flags: selectorFlag.none},
			],
	}, {
		hostname: /^www\.patreon\.com$/i,
		selector: [
			/* load more content */
			{s: 'div[display=flex] div[display=block] button[color=gray][type=button]', flags: selectorFlag.multi},
			/* load more comments */
			{s: 'div.stackable[display=block] > div  > div  > a[color=dark][target=_self]', flags: selectorFlag.none},
			/* load more replies */
			{s: 'div > a[scale="0"][color=blue][size="1"]', flags: selectorFlag.none},
			],
	}
	]);

/* pick selectors matching current location */
let hostname = document.location.hostname;
let selector = [];
for (let s of sites) {
	if (s.hostname.test (hostname)) {
		selector = selector.concat (s.selector);
	}
}

function makeClickEvent () {
	return new MouseEvent('click', {
				view: window,
				bubbles: true,
				cancelable: true
				});
}

/* throttle clicking */
let queue = [];
let clickTimeout = null;
function click () {
	if (queue.length > 0) {
		const item = queue.shift ();
		const o = item.o;
		const selector = item.selector;
		o.dispatchEvent (makeClickEvent ());

		if (queue.length > 0) {
			const nextTimeout = 'throttle' in selector ?
					selector.throttle : defaultClickThrottle;
			clickTimeout = window.setTimeout (click, nextTimeout);
		} else {
			clickTimeout = null;
		}
	}
}

/*	Element is visible if itself and all of its parents are
 */
function isVisible (o) {
	if (o === null || !(o instanceof Element)) {
		return true;
	}
	let style = window.getComputedStyle (o);
	if ('parentNode' in o) {
		return style.display !== 'none' && isVisible (o.parentNode);
	} else {
		return style.display !== 'none';
	}
}

/*	Elements are considered clickable if they are a) visible and b) not
 *	disabled
 */
function isClickable (o) {
	return !o.hasAttribute ('disabled') && isVisible (o);
}

/* some sites don’t remove/replace the element immediately, so keep track of
 * which ones we already clicked */
let have = new Set ();
function discover () {
	for (let s of selector) {
		let obj = document.querySelectorAll (s.s);
		for (let o of obj) {
			if (!have.has (o) && isClickable (o)) {
				queue.push ({o: o, selector: s});
				if (!(s.flags & selectorFlag.multi)) {
					have.add (o);
				}
			}
		}
	}
	if (queue.length > 0 && clickTimeout === null) {
		/* start clicking immediately */
		clickTimeout = window.setTimeout (click, 0);
	}
	return true;
}

/* XXX: can we use a mutation observer instead? */
window.setInterval (discover, discoverInterval);
}());
