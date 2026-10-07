(function () {
  "use strict";

  var page = document.querySelector(".editorial-page");
  var roster = document.querySelector(".editorial-roster");
  if (!page || !roster) return;

  var grid = roster.querySelector("#editorial-directory");
  var search = roster.querySelector("[data-journalist-search]");
  var clearSearch = roster.querySelector("[data-search-clear]");
  var searchStatus = roster.querySelector("[data-search-status]");
  var searchEmpty = roster.querySelector("[data-search-empty]");
  var pagination = roster.querySelector("[data-editorial-pagination]");
  var previousButton = roster.querySelector("[data-page-previous]");
  var nextButton = roster.querySelector("[data-page-next]");
  var pageStatus = roster.querySelector("[data-page-status]");
  var reduceMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  var numberFormatter = new Intl.NumberFormat();
  var pageSize = Number(searchStatus && searchStatus.dataset.pageSize) || 5;
  var currentPage = Number(pageStatus && pageStatus.dataset.currentPage) || 1;
  var currentTotal = Number(searchStatus && searchStatus.dataset.total) || 0;
  var requestSequence = 0;
  var activeRequest = null;
  var searchTimer = 0;
  var lastCardsMarkup = grid ? grid.innerHTML : "";

  function updateCards() {
    var cards = Array.prototype.slice.call(grid.querySelectorAll("[data-journalist-card]"));
    cards.forEach(function (card, index) {
      if (reduceMotionQuery.matches) {
        card.classList.add("is-visible");
        return;
      }
      card.classList.remove("is-visible");
      card.style.setProperty("--editorial-card-index", String(index));
      window.requestAnimationFrame(function () {
        window.requestAnimationFrame(function () {
          card.classList.add("is-visible");
        });
      });
    });
  }

  function showSkeletons() {
    var skeleton = "";
    for (var index = 0; index < 5; index += 1) {
      skeleton +=
        '<li class="editorial-card editorial-skeleton-card" aria-hidden="true">' +
          '<span class="editorial-skeleton-avatar"></span>' +
          '<span class="editorial-skeleton-line editorial-skeleton-name"></span>' +
          '<span class="editorial-skeleton-line editorial-skeleton-copy"></span>' +
          '<span class="editorial-skeleton-line editorial-skeleton-copy-short"></span>' +
          '<span class="editorial-skeleton-story">' +
            '<span class="editorial-skeleton-image"></span>' +
            '<span class="editorial-skeleton-story-copy">' +
              '<span class="editorial-skeleton-line editorial-skeleton-copy"></span>' +
              '<span class="editorial-skeleton-line editorial-skeleton-copy-short"></span>' +
            '</span>' +
          '</span>' +
        '</li>';
    }
    grid.innerHTML = skeleton;
    grid.setAttribute("aria-busy", "true");
    if (searchEmpty) searchEmpty.hidden = true;
    if (pagination) pagination.hidden = true;
  }

  function updatePagination(data) {
    currentPage = data.page;
    currentTotal = data.total;
    if (searchStatus) {
      var firstResult = data.total ? (data.page - 1) * pageSize + 1 : 0;
      var lastResult = Math.min(data.page * pageSize, data.total);
      searchStatus.textContent =
        "Showing " + firstResult + "–" + lastResult + " of " + data.total +
        " " + (data.total === 1 ? "journalist" : "journalists");
    }
    if (pageStatus) {
      pageStatus.textContent = "Page " + data.page + " of " + data.pages;
    }
    if (previousButton) previousButton.disabled = !data.has_previous;
    if (nextButton) nextButton.disabled = !data.has_next;
    if (pagination) pagination.hidden = data.pages <= 1;
    if (searchEmpty) searchEmpty.hidden = data.total !== 0;
  }

  function loadPage(pageNumber) {
    if (activeRequest) activeRequest.abort();
    var controller = "AbortController" in window ? new AbortController() : null;
    activeRequest = controller;
    var sequence = ++requestSequence;
    var url = new URL(window.location.href);
    url.searchParams.set("page", String(pageNumber));
    var query = search ? search.value.trim() : "";
    if (query) url.searchParams.set("q", query);
    else url.searchParams.delete("q");

    showSkeletons();
    if (searchStatus) searchStatus.textContent = "Loading journalists…";
    if (pageStatus) pageStatus.textContent = "Loading…";

    var options = {
      headers: { "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin"
    };
    if (controller) options.signal = controller.signal;

    fetch(url.toString(), options)
      .then(function (response) {
        if (!response.ok) throw new Error("Journalist request failed with status " + response.status);
        return response.json();
      })
      .then(function (data) {
        if (sequence !== requestSequence) return;
        grid.innerHTML = data.cards_html;
        lastCardsMarkup = data.cards_html;
        grid.removeAttribute("aria-busy");
        updatePagination(data);
        updateCards();
        var canonicalUrl = new URL(window.location.href);
        if (query) canonicalUrl.searchParams.set("q", query);
        else canonicalUrl.searchParams.delete("q");
        if (data.page > 1) canonicalUrl.searchParams.set("page", String(data.page));
        else canonicalUrl.searchParams.delete("page");
        window.history.replaceState({}, "", canonicalUrl);
      })
      .catch(function (error) {
        if (error.name === "AbortError" || sequence !== requestSequence) return;
        grid.innerHTML = lastCardsMarkup;
        grid.removeAttribute("aria-busy");
        if (searchStatus) {
          var start = currentTotal ? (currentPage - 1) * pageSize + 1 : 0;
          var end = Math.min(currentPage * pageSize, currentTotal);
          searchStatus.textContent =
            "Couldn’t load journalists. Showing " + start + "–" + end + " of " + currentTotal + ".";
        }
        if (pageStatus) pageStatus.textContent = "Page " + currentPage;
        if (pagination) pagination.hidden = false;
        updateCards();
      });
  }

  if (grid && search) {
    search.addEventListener("input", function () {
      if (clearSearch) clearSearch.hidden = !search.value;
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(function () {
        loadPage(1);
      }, 280);
    });

    search.addEventListener("keydown", function (event) {
      if (event.key !== "Escape" || !search.value) return;
      event.preventDefault();
      search.value = "";
      if (clearSearch) clearSearch.hidden = true;
      window.clearTimeout(searchTimer);
      loadPage(1);
    });

    if (clearSearch) {
      clearSearch.addEventListener("click", function () {
        search.value = "";
        clearSearch.hidden = true;
        window.clearTimeout(searchTimer);
        loadPage(1);
        search.focus();
      });
    }

    if (previousButton) {
      previousButton.addEventListener("click", function () {
        if (currentPage > 1) loadPage(currentPage - 1);
      });
    }
    if (nextButton) {
      nextButton.addEventListener("click", function () {
        if (currentPage * pageSize < currentTotal) loadPage(currentPage + 1);
      });
    }

    updateCards();
    window.addEventListener("popstate", function () {
      var url = new URL(window.location.href);
      search.value = url.searchParams.get("q") || "";
      if (clearSearch) clearSearch.hidden = !search.value;
      loadPage(Number(url.searchParams.get("page")) || 1);
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
      if (progress < 1) window.requestAnimationFrame(step);
      else showCounterFinal(counter);
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
    counters.forEach(showCounterFinal);
  } else {
    roster.classList.add("editorial-motion-ready");
    startVisibleCounters();
    document.addEventListener("visibilitychange", startVisibleCounters);
  }
})();
