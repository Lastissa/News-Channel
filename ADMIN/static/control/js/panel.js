(function () {
  "use strict";

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
      toastHost.style.cssText = "position:fixed;left:50%;bottom:22px;transform:translateX(-50%);z-index:300;display:flex;flex-direction:column;gap:8px;align-items:center;";
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

  function postForm(endpoint, formData) {
    return fetch(endpoint, {
      method: "POST",
      headers: { "X-CSRFToken": getCookie("csrftoken"), "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
      body: formData,
    }).then(function (response) {
      return response.text().then(function (text) { return { ok: response.ok, text: text }; });
    });
  }

  function debounce(fn, wait) {
    var timer = null;
    return function () {
      var args = arguments;
      var ctx = this;
      window.clearTimeout(timer);
      timer = window.setTimeout(function () { fn.apply(ctx, args); }, wait);
    };
  }

  /* ---------- lazy avatar images ---------- */
  var lazyObserver = null;
  function observeLazyImages(root) {
    var nodes = (root || document).querySelectorAll("img[data-src]");
    if (!nodes.length) return;

    if (!("IntersectionObserver" in window)) {
      nodes.forEach(function (img) { img.src = img.dataset.src; img.removeAttribute("data-src"); });
      return;
    }
    if (!lazyObserver) {
      lazyObserver = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          var img = entry.target;
          img.src = img.dataset.src;
          img.removeAttribute("data-src");
          lazyObserver.unobserve(img);
        });
      }, { rootMargin: "80px" });
    }
    nodes.forEach(function (img) { lazyObserver.observe(img); });
  }
  observeLazyImages(document);

  /* ---------- staff gallery: drag scroll + ping-pong auto-scroll ---------- */
  (function () {
    var viewport = document.querySelector("[data-gallery-viewport]");
    var track = document.querySelector("[data-gallery-track]");
    if (!viewport || !track) return;

    var isDragging = false;
    var dragStartX = 0;
    var scrollStartLeft = 0;
    var didDrag = false;
    var autoDir = 1;
    var autoTimer = null;
    var userPaused = false;
    var loadingMore = false;

    function renderCard(member) {
      var a = document.createElement("a");
      a.className = "panel-gallery-card";
      a.href = member.url;

      var avatar = document.createElement("span");
      avatar.className = "panel-gallery-avatar";
      if (member.profile_img) {
        var img = document.createElement("img");
        img.loading = "lazy";
        img.dataset.src = member.profile_img;
        img.alt = "";
        img.className = "panel-lazy-avatar";
        avatar.appendChild(img);
      } else {
        var initial = document.createElement("span");
        initial.className = "panel-gallery-initial";
        initial.textContent = (member.heading || "?").slice(0, 1);
        avatar.appendChild(initial);
      }

      var name = document.createElement("span");
      name.className = "panel-gallery-name";
      name.textContent = member.heading;

      var role = document.createElement("span");
      role.className = "panel-gallery-role";
      role.textContent = member.authority;

      a.appendChild(avatar);
      a.appendChild(name);
      a.appendChild(role);
      return a;
    }

    var loadMoreBtn = track.querySelector("[data-gallery-load-more]");

    function setLoadMoreLabel(loading) {
      if (!loadMoreBtn) return;
      loadMoreBtn.disabled = loading;
      loadMoreBtn.textContent = loading ? "Loading..." : "Load more";
    }

    /* Only ever runs from a tap on the "Load more" button now. It used to be
       fired by the scroll listener and the auto-scroll tick, and when there was
       no next page it fell back to requesting page 1 again -- which is what
       made mobile hammer the endpoint forever and never reach an end. */
    function loadMore() {
      if (loadingMore) return;
      var hasNext = track.dataset.hasNext === "true";
      var endpoint = track.dataset.endpoint;
      if (!endpoint || !hasNext) return;

      loadingMore = true;
      setLoadMoreLabel(true);
      var page = track.dataset.nextPage;

      fetch(endpoint + "?page=" + encodeURIComponent(page), { credentials: "same-origin" })
        .then(function (response) {
          if (!response.ok) throw new Error("bad response");
          return response.json();
        })
        .then(function (data) {
          var items = data.items || [];
          items.forEach(function (member) {
            var card = renderCard(member);
            if (loadMoreBtn) track.insertBefore(card, loadMoreBtn);
            else track.appendChild(card);
          });
          observeLazyImages(track);
          track.dataset.hasNext = data.has_next ? "true" : "false";
          track.dataset.nextPage = data.next_page || "";
          loadingMore = false;

          if (data.has_next && items.length) {
            /* more was loaded and there is still more: keep the animation going */
            setLoadMoreLabel(false);
          } else {
            /* nothing further to load: remove the button and stop the animation */
            if (loadMoreBtn) loadMoreBtn.hidden = true;
            if (autoTimer) {
              window.cancelAnimationFrame(autoTimer);
              autoTimer = null;
            }
          }
        })
        .catch(function () {
          loadingMore = false;
          setLoadMoreLabel(false);
          toast("Could not load more staff.", "error");
        });
    }

    if (loadMoreBtn) loadMoreBtn.addEventListener("click", loadMore);

    /* pointer drag */
    viewport.addEventListener("pointerdown", function (event) {
      if (event.target.closest && event.target.closest("[data-gallery-load-more]")) return;
      isDragging = true;
      didDrag = false;
      userPaused = true;
      viewport.classList.add("is-dragging");
      dragStartX = event.clientX;
      scrollStartLeft = viewport.scrollLeft;
      viewport.setPointerCapture(event.pointerId);
    });

    viewport.addEventListener("pointermove", function (event) {
      if (!isDragging) return;
      var delta = event.clientX - dragStartX;
      if (Math.abs(delta) > 4) didDrag = true;
      viewport.scrollLeft = scrollStartLeft - delta;
    });

    function endDrag() {
      isDragging = false;
      viewport.classList.remove("is-dragging");
      window.setTimeout(function () { userPaused = false; }, 1200);
    }
    viewport.addEventListener("pointerup", endDrag);
    viewport.addEventListener("pointercancel", endDrag);
    viewport.addEventListener("pointerleave", function () { if (isDragging) endDrag(); });

    /* clicking a card right after a drag shouldn't navigate */
    viewport.addEventListener("click", function (event) {
      if (didDrag) { event.preventDefault(); didDrag = false; }
    });

    viewport.addEventListener("mouseenter", function () { userPaused = true; });
    viewport.addEventListener("mouseleave", function () { if (!isDragging) userPaused = false; });

    /* ping-pong auto-scroll: right to the end, then back to the start */
    function tick() {
      if (!userPaused) {
        var maxScroll = track.scrollWidth - viewport.clientWidth;
        if (maxScroll > 0) {
          if (viewport.scrollLeft >= maxScroll - 2) autoDir = -1;
          else if (viewport.scrollLeft <= 2) autoDir = 1;
          viewport.scrollLeft += autoDir * 0.6;
        }
      }
      autoTimer = window.requestAnimationFrame(tick);
    }
    autoTimer = window.requestAnimationFrame(tick);
  })();

  /* ---------- active sessions: pager + logout ---------- */
  (function () {
    var list = document.querySelector("[data-sessions-list]");
    var pager = document.querySelector("[data-sessions-pager]");
    if (!list || !pager) return;

    var logoutTemplate = list.dataset.logoutEndpoint || "";

    function renderRows(items) {
      list.innerHTML = "";
      if (!items.length) {
        list.innerHTML = '<p class="empty-copy">Nobody is currently logged in.</p>';
        return;
      }
      items.forEach(function (row) {
        var div = document.createElement("div");
        div.className = "panel-row";
        div.dataset.sessionRow = "";
        div.dataset.accountId = row.id;

        var main = document.createElement("span");
        main.className = "panel-row-main";

        var email = document.createElement("span");
        email.textContent = row.email_masked;
        main.appendChild(email);

        if (row.logged_in_at) {
          var loginInfo = document.createElement("span");
          loginInfo.className = "panel-row-sub";
          loginInfo.textContent = "Logged in " + row.logged_in_at;
          main.appendChild(loginInfo);
        }

        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "panel-danger-link";
        btn.dataset.sessionLogout = "";
        btn.textContent = "Log out";

        div.appendChild(main);
        div.appendChild(btn);
        list.appendChild(div);
      });
    }

    function renderPager(data) {
      pager.innerHTML = "";
      if (data.num_pages <= 1) return;
      var prev = document.createElement("button");
      prev.type = "button";
      prev.textContent = "Prev";
      prev.disabled = !data.has_previous;
      prev.addEventListener("click", function () { load(data.previous_page); });

      var label = document.createElement("span");
      label.textContent = "Page " + data.page + " of " + data.num_pages;
      label.style.color = "var(--slate)";
      label.style.alignSelf = "center";

      var next = document.createElement("button");
      next.type = "button";
      next.textContent = "Next";
      next.disabled = !data.has_next;
      next.addEventListener("click", function () { load(data.next_page); });

      pager.appendChild(prev);
      pager.appendChild(label);
      pager.appendChild(next);
    }

    function load(page) {
      fetch(list.dataset.endpoint + "?page=" + encodeURIComponent(page), { credentials: "same-origin" })
        .then(function (response) { return response.json(); })
        .then(function (data) {
          list.dataset.page = data.page;
          renderRows(data.items || []);
          renderPager(data);
        })
        .catch(function () { toast("Could not load active sessions.", "error"); });
    }

    list.addEventListener("click", function (event) {
      var btn = event.target.closest("[data-session-logout]");
      if (!btn) return;
      var row = btn.closest("[data-session-row]");
      if (!row || btn.dataset.pending === "true") return;

      var accountId = row.dataset.accountId;
      var endpoint = logoutTemplate.replace(/0\/logout\/?$/, accountId + "/logout/");

      btn.dataset.pending = "true";
      btn.disabled = true;

      postForm(endpoint, new FormData()).then(function (result) {
        if (!result.ok) {
          btn.dataset.pending = "false";
          btn.disabled = false;
          toast(extractDetail(result.text, "Could not log that user out."), "error");
          return;
        }
        row.remove();
        toast(extractDetail(result.text, "Logged out."));
        if (!list.querySelector("[data-session-row]")) {
          list.innerHTML = '<p class="empty-copy">Nobody is currently logged in.</p>';
        }
      });
    });

    renderPager({
      page: Number(list.dataset.page) || 1,
      num_pages: Number(list.dataset.numPages) || 1,
      has_next: list.dataset.hasNext === "true",
      has_previous: list.dataset.hasPrevious === "true",
      next_page: (Number(list.dataset.page) || 1) + 1,
      previous_page: (Number(list.dataset.page) || 1) - 1,
    });
  })();

  /* ---------- site settings save ---------- */
  (function () {
    var form = document.querySelector("[data-settings-form]");
    if (!form) return;
    var feedback = form.querySelector("[data-settings-feedback]");
    var submitBtn = form.querySelector("button[type='submit']");

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (submitBtn.dataset.pending === "true") return;
      submitBtn.dataset.pending = "true";
      submitBtn.disabled = true;

      postForm(form.dataset.endpoint, new FormData(form)).then(function (result) {
        submitBtn.dataset.pending = "false";
        submitBtn.disabled = false;
        if (!result.ok) {
          toast(extractDetail(result.text, "Could not save site settings."), "error");
          return;
        }
        if (feedback) feedback.textContent = "Saved.";
        toast("Site settings saved.");
      });
    });
  })();

  /* ---------- news categories: add + remove ---------- */
  (function () {
    var form = document.querySelector("[data-category-form]");
    var list = document.querySelector("[data-category-list]");
    if (!form || !list) return;

    var total = document.querySelector("[data-category-total]");
    var input = form.querySelector("input[name='name']");
    var submitBtn = form.querySelector("button[type='submit']");
    var deleteTemplate = list.dataset.deleteEndpoint || "";

    function storyCopy(count) {
      return count + (count === 1 ? " story" : " stories");
    }

    function syncTotal() {
      var count = list.querySelectorAll("[data-category-row]").length;
      var empty = list.querySelector("[data-category-empty]");
      if (total) total.textContent = count + " active";
      if (!count && !empty) {
        list.insertAdjacentHTML("beforeend", '<p class="empty-copy" data-category-empty>No categories yet.</p>');
      }
      if (count && empty) empty.remove();
    }

    function buildRow(category) {
      var row = document.createElement("div");
      row.className = "panel-row";
      row.dataset.categoryRow = "";
      row.dataset.categoryId = category.id;
      row.dataset.categoryLabel = category.label;
      row.dataset.storyCount = category.story_count;

      var main = document.createElement("span");
      main.className = "panel-row-main";

      var name = document.createElement("span");
      name.textContent = category.label;
      main.appendChild(name);

      var stories = document.createElement("span");
      stories.className = "panel-row-sub";
      stories.dataset.categoryStories = "";
      stories.textContent = storyCopy(category.story_count);
      main.appendChild(stories);

      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "panel-danger-link";
      btn.dataset.categoryRemove = "";
      btn.textContent = "Remove";

      row.appendChild(main);
      row.appendChild(btn);
      return row;
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (submitBtn.dataset.pending === "true") return;
      submitBtn.dataset.pending = "true";
      submitBtn.disabled = true;

      postForm(form.dataset.endpoint, new FormData(form)).then(function (result) {
        submitBtn.dataset.pending = "false";
        submitBtn.disabled = false;
        if (!result.ok) {
          toast(extractDetail(result.text, "Could not add that category."), "error");
          return;
        }
        var data = {};
        try { data = JSON.parse(result.text); } catch (e) { data = {}; }
        if (data.category) list.appendChild(buildRow(data.category));
        input.value = "";
        syncTotal();
        toast(extractDetail(result.text, "Category added."));
      });
    });

    list.addEventListener("click", function (event) {
      var btn = event.target.closest("[data-category-remove]");
      if (!btn) return;
      var row = btn.closest("[data-category-row]");
      if (!row || btn.dataset.pending === "true") return;

      var label = row.dataset.categoryLabel || "this category";
      var stories = Number(row.dataset.storyCount) || 0;
      var warning = "Remove " + label + "? It disappears from the menu and the story form.";
      if (stories) warning += " " + storyCopy(stories) + " stay published under it.";
      if (!window.confirm(warning)) return;

      var endpoint = deleteTemplate.replace(/0\/delete\/?$/, row.dataset.categoryId + "/delete/");

      btn.dataset.pending = "true";
      btn.disabled = true;

      postForm(endpoint, new FormData()).then(function (result) {
        if (!result.ok) {
          btn.dataset.pending = "false";
          btn.disabled = false;
          toast(extractDetail(result.text, "Could not remove that category."), "error");
          return;
        }
        row.remove();
        syncTotal();
        toast(extractDetail(result.text, "Category removed."));
      });
    });
  })();

  /* ---------- text awareness: scrolling home bar, add + edit + delete ---------- */
  (function () {
    var form = document.querySelector("[data-ta-form]");
    var list = document.querySelector("[data-ta-list]");
    var initial = document.getElementById("ta-initial");
    if (!form || !list) return;

    var total = document.querySelector("[data-ta-total]");
    var updateTemplate = list.dataset.updateEndpoint || "";
    var deleteTemplate = list.dataset.deleteEndpoint || "";
    var STATUS_LABEL = { live: "Live", paused: "Paused", expired: "Expired" };
    var items = [];
    try { items = JSON.parse(initial ? initial.textContent : "[]") || []; } catch (e) { items = []; }

    function endpointFor(template, id) { return template.replace(/0\/(update|delete)\/?$/, id + "/$1/"); }

    function el(tag, className, text) {
      var node = document.createElement(tag);
      if (className) node.className = className;
      if (text !== undefined) node.textContent = text;
      return node;
    }

    function field(labelText, control, id) {
      var wrap = el("div", "panel-field");
      var label = el("label", "", labelText);
      label.setAttribute("for", id);
      control.id = id;
      wrap.appendChild(label);
      wrap.appendChild(control);
      return wrap;
    }

    function buildRow(item) {
      var row = el("div", "panel-row ta-row");
      row.dataset.taRow = "";
      row.dataset.id = item.id;

      var main = el("span", "panel-row-main");
      main.appendChild(el("span", "ta-text", item.content));
      var sub = el("span", "panel-row-sub");
      sub.appendChild(el("span", "ta-status ta-status-" + item.status, STATUS_LABEL[item.status] || item.status));
      sub.appendChild(document.createTextNode(" Ends " + item.expiry_label + (item.url ? " \u00b7 has link" : "") + (item.added_by ? " \u00b7 by " + item.added_by : "")));
      main.appendChild(sub);

      var actions = el("span", "ta-actions");
      var edit = el("button", "panel-ghost-btn", "Edit");
      edit.type = "button";
      edit.dataset.taEdit = "";
      var del = el("button", "panel-danger-link", "Delete");
      del.type = "button";
      del.dataset.taDelete = "";
      actions.appendChild(edit);
      actions.appendChild(del);

      row.appendChild(main);
      row.appendChild(actions);
      return row;
    }

    function buildEditor(item) {
      var row = el("form", "panel-form ta-editor");
      row.dataset.taEditor = "";
      row.dataset.id = item.id;
      row.noValidate = false;

      var content = el("textarea");
      content.name = "content"; content.rows = 2; content.maxLength = 400; content.required = true; content.value = item.content;
      var url = el("input");
      url.type = "url"; url.name = "url"; url.value = item.url; url.placeholder = "https://...";
      var expiry = el("input");
      expiry.type = "datetime-local"; expiry.name = "expiry_date"; expiry.required = true; expiry.value = item.expiry_input;

      var key = "ta-" + item.id + "-";
      row.appendChild(field("Text", content, key + "c"));
      row.appendChild(field("Link (optional)", url, key + "u"));
      row.appendChild(field("Stops showing on", expiry, key + "e"));

      var activeWrap = el("label", "ta-check");
      var active = el("input");
      active.type = "checkbox"; active.name = "is_active"; active.value = "1"; active.checked = item.is_active;
      activeWrap.appendChild(active);
      activeWrap.appendChild(document.createTextNode(" Show on the home page"));
      row.appendChild(activeWrap);

      var footer = el("div", "panel-form-footer");
      var cancel = el("button", "panel-ghost-btn", "Cancel");
      cancel.type = "button"; cancel.dataset.taCancel = "";
      var save = el("button", "panel-primary-btn", "Save");
      save.type = "submit";
      footer.appendChild(cancel);
      footer.appendChild(save);
      row.appendChild(footer);
      return row;
    }

    function render() {
      list.textContent = "";
      items.forEach(function (item) { list.appendChild(buildRow(item)); });
      if (!items.length) list.appendChild(el("p", "empty-copy", "No text yet. Readers will see the default placeholder until you add one."));
      if (total) {
        var live = items.filter(function (item) { return item.status === "live"; }).length;
        total.textContent = live + " live";
      }
    }

    function indexOfId(id) {
      for (var i = 0; i < items.length; i += 1) if (String(items[i].id) === String(id)) return i;
      return -1;
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var btn = form.querySelector("button[type='submit']");
      if (btn.disabled) return;
      btn.disabled = true;
      postForm(form.dataset.endpoint, new FormData(form)).then(function (result) {
        btn.disabled = false;
        if (!result.ok) { toast(extractDetail(result.text, "Could not add that text."), "error"); return; }
        var data = JSON.parse(result.text || "{}");
        if (data.item) items.unshift(data.item);
        form.reset();
        render();
        toast(extractDetail(result.text, "Text added."));
      }).catch(function () { btn.disabled = false; toast("Connection issue. Nothing was added.", "error"); });
    });

    list.addEventListener("click", function (event) {
      var row = event.target.closest("[data-ta-row]");
      var editor = event.target.closest("[data-ta-editor]");

      if (event.target.closest("[data-ta-edit]") && row) {
        var item = items[indexOfId(row.dataset.id)];
        if (item) row.replaceWith(buildEditor(item));
        return;
      }
      if (event.target.closest("[data-ta-cancel]") && editor) {
        var original = items[indexOfId(editor.dataset.id)];
        if (original) editor.replaceWith(buildRow(original));
        return;
      }
      var delBtn = event.target.closest("[data-ta-delete]");
      if (delBtn && row) {
        if (delBtn.disabled) return;
        if (!window.confirm("Delete this text? It stops scrolling on the home page straight away.")) return;
        delBtn.disabled = true;
        postForm(endpointFor(deleteTemplate, row.dataset.id), new FormData()).then(function (result) {
          if (!result.ok) { delBtn.disabled = false; toast(extractDetail(result.text, "Could not delete that text."), "error"); return; }
          var at = indexOfId(row.dataset.id);
          if (at !== -1) items.splice(at, 1);
          render();
          toast(extractDetail(result.text, "Text deleted."));
        }).catch(function () { delBtn.disabled = false; toast("Connection issue. Nothing was deleted.", "error"); });
      }
    });

    list.addEventListener("submit", function (event) {
      var editor = event.target.closest("[data-ta-editor]");
      if (!editor) return;
      event.preventDefault();
      var save = editor.querySelector("button[type='submit']");
      if (save.disabled) return;
      var data = new FormData(editor);
      if (!editor.querySelector("input[name='is_active']").checked) data.set("is_active", "0");
      save.disabled = true;
      postForm(endpointFor(updateTemplate, editor.dataset.id), data).then(function (result) {
        save.disabled = false;
        if (!result.ok) { toast(extractDetail(result.text, "Could not save that text."), "error"); return; }
        var payload = JSON.parse(result.text || "{}");
        var at = indexOfId(editor.dataset.id);
        if (at !== -1 && payload.item) items[at] = payload.item;
        render();
        toast(extractDetail(result.text, "Text updated."));
      }).catch(function () { save.disabled = false; toast("Connection issue. Nothing was saved.", "error"); });
    });

    render();
  })();

  /* ---------- mass email composer ---------- */
  (function () {
    var form = document.querySelector("[data-mass-email-form]");
    if (!form) return;

    var toggles = form.querySelectorAll("[data-toggle]");
    var addToggle = form.querySelector("[data-toggle-add]");
    var searchBox = form.querySelector("[data-recipient-search]");
    var searchInput = form.querySelector("[data-recipient-search-input]");
    var resultsHost = form.querySelector("[data-recipient-results]");
    var pillsHost = form.querySelector("[data-recipient-pills]");
    var hiddenIds = form.querySelector("[data-extra-account-ids]");
    var sendBtn = form.querySelector("[data-mass-email-send]");

    var active = { member: false, staff: false, admin: false };
    var extras = {}; // account_id -> { full_name, profile_img }

    function syncHidden() {
      hiddenIds.value = Object.keys(extras).join(",");
    }

    function renderPills() {
      pillsHost.innerHTML = "";
      Object.keys(extras).forEach(function (id) {
        var pill = document.createElement("span");
        pill.className = "panel-recipient-pill";
        var label = document.createElement("span");
        label.textContent = extras[id].full_name;
        var remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "\u2715";
        remove.addEventListener("click", function () {
          delete extras[id];
          renderPills();
          syncHidden();
        });
        pill.appendChild(label);
        pill.appendChild(remove);
        pillsHost.appendChild(pill);
      });
    }

    function updateAddAvailability() {
      var blocked = active.staff && active.admin;
      addToggle.disabled = blocked;
      addToggle.title = blocked ? "Staff and admin together already cover everyone with a staff profile." : "";
      if (blocked) {
        searchBox.hidden = true;
      }
    }

    toggles.forEach(function (btn) {
      if (btn.hasAttribute("data-toggle-add")) return;
      btn.addEventListener("click", function () {
        var key = btn.dataset.toggle;
        active[key] = !active[key];
        btn.classList.toggle("is-active", active[key]);
        updateAddAvailability();
      });
    });

    addToggle.addEventListener("click", function () {
      if (addToggle.disabled) return;
      searchBox.hidden = !searchBox.hidden;
      if (!searchBox.hidden) searchInput.focus();
    });

    var runSearch = debounce(function () {
      var q = searchInput.value.trim();
      resultsHost.innerHTML = "";
      if (!q) return;

      fetch(form.dataset.searchEndpoint + "?q=" + encodeURIComponent(q), { credentials: "same-origin" })
        .then(function (response) { return response.json(); })
        .then(function (data) {
          resultsHost.innerHTML = "";
          (data.items || []).forEach(function (item) {
            var row = document.createElement("div");
            row.className = "panel-recipient-result-row";

            var avatar = document.createElement("span");
            avatar.className = "panel-recipient-result-avatar";
            if (item.profile_img) {
              var img = document.createElement("img");
              img.src = item.profile_img;
              img.alt = "";
              avatar.appendChild(img);
            }

            var name = document.createElement("span");
            name.textContent = item.full_name + " \u00b7 " + item.authority;

            var addBtn = document.createElement("button");
            addBtn.type = "button";
            var already = !!extras[item.account_id];
            addBtn.textContent = already ? "Added" : "Add";
            addBtn.disabled = already;
            addBtn.addEventListener("click", function () {
              if (!window.confirm("Send this email to " + item.full_name + "? Their address stays hidden from you and everyone else client side.")) return;
              extras[item.account_id] = { full_name: item.full_name };
              renderPills();
              syncHidden();
              addBtn.textContent = "Added";
              addBtn.disabled = true;
            });

            row.appendChild(avatar);
            row.appendChild(name);
            row.appendChild(addBtn);
            resultsHost.appendChild(row);
          });
        });
    }, 260);

    searchInput.addEventListener("input", runSearch);

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (sendBtn.disabled || sendBtn.dataset.pending === "true") return;

      var subject = form.querySelector("[name='subject']").value.trim();
      var body = form.querySelector("[name='body']").value.trim();
      if (!subject) { toast("Enter an email heading.", "error"); return; }
      if (!body) { toast("Enter the email body.", "error"); return; }
      if (!active.member && !active.staff && !active.admin && !Object.keys(extras).length) {
        toast("Choose at least one recipient group.", "error");
        return;
      }

      var data = new FormData(form);
      if (active.member) data.set("include_member", "on");
      if (active.staff) data.set("include_staff", "on");
      if (active.admin) data.set("include_admin", "on");

      sendBtn.dataset.pending = "true";
      sendBtn.disabled = true;
      var originalText = sendBtn.textContent;
      sendBtn.textContent = "Sending...";

      postForm(form.dataset.endpoint, data).then(function (result) {
        sendBtn.dataset.pending = "false";
        sendBtn.disabled = false;
        sendBtn.textContent = originalText;
        if (!result.ok) {
          toast(extractDetail(result.text, "Could not send the email."), "error");
          return;
        }
        toast(extractDetail(result.text, "Email sent."));
        form.reset();
        toggles.forEach(function (btn) {
          if (!btn.hasAttribute("data-toggle-add")) btn.classList.remove("is-active");
        });
        active = { member: false, staff: false, admin: false };
        extras = {};
        renderPills();
        syncHidden();
        updateAddAvailability();
      });
    });
  })();

  /* ---------- speciality search ---------- */
  (function () {
    var input = document.querySelector("[data-speciality-input]");
    var list = document.querySelector("[data-speciality-list]");
    var pager = document.querySelector("[data-speciality-pager]");
    if (!input || !list) return;

    function renderRows(items) {
      list.innerHTML = "";
      if (!items.length) {
        list.innerHTML = '<p class="empty-copy">No staff match that speciality.</p>';
        return;
      }
      items.forEach(function (item) {
        var row = document.createElement("a");
        row.className = "panel-row panel-row-link";
        row.href = item.url;

        var avatar = document.createElement("span");
        avatar.className = "panel-row-avatar";
        if (item.profile_img) {
          var img = document.createElement("img");
          img.dataset.src = item.profile_img;
          img.className = "panel-lazy-avatar";
          img.alt = "";
          avatar.appendChild(img);
        }

        var textWrap = document.createElement("span");
        var name = document.createElement("span");
        name.className = "panel-row-name";
        name.textContent = item.full_name;
        var sub = document.createElement("span");
        sub.className = "panel-row-sub";
        sub.textContent = " \u00b7 " + item.achievement;
        textWrap.appendChild(name);
        textWrap.appendChild(sub);

        row.appendChild(avatar);
        row.appendChild(textWrap);
        list.appendChild(row);
      });
      observeLazyImages(list);
    }

    function renderPager(data, query) {
      pager.innerHTML = "";
      if (!data || data.num_pages <= 1) return;
      var prev = document.createElement("button");
      prev.type = "button";
      prev.textContent = "Prev";
      prev.disabled = !data.has_previous;
      prev.addEventListener("click", function () { load(query, data.previous_page); });

      var label = document.createElement("span");
      label.textContent = "Page " + data.page + " of " + data.num_pages;
      label.style.color = "var(--slate)";
      label.style.alignSelf = "center";

      var next = document.createElement("button");
      next.type = "button";
      next.textContent = "Next";
      next.disabled = !data.has_next;
      next.addEventListener("click", function () { load(query, data.next_page); });

      pager.appendChild(prev);
      pager.appendChild(label);
      pager.appendChild(next);
    }

    function load(query, page) {
      var endpoint = input.dataset.endpoint;
      fetch(endpoint + "?q=" + encodeURIComponent(query) + "&page=" + encodeURIComponent(page || 1), { credentials: "same-origin" })
        .then(function (response) { return response.json(); })
        .then(function (data) {
          renderRows(data.items || []);
          renderPager(data, query);
        })
        .catch(function () { toast("Could not search staff.", "error"); });
    }

    var runSearch = debounce(function () { load(input.value.trim(), 1); }, 300);
    input.addEventListener("input", runSearch);
    load("", 1);
  })();
})();
