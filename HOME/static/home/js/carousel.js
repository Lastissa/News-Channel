(function () {
  "use strict";

  var hero = document.getElementById("hero-carousel");
  if (!hero) return;

  var slides = Array.prototype.slice.call(hero.querySelectorAll(".hero-slide"));
  if (slides.length < 2) return;

  var selectorCards = Array.prototype.slice.call(hero.querySelectorAll(".hero-selector-card"));
  var selectorTrack = hero.querySelector(".hero-selector-track");
  var current = 0;
  var timer = null;
  var interval = parseInt(hero.getAttribute("data-autoplay"), 10) || 6000;
  var reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var swipeStartX = null;
  var touchStartX = null;
  var suppressClick = false;
  var progressBar = document.querySelector(".carousel-progress-fill");
  var progressTimer = null;
  var progressStart = Date.now();

  function scrollActiveCardIntoView(card) {
    if (!card || !selectorTrack) return;
    if (selectorTrack.scrollWidth <= selectorTrack.clientWidth + 1) return;
    var trackRect = selectorTrack.getBoundingClientRect();
    var cardRect = card.getBoundingClientRect();
    var offset = (cardRect.left - trackRect.left) - (trackRect.width / 2) + (cardRect.width / 2);
    selectorTrack.scrollTo({ left: selectorTrack.scrollLeft + offset, behavior: reducedMotion ? "auto" : "smooth" });
  }

  function syncSelector() {
    selectorCards.forEach(function (card, index) {
      var active = index === current;
      card.classList.toggle("is-active", active);
      card.setAttribute("aria-selected", active ? "true" : "false");
      card.setAttribute("tabindex", active ? "0" : "-1");
      if (active) scrollActiveCardIntoView(card);
    });
  }

  function goTo(index) {
    slides[current].classList.remove("is-active");
    current = (index + slides.length) % slides.length;
    slides[current].classList.add("is-active");
    syncSelector();
    if (progressBar) { progressBar.style.width = "0%"; progressStart = Date.now(); }
  }

  function next() { goTo(current + 1); }
  function prev() { goTo(current - 1); }

  function updateProgress() {
    if (reducedMotion || !progressBar) return;
    var elapsed = Date.now() - progressStart;
    var pct = Math.min((elapsed / interval) * 100, 100);
    progressBar.style.width = pct + "%";
  }

  function stop() {
    if (timer) { window.clearInterval(timer); timer = null; }
    if (progressTimer) { window.clearInterval(progressTimer); progressTimer = null; }
  }

  function start() {
    if (reducedMotion) return;
    stop();
    progressStart = Date.now();
    if (progressBar) progressBar.style.width = "0%";
    progressTimer = window.setInterval(updateProgress, 50);
    timer = window.setInterval(next, interval);
  }

  selectorCards.forEach(function (card, index) {
    card.addEventListener("click", function () { goTo(index); start(); });
    card.addEventListener("keydown", function (event) {
      if (event.key === "ArrowRight" || event.key === "ArrowDown") {
        event.preventDefault();
        goTo(index + 1);
        start();
        if (selectorCards[current]) selectorCards[current].focus();
      } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
        event.preventDefault();
        goTo(index - 1);
        start();
        if (selectorCards[current]) selectorCards[current].focus();
      }
    });
  });

  hero.addEventListener("pointerdown", function (event) {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    if (event.target.closest(".hero-selector")) return;
    swipeStartX = event.clientX;
  });

  hero.addEventListener("pointerup", function (event) {
    if (swipeStartX === null) return;
    var delta = event.clientX - swipeStartX;
    /* a drag must not count as a click on the full-slide story link */
    if (Math.abs(delta) > 10) {
      suppressClick = true;
      window.setTimeout(function () { suppressClick = false; }, 0);
    }
    if (Math.abs(delta) > 60) {
      if (delta < 0) next(); else prev();
      start();
    }
    swipeStartX = null;
  });

  hero.addEventListener("click", function (event) {
    if (suppressClick) { event.preventDefault(); event.stopPropagation(); }
  }, true);

  hero.addEventListener("pointerleave", function () {
    swipeStartX = null;
  });

  hero.addEventListener("touchstart", function (event) {
    if (event.target.closest(".hero-selector")) return;
    if (event.touches && event.touches[0]) {
      touchStartX = event.touches[0].clientX;
    }
  }, { passive: true });

  hero.addEventListener("touchend", function (event) {
    if (touchStartX === null) return;
    var endX = event.changedTouches && event.changedTouches[0] ? event.changedTouches[0].clientX : touchStartX;
    var delta = endX - touchStartX;
    if (Math.abs(delta) > 50) {
      if (delta < 0) next(); else prev();
      start();
    }
    touchStartX = null;
  }, { passive: true });

  hero.addEventListener("wheel", function (event) {
    if (event.target.closest(".hero-selector")) return;
    if (Math.abs(event.deltaX) <= Math.abs(event.deltaY)) return;
    event.preventDefault();
    if (event.deltaX < 0) next(); else prev();
    start();
  }, { passive: false });

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) stop(); else start();
  });

  syncSelector();
  start();
})();
