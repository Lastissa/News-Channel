(function () {
  "use strict";

  var valid = ["overview", "adverts", "analytics", "activity"];

  function setActive(name) {
    if (valid.indexOf(name) === -1) return;
    document.querySelectorAll("[data-ads-tab]").forEach(function (tab) {
      var active = tab.getAttribute("data-ads-tab") === name;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", active ? "true" : "false");
    });
  }

  document.addEventListener("click", function (event) {
    var tab = event.target.closest("[data-ads-tab]");
    if (tab) {
      setActive(tab.getAttribute("data-ads-tab"));
      return;
    }

    var opener = event.target.closest("[data-ads-open]");
    if (opener) {
      setActive(opener.getAttribute("data-ads-open"));
    }
  });

  document.addEventListener("htmx:afterSwap", function (event) {
    var target = event.detail && event.detail.target;
    if (target && target.id === "ads-tab-host") {
      window.dispatchEvent(new Event("resize"));
    }
  });

  var params = new URLSearchParams(window.location.search);
  setActive(params.get("section") || "overview");
})();

(function () {
  "use strict";

  function loadHtml2Canvas() {
    if (window.html2canvas) return Promise.resolve();
    return new Promise(function (resolve, reject) {
      var script = document.createElement("script");
      script.src = "https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js";
      script.onload = resolve;
      script.onerror = function () { reject(new Error("Screenshot library unavailable.")); };
      document.head.appendChild(script);
    });
  }

  function canvasToFile(canvas) {
    return new Promise(function (resolve, reject) {
      canvas.toBlob(function (blob) {
        if (!blob) return reject(new Error("Screenshot failed."));
        resolve(new File([blob], "abureport-advertiser-dashboard.png", { type: "image/png" }));
      }, "image/png");
    });
  }

  async function shareScreenshot(button) {
    var section = document.querySelector("[data-ads-dashboard]");
    if (!section) return;

    var oldText = button.textContent;
    button.disabled = true;
    button.textContent = "Preparingâ€¦";

    var header = document.createElement("div");
    header.className = "ads-shot-header";
    header.innerHTML = "<strong>AbuReport</strong><time></time>";
    header.querySelector("time").textContent = new Date().toLocaleDateString(undefined, {
      day: "2-digit", month: "short", year: "numeric"
    });

    try {
      await loadHtml2Canvas();

      section.insertBefore(header, section.firstChild);
      section.classList.add("is-capturing");
      await new Promise(function (r) { requestAnimationFrame(function () { requestAnimationFrame(r); }); });

      var bg = getComputedStyle(document.body).getPropertyValue("--paper").trim() || "#ffffff";
      var canvas = await window.html2canvas(section, {
        backgroundColor: bg,
        scale: 2,
        useCORS: true,
        scrollX: 0,
        scrollY: 0
      });

      var file = await canvasToFile(canvas);

      if (navigator.canShare && navigator.canShare({ files: [file] })) {
        await navigator.share({
          files: [file],
          title: "AbuReport advertiser dashboard",
          text: "My AbuReport advertiser dashboard"
        });
      } else {
        var url = URL.createObjectURL(file);
        var link = document.createElement("a");
        link.href = url;
        link.download = file.name;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
      }
    } catch (error) {
      window.alert(error.message || "Could not share the screenshot.");
    } finally {
      header.remove();
      section.classList.remove("is-capturing");
      button.disabled = false;
      button.textContent = oldText;
    }
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-ads-share-shot]");
    if (button) shareScreenshot(button);
  });
})();