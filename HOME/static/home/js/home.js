/* HOME PAGE BEHAVIOUR (HOME/templates/HOME/home.html)
   Bookmark, share, toast, theme and the newsletter popup stay in
   interactions.js / app.js. This file only owns what is new on the home page:
     1. hero slider (Swiper, self hosted in static/home/vendor/swiper)
     2. progress timers shown on the mobile segments and the desktop rail
     3. "Load more stories" key
     4. broken image fallback
   carousel.js and hero-teaser.js from base.html exit on their own here
   because the markup they look for no longer exists. */
(function () {
  "use strict";

  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- 4. broken image: drop the tag, the branded block underneath shows ---------- */
  document.addEventListener("error", function (event) {
    var img = event.target;
    if (img && img.tagName === "IMG" && img.hasAttribute("data-img-fallback")) img.remove();
  }, true);

  /* ---------- 1 + 2. hero ---------- */
  function initHero() {
    var hero = document.getElementById("hero-carousel");
    var el = hero && hero.querySelector("[data-lead]");
    if (!el || !window.Swiper) return;

    var slides = el.querySelectorAll(".swiper-slide");
    var count = slides.length;
    var delay = parseInt(hero.getAttribute("data-autoplay"), 10) || 7000;
    var segs = hero.querySelectorAll(".hp-seg");
    var railItems = hero.querySelectorAll(".hp-rail-item");
    var raf = 0, startedAt = 0, elapsed = 0, paused = false, running = false;

    var swiper = new window.Swiper(el, {
      loop: false,
      rewind: count > 1,
      speed: 650,
      grabCursor: count > 1,
      allowTouchMove: count > 1,
      watchSlidesProgress: true,
      keyboard: { enabled: true, onlyInViewport: true },
      a11y: { enabled: true, prevSlideMessage: "Previous story", nextSlideMessage: "Next story" },
      on: {
        progress: function (s) {
          /* soft parallax: each photo trails its slide a little */
          for (var i = 0; i < s.slides.length; i++) {
            s.slides[i].querySelector(".hp-slide-media").style.setProperty("--prog", s.slides[i].progress.toFixed(3));
          }
        },
        setTransition: function (s, dur) {
          for (var i = 0; i < s.slides.length; i++) {
            s.slides[i].querySelector(".hp-slide-media").style.transitionDuration = dur + "ms";
          }
        }
      }
    });

    hero.classList.add("is-ready");
    if (railItems.length) hero.classList.add("has-rail");
    if (count < 2) return;

    function paint(p) {
      var active = swiper.activeIndex;
      for (var i = 0; i < segs.length; i++) segs[i].style.setProperty("--p", i < active ? 1 : i === active ? p : 0);
      for (var j = 0; j < railItems.length; j++) railItems[j].style.setProperty("--p", j === active ? p : 0);
    }

    function tick(now) {
      if (paused) return;
      if (!startedAt) startedAt = now - elapsed;
      elapsed = now - startedAt;
      var p = Math.min(1, elapsed / delay);
      paint(p);
      if (p >= 1) { elapsed = 0; startedAt = 0; swiper.slideNext(); }
      raf = requestAnimationFrame(tick);
    }
    function play() {
      if (reduced || !paused && running) return;
      paused = false; running = true; startedAt = 0;
      cancelAnimationFrame(raf); raf = requestAnimationFrame(tick);
    }
    function pause() { paused = true; running = false; cancelAnimationFrame(raf); }

    swiper.on("slideChange", function () {
      hero.classList.add("is-running");
      elapsed = 0; startedAt = 0; paint(0);
      for (var i = 0; i < railItems.length; i++) {
        var on = i === swiper.activeIndex;
        railItems[i].classList.toggle("is-active", on);
        if (on) railItems[i].setAttribute("aria-current", "true"); else railItems[i].removeAttribute("aria-current");
      }
    });

    /* controls: any manual move restarts the timer on the new story */
    var prev = hero.querySelector("[data-lead-prev]"), next = hero.querySelector("[data-lead-next]");
    if (prev) prev.addEventListener("click", function () { swiper.slidePrev(); elapsed = 0; startedAt = 0; });
    if (next) next.addEventListener("click", function () { swiper.slideNext(); elapsed = 0; startedAt = 0; });
    railItems.forEach(function (item) {
      item.addEventListener("click", function () {
        swiper.slideTo(parseInt(item.getAttribute("data-index"), 10), 650);
        elapsed = 0; startedAt = 0;
      });
    });

    /* pause while the reader is looking or interacting */
    hero.addEventListener("mouseenter", pause);
    hero.addEventListener("mouseleave", function () { elapsed = 0; play(); });
    hero.addEventListener("focusin", pause);
    hero.addEventListener("focusout", function () { play(); });
    swiper.on("touchStart", pause);
    swiper.on("touchEnd", function () { elapsed = 0; play(); });
    document.addEventListener("visibilitychange", function () { if (document.hidden) pause(); else play(); });

    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (entries) {
        if (entries[0].isIntersecting) play(); else pause();
      }, { threshold: 0.35 }).observe(hero);
    } else {
      play();
    }
  }

  /* ---------- 3. load more ---------- */
  function initMore() {
    var wrap = document.querySelector("[data-more]");
    var grid = document.getElementById("story-grid");
    if (!wrap || !grid) return;

    var btn = wrap.querySelector("[data-more-btn]");
    var statusEl = wrap.querySelector("[data-more-status]");
    var loadedEl = wrap.querySelector("[data-more-loaded]");
    var totalEl = wrap.querySelector("[data-more-total]");
    var bar = wrap.querySelector("[data-more-bar]");
    var label = btn.querySelector(".hp-key-label");
    var idleLabel = label.textContent;
    var busy = false;

    /* the numbered pager stays as the no script fallback only */
    function say(msg, isError) {
      statusEl.textContent = msg || "";
      statusEl.classList.toggle("is-error", !!isError);
    }

    /* the first .page-meta is the server's page-1 marker, remove it up front */
    Array.prototype.forEach.call(grid.querySelectorAll(".page-meta"), function (n) { n.remove(); });

    btn.addEventListener("click", function () {
      if (busy) return;
      busy = true;
      btn.classList.add("is-loading");
      btn.setAttribute("aria-busy", "true");
      label.textContent = "Loading stories";
      say("");

      var params = new URLSearchParams();
      params.set("page", btn.getAttribute("data-next-page"));
      if (btn.getAttribute("data-query")) params.set("q", btn.getAttribute("data-query"));
      if (btn.getAttribute("data-category")) params.set("category", btn.getAttribute("data-category"));

      fetch(btn.getAttribute("data-endpoint") + "?" + params.toString(), {
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" }
      })
        .then(function (res) {
          if (!res.ok) throw new Error("status " + res.status);
          return res.text();
        })
        .then(function (html) {
          var tpl = document.createElement("template");
          tpl.innerHTML = html;
          var meta = tpl.content.querySelector(".page-meta");
          var cards = Array.prototype.slice.call(tpl.content.querySelectorAll(".hp-card"));
          var before = grid.querySelectorAll(".hp-card").length;

          cards.forEach(function (card) {
            card.classList.remove("hp-card--lead");  /* only page 1 has a lead card */
            grid.appendChild(card);
          });

          var hasMore = meta && meta.getAttribute("data-has-more") === "true";
          var loaded = meta ? parseInt(meta.getAttribute("data-loaded"), 10) : before + cards.length;
          var total = meta ? parseInt(meta.getAttribute("data-total"), 10) : loaded;
          if (loadedEl) loadedEl.textContent = loaded;
          if (totalEl) totalEl.textContent = total;
          if (bar && total) bar.style.setProperty("--w", Math.round((loaded / total) * 100) + "%");

          /* keyboard users land on the first new story */
          var firstNew = cards[0] && cards[0].querySelector("a.hp-card-title a, .hp-card-title a");
          if (firstNew) firstNew.focus({ preventScroll: true });

          if (hasMore) {
            btn.setAttribute("data-next-page", meta.getAttribute("data-next-page"));
            say(cards.length + " more stories added.");
          } else {
            wrap.classList.add("is-done");
            say("You have reached the end. That is every story.");
          }
        })
        .catch(function () {
          say("Could not load more stories. Check your connection and press the key again.", true);
        })
        .then(function () {
          busy = false;
          btn.classList.remove("is-loading");
          btn.removeAttribute("aria-busy");
          label.textContent = idleLabel;
        });
    });
  }

  function init() { initHero(); initMore(); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
