/* Search page: a search made here never reloads the page.
   - The page form already asks the server with htmx (see search.html).
   - The search box in the site header would normally leave for a new page, so
     on this page it hands its words to the page form instead.
   - The filter chooser keeps the hidden scope field in step, so the next
     search keeps the filter the reader picked. */
(function () {
  var pageForm = document.querySelector(".search-page-form");
  var pageInput = document.getElementById("search-page-input");
  var hidden = document.getElementById("search-scope-hidden");
  if (!pageForm || !pageInput || !window.htmx) return;

  var navInput = document.getElementById("search-input");
  var navForm = navInput && navInput.closest("form");
  if (navForm) {
    navForm.addEventListener("submit", function (event) {
      var words = navInput.value.trim();
      if (!words) return;
      event.preventDefault();
      pageInput.value = words;
      window.htmx.trigger(pageForm, "submit");
    });
  }

  //  Keep both boxes showing the same words.
  pageInput.addEventListener("input", function () {
    if (navInput) navInput.value = pageInput.value;
  });

  document.addEventListener("change", function (event) {
    if (hidden && event.target.id === "search-scope") hidden.value = event.target.value;
  });
})();
