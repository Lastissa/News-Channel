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

  /* ---------- advert preview video ---------- */
  //   The poster is local, so the page paints without fetching the MP4. The
  //   button is the only way to start playback: no autoplay, no muted loop, and
  //   native controls take over as soon as the visitor chooses to watch.
  var previewVideo = page.querySelector("[data-preview-video]");
  var previewButton = page.querySelector("[data-preview-play]");
  var previewFrame = page.querySelector("[data-preview-frame]");

  if (previewVideo && previewButton && previewFrame) {
    var previewLabel = previewButton.querySelector(".promote-preview-play-label");

    var hidePreviewCover = function () {
      previewFrame.classList.add("is-preview-playing");
      previewButton.setAttribute("aria-hidden", "true");
      previewButton.tabIndex = -1;
    };

    var showPreviewCover = function (label) {
      previewFrame.classList.remove("is-preview-playing");
      previewButton.removeAttribute("aria-hidden");
      previewButton.tabIndex = 0;
      if (label && previewLabel) previewLabel.textContent = label;
    };

    previewButton.addEventListener("click", function () {
      if (typeof previewVideo.play !== "function") return;

      var playResult;
      try {
        playResult = previewVideo.play();
      } catch (error) {
        showPreviewCover();
        return;
      }

      hidePreviewCover();
      if (playResult && typeof playResult.catch === "function") {
        playResult.catch(function () {
          showPreviewCover();
          previewFrame.classList.remove("is-preview-playing");
        });
      }
      if (typeof previewVideo.focus === "function") {
        try {
          previewVideo.focus({ preventScroll: true });
        } catch (error) {
          // Older browsers do not accept the options object; focus is optional.
        }
      }
    });

    previewVideo.addEventListener("play", hidePreviewCover);
    previewVideo.addEventListener("ended", function () {
      showPreviewCover("Watch the preview again");
    });
    previewVideo.addEventListener("error", function () {
      showPreviewCover("Preview unavailable");
      previewButton.disabled = true;
    });
  }

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

  /* ---------- pinned horizontal rails: plans and the path ---------- */
  //   On small screens the plan cards and the path steps become horizontal
  //   rails. Rather than hiding the rest off the right edge, each rail sticks
  //   in the viewport while the page scrolls vertically, translating the
  //   cards horizontally. A visible progress line tells readers the rail
  //   exists and how much is left. Short viewports, reduced motion, and
  //   desktop keep the native swipe rail, so the effect is an enhancement,
  //   not a scroll trap.
  function createPinnedRail(config) {
    var section = config.section;
    var pin = config.pin;
    var stick = config.stick;
    var rail = config.rail;
    var progress = config.progress;
    var progressBox = config.progressBox;
    var nav = config.nav;
    var itemSelector = config.itemSelector;
    var pinnedClass = config.pinnedClass;
    var maxWidth = config.maxWidth || 980;
    var bottomGap = config.bottomGap == null ? 14 : config.bottomGap;
    var pinned = false;
    var distance = 0;
    var topOffset = 0;

    if (!section || !pin || !stick || !rail || !progress) return null;

    function setProgress(value) {
      value = Math.max(0, Math.min(1, value));
      progress.style.width = (value * 100).toFixed(2) + "%";
    }

    function updateProgressFromRail() {
      if (pinned) return;
      var max = rail.scrollWidth - rail.clientWidth;
      setProgress(max > 2 ? rail.scrollLeft / max : 0);
    }

    function update() {
      if (!pinned) {
        updateProgressFromRail();
        return;
      }

      var rect = pin.getBoundingClientRect();
      var total = pin.offsetHeight - stick.offsetHeight;

      if (total <= 0) {
        setProgress(0);
        return;
      }

      var elapsed = topOffset - rect.top;
      var value = Math.max(0, Math.min(1, elapsed / total));

      rail.style.transform =
        "translate3d(" + (-value * distance).toFixed(2) + "px, 0, 0)";
      setProgress(value);
    }

    function measure() {
      var rootStyles = getComputedStyle(document.documentElement);
      var headerHeight = parseFloat(rootStyles.getPropertyValue("--header-h"));
      if (isNaN(headerHeight) || headerHeight <= 0) headerHeight = 64;

      var canPin = false;
      var available = 0;

      if (
        !reduceMotion &&
        window.matchMedia &&
        window.matchMedia("(max-width: " + maxWidth + "px)").matches
      ) {
        var jumpHeight = nav ? nav.offsetHeight : 0;
        topOffset = headerHeight + 12 + jumpHeight + 8;
        available = window.innerHeight - topOffset;
        distance = Math.max(0, rail.scrollWidth - stick.clientWidth);

        canPin =
          distance > 2 &&
          available > 0 &&
          rail.offsetHeight +
            (progressBox ? progressBox.offsetHeight : 0) +
            bottomGap <=
            available;
      }

      if (canPin) {
        if (!pinned) rail.scrollLeft = 0;

        section.classList.add(pinnedClass);
        section.style.setProperty("--promote-pin-top", topOffset + "px");
        section.style.setProperty("--promote-pin-height", available + "px");
        pin.style.height = distance + available + "px";
        pinned = true;
      } else {
        var lastProgress = progress.style.width
          ? parseFloat(progress.style.width) / 100
          : 0;

        section.classList.remove(pinnedClass);
        section.style.removeProperty("--promote-pin-top");
        section.style.removeProperty("--promote-pin-height");
        pin.style.height = "";
        rail.style.removeProperty("transform");
        pinned = false;
        distance = 0;

        //   Keep the native rail at the same card when a resize turns the
        //   pinned effect off.
        if (lastProgress > 0) {
          var restore = lastProgress;
          window.requestAnimationFrame(function () {
            var max = rail.scrollWidth - rail.clientWidth;
            if (max > 2) rail.scrollLeft = restore * max;
          });
        }

        updateProgressFromRail();
      }
    }

    function focusItem(event) {
      if (!pinned) return;

      var item =
        event.target && event.target.closest
          ? event.target.closest(itemSelector)
          : null;
      if (!item) return;

      var max = rail.scrollWidth - stick.clientWidth;
      if (max <= 2) return;

      //   The rail is translated rather than scrolled while pinned, so bring
      //   the page to the focused card. This keeps keyboard focus visible
      //   instead of letting it disappear off the side of the translated rail.
      var target = (item.offsetLeft - rail.offsetLeft) / max;
      target = Math.max(0, Math.min(1, target));

      var pinRect = pin.getBoundingClientRect();
      var total = pin.offsetHeight - stick.offsetHeight;
      if (total <= 0) return;

      var current = Math.max(
        0,
        Math.min(1, (topOffset - pinRect.top) / total)
      );
      if (Math.abs(target - current) < 0.01) return;

      window.scrollTo({
        top:
          pin.getBoundingClientRect().top +
          window.scrollY -
          topOffset +
          target * total,
        behavior: reduceMotion ? "auto" : "smooth"
      });
    }

    rail.addEventListener("scroll", updateProgressFromRail, {
      passive: true
    });
    rail.addEventListener("focusin", focusItem);

    return { measure: measure, update: update };
  }

  var planRailController = createPinnedRail({
    section: page.querySelector(".promote-plans"),
    pin: page.querySelector("[data-plan-pin]"),
    stick: page.querySelector(".promote-plans-stick"),
    rail: page.querySelector("[data-plan-rail]"),
    progress: page.querySelector("[data-plan-progress]"),
    progressBox: page.querySelector(".promote-plan-progress"),
    nav: page.querySelector("[data-promote-nav]"),
    itemSelector: ".promote-plan",
    pinnedClass: "is-plan-pinned"
  });

  var stepsRailController = createPinnedRail({
    section: page.querySelector(".promote-how"),
    pin: page.querySelector("[data-steps-pin]"),
    stick: page.querySelector(".promote-steps-stick"),
    rail: page.querySelector("[data-steps-rail]"),
    progress: page.querySelector("[data-steps-progress]"),
    progressBox: page.querySelector(".promote-steps-progress"),
    nav: page.querySelector("[data-promote-nav]"),
    itemSelector: ".promote-steps li",
    pinnedClass: "is-steps-pinned"
  });

  var pinnedRails = [planRailController, stepsRailController].filter(Boolean);
  var adRail = page.querySelector("[data-promote-ads]");
  var railTicking = false;

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
    pinnedRails.forEach(function (controller) {
      controller.update();
    });
    updateAdDrift();
  }

  function measureRails() {
    pinnedRails.forEach(function (controller) {
      controller.measure();
    });
  }

  function requestRailUpdate() {
    if (railTicking) return;
    railTicking = true;

    var done = false;
    var fallback = 0;

    function run() {
      if (done) return;
      done = true;
      if (fallback) window.clearTimeout(fallback);
      railTicking = false;
      updateRails();
    }

    window.requestAnimationFrame(run);
    //   Hidden tabs can suspend animation frames indefinitely. The timeout
    //   releases the latch and still paints the rail if the tab is visible
    //   but rAF is delayed by the browser.
    fallback = window.setTimeout(run, 120);
  }

  if (pinnedRails.length || adRail) {
    window.addEventListener("scroll", requestRailUpdate, { passive: true });
    window.addEventListener(
      "resize",
      function () {
        measureRails();
        requestRailUpdate();
      },
      { passive: true }
    );

    measureRails();
    updateRails();

    window.addEventListener(
      "load",
      function () {
        measureRails();
        requestRailUpdate();
      },
      { once: true }
    );

    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(function () {
        measureRails();
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
    var handoff = radio.getAttribute("data-plan-handoff-price") || price;

    if (selectedName) selectedName.textContent = name;
    if (selectedPrice) selectedPrice.textContent = price;
    if (handoffName) handoffName.textContent = name;
    if (handoffPrice) handoffPrice.textContent = handoff;
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
