(function () {
  "use strict";

  /* ---------- in-story advert slideshow ----------
     blog/story_detail.html renders a fixed-size skeleton box in the reading
     column, before the story body. This script asks blog:story_ads for two
     random live adverts (image + text) and swaps the shimmer for a slideshow
     of exactly the same size, so nothing in the advert can push the story
     text around. The reader steps between the creatives with the arrows, the
     dots, the keyboard, or a swipe.

     Nodes are built with textContent and setAttribute only -- the response is
     JSON, so an advert heading/body is never parsed as markup. */
  function init() {
    var slot = document.querySelector("[data-story-ad]");
    if (!slot) return;

    var skeleton = slot.querySelector("[data-story-ad-skeleton]");
    var stage = slot.querySelector("[data-story-ad-carousel]");
    var endpoint = slot.dataset.endpoint;
    var fallbackImage = slot.dataset.fallbackImage || "";
    if (!endpoint || !stage) return;

    function hideSlot() {
      slot.hidden = true;
      slot.setAttribute("aria-busy", "false");
    }

    function makeMedia(ad) {
      var tag = ad.url ? "a" : "div";
      var media = document.createElement(tag);
      media.className = "story-ad-media";
      if (ad.url) {
        media.href = ad.url;
        media.target = "_blank";
        media.rel = "noopener noreferrer nofollow sponsored";
      }

      var image = document.createElement("img");
      image.className = "story-ad-image";
      image.src = ad.image;
      image.alt = ad.heading || "Advertisement";
      image.loading = "lazy";
      image.decoding = "async";
      image.addEventListener("error", function () {
        if (fallbackImage && image.src !== fallbackImage) {
          image.src = fallbackImage;
        }
      });
      media.appendChild(image);
      return media;
    }

    function makeCopy(ad) {
      var copy = document.createElement("div");
      copy.className = "story-ad-copy";

      var label = document.createElement("span");
      label.className = "story-ad-tag";
      label.textContent = "Sponsored";
      copy.appendChild(label);

      if (ad.heading) {
        var heading = document.createElement("h3");
        heading.className = "story-ad-heading";
        heading.textContent = ad.heading;
        copy.appendChild(heading);
      }

      if (ad.body) {
        var text = document.createElement("p");
        text.className = "story-ad-text";
        text.textContent = ad.body;
        copy.appendChild(text);
      }

      return copy;
    }

    function makeSlide(ad, index, total) {
      var slide = document.createElement("article");
      slide.className = "story-ad-slide";
      slide.setAttribute("role", "group");
      slide.setAttribute("aria-roledescription", "slide");
      slide.setAttribute("aria-label", "Advert " + (index + 1) + " of " + total);
      slide.appendChild(makeMedia(ad));
      slide.appendChild(makeCopy(ad));
      return slide;
    }

    function render(ads) {
      if (!ads.length) {
        hideSlot();
        return;
      }

      stage.replaceChildren();

      var track = document.createElement("div");
      track.className = "story-ad-track";
      var slides = ads.map(function (ad, index) {
        var slide = makeSlide(ad, index, ads.length);
        track.appendChild(slide);
        return slide;
      });
      stage.appendChild(track);

      var current = 0;
      var dots = [];

      function goTo(next) {
        current = (next + slides.length) % slides.length;
        track.style.transform = "translateX(-" + current * 100 + "%)";
        slides.forEach(function (slide, index) {
          var active = index === current;
          slide.classList.toggle("is-active", active);
          slide.setAttribute("aria-hidden", active ? "false" : "true");
          /* an inactive slide must not swallow a tab stop */
          slide.toggleAttribute("inert", !active);
        });
        dots.forEach(function (dot, index) {
          var active = index === current;
          dot.classList.toggle("is-active", active);
          dot.setAttribute("aria-current", active ? "true" : "false");
        });
      }

      if (slides.length > 1) {
        var nav = document.createElement("div");
        nav.className = "story-ad-nav";

        var prev = document.createElement("button");
        prev.type = "button";
        prev.className = "story-ad-arrow story-ad-prev";
        prev.setAttribute("aria-label", "Previous advert");
        prev.innerHTML =
          '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 5l-7 7 7 7"/></svg>';
        prev.addEventListener("click", function () { goTo(current - 1); });

        var next = document.createElement("button");
        next.type = "button";
        next.className = "story-ad-arrow story-ad-next";
        next.setAttribute("aria-label", "Next advert");
        next.innerHTML =
          '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 5l7 7-7 7"/></svg>';
        next.addEventListener("click", function () { goTo(current + 1); });

        nav.append(prev, next);
        stage.appendChild(nav);

        var dotRow = document.createElement("div");
        dotRow.className = "story-ad-dots";
        ads.forEach(function (ad, index) {
          var dot = document.createElement("button");
          dot.type = "button";
          dot.className = "story-ad-dot";
          dot.setAttribute("aria-label", "Go to advert " + (index + 1));
          dot.addEventListener("click", function () { goTo(index); });
          dotRow.appendChild(dot);
          dots.push(dot);
        });
        stage.appendChild(dotRow);

        /* keyboard: the dots/arrows are real buttons, so arrow keys only add
           a shortcut while the carousel has focus */
        stage.addEventListener("keydown", function (event) {
          if (event.key === "ArrowLeft") {
            event.preventDefault();
            goTo(current - 1);
          } else if (event.key === "ArrowRight") {
            event.preventDefault();
            goTo(current + 1);
          }
        });

        /* touch/pointer swipe */
        var startX = null;
        stage.addEventListener("pointerdown", function (event) {
          if (event.pointerType === "mouse") return;
          startX = event.clientX;
        });
        stage.addEventListener("pointerup", function (event) {
          if (startX === null) return;
          var delta = event.clientX - startX;
          startX = null;
          if (Math.abs(delta) < 40) return;
          goTo(current + (delta < 0 ? 1 : -1));
        });
      }

      goTo(0);

      if (skeleton) skeleton.hidden = true;
      stage.hidden = false;
      slot.setAttribute("aria-busy", "false");
    }

    fetch(endpoint, {
      method: "GET",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "X-Requested-With": "XMLHttpRequest"
      }
    })
      .then(function (response) {
        if (!response.ok) throw new Error("Advert request failed: " + response.status);
        return response.json();
      })
      .then(function (payload) {
        if (!payload || !Array.isArray(payload.ads)) {
          throw new Error("Advert response was invalid.");
        }
        render(payload.ads);
      })
      .catch(hideSlot);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
