(function () {
  "use strict";

  /* Reading speed of the home page tickers, in pixels per second. Raise to
     speed up, lower to slow down. */
  var TICKER_SPEED_PX_PER_SECOND = 60;

  /* Makes a marquee truly endless.

     The markup holds ONE segment (a run of headlines / ad links). A loop that
     only translates by "half the track" shows blank space when the segment is
     narrower than the bar, e.g. when there are only a few headlines. So here
     the segment is cloned until one group of copies is at least as wide as the
     bar, then that whole group is repeated once more. The animation slides
     exactly one group width (--ticker-shift), and because the second group is
     identical to the first, the restart is invisible no matter how short the
     text is or how wide the screen. Clones are hidden from screen readers and
     the tab order so ad links are not announced or focusable twice. */
  function build(track) {
    var original = track.querySelector("[data-ticker-segment]:not([data-ticker-clone])");
    if (!original) return;

    Array.prototype.slice.call(track.querySelectorAll("[data-ticker-clone]")).forEach(function (node) {
      node.remove();
    });

    var bar = track.parentElement;
    var segmentWidth = original.getBoundingClientRect().width;
    var barWidth = bar.clientWidth;
    if (!segmentWidth || !barWidth) return;

    var copiesPerGroup = Math.max(1, Math.ceil(barWidth / segmentWidth));

    function addClone() {
      var clone = original.cloneNode(true);
      clone.setAttribute("data-ticker-clone", "");
      clone.setAttribute("aria-hidden", "true");
      Array.prototype.slice.call(clone.querySelectorAll("a")).forEach(function (link) {
        link.setAttribute("tabindex", "-1");
      });
      track.appendChild(clone);
    }

    /* group 1 = original + (copiesPerGroup - 1) clones, group 2 = copiesPerGroup clones */
    for (var i = 0; i < copiesPerGroup * 2 - 1; i += 1) addClone();

    var groupWidth = segmentWidth * copiesPerGroup;
    track.style.setProperty("--ticker-shift", "-" + groupWidth + "px");
    var speed = parseFloat(track.getAttribute("data-ticker-speed")) || TICKER_SPEED_PX_PER_SECOND;
    track.style.animationDuration = groupWidth / speed + "s";  }

  function buildAll() {
    Array.prototype.slice.call(document.querySelectorAll("[data-ticker-track]")).forEach(build);
  }

  function init() {
    buildAll();

    /* web fonts change the text width after first paint, measure again then */
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(buildAll);

    var resizeTimer = null;
    window.addEventListener("resize", function () {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(buildAll, 150);
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
