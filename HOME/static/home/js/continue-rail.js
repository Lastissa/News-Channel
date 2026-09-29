/* PICK UP WHAT YOU WERE READING -- 3D rail
   (HOME/templates/HOME/partials/continue_rail.html, .continue-rail)

   This file deliberately owns as little as possible. The rail is a real
   horizontal scroller in the markup, so native momentum fling on touch,
   scroll snapping, keyboard scrolling and focus order are all handled by the
   platform. All this adds on top is:

     1. per-card depth: --d (signed distance from the centre of the rail) and
        --a (that distance as a 0..1 magnitude), plus an explicit z-index so
        nearer cards paint over further ones. base.css does the rest with
        calc() -- the whole look is retunable from that one block.
     2. pointer parallax and tilt on a mouse, sheen included.
     3. prev/next buttons and arrow-key paging, and click-drag to scroll for
        mouse users, since a scroller is otherwise mouse-hostile.
     4. the entrance -> assemble sequence, so the row arrives flat and then
        takes up its 3D pose.

   Reduced motion is not a bail-out, it is a downgrade. The rail is already a
   complete, readable, keyboard-navigable scroller of story links without any
   of the decoration, so a reader who asks for less motion gets the same
   working row with the 3D, the entrance, the parallax and the drag all left
   out -- but keeps the paging buttons, which stay useful as controls and only
   stop animating. */
(function () {
  "use strict";

  function clamp(value, low, high) {
    return value < low ? low : value > high ? high : value;
  }

  function init() {
    var section = document.querySelector("[data-continue-rail]");
    if (!section) return;

    var stage = section.querySelector("[data-continue-stage]");
    var rail = section.querySelector("[data-continue-track]");
    if (!stage || !rail) return;

    var cards = Array.prototype.slice.call(rail.querySelectorAll(".continue-card"));
    if (!cards.length) return;

    /* --d / --a go on the SLOT, not the card: base.css derives --lift from
       --a on the slot (the contact shadow and the floor bloom are painted by
       the slot's own pseudo elements) and the card inherits from there. */
    var slots = cards.map(function (card) { return card.parentNode; });

    var MOTION = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var EASE = MOTION ? "smooth" : "auto";

    var prevBtn = section.querySelector("[data-continue-prev]");
    var nextBtn = section.querySelector("[data-continue-next]");

    /* ---------- 1. depth ---------- */

    /* Signed offset of each slot's centre from the centre of the visible rail
       window, in "one card" units: 0 dead centre, -1 one card to the left. */
    function measure() {
      var railBox = rail.getBoundingClientRect();
      var mid = railBox.left + railBox.width / 2;
      return slots.map(function (slot) {
        var box = slot.getBoundingClientRect();
        return (box.left + box.width / 2 - mid) / (box.width || 1);
      });
    }

    function paint() {
      var offsets = measure();
      /* One card pitch. Using the gap-inclusive distance between neighbouring
         centres rather than a card's own width keeps |d| at 1 for the card one
         step away at every viewport size. With a single card there is no
         neighbour, so fall back to its own width. */
      var step = offsets.length > 1
        ? Math.abs(offsets[1] - offsets[0])
        : (cards[0].getBoundingClientRect().width || 1);
      if (!step) return;

      for (var i = 0; i < cards.length; i++) {
        var d = clamp(offsets[i] / step, -1.5, 1.5);
        var a = Math.min(1, Math.abs(d));
        slots[i].style.setProperty("--d", d.toFixed(4));
        slots[i].style.setProperty("--a", a.toFixed(4));
        /* A flattened 3D context sorts by z-index, not by Z, so depth has to
           be restated here or the far cards paint over the near ones. */
        cards[i].style.zIndex = String(100 - Math.round(a * 100));
      }
      syncArrows();
    }

    /* ---------- 2. scroll plumbing ---------- */

    function scrollable() {
      return rail.scrollWidth - rail.clientWidth > 2;
    }

    function syncArrows() {
      if (!prevBtn || !nextBtn) return;
      var any = scrollable();
      if (section.classList.contains("is-assembled")) section.classList.toggle("has-overflow", any);
      prevBtn.disabled = !any || rail.scrollLeft <= 2;
      nextBtn.disabled = !any || rail.scrollLeft >= rail.scrollWidth - rail.clientWidth - 2;
    }

    function pitch() {
      var slot = slots[0];
      var gap = parseFloat(window.getComputedStyle(rail).columnGap || "0") || 0;
      return slot.getBoundingClientRect().width + gap;
    }

    /* Left-most scroll position that puts this slot in the middle. Clamped,
       because the first and last cards physically cannot reach the centre
       when there is not enough rail left over. */
    function centreOf(slot) {
      var target = slot.offsetLeft + slot.offsetWidth / 2 - rail.clientWidth / 2;
      return Math.max(0, Math.min(target, rail.scrollWidth - rail.clientWidth));
    }

    function pageBy(direction) {
      rail.scrollBy({ left: direction * pitch(), behavior: EASE });
    }

    var queued = false;
    function schedule() {
      if (!MOTION || queued) return;
      queued = true;
      window.requestAnimationFrame(function () {
        queued = false;
        paint();
      });
    }

    rail.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    if (window.ResizeObserver) {
      /* card width is clamp()-driven, so a font swap or a late image can
         change the pitch without the window itself changing size */
      new window.ResizeObserver(schedule).observe(rail);
    }

    if (prevBtn) prevBtn.addEventListener("click", function () { pageBy(-1); });
    if (nextBtn) nextBtn.addEventListener("click", function () { pageBy(1); });

    /* ---------- 3. keyboard ---------- */

    rail.addEventListener("keydown", function (event) {
      var handled = true;
      switch (event.key) {
        case "ArrowLeft":  pageBy(-1); break;
        case "ArrowRight": pageBy(1);  break;
        case "Home":       rail.scrollTo({ left: 0, behavior: EASE }); break;
        case "End":        rail.scrollTo({ left: rail.scrollWidth, behavior: EASE }); break;
        default: handled = false;
      }
      if (handled) event.preventDefault();
    });

    /* ---------- 4. click-drag for mouse users ----------
       Touch already has momentum scrolling; a mouse on a scroller has
       nothing. Only a left mouse button counts -- a right-button drag is a
       context menu, and pen/touch are left to the platform. Skipped
       entirely under reduced motion, where there is no 3D to throw around
       and the snap is better left alone. */

    var armed = false, dragging = false, startX = 0, startScroll = 0, swallowClick = false;

    if (MOTION) {
      rail.addEventListener("pointerdown", function (event) {
        if (event.pointerType !== "mouse" || event.button !== 0) return;
        armed = true;
        dragging = false;
        startX = event.clientX;
        startScroll = rail.scrollLeft;
      });

      window.addEventListener("pointermove", function (event) {
        if (!armed || event.pointerType !== "mouse") return;
        var dx = event.clientX - startX;
        if (!dragging) {
          if (Math.abs(dx) < 5) return;          /* let small movements stay clicks */
          dragging = true;
          /* Snap would yank the rail back to a slot the moment the drag ended,
             so hand snapping over to the settle below for the duration. */
          rail.style.scrollSnapType = "none";
          rail.classList.add("is-grabbing");
          try { rail.setPointerCapture(event.pointerId); } catch (err) { /* not fatal */ }
        }
        rail.scrollLeft = startScroll - dx;
      }, { passive: true });

      function endDrag() {
        if (!armed) return;
        armed = false;
        if (!dragging) return;
        dragging = false;
        swallowClick = true;
        rail.classList.remove("is-grabbing");
        var nearest = 0, nearestDist = Infinity;
        for (var i = 0; i < slots.length; i++) {
          var left = centreOf(slots[i]);
          var dist = Math.abs(left - rail.scrollLeft);
          if (dist < nearestDist) { nearestDist = dist; nearest = left; }
        }
        rail.scrollTo({ left: nearest, behavior: EASE });
        window.setTimeout(function () { rail.style.scrollSnapType = ""; schedule(); }, 450);
      }

      window.addEventListener("pointerup", endDrag);
      window.addEventListener("pointercancel", endDrag);
    }

    /* A drag that ends on a link must not also follow the link. */
    rail.addEventListener("click", function (event) {
      if (!swallowClick) return;
      swallowClick = false;
      event.preventDefault();
      event.stopPropagation();
    }, true);

    /* ---------- 5. pointer parallax and tilt ---------- */

    stage.addEventListener("pointermove", function (event) {
      if (!MOTION || event.pointerType !== "mouse") return;
      var box = stage.getBoundingClientRect();
      if (!box.width || !box.height) return;
      var nx = ((event.clientX - box.left) / box.width) * 2 - 1;
      var ny = ((event.clientY - box.top) / box.height) * 2 - 1;
      stage.style.setProperty("--px", nx.toFixed(3));
      stage.style.setProperty("--py", ny.toFixed(3));
      stage.style.setProperty("--tiltx", ny.toFixed(3));
    });

    stage.addEventListener("pointerleave", function () {
      if (!MOTION) return;
      stage.style.setProperty("--px", "0");
      stage.style.setProperty("--py", "0");
      stage.style.setProperty("--tiltx", "0");
    });

    /* ---------- 6. entrance, then assemble into 3D ---------- */

    var assembled = false;
    function assemble() {
      if (assembled) return;
      assembled = true;
      stage.classList.remove("is-entering");
      /* Two frames: one for the flat state to be committed, one so the
         transition actually has a start value to animate from. */
      window.requestAnimationFrame(function () {
        window.requestAnimationFrame(function () {
          paint();
          stage.classList.add("is-3d", "is-assembling");
          section.classList.add("is-assembled");
          window.setTimeout(function () {
            stage.classList.remove("is-assembling");
            schedule();
          }, 1000);
        });
      });
    }

    if (MOTION) {
      stage.classList.add("is-entering");
      var last = cards[cards.length - 1];
      /* Belt and braces: if animationend never arrives (a throttled tab, a
         browser that skips the animation) the rail must still end up 3D
         rather than stranded flat and unanimated. */
      var guard = window.setTimeout(assemble, 1800);
      last.addEventListener("animationend", function () {
        window.clearTimeout(guard);
        assemble();
      });
      paint();
    } else {
      /* No motion: never add is-3d, so every .continue-stage.is-3d rule in
         base.css stays unmatched and the row is a plain flat scroller. The
         arrow state is still synced once so the buttons are not lying about
         whether there is anywhere to go. */
      section.classList.add("is-assembled");
      syncArrows();
      rail.addEventListener("scroll", syncArrows, { passive: true });
      window.addEventListener("resize", syncArrows);
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
