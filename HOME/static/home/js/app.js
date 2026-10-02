// THEME SETTINGS AND OTHERS

(function () {
  "use strict";

  var root = document.documentElement;
  var header = document.getElementById("site-header");
  var THEME_KEY = "abureport-theme";

  /* Theme toggle */
  function applyTheme(theme) {
    root.setAttribute("data-theme", theme);
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
