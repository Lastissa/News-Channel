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
/* ---------- ALSO IN THIS FILE (page upgrade) ----------
   - icon search that expands in place, "/" focuses it, Escape closes it
   - All / Images / Files tabs (plain links without JS, htmx swap with it)
   - the address bar follows the grid (?descr= &kind= &page=) so a refresh or a
     shared link lands on the same view
   - after a page change the view scrolls back to the top of the grid
   - image viewer (click a picture; arrow keys, swipe, Escape)
   - popups: focus moves in, Tab is kept inside, focus returns on close,
     the page behind does not scroll, and they animate out */
(function () {
  "use strict";

  var shell = document.querySelector(".archive-shell");
  if (!shell) return;

  var MODAL_TIMEOUT_MS = 5000;

  var mainContent = document.getElementById("main-content");
  var overlayHost = document.querySelector("[data-archive-overlay]");
  var galleryEndpoint = shell.dataset.galleryEndpoint;
  var csrfToken = shell.dataset.csrf || "";
  var searchForm = document.querySelector("[data-archive-search-form]");
  var searchInput = document.querySelector("[data-archive-search]");
  var searchToggle = document.querySelector("[data-archive-search-toggle]");
  var kindInput = document.querySelector("[data-archive-kind]");
  var tabs = document.querySelectorAll("[data-archive-kind-btn]");
  var lastOpener = null;

  function getCookie(name) {
    var match = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
    return match ? decodeURIComponent(match.pop()) : "";
  }

  function csrf() {
    return csrfToken || getCookie("csrftoken");
  }

  var FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

  /* keeps Tab / Shift+Tab inside an open dialog */
  function trapTab(container, event) {
    if (event.key !== "Tab" || !container) return;
    var nodes = Array.prototype.filter.call(container.querySelectorAll(FOCUSABLE), function (node) {
      return node.offsetParent !== null || node === document.activeElement;
    });
    if (!nodes.length) return;
    var first = nodes[0];
    var last = nodes[nodes.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }

  function lockScroll(locked) {
    document.documentElement.classList.toggle("archive-locked", locked);
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
    if (typeof window.AbuToast === "function") {
      window.AbuToast(message, tone);
      return;
    }
    if (!toastHost) {
      toastHost = document.createElement("div");
      toastHost.className = "site-toast-stack";
      toastHost.setAttribute("aria-live", "polite");
      document.body.appendChild(toastHost);
    }
    var node = document.createElement("div");
    node.className = "site-toast" + (tone === "error" ? " site-toast--error" : "");
    node.setAttribute("role", tone === "error" ? "alert" : "status");
    node.textContent = message;
    node.style.display = "block";
    node.style.opacity = "0";
    node.style.transform = "translateY(-6px)";
    toastHost.appendChild(node);
    requestAnimationFrame(function () {
      node.style.opacity = "1";
      node.style.transform = "translateY(0)";
    });
    window.setTimeout(function () {
      node.style.opacity = "0";
      node.style.transform = "translateY(-6px)";
      window.setTimeout(function () { node.remove(); }, 200);
    }, 5000);
  }

  /* loads one page of the grid for the current search + type filter */
  function loadGrid(page) {
    var values = {
      page: page || 1,
      descr: searchInput ? searchInput.value : "",
      kind: kindInput ? kindInput.value : "",
    };
    if (window.htmx && galleryEndpoint) {
      window.htmx.ajax("POST", galleryEndpoint, {
        target: "#archive-grid-shell",
        swap: "innerHTML",
        values: values,
        headers: { "X-CSRFToken": csrf() },
      });
    } else {
      var query = new URLSearchParams();
      if (values.descr) query.set("descr", values.descr);
      if (values.kind) query.set("kind", values.kind);
      if (values.page > 1) query.set("page", values.page);
      window.location.href = galleryEndpoint + (query.toString() ? "?" + query.toString() : "");
    }
  }

  /* after an upload/edit/delete: back to page 1, keeping the search and type filter */
  function refreshGridToPage1() {
    loadGrid(1);
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
    var activeXhr = null;
    var scrollAfterSwap = false;

    document.body.addEventListener("htmx:beforeRequest", function (event) {
      if (!event.detail || event.detail.target !== gridShell) return;

      /* a newer request replaces one still in flight, so a slow old answer can never land on top of a newer one */
      if (activeXhr && activeXhr !== event.detail.xhr) { try { activeXhr.abort(); } catch (err) { /* settled */ } }
      activeXhr = event.detail.xhr || null;

      /* typing in the search only dims the cards; everything else (page buttons, tabs, refreshes) shows the skeleton */
      if (event.target === searchInput) {
        gridShell.classList.add("is-searching");
        return;
      }

      scrollAfterSwap = !!(event.target.closest && event.target.closest("[data-archive-page-btn]"));
      if (!gridShell.classList.contains("is-paginating")) {
        pendingGridHTML = gridShell.innerHTML;
        gridShell.style.height = gridShell.offsetHeight + "px";
        gridShell.style.overflow = "hidden";
        gridShell.classList.add("is-paginating");
      }
      var pageSize = Math.min(parseInt(gridShell.dataset.archivePageSize, 10) || 6, 6);
      gridShell.innerHTML = buildGridSkeleton(pageSize);
    });

    gridShell.addEventListener("htmx:afterSwap", function () {
      activeXhr = null;
      gridShell.classList.remove("is-searching");
      syncFromGrid();
      sweepLoadedImages();
      if (!gridShell.classList.contains("is-paginating")) return;
      gridShell.classList.remove("is-paginating");
      pendingGridHTML = null;
      settleGridHeight();
      if (scrollAfterSwap) {
        scrollAfterSwap = false;
        var top = gridShell.getBoundingClientRect().top + window.pageYOffset - 140;
        if (top < window.pageYOffset) window.scrollTo({ top: Math.max(top, 0), behavior: "smooth" });
      }
    });

    function recoverFailedPage(event) {
      if (!event.detail || event.detail.target !== gridShell) return;
      activeXhr = null;
      gridShell.classList.remove("is-searching");
      if (!gridShell.classList.contains("is-paginating")) {
        toast(extractDetail(event.detail.xhr ? event.detail.xhr.responseText : "", "Could not load that page."), "error");
        return;
      }
      gridShell.classList.remove("is-paginating");
      if (pendingGridHTML !== null) gridShell.innerHTML = pendingGridHTML;
      pendingGridHTML = null;
      gridShell.style.transition = "";
      gridShell.style.height = "";
      gridShell.style.overflow = "";
      var responseText = event.detail && event.detail.xhr ? event.detail.xhr.responseText : "";
      toast(extractDetail(responseText, "Could not load that page."), "error");
    }
    document.body.addEventListener("htmx:responseError", recoverFailedPage);
    document.body.addEventListener("htmx:sendError", recoverFailedPage);
    document.body.addEventListener("htmx:timeout", recoverFailedPage);
  }

  /* pictures that finished loading before their onload handler could run (cache hits) */
  function sweepLoadedImages() {
    var imgs = document.querySelectorAll(".archive-card-media img:not(.is-loaded)");
    for (var i = 0; i < imgs.length; i++) {
      if (imgs[i].complete && imgs[i].naturalWidth > 0) imgs[i].classList.add("is-loaded");
    }
  }
  sweepLoadedImages();

  /* after every swap: tabs, hidden type field and address bar follow what the server actually rendered */
  function syncFromGrid() {
    var meta = gridShell && gridShell.querySelector("[data-archive-meta]");
    if (!meta) return;
    var kind = meta.dataset.kind || "";
    var page = parseInt(meta.dataset.page, 10) || 1;
    var descr = meta.dataset.descr || "";
    if (kindInput) kindInput.value = kind;
    for (var i = 0; i < tabs.length; i++) {
      var active = (tabs[i].dataset.archiveKindBtn || "") === kind;
      tabs[i].classList.toggle("is-active", active);
      if (active) tabs[i].setAttribute("aria-current", "true"); else tabs[i].removeAttribute("aria-current");
      tabs[i].setAttribute("href", tabHref(tabs[i].dataset.archiveKindBtn || "", descr));
    }
    var query = new URLSearchParams();
    if (descr) query.set("descr", descr);
    if (kind) query.set("kind", kind);
    if (page > 1) query.set("page", page);
    var qs = query.toString();
    try { window.history.replaceState(null, "", window.location.pathname + (qs ? "?" + qs : "")); } catch (err) { /* ignore */ }
  }

  function tabHref(kind, descr) {
    var query = new URLSearchParams();
    if (kind) query.set("kind", kind);
    if (descr) query.set("descr", descr);
    var qs = query.toString();
    return galleryEndpoint + (qs ? "?" + qs : "");
  }

  /* ---------- type tabs ---------- */
  for (var t = 0; t < tabs.length; t++) {
    tabs[t].addEventListener("click", function (event) {
      if (!window.htmx || event.metaKey || event.ctrlKey || event.shiftKey || event.button) return;
      event.preventDefault();
      var kind = this.dataset.archiveKindBtn || "";
      if (kindInput && kindInput.value === kind) return;
      if (kindInput) kindInput.value = kind;
      loadGrid(1);
    });
  }

  /* ---------- icon search ---------- */
  function setSearchOpen(open, focusInput) {
    if (!searchForm) return;
    searchForm.classList.toggle("is-open", open);
    if (searchToggle) searchToggle.setAttribute("aria-expanded", open ? "true" : "false");
    if (open && focusInput && searchInput) searchInput.focus();
  }

  if (searchForm && searchInput) {
    searchForm.addEventListener("submit", function (event) {
      if (!window.htmx) return;               /* no htmx: plain GET submit still works */
      event.preventDefault();
      var isOpen = searchForm.classList.contains("is-open");
      if (!isOpen) { setSearchOpen(true, true); return; }
      if (!searchInput.value.trim()) { setSearchOpen(false); return; }
      loadGrid(1);
    });

    searchInput.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      if (searchInput.value) {
        searchInput.value = "";
        loadGrid(1);
      }
      setSearchOpen(false);
      if (searchToggle) searchToggle.focus();
    });

    /* "/" jumps to the search, like most sites with a library of items */
    document.addEventListener("keydown", function (event) {
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
      var el = document.activeElement;
      var tag = el && el.tagName ? el.tagName.toLowerCase() : "";
      if (tag === "input" || tag === "textarea" || tag === "select" || (el && el.isContentEditable)) return;
      if (document.querySelector("[data-archive-modal]") || (viewer && !viewer.hidden)) return;
      event.preventDefault();
      setSearchOpen(true, true);
    });
  }

  /* "Clear search" (summary line and empty state) */
  document.addEventListener("click", function (event) {
    if (!event.target.closest("[data-archive-clear-search]")) return;
    if (searchInput) searchInput.value = "";
    loadGrid(1);
    setSearchOpen(false);
  });

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
    if (!overlayHost) return;
    var layer = overlayHost.querySelector("[data-archive-modal]");
    var opener = lastOpener;
    lastOpener = null;
    function finish() {
      overlayHost.innerHTML = "";
      lockScroll(false);
      if (opener && document.body.contains(opener)) opener.focus();
    }
    if (!layer) { finish(); return; }
    layer.classList.add("is-closing");
    window.setTimeout(finish, 170);
  }

  /* a popup just landed in the overlay slot: lock the page behind it and move focus inside */
  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (!overlayHost || event.detail.target !== overlayHost) return;
    if (!overlayHost.querySelector("[data-archive-modal]")) return;
    lockScroll(true);
    var first = overlayHost.querySelector('input:not([type="hidden"]):not([type="file"]), select, button[data-archive-modal-close]');
    var fileInput = overlayHost.querySelector("[data-archive-upload-file]");
    var target = fileInput || first;
    if (target) target.focus({ preventScroll: true });
  });

  /* remember what opened the popup so focus can go back to it */
  document.addEventListener("click", function (event) {
    var opener = event.target.closest("[data-archive-add-btn], [data-archive-manage-btn]");
    if (opener) lastOpener = opener;
  });

  /* drag over the drop zone highlights it (the invisible input underneath takes the actual drop) */
  document.addEventListener("dragover", function (event) {
    var zone = event.target.closest && event.target.closest("[data-archive-dropzone]");
    if (zone) zone.classList.add("is-dragover");
  });
  ["dragleave", "drop"].forEach(function (name) {
    document.addEventListener(name, function (event) {
      var zone = event.target.closest && event.target.closest("[data-archive-dropzone]");
      if (zone) zone.classList.remove("is-dragover");
    });
  });

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
    if (event.key === "Escape" && viewer && !viewer.hidden) { closeViewer(); return; }
    if (event.key === "Escape" && overlayHost && overlayHost.querySelector("[data-archive-modal]")) { closeModal(); return; }
    var layer = overlayHost && overlayHost.querySelector("[data-archive-modal] [role='dialog']");
    if (layer) trapTab(layer, event);
  });

  /* ---------- image viewer ----------
     Opens from any picture card ([data-archive-open], its data-* attributes carry
     everything shown). Prev/Next walk through the pictures on the current page. */
  var viewer = document.querySelector("[data-archive-viewer]");
  var viewerIndex = -1;
  var viewerOpener = null;
  var touchStartX = null;

  function viewerItems() {
    return gridShell ? Array.prototype.slice.call(gridShell.querySelectorAll("[data-archive-open]")) : [];
  }

  function fillViewer(index) {
    var items = viewerItems();
    var item = items[index];
    if (!item || !viewer) return;
    viewerIndex = index;
    var d = item.dataset;
    var stage = viewer.querySelector(".archive-viewer-stage");
    var img = viewer.querySelector("[data-viewer-img]");
    stage.classList.add("is-loading");
    img.onload = function () { stage.classList.remove("is-loading"); };
    img.onerror = function () { img.onerror = null; img.src = "/static/404.jpg"; stage.classList.remove("is-loading"); };
    img.alt = d.title || "";
    img.src = d.viewSrc;
    if (img.complete && img.naturalWidth > 0) stage.classList.remove("is-loading");

    viewer.querySelector("[data-viewer-title]").textContent = d.title || "";
    viewer.querySelector("[data-viewer-dims]").textContent = (d.width && d.height && d.width !== "0") ? d.width + " \u00d7 " + d.height + " px" : "Unknown";
    viewer.querySelector("[data-viewer-quality]").textContent = d.quality || "";
    viewer.querySelector("[data-viewer-uploader]").textContent = d.uploader || "";
    viewer.querySelector("[data-viewer-date]").textContent = d.date || "";
    viewer.querySelector("[data-viewer-download]").setAttribute("href", d.download || d.viewSrc);
    viewer.querySelector("[data-viewer-copy]").dataset.shareUrl = d.copy || "";
    viewer.classList.toggle("is-single", items.length < 2);

    /* warm the neighbours so Prev/Next feels instant */
    [index - 1, index + 1].forEach(function (n) {
      if (items[n]) { var warm = new Image(); warm.src = items[n].dataset.viewSrc; }
    });
  }

  function openViewer(index, opener) {
    if (!viewer) return;
    viewerOpener = opener || null;
    viewer.classList.remove("is-closing");
    viewer.hidden = false;
    lockScroll(true);
    fillViewer(index);
    var closeBtn = viewer.querySelector(".archive-viewer-close");
    if (closeBtn) closeBtn.focus({ preventScroll: true });
  }

  function closeViewer() {
    if (!viewer || viewer.hidden) return;
    viewer.classList.add("is-closing");
    window.setTimeout(function () {
      viewer.hidden = true;
      viewer.classList.remove("is-closing");
      viewer.querySelector("[data-viewer-img]").removeAttribute("src");
      if (!(overlayHost && overlayHost.querySelector("[data-archive-modal]"))) lockScroll(false);
      if (viewerOpener && document.body.contains(viewerOpener)) viewerOpener.focus({ preventScroll: true });
      viewerOpener = null;
    }, 180);
  }

  function stepViewer(delta) {
    var items = viewerItems();
    if (items.length < 2) return;
    fillViewer((viewerIndex + delta + items.length) % items.length);
  }

  if (viewer) {
    document.addEventListener("click", function (event) {
      var open = event.target.closest("[data-archive-open]");
      if (open) {
        event.preventDefault();
        openViewer(viewerItems().indexOf(open), open);
        return;
      }
      if (viewer.hidden) return;
      if (event.target.closest("[data-archive-viewer-close]")) closeViewer();
      else if (event.target.closest("[data-viewer-prev]")) stepViewer(-1);
      else if (event.target.closest("[data-viewer-next]")) stepViewer(1);
    });

    document.addEventListener("keydown", function (event) {
      if (viewer.hidden) return;
      if (event.key === "ArrowLeft") { event.preventDefault(); stepViewer(-1); }
      else if (event.key === "ArrowRight") { event.preventDefault(); stepViewer(1); }
      else trapTab(viewer.querySelector(".archive-viewer-body"), event);
    });

    viewer.addEventListener("touchstart", function (event) {
      touchStartX = event.touches.length === 1 ? event.touches[0].clientX : null;
    }, { passive: true });
    viewer.addEventListener("touchend", function (event) {
      if (touchStartX === null) return;
      var dx = event.changedTouches[0].clientX - touchStartX;
      touchStartX = null;
      if (Math.abs(dx) > 60) stepViewer(dx < 0 ? 1 : -1);
    }, { passive: true });
  }

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
