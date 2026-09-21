(function () {
  "use strict";

  var config = window.ABUREPORTS || {};

  /* ---------- Hero carousel ---------- */

  var slidesWrap = document.getElementById("hero-slides");
  if (slidesWrap) {
    var slides = Array.prototype.slice.call(slidesWrap.querySelectorAll(".hero-slide"));
    var dots = Array.prototype.slice.call(document.querySelectorAll(".hero-dot"));
    var prevBtn = document.getElementById("hero-prev");
    var nextBtn = document.getElementById("hero-next");
    var current = 0;
    var timer = null;

    function goTo(index) {
      if (!slides.length) return;
      current = (index + slides.length) % slides.length;
      slides.forEach(function (slide, i) {
        slide.classList.toggle("is-active", i === current);
      });
      dots.forEach(function (dot, i) {
        dot.classList.toggle("is-active", i === current);
      });
    }

    function restartAutoplay() {
      if (timer) {
        window.clearInterval(timer);
      }
      if (slides.length > 1) {
        timer = window.setInterval(function () {
          goTo(current + 1);
        }, 7000);
      }
    }

    dots.forEach(function (dot, i) {
      dot.addEventListener("click", function () {
        goTo(i);
        restartAutoplay();
      });
    });

    if (prevBtn) {
      prevBtn.addEventListener("click", function () {
        goTo(current - 1);
        restartAutoplay();
      });
    }

    if (nextBtn) {
      nextBtn.addEventListener("click", function () {
        goTo(current + 1);
        restartAutoplay();
      });
    }

    restartAutoplay();
  }

  /* ---------- Toast ---------- */

  var toastEl = document.getElementById("bookmark-toast");
  var toastTimer = null;

  function showToast(message) {
    if (!toastEl) return;
    toastEl.textContent = message;
    toastEl.classList.add("is-visible");
    if (toastTimer) {
      window.clearTimeout(toastTimer);
    }
    toastTimer = window.setTimeout(function () {
      toastEl.classList.remove("is-visible");
    }, 2600);
  }

  /* ---------- Bookmark toggle ---------- */

  function toggleBookmark(button) {
    var blogId = button.getAttribute("data-blog-id");
    if (!blogId || !config.bookmarkUrlBase) return;

    fetch(config.bookmarkUrlBase + blogId + "/", {
      method: "POST",
      headers: {
        "X-CSRFToken": config.csrfToken || "",
        "X-Requested-With": "XMLHttpRequest"
      }
    })
      .then(function (response) {
        return response.json().then(function (data) {
          return { status: response.status, data: data };
        });
      })
      .then(function (result) {
        var message = (result.data && result.data.detail && result.data.detail[0]) || "";
        if (result.status === 401) {
          showToast(message || "Log in to bookmark stories.");
          return;
        }
        if (result.status === 200) {
          var bookmarked = !!result.data.bookmarked;
          document
            .querySelectorAll('[data-bookmark][data-blog-id="' + blogId + '"]')
            .forEach(function (el) {
              el.setAttribute("data-bookmarked", bookmarked ? "true" : "false");
              el.setAttribute("aria-pressed", bookmarked ? "true" : "false");
            });
          showToast(message || (bookmarked ? "Story bookmarked." : "Bookmark removed."));
          return;
        }
        showToast(message || "Something went wrong.");
      })
      .catch(function () {
        showToast("Could not reach the server. Try again.");
      });
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-bookmark]");
    if (button) {
      toggleBookmark(button);
    }
  });

  /* ---------- Share ---------- */

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-share]");
    if (!button) return;

    var shareData = {
      title: button.getAttribute("data-title") || document.title,
      url: window.location.href
    };

    if (navigator.share) {
      navigator.share(shareData).catch(function () {
        /* user cancelled, no action needed */
      });
    } else if (navigator.clipboard) {
      navigator.clipboard
        .writeText(shareData.url)
        .then(function () {
          showToast("Link copied.");
        })
        .catch(function () {
          showToast("Could not copy the link.");
        });
    }
  });

  /* ---------- Load more ---------- */

  var loadMoreBtn = document.getElementById("load-more");
  var grid = document.getElementById("reports-grid");

  function categoryLabel(raw) {
    return escapeHtml(raw.replace(/_/g, " "));
  }

  function escapeHtml(value) {
    var div = document.createElement("div");
    div.textContent = String(value == null ? "" : value);
    return div.innerHTML;
  }

  function buildCard(post) {
    var article = document.createElement("article");
    article.className = "report-card";
    article.id = "story-" + post.id;

    var imageHtml = post.image_1
      ? '<img class="report-image" src="' + escapeHtml(post.image_1) + '" alt="" loading="lazy">'
      : '<div class="report-image"></div>';

    article.innerHTML =
      imageHtml +
      '<span class="report-tag">' + categoryLabel(post.category) + "</span>" +
      '<h3 class="report-headline"><a href="#story-' + post.id + '">' + escapeHtml(post.heading) + "</a></h3>" +
      '<div class="report-meta">' +
      "<span>" + escapeHtml(post.author) + " &middot; " + escapeHtml(post.date_created) + "</span>" +
      '<button type="button" class="report-bookmark" data-bookmark data-blog-id="' + post.id + '" data-bookmarked="' + post.is_bookmarked + '" aria-label="Bookmark story">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M7 3.5h10a1 1 0 0 1 1 1V21l-6-4-6 4V4.5a1 1 0 0 1 1-1Z"></path></svg>' +
      "</button>" +
      "</div>";

    return article;
  }

  if (loadMoreBtn && grid && config.loadMoreUrl) {
    loadMoreBtn.addEventListener("click", function () {
      var page = loadMoreBtn.getAttribute("data-page");
      loadMoreBtn.disabled = true;
      loadMoreBtn.textContent = "Loading...";

      fetch(config.loadMoreUrl + "?page=" + encodeURIComponent(page))
        .then(function (response) {
          return response.json();
        })
        .then(function (data) {
          (data.posts || []).forEach(function (post) {
            grid.appendChild(buildCard(post));
          });

          if (data.has_more && data.next_page) {
            loadMoreBtn.setAttribute("data-page", data.next_page);
            loadMoreBtn.disabled = false;
            loadMoreBtn.textContent = "Load more reports";
          } else {
            loadMoreBtn.remove();
          }
        })
        .catch(function () {
          loadMoreBtn.disabled = false;
          loadMoreBtn.textContent = "Load more reports";
          showToast("Could not load more reports. Try again.");
        });
    });
  }
})();
