(function () {
  "use strict";

  /* Continue reading popup (HOME/partials/continue_popup.html, home page).
     Opens a short delay after the page loads, then stays quiet for this page's
     cooldown: 12 hours on the home page and 1 hour on a story page, tracked in
     localStorage under a per-scope key. Near full-screen
     sheet: full width, touches the bottom, small margin at the top. The
     blurred backdrop shows through that strip; tapping the strip, the close
     button or Escape dismisses it.

     Signed in readers get the personalised feed. Page 1 is server rendered;
     this script loads page 2+ from home:continue_feed as the reader scrolls
     the sheet, showing a skeleton loader while a slice is in flight. The
     next page number comes back in the X-Continue-Next-Page header, exactly
     like the portfolio feed. */

  var popup = document.querySelector("[data-continue-popup]");
  if (!popup) return;

  /* The cooldown and the storage key both depend on the page: home shows at
     most every 12 hours, a story page at most every hour (set by the view on
     data-continue-cooldown, in milliseconds). The scope is part of the key so
     one context's cooldown never suppresses the other. */
  var SCOPE = popup.getAttribute("data-continue-scope") || "home";
  var COOLDOWN_MS = parseInt(popup.getAttribute("data-continue-cooldown"), 10);
  if (!isFinite(COOLDOWN_MS) || COOLDOWN_MS <= 0) COOLDOWN_MS = 12 * 60 * 60 * 1000;
  var STORAGE_KEY = "abureport-continue-popup-state:" + SCOPE;
  var DELAY_MS = 6000;
  var isGuest = popup.hasAttribute("data-guest");
  var isOpen = false;

  function readState() {
    try { return localStorage.getItem(STORAGE_KEY); } catch (e) { return null; }
  }
  function writeState(value) {
    try { localStorage.setItem(STORAGE_KEY, value); } catch (e) { /* storage off, ignore */ }
  }

  var state = readState();
  if (state && Number(state) > Date.now()) return; // still inside this page's cooldown

  var closeBtn = popup.querySelector("[data-continue-close]");
  var backdrop = popup.querySelector("[data-continue-backdrop]");
  var sheet = popup.querySelector(".continue-popup-sheet");
  var lastFocus = null;

  function open() {
    if (isOpen) return;
    isOpen = true;
    lastFocus = document.activeElement;

    /* Never stack the anonymous newsletter bottom-sheet on top of this one. */
    var newsletter = document.querySelector(".newsletter-popup.is-visible");
    if (newsletter) newsletter.classList.remove("is-visible");

    popup.classList.add("is-visible");
    popup.setAttribute("aria-hidden", "false");
    document.documentElement.classList.add("continue-popup-locked");
    /* Force a reflow so the browser sees the starting (hidden) state, then add
       the class the transition animates to. A queued requestAnimationFrame can
       simply never fire while the tab is not being painted, which would leave
       the sheet stuck at opacity 0. */
    void popup.offsetWidth;
    popup.classList.add("is-open");
    if (closeBtn) closeBtn.focus({ preventScroll: true });
    writeState(String(Date.now() + COOLDOWN_MS));
    startFeed();
  }

  function close() {
    if (!isOpen) return;
    isOpen = false;
    popup.classList.remove("is-open");
    document.documentElement.classList.remove("continue-popup-locked");
    popup.setAttribute("aria-hidden", "true");
    window.setTimeout(function () { popup.classList.remove("is-visible"); }, 320);
    if (lastFocus && typeof lastFocus.focus === "function") {
      try { lastFocus.focus({ preventScroll: true }); } catch (e) {}
    }
  }

  popup.addEventListener("click", function (event) {
    if (event.target.closest("[data-continue-close]")) { close(); return; }
    if (event.target === backdrop) close();
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && isOpen) close();
  });

  /* Keep Tab inside the sheet while it is open. */
  if (sheet) {
    sheet.addEventListener("keydown", function (event) {
      if (event.key !== "Tab") return;
      var els = sheet.querySelectorAll('a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])');
      if (els.length < 2) return;
      var first = els[0];
      var last = els[els.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
  }

  /* Personalised feed: load more as the reader scrolls inside the sheet. */
  var feedUrl = popup.dataset.feedUrl;
  var nextPage = popup.dataset.nextPage || "";
  var items = popup.querySelector("[data-continue-items]");
  var sentinel = popup.querySelector("[data-continue-sentinel]");
  var skeleton = popup.querySelector("[data-continue-skeleton]");
  var endMessage = popup.querySelector("[data-continue-end]");
  var status = popup.querySelector("[data-continue-status]");
  var scrollRoot = popup.querySelector("[data-continue-scroll]");
  var observer = null;
  var loading = false;
  var feedStarted = false;

  function requestNextPage() {
    if (loading || !nextPage || !items) return;
    loading = true;
    if (sentinel) sentinel.hidden = true;
    if (skeleton) skeleton.hidden = false;
    if (status) status.textContent = "Loading more stories.";

    var pageQuery = "page=" + encodeURIComponent(nextPage);
    var requestUrl = feedUrl + (feedUrl.indexOf("?") === -1 ? "?" : "&") + pageQuery;

    fetch(requestUrl, {
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" },
      cache: "no-store"
    })
      .then(function (response) {
        if (!response.ok) throw new Error("bad response");
        return response.text().then(function (html) {
          items.insertAdjacentHTML("beforeend", html);
          nextPage = response.headers.get("X-Continue-Next-Page") || "";
          if (nextPage) {
            if (sentinel) { sentinel.hidden = false; if (observer) observer.observe(sentinel); }
          } else {
            if (sentinel && observer) observer.unobserve(sentinel);
            if (endMessage) endMessage.hidden = false;
          }
          if (status) status.textContent = nextPage ? "More stories loaded." : "All stories loaded.";
        });
      })
      .catch(function () {
        if (status) status.textContent = "More stories could not be loaded.";
        if (sentinel) { sentinel.hidden = false; if (observer) observer.observe(sentinel); }
      })
      .finally(function () {
        loading = false;
        if (skeleton) skeleton.hidden = true;
      });
  }

  function startFeed() {
    if (feedStarted || isGuest || !items || !sentinel || !nextPage) return;
    feedStarted = true;

    if ("IntersectionObserver" in window) {
      observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) requestNextPage();
        });
      }, { root: scrollRoot, rootMargin: "0px 0px 320px 0px" });
      observer.observe(sentinel);
    } else if (scrollRoot) {
      scrollRoot.addEventListener("scroll", function () {
        if (loading || !nextPage || sentinel.hidden) return;
        var rect = sentinel.getBoundingClientRect();
        var rootBottom = scrollRoot.getBoundingClientRect().bottom;
        if (rect.top <= rootBottom + 320) requestNextPage();
      }, { passive: true });
    }
  }

  window.setTimeout(open, DELAY_MS);
})();