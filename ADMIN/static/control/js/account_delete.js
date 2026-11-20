/* Deactivation controls: open the confirmation dialog and, where the dialog
   carries steps, walk through them. Plain buttons and <dialog>. */
(function () {
  if (window.__acctDeleteBound) return;
  window.__acctDeleteBound = true;

  function resetSteps(box) {
    var steps = box.querySelectorAll("[data-step]");
    steps.forEach(function (step, index) { step.hidden = index !== 0; });
    var next = box.querySelector("[data-acct-next]");
    var submit = box.querySelector("[data-acct-submit]");
    if (next) next.hidden = false;
    if (submit) submit.hidden = true;
  }

  document.addEventListener("click", function (event) {
    var open = event.target.closest("[data-acct-open]");
    if (open) {
      var box = document.getElementById(open.getAttribute("data-acct-open"));
      if (!box) return;
      if (box.hasAttribute("data-acct-steps")) resetSteps(box);
      box.showModal();
      return;
    }
    var cancel = event.target.closest("[data-acct-cancel]");
    if (cancel) {
      cancel.closest("dialog").close();
      return;
    }
    var next = event.target.closest("[data-acct-next]");
    if (next) {
      var dialog = next.closest("dialog");
      var steps = Array.prototype.slice.call(dialog.querySelectorAll("[data-step]"));
      var at = steps.findIndex(function (step) { return !step.hidden; });
      if (at < steps.length - 1) {
        steps[at].hidden = true;
        steps[at + 1].hidden = false;
      }
      if (at + 1 === steps.length - 1) {
        next.hidden = true;
        dialog.querySelector("[data-acct-submit]").hidden = false;
      }
    }
  });
})();
