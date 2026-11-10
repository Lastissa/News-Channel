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

  /* ---------- icons ---------- */
  var SVG_NS = "http://www.w3.org/2000/svg";
  function icon(name, extraClass) {
    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("class", "ic" + (extraClass ? " " + extraClass : ""));
    svg.setAttribute("aria-hidden", "true");
    var use = document.createElementNS(SVG_NS, "use");
    use.setAttribute("href", "#i-" + name);
    svg.appendChild(use);
    return svg;
  }

  /* Icon-only button. aria-label + title always set so nothing is lost. */
  function iconButton(className, name, label) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = className;
    btn.setAttribute("aria-label", label);
    btn.title = label;
    btn.appendChild(icon(name));
    return btn;
  }

  /* ---------- shell: scroll reveal, collapsible cards, icon nav ---------- */
  (function () {
    var shell = document.querySelector("[data-panel]");
    if (!shell) return;
    var cards = Array.prototype.slice.call(shell.querySelectorAll(".panel-card"));

    shell.classList.add("panel-js");
    if ("IntersectionObserver" in window) {
      var revealObserver = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-in");
          revealObserver.unobserve(entry.target);
        });
      }, { rootMargin: "0px 0px -8% 0px", threshold: 0.05 });
      cards.forEach(function (card) { revealObserver.observe(card); });
    } else {
      cards.forEach(function (card) { card.classList.add("is-in"); });
    }

    /*  Collapsible cards. Every card ships collapsed so the panel opens as a
        tidy list of section headers; a nav tap jumps to a section and opens
        it. One helper keeps the card class and the button's aria state in
        step, and syncs the labels for the cards that start folded. */
    function setCollapsed(card, collapsed) {
      card.classList.toggle("is-collapsed", collapsed);
      var btn = card.querySelector("[data-collapse]");
      if (!btn) return;
      btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
      var heading = card.querySelector("h2");
      var name = heading ? heading.textContent.trim() : "section";
      btn.setAttribute("aria-label", (collapsed ? "Expand " : "Collapse ") + name);
      btn.title = collapsed ? "Expand" : "Collapse";
    }
    cards.forEach(function (card) {
      if (card.classList.contains("is-collapsed")) setCollapsed(card, true);
    });

    shell.addEventListener("click", function (event) {
      var btn = event.target.closest("[data-collapse]");
      if (btn) {
        var card = btn.closest(".panel-card");
        if (card) setCollapsed(card, !card.classList.contains("is-collapsed"));
        return;
      }
      /*  The whole header is a handle. Tapping the section name -- "Active
          Logins", "Categories" -- opens the section, not only the chevron on
          the right. Anything that is itself a control inside the header keeps
          its own click. */
      var header = event.target.closest(".panel-card-header");
      if (header) {
        var ownControl = event.target.closest("button, a, input, select, textarea, [role='button']");
        if (!ownControl) {
          var card = header.closest(".panel-card");
          if (card) setCollapsed(card, !card.classList.contains("is-collapsed"));
        }
        return;
      }
      /*  A section link in the nav opens the section it points at, so a tap
          reveals content instead of landing on a folded header. */
      var link = event.target.closest(".panel-nav-link");
      if (!link) return;
      var target = document.getElementById((link.getAttribute("href") || "").slice(1));
      if (target && target.classList.contains("panel-card")) setCollapsed(target, false);
    });

    /* highlight the nav icon of the card nearest the top of the viewport */
    var nav = shell.querySelector("[data-panel-nav]");
    if (!nav || !("IntersectionObserver" in window)) return;
    var links = Array.prototype.slice.call(nav.querySelectorAll(".panel-nav-link"));
    function setActive(id) {
      links.forEach(function (link) {
        var on = link.getAttribute("href") === "#" + id;
        link.classList.toggle("is-active", on);
        if (on) {
          link.setAttribute("aria-current", "true");
          if (nav.scrollWidth > nav.clientWidth) {
            nav.scrollTo({ left: link.offsetLeft - nav.clientWidth / 2 + link.offsetWidth / 2, behavior: "smooth" });
          }
        } else {
          link.removeAttribute("aria-current");
        }
      });
    }
    var visible = {};
    var spy = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) { visible[entry.target.id] = entry.isIntersecting; });
      for (var i = 0; i < cards.length; i += 1) {
        if (visible[cards[i].id]) { setActive(cards[i].id); return; }
      }
    }, { rootMargin: "-30% 0px -55% 0px" });
    cards.forEach(function (card) { spy.observe(card); });
  })();

  /* ---------- label bubble for icon-only buttons ----------
     One shared bubble, positioned with fixed coordinates so no card or the
     scrolling nav can clip it. Shown on mouse hover, keyboard focus and, for
     touch/pen, on tap (short timeout, since touch has no hover). The text is
     the button's own aria-label, so it always matches what a screen reader
     says. The native title is moved to data-tip so the browser's own tooltip
     does not appear on top of it. */
  (function () {
    var shell = document.querySelector("[data-panel]");
    if (!shell) return;

    var bubble = document.createElement("div");
    bubble.className = "panel-tip";
    bubble.setAttribute("role", "presentation");
    bubble.setAttribute("aria-hidden", "true");
    document.body.appendChild(bubble);

    var current = null;
    var hideTimer = null;
    var SELECTOR = "button[aria-label], a[aria-label]";

    function labelOf(node) {
      if (node.hasAttribute("title")) {
        node.dataset.tip = node.getAttribute("title");
        node.removeAttribute("title");
      }
      /* the collapse button keeps its short title word ("Collapse") in sync
         with aria-label, so prefer aria-label when it is the longer, fuller one */
      return node.getAttribute("aria-label") || node.dataset.tip || "";
    }

    function place(node) {
      var rect = node.getBoundingClientRect();
      var tipRect = bubble.getBoundingClientRect();
      var margin = 8;
      var left = rect.left + rect.width / 2 - tipRect.width / 2;
      left = Math.max(margin, Math.min(left, window.innerWidth - tipRect.width - margin));
      var above = rect.top - tipRect.height - 8;
      var below = rect.bottom + 8;
      var top = above >= margin ? above : below;
      bubble.dataset.side = above >= margin ? "above" : "below";
      bubble.style.left = Math.round(left) + "px";
      bubble.style.top = Math.round(top) + "px";
    }

    function show(node, autoHideMs) {
      var text = labelOf(node);
      if (!text) return;
      window.clearTimeout(hideTimer);
      current = node;
      bubble.textContent = text;
      bubble.classList.add("is-on");
      place(node);
      if (autoHideMs) hideTimer = window.setTimeout(hide, autoHideMs);
    }

    function hide() {
      window.clearTimeout(hideTimer);
      current = null;
      bubble.classList.remove("is-on");
    }

    shell.addEventListener("pointerover", function (event) {
      if (event.pointerType !== "mouse") return;
      var node = event.target.closest(SELECTOR);
      if (node && shell.contains(node)) show(node);
    });
    shell.addEventListener("pointerout", function (event) {
      if (event.pointerType !== "mouse") return;
      var node = event.target.closest(SELECTOR);
      if (node && node === current && !node.contains(event.relatedTarget)) hide();
    });

    /* touch / pen: no hover exists, so a tap shows the label for a moment */
    shell.addEventListener("pointerdown", function (event) {
      if (event.pointerType === "mouse") return;
      var node = event.target.closest(SELECTOR);
      if (node && shell.contains(node)) show(node, 1800);
    });

    /* keyboard focus (not the focus a mouse click leaves behind) */
    shell.addEventListener("focusin", function (event) {
      var node = event.target.closest(SELECTOR);
      if (node && node.matches(":focus-visible")) show(node);
    });
    shell.addEventListener("focusout", function (event) {
      if (event.target.closest(SELECTOR) === current) hide();
    });

    /* a label that is showing while the user acts must not go stale or drift */
    shell.addEventListener("click", function (event) {
      var node = event.target.closest(SELECTOR);
      if (node && node === current) window.setTimeout(function () {
        if (current !== node) return;
        bubble.textContent = labelOf(node);   /* e.g. Collapse becomes Expand */
        place(node);
      }, 0);
    });
    window.addEventListener("scroll", hide, { passive: true });
    window.addEventListener("resize", hide);
    document.addEventListener("keydown", function (event) { if (event.key === "Escape") hide(); });
  })();

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
      loadMoreBtn.setAttribute("aria-busy", loading ? "true" : "false");
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

    /* pointer drag: the pointer is captured only once a real drag begins.
       Capturing on pointerdown retargeted the follow-up click to the viewport
       itself, so a plain click or tap on a card never reached the card's link
       and the directory felt unclickable. Deferring capture until the drag
       threshold is crossed lets both scrolling and clicking work. */
    var DRAG_THRESHOLD = 5;
    var pendingDrag = false;

    viewport.addEventListener("pointerdown", function (event) {
      if (event.target.closest && event.target.closest("[data-gallery-load-more]")) return;
      if (event.pointerType === "mouse" && event.button !== 0) return;
      pendingDrag = true;
      isDragging = false;
      didDrag = false;
      userPaused = true;
      dragStartX = event.clientX;
      scrollStartLeft = viewport.scrollLeft;
    });

    viewport.addEventListener("pointermove", function (event) {
      if (!pendingDrag) return;
      var delta = event.clientX - dragStartX;
      if (!isDragging) {
        if (Math.abs(delta) < DRAG_THRESHOLD) return;
        isDragging = true;
        didDrag = true;
        viewport.classList.add("is-dragging");
        if (viewport.setPointerCapture) {
          try { viewport.setPointerCapture(event.pointerId); } catch (err) { /* drag still works without capture */ }
        }
      }
      viewport.scrollLeft = scrollStartLeft - delta;
    });

    function endDrag() {
      pendingDrag = false;
      isDragging = false;
      viewport.classList.remove("is-dragging");
      window.setTimeout(function () { userPaused = false; }, 1200);
    }
    viewport.addEventListener("pointerup", endDrag);
    viewport.addEventListener("pointercancel", endDrag);
    viewport.addEventListener("pointerleave", endDrag);

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

  /* ---------- active sessions: pager, per-account logout, per-session logout ---------- */
  (function () {
    var list = document.querySelector("[data-sessions-list]");
    var pager = document.querySelector("[data-sessions-pager]");
    if (!list || !pager) return;

    var logoutTemplate = list.dataset.logoutEndpoint || "";
    var singleLogoutTemplate = list.dataset.singleLogoutEndpoint || "";

    function accountEndpoint(accountId) {
      return logoutTemplate.replace(/0\/logout\/?$/, accountId + "/logout/");
    }

    function singleEndpoint(accountId) {
      return singleLogoutTemplate.replace(/0\/session-logout\/?$/, accountId + "/session-logout/");
    }

    /*  Build the nested per-session block shown when a row is expanded:
        device, network, sign-in / last-seen / expiry per session, each with
        its own End button. Mirrors the server-rendered markup exactly. */
    function buildSessionDetail(row) {
      var detail = document.createElement("div");
      detail.className = "panel-session-detail";
      detail.dataset.sessionDetail = "";
      detail.hidden = true;

      (row.sessions || []).forEach(function (session) {
        var rowEl = document.createElement("div");
        rowEl.className = "panel-session-detail-row";
        rowEl.dataset.sessionKey = session.session_key;

        var main = document.createElement("span");
        main.className = "panel-row-main";

        var device = document.createElement("span");
        device.className = "panel-session-device";
        device.textContent = session.device;
        if (session.is_suspicious) {
          var badge = document.createElement("span");
          badge.className = "panel-badge panel-badge-danger";
          badge.textContent = "Unrecognised";
          device.appendChild(document.createTextNode(" "));
          device.appendChild(badge);
        }
        main.appendChild(device);

        var network = document.createElement("span");
        network.className = "panel-row-sub";
        network.textContent = session.ip + " · signed in " + session.logged_in_at;
        main.appendChild(network);

        var seen = "Last active " + session.last_seen;
        if (session.expires_at) seen += " · ends " + session.expires_at;
        var seenEl = document.createElement("span");
        seenEl.className = "panel-row-sub";
        seenEl.textContent = seen;
        main.appendChild(seenEl);

        var endBtn = iconButton("panel-icon-btn panel-icon-danger", "logout", "End this session");
        endBtn.dataset.sessionSingleLogout = "";

        rowEl.appendChild(main);
        rowEl.appendChild(endBtn);
        detail.appendChild(rowEl);
      });

      return detail;
    }

    function renderRows(items) {
      list.innerHTML = "";
      if (!items.length) {
        list.innerHTML = '<p class="panel-empty">Nobody is currently logged in.</p>';
        return;
      }
      items.forEach(function (row) {
        var div = document.createElement("div");
        div.className = "panel-row panel-session-row";
        div.dataset.sessionRow = "";
        div.dataset.accountId = row.id;

        var main = document.createElement("span");
        main.className = "panel-row-main";

        var email = document.createElement("span");
        email.className = "panel-session-email";
        email.textContent = row.email_masked;
        if (row.suspicious_count) {
          var badge = document.createElement("span");
          badge.className = "panel-badge panel-badge-danger";
          badge.title = "Signed in from a device this account had not used before";
          badge.textContent = "Unrecognised";
          email.appendChild(document.createTextNode(" "));
          email.appendChild(badge);
        }
        main.appendChild(email);

        var sub = document.createElement("span");
        sub.className = "panel-row-sub";
        var count = row.session_count || 0;
        sub.textContent = count + (count === 1 ? " session" : " sessions");
        if (row.logged_in_at) sub.textContent += " · last sign-in " + row.logged_in_at;
        main.appendChild(sub);

        var toggle = iconButton("panel-icon-btn panel-session-toggle", "chevron", "Show sessions");
        toggle.dataset.sessionToggle = "";
        toggle.setAttribute("aria-expanded", "false");

        var btn = iconButton("panel-icon-btn panel-icon-danger", "logout", "Log out all");
        btn.dataset.sessionLogout = "";

        div.appendChild(main);
        div.appendChild(toggle);
        div.appendChild(btn);
        div.appendChild(buildSessionDetail(row));
        list.appendChild(div);
      });
    }

    function renderPager(data) {
      pager.innerHTML = "";
      if (data.num_pages <= 1) return;
      var prev = iconButton("", "left", "Previous page");
      prev.disabled = !data.has_previous;
      prev.addEventListener("click", function () { load(data.previous_page); });

      var label = document.createElement("span");
      label.textContent = data.page + " / " + data.num_pages;

      var next = iconButton("", "right", "Next page");
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
      /*  Expand / collapse the per-session detail for one account. */
      var toggle = event.target.closest("[data-session-toggle]");
      if (toggle) {
        var toggleRow = toggle.closest("[data-session-row]");
        var detail = toggleRow ? toggleRow.querySelector("[data-session-detail]") : null;
        if (!detail) return;
        detail.hidden = !detail.hidden;
        toggle.setAttribute("aria-expanded", detail.hidden ? "false" : "true");
        return;
      }

      /*  End ONE session. The account id in the URL and the session key in
          the body both travel, so the server can prove they belong together. */
      var endOne = event.target.closest("[data-session-single-logout]");
      if (endOne) {
        var oneRow = endOne.closest("[data-session-detail-row]");
        var parentRow = endOne.closest("[data-session-row]");
        if (!oneRow || !parentRow || endOne.dataset.pending === "true") return;
        if (!window.confirm("End this session?")) return;

        var oneKey = oneRow.dataset.sessionKey;
        var oneData = new FormData();
        oneData.append("session_key", oneKey);
        endOne.dataset.pending = "true";
        endOne.disabled = true;

        postForm(singleEndpoint(parentRow.dataset.accountId), oneData).then(function (result) {
          if (!result.ok) {
            endOne.dataset.pending = "false";
            endOne.disabled = false;
            toast(extractDetail(result.text, "Could not end that session."), "error");
            return;
          }
          oneRow.remove();
          toast(extractDetail(result.text, "Session ended."));
        });
        return;
      }

      /*  End EVERY session the account holds. */
      var btn = event.target.closest("[data-session-logout]");
      if (!btn) return;
      var row = btn.closest("[data-session-row]");
      if (!row || btn.dataset.pending === "true") return;
      if (!window.confirm("Log this account out of every device?")) return;

      var accountId = row.dataset.accountId;
      var endpoint = accountEndpoint(accountId);

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
          list.innerHTML = '<p class="panel-empty">Nobody is currently logged in.</p>';
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
      if (total) total.textContent = String(count);
      if (!count && !empty) {
        list.insertAdjacentHTML("beforeend", '<p class="panel-empty" data-category-empty>No categories yet.</p>');
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

      var btn = iconButton("panel-icon-btn panel-icon-danger", "trash", "Remove " + category.label);
      btn.dataset.categoryRemove = "";

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

  /* ---------- announcements: scrolling home bar, add + edit + delete ---------- */
  (function () {
    var form = document.querySelector("[data-ann-form]");
    var list = document.querySelector("[data-ann-list]");
    var initial = document.getElementById("ann-initial");
    if (!form || !list) return;

    var total = document.querySelector("[data-ann-total]");
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
      var row = el("div", "ta-item ta-item-" + item.status);
      row.dataset.annRow = "";
      row.dataset.id = item.id;

      var main = el("span", "ta-main");
      main.appendChild(el("span", "ta-text", item.content));
      var sub = el("span", "ta-meta");
      sub.appendChild(el("span", "ta-status ta-status-" + item.status, STATUS_LABEL[item.status] || item.status));
      sub.appendChild(icon("clock"));
      sub.appendChild(el("span", "", item.expiry_label));
      if (item.url) { var linked = icon("link"); linked.setAttribute("aria-label", "Has a link"); sub.appendChild(linked); }
      if (item.added_by) { sub.appendChild(icon("user")); sub.appendChild(el("span", "", item.added_by)); }
      main.appendChild(sub);

      var actions = el("span", "ta-actions");
      var edit = iconButton("panel-icon-btn", "edit", "Edit");
      edit.dataset.annEdit = "";
      var del = iconButton("panel-icon-btn panel-icon-danger", "trash", "Delete");
      del.dataset.annDelete = "";
      actions.appendChild(edit);
      actions.appendChild(del);

      row.appendChild(main);
      row.appendChild(actions);
      return row;
    }

    function buildEditor(item) {
      var row = el("form", "ta-item ta-editor");
      row.dataset.annEditor = "";
      row.dataset.id = item.id;
      row.noValidate = false;

      var content = el("textarea");
      content.name = "content"; content.rows = 2; content.maxLength = 400; content.required = true; content.value = item.content;
      var url = el("input");
      url.type = "url"; url.name = "url"; url.value = item.url; url.placeholder = "https://...";
      var expiry = el("input");
      expiry.type = "datetime-local"; expiry.name = "expiry_date"; expiry.required = true; expiry.value = item.expiry_input;

      var key = "ann-" + item.id + "-";
      row.appendChild(field("Text", content, key + "c"));
      var pair = el("div", "ta-pair");
      pair.appendChild(field("Link", url, key + "u"));
      pair.appendChild(field("Ends", expiry, key + "e"));
      row.appendChild(pair);

      var activeWrap = el("label", "ta-check");
      var active = el("input");
      active.type = "checkbox"; active.name = "is_active"; active.value = "1"; active.checked = item.is_active;
      activeWrap.appendChild(active);
      activeWrap.appendChild(document.createTextNode(" Show on the home page"));
      row.appendChild(activeWrap);

      var footer = el("div", "ta-editor-actions");
      var cancel = iconButton("panel-icon-btn", "x", "Cancel");
      cancel.dataset.annCancel = "";
      var save = el("button", "panel-primary-btn");
      save.type = "submit"; save.setAttribute("aria-label", "Save"); save.title = "Save"; save.appendChild(icon("check"));
      footer.appendChild(cancel);
      footer.appendChild(save);
      row.appendChild(footer);
      return row;
    }

    function render() {
      list.textContent = "";
      items.forEach(function (item) { list.appendChild(buildRow(item)); });
      if (!items.length) list.appendChild(el("p", "ta-empty", "No text yet. Readers see the default placeholder until you add one."));
      if (total) {
        var live = items.filter(function (item) { return item.status === "live"; }).length;
        total.textContent = live + " live";
      }
    }

    function indexOfId(id) {
      for (var i = 0; i < items.length; i += 1) if (String(items[i].id) === String(id)) return i;
      return -1;
    }

    var contentBox = form.querySelector("[data-ann-content]");
    var counter = form.querySelector("[data-ann-count]");
    var preview = form.querySelector("[data-ann-preview]");
    function syncCompose() {
      var value = contentBox ? contentBox.value : "";
      if (counter) counter.textContent = value.length + " / 400";
      if (preview) preview.textContent = value.trim() || "Your text appears here";
    }
    if (contentBox) contentBox.addEventListener("input", syncCompose);
    form.addEventListener("reset", function () { window.setTimeout(syncCompose, 0); });

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
      }).catch(function () { btn.disabled = false; toast("Network Error. Nothing was added.", "error"); });
    });

    list.addEventListener("click", function (event) {
      var row = event.target.closest("[data-ann-row]");
      var editor = event.target.closest("[data-ann-editor]");

      if (event.target.closest("[data-ann-edit]") && row) {
        var item = items[indexOfId(row.dataset.id)];
        if (item) row.replaceWith(buildEditor(item));
        return;
      }
      if (event.target.closest("[data-ann-cancel]") && editor) {
        var original = items[indexOfId(editor.dataset.id)];
        if (original) editor.replaceWith(buildRow(original));
        return;
      }
      var delBtn = event.target.closest("[data-ann-delete]");
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
      var editor = event.target.closest("[data-ann-editor]");
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

  /* ---------- image adverts: home hero carousel, add + edit + delete ---------- */
  (function () {
    var form = document.querySelector("[data-ad-form]");
    var list = document.querySelector("[data-ad-list]");
    var initial = document.getElementById("ad-initial");
    if (!form || !list) return;

    var total = document.querySelector("[data-ad-total]");
    var updateTemplate = list.dataset.updateEndpoint || "";
    var deleteTemplate = list.dataset.deleteEndpoint || "";
    var landingTemplate = list.dataset.landingEndpoint || "";
    var landingPreviewTemplate = list.dataset.landingPreviewEndpoint || "";
    var landingDeleteTemplate = list.dataset.landingDeleteEndpoint || "";
    var STATUS_LABEL = { live: "Live", paused: "Paused", expired: "Expired" };
    var LANDING_LABEL = { live: "Landing live", draft: "Landing draft", blocked: "Landing blocked" };
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

    function indexOfId(id) {
      for (var i = 0; i < items.length; i += 1) if (String(items[i].id) === String(id)) return i;
      return -1;
    }

    function buildRow(item) {
      var row = el("div", "ta-item ta-item-" + item.status);
      row.dataset.adRow = "";
      row.dataset.id = item.id;

      var thumb = el("img", "ad-thumb");
      thumb.src = item.image; thumb.alt = ""; thumb.loading = "lazy";

      var main = el("span", "ta-main");
      var title = el("span", "ta-text", item.heading || "No heading");
      if (item.body) title.appendChild(el("span", "ta-text-sub", " " + item.body));
      main.appendChild(title);
      var sub = el("span", "ta-meta");
      sub.appendChild(el("span", "ta-status ta-status-" + item.status, STATUS_LABEL[item.status] || item.status));
      if (LANDING_LABEL[item.landing_status]) {
        sub.appendChild(el("span", "ta-landing-status ta-landing-" + item.landing_status, LANDING_LABEL[item.landing_status]));
      }
      sub.appendChild(icon("clock"));
      sub.appendChild(el("span", "", item.expiry_label));
      if (item.url) { var linked = icon("link"); linked.setAttribute("aria-label", "Has a link"); sub.appendChild(linked); }
      if (item.added_by) { sub.appendChild(icon("user")); sub.appendChild(el("span", "", item.added_by)); }
      main.appendChild(sub);

      var actions = el("span", "ta-actions");
      var landing = iconButton("panel-icon-btn", "code", "Landing page");
      landing.dataset.adLanding = "";
      if (item.landing_status === "live") landing.classList.add("is-landing-live");
      var edit = iconButton("panel-icon-btn", "edit", "Edit");
      edit.dataset.adEdit = "";
      var del = iconButton("panel-icon-btn panel-icon-danger", "trash", "Delete");
      del.dataset.adDelete = "";
      actions.appendChild(landing);
      actions.appendChild(edit);
      actions.appendChild(del);

      row.appendChild(thumb);
      row.appendChild(main);
      row.appendChild(actions);
      return row;
    }

    function buildEditor(item) {
      var row = el("form", "ta-item ta-editor");
      row.dataset.adEditor = "";
      row.dataset.id = item.id;

      var key = "ad-" + item.id + "-";

      var fileWrap = el("div", "ad-editor-file");
      var thumb = el("img", "ad-thumb");
      thumb.src = item.image; thumb.alt = "";
      var file = el("input", "panel-file-input");
      file.type = "file"; file.name = "image"; file.accept = "image/jpeg,image/png"; file.id = key + "i";
      file.setAttribute("aria-label", "Replace the picture");
      file.addEventListener("change", function () {
        if (file.files && file.files[0]) thumb.src = URL.createObjectURL(file.files[0]);
      });
      fileWrap.appendChild(thumb);
      fileWrap.appendChild(file);
      row.appendChild(fileWrap);

      var heading = el("input");
      heading.type = "text"; heading.name = "heading"; heading.maxLength = 90; heading.value = item.heading;
      var body = el("textarea");
      body.name = "body"; body.rows = 2; body.maxLength = 200; body.value = item.body;
      var url = el("input");
      url.type = "url"; url.name = "url"; url.value = item.url; url.placeholder = "https://..."; url.required = true;
      var expiry = el("input");
      expiry.type = "datetime-local"; expiry.name = "expiry_date"; expiry.required = true; expiry.value = item.expiry_input;

      row.appendChild(field("Heading", heading, key + "h"));
      row.appendChild(field("Text", body, key + "b"));
      var pair = el("div", "ta-pair");
      pair.appendChild(field("Link", url, key + "u"));
      pair.appendChild(field("Ends", expiry, key + "e"));
      row.appendChild(pair);

      var activeWrap = el("label", "ta-check");
      var active = el("input");
      active.type = "checkbox"; active.name = "is_active"; active.value = "1"; active.checked = item.is_active;
      activeWrap.appendChild(active);
      activeWrap.appendChild(document.createTextNode(" Show on the home page"));
      row.appendChild(activeWrap);

      var footer = el("div", "ta-editor-actions");
      var cancel = iconButton("panel-icon-btn", "x", "Cancel");
      cancel.dataset.adCancel = "";
      var save = el("button", "panel-primary-btn");
      save.type = "submit"; save.setAttribute("aria-label", "Save"); save.title = "Save"; save.appendChild(icon("check"));
      footer.appendChild(cancel);
      footer.appendChild(save);
      row.appendChild(footer);
      return row;
    }

    function render() {
      list.textContent = "";
      items.forEach(function (item) { list.appendChild(buildRow(item)); });
      if (!items.length) list.appendChild(el("p", "ta-empty", "No image adverts yet."));
      if (total) {
        var live = items.filter(function (item) { return item.status === "live"; }).length;
        total.textContent = live + " live";
      }
    }

    /* compose: live preview that mirrors the desktop home slide */
    var fileInput = form.querySelector("[data-ad-file]");
    var previewImg = form.querySelector("[data-ad-preview]");
    var emptyHint = form.querySelector("[data-ad-empty]");
    var caption = form.querySelector("[data-ad-caption]");
    var captionHeading = form.querySelector("[data-ad-caption-heading]");
    var captionBody = form.querySelector("[data-ad-caption-body]");
    var headingBox = form.querySelector("[data-ad-heading]");
    var bodyBox = form.querySelector("[data-ad-body]");
    var headingCount = form.querySelector("[data-ad-count-heading]");
    var bodyCount = form.querySelector("[data-ad-count-body]");
    var previewUrl = "";

    function clearPreviewUrl() {
      if (previewUrl) { URL.revokeObjectURL(previewUrl); previewUrl = ""; }
    }

    function syncCompose() {
      var h = headingBox ? headingBox.value : "";
      var b = bodyBox ? bodyBox.value : "";
      if (headingCount) headingCount.textContent = h.length + " / 90";
      if (bodyCount) bodyCount.textContent = b.length + " / 200";
      if (captionHeading) captionHeading.textContent = h.trim();
      if (captionBody) captionBody.textContent = b.trim();
      if (caption) caption.hidden = !(h.trim() || b.trim()) || !previewUrl;
    }

    function syncPicture() {
      clearPreviewUrl();
      var chosen = fileInput && fileInput.files && fileInput.files[0];
      if (chosen) previewUrl = URL.createObjectURL(chosen);
      if (previewImg) { previewImg.hidden = !previewUrl; previewImg.src = previewUrl; }
      if (emptyHint) emptyHint.hidden = !!previewUrl;
      syncCompose();
    }

    if (fileInput) fileInput.addEventListener("change", syncPicture);
    if (headingBox) headingBox.addEventListener("input", syncCompose);
    if (bodyBox) bodyBox.addEventListener("input", syncCompose);
    form.addEventListener("reset", function () { window.setTimeout(syncPicture, 0); });

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var btn = form.querySelector("button[type='submit']");
      if (btn.disabled) return;
      if (!fileInput.files || !fileInput.files[0]) { toast("Choose the advert picture.", "error"); return; }
      btn.disabled = true;
      btn.setAttribute("aria-busy", "true");
      postForm(form.dataset.endpoint, new FormData(form)).then(function (result) {
        btn.disabled = false;
        btn.setAttribute("aria-busy", "false");
        if (!result.ok) { toast(extractDetail(result.text, "Could not add that advert."), "error"); return; }
        var data = JSON.parse(result.text || "{}");
        if (data.item) items.unshift(data.item);
        form.reset();
        render();
        toast(extractDetail(result.text, "Advert added."));
      }).catch(function () {
        btn.disabled = false;
        btn.setAttribute("aria-busy", "false");
        toast("Network Error. Nothing was added.", "error");
      });
    });

    list.addEventListener("click", function (event) {
      var row = event.target.closest("[data-ad-row]");
      var editor = event.target.closest("[data-ad-editor]");

      if (event.target.closest("[data-ad-edit]") && row) {
        var item = items[indexOfId(row.dataset.id)];
        if (item) row.replaceWith(buildEditor(item));
        return;
      }
      if (event.target.closest("[data-ad-cancel]") && editor) {
        var original = items[indexOfId(editor.dataset.id)];
        if (original) editor.replaceWith(buildRow(original));
        return;
      }
      if (event.target.closest("[data-ad-landing]") && row) {
        var landingItem = items[indexOfId(row.dataset.id)];
        if (landingItem) openLanding(landingItem);
        return;
      }
      var delBtn = event.target.closest("[data-ad-delete]");
      if (delBtn && row) {
        if (delBtn.disabled) return;
        if (!window.confirm("Delete this advert? The picture is removed and it disappears from the home page straight away.")) return;
        delBtn.disabled = true;
        postForm(endpointFor(deleteTemplate, row.dataset.id), new FormData()).then(function (result) {
          if (!result.ok) { delBtn.disabled = false; toast(extractDetail(result.text, "Could not delete that advert."), "error"); return; }
          var at = indexOfId(row.dataset.id);
          if (at !== -1) items.splice(at, 1);
          render();
          toast(extractDetail(result.text, "Advert deleted."));
        }).catch(function () { delBtn.disabled = false; toast("Connection issue. Nothing was deleted.", "error"); });
      }
    });

    list.addEventListener("submit", function (event) {
      var editor = event.target.closest("[data-ad-editor]");
      if (!editor) return;
      event.preventDefault();
      var save = editor.querySelector("button[type='submit']");
      if (save.disabled) return;
      var data = new FormData(editor);
      var picker = editor.querySelector("input[type='file']");
      if (!picker.files || !picker.files.length) data.delete("image");
      if (!editor.querySelector("input[name='is_active']").checked) data.set("is_active", "0");
      save.disabled = true;
      save.setAttribute("aria-busy", "true");
      postForm(endpointFor(updateTemplate, editor.dataset.id), data).then(function (result) {
        save.disabled = false;
        save.setAttribute("aria-busy", "false");
        if (!result.ok) { toast(extractDetail(result.text, "Could not save that advert."), "error"); return; }
        var payload = JSON.parse(result.text || "{}");
        var at = indexOfId(editor.dataset.id);
        if (at !== -1 && payload.item) items[at] = payload.item;
        render();
        toast(extractDetail(result.text, "Advert updated."));
      }).catch(function () {
        save.disabled = false;
        save.setAttribute("aria-busy", "false");
        toast("Connection issue. Nothing was saved.", "error");
      });
    });

    syncCompose();
    render();

    /* ---------- image advert landing-page editor ---------- */
    var landingModal = document.querySelector("[data-ad-landing-modal]");
    var landingForm = landingModal ? landingModal.querySelector("[data-ad-landing-form]") : null;
    var landingSub = landingModal ? landingModal.querySelector("[data-ad-landing-sub]") : null;
    var landingError = landingModal ? landingModal.querySelector("[data-ad-landing-error]") : null;
    var landingStatus = landingModal ? landingModal.querySelector("[data-ad-landing-status]") : null;
    var landingView = landingModal ? landingModal.querySelector("[data-ad-landing-view]") : null;
    var landingDelete = landingModal ? landingModal.querySelector("[data-ad-landing-delete]") : null;
    var landingSave = landingModal ? landingModal.querySelector("[data-ad-landing-save]") : null;
    var landingPreviewBtn = landingModal ? landingModal.querySelector("[data-ad-landing-preview]") : null;
    var landingFrame = landingModal ? landingModal.querySelector("[data-ad-landing-frame]") : null;
    var landingPreviewEmpty = landingModal ? landingModal.querySelector("[data-ad-landing-preview-empty]") : null;
    var landingHtml = landingModal ? landingModal.querySelector("[data-ad-landing-html]") : null;
    var landingSize = landingModal ? landingModal.querySelector("[data-ad-landing-size]") : null;
    var landingLines = landingModal ? landingModal.querySelector("[data-ad-landing-lines]") : null;
    var landingMetaTitle = landingModal ? landingModal.querySelector("[data-ad-landing-meta-title]") : null;
    var landingMetaDescription = landingModal ? landingModal.querySelector("[data-ad-landing-meta-description]") : null;
    var landingOgImage = landingModal ? landingModal.querySelector("[data-ad-landing-og-image]") : null;
    var landingRobots = landingModal ? landingModal.querySelector("[data-ad-landing-robots]") : null;
    var landingPublished = landingModal ? landingModal.querySelector("[data-ad-landing-published]") : null;
    var landingTabs = landingModal ? landingModal.querySelectorAll("[data-ad-landing-tab]") : [];
    var landingMobileQuery = window.matchMedia ? window.matchMedia("(max-width: 900px)") : { matches: false };
    var currentLandingId = null;

    function landingEndpoint(template, id) {
      return template.replace("/0/", "/" + id + "/");
    }

    function readPanelResponse(response) {
      return response.text().then(function (text) {
        var data = {};
        try { data = JSON.parse(text || "{}"); } catch (e) { data = {}; }
        return { ok: response.ok, status: response.status, text: text, data: data };
      });
    }

    function setLandingError(message) {
      if (!landingError) return;
      landingError.textContent = message || "";
      landingError.hidden = !message;
    }

    function landingByteLength(text) {
      if (window.TextEncoder) return new TextEncoder().encode(text).length;
      return text.length;
    }

    function syncLandingCodeMeta() {
      if (!landingHtml) return;
      var text = landingHtml.value || "";
      var bytes = landingByteLength(text);
      if (landingSize) {
        landingSize.textContent = bytes < 1024
          ? bytes + " B"
          : (bytes < 1048576 ? (bytes / 1024).toFixed(1) + " KB" : (bytes / 1048576).toFixed(2) + " MB");
      }
      if (landingLines) {
        landingLines.textContent = (text ? text.split("\n").length : 0) + " lines";
      }
    }

    function setLandingStatus(item) {
      var status = item.landing_status || "none";
      var messages = {
        live: "Published. Advert clicks open this page.",
        draft: "Draft. Advert clicks use the advertiser link until it is published.",
        blocked: "Blocked. The last editor is no longer an active admin, so the page will not run.",
        none: "No landing page saved yet. Advert clicks use the advertiser link."
      };
      if (landingStatus) landingStatus.textContent = messages[status] || messages.none;
      if (landingView) {
        if (item.landing_url) {
          landingView.href = item.landing_url;
          landingView.hidden = false;
        } else {
          landingView.hidden = true;
          landingView.removeAttribute("href");
        }
      }
      if (landingDelete) landingDelete.hidden = !item.landing_path;
    }

    function setLandingPlaceholders(item) {
      if (landingMetaTitle) landingMetaTitle.placeholder = item.heading ? "Defaults to: " + item.heading : "Defaults to the advert heading";
      if (landingMetaDescription) landingMetaDescription.placeholder = item.body ? "Defaults to: " + item.body : "Defaults to the advert text";
      if (landingOgImage) landingOgImage.placeholder = item.image ? "Defaults to: " + item.image : "Defaults to the advert picture";
    }

    /* On a phone/tablet the editor and preview are two panes, not a long
       stacked page. Keep the same Code/Preview tab behavior as Add News. */
    function setLandingView(view, options) {
      if (!landingForm) return;
      view = view === "preview" ? "preview" : "code";
      landingForm.setAttribute("data-landing-view", view);
      landingTabs.forEach(function (tab) {
        var active = tab.getAttribute("data-ad-landing-tab") === view;
        tab.classList.toggle("is-active", active);
        tab.setAttribute("aria-selected", active ? "true" : "false");
        tab.tabIndex = active ? 0 : -1;
      });
      if (view === "preview" && (!options || options.render !== false)) {
        requestLandingPreview();
      }
    }

    function fillLandingPayload(payload) {
      var landing = payload.landing || {};
      if (landingMetaTitle) landingMetaTitle.value = landing.meta_title || "";
      if (landingMetaDescription) landingMetaDescription.value = landing.meta_description || "";
      if (landingOgImage) landingOgImage.value = landing.og_image || "";
      if (landingRobots) landingRobots.value = landing.robots || "noindex, nofollow";
      if (landingPublished) {
        landingPublished.checked = payload.item && payload.item.landing_path
          ? !!landing.is_published
          : true;
      }
      if (landingHtml) landingHtml.value = payload.html || payload.template || "";
      if (payload.fetch_error) {
        setLandingError("Could not load the saved Cloudinary HTML: " + payload.fetch_error + " The editor is blank so a save cannot overwrite it by accident.");
      }
      syncLandingCodeMeta();
    }

    function closeLanding() {
      if (!landingModal || landingModal.hidden) return;
      landingModal.hidden = true;
      landingModal.classList.remove("is-open");
      document.body.classList.remove("ad-landing-open");
      setLandingView("code", { render: false });
      if (landingFrame) landingFrame.removeAttribute("srcdoc");
      if (landingPreviewEmpty) {
        landingPreviewEmpty.hidden = false;
        landingPreviewEmpty.textContent = "Press Review page to render the HTML before saving.";
      }
      currentLandingId = null;
    }

    function openLanding(item) {
      if (!landingModal || !landingForm) return;
      if (!landingTemplate || !landingPreviewTemplate || !landingDeleteTemplate) {
        toast("Landing page editor is not configured.", "error");
        return;
      }
      currentLandingId = String(item.id);
      setLandingError("");
      landingForm.reset();
      setLandingView("code", { render: false });
      if (landingHtml) landingHtml.value = "";
      setLandingPlaceholders(item);
      setLandingStatus(item);
      syncLandingCodeMeta();
      if (landingSub) {
        var bits = ["Advert #" + item.id, item.heading || "No heading"];
        bits.push(item.landing_path || "no landing page yet");
        landingSub.textContent = bits.join(" • ");
      }
      if (landingPreviewEmpty) {
        landingPreviewEmpty.hidden = false;
        landingPreviewEmpty.textContent = "Loading the saved page...";
      }
      if (landingFrame) landingFrame.removeAttribute("srcdoc");
      if (landingSave) landingSave.disabled = true;
      landingModal.hidden = false;
      landingModal.classList.add("is-open");
      document.body.classList.add("ad-landing-open");
      window.setTimeout(function () {
        if (landingMetaTitle) landingMetaTitle.focus();
      }, 30);

      fetch(landingEndpoint(landingTemplate, item.id), {
        credentials: "same-origin",
        headers: { "Accept": "application/json", "X-Requested-With": "XMLHttpRequest" }
      }).then(readPanelResponse).then(function (result) {
        if (!result.ok) {
          setLandingError(extractDetail(result.text, "Could not load this landing page."));
          if (landingPreviewEmpty) landingPreviewEmpty.textContent = "The editor could not load this page.";
          return;
        }
        fillLandingPayload(result.data);
        if (result.data.fetch_error) {
          //   The editor is intentionally blank here. Keep Save disabled so a
          //   click cannot replace the stored Cloudinary page with nothing;
          //   typing/pasting the replacement re-enables it.
          if (landingSave) landingSave.disabled = true;
          if (landingPreviewEmpty) {
            landingPreviewEmpty.textContent = "The saved Cloudinary HTML could not be loaded.";
          }
          return;
        }
        if (landingSave) landingSave.disabled = false;
        if (!landingMobileQuery.matches || landingForm.getAttribute("data-landing-view") === "preview") {
          window.setTimeout(requestLandingPreview, 60);
        } else if (landingPreviewEmpty) {
          landingPreviewEmpty.textContent = "Switch to Preview to render the HTML.";
        }
      }).catch(function () {
        setLandingError("Connection issue. The landing page editor could not load.");
        if (landingPreviewEmpty) landingPreviewEmpty.textContent = "The editor could not load this page.";
        toast("Connection issue. Nothing was loaded.", "error");
      });
    }

    function requestLandingPreview() {
      if (!currentLandingId || !landingPreviewTemplate) return;
      if (!landingHtml || !landingHtml.value.trim()) {
        setLandingError("Paste the landing page HTML first.");
        return;
      }
      setLandingError("");
      if (landingPreviewBtn) landingPreviewBtn.disabled = true;
      if (landingPreviewEmpty) {
        landingPreviewEmpty.hidden = false;
        landingPreviewEmpty.textContent = "Rendering preview...";
      }
      var data = new FormData(landingForm);
      data.set("is_published", landingPublished && landingPublished.checked ? "1" : "0");
      postForm(landingEndpoint(landingPreviewTemplate, currentLandingId), data).then(function (result) {
        if (landingPreviewBtn) landingPreviewBtn.disabled = false;
        var payload = {};
        try { payload = JSON.parse(result.text || "{}"); } catch (e) { payload = {}; }
        if (!result.ok) {
          if (landingPreviewEmpty) {
            landingPreviewEmpty.hidden = false;
            landingPreviewEmpty.textContent = "Preview failed. " + extractDetail(result.text, "");
          }
          toast(extractDetail(result.text, "Could not render the preview."), "error");
          return;
        }
        if (landingFrame) landingFrame.srcdoc = payload.html || "";
        if (landingPreviewEmpty) landingPreviewEmpty.hidden = true;
      }).catch(function () {
        if (landingPreviewBtn) landingPreviewBtn.disabled = false;
        if (landingPreviewEmpty) {
          landingPreviewEmpty.hidden = false;
          landingPreviewEmpty.textContent = "Connection issue. The preview could not render.";
        }
        toast("Connection issue. The preview could not render.", "error");
      });
    }

    if (landingModal && landingForm) {
      landingForm.addEventListener("submit", function (event) {
        event.preventDefault();
        if (!currentLandingId || !landingTemplate) return;
        if (landingSave && landingSave.disabled) return;
        if (!landingHtml || !landingHtml.value.trim()) {
          setLandingError("Paste the landing page HTML first.");
          return;
        }
        setLandingError("");
        if (landingSave) { landingSave.disabled = true; landingSave.setAttribute("aria-busy", "true"); }
        var data = new FormData(landingForm);
        data.set("is_published", landingPublished && landingPublished.checked ? "1" : "0");
        postForm(landingEndpoint(landingTemplate, currentLandingId), data).then(function (result) {
          if (landingSave) { landingSave.disabled = false; landingSave.setAttribute("aria-busy", "false"); }
          var payload = {};
          try { payload = JSON.parse(result.text || "{}"); } catch (e) { payload = {}; }
          if (!result.ok) {
            setLandingError(extractDetail(result.text, "Could not save the landing page."));
            toast(extractDetail(result.text, "Could not save the landing page."), "error");
            return;
          }
          if (payload.item) {
            var at = indexOfId(currentLandingId);
            if (at !== -1) items[at] = payload.item;
            render();
            setLandingStatus(payload.item);
            setLandingPlaceholders(payload.item);
          }
          toast(extractDetail(result.text, "Landing page saved."));
        }).catch(function () {
          if (landingSave) { landingSave.disabled = false; landingSave.setAttribute("aria-busy", "false"); }
          setLandingError("Connection issue. Nothing was saved.");
          toast("Connection issue. Nothing was saved.", "error");
        });
      });

      landingForm.addEventListener("click", function (event) {
        var tab = event.target.closest("[data-ad-landing-tab]");
        if (tab) { setLandingView(tab.getAttribute("data-ad-landing-tab")); return; }
        if (event.target.closest("[data-ad-landing-preview]")) requestLandingPreview();
      });

      if (landingDelete) {
        landingDelete.addEventListener("click", function () {
          if (!currentLandingId || !landingDeleteTemplate || landingDelete.disabled) return;
          if (!window.confirm("Delete this landing page? The Cloudinary HTML file is removed and advert clicks fall back to the advertiser link.")) return;
          landingDelete.disabled = true;
          postForm(landingEndpoint(landingDeleteTemplate, currentLandingId), new FormData()).then(function (result) {
            landingDelete.disabled = false;
            var payload = {};
            try { payload = JSON.parse(result.text || "{}"); } catch (e) { payload = {}; }
            if (!result.ok) {
              setLandingError(extractDetail(result.text, "Could not delete the landing page."));
              toast(extractDetail(result.text, "Could not delete the landing page."), "error");
              return;
            }
            if (payload.item) {
              var at = indexOfId(currentLandingId);
              if (at !== -1) items[at] = payload.item;
              render();
            }
            closeLanding();
            toast(extractDetail(result.text, "Landing page deleted."));
          }).catch(function () {
            landingDelete.disabled = false;
            setLandingError("Connection issue. Nothing was deleted.");
            toast("Connection issue. Nothing was deleted.", "error");
          });
        });
      }

      landingModal.addEventListener("click", function (event) {
        if (event.target === landingModal) closeLanding();
        if (event.target.closest("[data-ad-landing-close]")) closeLanding();
      });

      document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && landingModal && !landingModal.hidden) closeLanding();
      });

      if (landingHtml) {
        landingHtml.addEventListener("input", function () {
          syncLandingCodeMeta();
          setLandingError("");
          if (landingSave && landingHtml.value.trim()) landingSave.disabled = false;
        });
        landingHtml.addEventListener("keydown", function (event) {
          if (event.key !== "Tab") return;
          event.preventDefault();
          var start = landingHtml.selectionStart;
          var end = landingHtml.selectionEnd;
          var value = landingHtml.value;
          landingHtml.value = value.slice(0, start) + "  " + value.slice(end);
          landingHtml.selectionStart = landingHtml.selectionEnd = start + 2;
          syncLandingCodeMeta();
        });
      }
    }
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
        remove.setAttribute("aria-label", "Remove " + extras[id].full_name);
        remove.appendChild(icon("x"));
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
            addBtn.setAttribute("aria-label", already ? "Added" : "Add " + item.full_name);
            addBtn.title = already ? "Added" : "Add";
            addBtn.appendChild(icon(already ? "check" : "plus"));
            addBtn.disabled = already;
            addBtn.addEventListener("click", function () {
              if (!window.confirm("Send this email to " + item.full_name + "? Their address stays hidden from you and everyone else client side.")) return;
              extras[item.account_id] = { full_name: item.full_name };
              renderPills();
              syncHidden();
              addBtn.setAttribute("aria-label", "Added");
              addBtn.title = "Added";
              addBtn.textContent = "";
              addBtn.appendChild(icon("check"));
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
      sendBtn.setAttribute("aria-busy", "true");

      postForm(form.dataset.endpoint, data).then(function (result) {
        sendBtn.dataset.pending = "false";
        sendBtn.disabled = false;
        sendBtn.setAttribute("aria-busy", "false");
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
        list.innerHTML = '<p class="panel-empty">No staff match that speciality.</p>';
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
      var prev = iconButton("", "left", "Previous page");
      prev.disabled = !data.has_previous;
      prev.addEventListener("click", function () { load(query, data.previous_page); });

      var label = document.createElement("span");
      label.textContent = data.page + " / " + data.num_pages;

      var next = iconButton("", "right", "Next page");
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
        .catch(function () { toast("Server Error, Could not search staff.", "error"); });
    }

    var runSearch = debounce(function () { load(input.value.trim(), 1); }, 300);
    input.addEventListener("input", runSearch);
    load("", 1);
  })();
})();
