/* ANALYTICS chart renderer.
   The page shell holds no numbers: each chart is an htmx GET that returns an
   HTML fragment carrying the data as a JSON <script> plus an empty SVG mount.
   This file reads that JSON and draws a plain SVG chart (no chart library),
   then re-runs whenever htmx swaps a fragment in.

   The chart is drawn in real CSS pixels rather than a fixed 920x400 box: the
   viewBox is set to the measured width of the mount, so an axis label is 12px
   on a phone exactly as it is on a desktop (a fixed viewBox scaled down to a
   phone width made every label about 5px tall). A resize/orientation change
   re-draws at the new width. */
(function () {
  "use strict";

  var SVG_NS = "http://www.w3.org/2000/svg";
  var DESKTOP_H = 400;          /* plot height on a wide screen */
  var COMPACT_H = 250;          /* taller relative plot on a phone */
  var COMPACT_W = 560;          /* mount widths under this use the compact frame */
  var MIN_W = 220;              /* unmeasurable mount: fall back to the wide frame */
  var FALLBACK_W = 920;
  var GRID_INTERVALS = 5;       /* horizontal gridlines above the baseline */
  var MAX_X_LABELS = 9;         /* never crowd the x-axis past this many labels */
  var LABEL_ROOM = 58;          /* rough px a date label needs, incl. its gap */

  var DESKTOP_MARGIN = { top: 24, right: 18, bottom: 52, left: 52 };
  var COMPACT_MARGIN = { top: 14, right: 12, bottom: 42, left: 40 };

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

  /* The drawing frame: measured width, an adaptive height and the matching
     margin. Small screens get a tighter margin (fewer wasted pixels) and a
     relatively taller plot so the lines are not squashed into a sliver. */
  function frameFor(host) {
    var w = host ? Math.round(host.clientWidth) : 0;
    if (!w || w < MIN_W) w = FALLBACK_W;
    var compact = w < COMPACT_W;
    return {
      w: w,
      h: compact ? COMPACT_H : DESKTOP_H,
      margin: compact ? COMPACT_MARGIN : DESKTOP_MARGIN,
      compact: compact
    };
  }

  function plotBox(frame) {
    return {
      w: frame.w - frame.margin.left - frame.margin.right,
      h: frame.h - frame.margin.top - frame.margin.bottom
    };
  }

  /* Thin the x labels to what the width can actually carry. */
  function labelStride(count, plotW) {
    var room = Math.floor(plotW / LABEL_ROOM);
    var maxLabels = Math.max(3, Math.min(MAX_X_LABELS, room));
    return count <= maxLabels ? 1 : Math.ceil(count / maxLabels);
  }

  /* Keep the first and last ticks from overhanging the plot edges. */
  function xAnchor(index, count) {
    if (count <= 1) return "middle";
    if (index === 0) return "start";
    if (index === count - 1) return "end";
    return "middle";
  }

  function svgClass(frame) {
    return "analytics-svg" + (frame.compact ? " analytics-svg--compact" : "");
  }

  function emptySvg(label, frame) {
    var svg = svgEl("svg", { viewBox: "0 0 " + frame.w + " " + frame.h, "class": svgClass(frame), role: "img", "aria-label": label });
    svg.appendChild(svgText(frame.w / 2, frame.h / 2, "No data for this selection.", "analytics-empty", "middle"));
    return svg;
  }

  function newSvg(label, frame) {
    return svgEl("svg", { viewBox: "0 0 " + frame.w + " " + frame.h, "class": svgClass(frame), role: "img", "aria-label": label });
  }

  function drawAxes(svg, max, frame, box) {
    var m = frame.margin;
    for (var i = 0; i <= GRID_INTERVALS; i++) {
      var y = m.top + box.h - (box.h * i / GRID_INTERVALS);
      svg.appendChild(svgEl("line", {
        x1: m.left, y1: y,
        x2: m.left + box.w, y2: y,
        "class": "analytics-gridline" + (i === 0 ? " analytics-gridline--base" : "")
      }));
      svg.appendChild(svgText(m.left - 8, y + 4, String(Math.round(max * i / GRID_INTERVALS)), "analytics-axis-label analytics-axis-label--y", "end"));
    }
  }

  function renderBar(host, data, root) {
    var values = (data.series && data.series[0] ? data.series[0].values : []) || [];
    var count = values.length;
    var frame = frameFor(host);
    if (!count) { host.appendChild(emptySvg("Stories published per week", frame)); return; }

    var box = plotBox(frame);
    var m = frame.margin;
    var max = axisMax(Math.max.apply(null, values.concat([0])));
    var svg = newSvg("Stories published per week", frame);
    drawAxes(svg, max, frame, box);

    var slot = box.w / count;
    var barW = Math.max(Math.min(slot * 0.6, 56), 3);
    var stride = labelStride(count, box.w);
    var colour = data.series[0].color || "#2563eb";
    /* Counts above a bar need room; drop them once the bars get thin. */
    var showValues = slot >= 22;
    /* Bars are only pressable when the fragment carried one week per bar and
       a week endpoint to fetch that week's stories from. */
    var weeks = data.bucket_starts || [];
    var endpoint = root ? root.getAttribute("data-week-endpoint") : "";
    var pressable = !!endpoint && weeks.length === count;

    for (var i = 0; i < count; i++) {
      var value = values[i] || 0;
      var height = max ? (box.h * value / max) : 0;
      var x = m.left + slot * i + (slot - barW) / 2;
      var y = m.top + box.h - height;
      var tipText = (data.tooltips && data.tooltips[i]) || (data.labels[i] + ": " + value);
      var rect = svgEl("rect", {
        x: x, y: y, width: barW,
        height: Math.max(height, value > 0 ? 2 : 0),
        rx: 4, "class": "analytics-bar", fill: colour
      });
      var tip = svgEl("title");
      tip.textContent = tipText;
      rect.appendChild(tip);

      if (pressable) {
        rect.setAttribute("class", "analytics-bar analytics-bar--pressable");
        rect.setAttribute("tabindex", "0");
        rect.setAttribute("role", "button");
        rect.setAttribute("data-week", weeks[i]);
        rect.setAttribute("aria-label", tipText + ". Opens this week's stories.");
      }
      svg.appendChild(rect);

      if (value > 0 && showValues) {
        svg.appendChild(svgText(x + barW / 2, y - 7, String(value), "analytics-bar-value", "middle"));
      }
      if (i % stride === 0 || i === count - 1) {
        var lx = m.left + slot * i + slot / 2;
        svg.appendChild(svgText(lx, m.top + box.h + 22, data.labels[i], "analytics-axis-label analytics-axis-label--x", xAnchor(i, count)));
      }
    }
    if (pressable && root) attachWeekPress(svg, root);
    host.appendChild(svg);
  }

  /* ---------- Point placard ---------- */
  /* A pressed or tapped point opens a small placard listing every ENABLED
     series at that intersection (only enabled series are ever drawn, so the
     data already holds exactly the ticked boxes). The placard lives inside the
     .analytics-chart root, which is position:relative, and is
     pointer-events:none so it can never steal the hover back from the dot it
     describes. On a phone the whole chart is a tap target: a press snaps to
     the nearest intersection instead of demanding a hit on a tiny dot. */

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  /* The step against the previous dot. Colour carries the direction (green up,
     red down), so only the size is written. The first point has no
     predecessor, so it gets nothing at all. */
  function deltaLabel(delta) {
    return String(Math.abs(delta));
  }

  function deltaHtml(delta) {
    if (delta === null) return "";
    var tone = delta > 0 ? " is-up" : delta < 0 ? " is-down" : " is-flat";
    return '<span class="analytics-placard-delta' + tone + '">' + escapeHtml(deltaLabel(delta)) + "</span>";
  }

  function placardFor(root) {
    var placard = root.querySelector(".analytics-placard");
    if (!placard) {
      placard = document.createElement("div");
      placard.className = "analytics-placard";
      placard.setAttribute("role", "status");
      placard.hidden = true;
      root.appendChild(placard);
    }
    return placard;
  }

  function hidePlacard(root) {
    var placard = root.querySelector(".analytics-placard");
    if (!placard) return;
    placard.classList.remove("is-visible");
    window.setTimeout(function () {
      if (!placard.classList.contains("is-visible")) placard.hidden = true;
    }, 200);
  }

  function showPlacard(root, svg, index) {
    var meta = svg.__placard;
    if (!meta || !(index >= 0 && index < meta.count)) return;
    var data = meta.data;

    var placard = placardFor(root);
    var html = '<div class="analytics-placard-label">' + escapeHtml((data.labels || [])[index] || "") + "</div>";
    (data.series || []).forEach(function (s) {
      var values = s.values || [];
      var value = values[index] || 0;
      var hasPrevious = index > 0 && index - 1 < values.length;
      var delta = hasPrevious ? value - (values[index - 1] || 0) : null;
      html += '<div class="analytics-placard-row">' +
        '<span class="analytics-placard-swatch" style="background:' + escapeHtml(s.color) + '"></span>' +
        '<span class="analytics-placard-name">' + escapeHtml(s.name) + "</span>" +
        '<span class="analytics-placard-value">' + escapeHtml(value) + "</span>" +
        deltaHtml(delta) +
        "</div>";
    });
    placard.innerHTML = html;
    placard.hidden = false;
    placard.classList.remove("is-visible");

    /* anchor on the highest point at that intersection, so the placard clears
       the lines of every enabled series */
    var x = meta.margin.left + (meta.count > 1 ? meta.stepX * index : meta.plotW / 2);
    var y = meta.margin.top + meta.plotH;
    (data.series || []).forEach(function (s) {
      var value = (s.values && s.values[index]) || 0;
      var py = meta.margin.top + meta.plotH - (meta.max ? meta.plotH * value / meta.max : 0);
      if (py < y) y = py;
    });

    var svgRect = svg.getBoundingClientRect();
    var rootRect = root.getBoundingClientRect();
    var scale = svgRect.width / meta.viewW;
    var pointX = (svgRect.left - rootRect.left) + x * scale;
    var pointY = (svgRect.top - rootRect.top) + y * scale;

    placard.style.visibility = "hidden";
    var width = placard.offsetWidth;
    var height = placard.offsetHeight;
    var left = Math.max(4, Math.min(pointX - width / 2, rootRect.width - width - 4));
    var top = pointY - height - 14;
    if (top < 0) top = pointY + 16;
    placard.style.left = left + "px";
    placard.style.top = top + "px";
    placard.style.visibility = "";
    requestAnimationFrame(function () { placard.classList.add("is-visible"); });
  }

  function indexFromEvent(svg, event) {
    var meta = svg.__placard;
    if (!meta || meta.count <= 1) return 0;
    var rect = svg.getBoundingClientRect();
    var x = (event.clientX - rect.left) * (meta.viewW / rect.width);
    return Math.max(0, Math.min(meta.count - 1, Math.round((x - meta.margin.left) / meta.stepX)));
  }

  function attachPlacard(svg, root) {
    function hoveredDot(event) {
      return event.target && event.target.closest ? event.target.closest(".analytics-dot") : null;
    }
    svg.addEventListener("click", function (event) {
      showPlacard(root, svg, indexFromEvent(svg, event));
    });
    svg.addEventListener("mouseover", function (event) {
      if (hoveredDot(event)) showPlacard(root, svg, indexFromEvent(svg, event));
    });
    /* bind once per root: the svg is rebuilt on every resize, the root is not */
    if (!root.__placardBound) {
      root.__placardBound = true;
      root.addEventListener("mouseleave", function () { hidePlacard(root); });
    }
  }

  function renderLine(host, data, root) {
    var series = data.series || [];
    var labels = data.labels || [];
    var count = labels.length;
    var frame = frameFor(host);
    if (!series.length || !count) { host.appendChild(emptySvg("Trend lines", frame)); return; }

    var box = plotBox(frame);
    var m = frame.margin;
    var all = [];
    series.forEach(function (s) { all = all.concat(s.values || []); });
    var max = axisMax(Math.max.apply(null, all.concat([0])));

    var svg = newSvg("Trend lines for the selected series", frame);
    drawAxes(svg, max, frame, box);

    var stepX = count > 1 ? box.w / (count - 1) : 0;
    var stride = labelStride(count, box.w);
    for (var i = 0; i < count; i++) {
      if (i % stride !== 0 && i !== count - 1) continue;
      var lx = m.left + (count > 1 ? stepX * i : box.w / 2);
      svg.appendChild(svgText(lx, m.top + box.h + 22, labels[i], "analytics-axis-label analytics-axis-label--x", xAnchor(i, count)));
    }

    series.forEach(function (s) {
      var values = s.values || [];
      var points = values.map(function (value, i) {
        var x = m.left + (count > 1 ? stepX * i : box.w / 2);
        var y = m.top + box.h - (max ? box.h * value / max : 0);
        return [x, y];
      });
      var d = points.map(function (p, i) { return (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1); }).join(" ");
      svg.appendChild(svgEl("path", { d: d, fill: "none", stroke: s.color, "stroke-width": 2.5, "class": "analytics-line" }));
      points.forEach(function (p) {
        svg.appendChild(svgEl("circle", { cx: p[0], cy: p[1], r: 3, fill: s.color, "class": "analytics-dot" }));
      });
    });

    svg.__placard = {
      data: data, count: count, stepX: stepX,
      plotW: box.w, plotH: box.h, max: max,
      margin: m, viewW: frame.w, viewH: frame.h
    };
    attachPlacard(svg, root);
    host.appendChild(svg);
  }

  function renderChart(root, force) {
    if (!force && root.getAttribute("data-rendered") === "1") return;
    var canvas = root.querySelector("[data-chart-canvas]");
    var script = root.querySelector('script[type="application/json"]');
    if (!canvas || !script) return;

    var data;
    try { data = JSON.parse(script.textContent); } catch (e) { return; }

    root.setAttribute("data-rendered", "1");
    canvas.innerHTML = "";
    var stalePlacard = root.querySelector(".analytics-placard");
    if (stalePlacard) stalePlacard.remove();
    if (data.type === "line") renderLine(canvas, data, root);
    else renderBar(canvas, data, root);

    var body = root.parentElement;
    while (body && !body.classList.contains("analytics-chart-body")) { body = body.parentElement; }
    if (body) body.setAttribute("aria-busy", "false");
  }

  function renderAll() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-chart]"), function (root) {
      renderChart(root, false);
    });
  }

  /* Redraw at the new width after a resize or a phone rotation. Debounced so a
     drag of the window does not redraw on every frame. */
  var resizeTimer = null;
  function redrawAll() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-chart]"), function (root) {
      renderChart(root, true);
    });
  }
  function onViewportChange() {
    if (resizeTimer) window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(redrawAll, 150);
  }

  document.addEventListener("DOMContentLoaded", renderAll);
  /* htmx swaps a fresh, unrendered [data-chart] into the page; the
     data-rendered guard makes a full rescan cheap and idempotent. */
  document.addEventListener("htmx:afterSwap", renderAll);
  document.addEventListener("htmx:afterSettle", renderAll);

  /* An aria-live fragment body starts out aria-busy while its first load is in
     flight, but nothing ever cleared it: the region stayed busy forever, so a
     screen reader skipped the very figures it was waiting for. Busy is raised
     again on the real swap target whenever a refresh goes out, and dropped as
     soon as the new markup lands. Charts also clear their own body once drawn,
     which this makes redundant rather than conflicting. */
  document.addEventListener("htmx:configRequest", function (event) {
    var target = event.detail && event.detail.target;
    if (target && target.hasAttribute && target.hasAttribute("aria-busy")) {
      target.setAttribute("aria-busy", "true");
    }
  });
  document.addEventListener("htmx:afterSettle", function (event) {
    var target = event.detail && event.detail.elt;
    if (target && target.hasAttribute && target.hasAttribute("aria-busy")) {
      target.setAttribute("aria-busy", "false");
    }
  });

  window.addEventListener("resize", onViewportChange);
  window.addEventListener("orientationchange", onViewportChange);

  /* a press outside a chart closes any open placard (a tap on the chart
     itself keeps it open, so a phone reader can read it without the pointer
     disappearing on them) */
  document.addEventListener("click", function (event) {
    Array.prototype.forEach.call(document.querySelectorAll("[data-chart]"), function (root) {
      if (!root.contains(event.target)) hidePlacard(root);
    });
  });

  var WEEK_DIALOG_ID = "analytics-week";
  var WEEK_TOAST_ID = "analytics-week-toast";

  function initTrendRange() {}

  function ensureWeekDialog() {
    var d = document.getElementById(WEEK_DIALOG_ID);
    if (d) return d;
    d = document.createElement("div");
    d.id = WEEK_DIALOG_ID;
    d.className = "analytics-week-dialog";
    d.setAttribute("role", "dialog");
    d.setAttribute("aria-modal", "true");
    d.setAttribute("aria-labelledby", WEEK_DIALOG_ID + "-title");
    d.hidden = true;
    d.innerHTML =
      '<div class="analytics-week-backdrop" data-week-close></div>' +
      '<div class="analytics-week-content" role="document">' +
        '<header class="analytics-week-header">' +
          '<h3 class="analytics-week-title" id="' + WEEK_DIALOG_ID + '-title"></h3>' +
          '<button type="button" class="analytics-week-close" data-week-close aria-label="Close">&times;</button>' +
        '</header>' +
        '<div class="analytics-week-body" data-week-body></div>' +
        '<div class="analytics-week-footer">' +
          '<button type="button" class="analytics-week-btn" data-week-close>Close</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(d);
    return d;
  }

  function ensureWeekToast() {
    var t = document.getElementById(WEEK_TOAST_ID);
    if (t) return t;
    t = document.createElement("div");
    t.id = WEEK_TOAST_ID;
    t.className = "analytics-toast";
    t.setAttribute("role", "status");
    t.setAttribute("aria-live", "polite");
    t.hidden = true;
    document.body.appendChild(t);
    return t;
  }

  function showWeekToast(msg) {
    var t = ensureWeekToast();
    t.textContent = msg || "";
    t.hidden = false;
    clearTimeout(t._hide);
    t._hide = setTimeout(function () { t.hidden = true; }, 2200);
  }

  function closeWeekDialog() {
    if (window._weekTrap) { window._weekTrap.release(); window._weekTrap = null; }
    var d = document.getElementById(WEEK_DIALOG_ID);
    if (d) d.hidden = true;
    if (window._weekLastFocus && window._weekLastFocus.focus) { window._weekLastFocus.focus(); window._weekLastFocus = null; }
  }

  function trapFocus(dialog) {
    var focusables = dialog.querySelectorAll('a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])');
    if (!focusables.length) return { release: function () {} };
    var first = focusables[0];
    var last = focusables[focusables.length - 1];
    function onKey(e) {
      if (e.key === "Escape") { e.preventDefault(); closeWeekDialog(); return; }
      if (e.key === "Tab") {
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    }
    dialog.addEventListener("keydown", onKey);
    first.focus();
    return { release: function () { dialog.removeEventListener("keydown", onKey); } };
  }

  function openWeekDialog(title, html) {
    var d = ensureWeekDialog();
    d.querySelector("#" + WEEK_DIALOG_ID + "-title").textContent = title || "Week stories";
    d.querySelector("[data-week-body]").innerHTML = html;
    window._weekLastFocus = document.activeElement;
    d.hidden = false;
    /* release a trap from a previous open/retry before installing a new one */
    if (window._weekTrap) { window._weekTrap.release(); window._weekTrap = null; }
    window._weekTrap = trapFocus(d);
    /* one delegated handler for close and retry (bound once on the dialog) */
    if (!d._actionsBound) {
      d._actionsBound = true;
      d.addEventListener("click", function (ev) {
        if (ev.target.closest && ev.target.closest("[data-week-close]")) { closeWeekDialog(); return; }
        if (ev.target.closest && ev.target.closest("[data-week-retry]")) {
          var week = d._week;
          if (week) fetchWeekStories(d._weekRoot, week, d._weekHint).catch(function () {});
        }
      });
    }
  }

  function fetchWeekStories(root, week, labelHint) {
    var endpoint = root ? root.getAttribute("data-week-endpoint") : "";
    if (!endpoint) return Promise.reject(new Error("no-endpoint"));
    var url = new URL(endpoint, window.location.origin);
    url.searchParams.set("week", week);
    var controller = new AbortController();
    var timeout = setTimeout(function () { controller.abort(); }, 8000);
    /* Open the dialog straight away with a skimmer in the body, so a tap
       always shows something immediately instead of a dead pause. */
    openWeekDialog(labelHint || "Week stories", weekSkimmerHtml());
    var d = document.getElementById(WEEK_DIALOG_ID);
    if (d) { d._weekRoot = root; d._week = week; d._weekHint = labelHint; }
    return fetch(url, { headers: { "X-Requested-With": "fetch" }, signal: controller.signal })
      .then(function (r) { clearTimeout(timeout); if (!r.ok) throw new Error(String(r.status)); return r.text(); })
      .then(function (html) { setWeekBody(html); })
      .catch(function (err) {
        clearTimeout(timeout);
        setWeekBody('<p class="analytics-week-error">Couldn\'t load this week. <button type="button" class="analytics-week-retry" data-week-retry>Retry</button></p>');
        throw err;
      });
  }

  /* A small shimmer body shown while the week's stories are fetched. */
  function weekSkimmerHtml() {
    var row =
      '<div class="analytics-week-skel-item" aria-hidden="true">' +
        '<div class="analytics-week-skel-bar"></div>' +
        '<div class="analytics-week-skel-bar is-short"></div>' +
      "</div>";
    return '<div class="analytics-week-skimmer">' + row + row + row + "</div>";
  }

  function setWeekBody(html) {
    var d = document.getElementById(WEEK_DIALOG_ID);
    if (!d) return;
    d.querySelector("[data-week-body]").innerHTML = html;
  }

  function attachWeekPress(svg, root) {
    if (!svg || svg._weekBound) return;
    svg._weekBound = true;
    svg.addEventListener("click", function (ev) {
      var btn = ev.target.closest && ev.target.closest(".analytics-bar--pressable");
      if (!btn) return;
      var week = btn.getAttribute("data-week");
      var tip = btn.querySelector("title");
      var hint = tip ? tip.textContent : "Week";
      fetchWeekStories(root, week, hint).catch(function (err) {
        showWeekToast(err && err.name === "AbortError" ? "Week stories took too long. Retry." : "Couldn't load week stories. Retry.");
      });
    });
    svg.addEventListener("keydown", function (ev) {
      var btn = ev.target.closest && ev.target.closest(".analytics-bar--pressable");
      if (!btn) return;
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); btn.click(); }
    });
  }

  window.AnalyticsCharts = { render: renderAll, redraw: redrawAll };

  /* ---------- Slow-network loading state ---------- */
  /* Every chart lives in an .analytics-chart-body. On a slow link the old
     chart would otherwise sit there unchanged until the new fragment lands,
     so a reader cannot tell whether their change took. Marking the body
     is-loading the instant a request starts (and clearing it on swap, settle
     or any error) makes every section acknowledge the change immediately.
     On an error htmx leaves the target untouched, so clearing the class
     simply reveals the previous chart again. */
  function chartBodyOf(el) {
    return el && el.classList && el.classList.contains("analytics-chart-body") ? el : null;
  }
  function setChartLoading(el, isLoading) {
    if (!el) return;
    el.classList.toggle("is-loading", isLoading);
    el.setAttribute("aria-busy", isLoading ? "true" : "false");
  }
  document.addEventListener("htmx:beforeRequest", function (event) {
    setChartLoading(chartBodyOf(event.detail.target), true);
  });
  ["htmx:afterSwap", "htmx:afterSettle", "htmx:responseError", "htmx:sendError", "htmx:timeout"].forEach(function (name) {
    document.addEventListener(name, function (event) {
      setChartLoading(chartBodyOf(event.detail.target), false);
    });
  });

  /* ---------- Story performance picker ---------- */
  /* Pressing a search result records the story id in the form's hidden field,
     shows the title, clears the list and asks the form to load that story's
     chart. Kept in JS rather than a submit button so the search box's own
     change event can never masquerade as a story choice. */
  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest(".analytics-story-result");
    if (!button) return;
    var form = button.closest("form");
    if (!form) return;

    var field = form.querySelector('input[name="story"]');
    if (field) field.value = button.getAttribute("data-story") || "";
    var chosen = form.querySelector("[data-story-chosen]");
    if (chosen) {
      chosen.innerHTML = "Showing <strong>" + button.getAttribute("data-story-title") + "</strong>";
    }
    var results = document.getElementById("analytics-story-results");
    if (results) results.innerHTML = "";

    if (form.requestSubmit) form.requestSubmit();
    else if (window.htmx) window.htmx.trigger(form, "submit");
  });

  /* ---------- "How this works" guide ---------- */
  /* A bottom-docked coach rail: the rail itself never covers the page, and each
     step scrolls its target into view and rings it, so the guide explains each
     figure while showing it. Steps are read from the DOM in order -- anything
     carrying data-guide-title becomes a step, a whole card or a single figure
     inside one -- so the wording lives next to what it describes. Much of that
     data arrives in htmx fragments, so the list is rebuilt each time the guide
     opens rather than frozen at first paint. Motion is spring-y on purpose;
     prefers-reduced-motion turns it off. */
  (function () {
    var guide = document.querySelector("[data-guide]");
    if (!guide) return;

    var openers = Array.prototype.slice.call(document.querySelectorAll("[data-guide-open]"));
    var headingEl = guide.querySelector("[data-guide-heading]");
    var bodyEl = guide.querySelector("[data-guide-body]");
    var stepEl = guide.querySelector("[data-guide-step]");
    var mainEl = guide.querySelector("[data-guide-main]");
    var dotsEl = guide.querySelector("[data-guide-dots]");
    var prevBtn = guide.querySelector("[data-guide-prev]");
    var nextBtn = guide.querySelector("[data-guide-next]");
    var closeBtn = guide.querySelector(".analytics-guide-close");
    var sections = [];
    var index = 0;
    var lastFocus = null;
    var reduceMotion = window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    function collectSections() {
      sections = Array.prototype.slice.call(document.querySelectorAll("[data-guide-title]"));
    }

    function buildDots() {
      if (!dotsEl) return;
      dotsEl.innerHTML = "";
      sections.forEach(function (_, i) {
        var dot = document.createElement("button");
        dot.type = "button";
        dot.className = "analytics-guide-dot";
        dot.setAttribute("aria-label", "Go to step " + (i + 1));
        dot.addEventListener("click", function () { goTo(i); });
        dotsEl.appendChild(dot);
      });
    }

    function scrollToSection(section) {
      var top = section.getBoundingClientRect().top + window.pageYOffset - 92;
      window.scrollTo({ top: Math.max(top, 0), behavior: reduceMotion ? "auto" : "smooth" });
    }

    function render() {
      var section = sections[index];
      if (!section) return;
      if (stepEl) stepEl.textContent = "Step " + (index + 1) + " of " + sections.length;
      if (headingEl) headingEl.textContent = section.getAttribute("data-guide-title") || "";
      if (bodyEl) bodyEl.textContent = section.getAttribute("data-guide-text") || "";

      sections.forEach(function (s) { s.classList.toggle("is-guided", s === section); });
      Array.prototype.forEach.call(dotsEl ? dotsEl.children : [], function (dot, i) {
        dot.classList.toggle("is-active", i === index);
        dot.setAttribute("aria-current", i === index ? "true" : "false");
      });

      if (prevBtn) prevBtn.disabled = index === 0;
      if (nextBtn) nextBtn.textContent = index === sections.length - 1 ? "Done" : "Next";

      if (mainEl) {
        mainEl.classList.remove("is-enter");
        void mainEl.offsetWidth; /* reflow so the step animation replays */
        mainEl.classList.add("is-enter");
      }
      scrollToSection(section);
    }

    function goTo(next) {
      if (!sections.length) return;
      index = Math.max(0, Math.min(sections.length - 1, next));
      render();
    }

    function onKey(event) {
      if (event.key === "Escape") { event.preventDefault(); close(); }
      else if (event.key === "ArrowRight") { event.preventDefault(); goTo(index + 1); }
      else if (event.key === "ArrowLeft") { event.preventDefault(); goTo(index - 1); }
    }

    function open() {
      collectSections();
      if (!sections.length) return;
      buildDots();
      lastFocus = document.activeElement;
      guide.hidden = false;
      index = 0;
      render();
      if (closeBtn) closeBtn.focus();
      document.addEventListener("keydown", onKey);
    }

    function close() {
      guide.hidden = true;
      sections.forEach(function (s) { s.classList.remove("is-guided"); });
      document.removeEventListener("keydown", onKey);
      if (lastFocus && lastFocus.focus) lastFocus.focus();
    }

    openers.forEach(function (button) { button.addEventListener("click", open); });
    Array.prototype.forEach.call(guide.querySelectorAll("[data-guide-close]"), function (button) {
      button.addEventListener("click", close);
    });
    if (prevBtn) prevBtn.addEventListener("click", function () { goTo(index - 1); });
    if (nextBtn) nextBtn.addEventListener("click", function () {
      if (index === sections.length - 1) close();
      else goTo(index + 1);
    });
  })();
})();
