(function () {
  "use strict";

  var page = document.querySelector(".editorial-page");
  var roster = document.querySelector(".editorial-roster");
  if (!page || !roster) return;

  var cards = Array.prototype.slice.call(roster.querySelectorAll("[data-journalist-card]"));
  var search = roster.querySelector("[data-journalist-search]");
  var clearSearch = roster.querySelector("[data-search-clear]");
  var searchStatus = roster.querySelector("[data-search-status]");
  var searchEmpty = roster.querySelector("[data-search-empty]");
  var reduceMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  var numberFormatter = new Intl.NumberFormat();

  function normalize(value) {
    return (value || "")
      .toLocaleLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .trim();
  }

  if (search) {
    function filterJournalists() {
      var query = normalize(search.value);
      var visibleCount = 0;

      if (clearSearch) clearSearch.hidden = !search.value;
      cards.forEach(function (card) {
        var isMatch = normalize(card.getAttribute("data-search-text")).indexOf(query) !== -1;
        var wasHidden = card.hidden;
        card.hidden = !isMatch;
        if (isMatch) {
          visibleCount += 1;
          if (wasHidden && query && !reduceMotionQuery.matches && card.animate) {
            card.animate(
              [
                { opacity: 0, transform: "translateY(8px)" },
                { opacity: 1, transform: "translateY(0)" }
              ],
              { duration: 260, easing: "cubic-bezier(.2, .65, .3, 1)" }
            );
          }
        }
      });

      if (searchStatus) {
        searchStatus.textContent =
          "Showing " + visibleCount + " of " + cards.length + " " +
          (cards.length === 1 ? "journalist" : "journalists");
      }
      if (searchEmpty) searchEmpty.hidden = visibleCount !== 0;
    }

    search.addEventListener("input", filterJournalists);
    search.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      event.preventDefault();
      search.value = "";
      filterJournalists();
    });

    if (clearSearch) {
      clearSearch.addEventListener("click", function () {
        search.value = "";
        filterJournalists();
        search.focus();
      });
    }

    document.addEventListener("keydown", function (event) {
      if (
        event.key === "/" &&
        !event.altKey &&
        !event.ctrlKey &&
        !event.metaKey &&
        !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)
      ) {
        event.preventDefault();
        search.focus();
      }
    });
  }

  var counters = Array.prototype.slice.call(page.querySelectorAll("[data-count-up]"));

  function showCounterFinal(counter) {
    counter.textContent = numberFormatter.format(Number(counter.dataset.countUp) || 0);
    counter.classList.remove("is-counting");
    counter.classList.add("is-counted");
  }

  function animateCounter(counter) {
    if (counter.dataset.countStarted === "true" || document.visibilityState !== "visible") return;

    var target = Number(counter.dataset.countUp);
    if (!Number.isFinite(target) || target <= 0 || reduceMotionQuery.matches) {
      counter.dataset.countStarted = "true";
      showCounterFinal(counter);
      return;
    }

    counter.dataset.countStarted = "true";
    var startedAt = 0;
    var duration = Math.min(1800, Math.max(900, 900 + Math.log10(target + 1) * 220));
    counter.textContent = "00";
    counter.classList.add("is-counting");

    function step(timestamp) {
      if (document.visibilityState !== "visible") {
        counter.dataset.countStarted = "false";
        return;
      }
      if (!startedAt) startedAt = timestamp;
      var progress = Math.min(1, (timestamp - startedAt) / duration);
      var eased = 1 - Math.pow(1 - progress, 3);
      counter.textContent = numberFormatter.format(Math.min(target, Math.floor(target * eased)));

      if (progress < 1) {
        window.requestAnimationFrame(step);
      } else {
        showCounterFinal(counter);
      }
    }

    window.requestAnimationFrame(step);
  }

  function startVisibleCounters() {
    if (document.visibilityState !== "visible") return;
    counters.forEach(function (counter) {
      var bounds = counter.getBoundingClientRect();
      if (bounds.bottom > 0 && bounds.top < window.innerHeight) animateCounter(counter);
    });
  }

  if (reduceMotionQuery.matches) {
    cards.forEach(function (card) {
      card.classList.add("is-visible");
    });
    counters.forEach(showCounterFinal);
  } else {
    roster.classList.add("editorial-motion-ready");

    if ("IntersectionObserver" in window) {
      var revealObserver = new IntersectionObserver(
        function (entries, observer) {
          entries.forEach(function (entry) {
            if (!entry.isIntersecting) return;
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          });
        },
        { threshold: 0.08, rootMargin: "0px 0px -24px 0px" }
      );
      cards.forEach(function (card) {
        revealObserver.observe(card);
        var bounds = card.getBoundingClientRect();
        if (bounds.bottom > 0 && bounds.top < window.innerHeight) {
          card.classList.add("is-visible");
        }
      });
    } else {
      cards.forEach(function (card) {
        card.classList.add("is-visible");
      });
    }

    startVisibleCounters();
    document.addEventListener("visibilitychange", startVisibleCounters);
  }
})();
