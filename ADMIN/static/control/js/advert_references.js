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

  //  Regular has no subdomain: switch the box off so nobody types one. Pro and
  //  Advance must have one unless a Public page URL opens an external link.
  //  The server applies the same rule; this is just the visible guard.
  function syncPlan(select) {
    var form = select.closest("form");
    var input = form && form.querySelector("[data-subdomain-input]");
    var hint = form && form.querySelector("[data-subdomain-hint]");
    var publicInput = form && form.querySelector("[data-public-url-input]");
    if (!input) return;
    var off = select.value === "regular";
    var external = !!(publicInput && publicInput.value.trim());
    if (!external && select.value !== "regular") {
      var chosen = form && form.querySelector('select[name="advert_id"]');
      var option = chosen && chosen.options[chosen.selectedIndex];
      external = !!(option && option.getAttribute("data-has-url") === "true");
    }
    input.disabled = off;
    if (off) input.value = "";
    input.required = !off && !external;
    if (hint) {
      hint.textContent = off
        ? "Not included in the Regular plan."
        : (external
            ? "Optional because a Public page URL is set. Otherwise each paid advert needs its own subdomain."
            : "Required for Pro and Advance. Add a Public page URL instead to open an external link.");
    }
  }
  document.addEventListener("change", function (event) {
    if (event.target.matches("[data-plan-select]")) syncPlan(event.target);
    if (event.target.matches('select[name="advert_id"]')) {
      var form = event.target.closest("form");
      var select = form && form.querySelector("[data-plan-select]");
      if (select) syncPlan(select);
    }
  });
  document.querySelectorAll("[data-plan-select]").forEach(syncPlan);

  //  Keep the subdomain box to what a web address allows: lowercase letters,
  //  numbers and hyphens (a space or underscore turns into a hyphen).
  document.addEventListener("input", function (event) {
    var box = event.target.closest && event.target.closest("[data-subdomain-input]");
    if (box) {
      var cleaned = box.value.toLowerCase().replace(/[\s_]+/g, "-").replace(/[^a-z0-9-]/g, "").replace(/^-+/, "").slice(0, 63);
      if (cleaned !== box.value) box.value = cleaned;
      return;
    }
    if (event.target.matches && event.target.matches("[data-public-url-input]")) {
      var form = event.target.closest("form");
      var select = form && form.querySelector("[data-plan-select]");
      if (select) syncPlan(select);
    }
  });

  applyFilter();
})();
