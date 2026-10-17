/* Interactions for the story table of contents.
   The list itself is built by BLOG.views.enhance_story_body and styled by the
   .story-toc block in HOME/static/home/css/base.css. The outer "TABLE OF
   CONTENT" row is a native <details>, so it needs no script; the script covers
   the two things a plain anchor cannot do well here:

     1. the per-section chevrons that open and close sub-lists, and
     2. jump links, so a click glides to the section and then briefly washes
        the heading it landed on.

   Clicks are delegated from the document, so the news editor's live preview,
   which re-renders the whole list on every keystroke, keeps working without
   re-binding anything. */
(function () {
  "use strict";

  var TARGET_CLASS = "story-toc-target";
  var HIGHLIGHT_MS = 1600;
  var highlightTimer = null;

  function prefersReducedMotion() {
    return window.matchMedia
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  /*  The box that actually scrolls this row: the window for a story page, or
      the preview pane inside the news editor. */
  function scrollContainer(element) {
    var node = element.parentElement;
    while (node) {
      var overflowY = window.getComputedStyle(node).overflowY;
      if (/(auto|scroll|overlay)/.test(overflowY) && node.scrollHeight > node.clientHeight) {
        return node;
      }
      node = node.parentElement;
    }
    return document.scrollingElement || document.documentElement;
  }

  /*  Wash the heading the reader just landed on, then clear it. Applied with a
      class plus a timer rather than a CSS animation so it still shows when the
      reader has asked for reduced motion (the global reduce-motion rule would
      collapse an animation to nothing). */
  function highlight(element) {
    var shown = document.querySelectorAll("." + TARGET_CLASS);
    for (var i = 0; i < shown.length; i++) shown[i].classList.remove(TARGET_CLASS);
    element.classList.add(TARGET_CLASS);
    if (highlightTimer) window.clearTimeout(highlightTimer);
    highlightTimer = window.setTimeout(function () {
      element.classList.remove(TARGET_CLASS);
      highlightTimer = null;
    }, HIGHLIGHT_MS);
  }

  function followLink(link, event) {
    var href = link.getAttribute("href") || "";
    if (href.charAt(0) !== "#" || href.length < 2) return;
    var target = document.getElementById(href.slice(1));
    if (!target) return;

    /*  Take over from the browser so the glide and the wash behave the same in
        the story page and inside the editor's scrollable preview pane. */
    event.preventDefault();
    target.scrollIntoView({
      behavior: prefersReducedMotion() ? "auto" : "smooth",
      block: "start",
    });
    highlight(target);
    if (window.history && window.history.replaceState) {
      window.history.replaceState(null, "", href);
    }
  }

  document.addEventListener("click", function (event) {
    var link = event.target.closest && event.target.closest(".story-toc-link");
    if (link) {
      followLink(link, event);
      return;
    }

    var button = event.target.closest && event.target.closest(".story-toc-branch");
    if (!button) return;

    var item = button.closest(".story-toc-item");
    var children = item && item.querySelector(":scope > .story-toc-children");
    if (!children) return;

    var isOpen = button.getAttribute("aria-expanded") === "true";
    var scroller = scrollContainer(button);
    var beforeTop = button.getBoundingClientRect().top;

    button.setAttribute("aria-expanded", isOpen ? "false" : "true");
    if (isOpen) {
      children.setAttribute("hidden", "");
    } else {
      children.removeAttribute("hidden");
    }

    /*  Opening or closing a branch changes the section's height. Left alone,
        the browser's scroll anchoring can re-anchor on whatever is below the
        list and yank the page by the exact height that changed, so the row the
        reader just clicked flies off the screen. Pin the clicked chevron to
        its precise viewport position instead: the row never moves under the
        reader, and nothing animates. "instant" keeps the global
        scroll-behavior: smooth from animating the correction, and running it
        twice (now and next frame) also undoes any anchoring the browser
        applied on its own. */
    function pin() {
      var delta = button.getBoundingClientRect().top - beforeTop;
      if (!delta) return;
      scroller.scrollTo({
        top: scroller.scrollTop + delta,
        left: scroller.scrollLeft,
        behavior: "instant",
      });
    }
    pin();
    window.requestAnimationFrame(pin);
  });
})();
