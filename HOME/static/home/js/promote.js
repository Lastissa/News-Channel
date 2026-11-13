(function () {
  "use strict";

  //   The promote page renders a shimmer skeleton in the advert grid, then this
  //   swaps in the server-rendered cards (HOME/views.PromoteAdsView). Keeping
  //   the fetch on GET and replacing innerHTML means we never build markup from
  //   strings in JS and the section is never a wall of text.
  var grid = document.querySelector("[data-promote-ads]");
  var adsUrl = grid ? grid.getAttribute("data-ads-url") : "";

  if (grid && adsUrl && typeof window.fetch === "function") {
    fetch(adsUrl, {
      method: "GET",
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" },
      cache: "no-store"
    })
      .then(function (response) {
        if (!response.ok) throw new Error("adverts feed failed: " + response.status);
        return response.text();
      })
      .then(function (html) {
        grid.innerHTML = html;
        grid.removeAttribute("aria-busy");
      })
      .catch(function () {
        //   Never leave the shimmer running forever: swap in a quiet fallback.
        var note = document.createElement("p");
        note.className = "promote-ads-empty";
        note.textContent =
          "We could not load the adverts running right now. Refresh the page to try again.";
        grid.innerHTML = "";
        grid.appendChild(note);
        grid.removeAttribute("aria-busy");
      });
  }

  /* ------------------------------------------------------------------------
     Progressive motion for the partner page. Everything below is an
     enhancement: the CSS falls back to a visible, static page when motion is
     reduced or JavaScript is unavailable. The data attributes in
     HOME/templates/HOME/promote.html are the contract.
     ------------------------------------------------------------------------ */
  var page = document.querySelector("[data-promote-page]");
  if (!page) return;

  var reduceMotion =
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var finePointer =
    window.matchMedia && window.matchMedia("(pointer: fine)").matches;

  /* ---------- scroll reveal ---------- */
  var revealItems = Array.prototype.slice.call(
    page.querySelectorAll("[data-reveal]")
  );

  var revealSafety = 0;

  function revealAll() {
    if (revealSafety) {
      window.clearTimeout(revealSafety);
      revealSafety = 0;
    }
    revealItems.forEach(function (item) {
      item.classList.add("is-visible");
    });
  }

  if (
    reduceMotion ||
    document.hidden ||
    !("IntersectionObserver" in window) ||
    !revealItems.length
  ) {
    revealAll();
  } else {
    var revealObserver = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-visible");
          revealObserver.unobserve(entry.target);
        });
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.08 }
    );

    revealItems.forEach(function (item) {
      revealObserver.observe(item);
    });

    //   If IntersectionObserver never settles (a hidden/reparented tab, an
    //   extension, or a browser quirk), show the content instead of leaving a
    //   blank page behind the reveal styles.
    revealSafety = window.setTimeout(function () {
      var hasVisible = revealItems.some(function (item) {
        return item.classList.contains("is-visible");
      });
      if (!hasVisible) revealAll();
    }, 2200);
  }

  /* ---------- active section in the jump nav ---------- */
  var nav = page.querySelector("[data-promote-nav]");
  var navLinks = nav
    ? Array.prototype.slice.call(nav.querySelectorAll('a[href^="#"]'))
    : [];
  var navSections = navLinks
    .map(function (link) {
      return document.getElementById(link.getAttribute("href").slice(1));
    })
    .filter(Boolean);

  function setActiveSection(id) {
    navLinks.forEach(function (link) {
      var active = link.getAttribute("href") === "#" + id;
      link.classList.toggle("is-active", active);
      if (active) {
        link.setAttribute("aria-current", "location");
      } else {
        link.removeAttribute("aria-current");
      }
    });
  }

  if (navSections.length) {
    var navTicking = false;

    function updateActiveSection() {
      navTicking = false;
      var headerHeight = 64;
      var rootStyles = getComputedStyle(document.documentElement);
      var token = parseFloat(rootStyles.getPropertyValue("--header-h"));
      if (!isNaN(token) && token > 0) headerHeight = token;

      var probe = window.scrollY + headerHeight + 130;
      var current = navSections[0].id;

      navSections.forEach(function (section) {
        var top = section.getBoundingClientRect().top + window.scrollY;
        if (top <= probe) current = section.id;
      });

      if (
        window.innerHeight + window.scrollY >=
        document.documentElement.scrollHeight - 6
      ) {
        current = navSections[navSections.length - 1].id;
      }

      setActiveSection(current);
    }

    function requestActiveUpdate() {
      if (navTicking) return;
      navTicking = true;
      window.requestAnimationFrame(updateActiveSection);
    }

    window.addEventListener("scroll", requestActiveUpdate, { passive: true });
    window.addEventListener("resize", requestActiveUpdate, { passive: true });
    updateActiveSection();
  }

  /* ---------- weekly plan rail: pinned horizontal scroll ---------- */
  //   On small screens the plan cards become a horizontal rail. Rather than
  //   hiding the rest of the plans off the right edge, the rail sticks in the
  //   viewport while the page scrolls vertically, translating the cards
  //   horizontally. A visible progress line tells readers the rail exists and
  //   how much is left. Short viewports, reduced motion, and desktop keep the
  //   native swipe rail, so the effect is an enhancement, not a scroll trap.
  var planSection = page.querySelector(".promote-plans");
  var planPin = page.querySelector("[data-plan-pin]");
  var planStick = planPin ? planPin.querySelector(".promote-plans-stick") : null;
  var planRail = page.querySelector("[data-plan-rail]");
  var planProgress = page.querySelector("[data-plan-progress]");
  var planNav = page.querySelector("[data-promote-nav]");
  var adRail = page.querySelector("[data-promote-ads]");
  var planPinned = false;
  var planDistance = 0;
  var planTopOffset = 0;
  var railTicking = false;

  function setPlanProgress(value) {
    if (!planProgress) return;
    value = Math.max(0, Math.min(1, value));
    planProgress.style.width = (value * 100).toFixed(2) + "%";
  }

  function updatePlanProgressFromRail() {
    if (!planRail || planPinned) return;
    var max = planRail.scrollWidth - planRail.clientWidth;
    setPlanProgress(max > 2 ? planRail.scrollLeft / max : 0);
  }

  function updatePlanRail() {
    if (!planRail) return;

    if (!planPinned) {
      updatePlanProgressFromRail();
      return;
    }

    if (!planPin || !planStick) return;

    var rect = planPin.getBoundingClientRect();
    var total = planPin.offsetHeight - planStick.offsetHeight;

    if (total <= 0) {
      setPlanProgress(0);
      return;
    }

    var elapsed = planTopOffset - rect.top;
    var progress = Math.max(0, Math.min(1, elapsed / total));

    planRail.style.transform =
      "translate3d(" + (-progress * planDistance).toFixed(2) + "px, 0, 0)";
    setPlanProgress(progress);
  }

  function measurePlanRail() {
    if (
      !planSection ||
      !planPin ||
      !planStick ||
      !planRail ||
      !planProgress
    ) {
      return;
    }

    var rootStyles = getComputedStyle(document.documentElement);
    var headerHeight = parseFloat(rootStyles.getPropertyValue("--header-h"));
    if (isNaN(headerHeight) || headerHeight <= 0) headerHeight = 64;

    var canPin = false;
    var available = 0;

    if (
      !reduceMotion &&
      window.matchMedia &&
      window.matchMedia("(max-width: 980px)").matches
    ) {
      var jumpHeight = planNav ? planNav.offsetHeight : 0;
      planTopOffset = headerHeight + 12 + jumpHeight + 8;
      available = window.innerHeight - planTopOffset;
      planDistance = Math.max(0, planRail.scrollWidth - planStick.clientWidth);

      canPin =
        planDistance > 2 &&
        available > 0 &&
        planRail.offsetHeight + planProgress.offsetHeight + 14 <= available;
    }

    if (canPin) {
      if (!planPinned) planRail.scrollLeft = 0;

      planSection.classList.add("is-plan-pinned");
      planSection.style.setProperty("--promote-pin-top", planTopOffset + "px");
      planSection.style.setProperty("--promote-pin-height", available + "px");
      planPin.style.height = planDistance + available + "px";
      planPinned = true;
    } else {
      var lastProgress = planProgress.style.width
        ? parseFloat(planProgress.style.width) / 100
        : 0;

      planSection.classList.remove("is-plan-pinned");
      planSection.style.removeProperty("--promote-pin-top");
      planSection.style.removeProperty("--promote-pin-height");
      planPin.style.height = "";
      planRail.style.removeProperty("transform");
      planPinned = false;
      planDistance = 0;

      //   Keep the native rail at the same card when a resize turns the
      //   pinned effect off.
      if (lastProgress > 0) {
        var restore = lastProgress;
        window.requestAnimationFrame(function () {
          var max = planRail.scrollWidth - planRail.clientWidth;
          if (max > 2) planRail.scrollLeft = restore * max;
        });
      }

      updatePlanProgressFromRail();
    }
  }

  /* ---------- advert rail scroll drift ---------- */
  function updateAdDrift() {
    if (!adRail) return;

    if (reduceMotion || adRail.scrollWidth <= adRail.clientWidth + 2) {
      adRail.style.removeProperty("--rail-drift");
      return;
    }

    var rect = adRail.getBoundingClientRect();
    var viewport = window.innerHeight || 0;

    if (!rect.height || rect.bottom < 0 || rect.top > viewport) {
      adRail.style.setProperty("--rail-drift", "0px");
      return;
    }

    var progress = (viewport - rect.top) / (viewport + rect.height);
    progress = Math.max(0, Math.min(1, progress));
    var drift = (0.5 - progress) * 36;
    adRail.style.setProperty("--rail-drift", drift.toFixed(1) + "px");
  }

  function updateRails() {
    updatePlanRail();
    updateAdDrift();
  }

  function focusPlanCard(event) {
    if (!planPinned || !planPin || !planStick || !planRail) return;

    var card =
      event.target && event.target.closest
        ? event.target.closest(".promote-plan")
        : null;
    if (!card) return;

    var max = planRail.scrollWidth - planStick.clientWidth;
    if (max <= 2) return;

    //   The rail is translated rather than scrolled while pinned, so bring the
    //   page to the focused card. This keeps keyboard focus visible instead of
    //   letting it disappear off the side of the translated rail.
    var target = (card.offsetLeft - planRail.offsetLeft) / max;
    target = Math.max(0, Math.min(1, target));

    var pinRect = planPin.getBoundingClientRect();
    var total = planPin.offsetHeight - planStick.offsetHeight;
    if (total <= 0) return;

    var current = Math.max(
      0,
      Math.min(1, (planTopOffset - pinRect.top) / total)
    );
    if (Math.abs(target - current) < 0.01) return;

    window.scrollTo({
      top:
        planPin.getBoundingClientRect().top +
        window.scrollY -
        planTopOffset +
        target * total,
      behavior: reduceMotion ? "auto" : "smooth"
    });
  }

  function requestRailUpdate() {
    if (railTicking) return;
    railTicking = true;
    window.requestAnimationFrame(function () {
      railTicking = false;
      updateRails();
    });
  }

  if (planRail || adRail) {
    window.addEventListener("scroll", requestRailUpdate, { passive: true });
    window.addEventListener(
      "resize",
      function () {
        measurePlanRail();
        requestRailUpdate();
      },
      { passive: true }
    );

    if (planRail) {
      planRail.addEventListener("scroll", updatePlanProgressFromRail, {
        passive: true
      });
      planRail.addEventListener("focusin", focusPlanCard);
    }

    measurePlanRail();
    updateRails();

    window.addEventListener(
      "load",
      function () {
        measurePlanRail();
        requestRailUpdate();
      },
      { once: true }
    );

    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(function () {
        measurePlanRail();
        requestRailUpdate();
      });
    }
  }

  /* ---------- cursor-reactive plan cards ---------- */
  if (finePointer && !reduceMotion) {
    var tiltCards = Array.prototype.slice.call(
      page.querySelectorAll("[data-tilt]")
    );

    tiltCards.forEach(function (card) {
      var frame = null;
      var next = null;

      function paint() {
        frame = null;
        if (!next) return;
        var max = card.classList.contains("is-featured") ? 4.2 : 2.8;
        var x = next.x;
        var y = next.y;

        card.style.setProperty("--tilt-x", ((0.5 - y) * max).toFixed(2) + "deg");
        card.style.setProperty("--tilt-y", ((x - 0.5) * max).toFixed(2) + "deg");
        card.style.setProperty("--spot-x", (x * 100).toFixed(1) + "%");
        card.style.setProperty("--spot-y", (y * 100).toFixed(1) + "%");
      }

      function onMove(event) {
        if (
          event.pointerType &&
          event.pointerType !== "mouse" &&
          event.pointerType !== "pen"
        ) {
          return;
        }

        var rect = card.getBoundingClientRect();
        if (!rect.width || !rect.height) return;

        next = {
          x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
          y: Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height))
        };

        if (!frame) frame = window.requestAnimationFrame(paint);
      }

      function reset() {
        next = null;
        card.style.setProperty("--tilt-x", "0deg");
        card.style.setProperty("--tilt-y", "0deg");
        card.style.setProperty("--spot-x", "50%");
        card.style.setProperty("--spot-y", "50%");
      }

      card.addEventListener("pointermove", onMove);
      card.addEventListener("pointerleave", reset);
      card.addEventListener("pointercancel", reset);
      card.addEventListener("blur", reset, true);
    });
  }

  /* ---------- hero media parallax ---------- */
  var heroMedia = page.querySelector("[data-hero-media]");
  if (heroMedia && finePointer && !reduceMotion) {
    var heroFrame = heroMedia.querySelector(".promote-hero-frame");

    heroMedia.addEventListener("pointermove", function (event) {
      if (event.pointerType && event.pointerType !== "mouse") return;
      var rect = heroMedia.getBoundingClientRect();
      if (!rect.width || !rect.height) return;

      var x = (event.clientX - rect.left) / rect.width - 0.5;
      var y = (event.clientY - rect.top) / rect.height - 0.5;

      heroFrame.style.setProperty("--hero-x", (x * 12).toFixed(1) + "px");
      heroFrame.style.setProperty("--hero-y", (y * 9).toFixed(1) + "px");
    });

    heroMedia.addEventListener("pointerleave", function () {
      heroFrame.style.setProperty("--hero-x", "0px");
      heroFrame.style.setProperty("--hero-y", "0px");
    });
  }

  /* ---------- plan picker -> live summary + WhatsApp preview ---------- */
  var radios = Array.prototype.slice.call(
    page.querySelectorAll("[data-plan-radio]")
  );
  var selectedName = page.querySelector("[data-selected-plan-name]");
  var selectedPrice = page.querySelector("[data-selected-plan-price]");
  var handoffName = page.querySelector("[data-handoff-plan]");
  var handoffPrice = page.querySelector("[data-handoff-price]");

  function syncPlan(radio) {
    radios.forEach(function (item) {
      var option = item.closest(".promote-plan-option");
      if (option) option.classList.toggle("is-selected", item.checked);
    });

    var name = radio.getAttribute("data-plan-name") || "";
    var price = radio.getAttribute("data-plan-price") || "";

    if (selectedName) selectedName.textContent = name;
    if (selectedPrice) selectedPrice.textContent = price;
    if (handoffName) handoffName.textContent = name;
    if (handoffPrice) handoffPrice.textContent = price;
  }

  if (radios.length) {
    radios.forEach(function (radio) {
      radio.addEventListener("change", function () {
        if (radio.checked) syncPlan(radio);
      });
    });

    var checked = page.querySelector("[data-plan-radio]:checked") || radios[0];
    if (checked) {
      if (!checked.checked) checked.checked = true;
      syncPlan(checked);
    }
  }
})();
