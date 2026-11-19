/* Marks each image as loaded or failed so the CSS shimmer (base.css) stops.
   Works for images already on the page, images that finish later, and images
   added afterwards (infinite feeds, htmx swaps). */
(function () {
  function loaded(img) { img.classList.add("is-loaded"); }
  function failed(img) { img.classList.add("is-loaded", "is-failed"); }

  function check(img) {
    if (img.complete) (img.naturalWidth ? loaded : failed)(img);
  }
  function sweep(root) {
    root.querySelectorAll("img:not(.is-loaded)").forEach(check);
  }

  document.addEventListener("load", function (event) {
    if (event.target.tagName === "IMG") loaded(event.target);
  }, true);
  document.addEventListener("error", function (event) {
    if (event.target.tagName === "IMG") failed(event.target);
  }, true);

  sweep(document);
  new MutationObserver(function (changes) {
    changes.forEach(function (change) {
      change.addedNodes.forEach(function (node) {
        if (node.nodeType !== 1) return;
        if (node.tagName === "IMG") check(node); else sweep(node);
      });
    });
  }).observe(document.body, { childList: true, subtree: true });
})();
