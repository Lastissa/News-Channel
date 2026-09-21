(function () {
  "use strict";

  var hero = document.getElementById("hero-carousel");
  if (!hero) return;

  var slides = Array.prototype.slice.call(hero.querySelectorAll(".hero-slide"));
  if (slides.length < 2) return;

  var dots = Array.prototype.slice.call(hero.querySelectorAll(".hero-dot"));
  var prevBtn = hero.querySelector(".hero-prev");
  var nextBtn = hero.querySelector(".hero-next");
  var current = 0;
  var timer = null;
  var interval = parseInt(hero.getAttribute("data-autoplay"), 10) || 6000;
  var reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var swipeStartX = null;
  var touchStartX = null;

  function goTo(index) {
    slides[current].classList.remove("is-active");
    if (dots[current]) dots[current].classList.remove("is-active");
    current = (index + slides.length) % slides.length;
    slides[current].classList.add("is-active");
    if (dots[current]) dots[current].classList.add("is-active");
  }

  function next() { goTo(current + 1); }
  function prev() { goTo(current - 1); }

  function start() {
    if (reducedMotion) return;
    stop();
    timer = window.setInterval(next, interval);
  }
  function stop() {
    if (timer) { window.clearInterval(timer); timer = null; }
  }

  if (nextBtn) nextBtn.addEventListener("click", function () { next(); start(); });
  if (prevBtn) prevBtn.addEventListener("click", function () { prev(); start(); });
  dots.forEach(function (dot, index) {
    dot.addEventListener("click", function () { goTo(index); start(); });
  });

  hero.addEventListener("pointerdown", function (event) {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    swipeStartX = event.clientX;
  });

  hero.addEventListener("pointerup", function (event) {
    if (swipeStartX === null) return;
    var delta = event.clientX - swipeStartX;
    if (Math.abs(delta) > 60) {
      if (delta < 0) next(); else prev();
      start();
    }
    swipeStartX = null;
  });

  hero.addEventListener("pointerleave", function () {
    swipeStartX = null;
  });

  hero.addEventListener("touchstart", function (event) {
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
    if (Math.abs(event.deltaX) <= Math.abs(event.deltaY)) return;
    event.preventDefault();
    if (event.deltaX < 0) next(); else prev();
    start();
  }, { passive: false });

  hero.addEventListener("mouseenter", stop);
  hero.addEventListener("mouseleave", start);
  hero.addEventListener("focusin", stop);
  hero.addEventListener("focusout", start);

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) stop(); else start();
  });

  start();
})();
