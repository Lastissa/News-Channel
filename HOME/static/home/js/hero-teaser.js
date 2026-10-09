(function () {
  "use strict";

  // Drives the hero's side "coming soon" carousel. Auto-plays only - no
  // prev/next/dots. One source serves both layouts (see base.css):
  //   - Desktop (.hero-teaser is 30vw beside the hero): slides are stacked
  //     with position:absolute, so this only needs to swap .is-active and the
  //     CSS crossfade does the rest; wrapping 0..N with a fade already reads
  //     as a continuous loop, no restart visible.
  //   - Mobile (.hero-teaser sits under the hero, detached from it): slides
  //     sit in normal flex flow, several visible at once, and .is-active
  //     genuinely changes a slide's flex-basis (bigger box), not just its
  //     scale. That resize is instant/non-transitioning on purpose, so the
  //     offsetLeft read right after toggling the class is already the real,
  //     final number - nothing to fight with an animating box size.
  //     Translating .teaser-track by that offset slides the whole strip so
  //     the newly-active slide lands in the larger spot, moving right to
  //     left as it advances.
  // offsetLeft is always 0 in the desktop layout (inset: 0 on every slide),
  // so the same translate call is a harmless no-op there.
  //
  // Endless loop (mobile): when the strip reaches the last original slide it
  // keeps sliding one more slot onto a clone of slide 0 - the same pictures
  // in the same order, one continued glide - and once that glide has painted
  // (0.6s transition + a small buffer) the index and transform snap back to
  // the real slide 0 with the transition switched off. The pixels are
  // identical in identical slots, so the reset is invisible and the strip
  // reads as "continues forever" instead of restarting.

  var teaser = document.getElementById("teaser-carousel");
  if (!teaser) return;

  var track = teaser.querySelector(".teaser-track");
  var originals = Array.prototype.slice.call(teaser.querySelectorAll(".teaser-slide"));
  if (!track || originals.length < 2) return;

  // A full copy of the set, marked and de-focusable. The desktop layout
  // hides them entirely (base.css); the mobile strip uses them as the
  // off-screen continuation of the slide left.
  var all = originals.concat(originals.map(function (slide) {
    var clone = slide.cloneNode(true);
    clone.setAttribute("data-clone", "true");
    clone.setAttribute("aria-hidden", "true");
    clone.tabIndex = -1;            /* stay clickable, drop out of tab order */
    track.appendChild(clone);
    return clone;
  }));
  var N = originals.length;

  var current = 0;
  var timer = null;
  var interval = parseInt(teaser.getAttribute("data-autoplay"), 10) || 4200;
  var reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function place() {
    track.style.transform = "translateX(-" + all[current].offsetLeft + "px)";
  }

  function isStrip() {
    return originals[1].offsetLeft !== 0;   /* flex flow (mobile) vs stacked (desktop) */
  }

  function setActive(index) {
    all[current].classList.remove("is-active");
    current = index;
    all[current].classList.add("is-active");
    place();
  }

  function goTo(index) {
    setActive((index + N) % N);   /* desktop: plain wrap, the crossfade hides the loop */
  }

  function next() {
    if (!isStrip()) { goTo(current + 1); return; }

    var target = current + 1;
    if (target < N) { setActive(target); return; }

    // Seam: target === N is the clone of slide 0. Glide onto it (the strip
    // keeps moving left over identical pictures), then swap back to the real
    // slide 0 once the glide has actually painted.
    setActive(N);
    window.setTimeout(function () {
      track.style.transition = "none";
      track.style.transform = "translateX(-" + originals[0].offsetLeft + "px)";
      void track.offsetWidth;               /* commit the inline "none" */
      track.style.transition = "";
      all[current].classList.remove("is-active");   /* clone of slide 0 */
      current = 0;
      all[0].classList.add("is-active");
    }, 680);
  }

  function start() {
    if (reducedMotion) return;
    stop();
    timer = window.setInterval(next, interval);
  }
  function stop() {
    if (timer) { window.clearInterval(timer); timer = null; }
  }

  // Keep the mobile strip aligned on resize/rotation (slide widths change)
  // and re-read the layout once base.css has finished applying (on slow
  // links the sheet can arrive after this deferred script has already run).
  window.addEventListener("resize", place);
  window.addEventListener("load", place);

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) stop(); else start();
  });

  place();
  start();
})();