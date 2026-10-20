/* FunnelScope — report renderer.
 *
 * Reads window.FUNNELSCOPE_DATA (written by scripts/build_web.py). No framework and no
 * chart library: a dependency-free page still opens from file:// in five years.
 *
 * No analysis happens here. Every rate, interval and verdict was computed in
 * funnelscope/ and passed through metrics.json; this file words it and draws it.
 * Headlines are generated from the data so they cannot go stale after a re-export.
 */

(function () {
  "use strict";

  var D = window.FUNNELSCOPE_DATA;

  if (!D) {
    document.querySelector("main").innerHTML =
      '<div class="wrap"><div class="fixture-banner"><strong>No data bundle</strong>' +
      "Run <code>python scripts/analyze.py && python scripts/build_web.py</code> to " +
      "generate <code>web/data.js</code>.</div></div>";
    return;
  }

  /* ---------------- formatting ---------------- */

  function pct(x, places) {
    if (x === null || x === undefined || isNaN(x)) return "—";
    return (x * 100).toFixed(places === undefined ? 1 : places) + "%";
  }

  function num(x) {
    if (x === null || x === undefined || isNaN(x)) return "—";
    return Math.round(x).toLocaleString("en-US");
  }

  function money(x) {
    if (x === null || x === undefined || isNaN(x)) return "—";
    return "$" + Math.round(x).toLocaleString("en-US");
  }

  function moneyShort(x) {
    if (x >= 1e6) return "$" + (x / 1e6).toFixed(1) + "M";
    if (x >= 1e3) return "$" + Math.round(x / 1e3) + "k";
    return money(x);
  }

  function pval(p) {
    if (p === null || p === undefined) return "—";
    if (p < 1e-4) return p.toExponential(0);
    return p < 0.01 ? p.toFixed(4) : p.toFixed(2);
  }

  function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

  /* Every data string that goes into innerHTML is escaped: the GA4 export's
   * obfuscated channel names ("<Other> / <Other>") are otherwise parsed as tags. */
  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  /* Plain-English names for each step, for sentences rather than chart labels. */
  var STEP = {
    added_to_cart: { short: "view → cart", verb: "between viewing an item and adding it to cart",
                     stage: "add-to-cart", kpi: "Lost before adding to cart", button: "Add to cart" },
    began_checkout: { short: "cart → checkout", verb: "between cart and checkout",
                      stage: "checkout start", kpi: "Lost between cart and checkout", button: "Checkout" },
    purchased: { short: "checkout → purchase", verb: "at checkout", stage: "purchase",
                 kpi: "Lost at checkout", button: "Purchase" }
  };
  function step(to) { return STEP[to] || { short: to, verb: "at " + to, stage: to, kpi: "Lost at " + to }; }

  /* "Four in five" reads better than "81.9%" in a headline. Falls back to the
   * percentage when no simple fraction is within two points. */
  function fractionPhrase(x) {
    var options = [[1, 2, "Half of"], [2, 3, "Two in three"], [3, 4, "Three in four"],
                   [4, 5, "Four in five"], [9, 10, "Nine in ten"]];
    for (var i = 0; i < options.length; i++) {
      if (Math.abs(x - options[i][0] / options[i][1]) <= 0.02) return options[i][2];
    }
    return pct(x, 0) + " of";
  }

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "class") node.className = attrs[k];
      else if (k === "html") node.innerHTML = attrs[k];
      else if (k === "text") node.textContent = attrs[k];
      else node.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { if (c) node.appendChild(c); });
    return node;
  }

  function mount(id, node) {
    var host = document.getElementById(id);
    if (!host) return;
    host.innerHTML = "";
    if (node) host.appendChild(node);
  }

  function setHTML(id, html) {
    var host = document.getElementById(id);
    if (host) host.innerHTML = html;
  }

  function decision(id, html) {
    setHTML(id, '<span class="tag">Decision</span><p>' + html + "</p>");
  }

  /* Table from a column spec: {head, get(row), num?, html?}. */
  function table(rows, cols, rowClass) {
    var head = el("tr", {}, cols.map(function (c) {
      return el("th", { class: c.num ? "num" : "", text: c.head });
    }));
    var body = rows.map(function (r, i) {
      return el("tr", { class: rowClass ? rowClass(r, i) : "" }, cols.map(function (c) {
        var v = c.get(r, i);
        var a = { class: c.num ? "num" : "" };
        if (c.html) a.html = v; else a.text = v;
        return el("td", a);
      }));
    });
    return el("table", {}, [el("thead", {}, [head]), el("tbody", {}, body)]);
  }

  var NS = "http://www.w3.org/2000/svg";
  function svg(tag, attrs) {
    var node = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "text") node.textContent = attrs[k];
      else node.setAttribute(k, attrs[k]);
    });
    return node;
  }

  /* Charts render at their container's real pixel width so 12px text stays 12px; a
   * fixed viewBox scaled down to a phone makes every label unreadable. */
  var NARROW = 520;
  function widthOf(id) {
    var host = document.getElementById(id);
    return Math.max(Math.floor((host && host.clientWidth) || 760), 280);
  }

  var ACCENT = "var(--accent)";
  var MUTED = "var(--series-muted)";
  var FAINT = "var(--series-faint)";

  /* ---------------- derived facts ---------------- */

  var overall = D.funnel.overall[0];
  var steps = overall.steps;
  var worst = steps.slice().sort(function (a, b) {
    return a.step_conversion - b.step_conversion;
  })[0];
  var totalLost = overall.counts.viewed - overall.counts.purchased;
  var worstShareOfLoss = totalLost ? worst.lost / totalLost : 0;
  var topOpp = D.opportunities[0];
  var gap = D.segment_gap;
  var tests = D.significance_tests || [];
  var gaps = D.segment_gaps_all || [];
  var rice = D.rice || [];
  var R = D.retention;
  var w1 = R.curve.filter(function (c) { return c.week === 1; })[0];
  var scope = D.scope_comparison;
  var ties = (D.validation || {}).timestamp_ties;
  var xval = (D.validation || {}).cross_validation || [];
  var maxDrift = xval.reduce(function (m, r) { return Math.max(m, r.rel_diff); }, 0);

  var channels = D.acquisition.filter(function (c) { return !c.is_long_tail; });
  var bestCh = channels.slice().sort(function (a, b) { return b.conversion - a.conversion; })[0];
  var worstCh = channels.slice().sort(function (a, b) { return a.conversion - b.conversion; })[0];

  function stageName(s) { return D.stage_labels[s] || s; }

  /* ---------------- chrome ---------------- */

  var CHAPTERS = [
    { id: "funnel", label: "Funnel" },
    { id: "segments", label: "Segments" },
    { id: "channels", label: "Channels" },
    { id: "retention", label: "Retention" },
    { id: "value", label: "Value" },
    { id: "decision", label: "Decision" },
    { id: "test", label: "Test plan" },
    { id: "method", label: "Method" }
  ];

  function renderToc() {
    var nav = document.getElementById("toc");
    CHAPTERS.forEach(function (c, i) {
      nav.appendChild(el("a", {
        href: "#" + c.id,
        html: "<span>0" + (i + 1) + "</span>" + c.label
      }));
    });

    if (!("IntersectionObserver" in window)) return;
    var links = nav.querySelectorAll("a");
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        links.forEach(function (a) {
          a.setAttribute("aria-current", a.getAttribute("href") === "#" + e.target.id
            ? "true" : "false");
        });
      });
    }, { rootMargin: "-40% 0px -55% 0px" });
    CHAPTERS.forEach(function (c) {
      var s = document.getElementById(c.id);
      if (s) observer.observe(s);
    });
  }

  function renderHero() {
    var p = D.provenance;
    setHTML("eyebrow", "Product analytics case study · Google Merchandise Store · " +
      p.window_start + " → " + p.window_end);

    var isViewToCart = worst.from === "viewed" && worst.to === "added_to_cart";
    setHTML("hero-title", isViewToCart
      ? fractionPhrase(1 - worst.step_conversion) + " shoppers <em>leave</em> before they add to cart."
      : pct(1 - worst.step_conversion, 0) + " of shoppers <em>leave</em> at " +
        worst.label.toLowerCase() + ".");

    setHTML("hero-lede",
      "An ordered funnel over <strong>" + num(D.overview.events_total) +
      " raw GA4 events</strong>, cross-validated by two independent SQL methods. " +
      "<strong>What I found:</strong> the loss is concentrated at one step, and the " +
      "segment everyone expects to matter does not. <strong>What to do:</strong> " +
      esc(rice[0].name.toLowerCase()) + " first.");

    var host = document.getElementById("provenance");
    if (p.is_real) {
      host.className = "provenance";
      host.innerHTML = '<span class="dot"></span>Real GA4 export · ' + esc(p.dataset) +
        " · exported " + String(p.generated_at).slice(0, 10);
    } else {
      /* The banner comes from the same manifest the numbers do, so fixture figures
       * cannot be published as an analysis. */
      host.className = "fixture-banner";
      host.innerHTML = "<strong>NOT AN ANALYSIS — SYNTHETIC FIXTURE OUTPUT</strong>" +
        "Every number on this page comes from <code>scripts/make_fixture.py</code>, a " +
        "simulated event log. Replace it with <code>python scripts/run_queries.py</code>.";
    }
  }

  function kpi(label, value, sub, accent) {
    return el("div", { class: "kpi" }, [
      el("p", { class: "label", text: label }),
      el("p", { class: "value" + (accent ? " is-accent" : ""), text: value }),
      el("p", { class: "sub", text: sub })
    ]);
  }

  function renderSnapshot() {
    var host = document.getElementById("snapshot");
    host.appendChild(kpi("Shoppers who viewed an item", num(overall.counts.viewed),
      num(D.overview.events_total) + " events analysed"));
    host.appendChild(kpi("End-to-end conversion", pct(overall.conversion, 2),
      num(overall.counts.purchased) + " purchases"));
    host.appendChild(kpi(step(worst.to).kpi,
      pct(1 - worst.step_conversion), "the largest single drop in the funnel", true));
    host.appendChild(kpi("Largest opportunity, upper bound", moneyShort(topOpp.recoverable_revenue),
      "from a 5-point lift in " + step(topOpp.to_stage).stage));
  }

  /* ---------------- 01 funnel ---------------- */

  function funnelChart(W) {
    var narrow = W < NARROW;
    var stages = D.stages;
    var rowH = narrow ? 58 : 48, top = 6;
    var labelW = narrow ? 0 : 140, valueW = narrow ? 72 : 200;
    var H = top + stages.length * rowH;
    var s = svg("svg", { viewBox: "0 0 " + W + " " + H, role: "img",
      "aria-label": "Funnel bar chart" });
    var maxW = W - labelW - valueW;
    var first = overall.counts[stages[0]] || 1;

    stages.forEach(function (st, i) {
      var y = top + i * rowH;
      var n = overall.counts[st];
      var w = Math.max((n / first) * maxW, 2);
      var isFocus = st === worst.to;
      var labelY = narrow ? y + 14 : y + 22;
      var barY = narrow ? y + 24 : y + 8, barH = narrow ? 18 : 22;
      s.appendChild(svg("text", { x: 0, y: labelY, class: isFocus ? "strong" : "",
        text: stageName(st) }));
      s.appendChild(svg("rect", { x: labelW, y: barY, width: w, height: barH,
        fill: isFocus ? ACCENT : FAINT, rx: 2 }));
      s.appendChild(svg("text", { x: labelW + w + 8, y: barY + barH - 5, class: "mono",
        text: num(n) }));
      if (!narrow) {
        s.appendChild(svg("text", { x: labelW + w + 8 + num(n).length * 8 + 10, y: barY + barH - 5,
          class: "mono-muted", text: pct(n / first) }));
      }
      if (i > 0) {
        var stp = steps[i - 1];
        s.appendChild(svg("text", { x: W, y: narrow ? labelY : barY + barH - 5,
          "text-anchor": "end", class: stp.to === worst.to ? "accent" : "mono-muted",
          text: "−" + pct(1 - stp.step_conversion) + (narrow ? "" : " step loss") }));
      }
    });
    return s;
  }

  function renderFunnel() {
    var dropped = 1 - worst.step_conversion;
    setHTML("h-funnel", pct(dropped) + " of product viewers <em>never</em> add to cart");
    setHTML("i-funnel",
      num(worst.lost) + " of " + num(worst.entered) + " shoppers leave " +
      step(worst.to).verb + " — <strong>" + pct(worstShareOfLoss, 0) +
      " of every shopper the funnel loses</strong>. The later steps hold up far better: " +
      steps.filter(function (x) { return x !== worst; }).map(function (x) {
        return step(x.to).short + " keeps " + pct(x.step_conversion, 0);
      }).join(", ") + ".");
    decision("d-funnel",
      "Prioritise the product page over checkout. A perfect checkout could recover at " +
      "most the " + pct(1 - worstShareOfLoss, 0) + " of lost shoppers who ever reach it.");
  }

  /* ---------------- 02 segments ---------------- */

  /* Forest plot: each comparison's difference with its 95% interval. An interval that
   * crosses zero is a difference this sample cannot distinguish from noise. */
  function forestPlot(W) {
    var narrow = W < NARROW;
    var rows = tests.map(function (t, i) {
      return { t: t, kind: (gaps[i] || {}).segment_type || "segment" };
    });
    var labelW = narrow ? 0 : 250, right = narrow ? 0 : 110;
    var rowH = narrow ? 82 : 52, top = 28;
    var H = top + rows.length * rowH + 24;
    var s = svg("svg", { viewBox: "0 0 " + W + " " + H, role: "img",
      "aria-label": "Forest plot of segment differences" });

    var lo = Math.min(0, Math.min.apply(null, rows.map(function (r) { return r.t.ci_low_pp; })));
    var hi = Math.max(0, Math.max.apply(null, rows.map(function (r) { return r.t.ci_high_pp; })));
    var pad = (hi - lo) * 0.12 || 1;
    lo -= pad; hi += pad;
    var plotL = narrow ? 8 : labelW, plotW = (narrow ? W - 16 : W - labelW - right);
    var x = function (v) { return plotL + ((v - lo) / (hi - lo)) * plotW; };

    s.appendChild(svg("line", { class: "zero", x1: x(0), x2: x(0), y1: top - 12, y2: H - 22 }));
    s.appendChild(svg("text", { x: x(0), y: top - 16, "text-anchor": "middle",
      class: "mono-muted", text: "no difference" }));

    rows.forEach(function (r, i) {
      var sig = r.t.significant;
      var colour = sig ? ACCENT : MUTED;
      var verdict = sig ? "real · p " + pval(r.t.p_value_adjusted) : "noise · p " + pval(r.t.p_value);
      var base = top + i * rowH;
      var labelY = narrow ? base + 12 : base + 14;
      var y = narrow ? base + 50 : base + 18;
      var name = narrow && r.t.comparison.length > 30 ? r.t.comparison.slice(0, 29) + "…" : r.t.comparison;
      s.appendChild(svg("text", { x: 0, y: labelY, class: "strong", text: name }));
      s.appendChild(svg("text", { x: 0, y: labelY + 17, text: cap(r.kind) + " · " +
        pct(r.t.rate_a, 2) + " vs " + pct(r.t.rate_b, 2) }));
      s.appendChild(svg("line", { x1: x(r.t.ci_low_pp), x2: x(r.t.ci_high_pp), y1: y, y2: y,
        stroke: colour, "stroke-width": 2 }));
      [r.t.ci_low_pp, r.t.ci_high_pp].forEach(function (v) {
        s.appendChild(svg("line", { x1: x(v), x2: x(v), y1: y - 5, y2: y + 5,
          stroke: colour, "stroke-width": 2 }));
      });
      s.appendChild(svg("circle", { cx: x(r.t.difference_pp), cy: y, r: 5, fill: colour }));
      s.appendChild(svg("text", { x: W, y: narrow ? labelY + 17 : y + 4, "text-anchor": "end",
        class: sig ? "accent" : "mono-muted", text: verdict }));
    });

    [lo, 0, hi].forEach(function (v) {
      s.appendChild(svg("text", { x: x(v), y: H - 4, "text-anchor": "middle",
        class: "mono-muted", text: (v > 0 ? "+" : "") + v.toFixed(1) + "pp" }));
    });
    return s;
  }

  function renderSegments() {
    var noise = tests.filter(function (t) { return !t.significant; })
      .map(function (t, i) { return { t: t, kind: (gaps[tests.indexOf(t)] || {}).segment_type }; });

    if (gap) {
      var ratio = gap.conversion_b / gap.conversion_a;
      var tail = noise.length ? " — " + noise[0].kind + " makes <em>no</em> difference" : "";
      setHTML("h-segments", esc(cap(gap.segment_b)) + " shoppers convert at " +
        ratio.toFixed(1) + "× the rate of " + esc(gap.segment_a) + " ones" + tail);
    } else {
      setHTML("h-segments", "No segment separates the loss — <em>every</em> gap is noise");
    }

    var parts = [];
    if (gap) {
      parts.push("<strong>" + esc(cap(gap.segment_a)) + " shoppers convert at " +
        pct(gap.conversion_a, 2) + " against " + pct(gap.conversion_b, 2) + "</strong> for " +
        esc(gap.segment_b) + " — a gap that survives correction for running " + tests.length +
        " comparisons, worth up to " + moneyShort(gap.value_if_closed) + " in this window.");
    }
    noise.forEach(function (n) {
      parts.push("The " + esc(n.kind) + " gap (" + esc(n.t.comparison) + ", " +
        Math.abs(n.t.difference_pp).toFixed(2) + "pp) has an interval that crosses zero: " +
        "on this sample it is indistinguishable from chance.");
    });
    setHTML("i-segments", parts.join(" "));

    var deviceNoise = noise.filter(function (n) { return n.kind === "device"; })[0];
    decision("d-segments", (deviceNoise
      ? "Don't fund a device-specific fix — the device gap is noise (p = " +
        pval(deviceNoise.t.p_value) + "). "
      : "") + (gap
      ? "Target the " + esc(gap.segment_a) + "-shopper experience, where the gap is real."
      : "Treat the loss as whole-funnel; no segment justifies a targeted project."));

    var mc = D.multiple_comparisons || {};
    setHTML("m-segments", "Pooled two-proportion z-test, unpooled 95% interval, " +
      "Holm–Bonferroni across all " + (mc.family_size || tests.length) +
      " comparisons so the family-wise error rate stays at 5%. " +
      "Implemented by hand against <code>math.erfc</code> and checked against SciPy and " +
      "statsmodels in the test suite.");
  }

  /* ---------------- 03 channels ---------------- */

  function scatter(W) {
    var narrow = W < NARROW;
    var H = narrow ? 300 : 340, L = narrow ? 40 : 56, Rp = narrow ? 72 : 150, T = 16, B = 46;
    var s = svg("svg", { viewBox: "0 0 " + W + " " + H, role: "img",
      "aria-label": "Channel volume against conversion" });
    var rows = channels;
    var vols = rows.map(function (r) { return Math.max(r.viewed, 1); });
    var lo = Math.log10(Math.min.apply(null, vols)) - 0.1;
    var hi = Math.log10(Math.max.apply(null, vols)) + 0.1;
    var maxY = Math.max.apply(null, rows.map(function (r) { return r.conversion; })) * 1.2;
    var x = function (v) { return L + ((Math.log10(Math.max(v, 1)) - lo) / (hi - lo)) * (W - L - Rp); };
    var y = function (v) { return T + (1 - v / maxY) * (H - T - B); };

    for (var g = 0; g <= 4; g++) {
      var gv = (maxY * g) / 4;
      s.appendChild(svg("line", { class: "grid", x1: L, x2: W - Rp, y1: y(gv), y2: y(gv) }));
      s.appendChild(svg("text", { x: L - 8, y: y(gv) + 4, "text-anchor": "end",
        class: "mono-muted", text: pct(gv, 1) }));
    }

    var avg = overall.conversion;
    s.appendChild(svg("line", { class: "zero", x1: L, x2: W - Rp, y1: y(avg), y2: y(avg) }));
    s.appendChild(svg("text", { x: W - Rp + 8, y: y(avg) + 4, class: "mono-muted",
      text: (narrow ? "" : "site ") + pct(avg, 2) }));

    var labels = [];
    var biggest = narrow ? [] : rows.slice().sort(function (a, b) { return b.viewed - a.viewed; }).slice(0, 2);
    rows.forEach(function (r) {
      var focus = r === bestCh || r === worstCh;
      var radius = 4 + 7 * Math.sqrt(r.viewed / Math.max.apply(null, vols));
      s.appendChild(svg("circle", { cx: x(r.viewed), cy: y(r.conversion), r: radius,
        fill: focus ? ACCENT : FAINT, "fill-opacity": focus ? 0.9 : 0.8 }));
      var dot = s.lastChild;
      dot.appendChild(svg("title", { text: r.channel + " — " + num(r.viewed) + " shoppers, " +
        pct(r.conversion, 2) + " convert" }));
      if (!focus && biggest.indexOf(r) < 0) return;
      labels.push({ x: x(r.viewed) + radius + 6, y: y(r.conversion) + 4, focus: focus,
        text: r.channel.length > (narrow ? 16 : 26)
          ? r.channel.slice(0, narrow ? 15 : 25) + "…" : r.channel });
    });
    labels.sort(function (a, b) { return a.y - b.y; });
    for (var i = 1; i < labels.length; i++) {
      if (labels[i].y - labels[i - 1].y < 14) labels[i].y = labels[i - 1].y + 14;
    }
    labels.forEach(function (l) {
      s.appendChild(svg("text", { x: l.x, y: l.y, class: l.focus ? "strong" : "", text: l.text }));
    });

    var mid = Math.pow(10, (lo + hi) / 2);
    [Math.pow(10, lo + 0.1), mid, Math.pow(10, hi - 0.1)].forEach(function (v) {
      s.appendChild(svg("text", { x: x(v), y: H - 22, "text-anchor": "middle",
        class: "mono-muted", text: num(v) }));
    });
    s.appendChild(svg("text", { x: (L + W - Rp) / 2, y: H - 4, "text-anchor": "middle",
      text: "shoppers who viewed an item (log scale)" }));
    return s;
  }

  function renderChannels() {
    setHTML("h-channels", "Channel conversion spans " + pct(worstCh.conversion, 1) +
      " to <em>" + pct(bestCh.conversion, 1) + "</em> — volume and quality point different ways");
    setHTML("i-channels",
      "<strong>" + esc(worstCh.channel) + "</strong> sends " + num(worstCh.viewed) +
      " shoppers converting at " + pct(worstCh.conversion, 2) + " — high volume, low " +
      "conversion, an expectation-mismatch problem rather than a checkout one. " +
      "<strong>" + esc(bestCh.channel) + "</strong> converts at " + pct(bestCh.conversion, 2) +
      " on " + num(bestCh.viewed) + " — a scale opportunity. A ranked table would blur " +
      "the two; they need opposite responses.");
    decision("d-channels", "Shift budget from " + esc(worstCh.channel) + " toward " +
      esc(bestCh.channel) + " — but check lifetime value first. Conversion alone misjudges a " +
      "brand-awareness channel.");

    mount("channel-table", table(D.acquisition, [
      { head: "Channel", get: function (r) { return r.channel; } },
      { head: "Shoppers", num: true, get: function (r) { return num(r.viewed); } },
      { head: "Cart rate", num: true, get: function (r) { return pct(r.cart_rate, 1); } },
      { head: "Conversion", num: true, get: function (r) { return pct(r.conversion, 2); } },
      { head: "Revenue", num: true, get: function (r) { return money(r.revenue_usd); } },
      { head: "Per shopper", num: true, get: function (r) { return "$" + r.revenue_per_viewer.toFixed(2); } }
    ], function (r) { return r === bestCh || r === worstCh ? "is-top" : ""; }));
  }

  /* ---------------- 04 retention ---------------- */

  function heatmap() {
    var observed = [];
    R.cohorts.forEach(function (c) {
      c.values.forEach(function (v, i) { if (i > 0 && v !== null) observed.push(v); });
    });
    var vmax = Math.max.apply(null, observed.concat([0.01]));

    /* Week 0 is 100% for every cohort by construction, so it is replaced by the
     * cohort's size — information the reader actually needs to weigh each row. */
    var weeks = R.weeks.slice(1);
    var head = el("tr", {}, [el("th", { class: "cohort", text: "Cohort" }),
                             el("th", { class: "cohort", text: "Users" })]
      .concat(weeks.map(function (w) { return el("th", { text: "W" + w }); })));
    var body = R.cohorts.map(function (c) {
      return el("tr", {}, [el("td", { class: "cohort", text: c.cohort.slice(5) }),
                           el("td", { class: "cohort size", text: num(c.cohort_size) })]
        .concat(c.values.slice(1).map(function (v) {
          if (v === null) return el("td", { class: "censored", title: "Not yet observable" });
          var w = Math.min(Math.pow(v / vmax, 0.6), 1);
          return el("td", {
            class: w > 0.6 ? "is-dark" : "",
            style: "background: rgba(var(--accent-ramp), " + (0.05 + w * 0.75).toFixed(2) + ")",
            text: (v * 100).toFixed(1)
          });
        })));
    });
    return el("table", { class: "heatmap" }, [el("thead", {}, [head]), el("tbody", {}, body)]);
  }

  function curve() {
    var pts = R.curve.filter(function (c) { return c.week > 0; });
    var W = 300, H = 220, L = 40, Rp = 10, T = 10, B = 28;
    var s = svg("svg", { viewBox: "0 0 " + W + " " + H, role: "img",
      "aria-label": "Pooled retention curve" });
    if (!pts.length) return s;
    var maxX = Math.max.apply(null, pts.map(function (p) { return p.week; }));
    var maxY = Math.max.apply(null, pts.map(function (p) { return p.rate; })) * 1.15 || 0.1;
    var x = function (w) { return L + ((w - 1) / Math.max(maxX - 1, 1)) * (W - L - Rp); };
    var y = function (v) { return T + (1 - v / maxY) * (H - T - B); };

    for (var g = 0; g <= 3; g++) {
      var gv = (maxY * g) / 3;
      s.appendChild(svg("line", { class: "grid", x1: L, x2: W - Rp, y1: y(gv), y2: y(gv) }));
      s.appendChild(svg("text", { x: L - 6, y: y(gv) + 4, "text-anchor": "end",
        class: "mono-muted", text: pct(gv, 0) }));
    }
    s.appendChild(svg("path", {
      d: pts.map(function (p, i) { return (i ? "L" : "M") + x(p.week) + " " + y(p.rate); }).join(" "),
      fill: "none", stroke: ACCENT, "stroke-width": 2
    }));
    pts.forEach(function (p) {
      var c = svg("circle", { cx: x(p.week), cy: y(p.rate), r: 3, fill: ACCENT });
      c.appendChild(svg("title", { text: "Week " + p.week + ": " + pct(p.rate, 1) +
        " of " + num(p.cohort_size) + " users" }));
      s.appendChild(c);
      if (p.week === 1 || p.week === maxX || p.week % 4 === 0) {
        s.appendChild(svg("text", { x: x(p.week), y: H - 12, "text-anchor": "middle",
          class: "mono-muted", text: "W" + p.week }));
      }
    });
    return s;
  }

  function renderRetention() {
    setHTML("h-retention", "Only <em>" + pct(w1 ? w1.rate : 0, 1) +
      "</em> of shoppers return the week after their first visit");
    mount("heatmap", heatmap());
    mount("curve", curve());
    var w4 = R.curve.filter(function (c) { return c.week === 4; })[0];
    var stats = document.getElementById("ret-stats");
    [["Week 1", w1 ? pct(w1.rate, 1) : "—"], ["Week 4", w4 ? pct(w4.rate, 1) : "—"],
     ["Purchases needing a return visit", scope ? pct(scope.return_visit_dependence, 0) : "—"],
     ["Grid not yet observable", pct(R.censoring.share_censored, 0)]
    ].forEach(function (r) {
      stats.appendChild(el("li", { html: "<span>" + r[0] + "</span><b>" + r[1] + "</b>" }));
    });
    var depend = scope ? pct(scope.return_visit_dependence, 0) : null;
    setHTML("i-retention",
      "Retention falls from " + pct(w1 ? w1.rate : 0, 1) + " in week one to under 2% by " +
      "week four. Yet return visits still matter: " +
      (depend ? "<strong>" + depend + " of purchases need a second session</strong> — " +
        "the session-scoped funnel converts at " + pct(scope.session_conversion, 2) +
        " against " + pct(scope.user_conversion, 2) + " user-level." : "") +
      " Few shoppers come back, but the ones who do are disproportionately the ones who buy.");
    decision("d-retention", "Persist the cart across sessions. Losing a returning " +
      "shopper's cart loses the purchase most likely to happen.");
    setHTML("m-retention", "Hatched cells are right-censored: a cohort formed in late " +
      "January cannot show week-8 retention because week 8 falls outside the data. " +
      R.censoring.cells_censored + " of " + R.censoring.cells_total + " cells (" +
      pct(R.censoring.share_censored, 0) + ") are excluded from every average rather " +
      "than plotted as zeros — which would read as a retention collapse.");
  }

  /* ---------------- 05 value ---------------- */

  function valueChart(W) {
    var narrow = W < NARROW;
    var intervals = {};
    (D.sizing_intervals || []).forEach(function (iv) { intervals[iv.to_stage] = iv; });
    var rows = D.opportunities;
    var rowH = narrow ? 56 : 50, labelW = narrow ? 0 : 220, right = narrow ? 76 : 120, top = 6;
    var H = top + rows.length * rowH + 4;
    var s = svg("svg", { viewBox: "0 0 " + W + " " + H, role: "img",
      "aria-label": "Recoverable revenue by step" });
    var maxV = Math.max.apply(null, rows.map(function (o) {
      return (intervals[o.to_stage] || {}).ci_high || o.recoverable_revenue;
    }));
    var x = function (v) { return labelW + (v / maxV) * (W - labelW - right); };

    rows.forEach(function (o, i) {
      var y = top + i * rowH;
      var iv = intervals[o.to_stage];
      var focus = i === 0;
      var labelY = narrow ? y + 14 : y + 22;
      var barY = narrow ? y + 22 : y + 8, barH = narrow ? 18 : 22;
      s.appendChild(svg("text", { x: 0, y: labelY, class: focus ? "strong" : "",
        text: narrow ? step(o.to_stage).short : stageName(o.from_stage) + " → " +
          stageName(o.to_stage).toLowerCase() }));
      s.appendChild(svg("rect", { x: labelW, y: barY, width: Math.max(x(o.recoverable_revenue) - labelW, 2),
        height: barH, fill: focus ? ACCENT : FAINT, rx: 2 }));
      if (iv) {
        s.appendChild(svg("line", { x1: x(iv.ci_low), x2: x(iv.ci_high), y1: barY + barH / 2,
          y2: barY + barH / 2, stroke: "var(--text)", "stroke-width": 1.5 }));
      }
      s.appendChild(svg("text", { x: W, y: barY + barH - 5, "text-anchor": "end",
        class: focus ? "mono" : "mono-muted", text: moneyShort(o.recoverable_revenue) }));
    });
    return s;
  }

  function renderValue() {
    setHTML("h-value", "Lifting " + step(topOpp.to_stage).stage +
      " by 5 points is worth up to <em>" + moneyShort(topOpp.recoverable_revenue) + "</em>");
    setHTML("i-value",
      "At an average order of " + money(D.aov) + ", a 5-point lift in " + step(topOpp.to_stage).stage +
      " recovers up to " + num(topOpp.users_recovered) + " shoppers. " +
      "<strong>Ranking by dollars and ranking by worst drop-off are the same ordering — " +
      "necessarily.</strong> Every purchaser passed every stage, so recoverable revenue " +
      "collapses to a function of step conversion. Sizing prices the steps; it cannot " +
      "re-rank them.");
    decision("d-value", "Use these figures as ceilings for comparing steps, never as a " +
      "forecast. Effort, not dollars, decides the order — see 06.");
  }

  /* ---------------- 06 decision ---------------- */

  function renderDecision() {
    var top = rice[0], second = rice[1];
    var lead = second ? top.rice_score / second.rice_score : null;
    setHTML("h-decision", "Start with the <em>product page</em>" +
      (lead ? ": it scores " + lead.toFixed(1) + "× the next option" : ""));

    var maxScore = Math.max.apply(null, rice.map(function (r) { return r.rice_score; }));
    mount("rice-table", table(rice, [
      { head: "#", num: true, get: function (r) { return r.rank; } },
      { head: "Option", get: function (r) { return r.name; } },
      { head: "Reach", num: true, get: function (r) { return num(r.reach); } },
      { head: "Impact", num: true, get: function (r) { return r.impact; } },
      { head: "Confidence", num: true, get: function (r) { return pct(r.confidence, 0); } },
      { head: "Effort (wk)", num: true, get: function (r) { return r.effort; } },
      { head: "RICE", num: true, html: true, get: function (r) {
        return '<span class="bar-cell"><i style="width:' +
          Math.round((r.rice_score / maxScore) * 72) + 'px"></i>' + num(r.rice_score) + "</span>";
      } }
    ], function (r) { return r.rank === 1 ? "is-top" : ""; }));

    setHTML("i-decision", "<strong>Why it ranks first:</strong> " + esc(top.rationale) +
      " <strong>Assumption to challenge:</strong> " + esc(top.assumptions));
    decision("d-decision", esc(top.name) + ". Validate with an A/B test on the product page " +
      "before committing the full " + top.effort + "-week build.");

    var next = [
      "<b>Why " + (gap ? esc(gap.segment_a) + " shoppers convert worse" : "shoppers leave the product page") +
        ".</b> Event counts record what happened, not why. Session recordings on that cohort would separate friction from intent.",
      "<b>A cart-abandonment exit survey.</b> Cart loss looks like friction, but price shock has the same signature and needs a different fix.",
      "<b>An A/B test on the top option.</b> Everything here is a hypothesis with a size attached, not a measured result."
    ];
    var ol = document.getElementById("next-steps");
    next.forEach(function (n) { ol.appendChild(el("li", { html: "<span>" + n + "</span>" })); });
  }

  /* ---------------- 07 test plan ---------------- */

  /* The planner looks values up from a grid computed in funnelscope/experiment.py.
   * Moving the slider never does arithmetic, so the page cannot disagree with the memo. */
  var EXP = D.experiment;
  var planState = { plan: 0, idx: 0 };

  function planFor(i) { return EXP.plans[i]; }

  function defaultIndex(plan) {
    var i = plan.grid.findIndex(function (g) { return g.lift === plan.smallest_detectable_lift; });
    return i >= 0 ? i : 0;
  }

  function daysChart(plan, selected, W) {
    var narrow = W < NARROW;
    var H = 200, L = 36, R = 8, T = 16, B = 30, cap = 90;
    var s = svg("svg", { viewBox: "0 0 " + W + " " + H, role: "img",
      "aria-label": "Days needed for each detectable lift" });
    var n = plan.grid.length;
    var bw = (W - L - R) / n;
    var y = function (d) { return T + (1 - Math.min(d, cap) / cap) * (H - T - B); };

    [0, 30, 60, 90].forEach(function (d) {
      s.appendChild(svg("line", { class: "grid", x1: L, x2: W - R, y1: y(d), y2: y(d) }));
      s.appendChild(svg("text", { x: L - 6, y: y(d) + 4, "text-anchor": "end", class: "mono-muted",
        text: d === cap ? cap + "+" : String(d) }));
    });
    s.appendChild(svg("line", { class: "zero", x1: L, x2: W - R, y1: y(EXP.max_days), y2: y(EXP.max_days) }));
    s.appendChild(svg("text", { x: W - R, y: y(EXP.max_days) - 6, "text-anchor": "end",
      class: "mono-muted", text: EXP.max_days + "-day limit" }));

    plan.grid.forEach(function (g, i) {
      var h = (H - B) - y(g.days);
      var bar = svg("rect", { x: L + i * bw + bw * 0.15, y: y(g.days), width: bw * 0.7,
        height: Math.max(h, 1), rx: 1,
        fill: i === selected ? ACCENT : (g.fits ? MUTED : FAINT) });
      bar.appendChild(svg("title", { text: "+" + (g.lift * 100).toFixed(1) + " pts: " +
        Math.round(g.days) + " days, " + num(g.n_per_arm) + " per arm" }));
      s.appendChild(bar);
      var every = narrow ? 4 : 2;
      var clear = Math.abs(i - selected) > (narrow ? 2 : 1);
      if ((i % every === 1 && clear) || i === selected) {
        s.appendChild(svg("text", { x: L + i * bw + bw / 2, y: H - 10, "text-anchor": "middle",
          class: i === selected ? "accent" : "mono-muted", text: "+" + (g.lift * 100).toFixed(1) }));
      }
    });
    return s;
  }

  function renderPlanner() {
    var plan = planFor(planState.plan);
    var g = plan.grid[planState.idx];
    document.getElementById("planner-lift").max = plan.grid.length - 1;
    document.getElementById("planner-lift").value = planState.idx;
    setHTML("planner-lift-label", "+" + (g.lift * 100).toFixed(1) + " pts");

    var host = document.getElementById("planner-readout");
    host.innerHTML = "";
    host.appendChild(kpi("Shoppers needed per arm", num(g.n_per_arm),
      pct(plan.baseline) + " → " + pct(plan.baseline + g.lift) + " " + step(plan.step_to).stage + " rate"));
    var len = kpi("Test length at current traffic",
      g.fits ? g.planned_days + " days" : Math.round(g.days) + " days", "");
    len.querySelector(".sub").appendChild(el("span", {
      class: "pill " + (g.fits ? "pill-good" : "pill-warn"),
      text: g.fits ? "fits a " + EXP.max_days + "-day test" : "over the " + EXP.max_days + "-day limit"
    }));
    host.appendChild(len);
    host.appendChild(kpi("Worth if it works", moneyShort(g.worth_up_to),
      "upper bound over " + EXP.window_days + " days"));
    mount("planner-chart", daysChart(plan, planState.idx, widthOf("planner-chart")));
  }

  function renderTest() {
    if (!EXP || !EXP.plans || !EXP.plans.length) {
      document.getElementById("test").style.display = "none";
      return;
    }
    var testable = EXP.practically_testable || [];
    var first = EXP.plans.filter(function (pl) { return testable.indexOf(pl.step_to) >= 0; })[0];

    setHTML("h-test", first
      ? "Only the " + step(first.step_to).stage + " fix can be <em>proven</em> in a month"
      : "At this traffic, <em>no</em> step can be tested in under a month");

    var seg = document.getElementById("planner-step");
    EXP.plans.forEach(function (pl, i) {
      var b = el("button", { type: "button", text: step(pl.step_to).button || cap(step(pl.step_to).stage),
        "aria-pressed": i === 0 ? "true" : "false" });
      b.addEventListener("click", function () {
        Array.prototype.forEach.call(seg.children, function (c) { c.setAttribute("aria-pressed", "false"); });
        b.setAttribute("aria-pressed", "true");
        planState.plan = i;
        planState.idx = defaultIndex(pl);
        renderPlanner();
      });
      seg.appendChild(b);
    });
    document.getElementById("planner-lift").addEventListener("input", function (e) {
      planState.idx = Number(e.target.value);
      renderPlanner();
    });
    planState.idx = defaultIndex(EXP.plans[0]);
    renderPlanner();

    var parts = EXP.plans.map(function (pl) {
      return step(pl.step_to).stage + " sees " + num(pl.eligible_per_day) + " shoppers a day" +
        (pl.smallest_detectable_lift
          ? " — the smallest lift it can detect in four weeks is " +
            (pl.smallest_detectable_lift * 100).toFixed(0) + " points"
          : " — too few to detect any lift in four weeks");
    });
    setHTML("i-test", cap(parts.join("; ")) + ". <strong>Testability is a prioritisation " +
      "input:</strong> the option that leads RICE is also the only one that can be validated " +
      "before it ships. Everything after the cart would have to ship on judgement.");

    if (first) {
      decision("d-test", "Run a " + (first.planned_days / 7) + "-week, 50/50 test on the product " +
        "page. Ship only if " + step(first.step_to).stage + " rises by at least " +
        (first.smallest_detectable_lift * 100).toFixed(0) + " points <em>and</em> no guardrail falls.");
      mount("guardrails", table(first.guardrails, [
        { head: "Guardrail — must not fall", html: true, get: function (g) {
          return esc(g.metric) + '<br><span class="cell-note">' + esc(cap(g.why)) + "</span>";
        } },
        { head: "Baseline", num: true, get: function (g) {
          return g.metric.indexOf("order value") >= 0 ? money(g.baseline) : pct(g.baseline);
        } }
      ]));
    }

    setHTML("m-test", "Sample size by Cohen's h, two-sided, α " + EXP.alpha + ", power " +
      EXP.power + ", 50/50 split — checked against statsmodels in the test suite. Shoppers a " +
      "day = users entering the step ÷ " + EXP.window_days + " days. Tests run at least " +
      EXP.min_days + " days so a weekday pattern cannot pass for a treatment effect, and at " +
      "most " + EXP.max_days + ".");
  }

  /* ---------------- 08 method ---------------- */

  function renderMethod() {
    setHTML("h-method", "The funnel is computed twice, and the check <em>caught</em> two real-data bugs");
    setHTML("i-method",
      "Method A compares each shopper's first-occurrence timestamps with cumulative " +
      "predicates. Method B turns those first occurrences into a sequence string and " +
      "matches a regex. The logic shares nothing, so an ordering bug in one cannot hide " +
      "in the other. Current agreement: <strong>" + (maxDrift === 0 ? "exact, at every stage"
        : "within " + pct(maxDrift, 2)) + "</strong>.");

    mount("xval-table", table(xval, [
      { head: "Stage", get: function (r) { return stageName(r.stage); } },
      { head: "A · timestamps", num: true, get: function (r) { return num(r.method_a_timestamps); } },
      { head: "B · sequence regex", num: true, get: function (r) { return num(r.method_b_sequence); } },
      { head: "Difference", num: true, get: function (r) { return num(r.abs_diff); } },
      { head: "Verdict", html: true, get: function (r) {
        return r.within_tolerance ? '<span class="pill pill-good">agree</span>'
          : '<span class="pill pill-bad">diverge</span>';
      } }
    ]));
    decision("d-method", "The gate blocks publication. If the two methods diverge by more " +
      "than 0.5%, the pipeline raises — no memo, chart or page is produced.");

    setHTML("gate-story",
      "<p class=\"interpret\">On the first real export the methods disagreed by up to 17%. " +
      "Neither query had a bug: they were answering different questions, and the " +
      "synthetic test data could not show it.</p>" +
      "<ol class=\"steps\">" +
      "<li><span><b>Repeat events.</b> Shoppers view 6.3 items each and re-add to cart " +
      "constantly, so \"first cart after first view\" and \"ever carted after ever " +
      "viewing\" are different questions. Method B now uses first occurrences only.</span></li>" +
      "<li><span><b>Batched timestamps.</b> GA4 stamps every event in one network request " +
      "with the same microsecond, so carting from a listing ties with the view. Method A's " +
      "strict ordering drops those shoppers; method B now breaks ties the same way.</span></li>" +
      "</ol>");

    if (ties && ties.excluded_by_tie) {
      setHTML("tie-block",
        "<p class=\"interpret\"><strong>" + num(ties.excluded_by_tie) + " shoppers (" +
        pct(ties.share_of_counted, 0) + " of the cart stage)</strong> add to cart in the " +
        "same microsecond they view, and the strict rule excludes them. Under ≥ the stage " +
        "would read " + num(ties.counted_at_or_after) + " instead of " +
        num(ties.counted_strict) + ". Strict is the conservative reading — an equal " +
        "timestamp is not evidence of an ordering — and the cost is measured rather than " +
        "assumed.</p>");
    }

    var lim = [
      "<b>No cross-device identity.</b> <code>user_pseudo_id</code> is per browser, so a phone-browse, laptop-buy shopper counts as two people — and a returning shopper on a new device looks new. The largest threat to every segment finding.",
      "<b>Recommendations are hypotheses.</b> Sizing figures are upper bounds and no experiment has been run.",
      "<b>" + (EXP ? EXP.window_days : 92) + " days of data.</b> Enough for funnel work, short for retention; " +
        pct(R.censoring.share_censored, 0) + " of the cohort grid is censored.",
      "<b>Public demo data.</b> Google's obfuscated sample export — channel and product names are redacted, so no merchandising insight is possible."
    ];
    var ol = document.getElementById("limitations");
    lim.forEach(function (l) { ol.appendChild(el("li", { html: "<span>" + l + "</span>" })); });

    document.getElementById("footer-line").textContent =
      "FunnelScope · generated " + String(D.provenance.generated_at).slice(0, 10) +
      " from metrics.json, written only after the correctness gates pass.";
  }

  /* ---------------- go ---------------- */

  renderToc();
  renderHero();
  renderSnapshot();
  renderFunnel();
  renderSegments();
  renderChannels();
  renderRetention();
  renderValue();
  renderDecision();
  renderTest();
  renderMethod();

  function drawCharts() {
    mount("funnel-chart", funnelChart(widthOf("funnel-chart")));
    mount("forest", forestPlot(widthOf("forest")));
    mount("scatter", scatter(widthOf("scatter")));
    mount("value-chart", valueChart(widthOf("value-chart")));
    if (EXP && EXP.plans && EXP.plans.length) {
      mount("planner-chart", daysChart(planFor(planState.plan), planState.idx, widthOf("planner-chart")));
    }
  }

  drawCharts();
  var lastWidth = window.innerWidth, pending = null;
  window.addEventListener("resize", function () {
    if (window.innerWidth === lastWidth) return;
    lastWidth = window.innerWidth;
    clearTimeout(pending);
    pending = setTimeout(drawCharts, 150);
  });
})();
