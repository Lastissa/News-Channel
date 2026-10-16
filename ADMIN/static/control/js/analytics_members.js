/* ANALYTICS "Members" table loading behaviour.
   The members table is an htmx fragment: the filter form in the shell and the
   pager inside the fragment both swap #analytics-members-body with innerHTML.
   Without help that reads as a jump -- a shorter later page shrinks the page
   under the reader and there is no sign that anything is loading. This mirrors
   the proven archive gallery / profile list pattern:

     1. on every request the body's height is locked to at least the current
        height (a full page), so the page below never moves while it loads;
     2. the rows are replaced by a shimmer skeleton of the page size, so the
        wait is visible;
     3. once the new page lands the height eases to its real size, and a pager
        click scrolls the "Members" heading back into view.

   Typing in the email box only dims the rows (like the archive search); the
   selects and the pager show the skeleton, since those are the "filter
   update" the reader expects to see acknowledged. */
(function () {
  "use strict";

  var membersBody = document.getElementById("analytics-members-body");
  if (!membersBody || typeof window.htmx === "undefined") return;

  var filtersForm = document.getElementById("analytics-members-filters");
  var searchInput = filtersForm ? filtersForm.querySelector('input[type="search"]') : null;

  function pageSize() {
    var size = parseInt(membersBody.dataset.pageSize, 10);
    return size > 0 ? size : 12;
  }

  function buildSkeleton() {
    var row =
      '<div class="analytics-member-skeleton-row" aria-hidden="true">' +
        '<span class="analytics-member-skeleton-avatar"></span>' +
        '<span class="analytics-member-skeleton-lines">' +
          '<span class="analytics-member-skeleton-bar"></span>' +
          '<span class="analytics-member-skeleton-bar is-short"></span>' +
        '</span>' +
        '<span class="analytics-member-skeleton-chip"></span>' +
        '<span class="analytics-member-skeleton-chip"></span>' +
      '</div>';
    var rows = "";
    for (var i = 0; i < pageSize(); i += 1) rows += row;
    return '<div class="analytics-member-skeleton" aria-hidden="true">' + rows + '</div>';
  }

  /* Ease from the locked height to the real height once the swap has landed.
     The height is set to auto for one read so a *shorter* new page reports its
     true content height (scrollHeight would otherwise be clamped to the lock). */
  function settleHeight() {
    var locked = parseFloat(membersBody.style.height) || membersBody.scrollHeight;
    membersBody.style.height = "auto";
    var natural = membersBody.scrollHeight;
    membersBody.style.height = locked + "px";
    var duration = natural < locked ? 420 : 260;

    membersBody.style.transition = "height " + duration + "ms cubic-bezier(0.22, 1, 0.36, 1)";
    requestAnimationFrame(function () {
      membersBody.style.height = natural + "px";
      window.setTimeout(function () {
        membersBody.style.transition = "";
        membersBody.style.height = "";
        membersBody.style.overflow = "";
      }, duration + 20);
    });
  }

  function headerOffset() {
    var h = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--header-h")) || 64;
    return h + 16;
  }

  function keepHeadingInView() {
    var heading = document.getElementById("analytics-members-title") || membersBody;
    var top = heading.getBoundingClientRect().top + window.pageYOffset - headerOffset();
    if (top < window.pageYOffset) window.scrollTo({ top: Math.max(top, 0), behavior: "smooth" });
  }

  var pendingHTML = null;
  var activeXhr = null;
  var scrollAfterSwap = false;

  document.body.addEventListener("htmx:beforeRequest", function (event) {
    if (!event.detail || event.detail.target !== membersBody) return;

    /* a newer request replaces one still in flight, so a slow old answer can
       never land on top of a newer one */
    if (activeXhr && activeXhr !== event.detail.xhr) {
      try { activeXhr.abort(); } catch (err) { /* already settled */ }
    }
    activeXhr = event.detail.xhr || null;
    membersBody.setAttribute("aria-busy", "true");

    if (searchInput && event.detail.elt === searchInput) {
      membersBody.classList.add("is-searching");
      return;
    }

    scrollAfterSwap = !!(event.detail.elt && event.detail.elt.closest && event.detail.elt.closest(".analytics-members-pagination"));
    if (!membersBody.classList.contains("is-paginating")) {
      pendingHTML = membersBody.innerHTML;
      var previousHeight = membersBody.offsetHeight;
      membersBody.innerHTML = buildSkeleton();
      /* never let the skeleton shrink the layout: keep whichever is taller */
      membersBody.style.height = Math.max(previousHeight, membersBody.scrollHeight) + "px";
      membersBody.style.overflow = "hidden";
      membersBody.classList.add("is-paginating");
    }
  });

  membersBody.addEventListener("htmx:afterSwap", function () {
    activeXhr = null;
    membersBody.classList.remove("is-searching");
    membersBody.setAttribute("aria-busy", "false");
    if (!membersBody.classList.contains("is-paginating")) return;
    membersBody.classList.remove("is-paginating");
    pendingHTML = null;
    settleHeight();
    if (scrollAfterSwap) {
      scrollAfterSwap = false;
      keepHeadingInView();
    }
  });

  function recover(event) {
    if (!event.detail || event.detail.target !== membersBody) return;
    activeXhr = null;
    membersBody.classList.remove("is-searching");
    membersBody.setAttribute("aria-busy", "false");
    if (membersBody.classList.contains("is-paginating")) {
      membersBody.classList.remove("is-paginating");
      if (pendingHTML !== null) membersBody.innerHTML = pendingHTML;
      pendingHTML = null;
      membersBody.style.transition = "";
      membersBody.style.height = "";
      membersBody.style.overflow = "";
    }
    if (typeof window.AbuToast === "function") {
      window.AbuToast("Could not load those members. Try again.", "error");
    }
  }
  document.body.addEventListener("htmx:responseError", recover);
  document.body.addEventListener("htmx:sendError", recover);
  document.body.addEventListener("htmx:timeout", recover);
})();
