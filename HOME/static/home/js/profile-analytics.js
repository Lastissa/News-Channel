(function () {
  "use strict";

  /* Client-side sorting for the author's story table. A delegated listener is
     used because the whole panel can be swapped in by HTMX after this script
     has already loaded. No request is made when a column is sorted. */

  function numeric(key) {
    return key !== "heading";
  }

  function sortTable(button) {
    var table = button.closest("[data-sort-table]");
    if (!table) return;
    var body = table.querySelector("tbody");
    if (!body) return;
    var rows = Array.prototype.slice.call(body.querySelectorAll("tr[data-" + button.dataset.sortKey + "]"));
    if (rows.length < 2) return;

    var key = button.dataset.sortKey;
    var direction = button.dataset.sortDir === "desc" ? -1 : 1;

    rows.sort(function (left, right) {
      var a = left.dataset[key] || "";
      var b = right.dataset[key] || "";
      if (numeric(key)) {
        return (Number(a) - Number(b)) * direction;
      }
      return a.localeCompare(b) * direction;
    });

    rows.forEach(function (row) { body.appendChild(row); });
    button.dataset.sortDir = direction === 1 ? "desc" : "asc";
    table.querySelectorAll("[data-sort-key]").forEach(function (other) {
      if (other !== button) delete other.dataset.sortDir;
    });
  }

  document.addEventListener("click", function (event) {
    var button = event.target && event.target.closest && event.target.closest("[data-sort-key]");
    if (button) sortTable(button);
  });

  /* The green button fetches the panel once. After the first successful swap
     it is a plain jump to the panel already on the page, so opening analytics
     again never repeats the request. A capture listener stops HTMX before it
     sees a later click. */
  var openButton = document.querySelector("[data-profile-analytics-open]");
  if (openButton) {
    var lazyAttributes = ["hx-get", "hx-target", "hx-swap", "hx-indicator", "hx-disabled-elt", "hx-push-url"];
    var originalAttributes = {};
    lazyAttributes.forEach(function (name) {
      if (openButton.hasAttribute(name)) originalAttributes[name] = openButton.getAttribute(name);
    });

    openButton.addEventListener("click", function (event) {
      if (openButton.dataset.loaded !== "1") return;
      event.preventDefault();
      event.stopPropagation();
      var panel = document.querySelector("[data-profile-analytics]");
      if (panel && panel.scrollIntoView) {
        panel.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }, true);

    function syncOpenButton(event) {
      var target = event.detail && event.detail.target;
      if (target && target.id && target.id !== "profile-content") return;
      if (document.querySelector("[data-profile-analytics]")) {
        openButton.dataset.loaded = "1";
        lazyAttributes.forEach(function (name) { openButton.removeAttribute(name); });
        return;
      }
      /* The profile came back through a jump link or the browser Back button,
         so the next green-button click is allowed to fetch a fresh panel. */
      delete openButton.dataset.loaded;
      Object.keys(originalAttributes).forEach(function (name) {
        openButton.setAttribute(name, originalAttributes[name]);
      });
    }

    document.body.addEventListener("htmx:afterSwap", syncOpenButton);
    document.body.addEventListener("htmx:historyRestore", syncOpenButton);
  }
})();
