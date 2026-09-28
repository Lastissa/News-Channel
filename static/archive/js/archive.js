/* /archive/ page behavior:
   - the "+ Add Image / File" htmx popup (blurred wait state with a 5
     second watchdog), its live preview (picture thumbnail or file icon),
     and the multipart upload submit inside it (real upload-progress bar,
     submit button locked for the whole upload).
   - the "Edit Added Images" htmx popup uses the same watchdog/close
     plumbing; its own edit/delete rows are plain htmx forms (see
     ARCHIVE/templates/ARCHIVE/partials/manage_row.html) -- edit/replace
     gets the same "Save" lock + progress bar treatment as the Add modal so
     the two upload paths behave consistently, and both forms fire the
     "archive:refresh" event on success (via an HX-Trigger response
     header) to keep the public grid behind the popup in sync.
   - Prev/page-number/Next (gallery_grid.html) and the manage popup's
     "Load more" button are plain hx-post + hx-target, but every htmx
     paginator on this page gets a loading state (skeleton cards sized to
     the page size + a locked nav for the numbered pager, a locked/labelled
     button for "Load more") so a page/description-search swap never looks
     like the button just froze, and the grid's height animates instead of
     jumping when the new page has fewer cards than the last one. */
(function () {
  "use strict";

  var shell = document.querySelector(".archive-shell");
  if (!shell) return;

  var MODAL_TIMEOUT_MS = 5000;

  var mainContent = document.getElementById("main-content");
  var overlayHost = document.querySelector("[data-archive-overlay]");
  var galleryEndpoint = shell.dataset.galleryEndpoint;

  function getCookie(name) {
    var match = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
    return match ? decodeURIComponent(match.pop()) : "";
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

  var toastHost = null;
  function toast(message, tone) {
    if (!toastHost) {
      toastHost = document.createElement("div");
      toastHost.setAttribute("aria-live", "polite");
      toastHost.style.cssText = "position:fixed;left:50%;bottom:22px;transform:translateX(-50%);z-index:2700;display:flex;flex-direction:column;gap:8px;align-items:center;";
      document.body.appendChild(toastHost);
    }
    var node = document.createElement("div");
    node.textContent = message;
    node.style.cssText =
      "font-family:var(--font-body);font-size:0.86rem;padding:10px 16px;border-radius:8px;color:var(--toast-fg);text-align:center;max-width:min(92vw,480px);" +
      "background:" + (tone === "error" ? "var(--toast-bg-error)" : "var(--toast-bg)") + ";box-shadow:0 8px 20px rgba(0,0,0,0.25);" +
      "opacity:0;transform:translateY(6px);transition:opacity .18s ease, transform .18s ease;";
    toastHost.appendChild(node);
    requestAnimationFrame(function () {
      node.style.opacity = "1";
      node.style.transform = "translateY(0)";
    });
    window.setTimeout(function () {
      node.style.opacity = "0";
      node.style.transform = "translateY(6px)";
      window.setTimeout(function () { node.remove(); }, 200);
    }, 2600);
  }

  function refreshGridToPage1() {
    if (window.htmx && galleryEndpoint) {
      window.htmx.ajax("POST", galleryEndpoint, {
        target: "#archive-grid-shell",
        swap: "innerHTML",
        /* keep whatever is typed in the description search, so the refresh
           after an upload/edit doesn't silently drop the filter */
        values: { page: 1, descr: (document.querySelector("[data-archive-search]") || {}).value || "" },
        headers: { "X-CSRFToken": getCookie("csrftoken") },
      });
    }
  }

  /* ---------- gallery pagination: skeleton cards + no-freeze buttons ----------
     #archive-grid-shell itself now stays in the DOM across every page /
     description-search swap (see gallery.html) -- only its *contents* are
     replaced (hx-swap="innerHTML") -- so it is safe to measure and animate
     its height here, and to temporarily overwrite its contents with a
     skeleton without the shell element itself getting thrown away mid
     request. Without this, pressing Prev/Next/a page number did nothing
     visible at all until the swap landed, which is what read as "frozen". */
  var gridShell = document.getElementById("archive-grid-shell");

  function buildGridSkeleton(count) {
    var card =
      '<article class="archive-card archive-skeleton-card" aria-hidden="true">' +
        '<div class="archive-card-media archive-skeleton-media"></div>' +
        '<div class="archive-card-body">' +
          '<div class="archive-skeleton-line"></div>' +
          '<div class="archive-skeleton-line is-short"></div>' +
          '<div class="archive-skeleton-actions"><div class="archive-skeleton-line"></div><div class="archive-skeleton-line"></div></div>' +
        '</div>' +
      '</article>';
    var cards = "";
    for (var i = 0; i < count; i++) cards += card;
    return '<div class="archive-grid archive-skeleton-grid">' + cards + '</div>';
  }

  /* animates gridShell's height from whatever it is locked at right now to
     its natural (post-swap) height -- shrinking a little slower than
     growing feels less jarring when a later page has fewer cards. */
  function settleGridHeight() {
    var lockedHeight = parseFloat(gridShell.style.height) || gridShell.scrollHeight;
    var naturalHeight = gridShell.scrollHeight;
    var isShrinking = naturalHeight < lockedHeight;
    var duration = isShrinking ? 420 : 260;

    gridShell.style.transition = "height " + duration + "ms cubic-bezier(0.22, 1, 0.36, 1)";
    /* two rAFs: the first lets the just-swapped-in DOM paint at its natural
       height so scrollHeight above is accurate, the second actually kicks
       off the transition from the locked height to that natural height. */
    requestAnimationFrame(function () {
      gridShell.style.height = naturalHeight + "px";
      window.setTimeout(function () {
        gridShell.style.transition = "";
        gridShell.style.height = "";
        gridShell.style.overflow = "";
      }, duration);
    });
  }

  if (gridShell) {
    var pendingGridHTML = null;

    gridShell.addEventListener("htmx:beforeRequest", function (event) {
      var btn = event.target.closest && event.target.closest("[data-archive-page-btn]");
      if (!btn) return;

      pendingGridHTML = gridShell.innerHTML;
      gridShell.style.height = gridShell.offsetHeight + "px";
      gridShell.style.overflow = "hidden";
      gridShell.classList.add("is-paginating");

      var pageSize = parseInt(gridShell.dataset.archivePageSize, 10) || 5;
      gridShell.innerHTML = buildGridSkeleton(pageSize);
    });

    gridShell.addEventListener("htmx:afterSwap", function () {
      if (!gridShell.classList.contains("is-paginating")) return;
      gridShell.classList.remove("is-paginating");
      pendingGridHTML = null;
      settleGridHeight();
    });

    function recoverFailedPage(event) {
      if (!gridShell.classList.contains("is-paginating")) return;
      gridShell.classList.remove("is-paginating");
      if (pendingGridHTML !== null) gridShell.innerHTML = pendingGridHTML;
      pendingGridHTML = null;
      gridShell.style.transition = "";
      gridShell.style.height = "";
      gridShell.style.overflow = "";
      var responseText = event.detail && event.detail.xhr ? event.detail.xhr.responseText : "";
      toast(extractDetail(responseText, "Could not load that page."), "error");
    }
    gridShell.addEventListener("htmx:responseError", recoverFailedPage);
    gridShell.addEventListener("htmx:sendError", recoverFailedPage);
    gridShell.addEventListener("htmx:timeout", recoverFailedPage);
  }

  /* ---------- manage popup "Load more" button: same idea, lighter touch --
     it only ever appends more rows (hx-target="this" hx-swap="outerHTML"
     replaces the button itself with the next page's rows + a fresh button),
     so there's nothing to shrink -- it just needs to stop looking frozen
     and stop accepting a second click while the request is in flight. */
  document.body.addEventListener("htmx:beforeRequest", function (event) {
    var loadMoreBtn = event.target.closest && event.target.closest(".archive-manage-more");
    if (!loadMoreBtn) return;
    loadMoreBtn.disabled = true;
    loadMoreBtn.dataset.originalLabel = loadMoreBtn.textContent;
    loadMoreBtn.textContent = "Loading more...";
    loadMoreBtn.classList.add("is-loading");
  });

  function recoverLoadMoreButton(event) {
    var loadMoreBtn = event.target.closest && event.target.closest(".archive-manage-more");
    if (!loadMoreBtn) return;
    loadMoreBtn.disabled = false;
    loadMoreBtn.classList.remove("is-loading");
    loadMoreBtn.textContent = loadMoreBtn.dataset.originalLabel || "Load more";
    toast("Could not load more items.", "error");
  }
  document.body.addEventListener("htmx:responseError", recoverLoadMoreButton);
  document.body.addEventListener("htmx:sendError", recoverLoadMoreButton);
  document.body.addEventListener("htmx:timeout", recoverLoadMoreButton);

  var currentPreviewObjectUrl = null;

  function revokePreviewObjectUrl() {
    if (currentPreviewObjectUrl) {
      URL.revokeObjectURL(currentPreviewObjectUrl);
      currentPreviewObjectUrl = null;
    }
  }

  function closeModal() {
    revokePreviewObjectUrl();
    if (overlayHost) overlayHost.innerHTML = "";
  }

  /* ---------- Add Image / File: show a preview of whatever was chosen
     before it uploads. A picture gets the usual thumbnail + pre-filled
     width/height (still editable) and shows the image-only fields; any
     other file gets a plain file icon + its name, and the image-only
     fields (width/height/quality) are hidden since they don't apply. ---------- */
  document.addEventListener("change", function (event) {
    var fileInput = event.target;
    if (!fileInput.matches || !fileInput.matches("[data-archive-upload-file]")) return;

    var form = fileInput.closest("[data-archive-upload-form]");
    if (!form) return;

    var previewWrap = form.querySelector("[data-archive-upload-preview]");
    var previewImg = form.querySelector("[data-archive-upload-preview-img]");
    var previewFile = form.querySelector("[data-archive-upload-preview-file]");
    var previewFilename = form.querySelector("[data-archive-upload-preview-filename]");
    var widthInput = form.querySelector("#archive-upload-width");
    var heightInput = form.querySelector("#archive-upload-height");
    var imageOnlyFields = form.querySelectorAll("[data-archive-image-only]");

    revokePreviewObjectUrl();

    var file = fileInput.files && fileInput.files[0];
    if (!file) {
      if (previewWrap) previewWrap.hidden = true;
      if (previewImg) { previewImg.hidden = true; previewImg.removeAttribute("src"); }
      if (previewFile) previewFile.hidden = true;
      for (var i = 0; i < imageOnlyFields.length; i++) imageOnlyFields[i].style.display = "";
      return;
    }

    var isImage = (file.type || "").indexOf("image/") === 0;

    for (var j = 0; j < imageOnlyFields.length; j++) {
      imageOnlyFields[j].style.display = isImage ? "" : "none";
    }

    if (isImage) {
      currentPreviewObjectUrl = URL.createObjectURL(file);
      if (previewImg) { previewImg.src = currentPreviewObjectUrl; previewImg.hidden = false; }
      if (previewFile) previewFile.hidden = true;
      if (previewWrap) previewWrap.hidden = false;

      var probe = new Image();
      probe.onload = function () {
        if (widthInput && !widthInput.value) widthInput.value = probe.naturalWidth;
        if (heightInput && !heightInput.value) heightInput.value = probe.naturalHeight;
      };
      probe.src = currentPreviewObjectUrl;
    } else {
      if (previewImg) previewImg.hidden = true;
      if (previewFile) previewFile.hidden = false;
      if (previewFilename) previewFilename.textContent = file.name;
      if (previewWrap) previewWrap.hidden = false;
      if (widthInput) widthInput.value = "";
      if (heightInput) heightInput.value = "";
    }
  });

  /* ---------- Add Image/File + Edit Added Images: blur the page while
     the htmx popup loads, unblur (+ timeout message) if nothing arrives
     within 5 seconds. Both header buttons share this behavior. ---------- */
  function bindOpenWatchdog(btn) {
    if (!btn || !overlayHost || !mainContent) return;
    var watchdogTimer = null;
    var pendingXhr = null;

    btn.addEventListener("htmx:beforeRequest", function (event) {
      pendingXhr = event.detail && event.detail.xhr;
      mainContent.classList.add("archive-page-blur");
      watchdogTimer = window.setTimeout(function () {
        watchdogTimer = null;
        if (pendingXhr) { try { pendingXhr.abort(); } catch (err) { /* already settled */ } }
        pendingXhr = null;
        mainContent.classList.remove("archive-page-blur");
        toast("Timeout, please try again.", "error");
      }, MODAL_TIMEOUT_MS);
    });

    btn.addEventListener("htmx:afterRequest", function (event) {
      pendingXhr = null;
      if (watchdogTimer) { window.clearTimeout(watchdogTimer); watchdogTimer = null; }
      mainContent.classList.remove("archive-page-blur");

      var status = event.detail && event.detail.xhr ? event.detail.xhr.status : 0;
      if (!event.detail.successful && status !== 0) {
        var responseText = event.detail.xhr ? event.detail.xhr.responseText : "";
        toast(extractDetail(responseText, "Could not open the popup."), "error");
      }
      /* status === 0 already got its own message from the watchdog above,
         unless it was a plain network drop -- either way nothing more to say. */
    });
  }

  bindOpenWatchdog(document.querySelector("[data-archive-add-btn]"));
  bindOpenWatchdog(document.querySelector("[data-archive-manage-btn]"));

  /* ---------- close the popup: backdrop, close button, Escape ---------- */
  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-archive-modal-close]")) closeModal();
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && overlayHost && overlayHost.querySelector("[data-archive-modal]")) closeModal();
  });

  /* ---------- Edit Added Images: an edit/save or a delete inside the
     manage popup re-renders the manage list itself via plain htmx (see
     manage_row.html) and, on success, sends back an "HX-Trigger:
     archive:refresh" response header -- htmx turns that into a DOM event
     on the element that made the request, which bubbles up to here. ---------- */
  document.body.addEventListener("archive:refresh", function () {
    refreshGridToPage1();
  });

  /* ---------- shared upload-progress-bar helpers: both the Add modal
     (below) and the manage-row "replace picture/file" edit form (further
     down) show the same thin bar under their button while bytes are
     actually going up, so the two upload paths in this popup behave
     consistently instead of one having a bar and the other nothing. ---------- */
  function showUploadProgress(container) {
    var bar = container && container.querySelector("[data-archive-upload-progress]");
    if (!bar) return null;
    bar.hidden = false;
    var fill = bar.querySelector("[data-archive-upload-progress-fill]");
    if (fill) fill.style.width = "0%";
    return fill;
  }

  function hideUploadProgress(container) {
    var bar = container && container.querySelector("[data-archive-upload-progress]");
    if (!bar) return;
    bar.hidden = true;
    var fill = bar.querySelector("[data-archive-upload-progress-fill]");
    if (fill) fill.style.width = "0%";
  }

  /* ---------- Add Image/File: the actual upload submit. Plain XHR (not
     fetch, and not htmx) so real upload-progress events are available --
     fetch has no reliable cross-browser upload progress, and this is a
     multipart file upload like every other upload form in this project. ---------- */
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.matches || !form.matches("[data-archive-upload-form]")) return;
    event.preventDefault();

    if (form.dataset.submitting === "true") return; //   already uploading, ignore a second Enter/click
    form.dataset.submitting = "true";

    var endpoint = form.dataset.endpoint;
    var errorNode = form.parentElement.querySelector("[data-archive-upload-error]");
    var submitBtn = form.querySelector("[data-archive-upload-submit]");
    if (errorNode) { errorNode.hidden = true; errorNode.textContent = ""; }
    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = "Uploading..."; }
    var progressFill = showUploadProgress(form);

    function finishSubmit() {
      form.dataset.submitting = "false";
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = "Upload"; }
      hideUploadProgress(form);
    }

    var xhr = new XMLHttpRequest();
    xhr.open("POST", endpoint, true);
    xhr.setRequestHeader("X-CSRFToken", getCookie("csrftoken"));
    xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");

    xhr.upload.addEventListener("progress", function (progressEvent) {
      if (progressFill && progressEvent.lengthComputable) {
        progressFill.style.width = ((progressEvent.loaded / progressEvent.total) * 100) + "%";
      }
    });

    xhr.addEventListener("load", function () {
      var payload = {};
      try { payload = JSON.parse(xhr.responseText || "{}") || {}; } catch (e) { /* non JSON body, fall back below */ }
      var ok = xhr.status >= 200 && xhr.status < 300;

      finishSubmit();

      if (!ok) {
        var message = payload.detail || "Could not upload.";
        if (errorNode) { errorNode.textContent = message; errorNode.hidden = false; }
        else toast(message, "error");
        return;
      }

      closeModal();
      toast(payload.detail || "Added to the archive.");

      /* Refresh the grid back to page 1 so the new item shows up at the
         top, the same way the rest of the archive pager swaps. */
      refreshGridToPage1();
    });

    xhr.addEventListener("error", function () {
      finishSubmit();
      if (errorNode) { errorNode.textContent = "Network error. Nothing was uploaded."; errorNode.hidden = false; }
    });
    xhr.addEventListener("abort", finishSubmit);

    xhr.send(new FormData(form));
  });

  /* ---------- Edit Added Images: the inline "Save" form (description, and
     optionally a replacement picture/file) is a plain htmx multipart form
     -- lock the Save button and drive the same progress bar off htmx's own
     "htmx:xhr:progress" event (the real upload-progress bytes for this
     request), so replacing a file here feels exactly like the Add modal's
     upload above instead of just sitting there with no feedback. ---------- */
  document.body.addEventListener("htmx:beforeRequest", function (event) {
    var form = event.target.closest && event.target.closest(".archive-manage-row-form");
    if (!form) return;
    var btn = form.querySelector("button[type='submit']");
    if (btn) {
      btn.disabled = true;
      btn.dataset.originalLabel = btn.textContent;
      btn.textContent = "Saving...";
    }
    showUploadProgress(form);
  });

  document.body.addEventListener("htmx:xhr:progress", function (event) {
    var form = event.target.closest && event.target.closest(".archive-manage-row-form");
    if (!form) return;
    var fill = form.querySelector("[data-archive-upload-progress-fill]");
    if (fill && event.detail && event.detail.lengthComputable) {
      fill.style.width = ((event.detail.loaded / event.detail.total) * 100) + "%";
    }
  });

  document.body.addEventListener("htmx:afterRequest", function (event) {
    var form = event.target.closest && event.target.closest(".archive-manage-row-form");
    if (!form) return;
    /* on success (2xx, including a validation-error response -- the view
       always re-renders #archive-manage-list either way) the whole list,
       this form included, is replaced from the server response, so
       there's nothing left here to unlock -- only a request that never
       got a usable response back (network drop, 5xx, timeout) needs this
       form put back the way it was. */
    if (event.detail && event.detail.successful) return;
    var btn = form.querySelector("button[type='submit']");
    if (btn) {
      btn.disabled = false;
      btn.textContent = btn.dataset.originalLabel || "Save";
    }
    hideUploadProgress(form);
    var responseText = event.detail && event.detail.xhr ? event.detail.xhr.responseText : "";
    toast(extractDetail(responseText, "Could not save. Please try again."), "error");
  });
})();
