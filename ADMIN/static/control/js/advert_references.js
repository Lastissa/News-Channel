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

/* Reference storage drawer. Upload/delete forms are htmx and re-render the
   drawer body; this only handles open/close, filter and search state. */
(function () {
  var storageModal = document.querySelector("[data-storage-modal]");
  var deleteModal = document.querySelector("[data-ref-delete-modal]");
  var storageBody = document.getElementById("advert-storage-body");
  var storageFilter = "all";
  var storageQuery = "";

  function open(modal) {
    if (!modal) return;
    modal.hidden = false;
    modal.classList.add("is-open");
    document.body.classList.add("has-ads-modal");
  }

  function close(modal) {
    if (!modal || modal.hidden) return;
    modal.hidden = true;
    modal.classList.remove("is-open");
    if (!document.querySelector(".ads-modal.is-open")) document.body.classList.remove("has-ads-modal");
  }

  function applyStorageFilter() {
    if (!storageBody) return;
    storageBody.querySelectorAll(".ads-storage-item").forEach(function (item) {
      var kind = item.getAttribute("data-storage-kind") || "file";
      var haystack = (item.getAttribute("data-storage-search") || "").toLowerCase();
      var kindOk = storageFilter === "all" || kind === storageFilter;
      var queryOk = !storageQuery || haystack.indexOf(storageQuery) !== -1;
      item.hidden = !(kindOk && queryOk);
    });
  }

  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-open-storage]")) open(storageModal);
    if (event.target.closest("[data-open-ref-delete]")) open(deleteModal);

    var closeButton = event.target.closest("[data-modal-close]");
    if (closeButton) {
      close(closeButton.closest(".ads-modal"));
      return;
    }
    var filterButton = event.target.closest("[data-storage-filter]");
    if (filterButton) {
      storageFilter = filterButton.getAttribute("data-storage-filter");
      storageBody && storageBody.querySelectorAll("[data-storage-filter]").forEach(function (button) {
        button.classList.toggle("is-active", button === filterButton);
      });
      applyStorageFilter();
      return;
    }
    if (event.target === storageModal) close(storageModal);
    if (event.target === deleteModal) close(deleteModal);
  });

  document.addEventListener("input", function (event) {
    if (!event.target.matches || !event.target.matches("[data-storage-search]")) return;
    storageQuery = (event.target.value || "").trim().toLowerCase();
    applyStorageFilter();
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    close(storageModal);
    close(deleteModal);
  });

  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.target && event.target.id === "advert-storage-body") {
      storageFilter = "all";
      storageQuery = "";
      open(storageModal);
      applyStorageFilter();
    }
    if (event.target && event.target.id === "advert-ref-delete-body") open(deleteModal);
  });
})();
