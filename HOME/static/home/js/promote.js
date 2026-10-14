(function () {
  "use strict";

  //   The promote page renders a shimmer skeleton in the advert grid, then this
  //   swaps in the server-rendered cards (HOME/views.PromoteAdsView). Keeping
  //   the fetch on GET and replacing innerHTML means we never build markup from
  //   strings in JS and the section is never a wall of text.
  var grid = document.querySelector("[data-promote-ads]");
  if (!grid) return;

  var url = grid.getAttribute("data-ads-url");
  if (!url || typeof window.fetch !== "function") return;

  fetch(url, {
    method: "GET",
    credentials: "same-origin",
    headers: { "X-Requested-With": "XMLHttpRequest" },
    cache: "no-store"
  })
    .then(function (response) {
      if (!response.ok) throw new Error("adverts feed failed: " + response.status);
      return response.text();
    })
    .then(function (html) {
      grid.innerHTML = html;
      grid.removeAttribute("aria-busy");
    })
    .catch(function () {
      //   Never leave the shimmer running forever: swap in a quiet fallback.
      var note = document.createElement("p");
      note.className = "promote-ads-empty";
      note.textContent =
        "We could not load the adverts running right now. Refresh the page to try again.";
      grid.innerHTML = "";
      grid.appendChild(note);
      grid.removeAttribute("aria-busy");
    });
})();
