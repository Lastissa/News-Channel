/* Ads desk: filters, the small message after a button, and the plan rule on
   the subdomain box. Buttons on the cards are handled by htmx. */
(function () {
  var cards = document.getElementById("ads-desk-cards");
  var toast = document.getElementById("ads-desk-toast");
  var filter = "all";
  var toastTimer = null;

  function applyFilter() {
    if (!cards) return;
    var counts = { all: 0, live: 0, scheduled: 0, paused: 0, expired: 0 };
    var shown = 0;
    cards.querySelectorAll(".ads-desk-ref").forEach(function (card) {
      var status = card.getAttribute("data-status");
      counts.all += 1;
      if (counts[status] !== undefined) counts[status] += 1;
      var show = filter === "all" || filter === status;
      card.hidden = !show;
      if (show) shown += 1;
    });
    Object.keys(counts).forEach(function (key) {
      var el = document.querySelector('[data-count="' + key + '"]');
      if (el) el.textContent = counts[key];
    });
    var none = document.getElementById("ads-desk-none");
    if (none) none.hidden = shown !== 0;
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-filter]");
    if (button) {
      filter = button.getAttribute("data-filter");
      document.querySelectorAll("[data-filter]").forEach(function (b) {
        b.classList.toggle("is-active", b === button);
      });
      applyFilter();
      return;
    }
    if (event.target.closest("[data-open-issue]")) {
      var box = document.getElementById("issue-reference");
      if (box) box.open = true;
    }
  });

  //  A card was swapped (pause, renew...): its status may have changed.
  document.body.addEventListener("htmx:afterSwap", applyFilter);

  document.body.addEventListener("adsToast", function (event) {
    if (!toast) return;
    var info = event.detail || {};
    toast.textContent = info.text || "";
    toast.className = "ads-desk-toast" + (info.ok === false ? " is-error" : "");
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toast.hidden = true; }, 4000);
  });

  //  Regular has no subdomain: switch the box off so nobody types one. Pro and
  //  Advance must have one unless a Public page URL opens an external link.
  //  The server applies the same rule; this is just the visible guard.
  function syncPlan(select) {
    var form = select.closest("form");
    var input = form && form.querySelector("[data-subdomain-input]");
    var hint = form && form.querySelector("[data-subdomain-hint]");
    var publicInput = form && form.querySelector("[data-public-url-input]");
    if (!input) return;
    var off = select.value === "regular";
    var external = !!(publicInput && publicInput.value.trim());
    if (!external && select.value !== "regular") {
      var chosen = form && form.querySelector('select[name="advert_id"]');
      var option = chosen && chosen.options[chosen.selectedIndex];
      external = !!(option && option.getAttribute("data-has-url") === "true");
    }
    input.disabled = off;
    if (off) input.value = "";
    input.required = !off && !external;
    if (hint) {
      hint.textContent = off
        ? "Not included in the Regular plan."
        : (external
            ? "Optional because a Public page URL is set. Otherwise each paid advert needs its own subdomain."
            : "Required for Pro and Advance. Add a Public page URL instead to open an external link.");
    }
  }
  document.addEventListener("change", function (event) {
    if (event.target.matches("[data-plan-select]")) syncPlan(event.target);
    if (event.target.matches('select[name="advert_id"]')) {
      var form = event.target.closest("form");
      var select = form && form.querySelector("[data-plan-select]");
      if (select) syncPlan(select);
    }
  });
  document.querySelectorAll("[data-plan-select]").forEach(syncPlan);

  //  Keep the subdomain box to what a web address allows: lowercase letters,
  //  numbers and hyphens (a space or underscore turns into a hyphen).
  document.addEventListener("input", function (event) {
    var box = event.target.closest && event.target.closest("[data-subdomain-input]");
    if (box) {
      var cleaned = box.value.toLowerCase().replace(/[\s_]+/g, "-").replace(/[^a-z0-9-]/g, "").replace(/^-+/, "").slice(0, 63);
      if (cleaned !== box.value) box.value = cleaned;
      return;
    }
    if (event.target.matches && event.target.matches("[data-public-url-input]")) {
      var form = event.target.closest("form");
      var select = form && form.querySelector("[data-plan-select]");
      if (select) syncPlan(select);
    }
  });

  applyFilter();
})();

/* Reference storage drawer: Archive-style upload, preview, progress, cancel,
   split list/editor, and media studio. */
(function () {
  var storageModal = document.querySelector("[data-storage-modal]");
  var deleteModal = document.querySelector("[data-ref-delete-modal]");
  var analyticsModal = document.querySelector("[data-analytics-modal]");
  var activeXhr = null;

  function open(modal) {
    if (!modal) return;
    modal.hidden = false;
    modal.classList.add("is-open");
    document.body.classList.add("has-ads-modal");
  }

  function close(modal) {
    if (!modal || modal.hidden) return;
    modal.hidden = true;
    modal.classList.remove("is-open");
    if (!document.querySelector(".ads-modal.is-open")) document.body.classList.remove("has-ads-modal");
  }

  function toast(text, ok) {
    document.body.dispatchEvent(new CustomEvent("adsToast", { detail: { text: text, ok: ok !== false } }));
  }

  function fileKind(file) {
    var name = (file.name || "").toLowerCase();
    if (file.type.indexOf("image/") === 0) return "image";
    if (file.type.indexOf("video/") === 0) return "video";
    if (/\.(html?|css|js|mjs|json|xml|txt|md|csv|svg)$/.test(name)) return "text";
    return "file";
  }

  function humanSize(bytes) {
    if (!bytes) return "0 B";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(2) + " MB";
  }

  function showPreview(form, file) {
    var box = form.querySelector("[data-storage-preview]");
    var art = form.querySelector("[data-storage-preview-art]");
    var name = form.querySelector("[data-storage-preview-name]");
    var meta = form.querySelector("[data-storage-preview-meta]");
    if (!box || !art) return;
    art.innerHTML = "";
    var kind = fileKind(file);

    if (kind === "image" || kind === "video") {
      var url = URL.createObjectURL(file);
      var element = document.createElement(kind === "image" ? "img" : "video");
      element.src = url;
      if (kind === "video") {
        element.muted = true;
        element.controls = false;
      }
      art.appendChild(element);
      box._previewUrl = url;
    } else {
      var icon = document.createElement("span");
      icon.className = "ads-storage-icon";
      icon.textContent = kind === "text" ? "T" : "F";
      art.appendChild(icon);
    }

    if (name) name.textContent = file.name;
    if (meta) meta.textContent = humanSize(file.size) + " Â· " + (file.type || kind);
    box.hidden = false;
  }

  function clearPreview(form) {
    var box = form.querySelector("[data-storage-preview]");
    if (!box) return;
    if (box._previewUrl) URL.revokeObjectURL(box._previewUrl);
    box._previewUrl = null;
    box.hidden = true;
    var input = form.querySelector("[data-storage-input]");
    if (input) input.value = "";
  }

  function setProgress(form, loaded, total, finished) {
    var wrap = form.querySelector("[data-storage-progress]");
    var fill = form.querySelector("[data-storage-progress-fill]");
    var text = form.querySelector("[data-storage-progress-text]");
    if (!wrap || !fill) return;
    wrap.hidden = false;
    var pct = total ? Math.min(100, Math.round((loaded / total) * 100)) : 0;
    fill.style.width = (finished ? 100 : pct) + "%";
    if (text) text.textContent = finished ? "Finishingâ€¦" : pct + "% Â· " + humanSize(loaded) + " of " + humanSize(total);
  }

  function refreshWorkspace() {
    var current = document.querySelector(".ads-storage-editor-shell, .ads-storage-list-pane");
    if (!current || !window.htmx) return;
    var form = document.querySelector("[data-storage-upload-form]");
    var url = form ? form.getAttribute("data-endpoint") : window.location.pathname;
    window.htmx.ajax("GET", url, { target: "#advert-storage-workspace", swap: "innerHTML" });
  }

  function upload(form) {
    var input = form.querySelector("[data-storage-input]");
    var file = input && input.files && input.files[0];
    var submit = form.querySelector("[data-storage-submit]");
    var cancel = form.querySelector("[data-storage-cancel]");
    if (!file) return toast("Choose a file first.", false);

    var maxBytes = Number(form.getAttribute("data-max-bytes") || 5) * 1024 * 1024;
    if (file.size > maxBytes) {
      return toast("That file is larger than the " + Math.round(maxBytes / (1024 * 1024)) + "MB limit.", false);
    }

    var data = new FormData(form);
    var xhr = new XMLHttpRequest();
    activeXhr = xhr;
    xhr.open("POST", form.getAttribute("data-endpoint"), true);
    xhr.setRequestHeader("X-CSRFToken", form.querySelector("[name=csrfmiddlewaretoken]").value);
    xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");

    if (submit) { submit.disabled = true; submit.textContent = "Uploadingâ€¦"; }
    if (cancel) cancel.hidden = false;
    setProgress(form, 0, file.size, false);

    xhr.upload.addEventListener("progress", function (event) {
      setProgress(form, event.loaded, event.total || file.size, false);
    });

    xhr.addEventListener("load", function () {
      activeXhr = null;
      setProgress(form, file.size, file.size, true);
      if (submit) { submit.disabled = false; submit.textContent = "Upload"; }
      if (cancel) cancel.hidden = true;
      if (xhr.status >= 200 && xhr.status < 400) {
        clearPreview(form);
        toast("File uploaded.");
        refreshWorkspace();
      } else {
        toast("Upload failed. Please try again.", false);
      }
    });

    xhr.addEventListener("error", function () {
      activeXhr = null;
      if (submit) { submit.disabled = false; submit.textContent = "Upload"; }
      if (cancel) cancel.hidden = true;
      toast("Upload failed. Please try again.", false);
    });

    xhr.addEventListener("abort", function () {
      activeXhr = null;
      if (submit) { submit.disabled = false; submit.textContent = "Upload"; }
      if (cancel) cancel.hidden = true;
      toast("Upload cancelled.", false);
    });

    xhr.send(data);
  }

  function setReplacement(form, blob, name) {
    var input = form.querySelector("[data-replacement-input]");
    if (!input) return;
    var file = new File([blob], name, { type: blob.type });
    var transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
  }

  function applyImageStudio(form) {
    var root = form.closest("[data-storage-editor]");
    var media = root && root.querySelector("[data-studio-media]");
    var canvas = root && root.querySelector("[data-studio-canvas]");
    if (!media || !canvas || media.tagName !== "IMG") return toast("Image is not ready yet.", false);
    var x = Number(root.querySelector("[data-crop-x]").value) || 0;
    var y = Number(root.querySelector("[data-crop-y]").value) || 0;
    var w = Number(root.querySelector("[data-crop-w]").value) || media.naturalWidth;
    var h = Number(root.querySelector("[data-crop-h]").value) || media.naturalHeight;
    var outW = Number(root.querySelector("[data-output-w]").value) || w;
    var quality = Number(root.querySelector("[data-quality]").value) || 0.8;
    var outH = Math.max(1, Math.round((h / w) * outW));
    canvas.width = outW;
    canvas.height = outH;
    var ctx = canvas.getContext("2d");
    ctx.drawImage(media, x, y, w, h, 0, 0, outW, outH);
    canvas.toBlob(function (blob) {
      if (!blob) return toast("Could not process this image.", false);
      var original = root.querySelector(".ads-storage-detail-head h4").textContent;
      setReplacement(form, blob, original);
      toast("Crop and resize ready. Save changes to publish it.");
    }, media.src.indexOf("png") >= 0 ? "image/png" : "image/jpeg", quality);
  }

  function applyVideoTrim(form) {
    var root = form.closest("[data-storage-editor]");
    var media = root && root.querySelector("[data-studio-media]");
    if (!media || media.tagName !== "VIDEO" || !media.captureStream || !window.MediaRecorder) {
      return toast("Video trimming is not supported in this browser. You can still replace the file.", false);
    }
    var start = Number(root.querySelector("[data-trim-start]").value) || 0;
    var end = Number(root.querySelector("[data-trim-end]").value) || 0;
    if (!end || end <= start) return toast("Add an end time greater than the start.", false);

    media.currentTime = start;
    media.play();
    var stream = media.captureStream();
    var chunks = [];
    var recorder = new MediaRecorder(stream);
    recorder.ondataavailable = function (event) { if (event.data.size) chunks.push(event.data); };
    recorder.onstop = function () {
      var blob = new Blob(chunks, { type: chunks[0] ? chunks[0].type : "video/webm" });
      var original = root.querySelector(".ads-storage-detail-head h4").textContent;
      setReplacement(form, blob, original);
      toast("Trim ready. Save changes to publish it.");
    };
    recorder.start();
    var watch = window.setInterval(function () {
      if (media.currentTime >= end || media.ended) {
        window.clearInterval(watch);
        media.pause();
        recorder.stop();
      }
    }, 100);
  }

  function makeVideoThumb(form) {
    var root = form.closest("[data-storage-editor]");
    var media = root && root.querySelector("[data-studio-media]");
    var canvas = root && root.querySelector("[data-studio-canvas]");
    if (!media || media.tagName !== "VIDEO" || !canvas) return;
    canvas.width = media.videoWidth || 640;
    canvas.height = media.videoHeight || 360;
    canvas.getContext("2d").drawImage(media, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(function (blob) {
      if (!blob) return;
      var original = root.querySelector(".ads-storage-detail-head h4").textContent;
      var name = original.replace(/\.[^.]+$/, "") + "-thumb.png";
      setReplacement(form, blob, name);
      toast("Thumbnail ready. Save changes to publish it.");
    }, "image/png");
  }

  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-open-storage]")) open(storageModal);
    if (event.target.closest("[data-open-analytics]")) open(analyticsModal);
    if (event.target.closest("[data-open-ref-delete]")) open(deleteModal);

    var closeButton = event.target.closest("[data-modal-close]");
    if (closeButton) { close(closeButton.closest(".ads-modal")); return; }

    var clear = event.target.closest("[data-storage-clear]");
    if (clear) {
      var toolForm = clear.closest("form");
      if (toolForm) {
        toolForm.querySelector("[data-storage-q]").value = "";
        toolForm.querySelector("[data-storage-kind]").value = "all";
        toolForm.querySelector("[data-storage-date]").value = "";
        if (window.htmx) window.htmx.trigger(toolForm, "submit");
      }
      return;
    }

    var previewClear = event.target.closest("[data-storage-preview-clear]");
    if (previewClear) { clearPreview(previewClear.closest("form")); return; }

    var cancel = event.target.closest("[data-storage-cancel]");
    if (cancel) { if (activeXhr) activeXhr.abort(); return; }

    var imageApply = event.target.closest("[data-image-apply]");
    if (imageApply) { applyImageStudio(imageApply.closest("form")); return; }

    var videoApply = event.target.closest("[data-video-apply]");
    if (videoApply) { applyVideoTrim(videoApply.closest("form")); return; }

    var videoThumb = event.target.closest("[data-video-thumb]");
    if (videoThumb) { makeVideoThumb(videoThumb.closest("form")); return; }

    if (event.target === storageModal) close(storageModal);
    if (event.target === analyticsModal) close(analyticsModal);
    if (event.target === deleteModal) close(deleteModal);
  });

  document.addEventListener("change", function (event) {
    if (event.target.matches("[data-storage-input]")) {
      showPreview(event.target.closest("form"), event.target.files[0]);
    }
  });

  document.addEventListener("dragover", function (event) {
    var zone = event.target.closest && event.target.closest("[data-storage-drop]");
    if (zone) { event.preventDefault(); zone.classList.add("is-over"); }
  });

  document.addEventListener("dragleave", function (event) {
    var zone = event.target.closest && event.target.closest("[data-storage-drop]");
    if (zone) zone.classList.remove("is-over");
  });

  document.addEventListener("drop", function (event) {
    var zone = event.target.closest && event.target.closest("[data-storage-drop]");
    if (!zone) return;
    event.preventDefault();
    zone.classList.remove("is-over");
    var file = event.dataTransfer.files && event.dataTransfer.files[0];
    if (!file) return;
    var form = zone.closest("form");
    var input = form.querySelector("[data-storage-input]");
    var transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    showPreview(form, file);
  });

  document.addEventListener("submit", function (event) {
    var form = event.target.closest("[data-storage-upload-form]");
    if (!form) return;
    event.preventDefault();
    upload(form);
  });

  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.target && event.target.id === "advert-storage-workspace") open(storageModal);
    if (event.target && event.target.id === "advert-ref-delete-body") open(deleteModal);
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    close(storageModal);
    close(deleteModal);
    close(analyticsModal);
  });
})();