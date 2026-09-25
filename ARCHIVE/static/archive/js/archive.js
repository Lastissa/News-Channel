/* /archive/ page behavior: the "+ Add Image" htmx popup (blurred wait state
   with a 5 second watchdog) and the multipart upload submit inside it.
   Pagination itself needs no JS -- the Prev/page/Next buttons in
   gallery_grid.html are plain hx-post + hx-target and htmx does the swap. */
(function () {
  "use strict";

  var shell = document.querySelector(".archive-shell");
  if (!shell) return;

  var ADD_MODAL_TIMEOUT_MS = 5000;

  var mainContent = document.getElementById("main-content");
  var overlayHost = document.querySelector("[data-archive-overlay]");
  var addBtn = document.querySelector("[data-archive-add-btn]");
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
      "font-family:var(--font-body);font-size:0.86rem;padding:10px 16px;border-radius:8px;color:#fff;text-align:center;max-width:min(92vw,480px);" +
      "background:" + (tone === "error" ? "#B3402A" : "#0E1B2C") + ";box-shadow:0 8px 20px rgba(0,0,0,0.25);" +
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

  /* ---------- Add Image: show a preview of the chosen picture before it
     uploads, and pre-fill width/height from its real size so the required
     boxes rarely need typing by hand -- the uploader can still edit them
     to request a smaller export. ---------- */
  document.addEventListener("change", function (event) {
    var fileInput = event.target;
    if (!fileInput.matches || !fileInput.matches("[data-archive-upload-file]")) return;

    var form = fileInput.closest("[data-archive-upload-form]");
    if (!form) return;

    var previewWrap = form.querySelector("[data-archive-upload-preview]");
    var previewImg = form.querySelector("[data-archive-upload-preview-img]");
    var widthInput = form.querySelector("#archive-upload-width");
    var heightInput = form.querySelector("#archive-upload-height");

    revokePreviewObjectUrl();

    var file = fileInput.files && fileInput.files[0];
    if (!file) {
      if (previewWrap) previewWrap.hidden = true;
      if (previewImg) previewImg.removeAttribute("src");
      return;
    }

    currentPreviewObjectUrl = URL.createObjectURL(file);
    if (previewImg) previewImg.src = currentPreviewObjectUrl;
    if (previewWrap) previewWrap.hidden = false;

    var probe = new Image();
    probe.onload = function () {
      if (widthInput && !widthInput.value) widthInput.value = probe.naturalWidth;
      if (heightInput && !heightInput.value) heightInput.value = probe.naturalHeight;
    };
    probe.src = currentPreviewObjectUrl;
  });

  /* ---------- Add Image: blur the page while the htmx popup loads,
     unblur (+ timeout message) if nothing arrives within 5 seconds ---------- */
  if (addBtn && overlayHost && mainContent) {
    var watchdogTimer = null;
    var pendingXhr = null;

    addBtn.addEventListener("htmx:beforeRequest", function (event) {
      pendingXhr = event.detail && event.detail.xhr;
      mainContent.classList.add("archive-page-blur");
      watchdogTimer = window.setTimeout(function () {
        watchdogTimer = null;
        if (pendingXhr) { try { pendingXhr.abort(); } catch (err) { /* already settled */ } }
        pendingXhr = null;
        mainContent.classList.remove("archive-page-blur");
        toast("Timeout, please try again.", "error");
      }, ADD_MODAL_TIMEOUT_MS);
    });

    addBtn.addEventListener("htmx:afterRequest", function (event) {
      pendingXhr = null;
      if (watchdogTimer) { window.clearTimeout(watchdogTimer); watchdogTimer = null; }
      mainContent.classList.remove("archive-page-blur");

      var status = event.detail && event.detail.xhr ? event.detail.xhr.status : 0;
      if (!event.detail.successful && status !== 0) {
        var responseText = event.detail.xhr ? event.detail.xhr.responseText : "";
        toast(extractDetail(responseText, "Could not open the upload form."), "error");
      }
      /* status === 0 already got its own message from the watchdog above,
         unless it was a plain network drop -- either way nothing more to say. */
    });
  }

  /* ---------- close the popup: backdrop, close button, Escape ---------- */
  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-archive-modal-close]")) closeModal();
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && overlayHost && overlayHost.querySelector("[data-archive-modal]")) closeModal();
  });

  /* ---------- Add Image: the actual upload submit (plain fetch, not htmx,
     so the multipart file upload behaves exactly like every other image
     upload form in this project) ---------- */
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.matches || !form.matches("[data-archive-upload-form]")) return;
    event.preventDefault();

    var endpoint = form.dataset.endpoint;
    var errorNode = form.parentElement.querySelector("[data-archive-upload-error]");
    var submitBtn = form.querySelector("[data-archive-upload-submit]");
    if (errorNode) { errorNode.hidden = true; errorNode.textContent = ""; }
    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = "Uploading..."; }

    var formData = new FormData(form);

    fetch(endpoint, {
      method: "POST",
      headers: { "X-CSRFToken": getCookie("csrftoken"), "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
      body: formData,
    })
      .then(function (response) {
        return response.text().then(function (text) { return { ok: response.ok, text: text }; });
      })
      .then(function (result) {
        var payload = {};
        try { payload = JSON.parse(result.text || "{}") || {}; } catch (e) { /* non JSON body, fall back below */ }

        if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = "Upload image"; }

        if (!result.ok) {
          var message = payload.detail || "Could not upload the image.";
          if (errorNode) { errorNode.textContent = message; errorNode.hidden = false; }
          else toast(message, "error");
          return;
        }

        closeModal();
        toast(payload.detail || "Image added to the archive.");

        /* Refresh the grid back to page 1 so the new picture shows up at
           the top, the same way the rest of the archive pager swaps. */
        if (window.htmx && galleryEndpoint) {
          window.htmx.ajax("POST", galleryEndpoint, {
            target: "#archive-grid-shell",
            swap: "outerHTML",
            values: { page: 1 },
            headers: { "X-CSRFToken": getCookie("csrftoken") },
          });
        }
      })
      .catch(function () {
        if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = "Upload image"; }
        if (errorNode) { errorNode.textContent = "Network error. The image was not uploaded."; errorNode.hidden = false; }
      });
  });
})();
