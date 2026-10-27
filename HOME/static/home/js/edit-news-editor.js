/* Edit news editor: heavy components. Loaded asynchronously by the light
   loader in edit_news.html so the page skeleton paints first. A copy of
   add-news-editor.js that saves to the edit endpoint instead of creating a
   story, and never touches the heading: the heading input is locked and has no
   name, so it is not part of the submitted form, and the server ignores one
   anyway (HOME.views.EditNewsView).

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
  var imageFileInput = shell.querySelector("[data-editor-image-file]");
  var imageFilenameEl = shell.querySelector("[data-editor-image-filename]");
  var imageClearBtn = shell.querySelector("[data-editor-image-clear]");
  var imageQualityField = shell.querySelector("[data-editor-image-quality-field]");
  var imageInfoInput = shell.querySelector("[data-editor-image-info]");
  var categorySelect = shell.querySelector("[data-editor-category]");
  var contentInput = shell.querySelector("[data-editor-content]");
  var tocModeSelect = shell.querySelector("[data-editor-toc-mode]");
  var output = shell.querySelector("[data-editor-preview-output]");
  var toggleBtn = shell.querySelector("[data-editor-preview-toggle]");
  var publishBtn = shell.querySelector("[data-editor-publish]");
  var uploadBtn = shell.querySelector("[data-editor-upload-btn]");
  var note = shell.querySelector("[data-editor-loading-note]");
  var guideEl = shell.querySelector("[data-format-guide]");
  var guideToggleBtn = shell.querySelector("[data-guide-toggle]");
  var guideCopyBtn = shell.querySelector("[data-guide-copy-all]");
  var toolbarEl = shell.querySelector("[data-editor-toolbar]");
  var tabButtons = shell.querySelectorAll("[data-editor-tab]");
  var archiveModal = shell.querySelector("[data-archive-modal]");
  var archiveFrame = archiveModal ? archiveModal.querySelector(".archive-picker-frame") : null;
  var archiveStage = archiveModal ? archiveModal.querySelector(".archive-picker-stage") : null;
  var archiveRefreshBtn = archiveModal ? archiveModal.querySelector("[data-archive-refresh]") : null;

  var PREVIEW_KEY = "abu-editor-preview";
  var MAX_IMAGE_BYTES = 8 * 1024 * 1024;
  var MODAL_CLOSE_MS = 240;
  var MOBILE_QUERY = window.matchMedia ? window.matchMedia("(max-width: 899.98px)") : { matches: false };
  var pendingPublish = false;

  /* Local-only preview of a chosen file. No upload happens here, that
     only happens inside the publish handler further down, via the real
     `image_file` FormData entry the browser already attached to the form. */
  var selectedImageObjectUrl = null;

  function toast(message, tone) {
    if (typeof window.AbuToast === "function") {
      window.AbuToast(message, tone);
      return;
    }
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

  /* ---------- animated dialogs ----------
     `hidden` can not be transitioned, so a dialog opens by clearing it and
     adding .is-open on the next frame, and closes by dropping .is-open and
     setting `hidden` once the fade is done. The page behind is locked from
     scrolling while any dialog is open. */
  function showDialog(el) {
    if (!el) return;
    window.clearTimeout(el._closeTimer);
    el.hidden = false;
    document.documentElement.classList.add("editor-modal-open");
    void el.offsetWidth;
    window.requestAnimationFrame(function () { el.classList.add("is-open"); });
  }

  function hideDialog(el) {
    if (!el || el.hidden) return;
    el.classList.remove("is-open");
    el._closeTimer = window.setTimeout(function () {
      el.hidden = true;
      var anyOpen = shell.querySelector(".editor-modal:not([hidden])");
      if (!anyOpen) document.documentElement.classList.remove("editor-modal-open");
    }, MODAL_CLOSE_MS);
  }

  /* ---------- archive picker ----------
     The picker shows the real /archive/ page in a frame. It is same-origin,
     so once it has loaded the site header, footer, splash and floating
     buttons are hidden and the gallery gets a compact, touch friendly layout
     (two columns on a phone). Only the picker is affected, the real archive
     page keeps its own styles. */
  var ARCHIVE_EMBED_CSS = [
    "#splash,.dummy-loading,.site-header,.site-footer,.fab-stack,#newsletter-popup{display:none!important}",
    "html,body{background:var(--paper)!important}",
    "body{padding-top:0!important}",
    ".archive-shell{padding:16px 16px 32px!important}",
    ".archive-hero{padding-bottom:12px!important}",
    ".archive-hero::after,.archive-heading,.archive-header-actions{animation:none!important}",
    ".archive-eyebrow{display:none!important}",
    ".archive-hero h1{font-size:1.4rem!important}",
    ".archive-subtitle{margin-top:4px!important;font-size:0.84rem!important}",
    ".archive-toolbar{position:sticky;top:0;z-index:20;background:var(--paper);padding:10px 0 6px!important}",
    ".archive-tab{padding:11px 14px!important}",
    "@media (max-width:560px){",
    ".archive-shell{padding:12px 12px 28px!important}",
    ".archive-subtitle{display:none!important}",
    ".archive-hero{gap:10px!important}",
    ".archive-header-actions .archive-action-btn{padding:9px 10px!important;font-size:0.8rem!important}",
    ".archive-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:10px!important}",
    ".archive-card-media{aspect-ratio:1/1!important}",
    ".archive-card-media .archive-tag{top:8px!important;font-size:0.6rem!important;padding:4px 12px 4px 7px!important}",
    ".archive-card-body{padding:9px 9px 10px!important;gap:7px!important}",
    ".archive-card-desc{font-size:0.8rem!important;-webkit-line-clamp:2}",
    ".archive-card-specs,.archive-card-credit{display:none!important}",
    ".archive-card-btn{min-height:38px!important;font-size:0.74rem!important;padding:7px 8px!important}",
    ".archive-card-btn.is-icon{flex:0 0 38px!important}",
    ".archive-card-btn-icon{width:14px!important;height:14px!important}",
    ".archive-pagination{flex-wrap:wrap;justify-content:center}",
    "}"
  ].join("\n");

  var PICKER_TIMEOUT_MS = 5000;
  var pickerWatchdogTimer = null;

  function clearPickerWatchdog() {
    if (pickerWatchdogTimer) {
      window.clearTimeout(pickerWatchdogTimer);
      pickerWatchdogTimer = null;
    }
  }

  function styleArchiveFrame() {
    clearPickerWatchdog();
    if (!archiveFrame) return;
    try {
      var doc = archiveFrame.contentDocument;
      if (doc && doc.querySelector(".archive-shell") && !doc.getElementById("picker-embed-css")) {
        var styleEl = doc.createElement("style");
        styleEl.id = "picker-embed-css";
        styleEl.textContent = ARCHIVE_EMBED_CSS;
        doc.head.appendChild(styleEl);
      }
    } catch (error) {
      console.error("Could not style the archive picker.", error);
    }
    if (archiveStage) archiveStage.classList.add("is-loaded");
    if (archiveRefreshBtn) archiveRefreshBtn.disabled = false;
  }

  /* Same watchdog the /archive/ page uses: if the picker frame has not
     loaded within 5 seconds (server down, slow connection), stop the
     spinner, re-enable refresh and say what happened instead of leaving
     the frame loading forever. */
  function loadArchiveFrame(force) {
    if (!archiveFrame) return;
    var url = archiveFrame.getAttribute("data-src");
    if (!url) return;
    if (!force && archiveFrame.getAttribute("src")) return;
    clearPickerWatchdog();
    if (archiveStage) archiveStage.classList.remove("is-loaded");
    archiveFrame.setAttribute("src", url);
    pickerWatchdogTimer = window.setTimeout(function () {
      pickerWatchdogTimer = null;
      if (archiveStage) archiveStage.classList.add("is-loaded");
      if (archiveRefreshBtn) archiveRefreshBtn.disabled = false;
      toast("Timeout, please try again.", "error");
    }, PICKER_TIMEOUT_MS);
  }

  function closeArchivePicker() {
    hideDialog(archiveModal);
  }

  shell.querySelectorAll("[data-archive-open]").forEach(function (button) {
    button.addEventListener("click", function () {
      if (!archiveModal) return;
      loadArchiveFrame(false);
      showDialog(archiveModal);
      var closeButton = archiveModal.querySelector("[data-archive-close]");
      if (closeButton) closeButton.focus({ preventScroll: true });
    });
  });
  if (archiveModal) {
    if (archiveFrame) archiveFrame.addEventListener("load", styleArchiveFrame);
    if (archiveRefreshBtn && archiveFrame) {
      archiveRefreshBtn.addEventListener("click", function () {
        archiveRefreshBtn.disabled = true;
        loadArchiveFrame(true);
      });
    }
    archiveModal.querySelectorAll("[data-archive-close]").forEach(function (button) {
      button.addEventListener("click", closeArchivePicker);
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !archiveModal.hidden) closeArchivePicker();
    });
  }

  /* ---------- shared formatting helpers (port of the server parser) ---------- */
  function escapeHtml(value) {
    return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function escapeAttr(value) {
    return escapeHtml(value).replace(/"/g, "&quot;");
  }

  /* Undo the escaping above. A URL is escaped before it is parsed for
     tagging, so "&" in the author's query string is sitting here as "&amp;";
     the real query string has to be read back before tagOutboundUrl runs, or
     a second "&" would come out as "&amp%3B" and break the link. Mirrors the
     html.unescape in _linkify_text (BLOG/views.py). */
  function unescapeHtml(value) {
    return String(value)
      .replace(/&quot;/g, '"')
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&amp;/g, "&");
  }

  /* OUTBOUND REFERRAL TAGGING -- mirrors tag_outbound_url in BLOG/views.py.
     A pasted link is stamped with our referral parameters before it becomes
     an anchor, so sites we send readers to see the traffic came from us.
     Only links that leave the site are tagged; our own domain, mailto:/tel:
     and #anchors are left alone, and a link the author already tagged (it
     carries a utm_source) is respected. The campaign story slug is added by
     the server on the published page; the preview omits it since the editor
     has no slug. */
  var REFERRAL_SOURCE = "abureport";
  var REFERRAL_MEDIUM = "referral";

  function tagOutboundUrl(url) {
    var parsed;
    try { parsed = new URL(url); } catch (error) { return url; }
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return url;
    var host = parsed.hostname.toLowerCase();
    if (host === "localhost" || host === "127.0.0.1") return url;
    var bare = REFERRAL_SOURCE.toLowerCase();
    if (host === bare || host.slice(-(bare.length + 1)) === "." + bare) return url;
    if (parsed.searchParams.has("utm_source")) return url;
    parsed.searchParams.set("utm_source", REFERRAL_SOURCE);
    parsed.searchParams.set("utm_medium", REFERRAL_MEDIUM);
    return parsed.toString();
  }

  function linkifyText(value) {
    var safe = escapeHtml(value);
    safe = safe.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    safe = safe.replace(/__(.+?)__/g, "<em>$1</em>");
    /* Markdown link ([words](url)) and bare URL in one pass, so a URL that
       already sits inside "[words](...)" is never linkified twice -- mirrors
       _linkify_text / _LINK_OR_URL_RE in BLOG/views.py. */
    safe = safe.replace(/\[([^\[\]]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s<>'"]+)/g, function (match, label, url, bare) {
      if (url === undefined) { url = bare; label = bare; }
      return '<a href="' + escapeAttr(tagOutboundUrl(unescapeHtml(url))) + '" rel="noopener noreferrer" target="_blank">' + label + "</a>";
    });
    return safe;
  }

  /* INLINE IMAGE TOKEN: "imgl URL alt text" / "imgr URL alt text" (floated,
     text wraps around it) / "imgc URL alt text" (centered, blocking --
     never floated/wrapped, still kept smaller than the hero image).
     Checked before headings/bold/italic so the URL + alt text are never
     consumed by those markers -- mirrors IMG_TOKEN_RE in BLOG/views.py. */
  var imgTokenRe = /^(imgl|imgr|imgc)\s+(\S+)(?:\s+(.*))?$/;

  /* INLINE FILE ATTACHMENT TOKEN: "filel URL display text". Same shape as
     the image token above (keyword, URL, optional trailing text) but
     renders as a downloadable link in the normal flow of the paragraph --
     mirrors FILE_TOKEN_RE / _render_inline_file in BLOG/views.py. */
  var fileTokenRe = /^filel\s+(\S+)(?:\s+(.*))?$/;

  var IMG_SIDE_CLASSES = {
    imgl: "story-inline-img-left",
    imgr: "story-inline-img-right",
    imgc: "story-inline-img-center"
  };

  /* INLINE VIDEO TOKEN: "vidl URL caption" / "vidr URL caption" (floated,
     text wraps around it) / "vidc URL caption" (centered, blocking). Same
     shape as the image token above but renders a self-playing <video> whose
     only control is a play/pause button -- mirrors VID_TOKEN_RE /
     _render_inline_video in BLOG/views.py. */
  var vidTokenRe = /^(vidl|vidr|vidc)\s+(\S+)(?:\s+(.*))?$/;

  var VID_SIDE_CLASSES = {
    vidl: "story-inline-fig-left",
    vidr: "story-inline-fig-right",
    vidc: "story-inline-fig-center"
  };

  /* BUTTON TOKEN: "btn URL label text". A whole line that starts with `btn`
     becomes one button-style link -- the URL is the destination and the
     trailing text is the label printed on the button. Mirrors BTN_TOKEN_RE /
     _render_inline_button in BLOG/views.py. */
  var btnTokenRe = /^btn\s+(\S+)(?:\s+(.*))?$/;

  function imageFilenameFromUrl(url) {
    var withoutQuery = url.split(/[?#]/)[0];
    var parts = withoutQuery.split("/");
    return parts[parts.length - 1] || url;
  }

  function renderInlineImage(direction, url, altText) {
    var alt = (altText || "").trim() || imageFilenameFromUrl(url);
    var sideClass = IMG_SIDE_CLASSES[direction] || "story-inline-img-left";
    return '<img class="story-inline-img ' + sideClass + '" src="' + escapeAttr(url) + '" alt="' + escapeAttr(alt) + '" loading="lazy">';
  }

  function renderInlineFile(url, displayText) {
    var label = (displayText || "").trim() || imageFilenameFromUrl(url);
    return '<a class="story-inline-file" href="' + escapeAttr(tagOutboundUrl(url)) + '" download rel="noopener noreferrer">' +
      '<span class="story-inline-file-icon" aria-hidden="true"><svg xmlns="http://w3.org" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" x2="12" y1="15" y2="3" /></svg></span>' + escapeHtml(label) + "</a>";
  }

  /* Mirrors _render_inline_button in BLOG/views.py: one block-level button
     link. With no label the URL itself is printed so the button is never
     blank. */
  function renderInlineButton(url, labelText) {
    var label = (labelText || "").trim() || url;
    return '<p class="story-inline-btn-row"><a class="story-inline-btn" href="' + escapeAttr(tagOutboundUrl(url)) + '" rel="noopener noreferrer" target="_blank">' + escapeHtml(label) + "</a></p>";
  }

  /* EXTERNAL VIDEO PROVIDERS - mirrors _video_embed_url in BLOG/views.py. A
     YouTube or Vimeo address is a page, not a file, so a <video> can never
     play it; it is shown in an <iframe> with the provider's own player. Any
     other URL stays on the plain <video> path below. */
  var YOUTUBE_ID_RE = /(?:youtube(?:-nocookie)?\.com\/(?:watch\?[^\s#]*?v=|embed\/|shorts\/|live\/|v\/)|youtu\.be\/)([A-Za-z0-9_-]{11})/;
  var VIMEO_ID_RE = /vimeo\.com\/(?:video\/)?(\d+)/;

  function videoEmbedUrl(url) {
    var value = url || "";
    var youtube = value.match(YOUTUBE_ID_RE);
    if (youtube) {
      var params = ["rel=0", "playsinline=1", "modestbranding=1", "autoplay=1", "mute=1", "loop=1", "playlist=" + youtube[1]];
      var start = value.match(/[?&](?:t|start)=(\d+)/);
      if (start) params.push("start=" + start[1]);
      return "https://www.youtube.com/embed/" + youtube[1] + "?" + params.join("&");
    }
    var vimeo = value.match(VIMEO_ID_RE);
    if (vimeo) {
      return "https://player.vimeo.com/video/" + vimeo[1] + "?autoplay=1&muted=1&loop=1&playsinline=1&dnt=1";
    }
    return "";
  }

  /* Mirrors _render_inline_video in BLOG/views.py: the same autoplay/muted/
     loop <video> with no native controls, plus the play/pause and sound
     buttons - except a YouTube/Vimeo URL, which becomes an <iframe> embed
     with the provider's own controls (is-embed, no overlay buttons). */
  function renderInlineVideo(direction, url, captionText) {
    var caption = (captionText || "").trim();
    var figClass = VID_SIDE_CLASSES[direction] || "story-inline-fig-left";
    var aria = caption || "Story video";
    var captionHtml = caption ? "<figcaption>" + escapeHtml(caption) + "</figcaption>" : "";
    var embedUrl = videoEmbedUrl(url);
    if (embedUrl) {
      return '<figure class="story-inline-fig story-inline-video is-embed ' + figClass + '">' +
        '<div class="story-inline-video-frame">' +
        '<iframe class="story-inline-video-embed" src="' + escapeAttr(embedUrl) + '" title="' + escapeAttr(aria) + '" loading="lazy" allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowfullscreen referrerpolicy="strict-origin-when-cross-origin"></iframe>' +
        '</div>' + captionHtml +
        "</figure>";
    }
    return '<figure class="story-inline-fig story-inline-video ' + figClass + '">' +
      '<div class="story-inline-video-frame">' +
      '<video onerror="this.onerror=null;this.src=\'/static/404_video.mp4\';" class="story-inline-video-el" src="' + escapeAttr(url) + '" muted loop playsinline autoplay preload="metadata" aria-label="' + escapeAttr(aria) + '"></video>' +
      '<button type="button" class="story-inline-video-toggle" data-video-toggle aria-label="Pause video">' +
      '<svg class="story-inline-video-icon story-inline-video-icon-pause" width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="5" width="4" height="14" rx="1"></rect><rect x="14" y="5" width="4" height="14" rx="1"></rect></svg>' +
      '<svg class="story-inline-video-icon story-inline-video-icon-play" width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7z"></path></svg>' +
      '</button>' +
      '<button type="button" class="story-inline-video-toggle story-inline-video-sound" data-video-sound aria-label="Unmute video">' +
      '<svg class="story-inline-video-icon story-inline-video-icon-sound-on" width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M11 5L6 9H3v6h3l5 4V5z"></path><path d="M15.5 8.5a5 5 0 0 1 0 7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"></path><path d="M18.5 5.5a9 9 0 0 1 0 13" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"></path></svg>' +
      '<svg class="story-inline-video-icon story-inline-video-icon-sound-off" width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M11 5L6 9H3v6h3l5 4V5z"></path><line x1="16" y1="9" x2="22" y2="15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"></line><line x1="22" y1="9" x2="16" y2="15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"></line></svg>' +
      '</button></div>' +
      (caption ? "<figcaption>" + escapeHtml(caption) + "</figcaption>" : "") +
      "</figure>";
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
    var starterRe = /^(#+\s+|\*\s+|\d+\.\s+|imgl\s+|imgr\s+|imgc\s+|vidl\s+|vidr\s+|vidc\s+|filel\s+|btn\s+)/;

    while (i < lines.length) {
      var line = lines[i].trim();
      if (!line) { i += 1; continue; }

      var imgMatch = line.match(imgTokenRe);
      if (imgMatch) {
        blocks.push(renderInlineImage(imgMatch[1], imgMatch[2], imgMatch[3]));
        i += 1;
        continue;
      }

      var fileMatch = line.match(fileTokenRe);
      if (fileMatch) {
        blocks.push(renderInlineFile(fileMatch[1], fileMatch[2]));
        i += 1;
        continue;
      }

      var vidMatch = line.match(vidTokenRe);
      if (vidMatch) {
        blocks.push(renderInlineVideo(vidMatch[1], vidMatch[2], vidMatch[3]));
        i += 1;
        continue;
      }

      var btnMatch = line.match(btnTokenRe);
      if (btnMatch) {
        blocks.push(renderInlineButton(btnMatch[1], btnMatch[2]));
        i += 1;
        continue;
      }

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

  /* ---------- table of contents (mirrors BLOG.views.enhance_story_body) ----------
     When the author picks any Table of contents mode other than Off, give every
     heading an id and splice the "TABLE OF CONTENT" section in right after the
     first paragraph, exactly as the published page will. The list is the same
     nested #/##/### tree with the same three starting states: level 2 and 3 open
     the outer disclosure, level 3 also opens every branch. Kept off the
     parseStoryContent path so the preview body still mirrors the parser. */
  var TOC_CHEVRON = '<svg class="story-toc-chevron" viewBox="0 0 16 16" width="18" height="18" aria-hidden="true" focusable="false"><path d="M4 6.5 8 10.5 12 6.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  function plainHeadingText(inner) {
    var host = document.createElement("div");
    host.innerHTML = inner;
    return (host.textContent || "").trim();
  }

  function tocSlug(text) {
    var value = String(text || "");
    if (value.normalize) value = value.normalize("NFKD").replace(/[\u0300-\u036f]/g, "");
    value = value.replace(/[^\w\s-]/g, "").toLowerCase();
    value = value.replace(/[-\s]+/g, "-");
    return value.replace(/^[-_]+|[-_]+$/g, "");
  }

  function tocTree(headings) {
    var roots = [];
    var stack = [];
    headings.forEach(function (heading) {
      var node = { level: heading.level, slug: heading.slug, text: heading.text, children: [] };
      while (stack.length && stack[stack.length - 1].level >= node.level) stack.pop();
      (stack.length ? stack[stack.length - 1].children : roots).push(node);
      stack.push(node);
    });
    return roots;
  }

  function renderTocNodes(nodes, branchesOpen) {
    return nodes.map(function (node) {
      var link = '<a class="story-toc-link" href="#' + node.slug + '">' + escapeHtml(node.text) + "</a>";
      if (node.children.length) {
        var expanded = branchesOpen ? "true" : "false";
        var hidden = branchesOpen ? "" : " hidden";
        return '<li class="story-toc-item story-toc-item--has-children" data-level="' + node.level + '">' +
          '<div class="story-toc-row">' + link +
          '<button type="button" class="story-toc-branch" aria-expanded="' + expanded + '" aria-label="Toggle subsections">' +
          TOC_CHEVRON + "</button></div>" +
          '<ol class="story-toc-children"' + hidden + ">" +
          renderTocNodes(node.children, branchesOpen) + "</ol></li>";
      }
      return '<li class="story-toc-item" data-level="' + node.level + '">' +
        '<div class="story-toc-row">' + link + "</div></li>";
    }).join("");
  }

  function enhanceStoryBody(htmlBody, tocMode) {
    var mode = parseInt(tocMode, 10) || 0;
    if (!htmlBody || !mode) return htmlBody;

    var headings = [];
    var seen = {};
    var withIds = htmlBody.replace(/<h([2-4])>([\s\S]*?)<\/h\1>/g, function (match, level, inner) {
      var plain = plainHeadingText(inner);
      var base = tocSlug(plain) || "part";
      var slug = "section-" + base;
      var suffix = 2;
      while (Object.prototype.hasOwnProperty.call(seen, slug)) {
        slug = "section-" + base + "-" + suffix;
        suffix += 1;
      }
      seen[slug] = true;
      headings.push({ level: parseInt(level, 10), slug: slug, text: plain });
      return "<h" + level + ' id="' + slug + '">' + inner + "</h" + level + ">";
    });

    if (!headings.length) return withIds;

    var branchesOpen = mode === 3;
    var shellOpen = (mode === 2 || mode === 3) ? " open" : "";
    var rows = renderTocNodes(tocTree(headings), branchesOpen);
    var toc = '<nav class="story-toc" aria-label="Table of contents" data-story-toc data-toc-mode="' + mode + '">' +
      '<details class="story-toc-shell"' + shellOpen + ">" +
      '<summary class="story-toc-head"><span class="story-toc-title">TABLE OF CONTENT</span>' + TOC_CHEVRON + "</summary>" +
      '<ol class="story-toc-list">' + rows + "</ol></details></nav>";

    var blocks = withIds.split("\n");
    var insertAt = 0;
    for (var index = 0; index < blocks.length; index += 1) {
      if (blocks[index].indexOf("<p>") === 0) { insertAt = index + 1; break; }
    }
    blocks.splice(insertAt, 0, toc);
    return blocks.join("\n");
  }

  /* ---------- preview ---------- */
  var debounceTimer = null;

  function currentCategoryLabel() {
    if (!categorySelect.value || categorySelect.selectedIndex < 0) return "";
    return categorySelect.options[categorySelect.selectedIndex].text;
  }

  /* the preview keeps showing the ORIGINAL publication date, editing a story
     does not move it (the server renders it into data-published) */
  function publishedLabel() {
    return shell.dataset.published || "";
  }

  function renderPreview() {
    var heading = headingInput.value.trim();
    var imageUrl = selectedImageObjectUrl || imageInput.value.trim();
    var imageInfo = imageInfoInput.value.trim() || "The image is self explanatory.";
    var categoryLabel = currentCategoryLabel();
    var tocMode = tocModeSelect ? parseInt(tocModeSelect.value, 10) || 0 : 0;
    var bodyHtml = enhanceStoryBody(parseStoryContent(contentInput.value), tocMode);

    var html = '<div class="editor-preview-frame"><article class="story-article no-inner-shell">';
    html += '<header class="story-header">';
    html += '<div class="story-kicker-row"><span class="story-kicker">' + escapeHtml(categoryLabel || "Category") + '</span>';
    html += '<span class="story-separator">&bull;</span><time>' + escapeHtml(publishedLabel()) + "</time></div>";
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

    /* The preview pane IS the scroll container, so replacing its html would
       otherwise snap it back to the top on every keystroke. Keep the reader's
       place in the preview. */
    var previewScrollTop = output.scrollTop;
    output.innerHTML = html;
    if (previewScrollTop) output.scrollTop = previewScrollTop;

    /* freshly built <video> elements need their play/pause glyph synced */
    document.dispatchEvent(new CustomEvent("story-video:sync"));
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
    publishBtn.textContent = pending ? "Saving..." : "Save changes";
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (pendingPublish) return;

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
          var detail = extractDetail(result.text, "Could not save the changes.");
          toast(detail, "error");
          /* the only "already" refusal is a category that would put the story
             next to another one with the same heading */
          if (/already/i.test(detail)) categorySelect.focus();
          return;
        }
        var payload = {};
        try { payload = JSON.parse(result.text || "{}") || {}; } catch (e) { /* ignore */ }
        if (payload.changed === false) {
          /* nothing was different, the server saved nothing, stay on the editor */
          toast(payload.detail || "No changes to save.");
          return;
        }
        if (selectedImageObjectUrl) { URL.revokeObjectURL(selectedImageObjectUrl); selectedImageObjectUrl = null; }
        toast(payload.detail || "Story updated.");
        if (payload.story_url) {
          window.setTimeout(function () { window.location.href = payload.story_url; }, 700);
        }
      })
      .catch(function () {
        setPublishPending(false);
        toast("Network error. Unable to save the changes.", "error");
      });
  });

  function getCookie(name) {
    var match = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
    return match ? decodeURIComponent(match.pop()) : "";
  }

  function clearSelectedImageFile() {
    if (imageFileInput) imageFileInput.value = "";
    if (selectedImageObjectUrl) {
      URL.revokeObjectURL(selectedImageObjectUrl);
      selectedImageObjectUrl = null;
    }
    imageInput.disabled = false;
    if (imageFilenameEl) { imageFilenameEl.hidden = true; imageFilenameEl.textContent = ""; }
    if (imageClearBtn) imageClearBtn.hidden = true;
    if (imageQualityField) imageQualityField.hidden = true;
  }

  if (uploadBtn && imageFileInput) {
    uploadBtn.addEventListener("click", function () {
      imageFileInput.click();
    });

    imageFileInput.addEventListener("change", function () {
      var file = imageFileInput.files && imageFileInput.files[0];
      if (!file) return;

      if (!/^image\/(jpeg|png|webp|gif)$/.test(file.type)) {
        toast("Unsupported image type. Use JPEG, PNG, WEBP or GIF.", "error");
        clearSelectedImageFile();
        return;
      }
      if (file.size > MAX_IMAGE_BYTES) {
        toast("Image is too large. Max allowed size is 8MB.", "error");
        clearSelectedImageFile();
        return;
      }

      if (selectedImageObjectUrl) URL.revokeObjectURL(selectedImageObjectUrl);
      selectedImageObjectUrl = URL.createObjectURL(file);

      /* the file replaces the pasted URL, so it is disabled (and left out
         of the form submit) while a file is selected */
      imageInput.disabled = true;
      if (imageFilenameEl) { imageFilenameEl.textContent = file.name; imageFilenameEl.hidden = false; }
      if (imageClearBtn) imageClearBtn.hidden = false;
      if (imageQualityField) imageQualityField.hidden = false;
      schedulePreview();
    });
  }

  if (imageClearBtn) {
    imageClearBtn.addEventListener("click", function () {
      clearSelectedImageFile();
      schedulePreview();
    });
  }

  /* ---------- insert bar: drop a command at the cursor ----------
     Only commands that act the moment they are typed live here (line-start
     markers and img/file tokens). A line-start command
     (data-insert-kind="line", the default) always lands at the start of a
     line, because the parser only recognises those at the start of a line. An
     inline command (data-insert-kind="inline", e.g. the Link button) is
     dropped in place at the cursor instead. If text is selected, the marker
     is put in front of it. */
  function insertAtCursor(text) {
    contentInput.focus();
    var done = false;
    try { done = document.execCommand("insertText", false, text); } catch (e) { done = false; }
    if (!done) {
      var s = contentInput.selectionStart, e2 = contentInput.selectionEnd;
      contentInput.setRangeText(text, s, e2, "end");
      contentInput.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }

  shell.querySelectorAll("[data-insert]").forEach(function (btn) {
    btn.addEventListener("mousedown", function (event) { event.preventDefault(); });
    btn.addEventListener("click", function () {
      var token = btn.getAttribute("data-insert");
      var value = contentInput.value;
      var start = contentInput.selectionStart;
      var end = contentInput.selectionEnd;
      var atLineStart = start === 0 || value.charAt(start - 1) === "\n";
      var selected = value.slice(start, end);
      var inline = btn.getAttribute("data-insert-kind") === "inline";

      /* a selection that is already a whole line keeps its text, the marker goes in front */
      var prefix = (!inline && !atLineStart) ? "\n" : "";
      contentInput.focus();
      if (selected) {
        contentInput.setSelectionRange(start, end);
        insertAtCursor(prefix + token + selected);
      } else {
        insertAtCursor(prefix + token);
      }
    });
  });

  /* ---------- formatting guide: collapse toggle + Copy All ---------- */
  function setGuideOpen(open) {
    if (!guideEl || !guideToggleBtn) return;
    guideEl.classList.toggle("is-collapsed", !open);
    guideToggleBtn.setAttribute("aria-expanded", open ? "true" : "false");
    guideToggleBtn.textContent = open ? "Hide guide" : "Read before publishing";
  }
  if (guideToggleBtn) {
    guideToggleBtn.addEventListener("click", function () {
      setGuideOpen(guideEl.classList.contains("is-collapsed"));
    });
    setGuideOpen(false);
  }

  function buildGuideText() {
    var guide = shell.querySelector("[data-format-guide]");
    if (!guide) return "";
    var out = ["FORMATTING GUIDE", "Follow the review checks before you publish. The formatting codes are optional but help segment the article for search engines."];
    guide.querySelectorAll("[data-guide-section]").forEach(function (section) {
      out.push("", section.getAttribute("data-guide-section").toUpperCase());
      section.querySelectorAll("[data-guide-item]").forEach(function (item) {
        out.push("- " + item.getAttribute("data-guide-item"));
      });
    });
    return out.join("\n");
  }

  function fallbackCopy(text) {
    var area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.cssText = "position:fixed;top:0;left:0;opacity:0;";
    document.body.appendChild(area);
    area.select();
    var done = false;
    try { done = document.execCommand("copy"); } catch (e) { done = false; }
    area.remove();
    return done;
  }

  if (guideCopyBtn) {
    var copyResetTimer = null;
    guideCopyBtn.addEventListener("click", function () {
      var text = buildGuideText();
      var copyLabel = guideCopyBtn.getAttribute("data-label") || guideCopyBtn.textContent;
      guideCopyBtn.setAttribute("data-label", copyLabel);
      function showCopied(ok) {
        guideCopyBtn.textContent = ok ? "Copied" : "Copy failed";
        if (copyResetTimer) window.clearTimeout(copyResetTimer);
        copyResetTimer = window.setTimeout(function () {
          guideCopyBtn.textContent = copyLabel;
        }, 1800);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () { showCopied(true); }, function () { showCopied(fallbackCopy(text)); });
      } else {
        showCopied(fallbackCopy(text));
      }
    });
  }

  /* ---------- mobile: Write / Preview tabs ----------
     On a phone only one pane shows at a time, so the author never scrolls
     past a long preview to reach the form. Desktop keeps both panes. */
  function setView(view) {
    if (!MOBILE_QUERY.matches || shell.getAttribute("data-view") === view) return;
    shell.setAttribute("data-view", view);
    tabButtons.forEach(function (tab) {
      var active = tab.getAttribute("data-editor-tab") === view;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", active ? "true" : "false");
    });
    if (view === "preview") renderPreview();
    var top = shell.getBoundingClientRect().top + window.pageYOffset;
    if (window.pageYOffset > top) window.scrollTo({ top: top, behavior: "smooth" });
  }

  tabButtons.forEach(function (tab) {
    tab.addEventListener("click", function () { setView(tab.getAttribute("data-editor-tab")); });
  });

  /* The site sets `html { scroll-behavior: smooth }`. On the editor that
     fights the browser's own "keep the caret in view" scrolling while the
     author types, so the page looks like it scrolls on its own. Force instant
     scrolling for this tool page; the Write/Preview tab switch still asks for
     smooth explicitly. */
  document.documentElement.style.scrollBehavior = "auto";

  /* the sticky insert bar sits right under the sticky toolbar */
  function syncToolbarHeight() {
    if (toolbarEl) shell.style.setProperty("--editor-toolbar-h", toolbarEl.offsetHeight + "px");
  }
  syncToolbarHeight();
  if (window.ResizeObserver && toolbarEl) new ResizeObserver(syncToolbarHeight).observe(toolbarEl);
  window.addEventListener("resize", syncToolbarHeight);

  /* the textarea grows with its text on small screens (page scroll only) */
  function autosizeContent() {
    if (!MOBILE_QUERY.matches) { contentInput.style.height = ""; return; }
    contentInput.style.height = "auto";
    contentInput.style.height = contentInput.scrollHeight + 2 + "px";
  }
  contentInput.addEventListener("input", autosizeContent);
  if (MOBILE_QUERY.addEventListener) MOBILE_QUERY.addEventListener("change", autosizeContent);

  /* ---------- wire up + reveal ---------- */
  /* no listener on the heading: it is locked and never changes */
  imageInput.addEventListener("input", schedulePreview);
  imageInfoInput.addEventListener("input", schedulePreview);
  categorySelect.addEventListener("change", schedulePreview);
  contentInput.addEventListener("input", schedulePreview);

  /*  Changing the Table of contents level only changes how the list looks, so
      it refreshes the preview immediately. The select shows its own value, so
      there is no separate state word to keep in sync. */
  if (tocModeSelect) {
    tocModeSelect.addEventListener("change", schedulePreview);
  }

  renderPreview();
  applyPreviewState(shell.classList.contains("preview-off"));

  shell.classList.remove("is-loading");
  shell.classList.add("is-ready");
  if (note) note.remove();
  toggleBtn.hidden = false;
  publishBtn.disabled = false;
})();
