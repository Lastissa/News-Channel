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
     again never repeats the request. A delegated capture listener survives
     HTMX history restores, which replace body children with cached HTML. */
  var lazyAttributes = ["hx-get", "hx-target", "hx-swap", "hx-indicator", "hx-disabled-elt", "hx-push-url"];
  var originalAttributes = {};

  function captureOriginalAttributes(button) {
    if (!button) return;
    lazyAttributes.forEach(function (name) {
      if (button.hasAttribute(name)) originalAttributes[name] = button.getAttribute(name);
    });
  }

  captureOriginalAttributes(document.querySelector("[data-profile-analytics-open]"));

  document.addEventListener("click", function (event) {
    var button = event.target && event.target.closest && event.target.closest("[data-profile-analytics-open]");
    if (!button || button.dataset.loaded !== "1") return;
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
    var button = document.querySelector("[data-profile-analytics-open]");
    if (!button) return;
    captureOriginalAttributes(button);
    if (document.querySelector("[data-profile-analytics]")) {
      button.dataset.loaded = "1";
      lazyAttributes.forEach(function (name) { button.removeAttribute(name); });
      return;
    }
    /* The profile came back through a jump link or the browser Back button,
       so the next green-button click is allowed to fetch a fresh panel. */
    delete button.dataset.loaded;
    Object.keys(originalAttributes).forEach(function (name) {
      button.setAttribute(name, originalAttributes[name]);
    });
  }

  document.body.addEventListener("htmx:afterSwap", syncOpenButton);
  document.body.addEventListener("htmx:historyRestore", syncOpenButton);
})();
