/* Add news editor: heavy components. Loaded asynchronously by the light
   loader in add_news.html so the page skeleton paints first.

   The preview engine below is a direct port of BLOG.views.parse_story_content
   and _linkify_text (see docs/NEWS_CONTENT_CONVENTION.MD) so what the author
   sees here is exactly what every reader will get on the published page. */
(function () {
  "use strict";

  var shell = document.getElementById("editor-shell");
  if (!shell) return;

  var form = shell.querySelector("[data-editor-form]");
  var headingInput = shell.querySelector("[data-editor-heading]");
  var imageInput = shell.querySelector("[data-editor-image]");
  var imageInfoInput = shell.querySelector("[data-editor-image-info]");
  var categorySelect = shell.querySelector("[data-editor-category]");
  var contentInput = shell.querySelector("[data-editor-content]");
  var output = shell.querySelector("[data-editor-preview-output]");
  var toggleBtn = shell.querySelector("[data-editor-preview-toggle]");
  var publishBtn = shell.querySelector("[data-editor-publish]");
  var uploadBtn = shell.querySelector("[data-editor-upload-btn]");
  var note = shell.querySelector("[data-editor-loading-note]");

  var PREVIEW_KEY = "abu-editor-preview";
  var pendingPublish = false;

  function toast(message, tone) {
    if (window.editorToast) {
      window.editorToast(message, tone);
      return;
    }
    window.alert(message);
  }

  function extractDetail(rawText, genericMessage) {
    if (!rawText) return genericMessage;
    try {
      var data = JSON.parse(rawText);
      return data && data.detail ? data.detail : genericMessage;
    } catch (e) {
      return genericMessage;
    }
  }

  /* ---------- shared formatting helpers (port of the server parser) ---------- */
  function escapeHtml(value) {
    return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function escapeAttr(value) {
    return escapeHtml(value).replace(/"/g, "&quot;");
  }

  function linkifyText(value) {
    var safe = escapeHtml(value);
    safe = safe.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    safe = safe.replace(/__(.+?)__/g, "<em>$1</em>");
    safe = safe.replace(/https?:\/\/[^\s<>'"]+/g, function (match) {
      return '<a href="' + match + '" rel="noopener noreferrer" target="_blank">' + match + "</a>";
    });
    return safe;
  }

  function parseStoryContent(content) {
    if (!content) return "";
    var normalized = String(content).replace(/\r\n?/g, "\n").trim();
    var lines = normalized.split("\n").map(function (line) { return line.replace(/\s+$/, ""); });
    var blocks = [];
    var i = 0;
    var headingRe = /^(#+)\s*(.*)$/;
    var bulletRe = /^\*\s+/;
    var orderedRe = /^\d+\.\s+/;
    var starterRe = /^(#+\s+|\*\s+|\d+\.\s+)/;

    while (i < lines.length) {
      var line = lines[i].trim();
      if (!line) { i += 1; continue; }

      var headingMatch = line.match(headingRe);
      if (headingMatch) {
        var level = Math.min(headingMatch[1].length + 1, 4);
        var headingText = headingMatch[2].trim();
        if (headingText) blocks.push("<h" + level + ">" + linkifyText(headingText) + "</h" + level + ">");
        i += 1;
        continue;
      }

      if (bulletRe.test(line)) {
        var bullets = [];
        while (i < lines.length) {
          var bulletLine = lines[i].trim();
          if (!bulletLine || !bulletRe.test(bulletLine)) break;
          var bulletItem = bulletLine.slice(2).trim();
          if (bulletItem) bullets.push("<li>" + linkifyText(bulletItem) + "</li>");
          i += 1;
        }
        if (bullets.length) blocks.push("<ul>" + bullets.join("") + "</ul>");
        continue;
      }

      if (orderedRe.test(line)) {
        var ordered = [];
        while (i < lines.length) {
          var orderedLine = lines[i].trim();
          if (!orderedLine || !orderedRe.test(orderedLine)) break;
          var orderedMatch = orderedLine.match(/^\d+\.\s+(.*)$/);
          if (orderedMatch && orderedMatch[1].trim()) ordered.push("<li>" + linkifyText(orderedMatch[1].trim()) + "</li>");
          i += 1;
        }
        if (ordered.length) blocks.push("<ol>" + ordered.join("") + "</ol>");
        continue;
      }

      var paragraphLines = [];
      while (i < lines.length) {
        var paragraphLine = lines[i].trim();
        if (!paragraphLine) break;
        if (starterRe.test(paragraphLine)) break;
        paragraphLines.push(paragraphLine);
        i += 1;
        if (i < lines.length && !lines[i].trim()) break;
      }
      var paragraph = paragraphLines.join(" ").trim();
      if (paragraph) blocks.push("<p>" + linkifyText(paragraph) + "</p>");
    }

    return blocks.join("\n");
  }

  /* ---------- preview ---------- */
  var debounceTimer = null;

  function currentCategoryLabel() {
    if (!categorySelect.value || categorySelect.selectedIndex < 0) return "";
    return categorySelect.options[categorySelect.selectedIndex].text;
  }

  function todayLabel() {
    return new Date().toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  }

  function renderPreview() {
    var heading = headingInput.value.trim();
    var imageUrl = imageInput.value.trim();
    var imageInfo = imageInfoInput.value.trim() || "The image is self explanatory.";
    var categoryLabel = currentCategoryLabel();
    var bodyHtml = parseStoryContent(contentInput.value);

    var html = '<div class="editor-preview-frame"><article class="story-article no-inner-shell">';
    html += '<header class="story-header">';
    html += '<div class="story-kicker-row"><span class="story-kicker">' + escapeHtml(categoryLabel || "Category") + '</span>';
    html += '<span class="story-separator">&bull;</span><time>' + escapeHtml(todayLabel()) + "</time></div>";
    html += "<h1>" + escapeHtml(heading || "Untitled story") + "</h1>";
    html += "</header>";

    if (imageUrl) {
      html += '<figure class="story-hero-figure">';
      html += '<img src="' + escapeAttr(imageUrl) + '" alt="' + escapeAttr(heading || "Story image") + '" loading="eager" onerror="this.onerror=null;this.src=\'/static/404.jpg\';">';
      html += "<figcaption>" + escapeHtml(imageInfo) + "</figcaption>";
      html += "</figure>";
    }

    html += '<div class="story-body">';
    html += bodyHtml || '<p class="editor-preview-empty">Live Preview Plcaeholder Text</p>';
    html += "</div>";
    html += "</article></div>";

    output.innerHTML = html;
  }

  function schedulePreview() {
    if (debounceTimer) window.clearTimeout(debounceTimer);
    debounceTimer = window.setTimeout(renderPreview, 120);
  }

  /* ---------- closeable preview ---------- */
  function applyPreviewState(off) {
    shell.classList.toggle("preview-off", off);
    toggleBtn.classList.toggle("is-off", off);
    toggleBtn.textContent = off ? "Show preview" : "Hide preview";
  }

  toggleBtn.addEventListener("click", function () {
    var nextOff = !shell.classList.contains("preview-off");
    applyPreviewState(nextOff);
    try { window.localStorage.setItem(PREVIEW_KEY, nextOff ? "off" : "on"); } catch (e) { /* storage unavailable */ }
  });

  var storedPreview = null;
  try { storedPreview = window.localStorage.getItem(PREVIEW_KEY); } catch (e) { /* ignore */ }
  applyPreviewState(storedPreview === "off");

  /* ---------- publish ---------- */
  function setPublishPending(pending) {
    pendingPublish = pending;
    publishBtn.disabled = pending;
    publishBtn.classList.toggle("is-pending", pending);
    publishBtn.textContent = pending ? "Publishing..." : "Publish story";
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (pendingPublish) return;

    if (!headingInput.value.trim()) {
      toast("You Forgot To Add Heading", "error");
      headingInput.focus();
      return;
    }
    if (!categorySelect.value) {
      toast("Select a category for the story.", "error");
      categorySelect.focus();
      return;
    }
    if (!contentInput.value.trim()) {
      toast("The story content cannot be empty.", "error");
      contentInput.focus();
      return;
    }

    setPublishPending(true);
    fetch(form.dataset.endpoint, {
      method: "POST",
      headers: { "X-CSRFToken": getCookie("csrftoken"), "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
      body: new FormData(form),
    })
      .then(function (response) {
        return response.text().then(function (text) { return { ok: response.ok, status: response.status, text: text }; });
      })
      .then(function (result) {
        setPublishPending(false);
        if (!result.ok) {
          var detail = extractDetail(result.text, "Could not publish the story.");
          toast(detail, "error");
          if (/already/i.test(detail)) {
            headingInput.classList.add("is-error");
            headingInput.focus();
            headingInput.select();
          }
          return;
        }
        var payload = {};
        try { payload = JSON.parse(result.text || "{}") || {}; } catch (e) { /* ignore */ }
        toast(payload.detail || "Story published.");
        if (payload.story_url) {
          window.setTimeout(function () { window.location.href = payload.story_url; }, 700);
        }
      })
      .catch(function () {
        setPublishPending(false);
        toast("Network Error.Unable to publish story.", "error");
      });
  });

  function getCookie(name) {
    var match = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
    return match ? decodeURIComponent(match.pop()) : "";
  }

  if (uploadBtn) {
    uploadBtn.addEventListener("click", function () {
      toast("File upload is not available yet. Paste an image URL for now.");
    });
  }

  /* ---------- wire up + reveal ---------- */
  headingInput.addEventListener("input", function () {
    headingInput.classList.remove("is-error");
    schedulePreview();
  });
  imageInput.addEventListener("input", schedulePreview);
  imageInfoInput.addEventListener("input", schedulePreview);
  categorySelect.addEventListener("change", schedulePreview);
  contentInput.addEventListener("input", schedulePreview);

  renderPreview();
  applyPreviewState(shell.classList.contains("preview-off"));

  shell.classList.remove("is-loading");
  shell.classList.add("is-ready");
  if (note) note.remove();
  toggleBtn.hidden = false;
  publishBtn.disabled = false;
})();
