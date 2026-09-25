(function () {
  "use strict";

  /* ---------- helpers ---------- */
  function getCookie(name) {
    var match = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
    return match ? decodeURIComponent(match.pop()) : "";
  }

  /* Reads the `detail` key out of a JSON response body, whatever the status
     code was. Falls back to genericMessage if the body isn't JSON or has no
     detail key, so a non-JSON error (e.g. a raw HTML 500 page) never crashes
     the handler -- it just shows something reasonable instead. */
  function extractDetail(rawText, genericMessage) {
    if (!rawText) return genericMessage;
    try {
      var data = JSON.parse(rawText);
      return (data && data.detail) ? data.detail : genericMessage;
    } catch (e) {
      return genericMessage;
    }
  }

  var toastHost = null;

  function dismissToast(node) {
    if (!node || node.dataset.dismissed === "true") return;
    node.dataset.dismissed = "true";
    node.style.opacity = "0";
    node.style.transform = "translateY(6px)";
    window.setTimeout(function () { node.remove(); }, 200);
  }

  function toast(message, tone) {
    if (!toastHost) {
      toastHost = document.createElement("div");
      toastHost.setAttribute("aria-live", "polite");
      toastHost.style.cssText = "position:fixed;left:50%;bottom:22px;transform:translateX(-50%);z-index:300;display:flex;flex-direction:column;gap:8px;align-items:center;";
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
      dismissToast(node);
    }, 2600);
  }

  document.addEventListener("DOMContentLoaded", function () {
    var messageNodes = document.querySelectorAll(".django-message");
    if (!messageNodes.length) return;

    messageNodes.forEach(function (node) {
      var text = (node.textContent || "").trim();
      if (!text) return;
      var classes = node.className ? node.className.split(" ") : [];
      var tone = classes.indexOf("error") !== -1 || classes.indexOf("danger") !== -1 ? "error" : "success";
      toast(text, tone);
    });
  });

  /* ---------- bookmark: optimistic toggle, revert on failure ---------- */
  document.addEventListener("click", function (event) {
    var btn = event.target.closest("[data-bookmark-btn]");
    if (!btn || btn.dataset.pending === "true") return;

    var wasSaved = btn.dataset.saved === "true";
    var nextSaved = !wasSaved;
    var countNode = btn.querySelector("[data-bookmark-count]");
    var oldCount = countNode ? Number(countNode.textContent.trim()) || 0 : 0;

    setBookmarkVisual(btn, nextSaved);
    if (countNode) countNode.textContent = String(Math.max(0, oldCount + (nextSaved ? 1 : -1)));
    btn.dataset.pending = "true";
    btn.classList.add("is-pending");

    fetch(btn.dataset.endpoint, {
      method: "POST",
      headers: { "X-CSRFToken": getCookie("csrftoken"), "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
    })
      .then(function (response) {
        return response.text().then(function (text) { return { ok: response.ok, text: text, status: response.status}; });
      })
      .then(function (result) {
        btn.dataset.pending = "false";
        btn.classList.remove("is-pending");
        if (result.status > 299) {
          setBookmarkVisual(btn, wasSaved);
          if (countNode) countNode.textContent = String(oldCount);
          if (result.status === 401) {
            toast(extractDetail(result.text, "Sign in to save stories."), "error");
          } else if (result.status === 403) {
            toast(extractDetail(result.text, "Security check failed. Please reload and try again."), "error");
          } else if (result.status >= 500) {
            toast(extractDetail(result.text, "Server error. Please try again."), "error");
          } else {
            toast(extractDetail(result.text, "Could not update bookmark."), "error");
          }
          return;
        }
        // only get here on success
        var payload = {};
        try { payload = JSON.parse(result.text || "{}") || {}; } catch (e) {}
        if (countNode) {
          if (typeof payload.bookmark_count === "number") {
            countNode.textContent = String(payload.bookmark_count);
          } else {
            countNode.textContent = String(Math.max(0, oldCount + (nextSaved ? 1 : -1)));
          }
        }
        if (typeof payload.bookmarked === "boolean") {
          setBookmarkVisual(btn, payload.bookmarked);
        }
        toast(extractDetail(result.text, "Bookmark updated."));
      })
      .catch(function () {
        btn.dataset.pending = "false";
        btn.classList.remove("is-pending");
        setBookmarkVisual(btn, wasSaved);
        if (countNode) countNode.textContent = String(oldCount);
        toast("Network Error. Story was not saved.", "error");
      });
  });

  function setBookmarkVisual(btn, saved) {
    btn.dataset.saved = saved ? "true" : "false";
    btn.setAttribute("aria-pressed", saved ? "true" : "false");
    btn.classList.toggle("is-saved", saved);
    var path = btn.querySelector("path");
    if (path) path.setAttribute("fill", saved ? "currentColor" : "none");
    if (btn.classList.contains("profile-bookmark-toggle")) {
      btn.setAttribute("aria-label", saved ? "Remove bookmark" : "Save bookmark");
      btn.setAttribute("title", saved ? "Remove bookmark" : "Save bookmark");
    }
  }

  /* ---------- share: copy link, instant feedback ---------- */
  document.addEventListener("click", function (event) {
    var btn = event.target.closest("[data-share-btn]");
    if (!btn) return;
    event.preventDefault();
 var extra = btn.dataset.copyExtra || "";
  var url = btn.dataset.shareUrl || "";
  var text = extra ? url + "\n\n" + extra : url;
  
  if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        toast("Link copied.");
      }).catch(function () {
        toast("Could not copy link.", "error");
      });
    } else {
      window.prompt("Copy this link:", url);
    }
  });

  /* ---------- newsletter: optimistic submit, revert on failure ---------- */
  var newsletterForm = document.getElementById("newsletter-form");
  if (newsletterForm) {
    var statusEl = document.getElementById("newsletter-status");
    var emailInput = document.getElementById("newsletter-email");
    var submitBtn = newsletterForm.querySelector("button[type=submit]");

    newsletterForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var email = emailInput.value.trim();
      if (!email) return;

      var previousValue = email;
      /*  Read the form's data BEFORE clearing the input for the optimistic
          UI below. FormData snapshots the live DOM value, so clearing the
          field first was sending an empty "email" to the view every time. */
      var body = new FormData(newsletterForm);

      statusEl.textContent = "Suscribed.";
      statusEl.className = "newsletter-status is-ok";
      submitBtn.disabled = true;
      emailInput.value = "";

      fetch(newsletterForm.dataset.endpoint, {
        method: "POST",
        headers: { "X-CSRFToken": getCookie("csrftoken"), "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
        body: body,
      })
        .then(function (response) {
          return response.text().then(function (text) { return { ok: response.ok, text: text }; });
        })
        .then(function (result) {
          submitBtn.disabled = false;
          if (!result.ok) {
            emailInput.value = previousValue;
            statusEl.textContent = extractDetail(result.text, "Something went wrong.");
            statusEl.className = "newsletter-status is-error";
          }
        })
        .catch(function () {
          submitBtn.disabled = false;
          emailInput.value = previousValue;
          statusEl.textContent = "Network Error. Please try again.";
          statusEl.className = "newsletter-status is-error";
        });
    });
  }

  document.addEventListener("click", function (event) {
    var toggle = event.target.closest("[data-newsletter-toggle]");
    if (!toggle || toggle.dataset.pending === "true") return;

    var targetUrl = toggle.dataset.enableUrl;
    var previous = toggle.dataset.enabled === "true";
    var next = !previous;
    /* Each toggle carries its own label copy so the same handler serves the
       login alert and the story view reminder without hard coded text. */
    var onText = toggle.dataset.onText || "Receiving updates";
    var offText = toggle.dataset.offText || "Not receiving updates";
    var label = toggle.closest(".setting-row") && toggle.closest(".setting-row").querySelector(".setting-copy small");

    toggle.dataset.pending = "true";
    toggle.classList.add("is-pending");
    toggle.classList.toggle("is-on", next);
    toggle.setAttribute("aria-pressed", String(next));
    toggle.dataset.enabled = String(next);

    if (label) {
      label.textContent = next ? onText : offText;
    }

    fetch(targetUrl, {
      method: "POST",
      headers: {
        "X-CSRFToken": getCookie("csrftoken"),
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/json",
      },
      credentials: "same-origin",
      body: JSON.stringify({ enabled: next }),
    })
      .then(function (response) {
        return response.json().then(function (payload) {
          return { ok: response.ok, payload: payload, status: response.status };
        });
      })
      .then(function (result) {
        toggle.dataset.pending = "false";
        toggle.classList.remove("is-pending");

        if (!result.ok) {
          toggle.classList.toggle("is-on", previous);
          toggle.setAttribute("aria-pressed", String(previous));
          toggle.dataset.enabled = String(previous);
          if (label) {
            label.textContent = previous ? onText : offText;
          }
          toast(extractDetail(JSON.stringify(result.payload || {}), "Could not update the setting."), "error");
          return;
        }

        toggle.classList.toggle("is-on", !!result.payload.enabled);
        toggle.setAttribute("aria-pressed", String(!!result.payload.enabled));
        toggle.dataset.enabled = String(!!result.payload.enabled);
        if (label) {
          label.textContent = result.payload.enabled ? onText : offText;
        }
        toast(result.payload.detail || "Setting updated.");
      })
      .catch(function () {
        toggle.dataset.pending = "false";
        toggle.classList.remove("is-pending");
        toggle.classList.toggle("is-on", previous);
        toggle.setAttribute("aria-pressed", String(previous));
        toggle.dataset.enabled = String(previous);
        if (label) {
          label.textContent = previous ? onText : offText;
        }
        toast("Network Error. The setting was not updated.", "error");
      });
  });

  function isValidHttpUrl(value) {
    if (!value) return false;
    try {
      var parsed = new URL(value);
      return (parsed.protocol === "http:" || parsed.protocol === "https:") && !!parsed.hostname;
    } catch (e) {
      return false;
    }
  }

  document.addEventListener("click", function (event) {
    var previewBtn = event.target.closest("[data-preview-profile-image]");
    if (!previewBtn) return;

    var input = document.getElementById("profile-image-url");
    if (!input) return;

    var value = (input.value || "").trim();
    if (!isValidHttpUrl(value)) {
      toast("Please enter a valid http or https image URL.", "error");
      return;
    }

    var avatar = document.querySelector(".profile-avatar");
    if (avatar) {
      var previousSrc = avatar.src;
      avatar.src = value;
      avatar.onerror = function () {
        this.onerror = null;
        this.src = "/static/404.jpg";
      };
      avatar.dataset.previewSource = value;
      if (previousSrc && previousSrc !== avatar.src) {
        toast("Preview updated.");
      }
    } else {
      toast("Preview updated.");
    }
  });

  document.addEventListener("click", function (event) {
    var saveBtn = event.target.closest("[data-save-profile-image]");
    if (!saveBtn || saveBtn.dataset.pending === "true") return;

    var input = document.getElementById("profile-image-url");
    if (!input) return;

    /* No client side verdict: the view validates and returns its own `detail`
       message, which is what the toast shows for every outcome. */
    var value = (input.value || "").trim();

    saveBtn.dataset.pending = "true";
    saveBtn.disabled = true;
    saveBtn.classList.add("is-pending");

    fetch("/profile/settings/image/", {
      method: "POST",
      headers: {
        "X-CSRFToken": getCookie("csrftoken"),
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
      },
      credentials: "same-origin",
      body: new URLSearchParams({ image_url: value }).toString(),
    })
      .then(function (response) {
        return response.text().then(function (text) { return { ok: response.ok, text: text }; });
      })
      .then(function (result) {
        saveBtn.dataset.pending = "false";
        saveBtn.disabled = false;
        saveBtn.classList.remove("is-pending");

        var payload = {};
        try { payload = JSON.parse(result.text || "{}") || {}; } catch (e) { /* non JSON body, fall back below */ }
        var detail = payload.detail || (result.ok ? "Profile image updated." : "Could not update profile image.");
        if (result.ok) {
          toast(detail);
        } else {
          toast(detail, "error");
          return;
        }

        var avatar = document.querySelector(".profile-avatar");
        if (avatar && payload.image_url) {
          avatar.src = payload.image_url;
          avatar.onerror = function () {
            this.src = "/static/404.jpg";
          };
        }
      })
      .catch(function () {
        saveBtn.dataset.pending = "false";
        saveBtn.disabled = false;
        saveBtn.classList.remove("is-pending");
        toast("Network Error. Profile image was not updated.", "error");
      });
  });

  /* ---------- profile avatar: select, resize, preview, confirm, then upload ----------
     Picking a file only opens the adjust window. The photo is repositioned and
     zoomed there, cropped to a square on a canvas, and nothing leaves the
     browser until "Confirm upload" is pressed. The upload goes to the same
     endpoint as before, and the server stores it over the user's existing
     avatar instead of adding a new image. */
  (function initAvatarCropper() {
    var MAX_AVATAR_BYTES = 8 * 1024 * 1024;   /* largest file we will even open */
    var OUTPUT_PX = 512;                      /* same size as the preset in SERVICE_INTERNAL/images.py */
    var MAX_ZOOM = 4;
    var JPEG_QUALITY = 0.9;
    var ENDPOINT = "/profile/settings/image/";

    var layer = document.querySelector("[data-avatar-crop]");
    var fileInput = document.getElementById("profile-avatar-file");
    var openBtn = document.querySelector("[data-upload-profile-image]");
    if (!layer || !fileInput || !openBtn) return;

    var stage = layer.querySelector("[data-avatar-crop-stage]");
    var stageCanvas = layer.querySelector("[data-avatar-crop-canvas]");
    var previewCanvas = layer.querySelector("[data-avatar-crop-preview]");
    var zoomInput = layer.querySelector("[data-avatar-crop-zoom]");
    var feedback = layer.querySelector("[data-avatar-crop-feedback]");
    var confirmBtn = layer.querySelector("[data-avatar-crop-confirm]");
    var cancelBtn = layer.querySelector("[data-avatar-crop-cancel]");

    /* The whole crop is three numbers: `zoom` (1 = the largest square that
       fits the photo) and `cx`, `cy` (the point of the photo, in its own
       pixels, sitting at the middle of the frame). The visible square is
       always inside the photo, so there is never an empty edge. */
    var img = null;
    var objectUrl = null;
    var zoom = 1;
    var cx = 0;
    var cy = 0;
    var pointers = {};
    var pinchStartDistance = 0;
    var pinchStartZoom = 1;
    var pending = false;
    var isOpen = false;
    var frameQueued = false;

    function clamp(value, low, high) {
      return Math.min(high, Math.max(low, value));
    }

    function sourceSide() {
      return Math.min(img.naturalWidth, img.naturalHeight) / zoom;
    }

    function keepInsidePhoto() {
      zoom = clamp(zoom, 1, MAX_ZOOM);
      var half = sourceSide() / 2;
      cx = clamp(cx, half, img.naturalWidth - half);
      cy = clamp(cy, half, img.naturalHeight - half);
    }

    /* One painter for the stage, the preview and the file that gets uploaded,
       so what the person sees is exactly what is sent. */
    function paint(target, size) {
      if (target.width !== size) {
        target.width = size;
        target.height = size;
      }
      var ctx = target.getContext("2d");
      var side = sourceSide();
      ctx.fillStyle = "#ffffff";   /* only ever shows through a transparent PNG */
      ctx.fillRect(0, 0, size, size);
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = "high";
      ctx.drawImage(img, cx - side / 2, cy - side / 2, side, side, 0, 0, size, size);
    }

    function draw() {
      frameQueued = false;
      if (!img) return;
      var density = Math.min(window.devicePixelRatio || 1, 2);
      paint(stageCanvas, Math.max(160, Math.round(stage.clientWidth * density)));
      paint(previewCanvas, 192);
    }

    function queueDraw() {
      if (frameQueued) return;
      frameQueued = true;
      requestAnimationFrame(draw);
    }

    function panBy(dx, dy) {
      var sourcePerPixel = sourceSide() / stage.clientWidth;
      cx -= dx * sourcePerPixel;
      cy -= dy * sourcePerPixel;
      keepInsidePhoto();
      queueDraw();
    }

    function setZoom(next) {
      zoom = next;
      keepInsidePhoto();
      zoomInput.value = String(zoom);
      queueDraw();
    }

    function setFeedback(message) {
      feedback.textContent = message || "";
      feedback.hidden = !message;
    }

    function setPending(on) {
      pending = on;
      confirmBtn.disabled = on;
      cancelBtn.disabled = on;
      zoomInput.disabled = on;
      confirmBtn.textContent = on ? "Uploading..." : "Confirm upload";
      layer.classList.toggle("is-pending", on);
    }

    function releasePhoto() {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      objectUrl = null;
      img = null;
    }

    function openCropper(file) {
      releasePhoto();
      objectUrl = URL.createObjectURL(file);

      var candidate = new Image();
      candidate.onload = function () {
        img = candidate;
        zoom = 1;
        cx = img.naturalWidth / 2;
        cy = img.naturalHeight / 2;
        zoomInput.min = "1";
        zoomInput.max = String(MAX_ZOOM);
        zoomInput.value = "1";
        setFeedback("");
        setPending(false);
        layer.hidden = false;
        isOpen = true;
        document.documentElement.classList.add("avatar-crop-open");
        draw();
        stage.focus({ preventScroll: true });
      };
      candidate.onerror = function () {
        releasePhoto();
        toast("That file could not be opened as an image.", "error");
      };
      candidate.src = objectUrl;
    }

    function closeCropper() {
      if (pending) return;
      isOpen = false;
      layer.hidden = true;
      document.documentElement.classList.remove("avatar-crop-open");
      pointers = {};
      stage.classList.remove("is-dragging");
      releasePhoto();
      openBtn.focus();
    }

    function sendAvatar(blob) {
      var formData = new FormData();
      formData.append("image_file", blob, "avatar.jpg");

      fetch(ENDPOINT, {
        method: "POST",
        headers: {
          "X-CSRFToken": getCookie("csrftoken"),
          "X-Requested-With": "XMLHttpRequest"
        },
        credentials: "same-origin",
        body: formData,
      })
        .then(function (response) {
          return response.text().then(function (text) { return { ok: response.ok, text: text }; });
        })
        .then(function (result) {
          var payload = {};
          try { payload = JSON.parse(result.text || "{}") || {}; } catch (e) { /* non JSON body, fall back below */ }

          setPending(false);
          if (!result.ok) {
            /* Stay open so the person can retry. The toast host sits under
               this window, so the message is shown inside it. */
            setFeedback(payload.detail || "Could not upload profile image.");
            return;
          }

          var avatar = document.querySelector(".profile-avatar");
          if (avatar && payload.image_url) {
            avatar.src = payload.image_url;
            avatar.onerror = function () {
              this.src = "/static/404.jpg";
            };
          }
          closeCropper();
          toast(payload.detail || "Profile image updated.");
        })
        .catch(function () {
          setPending(false);
          setFeedback("Network Error. Profile image was not uploaded.");
        });
    }

    function confirmUpload() {
      if (pending || !img) return;
      setFeedback("");
      setPending(true);   /* locks the window before the async steps below */

      var output = document.createElement("canvas");
      paint(output, OUTPUT_PX);
      output.toBlob(function (blob) {
        if (!blob) {
          setPending(false);
          setFeedback("Could not prepare this image. Try a different photo.");
          return;
        }
        sendAvatar(blob);
      }, "image/jpeg", JPEG_QUALITY);
    }

    /* ----- opening: the icon button only asks for a file ----- */
    openBtn.addEventListener("click", function () {
      fileInput.click();
    });

    fileInput.addEventListener("change", function () {
      var file = fileInput.files && fileInput.files[0];
      fileInput.value = "";   /* lets the same file be picked again after a cancel */
      if (!file) return;

      if (!/^image\/(jpeg|png|webp|gif)$/.test(file.type)) {
        toast("Unsupported image type. Use JPEG, PNG, WEBP or GIF.", "error");
        return;
      }
      if (file.size > MAX_AVATAR_BYTES) {
        toast("Image is too large. Max allowed size is 8MB.", "error");
        return;
      }
      openCropper(file);
    });

    /* ----- adjusting: drag, pinch, wheel, slider, keyboard ----- */
    function pointerDistance() {
      var ids = Object.keys(pointers);
      var a = pointers[ids[0]];
      var b = pointers[ids[1]];
      return Math.hypot(a.x - b.x, a.y - b.y);
    }

    stage.addEventListener("pointerdown", function (event) {
      if (!img || pending) return;
      stage.setPointerCapture(event.pointerId);
      pointers[event.pointerId] = { x: event.clientX, y: event.clientY };
      if (Object.keys(pointers).length === 2) {
        pinchStartDistance = pointerDistance();
        pinchStartZoom = zoom;
      }
      stage.classList.add("is-dragging");
    });

    stage.addEventListener("pointermove", function (event) {
      var point = pointers[event.pointerId];
      if (!point || !img) return;

      if (Object.keys(pointers).length >= 2) {
        point.x = event.clientX;
        point.y = event.clientY;
        if (pinchStartDistance > 0) setZoom(pinchStartZoom * pointerDistance() / pinchStartDistance);
        return;
      }

      var dx = event.clientX - point.x;
      var dy = event.clientY - point.y;
      point.x = event.clientX;
      point.y = event.clientY;
      panBy(dx, dy);
    });

    function endPointer(event) {
      delete pointers[event.pointerId];
      if (!Object.keys(pointers).length) stage.classList.remove("is-dragging");
    }
    stage.addEventListener("pointerup", endPointer);
    stage.addEventListener("pointercancel", endPointer);

    stage.addEventListener("wheel", function (event) {
      if (!img || pending) return;
      event.preventDefault();
      setZoom(zoom * Math.exp(-event.deltaY * 0.0015));
    }, { passive: false });

    zoomInput.addEventListener("input", function () {
      if (!img) return;
      setZoom(parseFloat(zoomInput.value) || 1);
    });

    stage.addEventListener("keydown", function (event) {
      if (!img || pending) return;
      var step = stage.clientWidth * 0.04;
      var handled = true;
      if (event.key === "ArrowLeft") panBy(-step, 0);
      else if (event.key === "ArrowRight") panBy(step, 0);
      else if (event.key === "ArrowUp") panBy(0, -step);
      else if (event.key === "ArrowDown") panBy(0, step);
      else if (event.key === "+" || event.key === "=") setZoom(zoom + 0.1);
      else if (event.key === "-") setZoom(zoom - 0.1);
      else handled = false;
      if (handled) event.preventDefault();
    });

    /* ----- confirming / leaving ----- */
    confirmBtn.addEventListener("click", confirmUpload);
    cancelBtn.addEventListener("click", closeCropper);

    document.addEventListener("keydown", function (event) {
      if (!isOpen) return;
      if (event.key === "Escape") {
        closeCropper();
        return;
      }
      if (event.key !== "Tab") return;

      /* keep keyboard focus inside the window while it is open */
      var stops = Array.prototype.filter.call(
        layer.querySelectorAll("button, input, [tabindex=\"0\"]"),
        function (node) { return !node.disabled; }
      );
      if (!stops.length) return;
      var first = stops[0];
      var last = stops[stops.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });

    window.addEventListener("resize", function () {
      if (isOpen) queueDraw();
    });
  })();

  /* ---------- profile pagination: bookmarks + reading history share one flow ---------- */
  var PROFILE_LISTS = {
    bookmark: {
      listId: "profile-bookmarks-list",
      endpointKey: "bookmarkEndpoint",
      paginationSelector: ".profile-bookmark-pagination",
      buttonAttr: "data-bookmark-page-btn",
      emptyText: "No bookmarks saved yet.",
      dateKey: "created_at",
      loadError: "Could not load bookmarks.",
      netError: "Connection issue. Bookmarks could not be loaded.",
    },
    history: {
      listId: "profile-history-list",
      endpointKey: "historyEndpoint",
      paginationSelector: ".profile-history-pagination",
      buttonAttr: "data-history-page-btn",
      emptyText: "No reading history yet.",
      dateKey: "date_created",
      loadError: "Could not load history.",
      netError: "Connection issue. History could not be loaded.",
    },
    comment: {
      listId: "profile-comments-list",
      endpointKey: "commentsEndpoint",
      paginationSelector: ".profile-comments-pagination",
      buttonAttr: "data-comments-page-btn",
      emptyText: "No comments yet.",
      excerptKey: "excerpt",
      linkLabel: "View",
      loadError: "Could not load comments.",
      netError: "Connection issue. Comments could not be loaded.",
    },
    staff: {
      listId: "profile-staff-list",
      endpointKey: "staffEndpoint",
      paginationSelector: ".profile-staff-pagination",
      buttonAttr: "data-staff-page-btn",
      emptyText: "No staff accounts found.",
      excerptKey: "detail",
      loadError: "Could not load the staff directory.",
      netError: "Connection issue. The staff directory could not be loaded.",
    },
    staffPublished: {
      listId: "profile-staff-published-list",
      endpointKey: "staffPublishedEndpoint",
      paginationSelector: ".profile-staff-published-pagination",
      buttonAttr: "data-staff-published-page-btn",
      emptyText: "No stories published yet.",
      excerptKey: "detail",
      loadError: "Could not load the published news.",
      netError: "Connection issue. The published news could not be loaded.",
    },
    published: {
      listId: "profile-published-list",
      endpointKey: "publishedEndpoint",
      paginationSelector: ".profile-published-pagination",
      buttonAttr: "data-published-page-btn",
      emptyText: "No stories published yet.",
      dateKey: "date_created",
      viewsKey: "views",
      loadError: "Could not load published stories.",
      netError: "Connection issue. Published stories could not be loaded.",
    },
  };

  function renderProfileItems(config, payload) {
    var items = payload.items || [];
    if (!items.length) return '<p class="empty-copy">' + config.emptyText + "</p>";

    var linkLabel = config.linkLabel || "Open";
    var html = '<ul class="profile-list">';
    items.forEach(function (item) {
      var detailText = "";
      if (config.excerptKey) {
        detailText = item[config.excerptKey] || "";
      } else {
        var parts = [];
        if (config.viewsKey && typeof item[config.viewsKey] === "number") {
          parts.push(item[config.viewsKey] + " view" + (item[config.viewsKey] === 1 ? "" : "s"));
        }
        var rawDate = item[config.dateKey];
        if (rawDate) {
          parts.push(new Date(rawDate).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }));
        }
        detailText = parts.join(" \u2022 ");
      }
      var actions = '<a href="' + (item.url || '/story/' + item.blog_id + '/') + '">' + linkLabel + '</a>';
      if (config === PROFILE_LISTS.bookmark) {
        actions += '<button type="button" class="profile-bookmark-toggle" data-bookmark-btn data-endpoint="/bookmark/' + item.blog_id + '/" data-saved="true" aria-pressed="true" aria-label="Remove bookmark" title="Remove bookmark">' +
          '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M6.5 3.5h11a1 1 0 0 1 1 1V21l-6.5-4-6.5 4V4.5a1 1 0 0 1 1-1Z" fill="currentColor"/></svg>' +
          '<span class="visually-hidden">Remove bookmark</span></button>';
        actions = '<div class="profile-bookmark-actions">' + actions + '</div>';
      }
      if (config === PROFILE_LISTS.published) {
        actions += '<form method="post" data-published-story-delete-form data-endpoint="/profile/stories/' + item.blog_id + '/delete/">' +
          '<button type="submit" class="published-story-delete-btn" aria-label="Delete ' + (item.heading || "Untitled story") + '" title="Delete story">' +
          '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13M10 11v5m4-5v5"/></svg>' +
          '<span class="visually-hidden">Delete story</span></button></form>';
        actions = '<div class="published-story-actions">' + actions + '</div>';
      }
      html += '<li' + (config === PROFILE_LISTS.published ? ' data-published-story-item' : '') + '><div><strong>' + (item.heading || "Untitled story") + '</strong><small>' + detailText + '</small></div>' + actions + '</li>';
    });
    return html + "</ul>";
  }

  /* ---------- published story deletion ---------- */
  document.addEventListener("submit", function (event) {
    var form = event.target.closest("[data-published-story-delete-form]");
    if (!form) return;
    event.preventDefault();

    if (!window.confirm("Delete this story? This cannot be undone.")) return;

    var button = form.querySelector("button[type='submit']");
    if (!button || button.dataset.pending === "true") return;

    button.dataset.pending = "true";
    button.disabled = true;

    fetch(form.dataset.endpoint || form.action, {
      method: "POST",
      headers: { "X-CSRFToken": getCookie("csrftoken"), "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
    })
      .then(function (response) {
        return response.text().then(function (text) { return { ok: response.ok, text: text }; });
      })
      .then(function (result) {
        if (!result.ok) {
          button.dataset.pending = "false";
          button.disabled = false;
          toast(extractDetail(result.text, "Could not delete the story."), "error");
          return;
        }

        var item = form.closest("[data-published-story-item]");
        if (item) item.remove();

        var list = document.getElementById("profile-published-list");
        if (list && !list.querySelector("[data-published-story-item]")) {
          list.innerHTML = '<p class="empty-copy">No stories published yet.</p>';
        }

        var total = document.querySelector("#published-stories .panel-tag");
        if (total) {
          var count = Number((total.textContent || "").trim().split(" ")[0]);
          if (!isNaN(count)) total.textContent = Math.max(0, count - 1) + " total";
        }
        toast(extractDetail(result.text, "Story deleted."));
      })
      .catch(function () {
        button.dataset.pending = "false";
        button.disabled = false;
        toast("Connection issue. The story was not deleted.", "error");
      });
  });

  /* ---------- add news link: quick connection check before opening ---------- */
  document.addEventListener("click", function (event) {
    var link = event.target.closest("[data-add-news-link]");
    if (!link) return;
    event.preventDefault();

    /* Fast path: the OS already reports no network. navigator.onLine alone is
       not enough though (it can stay true with no real internet), so an open
       connection is confirmed with a cheap HEAD probe before navigating. */
    if (!window.navigator.onLine) {
      toast("internet connection disabled", "error");
      return;
    }

    var controller = new AbortController();
    var timedOut = window.setTimeout(function () { controller.abort(); }, 4000);

    fetch(link.href, { method: "HEAD", cache: "no-store", credentials: "same-origin", signal: controller.signal })
      .then(function () {
        window.clearTimeout(timedOut);
        window.location.href = link.href;
      })
      .catch(function () {
        window.clearTimeout(timedOut);
        toast("internet connection disabled", "error");
      });
  });

  /* ---------- staff profile: single save, sync canonical values on success ---------- */
  var staffForm = document.querySelector("[data-staff-profile-form]");
  if (staffForm) {
    var staffSaveBtn = staffForm.querySelector("[data-staff-save-btn]");

    staffForm.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!staffSaveBtn || staffSaveBtn.dataset.pending === "true") return;

      var fullNameInput = staffForm.querySelector("input[name='full_name']");
      if (fullNameInput && !fullNameInput.value.trim()) {
        toast("Full name cannot be empty.", "error");
        fullNameInput.focus();
        return;
      }

      var originalText = staffSaveBtn.textContent;
      staffSaveBtn.dataset.pending = "true";
      staffSaveBtn.disabled = true;
      staffSaveBtn.classList.add("is-pending");
      staffSaveBtn.textContent = "Saving...";

      fetch(staffForm.dataset.endpoint, {
        method: "POST",
        headers: { "X-CSRFToken": getCookie("csrftoken"), "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
        body: new FormData(staffForm),
      })
        .then(function (response) {
          return response.text().then(function (text) { return { ok: response.ok, text: text, status: response.status }; });
        })
        .then(function (result) {
          staffSaveBtn.dataset.pending = "false";
          staffSaveBtn.disabled = false;
          staffSaveBtn.classList.remove("is-pending");
          staffSaveBtn.textContent = originalText;

          if (!result.ok) {
            toast(extractDetail(result.text, "Could not update the staff profile."), "error");
            return;
          }

          var payload = {};
          try { payload = JSON.parse(result.text || "{}") || {}; } catch (e) {}

          if (fullNameInput && typeof payload.full_name === "string") {
            fullNameInput.value = payload.full_name;
            var identityName = document.querySelector(".profile-identity-copy h2");
            if (identityName && payload.full_name) identityName.textContent = payload.full_name;
          }
          if (typeof payload.speciality_csv === "string") {
            var specInput = staffForm.querySelector("input[name='speciality']");
            if (specInput) specInput.value = payload.speciality_csv;
          }
          toast(payload.detail || "Staff profile updated.");
        })
        .catch(function () {
          staffSaveBtn.dataset.pending = "false";
          staffSaveBtn.disabled = false;
          staffSaveBtn.classList.remove("is-pending");
          staffSaveBtn.textContent = originalText;
          toast("Connection issue. Staff profile was not updated.", "error");
        });
    });
  }

  document.addEventListener("click", function (event) {
    var pageBtn = event.target.closest("[data-bookmark-page-btn], [data-history-page-btn], [data-comments-page-btn], [data-published-page-btn], [data-staff-page-btn], [data-staff-published-page-btn]");
    if (!pageBtn) return;

    var kind = "bookmark";
    if (pageBtn.hasAttribute("data-history-page-btn")) kind = "history";
    else if (pageBtn.hasAttribute("data-comments-page-btn")) kind = "comment";
    else if (pageBtn.hasAttribute("data-published-page-btn")) kind = "published";
    else if (pageBtn.hasAttribute("data-staff-published-page-btn")) kind = "staffPublished";
    else if (pageBtn.hasAttribute("data-staff-page-btn")) kind = "staff";
    var config = PROFILE_LISTS[kind];
    var list = document.getElementById(config.listId);
    if (!list) return;

    var endpoint = list.dataset[config.endpointKey];
    var page = pageBtn.dataset.page;
    if (!endpoint || !page) return;

    list.classList.add("is-animating");
    var previousHeight = list.offsetHeight || 0;
    list.style.height = previousHeight + "px";
    list.style.overflow = "hidden";

    fetch(endpoint + "?page=" + encodeURIComponent(page), {
      method: "GET",
      headers: { "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
    })
      .then(function (response) {
        return response.json().then(function (payload) {
          return { ok: response.ok, payload: payload, status: response.status };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          list.classList.remove("is-animating");
          list.style.height = "";
          list.style.overflow = "";
          toast(extractDetail(JSON.stringify(result.payload || {}), config.loadError), "error");
          return;
        }

        list.innerHTML = renderProfileItems(config, result.payload);

        requestAnimationFrame(function () {
          var nextHeight = list.scrollHeight || 0;
          var isShrinking = nextHeight < previousHeight;
          var duration = isShrinking ? 420 : 260;

          list.style.transition = "height " + duration + "ms cubic-bezier(0.22, 1, 0.36, 1), opacity 180ms ease, transform 180ms ease";
          list.style.height = nextHeight + "px";
          list.classList.remove("is-animating");
          list.style.opacity = "1";
          list.style.transform = "translateY(0)";
          window.setTimeout(function () {
            list.style.height = "";
            list.style.overflow = "";
            list.style.transition = "";
          }, duration + 40);
        });

        var pagination = list.closest(".profile-card").querySelector(config.paginationSelector);
        if (pagination && result.payload.page_range) {
          var buttonsHtml = "";
          if (result.payload.has_previous) {
            buttonsHtml += '<button type="button" class="story-page-btn page-nav" ' + config.buttonAttr + ' data-page="' + (result.payload.page - 1) + '">Prev</button>';
          }
          result.payload.page_range.forEach(function (pageNum) {
            if (pageNum === "…") {
              buttonsHtml += '<span class="story-page-btn is-ellipsis" aria-hidden="true">…</span>';
              return;
            }
            buttonsHtml += '<button type="button" class="story-page-btn ' + (Number(pageNum) === Number(result.payload.page) ? 'is-active' : '') + '" ' + config.buttonAttr + ' data-page="' + pageNum + '" aria-label="Go to page ' + pageNum + '" ' + (Number(pageNum) === Number(result.payload.page) ? 'aria-current="page"' : '') + '>' + pageNum + '</button>';
          });
          if (result.payload.has_next) {
            buttonsHtml += '<button type="button" class="story-page-btn page-nav" ' + config.buttonAttr + ' data-page="' + (result.payload.page + 1) + '">Next</button>';
          }
          pagination.innerHTML = buttonsHtml;
        }
      })
      .catch(function () {
        list.classList.remove("is-animating");
        list.style.height = "";
        list.style.overflow = "";
        toast(config.netError, "error");
      });
  });

  function refreshCommentCount() {
    var countNode = document.querySelector("[data-comment-count]");
    if (!countNode) return;
    var total = document.querySelectorAll("[data-comment-item]").length;
    countNode.textContent = total + " comment" + (total === 1 ? "" : "s");
  }

  function ensureEmptyCommentPlaceholder() {
    var list = document.querySelector("[data-comment-list]");
    if (!list) return;
    if (!list.querySelector("[data-comment-item]")) {
      var emptyNode = list.querySelector("[data-empty-comment-state]");
      if (!emptyNode) {
        emptyNode = document.createElement("p");
        emptyNode.className = "empty-comments";
        emptyNode.setAttribute("data-empty-comment-state", "true");
        emptyNode.textContent = "No comments yet. Be the first to share your thoughts.";
        list.appendChild(emptyNode);
      }
    } else {
      var emptyNode = list.querySelector("[data-empty-comment-state]");
      if (emptyNode) emptyNode.remove();
    }
  }

  document.addEventListener("submit", function (event) {
    var storyForm = event.target.closest("[data-story-like-form]");
    if (!storyForm) return;
    event.preventDefault();

    var button = storyForm.querySelector("[data-story-like-btn]");
    if (!button || button.dataset.pending === "true") return;

    var countNode = document.querySelector("[data-story-like-count]");
    var oldValue = countNode ? Number(countNode.textContent.trim()) || 0 : 0;
    var previousText = button.innerHTML;
    button.dataset.pending = "true";
    button.disabled = true;
    button.classList.add("is-pending");
    if (countNode) countNode.textContent = oldValue + 1;

    fetch(storyForm.dataset.endpoint, {
      method: "POST",
      headers: { "X-CSRFToken": getCookie("csrftoken"), "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
    })
      .then(function (response) {
        return response.text().then(function (text) { return { ok: response.ok, status: response.status, text: text }; });
      })
      .then(function (result) {
        button.dataset.pending = "false";
        button.disabled = false;
        button.classList.remove("is-pending");
        if (!result.ok) {
          if (countNode) countNode.textContent = String(oldValue);
          button.innerHTML = previousText;
          toast(extractDetail(result.text, "Could not like this story."), "error");
          return;
        }
        var payload = result.text ? JSON.parse(result.text) : {};
        if (countNode) countNode.textContent = String(payload.likes || oldValue);
        toast(payload.detail || "Story liked.");
      })
      .catch(function () {
        button.dataset.pending = "false";
        button.disabled = false;
        button.classList.remove("is-pending");
        if (countNode) countNode.textContent = String(oldValue);
        button.innerHTML = previousText;
        toast("Connection issue. The like was not saved.", "error");
      });
  });

  /* ---------- author follow: one optimistic handler for the story page and
     the portfolio. Anonymous clicks get the server's 401 detail as a toast,
     so the button doubles as the "log in to follow" prompt. ---------- */
  function setFollowVisual(button, following) {
    button.dataset.following = following ? "true" : "false";
    button.setAttribute("aria-pressed", String(following));
    button.setAttribute("aria-label", following ? "Unfollow author" : "Follow author");
    button.title = following ? "Unfollow author" : "Follow author";
    var label = button.querySelector("[data-follow-label]");
    if (label) label.textContent = following ? "Following" : "Follow author";
  }

  /* The story page now shows a follow button both at the top (by the byline)
     and at the bottom, both for the same author -- keep every copy on the
     page in sync instead of only the one that was actually submitted. */
  function syncFollowButtons(following) {
    document.querySelectorAll("[data-follow-author-btn]").forEach(function (node) {
      setFollowVisual(node, following);
    });
  }

  function setFollowPending(pending) {
    document.querySelectorAll("[data-follow-author-btn]").forEach(function (node) {
      node.dataset.pending = pending ? "true" : "false";
      node.classList.toggle("is-pending", pending);
    });
  }

  document.addEventListener("submit", function (event) {
    var form = event.target.closest("[data-follow-author-form]");
    if (!form) return;
    event.preventDefault();

    var button = form.querySelector("[data-follow-author-btn]");
    if (!button || button.dataset.pending === "true") return;

    var wasFollowing = button.dataset.following === "true";
    var next = !wasFollowing;
    setFollowPending(true);
    syncFollowButtons(next);

    fetch(form.dataset.endpoint || form.action, {
      method: "POST",
      headers: { "X-CSRFToken": getCookie("csrftoken"), "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
    })
      .then(function (response) {
        return response.text().then(function (text) { return { ok: response.ok, status: response.status, text: text }; });
      })
      .then(function (result) {
        setFollowPending(false);

        if (!result.ok) {
          syncFollowButtons(wasFollowing);
          var message = extractDetail(result.text, "Could not update the follow.");
          if (result.status === 401) message = extractDetail(result.text, "You have to log in to follow this author.");
          toast(message, "error");
          return;
        }

        var payload = {};
        try { payload = JSON.parse(result.text || "{}") || {}; } catch (e) {}
        var following = typeof payload.following === "boolean" ? payload.following : next;
        syncFollowButtons(following);
        if (typeof payload.follower_count === "number") {
          document.querySelectorAll("[data-follow-count]").forEach(function (node) {
            node.textContent = String(payload.follower_count);
          });
          document.querySelectorAll("[data-follow-count-noun]").forEach(function (node) {
            node.textContent = payload.follower_count === 1 ? "follower" : "followers";
          });
        }
        toast(payload.detail || (following ? "Followed." : "Unfollowed."));
      })
      .catch(function () {
        setFollowPending(false);
        syncFollowButtons(wasFollowing);
        toast("Connection issue. The follow was not updated.", "error");
      });
  });

  document.addEventListener("submit", function (event) {
    var commentForm = event.target.closest("[data-comment-form]");
    if (!commentForm) return;
    event.preventDefault();

    var textarea = commentForm.querySelector("textarea[name='comment']");
    var value = textarea ? textarea.value.trim() : "";
    if (!value) {
      toast("Comment cannot be empty.", "error");
      if (textarea) textarea.focus();
      return;
    }

    var submitBtn = commentForm.querySelector("button[type='submit']");
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.dataset.originalText = submitBtn.textContent;
      submitBtn.textContent = "Posting...";
    }

    var formData = new FormData(commentForm);
    fetch("/story/" + document.querySelector("[data-story-like-form]").dataset.endpoint.split("/")[2] + "/comment/", {
      method: "POST",
      headers: { "X-CSRFToken": getCookie("csrftoken"), "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
      body: formData,
    })
      .then(function (response) {
        return response.text().then(function (text) { return { ok: response.ok, status: response.status, text: text }; });
      })
      .then(function (result) {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = submitBtn.dataset.originalText || "Post comment";
        }
        if (!result.ok) {
          var message = extractDetail(result.text, "Could not post comment.");
          toast(message, "error");
          return;
        }

        var payload = JSON.parse(result.text || "{}");
        var list = document.querySelector("[data-comment-list]");
        if (!list) return;
        var emptyNode = list.querySelector("[data-empty-comment-state]");
        if (emptyNode) emptyNode.remove();

        var article = document.createElement("article");
        article.className = "comment-item";
        article.setAttribute("data-comment-item", "true");
        article.setAttribute("data-comment-id", String(payload.comment_id || ""));
        article.innerHTML = '<div class="comment-header">' +
          '<div class="comment-author-block"><span class="comment-avatar">Y</span><strong>Me</strong></div>' +
          '<div class="comment-toolbar"><form method="post" action="/story/comment/' + (payload.comment_id || "") + '/like/" class="comment-like-form" data-comment-like-form data-endpoint="/story/comment/' + (payload.comment_id || "") + '/like/"><input type="hidden" name="csrfmiddlewaretoken" value="' + getCookie("csrftoken") + '"><button type="submit" class="comment-like-btn" data-comment-like-btn><span aria-hidden="true">❤</span> Like <span class="comment-like-count" data-comment-like-count>0</span></button></form></div></div>' +
          '<p>' + (payload.content || value) + '</p>' +
          '<small data-comment-like-summary>0 likes</small>';
        list.prepend(article);
        textarea.value = "";
        refreshCommentCount();
        ensureEmptyCommentPlaceholder();
        toast(payload.detail || "Comment posted.");
      })
      .catch(function () {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = submitBtn.dataset.originalText || "Post comment";
        }
        toast("Connection issue. Your comment was not posted.", "error");
      });
  });

  document.addEventListener("submit", function (event) {
    var likeForm = event.target.closest("[data-comment-like-form]");
    if (!likeForm) return;
    event.preventDefault();

    var button = likeForm.querySelector("[data-comment-like-btn]");
    if (!button || button.dataset.pending === "true") return;
    var countNode = likeForm.querySelector("[data-comment-like-count]");
    var oldValue = countNode ? Number(countNode.textContent.trim()) || 0 : 0;
    button.dataset.pending = "true";
    button.disabled = true;
    if (countNode) countNode.textContent = String(oldValue + 1);

    fetch(likeForm.dataset.endpoint, {
      method: "POST",
      headers: { "X-CSRFToken": getCookie("csrftoken"), "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
    })
      .then(function (response) {
        return response.text().then(function (text) { return { ok: response.ok, status: response.status, text: text }; });
      })
      .then(function (result) {
        button.dataset.pending = "false";
        button.disabled = false;
        if (!result.ok) {
          if (countNode) countNode.textContent = String(oldValue);
          toast(extractDetail(result.text, "Could not like the comment."), "error");
          return;
        }
        var payload = JSON.parse(result.text || "{}");
        if (countNode) countNode.textContent = String(payload.likes || oldValue);
        var summaryNode = likeForm.closest("[data-comment-item]")?.querySelector("[data-comment-like-summary]");
        if (summaryNode) summaryNode.textContent = (payload.likes || oldValue) + " like" + ((payload.likes || oldValue) === 1 ? "" : "s");
        toast(payload.detail || "Comment liked.");
      })
      .catch(function () {
        button.dataset.pending = "false";
        button.disabled = false;
        if (countNode) countNode.textContent = String(oldValue);
        toast("Connection issue. The comment like was not saved.", "error");
      });
  });

  document.addEventListener("submit", function (event) {
    var deleteForm = event.target.closest("[data-comment-delete-form]");
    if (!deleteForm) return;
    event.preventDefault();

    var item = deleteForm.closest("[data-comment-item]");
    if (!item) return;

    fetch(deleteForm.dataset.endpoint, {
      method: "POST",
      headers: { "X-CSRFToken": getCookie("csrftoken"), "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
    })
      .then(function (response) {
        return response.text().then(function (text) { return { ok: response.ok, status: response.status, text: text }; });
      })
      .then(function (result) {
        if (!result.ok) {
          toast(extractDetail(result.text, "Could not delete the comment."), "error");
          return;
        }
        item.remove();
        refreshCommentCount();
        ensureEmptyCommentPlaceholder();
        toast(extractDetail(result.text, "Comment deleted."));
      })
      .catch(function () {
        toast("Connection issue. The comment was not deleted.", "error");
      });
  });

  /* ---------- load more: page bookkeeping around htmx swap ---------- */
  var loadMoreOlder = document.getElementById("load-more-older");
  var loadMoreNewer = document.getElementById("load-more-newer");
  var currentPageLabel = document.getElementById("load-more-index");
  var currentPage = 1;

  function updateLoadMorePager() {
    if (currentPageLabel) {
      currentPageLabel.textContent = String(currentPage);
    }
    if (loadMoreNewer) {
      loadMoreNewer.classList.toggle("is-disabled", currentPage <= 1);
    }
  }

  if (loadMoreOlder && window.htmx) {
    loadMoreOlder.addEventListener("htmx:configRequest", function (event) {
      var nextPage = currentPage + 1;
      currentPage = nextPage;
      updateLoadMorePager();
      event.detail.parameters.page = String(nextPage);
    });
    loadMoreOlder.addEventListener("htmx:beforeRequest", function () {
      loadMoreOlder.classList.add("is-loading");
    });
    loadMoreOlder.addEventListener("htmx:afterSwap", function () {
      loadMoreOlder.classList.remove("is-loading");
      var grid = document.getElementById("story-grid");
      var metas = grid.querySelectorAll(".page-meta");
      var lastMeta = metas[metas.length - 1];
      if (!lastMeta) return;
      var hasMore = lastMeta.dataset.hasMore === "true";
      var nextPage = lastMeta.dataset.nextPage;
      lastMeta.remove();
      if (hasMore && nextPage) {
        loadMoreOlder.dataset.nextPage = nextPage;
      } else {
        loadMoreOlder.closest(".load-more-wrap").remove();
      }
    });
    loadMoreOlder.addEventListener("htmx:responseError", function (event) {
      loadMoreOlder.classList.remove("is-loading");
      var xhr = event.detail && event.detail.xhr;
      var responseText = xhr ? xhr.responseText : "";
      toast(extractDetail(responseText, "Could not load more stories."), "error");
    });
  }

  if (loadMoreNewer) {
    loadMoreNewer.addEventListener("click", function () {
      if (currentPage > 1) {
        currentPage -= 1;
        updateLoadMorePager();
      }
    });
  }

  updateLoadMorePager();
})();

/*  ADMIN AUTHORITY: STAFF RECORD WRITE CONTROLS
    Drives the tribute, role and account status controls on the staff detail
    page. Every control is also guarded server side in ADMIN.views, so a
    disabled button here is a convenience, not the security boundary. */
(function () {
  var shell = document.querySelector(".staff-record-shell");
  if (!shell) return;

  function getCookie(name) {
    var match = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
    return match ? decodeURIComponent(match.pop()) : "";
  }

  function say(node, message, isError) {
    if (!node) return;
    node.textContent = message;
    node.classList.toggle("is-error", !!isError);
  }

  function post(endpoint, payload) {
    var body = new URLSearchParams();
    Object.keys(payload).forEach(function (key) {
      body.append(key, payload[key]);
    });

    return fetch(endpoint, {
      method: "POST",
      headers: {
        "X-CSRFToken": getCookie("csrftoken"),
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded",
      },
      credentials: "same-origin",
      body: body.toString(),
    }).then(function (response) {
      return response.json().catch(function () {
        return {};
      }).then(function (data) {
        return { ok: response.ok, data: data };
      });
    });
  }

  /*  TRIBUTE  */
  var tributeSave = shell.querySelector("[data-tribute-save]");
  var tributeInput = shell.querySelector("[data-tribute-input]");
  var tributeFeedback = shell.querySelector("[data-tribute-feedback]");

  if (tributeSave && tributeInput) {
    tributeSave.addEventListener("click", function () {
      tributeSave.disabled = true;
      say(tributeFeedback, "Saving...", false);

      post(shell.dataset.tributeEndpoint, { tribute_bio: tributeInput.value })
        .then(function (result) {
          say(tributeFeedback, result.data.detail || (result.ok ? "Tribute saved." : "Could not save the tribute."), !result.ok);
        })
        .catch(function () {
          say(tributeFeedback, "Connection issue. The tribute was not saved.", true);
        })
        .finally(function () {
          tributeSave.disabled = false;
        });
    });
  }

  /*  SPECIALITY  */
  var specialitySave = shell.querySelector("[data-speciality-save]");
  var specialityInput = shell.querySelector("[data-speciality-input]");
  var specialityFeedback = shell.querySelector("[data-speciality-feedback]");

  if (specialitySave && specialityInput) {
    specialitySave.addEventListener("click", function () {
      specialitySave.disabled = true;
      say(specialityFeedback, "Saving...", false);

      post(shell.dataset.specialityEndpoint, { speciality: specialityInput.value })
        .then(function (result) {
          say(specialityFeedback, result.data.detail || (result.ok ? "Speciality saved." : "Could not save the speciality."), !result.ok);
          if (result.ok && typeof result.data.speciality_csv === "string") {
            specialityInput.value = result.data.speciality_csv;
          }
        })
        .catch(function () {
          say(specialityFeedback, "Connection issue. The speciality was not saved.", true);
        })
        .finally(function () {
          specialitySave.disabled = false;
        });
    });
  }

  /*  ROLE. Choices are server rendered from SERVICE_INTERNAL.config so nothing
      about the role list is hard coded in this file. */
  var roleSave = shell.querySelector("[data-role-save]");
  var roleInput = shell.querySelector("[data-role-input]");
  var roleFeedback = shell.querySelector("[data-role-feedback]");
  var promotionNode = shell.querySelector("[data-staff-last-promotion]");

  if (roleSave && roleInput) {
    roleSave.addEventListener("click", function () {
      roleSave.disabled = true;
      say(roleFeedback, "Updating...", false);

      post(shell.dataset.roleEndpoint, { role: roleInput.value })
        .then(function (result) {
          say(roleFeedback, result.data.detail || (result.ok ? "Role updated." : "Could not update the role."), !result.ok);
          if (result.ok && result.data.last_promotion && promotionNode) {
            promotionNode.textContent = result.data.last_promotion;
          }
        })
        .catch(function () {
          say(roleFeedback, "Connection issue. The role was not updated.", true);
        })
        .finally(function () {
          roleSave.disabled = false;
        });
    });
  }

  /*  GENDER. Admin only control; choices are server rendered from
      STAFF.models.GENDER_CHOICES so nothing is hard coded here. */
  var genderSave = shell.querySelector("[data-gender-save]");
  var genderInput = shell.querySelector("[data-gender-input]");
  var genderFeedback = shell.querySelector("[data-gender-feedback]");

  if (genderSave && genderInput) {
    genderSave.addEventListener("click", function () {
      genderSave.disabled = true;
      say(genderFeedback, "Updating...", false);

      post(shell.dataset.genderEndpoint, { gender: genderInput.value })
        .then(function (result) {
          say(genderFeedback, result.data.detail || (result.ok ? "Gender updated." : "Could not update the gender."), !result.ok);
          if (result.ok && typeof result.data.gender === "string") {
            genderInput.value = result.data.gender;
          }
        })
        .catch(function () {
          say(genderFeedback, "Connection issue. The gender was not updated.", true);
        })
        .finally(function () {
          genderSave.disabled = false;
        });
    });
  }

  /*  ACCOUNT STATUS. Suspending ends every session the account holds. */
  var statusToggle = shell.querySelector("[data-status-toggle]");
  var statusLabel = shell.querySelector("[data-status-label]");
  var statusFeedback = shell.querySelector("[data-status-feedback]");

  if (statusToggle && !statusToggle.disabled) {
    statusToggle.addEventListener("click", function () {
      var suspending = statusToggle.classList.contains("is-on");
      if (suspending && !window.confirm("Suspend this account? Every active session will end immediately.")) {
        return;
      }

      statusToggle.disabled = true;
      say(statusFeedback, "Working...", false);

      post(shell.dataset.statusEndpoint, {})
        .then(function (result) {
          if (result.ok) {
            statusToggle.classList.toggle("is-on", !!result.data.is_active);
            statusToggle.setAttribute("aria-pressed", result.data.is_active ? "true" : "false");
            if (statusLabel) {
              statusLabel.textContent = result.data.is_active ? "Active" : "Suspended, sessions ended";
            }
          }
          say(statusFeedback, result.data.detail || (result.ok ? "Status updated." : "Could not update the status."), !result.ok);
        })
        .catch(function () {
          say(statusFeedback, "Connection issue. The status was not changed.", true);
        })
        .finally(function () {
          statusToggle.disabled = false;
        });
    });
  }
})();

/*  PROFILE PAGE: OWN ROLE, LOG OUT ALL SESSIONS, ADD STAFF
    The profile page has no .staff-record-shell so the block above returns
    early there; these handlers live in their own scope. Every guard here is
    also enforced server side, in ADMIN.views and HOME.views. */
(function () {
  "use strict";

  function getCookie(name) {
    var match = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
    return match ? decodeURIComponent(match.pop()) : "";
  }

  function say(node, message, isError) {
    if (!node) return;
    node.textContent = message;
    node.classList.toggle("is-error", !!isError);
  }

  function post(endpoint, payload, formData) {
    var options = {
      method: "POST",
      headers: {
        "X-CSRFToken": getCookie("csrftoken"),
        "X-Requested-With": "XMLHttpRequest",
      },
      credentials: "same-origin",
    };
    if (formData) {
      options.body = formData;
    } else {
      options.headers["Content-Type"] = "application/x-www-form-urlencoded";
      var body = new URLSearchParams();
      Object.keys(payload || {}).forEach(function (key) {
        body.append(key, payload[key]);
      });
      options.body = body.toString();
    }

    return fetch(endpoint, options).then(function (response) {
      return response.json().catch(function () {
        return {};
      }).then(function (data) {
        return { ok: response.ok, data: data };
      });
    });
  }

  /*  OWN ROLE: an admin sets their own role from their own profile. */
  var ownRoleSave = document.querySelector("[data-own-role-save]");
  var ownRoleInput = document.querySelector("[data-own-role-input]");
  var ownRoleFeedback = document.querySelector("[data-own-role-feedback]");

  if (ownRoleSave && ownRoleInput) {
    ownRoleSave.addEventListener("click", function () {
      ownRoleSave.disabled = true;
      say(ownRoleFeedback, "Updating...", false);

      post(ownRoleSave.dataset.endpoint, { role: ownRoleInput.value })
        .then(function (result) {
          say(ownRoleFeedback, result.data.detail || (result.ok ? "Role updated." : "Could not update the role."), !result.ok);
        })
        .catch(function () {
          say(ownRoleFeedback, "Connection issue. The role was not updated.", true);
        })
        .finally(function () {
          ownRoleSave.disabled = false;
        });
    });
  }

  /*  LOG OUT ALL SESSIONS: destructive from the user's point of view, so it
      confirms first, and the successful response redirects to the login page
      because the session that clicked is gone with the rest. */
  var logoutAllBtn = document.querySelector("[data-logout-all-sessions]");
  var logoutAllFeedback = document.querySelector("[data-logout-all-feedback]");

  if (logoutAllBtn) {
    logoutAllBtn.addEventListener("click", function () {
      if (!window.confirm("End every session for this account? You will be signed out on this device too. Only Do This Is You Need To LogOut From Every Single Place You Are Logged In Else Use The Logout btn in the header")) {
        return;
      }

      logoutAllBtn.disabled = true;
      say(logoutAllFeedback, "Signing out...", false);

      post(logoutAllBtn.dataset.endpoint, {})
        .then(function (result) {
          if (result.ok) {
            window.location.href = (result.data && result.data.redirect_to) || "/auth/login/";
            return;
          }
          logoutAllBtn.disabled = false;
          say(logoutAllFeedback, result.data.detail || "Could not sign out the sessions.", true);
        })
        .catch(function () {
          logoutAllBtn.disabled = false;
          say(logoutAllFeedback, "Connection issue. Sessions were not ended.", true);
        });
    });
  }

  /*  ADD STAFF: full page form on its own route, submitted the same AJAX way
      as every other form here so the feedback pattern stays one pattern. */
  var createForm = document.querySelector("[data-staff-create-form]");
  var createFeedback = document.querySelector("[data-staff-create-feedback]");

  if (createForm) {
    createForm.addEventListener("submit", function (event) {
      event.preventDefault();

      var submitBtn = createForm.querySelector("[data-staff-create-btn]");
      if (submitBtn && submitBtn.dataset.pending === "true") return;

      if (submitBtn) {
        submitBtn.dataset.pending = "true";
        submitBtn.disabled = true;
        submitBtn.classList.add("is-pending");
      }
      say(createFeedback, "Creating Account, Please Wait.", false);

      fetch(createForm.dataset.endpoint || createForm.action, {
        method: "POST",
        headers: {
          "X-CSRFToken": getCookie("csrftoken"),
          "X-Requested-With": "XMLHttpRequest",
        },
        credentials: "same-origin",
        body: new FormData(createForm),
      })
        .then(function (response) {
          return response.json().catch(function () {
            return {};
          }).then(function (data) {
            return { ok: response.ok, data: data };
          });
        })
        .then(function (result) {
          if (result.ok && result.data.redirect_to) {
            window.location.href = result.data.redirect_to;
            return;
          }
          if (submitBtn) {
            submitBtn.dataset.pending = "false";
            submitBtn.disabled = false;
            submitBtn.classList.remove("is-pending");
          }
          say(createFeedback, result.data.detail || (result.ok ? "Staff account created." : "Could not create the staff account."), !result.ok);
        })
        .catch(function () {
          if (submitBtn) {
            submitBtn.dataset.pending = "false";
            submitBtn.disabled = false;
            submitBtn.classList.remove("is-pending");
          }
          say(createFeedback, "Connection issue. The staff account was not created.", true);
        });
    });
  }
  /* ---------- newsletter popup: bottom-sheet, scroll-triggered, dismissible ---------- */
  (function () {
    var popup = document.querySelector("[data-newsletter-popup]");
    if (!popup) return; // not rendered for this page/user (see newsletter_popup.html)

    var STORAGE_KEY = "abureport-newsletter-popup-state";
    var DISMISS_MS = 3 * 24 * 60 * 60 * 1000; // re-offer 3 days after a manual dismiss
    var FALLBACK_DELAY_MS = 8000; // used only when the page can't scroll at all

    function readState() {
      try { return localStorage.getItem(STORAGE_KEY); } catch (e) { return null; }
    }
    function writeState(value) {
      try { localStorage.setItem(STORAGE_KEY, value); } catch (e) { /* storage unavailable, ignore */ }
    }

    var state = readState();
    if (state === "subscribed") return; // already subscribed, never ask again
    if (state && state !== "subscribed" && Number(state) > Date.now()) return; // still inside a dismiss cooldown

    var endpoint = popup.dataset.endpoint;
    var threshold = parseFloat(popup.dataset.scrollThreshold);
    if (isNaN(threshold) || threshold <= 0 || threshold > 1) threshold = 0.4;
    var targetSelector = popup.dataset.scrollTarget;
    var targetEl = targetSelector ? document.querySelector(targetSelector) : null;

    var form = popup.querySelector("[data-newsletter-popup-form]");
    var emailInput = document.getElementById("newsletter-popup-email");
    var statusEl = document.getElementById("newsletter-popup-status");
    var submitBtn = form ? form.querySelector(".newsletter-popup-submit") : null;
    var shown = false;

    function showPopup() {
      if (shown) return;
      shown = true;
      popup.classList.add("is-visible");
      popup.setAttribute("aria-hidden", "false");
      window.removeEventListener("scroll", onScroll);
    }

    function hidePopup(persistDismiss) {
      popup.classList.remove("is-visible");
      popup.setAttribute("aria-hidden", "true");
      if (persistDismiss) writeState(String(Date.now() + DISMISS_MS));
    }

    function scrollProgress() {
      if (targetEl) {
        var rect = targetEl.getBoundingClientRect();
        var elTop = rect.top + window.scrollY;
        var elHeight = targetEl.offsetHeight || 1;
        return (window.scrollY + window.innerHeight - elTop) / elHeight;
      }
      var doc = document.documentElement;
      var maxScroll = doc.scrollHeight - window.innerHeight;
      if (maxScroll <= 0) return -1; // page too short to scroll, caller falls back to a timer
      return window.scrollY / maxScroll;
    }

    var scrollTicking = false;
    function onScroll() {
      if (scrollTicking) return;
      scrollTicking = true;
      window.requestAnimationFrame(function () {
        scrollTicking = false;
        var progress = scrollProgress();
        if (progress >= threshold) showPopup();
      });
    }

    if (scrollProgress() === -1) {
      window.setTimeout(showPopup, FALLBACK_DELAY_MS);
    } else {
      window.addEventListener("scroll", onScroll, { passive: true });
      onScroll(); // covers a visitor who is already past the threshold on load
    }

    popup.querySelectorAll("[data-newsletter-popup-close]").forEach(function (btn) {
      btn.addEventListener("click", function () { hidePopup(true); });
    });

    if (emailInput) {
      emailInput.addEventListener("input", function () {
        emailInput.classList.remove("is-invalid");
      });
    }

    if (form) {
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        var email = emailInput.value.trim();
        var validEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);

        if (!validEmail) {
          emailInput.classList.add("is-invalid");
          statusEl.textContent = "Enter a valid email address.";
          statusEl.className = "newsletter-popup-status is-error";
          return;
        }

        var body = new FormData(form);
        submitBtn.disabled = true;
        statusEl.textContent = "";
        statusEl.className = "newsletter-popup-status";

        fetch(endpoint, {
          method: "POST",
          headers: { "X-CSRFToken": getCookie("csrftoken"), "X-Requested-With": "XMLHttpRequest" },
          credentials: "same-origin",
          body: body,
        })
          .then(function (response) {
            return response.text().then(function (text) { return { ok: response.ok, text: text }; });
          })
          .then(function (result) {
            submitBtn.disabled = false;
            if (result.ok) {
              statusEl.textContent = extractDetail(result.text, "Subscribed. Check your inbox.");
              statusEl.className = "newsletter-popup-status is-ok";
              writeState("subscribed");
              window.setTimeout(function () { hidePopup(false); }, 1800);
            } else {
              emailInput.classList.add("is-invalid");
              statusEl.textContent = extractDetail(result.text, "Something went wrong.");
              statusEl.className = "newsletter-popup-status is-error";
            }
          })
          .catch(function () {
            submitBtn.disabled = false;
            statusEl.textContent = "Network Error. Please try again.";
            statusEl.className = "newsletter-popup-status is-error";
          });
      });
    }
  })();
})();
