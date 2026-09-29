/* MOST VIEWED RAIL (HOME/templates/HOME/home.html, #trending-section)
   The top-3-by-views list is not part of HomeView's own render (see the
   docstring on HOME.views.MostViewedView for why) -- it is fetched once,
   here, right after the page loads. The section ships hidden with 3
   skeleton rows already in the markup; this either swaps them for the real
   3 stories and reveals the section, or leaves it hidden for good on
   failure/empty so a broken fetch never shows as broken UI. */
(function () {
  "use strict";

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  var EYE_ICON =
    '<svg viewBox="0 0 20 20" class="trending-eye" aria-hidden="true">' +
    '<path d="M1.5 10S4.5 4 10 4s8.5 6 8.5 6-3 6-8.5 6-8.5-6-8.5-6z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/>' +
    '<circle cx="10" cy="10" r="2.4" fill="none" stroke="currentColor" stroke-width="1.4"/>' +
    "</svg>";

  var FALLBACK_IMG = "https://placehold.co/160x160/1F2A37/F6F3ED?text=%20";

  function formatViews(count) {
    var n = Number(count) || 0;
    if (n >= 1000000) return (n / 1000000).toFixed(n % 1000000 === 0 ? 0 : 1) + "M";
    if (n >= 1000) return (n / 1000).toFixed(n % 1000 === 0 ? 0 : 1) + "K";
    return String(n);
  }

  function renderItem(post, rank) {
    var url = escapeHtml(post.url || "#");
    return (
      '<li class="trending-item">' +
        '<span class="trending-rank">' + "-" + "</span>" +
        '<a class="trending-media" href="' + url + '" tabindex="-1">' +
          '<img src="' + escapeHtml(post.image || FALLBACK_IMG) + '" alt="" loading="lazy" ' +
          'onerror="this.onerror=null;this.src=\'' + FALLBACK_IMG + '\';">' +
        "</a>" +
        '<div class="trending-body">' +
          '<span class="tag">' + escapeHtml(post.category || "") + "</span>" +
          '<h3 class="trending-title"><a href="' + url + '">' + escapeHtml(post.heading) + "</a></h3>" +
          '<span class="trending-meta">' + EYE_ICON + " " + formatViews(post.views) + " views</span>" +
        "</div>" +
      "</li>"
    );
  }

  function init() {
    var section = document.getElementById("trending-section");
    var list = document.getElementById("trending-list");
    if (!section || !list || !section.dataset.endpoint) return;

    fetch(section.dataset.endpoint, {
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" },
    })
      .then(function (response) {
        if (!response.ok) throw new Error("status " + response.status);
        return response.json();
      })
      .then(function (data) {
        var results = (data && data.results) || [];
        if (!results.length) return; /* stays hidden, no empty box shown */
        list.innerHTML = results.map(renderItem).join("");
        section.hidden = false;
      })
      .catch(function () {
        /* network hiccup or nothing published yet: leave it hidden */
      });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
