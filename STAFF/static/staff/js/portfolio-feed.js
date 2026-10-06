(function () {
  "use strict";

  var feed = document.getElementById("portfolio-feed");
  if (!feed) return;

  var items = feed.querySelector("[data-feed-items]");
  var sentinel = feed.querySelector("[data-feed-sentinel]");
  var skeleton = feed.querySelector("[data-feed-skeleton]");
  var endMessage = feed.querySelector("[data-feed-end]");
  var status = feed.querySelector("[data-feed-status]");
  var nextPage = feed.dataset.nextPage;
  var loading = false;
  var observer = null;

  var popularList = document.querySelector(".portfolio-popular-list");
  var popularRail = document.querySelector(".portfolio-popular-rail");
  var mobileLayout = window.matchMedia("(max-width: 899.98px)");
  var popularRailPlaceholder = popularRail ? document.createComment("portfolio-popular-rail") : null;
  if (popularRail && popularRail.parentNode && popularRailPlaceholder) {
    popularRail.parentNode.insertBefore(popularRailPlaceholder, popularRail);
  }

  function placePopularRail() {
    if (!popularRail || !popularRailPlaceholder || !popularRailPlaceholder.parentNode) return;

    if (mobileLayout.matches) {
      var firstStory = items && items.querySelector("[data-feed-story]");
      if (firstStory) firstStory.insertAdjacentElement("afterend", popularRail);
    } else {
      popularRailPlaceholder.parentNode.insertBefore(popularRail, popularRailPlaceholder.nextSibling);
    }
  }

  placePopularRail();
  if (mobileLayout.addEventListener) {
    mobileLayout.addEventListener("change", placePopularRail);
  } else {
    mobileLayout.addListener(placePopularRail);
  }

  if (popularList && "IntersectionObserver" in window) {
    var popularObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting && entry.intersectionRatio >= 0.2) {
          popularList.classList.add("is-inview");
        } else if (!entry.isIntersecting) {
          popularList.classList.remove("is-inview");
        }
      });
    }, { threshold: [0, 0.2] });
    popularObserver.observe(popularList);
  } else if (popularList) {
    popularList.classList.add("is-inview");
  }

  if (!items || !sentinel || !skeleton || !nextPage) return;

  function showToast(message, tone) {
    if (typeof window.AbuToast === "function") {
      window.AbuToast(message, tone);
    }
  }

  function requestNextPage() {
    if (loading || !nextPage || sentinel.hidden) return;
    loading = true;
    sentinel.hidden = true;
    skeleton.hidden = false;
    feed.setAttribute("aria-busy", "true");
    if (status) status.textContent = "Loading more stories.";
    showToast("Please wait while more stories load.", "info");

    fetch(feed.dataset.feedUrl + "?page=" + encodeURIComponent(nextPage), {
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" },
      cache: "no-store"
    }).then(function (response) {
      if (!response.ok) {
        return response.text().then(function (body) {
          var detail = "Could not load more stories.";
          try {
            var payload = JSON.parse(body);
            if (payload.detail) detail = payload.detail;
          } catch (error) {
            // Keep the user-facing message generic for non-JSON server errors.
          }
          throw new Error(detail);
        });
      }
      return response.text().then(function (html) {
        items.insertAdjacentHTML("beforeend", html);
        nextPage = response.headers.get("X-Portfolio-Next-Page") || "";
        feed.dataset.nextPage = nextPage;

        if (nextPage) {
          sentinel.hidden = false;
          if (observer) observer.observe(sentinel);
        } else {
          if (observer) observer.unobserve(sentinel);
          if (endMessage) endMessage.hidden = false;
        }
        if (status) status.textContent = nextPage ? "More stories loaded." : "All stories loaded.";
      });
    }).catch(function (error) {
      showToast(error.message || "Could not load more stories.", "error");
      if (status) status.textContent = "More stories could not be loaded.";
      sentinel.hidden = false;
      if (observer) observer.unobserve(sentinel);

      var retryOnScroll = function () {
        if (nextPage && !sentinel.hidden && observer) observer.observe(sentinel);
      };
      window.addEventListener("scroll", retryOnScroll, { once: true, passive: true });
    }).finally(function () {
      loading = false;
      skeleton.hidden = true;
      feed.removeAttribute("aria-busy");
    });
  }

  if ("IntersectionObserver" in window) {
    observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) requestNextPage();
      });
    }, { rootMargin: "320px 0px" });
    observer.observe(sentinel);
  } else {
    window.addEventListener("scroll", function () {
      if (!loading && !sentinel.hidden && sentinel.getBoundingClientRect().top <= window.innerHeight + 320) {
        requestNextPage();
      }
    }, { passive: true });
  }
})();
