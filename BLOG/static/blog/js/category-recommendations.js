(function () {
  "use strict";

  function watchAuthorMostViewed() {
    var list = document.querySelector(".author-most-viewed-list");
    if (!list) return;
    if (!("IntersectionObserver" in window)) {
      list.classList.add("is-inview");
      return;
    }

    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting && entry.intersectionRatio >= 0.2) {
          list.classList.add("is-inview");
        } else if (!entry.isIntersecting) {
          list.classList.remove("is-inview");
        }
      });
    }, { threshold: [0, 0.2] });
    observer.observe(list);
  }

  function init() {
    watchAuthorMostViewed();
    var panel = document.querySelector("[data-read-also]");
    if (!panel) return;

    var list = panel.querySelector("[data-read-also-list]");
    var endpoint = panel.dataset.endpoint;
    var fallbackImage = panel.dataset.fallbackImage;
    var skeletonMarkup = list ? list.innerHTML : "";
    var rail = panel.closest("[data-read-also-rail]");
    var layout = panel.closest(".story-reading-layout");
    var storyBody = document.querySelector("[data-story-body]");
    var mobileLayout = window.matchMedia("(max-width: 899.98px)");
    var railPlaceholder = rail ? document.createComment("read-also-rail") : null;

    if (rail && rail.parentNode && railPlaceholder) {
      rail.parentNode.insertBefore(railPlaceholder, rail);
    }

    function moveRailForViewport() {
      if (!rail || !storyBody || !railPlaceholder || !railPlaceholder.parentNode) return;

      if (mobileLayout.matches) {
        var firstParagraph = Array.prototype.find.call(storyBody.children, function (child) {
          return child.tagName === "P";
        });
        if (firstParagraph) {
          firstParagraph.insertAdjacentElement("afterend", rail);
        }
      } else if (railPlaceholder.parentNode) {
        railPlaceholder.parentNode.insertBefore(rail, railPlaceholder.nextSibling);
      }
    }

    moveRailForViewport();
    if (mobileLayout.addEventListener) {
      mobileLayout.addEventListener("change", moveRailForViewport);
    } else {
      mobileLayout.addListener(moveRailForViewport);
    }

    function makeStoryCard(story, index) {
      var card = document.createElement("li");
      card.className = "read-also-card";
      card.style.setProperty("--card-index", index);

      var imageLink = document.createElement("a");
      imageLink.className = "read-also-card-image";
      imageLink.href = story.url;
      imageLink.tabIndex = -1;

      var image = document.createElement("img");
      image.src = story.image || fallbackImage;
      image.alt = "";
      image.loading = "lazy";
      image.onerror = function () {
        image.onerror = null;
        image.src = fallbackImage;
      };
      imageLink.appendChild(image);
      card.appendChild(imageLink);

      var content = document.createElement("div");
      content.className = "read-also-card-content";

      var metadata = document.createElement("p");
      metadata.className = "read-also-card-meta";
      metadata.textContent = story.category || "";
      if (story.date_created) {
        var date = new Date(story.date_created);
        if (!Number.isNaN(date.getTime())) {
          metadata.textContent += (metadata.textContent ? " · " : "") +
            date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
        }
      }
      content.appendChild(metadata);

      var heading = document.createElement("h3");
      var link = document.createElement("a");
      link.href = story.url;
      link.textContent = story.heading;
      heading.appendChild(link);
      content.appendChild(heading);

      card.appendChild(content);
      return card;
    }

    function showError() {
      if (!list) return;
      list.replaceChildren();

      var message = document.createElement("p");
      message.className = "read-also-error";
      message.textContent = "Could not load these stories. Please try again.";

      var retry = document.createElement("button");
      retry.type = "button";
      retry.className = "read-also-retry";
      retry.dataset.readAlsoRetry = "";
      retry.textContent = "Try again";

      var item = document.createElement("li");
      item.className = "read-also-error-item";
      item.append(message, retry);
      list.appendChild(item);
      panel.setAttribute("aria-busy", "false");
    }

    function loadStories() {
      if (!endpoint || !list) return;
      list.innerHTML = skeletonMarkup;
      panel.setAttribute("aria-busy", "true");

      fetch(endpoint, {
        method: "GET",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "X-Requested-With": "XMLHttpRequest"
        }
      })
        .then(function (response) {
          if (!response.ok) throw new Error("Recommendations request failed: " + response.status);
          return response.json();
        })
        .then(function (payload) {
          if (!payload || !Array.isArray(payload.stories)) {
            throw new Error("Recommendations response was invalid.");
          }
          if (!payload.stories.length) {
            if (rail) rail.hidden = true;
            if (layout) layout.classList.remove("has-read-also-rail");
            panel.setAttribute("aria-busy", "false");
            return;
          }

          list.replaceChildren();
          payload.stories.forEach(function (story, index) {
            list.appendChild(makeStoryCard(story, index));
          });
          panel.classList.add("is-loaded");
          panel.setAttribute("aria-busy", "false");
        })
        .catch(showError);
    }

    if (list) {
      list.addEventListener("click", function (event) {
        if (event.target instanceof Element && event.target.closest("[data-read-also-retry]")) {
          loadStories();
        }
      });
    }
    loadStories();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
