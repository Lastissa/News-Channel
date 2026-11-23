// THEME SETTINGS AND OTHERS

(function () {
  "use strict";

  var root = document.documentElement;
  var header = document.getElementById("site-header");
  var THEME_KEY = "abureport-theme";

  /* Theme toggle */
  function applyTheme(theme) {
    root.setAttribute("data-theme", theme);
    /* keep the phone's address bar colour in step with the navbar colour of the theme */
    var bar = document.querySelector('meta[name="theme-color"]');
    if (bar) bar.setAttribute("content", theme === "dark" ? "#1C2E47" : "#0E1B2C");
    try { localStorage.setItem(THEME_KEY, theme); } catch (e) { /* storage unavailable, ignore */ }
    try {
      document.cookie = THEME_KEY + "=" + theme + "; path=/; max-age=31536000; SameSite=Lax";
    } catch (e) { /* ignore */ }
  }

  var savedTheme = null;
  try { savedTheme = localStorage.getItem(THEME_KEY); } catch (e) { /* ignore */ }
  if (savedTheme) {
    applyTheme(savedTheme);
  } else if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) {
    applyTheme("light");
  }

  var themeToggle = document.getElementById("theme-toggle");
  if (themeToggle) {
    themeToggle.addEventListener("click", function () {
      var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      applyTheme(next);
    });
  }

  /* Mobile nav drawer: slide-in panel + backdrop, scroll lock, swipe right
     to close, closes on link tap / Escape / backdrop / resize to desktop. */
  var navToggle = document.getElementById("nav-toggle");
  var navPanel = document.getElementById("primary-nav-mobile");
  var navBackdrop = document.querySelector("[data-nav-backdrop]");

  function setNav(open, restoreFocus) {
    if (!header) return;
    var wasOpen = header.classList.contains("nav-open");
    header.classList.toggle("nav-open", open);
    root.classList.toggle("nav-locked", open);
    if (navToggle) navToggle.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) {
      header.classList.remove("search-open");
      var closeBtn = navPanel && navPanel.querySelector("[data-nav-close]");
      if (closeBtn) setTimeout(function () { closeBtn.focus({ preventScroll: true }); }, 80);
    } else {
      closeDropdowns();
      if (wasOpen && restoreFocus && navToggle) navToggle.focus({ preventScroll: true });
    }
  }

  if (navToggle && header) {
    navToggle.addEventListener("click", function () {
      setNav(!header.classList.contains("nav-open"), false);
    });
  }
  if (navBackdrop) navBackdrop.addEventListener("click", function () { setNav(false, true); });
  if (navPanel) {
    var closeButton = navPanel.querySelector("[data-nav-close]");
    if (closeButton) closeButton.addEventListener("click", function () { setNav(false, true); });

    navPanel.addEventListener("click", function (event) {
      var link = event.target.closest("a[href]");
      if (link && link.getAttribute("href") !== "#") setNav(false, false);
    });

    var touchX = null, touchY = null;
    navPanel.addEventListener("touchstart", function (event) {
      touchX = event.touches[0].clientX; touchY = event.touches[0].clientY;
    }, { passive: true });
    navPanel.addEventListener("touchend", function (event) {
      if (touchX === null) return;
      var dx = event.changedTouches[0].clientX - touchX;
      var dy = event.changedTouches[0].clientY - touchY;
      touchX = touchY = null;
      if (dx > 70 && Math.abs(dy) < 60) setNav(false, true);
    }, { passive: true });
  }
  if (window.matchMedia) {
    var desktopQuery = window.matchMedia("(min-width: 900px)");
    var onDesktop = function (e) { if (e.matches) setNav(false, false); };
    if (desktopQuery.addEventListener) desktopQuery.addEventListener("change", onDesktop);
    else if (desktopQuery.addListener) desktopQuery.addListener(onDesktop);
  }

  /* Search toggle (mobile) */
  var searchToggle = document.getElementById("search-toggle");
  if (searchToggle && header) {
    searchToggle.addEventListener("click", function () {
      var open = header.classList.toggle("search-open");
      searchToggle.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) {
        var input = document.getElementById("search-input");
        if (input) input.focus();
      }
    });
  }

  function closeDropdowns() {
    var dropdowns = document.querySelectorAll(".has-dropdown");
    dropdowns.forEach(function (dropdown) {
      dropdown.classList.remove("is-open");
      var toggle = dropdown.querySelector(".dropdown-toggle");
      if (toggle) toggle.setAttribute("aria-expanded", "false");
    });
  }

  /* Category dropdown */
  var dropdowns = document.querySelectorAll(".has-dropdown");
  dropdowns.forEach(function (dropdown) {
    var toggle = dropdown.querySelector(".dropdown-toggle");
    if (!toggle) return;
    toggle.addEventListener("click", function (event) {
      event.stopPropagation();
      var isOpen = dropdown.classList.contains("is-open");
      closeDropdowns();
      if (!isOpen) {
        dropdown.classList.add("is-open");
        toggle.setAttribute("aria-expanded", "true");
      }
    });

    dropdown.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        closeDropdowns();
        if (header) header.classList.remove("nav-open");
      });
    });
  });

  document.addEventListener("click", function (event) {
    if (!event.target.closest(".has-dropdown")) {
      closeDropdowns();
    }
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      closeDropdowns();
      if (header) { header.classList.remove("search-open"); setNav(false, true); }
    }
  });

  /* Category filtering works in the same dropdown at every breakpoint. */
  var categoryFilter = document.querySelector("[data-category-filter]");
  if (categoryFilter) {
    categoryFilter.addEventListener("input", function () {
      var term = categoryFilter.value.trim().toLowerCase();
      document.querySelectorAll("[data-category-option]").forEach(function (option) {
        option.hidden = term !== "" && option.textContent.toLowerCase().indexOf(term) === -1;
      });
    });

    categoryFilter.addEventListener("click", function (event) {
      event.stopPropagation();
    });
  }

  /* Floating social buttons: the reader lays them out as a column or as a
     row. The choice is remembered on the device, and the buttons are moved
     into place rather than re-flowed, so the switch is smooth. */
  var fabStacks = document.querySelectorAll("[data-fab-stack]");
  fabStacks.forEach(function (stack) {
    var toggle = stack.querySelector("[data-fab-toggle]");
    if (!toggle) return;

    function paint() {
      var horizontal = stack.classList.contains("is-horizontal");
      var label = horizontal
        ? "Switch the social buttons to a column"
        : "Switch the social buttons to a row";
      toggle.setAttribute("aria-pressed", horizontal ? "true" : "false");
      toggle.setAttribute("aria-label", label);
      toggle.setAttribute("title", label);
    }

    paint();
    toggle.addEventListener("click", function () {
      stack.classList.toggle("is-horizontal");
      var horizontal = stack.classList.contains("is-horizontal");
      try {
        localStorage.setItem("abureport-fab-layout", horizontal ? "row" : "column");
      } catch (e) { /* storage unavailable, ignore */ }
      paint();
    });
  });

  var logoutButtons = document.querySelectorAll("[data-logout-btn]");
  logoutButtons.forEach(function (button) {
    button.addEventListener("click", function (event) {
      event.preventDefault();
      var confirmed = window.confirm("Are you sure you want to log out?");
      if (!confirmed) return;

      var form = button.closest("form");
      if (!form) return;

      fetch(form.action, {
        method: "POST",
        headers: {
          "X-CSRFToken": document.cookie.match(/(^|;)\s*csrftoken\s*=\s*([^;]+)/)?.pop() || "",
          "X-Requested-With": "XMLHttpRequest"
        },
        body: new FormData(form),
        credentials: "same-origin"
      })
        .then(function (response) {
          if (!response.ok) {
            throw new Error("Logout failed");
          }
          return response.json().catch(function () { return { detail: "success" }; });
        })
        .then(function () {
          window.location.reload();
        })
        .catch(function () {
          window.alert("Could not log out. Please try again.");
        });
    });
  });
})();

/* Advert analytics charts.
   The dashboard and the Ads desk reuse the same ApexCharts bundle and the same
   JSON payloads, so this only draws what the server already calculated. It is
   safe to load on every page: without a [data-advert-chart] mount it does
   nothing. */
(function () {
  "use strict";

  function reducedMotion() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function chartOptions(data, mount) {
    var height = mount.clientWidth < 420 ? 220 : 260;
    var common = {
      chart: {
        height: height,
        width: "100%",
        fontFamily: "inherit",
        background: "transparent",
        toolbar: { show: false },
        zoom: { enabled: false },
        animations: { enabled: !reducedMotion(), speed: 220 },
      },
      stroke: { width: 0 },
    };

    if (data.kind === "pie") {
      return {
        chart: Object.assign({}, common.chart, { type: "pie" }),
        series: data.values || [],
        labels: data.labels || [],
        colors: data.colors || [],
        dataLabels: {
          enabled: true,
          formatter: function (value) { return Math.round(value) + "%"; },
        },
        legend: { show: true, position: "bottom", fontSize: "12px" },
        tooltip: { y: { formatter: function (value) { return value + " clicks"; } } },
        noData: { text: "No clicks yet" },
      };
    }

    return {
      chart: Object.assign({}, common.chart, { type: "line" }),
      series: [{ name: data.name || "Views", data: data.values || [] }],
      colors: ["#e8b84a"],
      stroke: { curve: "straight", width: 2 },
      markers: { size: 2.5, strokeWidth: 0 },
      grid: { borderColor: "rgba(127, 140, 160, 0.2)", strokeDashArray: 3 },
      xaxis: {
        categories: data.labels || [],
        tickAmount: Math.min(8, (data.labels || []).length),
        labels: { hideOverlappingLabels: true, rotate: 0, trim: true },
      },
      yaxis: {
        min: 0,
        forceNiceScale: true,
        labels: { formatter: function (value) { return Math.round(value); } },
      },
      legend: { show: false },
      tooltip: { shared: true, intersect: false },
      noData: { text: "No views yet" },
    };
  }

  function paintChart(mount) {
    var root = mount.closest("[data-advert-chart]");
    var script = root && root.querySelector('script[type="application/json"]');
    if (!script) return;
    var data;
    try {
      data = JSON.parse(script.textContent);
    } catch (error) {
      return;
    }
    if (mount._advertChart) {
      mount._advertChart.destroy();
      mount._advertChart = null;
    }
    if (!window.ApexCharts) {
      mount.textContent = "Charts are unavailable right now.";
      return;
    }
    mount._advertChart = new window.ApexCharts(mount, chartOptions(data, mount));
    mount._advertChart.render();
  }

  function paintAll() {
    document.querySelectorAll("[data-advert-chart] .ads-dash-chart-canvas").forEach(function (mount) {
      paintChart(mount);
    });
  }

  function currentValue(panel, selector) {
    var field = panel.querySelector(selector);
    return field ? field.value : "";
  }

  function reload(panel, range, reference) {
    var url = panel.getAttribute("data-advert-analytics-url");
    if (!url) return;
    var query = "range=" + encodeURIComponent(range || "30");
    query += "&reference=" + encodeURIComponent(reference || "");
    url += (url.indexOf("?") >= 0 ? "&" : "?") + query;
    if (window.htmx) {
      window.htmx.ajax("GET", url, { target: panel, swap: "innerHTML" });
    } else {
      window.location.href = url;
    }
  }

  document.addEventListener("DOMContentLoaded", paintAll);
  document.addEventListener("htmx:afterSwap", paintAll);
  document.addEventListener("htmx:beforeSwap", function (event) {
    var target = event.detail && event.detail.target;
    if (!target || !target.querySelectorAll) return;
    target.querySelectorAll("[data-advert-chart] .ads-dash-chart-canvas").forEach(function (mount) {
      if (mount._advertChart) {
        mount._advertChart.destroy();
        mount._advertChart = null;
      }
    });
  });

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-advert-range]");
    if (!button) return;
    var panel = button.closest("[data-advert-analytics]");
    if (!panel) return;
    reload(
      panel,
      button.getAttribute("data-advert-range"),
      currentValue(panel, "[data-advert-reference]")
    );
  });

  document.addEventListener("change", function (event) {
    var select = event.target.closest("[data-advert-reference]");
    if (!select) return;
    var panel = select.closest("[data-advert-analytics]");
    if (!panel) return;
    reload(
      panel,
      panel.getAttribute("data-advert-range") || "30",
      select.value
    );
  });
})();
