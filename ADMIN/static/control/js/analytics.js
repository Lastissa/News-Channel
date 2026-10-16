/* ANALYTICS chart renderer.
   The page shell holds no numbers: each chart is an htmx GET that returns an
   HTML fragment carrying the data as a JSON <script> plus an empty SVG mount.
   This file reads that JSON and draws a plain SVG chart (no chart library),
   then re-runs whenever htmx swaps a fragment in. */
(function () {
  "use strict";

  var SVG_NS = "http://www.w3.org/2000/svg";
  var VIEW_W = 920;
  var VIEW_H = 400;
  var GRID_INTERVALS = 5;      /* horizontal gridlines above the baseline */
  var MAX_X_LABELS = 9;        /* thin x labels past this many buckets */
  var MARGIN = { top: 24, right: 18, bottom: 52, left: 52 };

  function svgEl(name, attrs) {
    var node = document.createElementNS(SVG_NS, name);
    if (attrs) {
      for (var key in attrs) {
        if (Object.prototype.hasOwnProperty.call(attrs, key)) {
          node.setAttribute(key, attrs[key]);
        }
      }
    }
    return node;
  }

  function svgText(x, y, value, className, anchor) {
    var node = svgEl("text", { x: x, y: y, "class": className });
    if (anchor) node.setAttribute("text-anchor", anchor);
    node.textContent = value;
    return node;
  }

  /* Round a raw tick size up to a "nice" whole number so the y-axis labels
     never come out as fractions for integer counts. */
  function niceStep(step) {
    if (step <= 1) return 1;
    var magnitude = Math.pow(10, Math.floor(Math.log10(step)));
    var residual = step / magnitude;
    var factor = residual <= 1 ? 1 : residual <= 2 ? 2 : residual <= 5 ? 5 : 10;
    return Math.round(factor * magnitude);
  }

  function axisMax(maxValue) {
    if (!maxValue || maxValue <= 0) return GRID_INTERVALS;
    return niceStep(Math.ceil(maxValue / GRID_INTERVALS)) * GRID_INTERVALS;
  }

  function labelStride(count) {
    return count <= MAX_X_LABELS ? 1 : Math.ceil(count / MAX_X_LABELS);
  }

  function emptySvg(label) {
    var svg = svgEl("svg", { viewBox: "0 0 " + VIEW_W + " " + VIEW_H, "class": "analytics-svg", role: "img", "aria-label": label });
    svg.appendChild(svgText(VIEW_W / 2, VIEW_H / 2, "No data for this selection.", "analytics-empty", "middle"));
    return svg;
  }

  function newSvg(label) {
    return svgEl("svg", { viewBox: "0 0 " + VIEW_W + " " + VIEW_H, "class": "analytics-svg", role: "img", "aria-label": label });
  }

  function drawAxes(svg, max, plotW, plotH) {
    for (var i = 0; i <= GRID_INTERVALS; i++) {
      var y = MARGIN.top + plotH - (plotH * i / GRID_INTERVALS);
      svg.appendChild(svgEl("line", {
        x1: MARGIN.left, y1: y,
        x2: MARGIN.left + plotW, y2: y,
        "class": "analytics-gridline" + (i === 0 ? " analytics-gridline--base" : "")
      }));
      svg.appendChild(svgText(MARGIN.left - 10, y + 4, String(Math.round(max * i / GRID_INTERVALS)), "analytics-axis-label analytics-axis-label--y", "end"));
    }
  }

  function renderBar(host, data) {
    var values = (data.series && data.series[0] ? data.series[0].values : []) || [];
    var count = values.length;
    if (!count) { host.appendChild(emptySvg("Stories published per week")); return; }

    var plotW = VIEW_W - MARGIN.left - MARGIN.right;
    var plotH = VIEW_H - MARGIN.top - MARGIN.bottom;
    var max = axisMax(Math.max.apply(null, values.concat([0])));
    var svg = newSvg("Stories published per week");
    drawAxes(svg, max, plotW, plotH);

    var slot = plotW / count;
    var barW = Math.max(Math.min(slot * 0.6, 56), 3);
    var stride = labelStride(count);
    var colour = data.series[0].color || "#2563eb";

    for (var i = 0; i < count; i++) {
      var value = values[i] || 0;
      var height = max ? (plotH * value / max) : 0;
      var x = MARGIN.left + slot * i + (slot - barW) / 2;
      var y = MARGIN.top + plotH - height;
      var rect = svgEl("rect", {
        x: x, y: y, width: barW,
        height: Math.max(height, value > 0 ? 2 : 0),
        rx: 4, "class": "analytics-bar", fill: colour
      });
      var tip = svgEl("title");
      tip.textContent = (data.tooltips && data.tooltips[i]) || (data.labels[i] + ": " + value);
      rect.appendChild(tip);
      svg.appendChild(rect);

      if (value > 0) {
        svg.appendChild(svgText(x + barW / 2, y - 7, String(value), "analytics-bar-value", "middle"));
      }
      if (i % stride === 0 || i === count - 1) {
        svg.appendChild(svgText(x + barW / 2, MARGIN.top + plotH + 22, data.labels[i], "analytics-axis-label analytics-axis-label--x", "middle"));
      }
    }
    host.appendChild(svg);
  }

  function renderLine(host, data) {
    var series = data.series || [];
    var labels = data.labels || [];
    var count = labels.length;
    if (!series.length || !count) { host.appendChild(emptySvg("Trend lines")); return; }

    var plotW = VIEW_W - MARGIN.left - MARGIN.right;
    var plotH = VIEW_H - MARGIN.top - MARGIN.bottom;
    var all = [];
    series.forEach(function (s) { all = all.concat(s.values || []); });
    var max = axisMax(Math.max.apply(null, all.concat([0])));

    var svg = newSvg("Trend lines for the selected series");
    drawAxes(svg, max, plotW, plotH);

    var stepX = count > 1 ? plotW / (count - 1) : 0;
    var stride = labelStride(count);
    for (var i = 0; i < count; i++) {
      if (i % stride !== 0 && i !== count - 1) continue;
      var lx = MARGIN.left + (count > 1 ? stepX * i : plotW / 2);
      svg.appendChild(svgText(lx, MARGIN.top + plotH + 22, labels[i], "analytics-axis-label analytics-axis-label--x", "middle"));
    }

    series.forEach(function (s) {
      var values = s.values || [];
      var points = values.map(function (value, i) {
        var x = MARGIN.left + (count > 1 ? stepX * i : plotW / 2);
        var y = MARGIN.top + plotH - (max ? plotH * value / max : 0);
        return [x, y];
      });
      var d = points.map(function (p, i) { return (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1); }).join(" ");
      svg.appendChild(svgEl("path", { d: d, fill: "none", stroke: s.color, "stroke-width": 2.5, "class": "analytics-line" }));
      points.forEach(function (p, i) {
        var dot = svgEl("circle", { cx: p[0], cy: p[1], r: 3, fill: s.color, "class": "analytics-dot" });
        var tip = svgEl("title");
        tip.textContent = s.name + " \u2014 " + labels[i] + ": " + values[i];
        dot.appendChild(tip);
        svg.appendChild(dot);
      });
    });
    host.appendChild(svg);
  }

  function renderChart(root) {
    if (root.getAttribute("data-rendered") === "1") return;
    var canvas = root.querySelector("[data-chart-canvas]");
    var script = root.querySelector('script[type="application/json"]');
    if (!canvas || !script) return;

    var data;
    try { data = JSON.parse(script.textContent); } catch (e) { return; }

    root.setAttribute("data-rendered", "1");
    canvas.innerHTML = "";
    if (data.type === "line") renderLine(canvas, data);
    else renderBar(canvas, data);

    var body = root.parentElement;
    while (body && !body.classList.contains("analytics-chart-body")) { body = body.parentElement; }
    if (body) body.setAttribute("aria-busy", "false");
  }

  function renderAll() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-chart]"), renderChart);
  }

  document.addEventListener("DOMContentLoaded", renderAll);
  /* htmx swaps a fresh, unrendered [data-chart] into the page; the
     data-rendered guard makes a full rescan cheap and idempotent. */
  document.addEventListener("htmx:afterSwap", renderAll);
  document.addEventListener("htmx:afterSettle", renderAll);

  window.AnalyticsCharts = { render: renderAll };
})();
