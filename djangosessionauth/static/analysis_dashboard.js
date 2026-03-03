/* ================================================================
   analysis_dashboard.js — A³ Resume Intelligence
   Reads window.ATS_DATA (Django template → script tag) and
   parses #typing-output (rendered by render_analysis_html) to
   populate every dashboard card without touching the backend.

   Depends on: Chart.js 4.x loaded before this script.
   ================================================================ */

(function () {
  "use strict";

  /* ── Shortcuts ───────────────────────────────────────────── */
  const $  = id  => document.getElementById(id);
  const mk = (tag, cls) => {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    return el;
  };
  const clamp = (n, lo, hi) => Math.min(Math.max(n, lo), hi);

  /* ── Section-detection regexes (match render_analysis_html h3 text) */
  const SEC_RE = {
    matched:     /matched\s*(skills?|keywords?)?/i,
    missing:     /missing\s*(skills?|keywords?)?/i,
    weak:        /weak\s*(alignment)?/i,
    improvement: /improvement/i,
  };

  /* ================================================================
     BOOT
  ================================================================ */
  function boot() {
    const data = window.ATS_DATA || { score: 0, breakdown: {} };

    animateRing(data.score);
    animateBreakdownBars();
    setScoreTier(data.score);

    /* give the browser one frame to render #typing-output */
    requestAnimationFrame(() => {
      const parsed = parseAnalysisHTML();
      populateMatchedCloud(parsed.matched);
      populateMissingCloud(parsed.missing);
      populateWarnList(parsed.weak);
      populateImpList(parsed.improvements);
      updateChips(parsed);
      buildBreakdownChart(data.breakdown);
      buildSkillsDonut(parsed.matched.length, parsed.missing.length);
      wireSkillsTabs();
      wireRawToggle();
    });
  }

  document.readyState === "loading"
    ? document.addEventListener("DOMContentLoaded", boot)
    : boot();

  /* ================================================================
     SCORE RING
  ================================================================ */
  function animateRing(score) {
    const fill  = document.querySelector(".rf");
    const numEl = $("ring-num");
    if (!fill || !numEl) return;

    const circ   = 2 * Math.PI * 80;   /* r = 80 */
    const target = clamp(Number(score) || 0, 0, 100);
    const offset = circ - (target / 100) * circ;

    fill.style.strokeDasharray  = circ;
    fill.style.strokeDashoffset = circ;

    /* double rAF ensures transition fires */
    requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        fill.style.strokeDashoffset = offset;
      })
    );

    /* counter animation */
    let cur = 0;
    const step = target / 70;
    function tick() {
      cur += step;
      if (cur < target) { numEl.textContent = cur.toFixed(1); requestAnimationFrame(tick); }
      else               { numEl.textContent = target.toFixed(1); }
    }
    setTimeout(tick, 250);
  }

  /* ================================================================
     SCORE TIER BADGE
  ================================================================ */
  function setScoreTier(score) {
    const el = $("score-tier");
    if (!el) return;
    const s = Number(score) || 0;
    let label, color;
    if      (s >= 80) { label = "Excellent  ★★★"; color = "#34d399"; }
    else if (s >= 65) { label = "Good  ★★☆";      color = "#D4AF37"; }
    else if (s >= 50) { label = "Average  ★☆☆";   color = "#fbbf24"; }
    else              { label = "Needs Work  ☆☆☆"; color = "#f87171"; }
    el.textContent = label;
    el.style.color       = color;
    el.style.borderColor = color + "55";
    el.style.background  = color + "18";
  }

  /* ================================================================
     BREAKDOWN BARS (rendered in Django template)
  ================================================================ */
  function animateBreakdownBars() {
    document.querySelectorAll(".bk-fill").forEach((bar, i) => {
      const pct = clamp(parseFloat(bar.dataset.pct) || 0, 0, 100);
      setTimeout(() => { bar.style.width = pct + "%"; }, 300 + i * 130);
    });
  }

  /* ================================================================
     PARSE #typing-output
     render_analysis_html structure:
       <div class="card ...">
         <h3>Section Heading</h3>
         <ul><li>item</li>…</ul>
       </div>
     Walk every h3, detect section type, collect sibling li text.
  ================================================================ */
  function parseAnalysisHTML() {
    const result = { matched: [], missing: [], weak: [], improvements: [] };
    const container = $("typing-output");
    if (!container) return result;

    const headings = Array.from(container.querySelectorAll("h3"));

    headings.forEach(h3 => {
      const text = h3.textContent.trim();
      let key = null;
      if      (SEC_RE.matched.test(text))     key = "matched";
      else if (SEC_RE.missing.test(text))     key = "missing";
      else if (SEC_RE.weak.test(text))        key = "weak";
      else if (SEC_RE.improvement.test(text)) key = "improvements";
      if (!key) return;

      /* walk forward siblings until next h3 */
      let sib = h3.nextElementSibling;
      while (sib && sib.tagName !== "H3") {
        if (sib.tagName === "UL" || sib.tagName === "OL") {
          sib.querySelectorAll("li").forEach(li => {
            const raw = li.textContent.trim();
            if (!raw) return;
            if (key === "matched" || key === "missing") {
              /* Gemini sometimes packs "Cat: Skill1, Skill2" in one li */
              raw.split(/[,;]+/).forEach(chunk => {
                chunk.split(/\n+/).forEach(s => {
                  const t = s.trim().replace(/^[-•*]\s*/, "");
                  if (t.length > 1 && t.length < 80) result[key].push(t);
                });
              });
            } else {
              result[key].push(raw);
            }
          });
        } else if (sib.tagName === "P") {
          const raw = sib.textContent.trim();
          if (raw && key !== "matched" && key !== "missing") result[key].push(raw);
        }
        sib = sib.nextElementSibling;
      }

      result[key] = [...new Set(result[key])];
    });

    return result;
  }

  /* ================================================================
     POPULATE MATCHED CLOUD
  ================================================================ */
  function populateMatchedCloud(skills) {
    const cloud = $("matched-cloud");
    if (!cloud) return;
    cloud.innerHTML = "";
    if (!skills.length) {
      cloud.innerHTML = `<span class="parse-hint">No matched skills identified</span>`;
      return;
    }
    skills.forEach((s, i) => {
      const b = mk("span", "skill-badge badge-matched");
      b.textContent = s;
      animateBadge(b, i);
      cloud.appendChild(b);
    });
  }

  /* ================================================================
     POPULATE MISSING CLOUD
  ================================================================ */
  function populateMissingCloud(skills) {
    const cloud = $("missing-cloud");
    if (!cloud) return;
    cloud.innerHTML = "";
    if (!skills.length) {
      cloud.innerHTML = `<span class="parse-hint">No missing skills identified</span>`;
      return;
    }
    skills.forEach((s, i) => {
      const b = mk("span", "skill-badge badge-missing");
      b.textContent = s;
      animateBadge(b, i);
      cloud.appendChild(b);
    });
  }

  function animateBadge(el, i) {
    el.style.opacity   = "0";
    el.style.transform = "scale(0.85) translateY(6px)";
    setTimeout(() => {
      el.style.transition = "opacity .28s ease, transform .28s ease";
      el.style.opacity    = "1";
      el.style.transform  = "scale(1) translateY(0)";
    }, 380 + i * 28);
  }

  /* ================================================================
     POPULATE WARNING LIST
  ================================================================ */
  function populateWarnList(areas) {
    const list = $("warn-list");
    if (!list) return;
    list.innerHTML = "";
    if (!areas.length) {
      list.innerHTML = `<li style="color:rgba(245,245,245,0.35);font-size:13px;padding:6px 0">No weak alignment areas identified</li>`;
      return;
    }
    areas.forEach(area => {
      const li   = mk("li", "warn-item");
      const icon = mk("span", "warn-icon"); icon.setAttribute("aria-hidden","true"); icon.textContent = "⚠";
      const txt  = mk("span", "warn-text"); txt.textContent = area;
      li.appendChild(icon); li.appendChild(txt);
      list.appendChild(li);
    });
  }

  /* ================================================================
     POPULATE IMPROVEMENT LIST
  ================================================================ */
  function populateImpList(recs) {
    const list = $("imp-list");
    if (!list) return;
    list.innerHTML = "";
    if (!recs.length) {
      list.innerHTML = `<li style="color:rgba(245,245,245,0.35);font-size:13px;padding:6px 0">No recommendations found</li>`;
      return;
    }
    recs.forEach((rec, i) => {
      const li    = mk("li", "imp-item");
      const arrow = mk("span", "imp-arrow"); arrow.setAttribute("aria-hidden","true"); arrow.textContent = "↑";
      const num   = mk("span", "imp-num"); num.textContent = i + 1;
      const txt   = mk("span", "imp-text"); txt.textContent = rec;
      li.appendChild(arrow); li.appendChild(num); li.appendChild(txt);
      list.appendChild(li);
    });
  }

  /* ================================================================
     UPDATE STAT CHIPS + BADGE COUNTS
  ================================================================ */
  function updateChips(parsed) {
    const set = (id, val) => { const el = $(id); if (el) el.textContent = val; };
    set("chip-matched-val", parsed.matched.length);
    set("chip-missing-val", parsed.missing.length);
    set("chip-weak-val",    parsed.weak.length);
    set("chip-imp-val",     parsed.improvements.length);
    set("badge-matched",    parsed.matched.length);
    set("badge-missing",    parsed.missing.length);
    set("badge-weak",       parsed.weak.length);
    set("badge-imp",        parsed.improvements.length);
  }

  /* ================================================================
     CHART: BREAKDOWN HORIZONTAL BAR
  ================================================================ */
  function buildBreakdownChart(breakdown) {
    const canvas = $("breakdownChart");
    if (!canvas || !window.Chart) return;

    const labels = Object.keys(breakdown);
    const values = Object.values(breakdown).map(Number);

    /* Shorten labels */
    const short = labels.map(l => {
      if (/hard/i.test(l))       return "Hard Skills";
      if (/job|title/i.test(l))  return "Job Match";
      if (/educ/i.test(l))       return "Education";
      if (/format/i.test(l))     return "Formatting";
      return l.split(/[\s&]+/)[0];
    });

    const barColors = values.map(v =>
      v >= 75 ? "rgba(52,211,153,0.72)" : v >= 50 ? "rgba(212,175,55,0.72)" : "rgba(248,113,113,0.72)"
    );
    const barBorders = values.map(v =>
      v >= 75 ? "#34d399" : v >= 50 ? "#D4AF37" : "#f87171"
    );

    new window.Chart(canvas, {
      type: "bar",
      data: {
        labels: short,
        datasets: [{
          label: "Score",
          data:  values,
          backgroundColor: barColors,
          borderColor:     barBorders,
          borderWidth:     1.5,
          borderRadius:    6,
          borderSkipped:   false,
        }]
      },
      options: {
        indexAxis: "y",
        responsive: true,
        animation: { duration: 1100, easing: "easeOutQuart" },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "rgba(14,14,22,0.96)",
            borderColor: "rgba(212,175,55,0.3)", borderWidth: 1,
            titleColor: "#D4AF37", bodyColor: "#F5F5F5",
            callbacks: { label: ctx => ` ${ctx.parsed.x} / 100` }
          }
        },
        scales: {
          x: {
            min: 0, max: 100,
            grid:   { color: "rgba(255,255,255,0.04)" },
            ticks:  { color: "rgba(245,245,245,0.45)", font: { size: 10 } },
            border: { color: "transparent" }
          },
          y: {
            grid:   { display: false },
            ticks:  { color: "rgba(245,245,245,0.65)", font: { size: 11 } },
            border: { color: "transparent" }
          }
        }
      }
    });
  }

  /* ================================================================
     CHART: SKILLS DOUGHNUT
  ================================================================ */
  function buildSkillsDonut(matchedCount, missingCount) {
    const canvas     = $("skillsChart");
    const legendEl   = $("skill-legend");
    const donutLabel = $("donut-label");
    if (!canvas || !window.Chart) return;

    const total = (matchedCount + missingCount) || 1;
    const pct   = Math.round((matchedCount / total) * 100);

    if (donutLabel) donutLabel.textContent = pct + "%";

    new window.Chart(canvas, {
      type: "doughnut",
      data: {
        labels: ["Matched", "Missing"],
        datasets: [{
          data: [matchedCount, missingCount],
          backgroundColor: ["rgba(52,211,153,0.72)", "rgba(248,113,113,0.62)"],
          borderColor:     ["#34d399", "#f87171"],
          borderWidth: 1.5,
          hoverOffset: 6,
        }]
      },
      options: {
        cutout: "72%",
        responsive: false,
        animation: { duration: 900 },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "rgba(14,14,22,0.96)",
            borderColor: "rgba(212,175,55,0.3)", borderWidth: 1,
            titleColor: "#D4AF37", bodyColor: "#F5F5F5",
            callbacks: {
              label: ctx => ` ${ctx.label}: ${ctx.parsed} (${Math.round(ctx.parsed / total * 100)}%)`
            }
          }
        }
      }
    });

    /* manual legend */
    if (legendEl) {
      [
        { label: `Matched (${matchedCount})`, color: "#34d399" },
        { label: `Missing  (${missingCount})`, color: "#f87171" },
      ].forEach(({ label, color }) => {
        const item = mk("div", "leg-item");
        const dot  = mk("span", "leg-dot"); dot.style.background = color;
        item.appendChild(dot);
        item.appendChild(document.createTextNode(label));
        legendEl.appendChild(item);
      });
    }
  }

  /* ================================================================
     SKILLS TABS — Matched / Missing switcher
  ================================================================ */
  function wireSkillsTabs() {
    const tabs = document.querySelectorAll(".s-tab");
    const panels = {
      matched: $("panel-matched"),
      missing: $("panel-missing"),
    };

    tabs.forEach(tab => {
      tab.addEventListener("click", () => {
        const target = tab.dataset.tab;

        /* update tab active state */
        tabs.forEach(t => t.classList.remove("s-tab--active"));
        tab.classList.add("s-tab--active");

        /* show/hide panels */
        Object.entries(panels).forEach(([key, panel]) => {
          if (!panel) return;
          if (key === target) panel.classList.remove("skills-panel--hidden");
          else                panel.classList.add("skills-panel--hidden");
        });
      });
    });
  }

  /* ================================================================
     RAW TOGGLE
  ================================================================ */
  function wireRawToggle() {
    const btn  = $("raw-toggle");
    const body = $("raw-body");
    if (!btn || !body) return;
    btn.addEventListener("click", () => {
      const isHidden = body.hidden;
      body.hidden    = !isHidden;
      btn.textContent = isHidden ? "Hide ↑" : "Show ↓";
      btn.setAttribute("aria-expanded", String(isHidden));
    });
  }

})();