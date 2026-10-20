/* ANALYTICS ApexCharts adapter.

   The page shell holds no numbers: each chart is an htmx GET returning an HTML
   fragment that carries the data as a JSON <script> plus an empty mount. This
   file turns that payload into an ApexCharts instance.

   It deliberately owns ONLY drawing. The height control, the week dialog, the
   htmx re-scan and the accessibility wiring all stay in analytics.js, which
   calls into here through window.AnalyticsApex. When ApexCharts is missing
   (an old cached bundle, a blocked script) this reports unavailable and
   analytics.js draws its own SVG instead, so a chart is never simply blank.

   ApexCharts paints its own stylesheet into <head> on first render; we only
   re-point its colours to the newsroom tokens, never its layout. */
(function () {
  "use strict";

  var FALLBACK_H = 400;   /* the wide-screen chart height, matching analytics.js */

  /* Apex fills the grid, axis and tooltip itself, so it needs the live theme
     tokens rather than a hardcoded palette. */
  function ink() {
    var css = getComputedStyle(document.documentElement);
    function read(name, fallback) {
      var value = css.getPropertyValue(name);
      return (value || "").trim() || fallback;
    }
    return {
      slate: read("--slate", "#6B7280"),
      line: read("--line", "#E5E7EB"),
      dark: document.documentElement.getAttribute("data-theme") === "dark",
    };
  }

  /* The height the admin pinned on this chart, as real pixels. The natural
     height follows analytics.js's compact/desktop frame so a percentage means
     the same shape at every width; a missing value is simply the natural one. */
  function chartHeight(mount) {
    var root = mount && mount.closest ? mount.closest("[data-chart]") : null;
    var width = mount ? mount.clientWidth : 0;
    var compact = width > 0 && width < 560;
    var natural = compact ? 250 : FALLBACK_H;
    var pct = root ? parseFloat(root.getAttribute("data-chart-h")) : NaN;
    if (pct > 0) natural = Math.round(natural * pct / 100);
    return Math.max(160, natural);
  }

  function apexSeries(data) {
    return (data.series || []).map(function (s) {
      return { name: s.name || "Series", data: s.values || [], color: s.color };
    });
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  /* Apex wants a category axis; the server already sends one label per point. */
  function buildOptions(mount, data, root) {
    var theme = ink();
    var labels = data.labels || [];
    var isBar = data.type === "bar";
    var height = chartHeight(mount);
    var weeks = data.bucket_starts || [];
    var endpoint = root ? root.getAttribute("data-week-endpoint") : "";
    var pressable = !!endpoint && weeks.length === labels.length;

    var options = {
      chart: {
        type: isBar ? "bar" : "line",
        height: height,
        width: "100%",
        fontFamily: "inherit",
        background: "transparent",
        toolbar: { show: false },
        zoom: { enabled: false },
        animations: {
          enabled: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
          dynamicAnimation: { enabled: false },
          speed: 220,
        },
        events: {},
      },
      series: apexSeries(data),
      colors: (data.series || []).map(function (s) { return s.color; }),
      labels: labels,
      dataLabels: { enabled: false },
      legend: { show: false },
      grid: {
        borderColor: theme.line,
        strokeDashArray: 0,
        xaxis: { lines: { show: false } },
        yaxis: { lines: { show: true } },
        padding: { left: 6, right: 6 },
      },
      stroke: isBar
        ? { show: false }
        : { curve: "smooth", width: 2.5, lineCap: "round" },
      markers: isBar
        ? { size: 0 }
        : { size: 3.5, strokeWidth: 0, hover: { size: 6 } },
      xaxis: {
        categories: labels,
        tickAmount: labels.length > 9 ? 9 : undefined,
        labels: {
          style: { colors: theme.slate, fontSize: "12px" },
          hideOverlappingLabels: true,
          trim: false,
        },
        axisBorder: { show: false },
        axisTicks: { show: false },
        tooltip: { enabled: false },
      },
      yaxis: {
        labels: {
          style: { colors: theme.slate, fontSize: "12px" },
          formatter: function (value) { return Math.round(value); },
        },
        forceNiceScale: true,
        min: 0,
      },
      tooltip: {
        theme: theme.dark ? "dark" : "light",
        shared: !isBar,
        intersect: isBar,
        followCursor: false,
        style: { fontSize: "12.5px", fontFamily: "inherit" },
        custom: function (ctx) { return tooltipHtml(data, ctx); },
      },
      plotOptions: isBar
        ? { bar: { columnWidth: "58%", borderRadius: 3, borderRadiusApplication: "end" } }
        : {},
    };

    if (pressable) {
      options.chart.cursor = "pointer";
      options.chart.events.dataPointSelection = function (event, ctx) {
        var index = ctx && typeof ctx.dataPointIndex === "number" ? ctx.dataPointIndex : event;
        if (root && root.__weekPress) {
          root.__weekPress(weeks[index], (data.tooltips && data.tooltips[index]) || "Week stories");
        }
      };
    }

    return options;
  }

  /* The placard's own HTML, so a tooltip carries the same figures (and the same
     step against the previous point) the SVG renderer showed. */
  function tooltipHtml(data, ctx) {
    var index = ctx && typeof ctx.dataPointIndex === "number" ? ctx.dataPointIndex : 0;
    var label = (data.labels || [])[index] || "";
    var rows = (data.series || []).map(function (s) {
      var values = s.values || [];
      var value = values[index] || 0;
      var delta = index > 0 ? value - (values[index - 1] || 0) : null;
      var tone = delta === null ? "" : delta > 0 ? " is-up" : delta < 0 ? " is-down" : " is-flat";
      var step = delta === null
        ? ""
        : '<span class="analytics-placard-delta' + tone + '">' + Math.abs(delta) + "</span>";
      return '<div class="analytics-placard-row">' +
        '<span class="analytics-placard-swatch" style="background:' + s.color + '"></span>' +
        '<span class="analytics-placard-name">' + escapeHtml(s.name) + "</span>" +
        '<span class="analytics-placard-value">' + value + "</span>" +
        step +
        "</div>";
    }).join("");
    return '<div class="analytics-apex-tip">' +
      '<div class="analytics-placard-label">' + escapeHtml(label) + "</div>" +
      rows +
      "</div>";
  }

  function available() {
    return typeof window.ApexCharts === "function";
  }

  /* Draw (or redraw) one chart. Returns true when ApexCharts took it, false
     when the caller should fall back to the SVG renderer. */
  function render(mount, data, root) {
    if (!mount || !available()) return false;
    if (!data || !(data.series || []).length || !(data.labels || []).length) return false;

    destroy(mount);
    var chart = new window.ApexCharts(mount, buildOptions(mount, data, root));
    chart.render();
    mount.__apex = chart;
    return true;
  }

  function destroy(mount) {
    if (mount && mount.__apex) {
      try { mount.__apex.destroy(); } catch (e) { /* already gone */ }
      mount.__apex = null;
    }
  }

  window.AnalyticsApex = {
    render: render,
    destroy: destroy,
    available: available,
    heightFor: chartHeight,
  };
})();
