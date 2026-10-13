/* Document reader behaviour, shared by the author handbook and the privacy policy.
   Does four small things: draws a reading progress line, marks the section being
   read in the contents, turns the contents into a one-line bar on phones, and eases
   sections in as they arrive. If this file fails to load, the page is still a
   complete, readable document. */
(function () {
  "use strict";

  var root = document.querySelector("[data-doc]");
  if (!root) return;
  root.classList.add("doc-js");

  var main = root.querySelector(".doc-main");
  var toc = root.querySelector(".doc-toc");
  var toggle = root.querySelector(".doc-toc-toggle");
  var currentLabel = root.querySelector("[data-doc-current]");
  var header = document.querySelector(".site-header");
  var phone = window.matchMedia("(max-width: 959.98px)");
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var links = [];
  var sections = [];
  [].slice.call(root.querySelectorAll(".doc-toc-list a[href^='#']")).forEach(function (a) {
    var target = document.getElementById(decodeURIComponent(a.getAttribute("href").slice(1)));
    if (target) {
      links.push(a);
      sections.push(target);
    }
  });

  function headerHeight() {
    return header ? header.offsetHeight : 64;
  }

  function barHeight() {
    return phone.matches && toggle ? toggle.offsetHeight : 0;
  }

  /* ---------- Contents bar on phones ---------- */
  function setOpen(open) {
    if (!toc || !toggle) return;
    toc.classList.toggle("is-open", open);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  }

  if (toc && toggle) {
    toggle.addEventListener("click", function () {
      setOpen(!toc.classList.contains("is-open"));
    });

    toc.addEventListener("click", function (event) {
      if (event.target.closest && event.target.closest(".doc-toc-list a")) setOpen(false);
    });

    document.addEventListener("click", function (event) {
      if (toc.classList.contains("is-open") && !toc.contains(event.target)) setOpen(false);
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && toc.classList.contains("is-open")) {
        setOpen(false);
        toggle.focus();
      }
    });

    var onBreakpoint = function () {
      if (!phone.matches) setOpen(false);
    };
    if (phone.addEventListener) phone.addEventListener("change", onBreakpoint);
    else if (phone.addListener) phone.addListener(onBreakpoint);
  }

  /* ---------- Which section is being read ---------- */
  var activeIndex = -2;

  function setActive(index) {
    if (index === activeIndex) return;
    activeIndex = index;

    links.forEach(function (a, i) {
      var on = i === index;
      a.classList.toggle("is-active", on);
      if (on) a.setAttribute("aria-current", "true");
      else a.removeAttribute("aria-current");
    });

    if (currentLabel) {
      currentLabel.textContent = index >= 0 ? links[index].textContent : "Start of page";
    }

    /* Keep the active link in view if the rail itself scrolls. */
    if (!phone.matches && toc && index >= 0 && toc.scrollHeight > toc.clientHeight) {
      var link = links[index];
      toc.scrollTop = link.offsetTop - (toc.clientHeight - link.offsetHeight) / 2;
    }
  }

  function currentSection() {
    var line = headerHeight() + barHeight() + 48;
    var found = -1;
    for (var i = 0; i < sections.length; i += 1) {
      if (sections[i].getBoundingClientRect().top <= line) found = i;
      else break;
    }
    return found;
  }

  /* ---------- Reading progress ---------- */
  function updateProgress() {
    if (!main) return;
    var rect = main.getBoundingClientRect();
    var top = headerHeight();
    var total = rect.height - (window.innerHeight - top) * 0.6;
    var p = total > 0 ? (top - rect.top) / total : 0;
    p = Math.max(0, Math.min(1, p));
    root.style.setProperty("--doc-p", p.toFixed(4));
  }

  var queued = false;
  function onScroll() {
    if (queued) return;
    queued = true;
    window.requestAnimationFrame(function () {
      queued = false;
      updateProgress();
      setActive(currentSection());
    });
  }

  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll);
  onScroll();

  /* ---------- Sections ease in ---------- */
  var blocks = [].slice.call(root.querySelectorAll(".doc-section"));

  function showAll() {
    blocks.forEach(function (block) {
      block.classList.add("is-in");
    });
  }

  if (reduceMotion || !("IntersectionObserver" in window)) {
    showAll();
  } else {
    var seen = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-in");
            seen.unobserve(entry.target);
          }
        });
      },
      { rootMargin: "0px 0px -6% 0px", threshold: 0 }
    );
    blocks.forEach(function (block) {
      seen.observe(block);
    });
  }
})();
