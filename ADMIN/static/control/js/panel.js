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

    function loadMore() {
      if (loadingMore) return;
      var hasNext = track.dataset.hasNext === "true";
      var endpoint = track.dataset.endpoint;
      if (!endpoint) return;

      loadingMore = true;
      var page = hasNext ? track.dataset.nextPage : "1";

      fetch(endpoint + "?page=" + encodeURIComponent(page), { credentials: "same-origin" })
        .then(function (response) { return response.json(); })
        .then(function (data) {
          (data.items || []).forEach(function (member) { track.appendChild(renderCard(member)); });
          observeLazyImages(track);
          track.dataset.hasNext = data.has_next ? "true" : "false";
          track.dataset.nextPage = data.next_page || "";
          loadingMore = false;
        })
        .catch(function () { loadingMore = false; });
    }

    function maybeLoadMore() {
      var remaining = track.scrollWidth - viewport.scrollLeft - viewport.clientWidth;
      if (remaining < viewport.clientWidth) loadMore();
    }

    /* pointer drag */
    viewport.addEventListener("pointerdown", function (event) {
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
    viewport.addEventListener("scroll", maybeLoadMore);

    /* ping-pong auto-scroll: right to the end, then back to the start */
    function tick() {
      if (!userPaused) {
        var maxScroll = track.scrollWidth - viewport.clientWidth;
        if (maxScroll > 0) {
          if (viewport.scrollLeft >= maxScroll - 2) autoDir = -1;
          else if (viewport.scrollLeft <= 2) autoDir = 1;
          viewport.scrollLeft += autoDir * 0.6;
          if (autoDir > 0) maybeLoadMore();
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

        var email = document.createElement("span");
        email.textContent = row.email_masked;

        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "panel-danger-link";
        btn.dataset.sessionLogout = "";
        btn.textContent = "Log out";

        div.appendChild(email);
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

  /* ---------- analytics: lazy, only once scrolled into view ---------- */
  (function () {
    var card = document.querySelector("[data-analytics-card]");
    if (!card) return;
    var skeleton = card.querySelector("[data-analytics-skeleton]");
    var dataHost = card.querySelector("[data-analytics-data]");
    var loaded = false;

    function metric(label, value) {
      var div = document.createElement("div");
      div.className = "panel-metric-card";
      var l = document.createElement("p");
      l.className = "panel-metric-label";
      l.textContent = label;
      var v = document.createElement("p");
      v.className = "panel-metric-value";
      v.textContent = value;
      div.appendChild(l);
      div.appendChild(v);
      return div;
    }

    function load() {
      if (loaded) return;
      loaded = true;
      fetch(card.dataset.endpoint, { credentials: "same-origin" })
        .then(function (response) { return response.json(); })
        .then(function (data) {
          dataHost.appendChild(metric("Members", data.member_count));
          dataHost.appendChild(metric("Staff", data.staff_count));
          dataHost.appendChild(metric("Admins", data.admin_count));
          dataHost.appendChild(metric("Published stories", data.published_count));
          dataHost.appendChild(metric("Currently logged in", data.active_people));
          skeleton.hidden = true;
          dataHost.hidden = false;
        })
        .catch(function () {
          loaded = false;
          toast("Could not load analytics.", "error");
        });
    }

    if ("IntersectionObserver" in window) {
      var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) { load(); observer.disconnect(); }
        });
      }, { rootMargin: "100px" });
      observer.observe(card);
    } else {
      load();
    }
  })();
})();
