/*	Continuously scrolls the page
 */
var __crocoite_stop__ = false;
(function(){
function scroll (event) {
	if (__crocoite_stop__) {
		return false;
	} else {
		window.scrollBy (0, window.innerHeight/2);
		document.querySelectorAll ('*').forEach (
			function (d) {
				if (d.clientHeight < d.scrollHeight) {
					d.scrollBy (0, d.clientHeight/2);
				}
			});
		return true;
	}
}
function onload (event) {
    window.setInterval (scroll, 200);
}
document.addEventListener("DOMContentLoaded", onload);
}());
