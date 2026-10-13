/* Author handbook: optional slide reader.
   The long document is the default. This adds a small mode switch that turns
   the sections into a horizontal, snap-scrolling deck for authors who prefer
   to page through it. If this file fails to load, the page is still a complete,
   readable document. */
(function () {
  "use strict";

  var root = document.querySelector("[data-doc]");
  if (!root) return;

  var main = root.querySelector(".doc-main");
  var toggle = root.querySelector("[data-doc-toggle]");
  var bar = root.querySelector("[data-doc-slidebar]");
  var prev = root.querySelector("[data-doc-prev]");
  var next = root.querySelector("[data-doc-next]");
  var close = root.querySelector("[data-doc-close]");
  var status = root.querySelector("[data-doc-status]");

  var sections = main ? [].slice.call(main.querySelectorAll(".doc-section")) : [];
  if (!main || !toggle || sections.length < 2) return;

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");

  function isOn() {
    return root.classList.contains("doc--slides");
  }

  function slideWidth() {
    return main.clientWidth;
  }

  function current() {
    var w = slideWidth();
    if (!w) return 0;
    return Math.min(sections.length - 1, Math.max(0, Math.round(main.scrollLeft / w)));
  }

  function titleOf(section) {
    var h = section.querySelector("h2");
    return h ? h.textContent.trim() : "";
  }

  function paint() {
    if (!status) return;
    var i = current();
    var name = titleOf(sections[i]);
    status.textContent = "Slide " + (i + 1) + " of " + sections.length + (name ? " · " + name : "");
  }

  function go(i) {
    var w = slideWidth();
    i = Math.min(sections.length - 1, Math.max(0, i));
    main.scrollTo({
      left: i * w,
      behavior: reduced.matches ? "auto" : "smooth"
    });
  }

  function set(on) {
    root.classList.toggle("doc--slides", on);
    if (bar) bar.hidden = !on;
    toggle.setAttribute("aria-pressed", on ? "true" : "false");
    toggle.textContent = on ? "Close slides" : "Read as slides";
    if (on) {
      main.scrollLeft = 0;
      paint();
      if (close) close.focus();
    } else {
      sections[0].scrollIntoView({ block: "start", behavior: "auto" });
      toggle.focus();
    }
  }

  toggle.addEventListener("click", function () { set(!isOn()); });
  if (close) close.addEventListener("click", function () { set(false); });
  if (prev) prev.addEventListener("click", function () { go(current() - 1); });
  if (next) next.addEventListener("click", function () { go(current() + 1); });

  main.addEventListener("scroll", function () {
    if (!isOn()) return;
    window.requestAnimationFrame(paint);
  }, { passive: true });

  window.addEventListener("resize", function () {
    if (isOn()) paint();
  });

  document.addEventListener("keydown", function (event) {
    if (!isOn()) return;
    var tag = (event.target && event.target.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    if (event.key === "ArrowRight") { event.preventDefault(); go(current() + 1); }
    else if (event.key === "ArrowLeft") { event.preventDefault(); go(current() - 1); }
    else if (event.key === "Escape") { event.preventDefault(); set(false); }
  });
})();
