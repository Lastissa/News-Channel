/* Ads desk: filters, the small message after a button, and the plan rule on
   the subdomain box. Buttons on the cards are handled by htmx. */
(function () {
  var cards = document.getElementById("ads-desk-cards");
  var toast = document.getElementById("ads-desk-toast");
  var filter = "all";
  var toastTimer = null;

  function applyFilter() {
    if (!cards) return;
    var counts = { all: 0, live: 0, scheduled: 0, paused: 0, expired: 0 };
    var shown = 0;
    cards.querySelectorAll(".ads-desk-ref").forEach(function (card) {
      var status = card.getAttribute("data-status");
      counts.all += 1;
      if (counts[status] !== undefined) counts[status] += 1;
      var show = filter === "all" || filter === status;
      card.hidden = !show;
      if (show) shown += 1;
    });
    Object.keys(counts).forEach(function (key) {
      var el = document.querySelector('[data-count="' + key + '"]');
      if (el) el.textContent = counts[key];
    });
    var none = document.getElementById("ads-desk-none");
    if (none) none.hidden = shown !== 0;
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-filter]");
    if (button) {
      filter = button.getAttribute("data-filter");
      document.querySelectorAll("[data-filter]").forEach(function (b) {
        b.classList.toggle("is-active", b === button);
      });
      applyFilter();
      return;
    }
    if (event.target.closest("[data-open-issue]")) {
      var box = document.getElementById("issue-reference");
      if (box) box.open = true;
    }
  });

  //  A card was swapped (pause, renew...): its status may have changed.
  document.body.addEventListener("htmx:afterSwap", applyFilter);

  document.body.addEventListener("adsToast", function (event) {
    if (!toast) return;
    var info = event.detail || {};
    toast.textContent = info.text || "";
    toast.className = "ads-desk-toast" + (info.ok === false ? " is-error" : "");
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toast.hidden = true; }, 4000);
  });

  //  Regular has no subdomain: switch the box off so nobody types one. The
  //  server refuses it too.
  function syncPlan(select) {
    var form = select.closest("form");
    var input = form && form.querySelector("[data-subdomain-input]");
    var hint = form && form.querySelector("[data-subdomain-hint]");
    if (!input) return;
    var off = select.value === "regular";
    input.disabled = off;
    if (off) input.value = "";
    if (hint) hint.textContent = off ? "Not included in the Regular plan." : "Pro and Advance plans only. Each advert needs its own subdomain. An underscore becomes a hyphen.";
  }
  document.addEventListener("change", function (event) {
    if (event.target.matches("[data-plan-select]")) syncPlan(event.target);
  });
  document.querySelectorAll("[data-plan-select]").forEach(syncPlan);

  applyFilter();
})();
