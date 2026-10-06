(function () {
  "use strict";

  /* Guest gate: when a signed out visitor taps like, comment, save or follow, the
     server answers 401 and interactions.js calls AbuAuthGate.open(kind). A blurred
     popup then holds the create account / sign in card (an iframe on /auth/gate/).
     When the iframe reports that a session now exists, the popup closes, the page
     reloads once so the header and every form match the signed in user, and a
     success toast tells the reader to go ahead with what they were doing. */

  var GATE_URL = "/auth/gate/";
  var TOAST_KEY = "abureport-gate-toast";
  var DRAFT_KEY = "abureport-gate-comment";

  /* Copy per action. Edit the words here, nothing else reads them. */
  var COPY = {
    like: {
      title: "You do not have to like this story.",
      hook: "But a like is how an author knows the work is being appreciated. Create a free account and back them in under a minute. We will never share your email or spam you.",
      verb: "like this story"
    },
    comment: {
      title: "You do not have to comment.",
      hook: "But writers read every comment, and yours could be the one that keeps them going. A free account takes under a minute.",
      verb: "post your comment"
    },
    "comment-like": {
      title: "You do not have to like this comment.",
      hook: "But the reader who wrote it will notice. A free account takes under a minute.",
      verb: "like this comment"
    },
    bookmark: {
      title: "You do not have to save this story.",
      hook: "But every save tells the author the story was worth coming back to. A free account takes under a minute, and your reading list stays with you.",
      verb: "save this story"
    },
    follow: {
      title: "Followers are what let an author Know they have people rooting for their work",
      hook: "Signup TO Follow Author So We Can Send This Author Newsletter Whenever They Publish A New Article. We will never share your email or spam you. If you want to opt out, click here <a>ff</a>",
      verb: "follow this author"
    }
  };
  var FALLBACK = {
    title: "You do not have to sign in.",
    hook: "But a free account lets you support the authors you read. It takes under a minute.",
    verb: "continue"
  };

  var root = null;      /* overlay element */
  var frame = null;     /* iframe */
  var current = null;   /* copy for the open gate */
  var lastFocus = null;
  var closeTimer = null;

  function build() {
    root = document.createElement("div");
    root.className = "auth-gate";
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-modal", "true");
    root.setAttribute("aria-labelledby", "auth-gate-title");
    root.innerHTML =
      '<div class="auth-gate-card is-loading" data-gate-card>' +
        '<button type="button" class="auth-gate-close" data-gate-close aria-label="Close">' +
          '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 5l10 10M15 5L5 15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>' +
        '</button>' +
        '<p class="auth-gate-eyebrow">Support the author</p>' +
        '<h2 class="auth-gate-title" id="auth-gate-title" data-gate-title></h2>' +
        '<p class="auth-gate-hook" data-gate-hook></p>' +
        '<div class="auth-gate-frame-wrap"><iframe class="auth-gate-frame" title="Create an account or sign in" data-gate-frame></iframe></div>' +
      '</div>';
    document.body.appendChild(root);

    root.addEventListener("click", function (event) {
      if (event.target === root || event.target.closest("[data-gate-close]")) close();
    });
    frame = root.querySelector("[data-gate-frame]");
    frame.addEventListener("load", function () {
      root.querySelector("[data-gate-card]").classList.remove("is-loading");
    });
  }

  function open(kind) {
    if (root && root.classList.contains("is-open")) return;
    window.clearTimeout(closeTimer);
    current = COPY[kind] || FALLBACK;
    lastFocus = document.activeElement;

    if (!root) build();
    root.querySelector("[data-gate-title]").textContent = current.title;
    root.querySelector("[data-gate-hook]").textContent = current.hook;

    /* A fresh iframe each time: forms empty, CSRF pair current. */
    root.querySelector("[data-gate-card]").classList.add("is-loading");
    frame.style.height = "";
    frame.src = GATE_URL;

    root.style.display = "flex";
    document.documentElement.classList.add("auth-gate-locked");
    /* Two frames so the blur and the card animate in from their start state. */
    window.requestAnimationFrame(function () {
      window.requestAnimationFrame(function () {
        root.classList.add("is-open");
        var closeBtn = root.querySelector("[data-gate-close]");
        if (closeBtn) closeBtn.focus({ preventScroll: true });
      });
    });
  }

  function close(restoreFocus) {
    if (!root || !root.classList.contains("is-open")) return;
    root.classList.remove("is-open");
    document.documentElement.classList.remove("auth-gate-locked");
    closeTimer = window.setTimeout(function () {
      root.style.display = "none";
      frame.src = "about:blank";
    }, 260);
    if (restoreFocus !== false && lastFocus && typeof lastFocus.focus === "function") {
      try { lastFocus.focus({ preventScroll: true }); } catch (e) {}
    }
  }

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && root && root.classList.contains("is-open")) close();
  });

  window.addEventListener("message", function (event) {
    if (!frame || event.origin !== window.location.origin || event.source !== frame.contentWindow) return;
    var data = event.data;
    if (!data || data.source !== "abureport-auth-gate") return;

    if (data.type === "height" && typeof data.value === "number") {
      frame.style.height = Math.min(Math.max(data.value, 220), 520) + "px";
      return;
    }
    if (data.type !== "success") return;

    var verb = (current || FALLBACK).verb;
    var message = (data.mode === "register" ? "Account created. " : "Signed in. ") +
      (verb === "continue" ? "You can continue where you left off." : "You can now " + verb + ".");

    /* A comment typed before the popup would vanish in the reload, so keep it. */
    try {
      var box = document.querySelector("[data-comment-form] textarea[name='comment']");
      if (box && box.value.trim()) {
        sessionStorage.setItem(DRAFT_KEY, JSON.stringify({ path: window.location.pathname, text: box.value }));
      }
      sessionStorage.setItem(TOAST_KEY, message);
    } catch (e) {}

    close(false);
    window.setTimeout(function () { window.location.reload(); }, 280);
  });

  /* After the reload: restore the draft and show the success toast. */
  document.addEventListener("DOMContentLoaded", function () {
    var message = null;
    try {
      message = sessionStorage.getItem(TOAST_KEY);
      sessionStorage.removeItem(TOAST_KEY);
      var raw = sessionStorage.getItem(DRAFT_KEY);
      sessionStorage.removeItem(DRAFT_KEY);
      if (raw) {
        var draft = JSON.parse(raw);
        var box = document.querySelector("[data-comment-form] textarea[name='comment']");
        if (box && draft && draft.path === window.location.pathname && !box.value) box.value = draft.text;
      }
    } catch (e) {}
    if (message && typeof window.AbuToast === "function") {
      window.setTimeout(function () { window.AbuToast(message, "success"); }, 250);
    }
  });

  window.AbuAuthGate = { open: open, close: close };
})();
