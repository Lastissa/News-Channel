(function () {
  "use strict";

  /* Reading speed of the top-of-page ticker, in pixels per second.
     Raise this to speed it up, lower it to slow it down. */
  var TICKER_SPEED_PX_PER_SECOND = 60;

  document.addEventListener("DOMContentLoaded", function () {
    var track = document.querySelector("[data-ticker-track]");
    if (!track) return;

    var firstSegment = track.querySelector("[data-ticker-segment]");
    if (!firstSegment) return;

    /* One segment is exactly one full loop of the content (the track holds
       two identical segments back to back so the loop restart is never
       visible -- the animation only ever needs to travel the width of one
       segment, i.e. translateX(-50%) of the whole track). Sizing the
       duration off that width keeps the reading speed constant no matter
       how long a given story's ticker text ends up being. */
    function applyDuration() {
      var width = firstSegment.getBoundingClientRect().width;
      if (!width) return;
      var duration = width / TICKER_SPEED_PX_PER_SECOND;
      track.style.animationDuration = duration + "s";
    }

    applyDuration();
    window.addEventListener("resize", applyDuration);
  });
})();
