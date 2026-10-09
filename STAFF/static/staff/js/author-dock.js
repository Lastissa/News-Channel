(function () {
  "use strict";

  // Author dock on the portfolio page. The links show first (they pop in via
  // CSS), then fold into the author's picture after a few seconds so they stop
  // covering the content. Hover, focus or a tap on the picture reopens them.
  var dock = document.querySelector("[data-author-dock]");
  if (!dock) return;
  var toggle = dock.querySelector("[data-dock-toggle]");
  if (!toggle) return;

  var reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var finePointer = window.matchMedia && window.matchMedia("(hover: hover) and (pointer: fine)").matches;
  var FOLD_AFTER = 4500;      // first fold, after the intro has played
  var LEAVE_DELAY = 700;      // fold again after the pointer leaves
  var timer = null;

  // Reduced motion: leave the links open, no launcher, nothing moving.
  if (reducedMotion) return;

  dock.classList.add("is-js");
  toggle.hidden = false;

  function clear() { if (timer) { window.clearTimeout(timer); timer = null; } }

  function open() {
    clear();
    dock.classList.remove("is-folded");
    toggle.classList.remove("is-nudge");
    toggle.setAttribute("aria-expanded", "true");
  }

  function fold() {
    clear();
    if (dock.contains(document.activeElement) && document.activeElement !== toggle) return;
    dock.classList.add("is-folded");
    toggle.classList.add("is-nudge");
    toggle.setAttribute("aria-expanded", "false");
  }

  function foldLater(delay) {
    clear();
    timer = window.setTimeout(fold, delay);
  }

  // The intro class only drives the entrance animation, drop it once it is done.
  window.setTimeout(function () { dock.classList.remove("is-intro"); }, 2500);

  toggle.addEventListener("click", function () {
    if (dock.classList.contains("is-folded")) {
      open();
      if (!finePointer) foldLater(6000);
    } else {
      fold();
    }
  });

  if (finePointer) {
    dock.addEventListener("mouseenter", function () { if (dock.classList.contains("is-folded") || timer) open(); });
    dock.addEventListener("mouseleave", function () { foldLater(LEAVE_DELAY); });
  }
  dock.addEventListener("focusin", function () { if (dock.classList.contains("is-folded")) open(); });
  dock.addEventListener("focusout", function () { foldLater(LEAVE_DELAY); });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !dock.classList.contains("is-folded")) { fold(); toggle.focus(); }
  });

  // tap anywhere else on touch screens closes it
  document.addEventListener("pointerdown", function (event) {
    if (!dock.contains(event.target) && !dock.classList.contains("is-folded") && !finePointer) fold();
  });

  foldLater(FOLD_AFTER);
})();
