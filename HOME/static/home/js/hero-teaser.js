(function () {
  "use strict";

  /* Reader-driven advert rail (HOME/static/home/css/base.css). The track is a
     native horizontal scroll container with scroll snapping, so swipe,
     trackpad, shift+wheel and the keyboard already work without this file.
     On phones the focused advert grows and the other adverts stay small beside
     it. This script decides which advert is focused, keeps its arrows in sync,
     and gets out of the way while the reader is actually scrolling. There is
     deliberately no auto-advance and no numeric pager. */

  var teaser = document.getElementById("teaser-carousel");
  if (!teaser) return;

  var track = teaser.querySelector("[data-teaser-track]") || teaser.querySelector(".teaser-track");
  if (!track) return;

  var slides = Array.prototype.slice.call(track.querySelectorAll(".teaser-slide"));
  var controls = teaser.querySelector("[data-teaser-controls]");
  if (slides.length < 2) {
    if (controls) controls.hidden = true;
    return;
  }

  var prev = teaser.querySelector("[data-teaser-prev]");
  var next = teaser.querySelector("[data-teaser-next]");
  var reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var current = 0;
  var settleTimer = 0;
  var resizeFrame = 0;
  var programmaticUntil = 0;

  /* Find the snap position the browser will use for a slide. Most slides snap
     at their start, but the final phone advert snaps at its end so a focused
     last card is not left half outside the rail. */
  function snapPosition(slide) {
    var align = window.getComputedStyle(slide).scrollSnapAlign || "start";
    if (align.indexOf("end") !== -1) return slide.offsetLeft + slide.offsetWidth - track.clientWidth;
    if (align.indexOf("center") !== -1) return slide.offsetLeft + (slide.offsetWidth - track.clientWidth) / 2;
    return slide.offsetLeft;
  }

  function nearestIndex() {
    var left = track.scrollLeft;
    var best = 0;
    var bestDistance = Infinity;
    for (var i = 0; i < slides.length; i += 1) {
      var distance = Math.abs(snapPosition(slides[i]) - left);
      if (distance < bestDistance) {
        bestDistance = distance;
        best = i;
      }
    }
    return best;
  }

  function updateButtons(index) {
    if (prev) prev.disabled = index <= 0;
    if (next) next.disabled = index >= slides.length - 1;
  }

  function setActive(index) {
    updateButtons(index);
    if (index === current) return false;
    slides[current].classList.remove("is-active");
    current = index;
    slides[current].classList.add("is-active");
    return true;
  }

  /* Move the rail only as far as needed to show the whole focused advert. The
     phone cards have different widths, so this is intentionally not a jump to
     offsetLeft: a middle advert can become focused in place with a small one
     still peeking on either side. */
  function ensureVisible(index, behavior) {
    var slide = slides[index];
    var viewLeft = track.scrollLeft;
    var viewRight = viewLeft + track.clientWidth;
    var left = slide.offsetLeft;
    var right = left + slide.offsetWidth;
    var align = window.getComputedStyle(slide).scrollSnapAlign || "start";
    var target = null;

    if (align.indexOf("end") !== -1) {
      target = right - track.clientWidth;
    } else if (left < viewLeft) {
      target = left;
    } else if (right > viewRight) {
      target = right - track.clientWidth;
    }
    if (target === null) return;

    target = Math.max(0, Math.min(target, track.scrollWidth - track.clientWidth));
    if (Math.abs(target - track.scrollLeft) < 1) return;

    if (typeof track.scrollTo === "function") {
      track.scrollTo({ left: target, behavior: behavior || "auto" });
    } else {
      track.scrollLeft = target;
    }
  }

  function goTo(index, behavior) {
    var target = Math.max(0, Math.min(slides.length - 1, index));
    setActive(target);
    /* Ignore scroll events while the arrow's smooth scroll is still moving:
       an intermediate position can look closer to a different slide. */
    programmaticUntil = Date.now() + 500;
    /* setActive changes the focused card's width; read the new offsets now so
       the scroll target is based on the layout the reader is about to see. */
    ensureVisible(target, behavior || (reducedMotion ? "auto" : "smooth"));
  }

  if (prev) prev.addEventListener("click", function () { goTo(current - 1); });
  if (next) next.addEventListener("click", function () { goTo(current + 1); });

  function settle() {
    settleTimer = 0;
    if (Date.now() < programmaticUntil) {
      updateButtons(current);
      return;
    }
    var index = nearestIndex();
    if (setActive(index)) ensureVisible(index, "auto");
  }

  track.addEventListener("scroll", function () {
    if (settleTimer) window.clearTimeout(settleTimer);
    settleTimer = window.setTimeout(settle, 160);
  }, { passive: true });

  track.addEventListener("keydown", function (event) {
    if (event.target !== track) return;
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      goTo(current - 1);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      goTo(current + 1);
    } else if (event.key === "Home") {
      event.preventDefault();
      goTo(0);
    } else if (event.key === "End") {
      event.preventDefault();
      goTo(slides.length - 1);
    }
  });

  function keepCurrentVisible() {
    if (resizeFrame) window.cancelAnimationFrame(resizeFrame);
    resizeFrame = window.requestAnimationFrame(function () {
      resizeFrame = 0;
      updateButtons(current);
      ensureVisible(current, "auto");
    });
  }

  window.addEventListener("resize", keepCurrentVisible);
  window.addEventListener("load", keepCurrentVisible);

  if (typeof window.ResizeObserver === "function") {
    new window.ResizeObserver(keepCurrentVisible).observe(track);
  }

  teaser.classList.add("is-scroll-ready");
  updateButtons(current);
})();
