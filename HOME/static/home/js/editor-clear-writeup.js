(function () {
  "use strict";

  /* Two-step confirmation shared by the add and edit editors.

     Step one is a plain Yes/No. Step two repeats the warning, shows
     "CALM DOWN AND READ IT PROPERLY" with a 1.5 second progress bar, and only
     enables its Yes button when the bar is finished. No at either step,
     Escape, or a backdrop click leaves the editor exactly as it was. */

  var COUNTDOWN_MS = 1500;
  var active = null;

  function makeLayer() {
    var layer = document.createElement("div");
    layer.className = "editor-clear-layer";
    layer.setAttribute("data-clear-layer", "");
    layer.hidden = true;

    var backdrop = document.createElement("div");
    backdrop.className = "editor-clear-backdrop";
    backdrop.setAttribute("data-clear-backdrop", "");

    var dialog = document.createElement("div");
    dialog.className = "editor-clear-dialog";
    dialog.setAttribute("role", "alertdialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-labelledby", "editor-clear-title");

    var title = document.createElement("h2");
    title.className = "editor-clear-title";
    title.id = "editor-clear-title";
    title.setAttribute("data-clear-title", "");

    var message = document.createElement("p");
    message.className = "editor-clear-message";
    message.setAttribute("data-clear-message", "");

    var countdown = document.createElement("p");
    countdown.className = "editor-clear-countdown";
    countdown.setAttribute("data-clear-countdown", "");
    countdown.hidden = true;
    countdown.textContent = "CALM DOWN AND READ IT PROPERLY";

    var track = document.createElement("span");
    track.className = "editor-clear-progress";
    var bar = document.createElement("i");
    track.appendChild(bar);
    countdown.appendChild(track);

    var actions = document.createElement("div");
    actions.className = "editor-clear-actions";

    var no = document.createElement("button");
    no.type = "button";
    no.className = "editor-modal-btn";
    no.setAttribute("data-clear-no", "");
    no.textContent = "No";

    var yes = document.createElement("button");
    yes.type = "button";
    yes.className = "editor-modal-btn editor-modal-btn-primary";
    yes.setAttribute("data-clear-yes", "");
    yes.textContent = "Yes";

    actions.appendChild(no);
    actions.appendChild(yes);
    dialog.appendChild(title);
    dialog.appendChild(message);
    dialog.appendChild(countdown);
    dialog.appendChild(actions);
    layer.appendChild(backdrop);
    layer.appendChild(dialog);
    document.body.appendChild(layer);

    return {
      layer: layer,
      backdrop: backdrop,
      title: title,
      message: message,
      countdown: countdown,
      bar: bar,
      no: no,
      yes: yes
    };
  }

  function close() {
    if (!active) return;
    active.layer.hidden = true;
    active.yes.disabled = false;
    active.yes.textContent = "Yes";
    active.yes.onclick = null;
    delete active.yes.dataset.step;
    active.bar.style.width = "0%";
    active.onConfirm = null;
  }

  function onKey(event) {
    if (event.key === "Escape" || event.keyCode === 27) close();
  }

  window.AbuEditorClearConfirm = function (options) {
    var config = options || {};
    if (typeof config.onConfirm !== "function") return;

    if (!active) {
      active = makeLayer();
      active.no.addEventListener("click", close);
      active.backdrop.addEventListener("click", close);
      document.addEventListener("keydown", onKey);
    }

    active.onConfirm = config.onConfirm;
    active.title.textContent = config.title || "Clear this write-up?";
    active.message.textContent = config.message || "";
    active.countdown.hidden = true;
    active.bar.style.width = "0%";
    active.yes.disabled = false;
    active.yes.textContent = "Yes";
    active.layer.hidden = false;
    active.no.focus();
    delete active.yes.dataset.step;

    active.yes.onclick = function () {
      if (active.yes.dataset.step === "two") {
        if (active.yes.disabled) return;
        var run = active.onConfirm;
        close();
        if (run) run();
        return;
      }

      active.yes.dataset.step = "two";
      active.title.textContent = config.secondTitle || "This cannot be undone";
      active.message.textContent = config.secondMessage || "";
      active.countdown.hidden = false;
      active.yes.disabled = true;
      active.yes.textContent = "Yes, clear it";

      /* Force a frame before the transition so the bar really starts at 0. */
      active.bar.style.transition = "none";
      active.bar.style.width = "0%";
      window.requestAnimationFrame(function () {
        window.requestAnimationFrame(function () {
          active.bar.style.transition = "width " + COUNTDOWN_MS + "ms linear";
          active.bar.style.width = "100%";
        });
      });
      window.setTimeout(function () {
        if (active && active.yes.dataset.step === "two") active.yes.disabled = false;
      }, COUNTDOWN_MS);
    };
  };
})();
