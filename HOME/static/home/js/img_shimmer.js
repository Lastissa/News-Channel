/* Marks each image as loaded or failed so the CSS shimmer (base.css) stops.
   Works for images already on the page, images that finish later, and images
   added afterwards (infinite feeds, htmx swaps). */
(function () {
  function loaded(img) { img.classList.remove("is-failed"); img.classList.add("is-loaded"); }
  function failed(img) { img.classList.add("is-loaded", "is-failed"); }

  function track(img) { img.dataset.shimmerSrc = img.getAttribute("src") || ""; }

  function check(img) {
    if (img.complete) (img.naturalWidth ? loaded : failed)(img);
  }

  /* Several widgets reuse one <img> for previews, viewer slides and avatar
     edits. Clear the previous result when its src changes; otherwise an old
     error leaves .is-failed on the element and the next, perfectly good
     picture stays hidden by base.css. */
  function reset(img) {
    img.classList.remove("is-loaded", "is-failed");
    track(img);
    check(img);
  }

  function sweep(root) {
    root.querySelectorAll("img:not(.is-loaded)").forEach(function (img) {
      track(img);
      check(img);
    });
  }

  document.addEventListener("load", function (event) {
    if (event.target.tagName === "IMG") loaded(event.target);
  }, true);
  document.addEventListener("error", function (event) {
    if (event.target.tagName !== "IMG") return;
    var img = event.target;
    /* An error from a src we have already replaced must not hide the new one. */
    if (img.dataset.shimmerSrc && img.dataset.shimmerSrc !== (img.getAttribute("src") || "")) return;
    failed(img);
  }, true);

  sweep(document);
  new MutationObserver(function (changes) {
    changes.forEach(function (change) {
      if (change.type === "attributes") {
        if (change.target.tagName === "IMG" && change.attributeName === "src") reset(change.target);
        return;
      }
      change.addedNodes.forEach(function (node) {
        if (node.nodeType !== 1) return;
        if (node.tagName === "IMG") { track(node); check(node); } else sweep(node);
      });
    });
  }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["src"] });
})();
