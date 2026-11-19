(function () {
  "use strict";

  /* Advert rail (HOME/static/home/css/base.css). The track is a native
     horizontal scroll container with scroll snapping, so swipe, trackpad,
     shift+wheel and the keyboard always work without this file. This script
     decides which advert is focused, keeps the arrows in sync, and advances
     the rail on a timer. Manual input wins: dragging, scrolling or using the
     arrows pauses the timer, then it resumes after the reader has been idle
     -- hovering or simply leaving focus on a button does not stop it forever.
     Every step scrolls to the advert's snap point, so the rail visibly moves
     on both desktop and phones. On phones the focused advert grows and the
     other adverts stay small beside it. There is deliberately no numeric pager. */

  var teaser = document.getElementById("teaser-carousel");
  if (!teaser) return;

  var track = teaser.querySelector("[data-teaser-track]") || teaser.querySelector(".teaser-track");
  if (!track) return;

  var slides = Array.prototype.slice.call(track.querySelectorAll(".teaser-slide"));
  var controls = teaser.querySelector("[data-teaser-controls]");
  var trackedViews = {};

  /* A slide with data-ad-view is a real, referenced advert. Request its 1x1
     pixel only when it becomes the focused slide, and only once per page
     load. Bots are filtered server-side; this keeps a long rail from counting
     every off-screen advert as seen. */
  function trackView(slide) {
    if (!slide) return;
    var url = slide.getAttribute("data-ad-view");
    if (!url || trackedViews[url]) return;
    trackedViews[url] = true;
    var pixel = new Image(1, 1);
    pixel.alt = "";
    pixel.src = url + (url.indexOf("?") === -1 ? "?" : "&") + "t=" + Date.now();
  }

  if (slides.length < 2) {
    trackView(slides[0]);
    if (controls) controls.hidden = true;
    return;
  }

  var prev = teaser.querySelector("[data-teaser-prev]");
  var next = teaser.querySelector("[data-teaser-next]");
  var reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var autoDelay = parseInt(teaser.getAttribute("data-autoplay"), 10) || 6000;
  var resumeDelay = parseInt(teaser.getAttribute("data-resume-after"), 10) || 4500;
  var current = 0;
  var settleTimer = 0;
  var resizeFrame = 0;
  var autoTimer = 0;
  var resumeTimer = 0;
  var programmaticPoll = 0;
  var programmaticScroll = false;
  var dragging = false;
  var manualPauseUntil = 0;

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
    trackView(slides[current]);
    return true;
  }

  /* Always move to the focused advert's snap point. Checking "is it already
     visible?" is what made the phone rail look frozen: a middle card could
     become active without the track moving at all. A real scroll keeps the
     desktop slides and the phone carousel visibly advancing.

     Snapping is suspended for the duration of a programmatic move. Mandatory
     snapping (and scroll-snap-stop) can otherwise re-snap a smooth scroll to
     the wrong card, which made the rail appear stuck even while the active
     class changed. Scroll events are ignored until we actually reach the
     target, so the manual settle logic cannot pull the rail back. */
  function scrollToSlide(index, behavior) {
    var slide = slides[index];
    var max = Math.max(0, track.scrollWidth - track.clientWidth);
    var target = Math.max(0, Math.min(snapPosition(slide), max));
    if (Math.abs(target - track.scrollLeft) < 1) return;

    if (programmaticPoll) window.clearTimeout(programmaticPoll);
    programmaticScroll = true;
    var previousSnap = track.style.scrollSnapType;
    var started = Date.now();
    track.style.scrollSnapType = "none";

    if (typeof track.scrollTo === "function") {
      track.scrollTo({ left: target, behavior: behavior || (reducedMotion ? "auto" : "smooth") });
    } else {
      track.scrollLeft = target;
    }

    function finish() {
      if (Math.abs(track.scrollLeft - target) < 2 || Date.now() - started > 1600) {
        track.style.scrollSnapType = previousSnap;
        programmaticScroll = false;
        programmaticPoll = 0;
        return;
      }
      programmaticPoll = window.setTimeout(finish, 40);
    }
    programmaticPoll = window.setTimeout(finish, 40);
  }

  function goTo(index, behavior) {
    var target = Math.max(0, Math.min(slides.length - 1, index));
    setActive(target);
    /* setActive changes the focused card's width; read the new offset now so
       the scroll target matches the layout the reader is about to see. */
    scrollToSlide(target, behavior || (reducedMotion ? "auto" : "smooth"));
  }

  function clearAutoTimer() {
    if (autoTimer) {
      window.clearTimeout(autoTimer);
      autoTimer = 0;
    }
  }

  function autoAllowed() {
    /* Reduced motion switches the step to an instant jump, not to a stopped
       rail: readers who ask for less animation still get the adverts rotating. */
    return !document.hidden && !dragging && Date.now() >= manualPauseUntil;
  }

  function queueNext() {
    clearAutoTimer();
    if (!autoAllowed()) return;
    autoTimer = window.setTimeout(function () {
      if (!autoAllowed()) return;
      /* Loop back to the first advert instead of stopping at the last one. */
      goTo((current + 1) % slides.length);
      queueNext();
    }, autoDelay);
  }

  function syncAuto() {
    if (!autoAllowed()) {
      clearAutoTimer();
      return;
    }
    if (!autoTimer) queueNext();
  }

  /* Deliberate input gets a short quiet window, then the timer takes over
     again from the advert the reader left on screen. Hover/focus are not
     permanent pauses, so the rail keeps moving like it used to. */
  function pauseForReader() {
    manualPauseUntil = Date.now() + resumeDelay;
    clearAutoTimer();
    if (resumeTimer) window.clearTimeout(resumeTimer);
    resumeTimer = window.setTimeout(function () {
      resumeTimer = 0;
      manualPauseUntil = 0;
      syncAuto();
    }, resumeDelay);
  }

  if (prev) prev.addEventListener("click", function () { pauseForReader(); goTo(current - 1); });
  if (next) next.addEventListener("click", function () { pauseForReader(); goTo(current + 1); });

  function settle() {
    settleTimer = 0;
    if (programmaticScroll) return;
    var index = nearestIndex();
    if (setActive(index)) scrollToSlide(index, "auto");
  }

  track.addEventListener("scroll", function () {
    /* A scroll while our own smooth move is running is not reader input. */
    if (programmaticScroll) return;
    pauseForReader();
    if (settleTimer) window.clearTimeout(settleTimer);
    settleTimer = window.setTimeout(settle, 160);
  }, { passive: true });

  track.addEventListener("keydown", function (event) {
    if (event.target !== track) return;
    var handled = true;
    if (event.key === "ArrowLeft") {
      goTo(current - 1);
    } else if (event.key === "ArrowRight") {
      goTo(current + 1);
    } else if (event.key === "Home") {
      goTo(0);
    } else if (event.key === "End") {
      goTo(slides.length - 1);
    } else {
      handled = false;
    }
    if (handled) {
      event.preventDefault();
      pauseForReader();
    }
  });

  /* Swipe and drag are native scrolling: never preventDefault here, just hold
     the timer briefly while the reader is touching the rail. */
  function beginDrag() {
    dragging = true;
    pauseForReader();
  }
  function endDrag() {
    dragging = false;
    syncAuto();
  }
  teaser.addEventListener("pointerdown", beginDrag);
  teaser.addEventListener("pointerup", endDrag);
  teaser.addEventListener("pointercancel", endDrag);
  teaser.addEventListener("touchstart", beginDrag, { passive: true });
  teaser.addEventListener("touchend", endDrag, { passive: true });
  teaser.addEventListener("touchcancel", endDrag, { passive: true });

  teaser.addEventListener("focusin", pauseForReader);
  teaser.addEventListener("focusout", syncAuto);

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) clearAutoTimer();
    else syncAuto();
  });

  function keepCurrentVisible() {
    if (resizeFrame) window.cancelAnimationFrame(resizeFrame);
    resizeFrame = window.requestAnimationFrame(function () {
      resizeFrame = 0;
      updateButtons(current);
      scrollToSlide(current, "auto");
    });
  }

  window.addEventListener("resize", keepCurrentVisible);
  window.addEventListener("load", keepCurrentVisible);

  if (typeof window.ResizeObserver === "function") {
    new window.ResizeObserver(keepCurrentVisible).observe(track);
  }

  teaser.classList.add("is-scroll-ready");
  updateButtons(current);
  trackView(slides[current]);
  syncAuto();
})();
