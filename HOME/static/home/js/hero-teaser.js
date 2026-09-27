(function () {
  "use strict";

  // Drives the hero's side "coming soon" carousel. No prev/next/dots — it
  // only ever autoplays. The same logic serves both layouts (see base.css):
  //   - Desktop (.hero-teaser is 30vw beside the hero): slides are stacked
  //     with position:absolute, so this only needs to swap .is-active and
  //     crossfade opacity does the rest.
  //   - Mobile (.hero-teaser sits under the hero, detached from it): slides
  //     sit in normal flex flow, several visible at once, and .is-active
  //     genuinely changes a slide's flex-basis (bigger box), not just its
  //     scale. That resize is instant/non-transitioning on purpose, so the
  //     offsetLeft read right after toggling the class is already the real,
  //     final number — nothing to fight with an animating box size.
  //     Translating .teaser-track by that offset slides the whole strip so
  //     the newly-active slide lands in the larger spot, moving right to
  //     left as it advances.
  // offsetLeft is always 0 in the desktop layout (inset: 0 on every slide),
  // so the same translate call is a harmless no-op there.

  var teaser = document.getElementById("teaser-carousel");
  if (!teaser) return;

  var track = teaser.querySelector(".teaser-track");
  var slides = Array.prototype.slice.call(teaser.querySelectorAll(".teaser-slide"));
  if (!track || slides.length < 2) return;

  var current = 0;
  var timer = null;
  var interval = parseInt(teaser.getAttribute("data-autoplay"), 10) || 4200;
  var reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function place() {
    track.style.transform = "translateX(-" + slides[current].offsetLeft + "px)";
  }

  function goTo(index) {
    slides[current].classList.remove("is-active");
    current = (index + slides.length) % slides.length;
    slides[current].classList.add("is-active");
    place();
  }

  function next() { goTo(current + 1); }

  function start() {
    if (reducedMotion) return;
    stop();
    timer = window.setInterval(next, interval);
  }
  function stop() {
    if (timer) { window.clearInterval(timer); timer = null; }
  }

  // Keep the mobile strip aligned on resize/rotation (slide widths change).
  window.addEventListener("resize", place);

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) stop(); else start();
  });

  place();
  start();
})();
