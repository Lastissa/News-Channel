(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    var panel = document.querySelector("[data-read-also]");
    var storyBody = document.querySelector("[data-story-body]");
    var rail = document.querySelector("[data-related-rail]");
    if (!panel || !storyBody) return;

    var list = panel.querySelector("[data-read-also-list]");
    var firstParagraph = storyBody.querySelector("p");
    var desktopLayout = window.matchMedia("(min-width: 1200px)");
    var endpoint = panel.dataset.endpoint;

    function placePanel() {
      if (desktopLayout.matches && rail) {
        rail.appendChild(panel);
      } else if (firstParagraph) {
        firstParagraph.after(panel);
      } else {
        storyBody.appendChild(panel);
      }
    }

    function makeStoryCard(story, index) {
      var card = document.createElement("article");
      card.className = "read-also-card";
      card.style.setProperty("--card-index", index);

      if (story.image) {
        var imageLink = document.createElement("a");
        imageLink.className = "read-also-card-image";
        imageLink.href = story.url;
        imageLink.tabIndex = -1;

        var image = document.createElement("img");
        image.src = story.image;
        image.alt = "";
        image.loading = "lazy";
        imageLink.appendChild(image);
        card.appendChild(imageLink);
      }

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

      if (story.excerpt) {
        var excerpt = document.createElement("p");
        excerpt.className = "read-also-card-excerpt";
        excerpt.textContent = story.excerpt;
        content.appendChild(excerpt);
      }

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

      list.append(message, retry);
      panel.setAttribute("aria-busy", "false");
    }

    function loadStories() {
      if (!endpoint || !list) return;
      panel.setAttribute("aria-busy", "true");

      fetch(endpoint, {
        method: "GET",
        headers: { Accept: "application/json" },
        credentials: "same-origin"
      })
        .then(function (response) {
          if (!response.ok) throw new Error("Recommendations request failed.");
          return response.json();
        })
        .then(function (payload) {
          if (!payload || !Array.isArray(payload.stories)) {
            throw new Error("Recommendations response was invalid.");
          }
          if (!payload.stories.length) {
            panel.hidden = true;
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

    placePanel();
    desktopLayout.addEventListener("change", placePanel);
    if (list) {
      list.addEventListener("click", function (event) {
        if (event.target.closest("[data-read-also-retry]")) loadStories();
      });
    }
    loadStories();
  });
})();
