(function () {
  "use strict";

  /* ---------- in-story advert popup ----------
     blog/story_detail.html renders a hidden settings holder ([data-story-ad]).
     This script runs this loop for as long as the story stays open:

       1. GET blog:story_ads -> ONE advert (the server answers from a pool of
          three that it caches for two minutes, so this is not a DB hit)
       2. preload its image, so the popup never opens with an empty picture
       3. slide the popup up from the bottom-left corner; a bar along its
          bottom edge drains from right to left over data-show-seconds
       4. when the bar is empty, or the reader presses the close button, the
          popup slides away and is removed
       5. wait data-gap-seconds, then go back to 1 (closing an advert only
          skips the rest of that one; the next one still comes after the wait)

     The popup is a fixed card appended to <body>, so it takes no room in the
     reading column and nothing in the story can jump. The image, the heading
     and the text all sit inside ONE link, so tapping any of them opens the
     advert.

     Nodes are built with textContent and setAttribute only -- the response is
     JSON, so an advert heading/body is never parsed as markup. */

  var LEAVE_MS = 320;       /* keep in step with story-ad-out in story-ads.css */
  var IMAGE_WAIT_MS = 8000; /* a stalled image must not freeze the loop */

  function seconds(value, fallback) {
    var number = parseFloat(value);
    return isFinite(number) && number > 0 ? number : fallback;
  }

  function init() {
    var host = document.querySelector("[data-story-ad]");
    if (!host) return;

    var endpoint = host.dataset.endpoint;
    if (!endpoint) return;

    var fallbackImage = host.dataset.fallbackImage || "";
    var showMs = seconds(host.dataset.showSeconds, 10) * 1000;
    var gapMs = seconds(host.dataset.gapSeconds, 30) * 1000;
    var lastId = null;

    /* ----- 1. ask for one advert ----- */
    function requestAd() {
      var url = new URL(endpoint, window.location.href);
      if (lastId !== null) url.searchParams.set("last", lastId);

      return fetch(url.toString(), {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
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
          if (!payload || typeof payload !== "object") {
            throw new Error("Advert response was invalid.");
          }
          var ad = payload.ad;
          if (!ad || !ad.image) return null;
          lastId = ad.id === undefined ? null : ad.id;
          return ad;
        });
    }

    /* ----- 2. make sure the picture can be shown ----- */
    function probe(src) {
      return new Promise(function (resolve) {
        var image = new Image();
        var timer = window.setTimeout(function () { resolve(false); }, IMAGE_WAIT_MS);
        image.onload = function () { window.clearTimeout(timer); resolve(true); };
        image.onerror = function () { window.clearTimeout(timer); resolve(false); };
        image.src = src;
      });
    }

    function prepare(ad) {
      return probe(ad.image).then(function (ok) {
        if (ok) return { ad: ad, src: ad.image };
        if (!fallbackImage) return null;
        return probe(fallbackImage).then(function (fallbackOk) {
          return fallbackOk ? { ad: ad, src: fallbackImage } : null;
        });
      });
    }

    /* ----- 3. build and show the popup ----- */
    function buildPopup(ad, src) {
      var popup = document.createElement("aside");
      popup.className = "story-ad";
      popup.setAttribute("aria-label", "Ads");
      popup.style.setProperty("--story-ad-show", showMs + "ms");

      /* one link around picture + label + heading + text. An advert saved
         without a link still shows, it just is not clickable. */
      var link = document.createElement(ad.url ? "a" : "div");
      link.className = "story-ad-link";
      if (ad.url) {
        link.href = ad.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer nofollow sponsored";
      }

      var media = document.createElement("span");
      media.className = "story-ad-media";
      var image = document.createElement("img");
      image.className = "story-ad-image";
      image.src = src;
      /* the heading sits right beside it, so a description would be read twice */
      image.alt = "";
      image.decoding = "async";
      media.appendChild(image);
      link.appendChild(media);

      var copy = document.createElement("span");
      copy.className = "story-ad-copy";

      var tag = document.createElement("span");
      tag.className = "story-ad-tag";
      tag.textContent = "Ads";
      copy.appendChild(tag);

      if (ad.heading) {
        var heading = document.createElement("span");
        heading.className = "story-ad-heading";
        heading.textContent = ad.heading;
        copy.appendChild(heading);
      }

      if (ad.body) {
        var text = document.createElement("span");
        text.className = "story-ad-text";
        text.textContent = ad.body;
        copy.appendChild(text);
      }

      link.appendChild(copy);
      popup.appendChild(link);

      var close = document.createElement("button");
      close.type = "button";
      close.className = "story-ad-close";
      close.setAttribute("aria-label", "Close ad");
      var svgNs = "http://www.w3.org/2000/svg";
      var icon = document.createElementNS(svgNs, "svg");
      icon.setAttribute("viewBox", "0 0 14 14");
      icon.setAttribute("aria-hidden", "true");
      var cross = document.createElementNS(svgNs, "path");
      cross.setAttribute("d", "M2 2l10 10M12 2L2 12");
      icon.appendChild(cross);
      close.appendChild(icon);
      popup.appendChild(close);

      var timer = document.createElement("span");
      timer.className = "story-ad-timer";
      timer.setAttribute("aria-hidden", "true");
      var bar = document.createElement("span");
      bar.className = "story-ad-timer-bar";
      timer.appendChild(bar);
      popup.appendChild(timer);

      return { popup: popup, bar: bar, close: close };
    }

    /* resolves once the popup is fully gone */
    function present(ready) {
      return new Promise(function (resolve) {
        var built = buildPopup(ready.ad, ready.src);
        var leaving = false;

        function leave() {
          if (leaving) return;
          leaving = true;
          built.popup.classList.add("is-leaving");
          window.setTimeout(function () {
            built.popup.remove();
            resolve();
          }, LEAVE_MS);
        }

        document.body.appendChild(built.popup);

        built.close.addEventListener("click", leave);

        /* 4. the empty bar is the signal; the timer only backs it up in case
              the stylesheet never loaded and the bar never animates */
        built.bar.addEventListener("animationend", leave, { once: true });
        window.setTimeout(leave, showMs + 600);
      });
    }

    /* ----- 5. wait, then start over -----
       A failed request, an empty answer and a broken picture all fall through
       to the same wait, so one bad round never ends the rotation. */
    function cycle() {
      requestAd()
        .then(function (ad) { return ad ? prepare(ad) : null; })
        .then(function (ready) { return ready ? present(ready) : null; })
        .catch(function () { /* try again after the wait */ })
        .then(function () { window.setTimeout(cycle, gapMs); });
    }

    cycle();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
