/* OMNISIGHT website. Plain JavaScript, no libraries, works offline once the server is running. */
"use strict";

const REDUCE = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const LEVEL_CLASS = { "Low": "lvl-low", "Moderate": "lvl-mod", "High": "lvl-high", "Very high": "lvl-vhigh" };
const TUBE = { x: 34, y: 10, w: 60, h: 250 };   // gauge tube in SVG units
const FULL_PCT = 150;                            // the tube is full at 150% of normal rain

const state = { valid: null, overview: null, selected: null, history: {}, pred: {}, anom: {}, sens: {}, card: null, labToken: 0 };

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const $ = (sel, root = document) => root.querySelector(sel);
const enc = encodeURIComponent;
const raf2 = (fn) => requestAnimationFrame(() => requestAnimationFrame(fn));

/* run an animation only when the section scrolls into view */
function whenVisible(el, fn) {
  if (REDUCE || !("IntersectionObserver" in window)) { raf2(fn); return; }
  const io = new IntersectionObserver((entries) => { if (entries.some((e) => e.isIntersecting)) { io.disconnect(); raf2(fn); } }, { threshold: 0.12 });
  io.observe(el);
}
function armSection(box, fn) {
  box.classList.add("pending");
  whenVisible(box, () => { box.classList.remove("pending"); if (fn) fn(); });
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  let body = {};
  try { body = await res.json(); } catch (e) { /* not JSON */ }
  if (!res.ok) throw new Error(body.error || ("Request failed (" + res.status + ")"));
  return body;
}
function cached(map, key, path) { return map[key] ? Promise.resolve(map[key]) : api(path).then((v) => (map[key] = v)); }

function fmtDate(iso) {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" });
}
function fmtMonth(ym) {   // "2002-07" -> "July 2002"
  const [y, m] = ym.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-IN", { month: "long", year: "numeric" });
}
function sign(v, d = 1) { const r = Number(v.toFixed(d)); return (r > 0 ? "+" : r < 0 ? "−" : "") + Math.abs(r).toFixed(d); }
function levelOf(score) { return score < 25 ? "Low" : score < 50 ? "Moderate" : score < 75 ? "High" : "Very high"; }

function tween(node, to, ms = 700) {
  if (!Number.isFinite(to)) { node.textContent = "-"; return; }
  const from = Number(node.dataset.v ?? node.textContent) || 0;
  node.dataset.v = to;
  if (REDUCE || from === to) { node.textContent = Math.round(to); return; }
  const t0 = performance.now();
  const step = (t) => {
    const k = Math.min(1, (t - t0) / ms), e = 1 - Math.pow(1 - k, 3);
    node.textContent = Math.round(from + (to - from) * e);
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

/* ---------------- rain gauge tubes (hero and scenario lab) ---------------- */
function waveD() {   // a repeating wave, 60 units per period, wide enough to drift left forever
  let d = "M0,6";
  for (let i = 0; i < 6; i++) d += " q15,-7 30,0 t30,0";
  return d + ` V${TUBE.h + 20} H0 Z`;
}
const restFor = (pct) => (1 - (pct == null ? 0 : Math.max(0, Math.min(1, pct / FULL_PCT)))) * TUBE.h;

function tubeSvg(id, pct) {
  const normalY = TUBE.y + TUBE.h * (1 - 100 / FULL_PCT);
  return `
  <svg viewBox="0 0 150 280" aria-hidden="true" focusable="false">
    <defs><clipPath id="${id}"><rect x="${TUBE.x}" y="${TUBE.y}" width="${TUBE.w}" height="${TUBE.h}" rx="30"/></clipPath></defs>
    <rect class="tube-wall" x="${TUBE.x}" y="${TUBE.y}" width="${TUBE.w}" height="${TUBE.h}" rx="30"/>
    <g clip-path="url(#${id})">
      <g class="water-shift" data-rest="${restFor(pct)}" style="transform: translateY(${TUBE.h + 12}px)">
        <g transform="translate(0 ${TUBE.y})">
          <path class="water-wave back" transform="translate(-20 0)" d="${waveD()}"/>
          <path class="water-wave" d="${waveD()}"/>
          <g class="bubbles"><circle cx="52" cy="${TUBE.h - 6}" r="3"/><circle cx="70" cy="${TUBE.h - 6}" r="2"/><circle cx="62" cy="${TUBE.h - 6}" r="4"/><circle cx="78" cy="${TUBE.h - 6}" r="2.5"/><circle cx="46" cy="${TUBE.h - 6}" r="2"/></g>
        </g>
      </g>
    </g>
    <line class="normal-line" x1="${TUBE.x - 8}" x2="${TUBE.x + TUBE.w + 8}" y1="${normalY}" y2="${normalY}"/>
    <text class="normal-text" x="${TUBE.x + TUBE.w + 12}" y="${normalY + 3}">normal</text>
  </svg>`;
}
function riseTubes(root) {
  raf2(() => root.querySelectorAll(".water-shift").forEach((g) => { g.style.transform = `translateY(${g.dataset.rest}px)`; }));
}
function setTube(root, pct) {
  const g = $(".water-shift", root);
  g.dataset.rest = restFor(pct);
  g.style.transform = `translateY(${g.dataset.rest}px)`;
}

function renderGauges() {
  const box = $("#gauges");
  box.innerHTML = "";
  state.overview.cities.forEach((c, i) => {
    const ok = c.status !== "unavailable";
    const b = document.createElement("button");
    b.className = "gauge";
    b.type = "button";
    b.setAttribute("role", "listitem");
    b.dataset.city = c.city;
    b.setAttribute("aria-pressed", String(c.city === state.selected));
    b.setAttribute("aria-label", ok
      ? `${c.city}: risk score ${Math.round(c.score)} out of 100, ${c.level}. Rain in the last three months is ${c.rain_3m_pct} percent of normal.`
      : `${c.city}: no risk score for this month`);
    b.innerHTML = `
      ${tubeSvg("tube" + i, ok ? c.rain_3m_pct : null)}
      <span class="g-city">${esc(c.city)}</span>
      <span class="g-score" data-to="${ok ? c.score : ""}">${ok ? (REDUCE ? Math.round(c.score) : 0) : "-"}</span>
      <span class="g-level ${ok ? LEVEL_CLASS[c.level] : ""}"><i></i>${ok ? esc(c.level) : "No score this month"}</span>
      <span class="g-pct">${ok && c.rain_3m_pct != null ? c.rain_3m_pct + "% of normal rain" : ""}</span>`;
    b.addEventListener("click", () => select(c.city));
    box.appendChild(b);
  });
  riseTubes(box);       // the first orchestrated moment: water rises, numbers count up
  raf2(() => box.querySelectorAll(".g-score").forEach((n) => { if (n.dataset.to !== "") tween(n, Number(n.dataset.to), 1500); }));
}

/* ---------------- charts (hand-made SVG) ---------------- */
function niceMax(v) {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v))), n = v / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
}

function monthlyChart(rows) {
  const W = 640, H = 260, L = 44, R = 8, T = 10, B = 28;
  const max = niceMax(Math.max(...rows.map((r) => Math.max(r.actual_mm, r.normal_mm))));
  const iw = W - L - R, ih = H - T - B, slot = iw / rows.length, bw = slot * 0.58;
  const y = (v) => T + ih - (v / max) * ih;
  let g = "";
  [0, 0.5, 1].forEach((t) => {
    const v = max * t;
    g += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${Math.round(v)}</text>`;
  });
  rows.forEach((r, i) => {
    const x = L + i * slot + (slot - bw) / 2, top = y(r.actual_mm);
    g += `<rect class="bar" style="animation-delay:${REDUCE ? 0 : i * 45}ms" x="${x}" y="${top}" width="${bw}" height="${Math.max(0, y(0) - top)}" rx="2"><title>${esc(r.month)}: ${r.actual_mm} mm (normal ${r.normal_mm} mm)</title></rect>`;
    g += `<line class="normal" x1="${x - 3}" x2="${x + bw + 3}" y1="${y(r.normal_mm)}" y2="${y(r.normal_mm)}"/>`;
    g += `<text x="${x + bw / 2}" y="${H - 8}" text-anchor="middle">${esc(r.month.split(" ")[0])}</text>`;
  });
  return `<svg class="chart monthly" viewBox="0 0 ${W} ${H}" role="img" aria-label="Rain in each of the last 12 months compared with the normal for that month">${g}</svg>`;
}

function dailyRainChart(days) {
  const W = 310, H = 150, L = 34, R = 6, T = 8, B = 22;
  const max = niceMax(Math.max(1, ...days.map((d) => d.rain_mm)));
  const iw = W - L - R, ih = H - T - B, slot = iw / days.length;
  const y = (v) => T + ih - (v / max) * ih;
  let g = `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}"/><line class="grid" x1="${L}" x2="${W - R}" y1="${y(max)}" y2="${y(max)}"/>
           <text x="${L - 5}" y="${y(max) + 4}" text-anchor="end">${max}</text><text x="${L - 5}" y="${y(0) + 4}" text-anchor="end">0</text>`;
  days.forEach((d, i) => {
    const top = y(d.rain_mm);
    g += `<rect class="bar" x="${L + i * slot + 0.5}" y="${top}" width="${Math.max(1, slot - 1.5)}" height="${Math.max(0, y(0) - top)}"><title>${d.date}: ${d.rain_mm} mm</title></rect>`;
  });
  g += `<text x="${L}" y="${H - 5}">${esc(days[0].date.slice(5))}</text><text x="${W - R}" y="${H - 5}" text-anchor="end">${esc(days[days.length - 1].date.slice(5))}</text>`;
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Daily rain, newest 45 days, in millimetres">${g}</svg>`;
}

function dailyTempChart(days) {
  const W = 310, H = 150, L = 34, R = 6, T = 8, B = 22;
  const vals = days.map((d) => d.tmax_c), lo = Math.floor(Math.min(...vals) - 1), hi = Math.ceil(Math.max(...vals) + 1);
  const iw = W - L - R, ih = H - T - B;
  const x = (i) => L + (i / Math.max(1, days.length - 1)) * iw, y = (v) => T + ih - ((v - lo) / (hi - lo)) * ih;
  const pts = days.map((d, i) => `${x(i).toFixed(1)},${y(d.tmax_c).toFixed(1)}`).join(" ");
  const g = `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(lo)}" y2="${y(lo)}"/><line class="grid" x1="${L}" x2="${W - R}" y1="${y(hi)}" y2="${y(hi)}"/>
    <text x="${L - 5}" y="${y(hi) + 4}" text-anchor="end">${hi}</text><text x="${L - 5}" y="${y(lo) + 4}" text-anchor="end">${lo}</text>
    <polyline class="tline" points="${pts}"/>
    <text x="${L}" y="${H - 5}">${esc(days[0].date.slice(5))}</text><text x="${W - R}" y="${H - 5}" text-anchor="end">${esc(days[days.length - 1].date.slice(5))}</text>`;
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Daily maximum temperature, newest 45 days, in degrees Celsius">${g}</svg>`;
}

/* ---------------- section 1: city detail ---------------- */
function detailHtml(c, hist) {
  const w = c.weights, p = c.points;
  const max = { rain: 100 * w.rain, heat: 100 * w.heat, dry: 100 * w.dry };
  const pctRain = c.rain_3m_pct == null ? "" : `${c.rain_3m_pct}% of normal rain (${Math.round(c.rain_3m_mm)} mm against ${Math.round(c.rain_3m_normal_mm)} mm). `;
  const factor = (title, text, key) => `
    <li class="factor"><h3>${title}</h3><p>${text}</p>
      <div class="pts"><span>${p[key].toFixed(1)} of ${max[key].toFixed(0)} points</span>
      <div class="track"><div class="fill" data-w="${(100 * p[key] / max[key]).toFixed(0)}" style="width:0"></div></div></div></li>`;
  const last = hist.recent_days[hist.recent_days.length - 1].date, first = hist.recent_days[0].date;
  return `
  <div class="detail-inner">
    <div>
      <h2>${esc(c.city)}</h2>
      <p class="sub">Data as of ${fmtDate(c.as_of)}, the last complete month.</p>
      <div class="big-score"><b>${Math.round(c.score)}</b><span>${esc(c.level)} risk</span></div>
      <div class="zonebar" role="img" aria-label="Score ${Math.round(c.score)} on a scale of 0 to 100"><span></span><span></span><span></span><span></span>
        <div class="pin" data-left="${c.score}" style="left:0"></div></div>
      <div class="zonelabels"><span>0 Low</span><span>25 Moderate</span><span>50 High</span><span>75 Very high</span><span>100</span></div>
      <ul class="factors">
        ${factor("Rain over the last 3 months", `${pctRain}The 3-month rain index (SPI-3) is ${sign(c.spi3)}, which is ${esc(c.spi3_label)}.`, "rain")}
        ${factor("Heat over the last 30 days", `The average daily maximum is ${sign(c.heat_z)} standard deviations from normal for these days: ${esc(c.heat_label)}.`, "heat")}
        ${factor("Longest dry spell in the last 60 days", `${c.dry_run_days} days in a row with less than 1 mm of rain.`, "dry")}
      </ul>
      <p class="dl"><button type="button" class="btn" id="dl-report">Download evidence report</button><span id="dl-msg" role="status"></span></p>
    </div>
    <div class="charts">
      <h3>Rain in each of the last 12 months</h3>
      <p class="cap">Bars are the rain that fell. The dark line is the 1991&ndash;2020 average for the same month, in millimetres.</p>
      ${monthlyChart(hist.monthly)}
      <div class="legend"><span><i class="sw-bar"></i>Rain this year</span><span><i class="sw-norm"></i>Normal for the month</span></div>
      <div class="two">
        <div><h3>Daily rain, newest 45 days</h3><p class="cap">${esc(first)} to ${esc(last)}, mm</p>${dailyRainChart(hist.recent_days)}</div>
        <div><h3>Daily maximum temperature</h3><p class="cap">Same days, &deg;C</p>${dailyTempChart(hist.recent_days)}</div>
      </div>
    </div>
  </div>`;
}
async function downloadReport(city) {
  const msg = $("#dl-msg");
  msg.textContent = "Preparing the report\u2026";
  try {
    const r = await api(`/api/city/${enc(city)}/report`);
    const url = URL.createObjectURL(new Blob([r.markdown], { type: "text/markdown;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url; a.download = r.filename; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    msg.textContent = `Saved ${r.filename}`;
  } catch (e) { msg.textContent = "Could not create the report: " + e.message; }
}

function renderDetail(c, hist) {
  const box = $("#detail");
  box.innerHTML = detailHtml(c, hist);
  $("#dl-report", box).addEventListener("click", () => downloadReport(c.city));
  armSection(box, () => {
    box.querySelectorAll(".fill").forEach((f) => { f.style.width = f.dataset.w + "%"; });
    box.querySelectorAll(".pin").forEach((p) => { p.style.left = p.dataset.left + "%"; });
  });
}

/* ---------------- section 2: next month (machine learning) ---------------- */
function effValue(e) {
  if (e.value == null) return "";
  if (e.feature === "dry_run_60") return `${Math.round(e.value)} days (typical ${Math.round(e.typical)})`;
  return `${sign(e.value)} std dev (typical ${sign(e.typical)})`;
}
function effectBars(exp) {
  const rows = exp.filter((e) => Math.abs(e.effect) >= 0.001).slice(0, 5);
  if (!rows.length) return `<p class="cap">No single factor moves the score noticeably.</p>`;
  const m = Math.max(...rows.map((r) => Math.abs(r.effect)), 0.01);
  return `<ul class="effects">` + rows.map((r) => {
    const side = r.effect > 0 ? "dry" : "wet", w = (Math.abs(r.effect) / m) * 50;
    return `<li class="eff"><div class="eff-label"><b>${esc(r.meaning)}</b><span>${esc(effValue(r))}</span></div>
      <div class="eff-bar" role="img" aria-label="${esc(r.meaning)} pushes the score ${r.effect > 0 ? "towards dry" : "towards not dry"}"><i class="${side}" data-w="${w.toFixed(1)}" style="width:0"></i></div></li>`;
  }).join("") + `</ul>
    <div class="eff-key"><span>pushes towards not dry</span><span>pushes towards dry</span></div>`;
}
function aucChart(res) {
  const [lo, hi] = res.auc_ci95, W = 640, H = 96, L = 24, R = 24;
  const x = (v) => L + ((v - 0.3) / 0.6) * (W - L - R);
  let g = "";
  [0.3, 0.5, 0.7, 0.9].forEach((t) => { g += `<line class="grid" x1="${x(t)}" x2="${x(t)}" y1="22" y2="62"/><text x="${x(t)}" y="80" text-anchor="middle">${t.toFixed(1)}</text>`; });
  g += `<line class="guess" x1="${x(0.5)}" x2="${x(0.5)}" y1="14" y2="62"/><text x="${x(0.5)}" y="11" text-anchor="middle">guessing</text>`;
  g += `<line class="ci" x1="${x(lo)}" x2="${x(hi)}" y1="42" y2="42"/><line class="ci" x1="${x(lo)}" x2="${x(lo)}" y1="34" y2="50"/><line class="ci" x1="${x(hi)}" x2="${x(hi)}" y1="34" y2="50"/>`;
  g += `<circle class="auc" cx="${x(res.roc_auc)}" cy="42" r="7"/>`;
  return `<svg class="chart auc-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Test score ${res.roc_auc}, 95 percent interval ${lo} to ${hi}. 0.5 means guessing.">${g}</svg>`;
}
function renderNext(c, p) {
  const box = $("#next");
  if (!p) { box.innerHTML = `<div class="band-inner"><h2>Next month</h2><p class="cap">The prediction could not be loaded.</p></div>`; return; }
  if (p.status !== "ok") {
    box.innerHTML = `<div class="band-inner"><h2>Next month in ${esc(c.city)}</h2><p class="cap">${esc(p.message || "No prediction is available for this month.")}</p></div>`;
    return;
  }
  const res = state.card && state.card.test_results && state.card.test_results[state.card.chosen_model];
  const years = state.card ? `${state.card.test_years[0]} to ${state.card.test_years[1]}` : "held-out years";
  const warn = (p.warnings || []).map((w) => `<p class="notice-line">${esc(w)}</p>`).join("");
  box.innerHTML = `
  <div class="band-inner">
    <h2>What the model says about ${esc(p.target_month)}</h2>
    <p class="sub">A machine-learning model reads the weather up to ${fmtDate(p.as_of)} and asks one question about ${esc(c.city)}:
      will next month's rain fall in the driest third of years for that month?</p>
    ${warn}
    <div class="next-grid">
      <div>
        <p class="answer">${esc(p.answer)}</p>
        <div class="mtrack" role="img" aria-label="Model score ${p.score} on a scale from 0 to 1">
          <b class="mhalf"></b><i class="mpin" data-left="${(p.score * 100).toFixed(1)}" style="left:0"></i></div>
        <div class="mlabels"><span>0 not dry</span><span>0.5</span><span>1 dry</span></div>
        <p class="cap">Model score ${p.score.toFixed(2)}. ${esc(p.score_note)} In 1991&ndash;2015 about ${Math.round(100 * p.base_rate_train)}% of months in this season were dry by this definition.</p>
        <h3>Why the model leans this way</h3>
        <p class="cap">Each bar shows how far one factor moves the score away from a typical year.</p>
        ${effectBars(p.explanation)}
      </div>
      <div>
        <h3>How well has this model done?</h3>
        <p class="cap">Scored on ${esc(years)}, years it never saw during training. A score of 0.5 means no better than guessing; the line shows the 95% interval.</p>
        ${res ? aucChart(res) : ""}
        <p class="cap">${esc(p.skill_note)}</p>
        <details class="limits"><summary>What this prediction does not do</summary>
          <ul>${(p.limitations || []).map((l) => `<li>${esc(l)}</li>`).join("")}</ul></details>
        <p class="cap model-line">Model: ${esc(p.model)}, trained on ${state.card ? state.card.train_years[0] + " to " + state.card.train_years[1] : "earlier years"}.</p>
      </div>
    </div>
  </div>`;
  armSection(box, () => {
    box.querySelectorAll(".eff-bar i").forEach((i) => { i.style.width = i.dataset.w + "%"; });
    box.querySelectorAll(".mpin").forEach((i) => { i.style.left = i.dataset.left + "%"; });
  });
}

/* ---------------- section 3: unusual months ---------------- */
function anomalyChart(recent, threshold) {
  const W = 640, H = 200, L = 36, R = 8, T = 10, B = 30;
  const max = Math.max(threshold * 1.2, ...recent.map((r) => r.anomaly_score)) * 1.05 || 1;
  const iw = W - L - R, ih = H - T - B, slot = iw / recent.length, bw = slot * 0.64;
  const y = (v) => T + ih - (v / max) * ih;
  let g = `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}"/>`;
  g += `<line class="thr" x1="${L}" x2="${W - R}" y1="${y(threshold)}" y2="${y(threshold)}"/><text x="${L - 4}" y="${y(threshold) + 4}" text-anchor="end">flag</text>`;
  recent.forEach((r, i) => {
    const x = L + i * slot + (slot - bw) / 2, top = y(r.anomaly_score);
    g += `<rect class="bar ${r.flagged ? "flag" : "quiet"}" style="animation-delay:${REDUCE ? 0 : i * 30}ms" x="${x}" y="${top}" width="${bw}" height="${Math.max(0, y(0) - top)}" rx="2"><title>${fmtMonth(r.month)}: ${r.kind}${r.flagged ? " (flagged)" : ""}</title></rect>`;
    if (i % 3 === 0) {
      const [yy, mm] = r.month.split("-");
      g += `<text x="${x + bw / 2}" y="${H - 12}" text-anchor="middle">${new Date(+yy, +mm - 1, 1).toLocaleDateString("en-IN", { month: "short" })}</text>
            <text x="${x + bw / 2}" y="${H - 1}" text-anchor="middle">${yy}</text>`;
    }
  });
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="How unusual each of the last 24 months was. Bars above the flag line are flagged.">${g}</svg>`;
}
function anomalyItem(a) {
  const trig = a.triggers.length
    ? `<ul class="an-trig">${a.triggers.map((t) => `<li>${esc(t.detail)}</li>`).join("")}</ul>`
    : `<p class="an-trig">No single value is extreme; the combination is unusual.</p>`;
  const notes = a.notes.filter((n) => !n.startsWith("Gridded")).map((n) => `<p class="an-note">${esc(n)}</p>`).join("");
  return `<li class="an-item"><div class="an-head"><h4>${fmtMonth(a.month)}</h4><span class="${/dry|hot/i.test(a.kind) ? "k-hot" : /wet|cool/i.test(a.kind) ? "k-wet" : "k-mix"}">${esc(a.kind)}</span></div>
    ${trig}<p class="an-ev">Evidence: ${esc(a.evidence)}.</p>${notes}</li>`;
}
function renderUnusual(c, an) {
  const box = $("#unusual");
  if (!an) { box.innerHTML = `<div class="band-inner"><h2>Unusual months</h2><p class="cap">Could not load the analysis.</p></div>`; return; }
  const recentFlags = an.recent.filter((r) => r.flagged);
  const summary = recentFlags.length
    ? `In the last 24 months, ${recentFlags.length} ${recentFlags.length === 1 ? "month was" : "months were"} flagged: ${recentFlags.map((r) => fmtMonth(r.month)).join(", ")}.`
    : "None of the last 24 months was flagged as unusual.";
  box.innerHTML = `
  <div class="band-inner">
    <h2>Unusual months in ${esc(c.city)}</h2>
    <p class="sub">Every month is compared with the same month in 1991&ndash;2020. Two checks run side by side: a plain
      statistical test, and an Isolation Forest that looks at rain, heat, dry spells and rainy days together.
      A flag means &ldquo;unusual for this city&rdquo;. It is not a drought declaration.</p>
    <div class="an-grid">
      <div>
        <h3>The last 24 months</h3>
        <p class="cap">${esc(summary)}</p>
        ${anomalyChart(an.recent, an.threshold)}
        <div class="legend"><span><i class="sw-flag"></i>Flagged</span><span><i class="sw-quiet"></i>Within the normal range</span></div>
      </div>
      <div>
        <h3>The most unusual months since 1991</h3>
        <ol class="an-list">${an.top_historic.slice(0, 6).map(anomalyItem).join("")}</ol>
      </div>
    </div>
  </div>`;
  armSection(box);
}

/* ---------------- section 4: scenario lab ---------------- */
const PRESETS = [
  { label: "As observed", rain: 100, temp: 0 },
  { label: "Weak monsoon", rain: 70, temp: 0 },
  { label: "Heatwave", rain: 100, temp: 3 },
  { label: "Weak monsoon and heatwave", rain: 70, temp: 3 },
];
function labHtml(c) {
  return `
  <div class="lab-inner">
    <h2>Scenario lab: what if it had been different?</h2>
    <p class="sub on-deep">Change the rain and the heat of the recent past in ${esc(c.city)} and watch the score respond.
      Everything you change here is a hypothetical assumption, not a forecast.</p>
    <div class="lab-grid">
      <div class="lab-controls">
        <label for="rain">Rain over the last 3 months <output id="rain-out">100% of observed</output></label>
        <input id="rain" type="range" min="0" max="150" step="5" value="100">
        <label for="temp">Temperature over the last 30 days <output id="temp-out">+0.0 &deg;C</output></label>
        <input id="temp" type="range" min="-2" max="5" step="0.5" value="0">
        <div class="presets" role="group" aria-label="Example scenarios">
          ${PRESETS.map((p, i) => `<button type="button" data-i="${i}">${esc(p.label)}</button>`).join("")}
        </div>
        <p class="lab-reading" id="lab-reading">&nbsp;</p>
      </div>
      <div class="twin" aria-live="polite">
        <figure class="twin-one" id="tw-base">${tubeSvg("twB", c.rain_3m_pct)}
          <figcaption><span class="tw-name">Observed</span><b class="tw-score">${Math.round(c.score)}</b>
          <span class="tw-level">${esc(c.level)}</span><span class="tw-pct">${c.rain_3m_pct}% of normal rain</span></figcaption></figure>
        <div class="twin-mid"><span id="tw-delta">no change</span></div>
        <figure class="twin-one" id="tw-scen">${tubeSvg("twS", c.rain_3m_pct)}
          <figcaption><span class="tw-name">Scenario</span><b class="tw-score" data-v="${Math.round(c.score)}">${Math.round(c.score)}</b>
          <span class="tw-level">${esc(c.level)}</span><span class="tw-pct" id="tw-pct">${c.rain_3m_pct}% of normal rain</span></figcaption></figure>
      </div>
    </div>
    <p class="lab-ml" id="lab-ml"></p>
    <div class="sens" id="sens"><p class="cap on-deep">Calculating the sensitivity grid&hellip;</p></div>
    <ul class="layers" id="layers"></ul>
  </div>`;
}

function renderLab(c) {
  const box = $("#lab");
  box.innerHTML = labHtml(c);
  armSection(box, () => riseTubes(box));
  const city = c.city, rain = $("#rain", box), temp = $("#temp", box);
  let timer = null;

  const labels = () => {
    $("#rain-out", box).textContent = `${rain.value}% of observed`;
    $("#temp-out", box).textContent = `${sign(+temp.value)} °C`;
  };
  const apply = async () => {
    const token = ++state.labToken;
    try {
      const r = await api(`/api/city/${enc(city)}/compare?rain_factor=${rain.value / 100}&temp_add=${temp.value}`);
      if (token !== state.labToken || state.selected !== city) return;
      const s = r.scenario.risk, b = r.baseline.risk;
      setTube($("#tw-scen", box), s.rain_3m_pct);
      tween($("#tw-scen .tw-score", box), s.score);
      $("#tw-scen .tw-level", box).textContent = s.level;
      $("#tw-pct", box).textContent = `${s.rain_3m_pct}% of normal rain`;
      const d = Math.round(s.score) - Math.round(b.score);
      $("#tw-delta", box).textContent = d === 0 ? "no change" : `${d > 0 ? "+" : "−"}${Math.abs(d)} points`;
      $("#lab-reading", box).textContent = r.reading;
      const m = r.delta.ml_score;
      $("#lab-ml", box).textContent = (r.baseline.prediction.status === "ok" && r.scenario.prediction.status === "ok")
        ? `The next-month model score would move from ${r.baseline.prediction.score.toFixed(2)} to ${r.scenario.prediction.score.toFixed(2)} (${sign(m, 2)}). This is a what-if on the model, not a forecast.`
        : "";
      const layers = $("#layers", box);
      if (!layers.children.length) {
        const names = { observed: "Observed", ml_prediction: "Model output", simulation: "Simulation", assumption: "Your assumption" };
        layers.innerHTML = Object.keys(names).map((k) => `<li class="layer ${k}"><b>${names[k]}</b><span>${esc(r.layers[k])}</span></li>`).join("");
      }
    } catch (e) {
      $("#lab-reading", box).textContent = "Could not update the scenario: " + e.message;
    }
  };
  const schedule = () => { labels(); clearTimeout(timer); timer = setTimeout(apply, REDUCE ? 0 : 200); };
  rain.addEventListener("input", schedule);
  temp.addEventListener("input", schedule);
  box.querySelectorAll(".presets button").forEach((b) => b.addEventListener("click", () => {
    const p = PRESETS[+b.dataset.i];
    rain.value = p.rain; temp.value = p.temp; schedule();
  }));
  apply();

  cached(state.sens, city, `/api/city/${enc(city)}/sensitivity`).then((g) => {
    if (state.selected !== city) return;
    const head = g.rain_factors.map((r) => `<th scope="col">${Math.round(r * 100)}%</th>`).join("");
    const rows = g.temp_adds.map((t, ti) => `<tr><th scope="row">${t === 0 ? "0" : "+" + t}</th>` + g.risk_score[ti].map((v, ri) => {
      const r = g.rain_factors[ri], observed = (r === 1 && t === 0);
      return `<td><button type="button" class="cell lvl-${levelOf(v).toLowerCase().replace(" ", "")}${observed ? " observed" : ""}"
        data-rain="${Math.round(r * 100)}" data-temp="${t}" aria-label="Rain ${Math.round(r * 100)} percent, ${t >= 0 ? "plus " : "minus "}${Math.abs(t)} degrees: score ${Math.round(v)}, ${levelOf(v)}">${Math.round(v)}</button></td>`;
    }).join("") + `</tr>`).join("");
    $("#sens", box).innerHTML = `
      <h3>How the score responds</h3>
      <p class="cap on-deep">Each cell is the risk score for one combination. Columns: rain as a share of what was observed. Rows: how many &deg;C warmer. Click a cell to try it above. The outlined cell is what was observed.</p>
      <div class="sens-wrap"><table><caption class="sr">Risk score for combinations of rain and temperature change</caption>
        <thead><tr><th scope="col"><span class="sr">Temperature change</span></th>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
    box.querySelectorAll(".cell").forEach((b) => b.addEventListener("click", () => {
      rain.value = b.dataset.rain; temp.value = b.dataset.temp; schedule();
    }));
  }).catch((e) => { $("#sens", box).innerHTML = `<p class="cap on-deep">Could not load the grid: ${esc(e.message)}</p>`; });
}


/* ---------------- section: how we checked it ---------------- */
function yearsChart(years) {
  const W = 640, H = 236, L = 30, R = 8, T = 22, B = 44;
  const max = Math.max(...years.map((y) => y.avg_score)) * 1.1 || 1;
  const iw = W - L - R, ih = H - T - B, slot = iw / years.length, bw = slot * 0.7;
  const y = (v) => T + ih - (v / max) * ih;
  const weak = years.filter((d) => d.deficient).map((d) => d.year);
  let g = `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}"/><text x="${L - 4}" y="${y(0) + 4}" text-anchor="end">0</text>
           <text x="${L - 4}" y="${y(max / 1.1) + 4}" text-anchor="end">${Math.round(max / 1.1)}</text>`;
  years.forEach((d, i) => {
    const x = L + i * slot + (slot - bw) / 2, top = y(d.avg_score), cx = x + bw / 2;
    g += `<rect class="bar ${d.deficient ? "flag" : "quiet"}" style="animation-delay:${REDUCE ? 0 : i * 20}ms" x="${x}" y="${top}" width="${bw}" height="${Math.max(0, y(0) - top)}" rx="1.5"><title>${d.year}: average score ${d.avg_score} (rank ${d.rank})${d.deficient ? ", documented weak monsoon" : ""}</title></rect>`;
    if (d.deficient) {   // labels sit below the axis, on two alternating rows so neighbours do not collide
      const row = weak.indexOf(d.year) % 2 === 0 ? H - 22 : H - 6;
      g += `<line class="tick" x1="${cx}" x2="${cx}" y1="${y(0)}" y2="${row - 11}"/><text class="dlabel" x="${cx}" y="${row}" text-anchor="middle">${d.year}</text>`;
    } else if (d.year % 5 === 0 && !weak.some((w) => Math.abs(w - d.year) <= 3)) {
      g += `<text x="${cx}" y="${H - 6}" text-anchor="middle">${d.year}</text>`;
    }
  });
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Average risk score of the five cities in each year since 1991. The four documented weak monsoons are highlighted.">${g}</svg>`;
}
function renderValidation() {
  const box = $("#validation"), v = state.valid;
  if (!v || v.error) { box.innerHTML = ""; return; }
  const mrows = v.model.rows.map((r) => `<tr class="${r.used_in_app ? "used" : ""}"><th scope="row">${esc(r.model)}${r.used_in_app ? " (used in the app)" : ""}</th>
      <td>${r.roc_auc.toFixed(2)} <span class="ci">(${r.auc_ci95[0].toFixed(2)} to ${r.auc_ci95[1].toFixed(2)})</span></td>
      <td>${r.balanced_acc.toFixed(2)}</td><td>${r.f1.toFixed(2)}</td></tr>`).join("");
  let check1;
  if (v.available) {
    const hits = v.table.filter((t) => t.top6).length;
    const trows = v.table.map((t) => `<tr><th scope="row">${t.year}</th><td>${esc(t.monsoon)}</td><td>${t.avg_score.toFixed(1)}</td>
        <td>${t.rank} of ${t.of}</td><td>${t.top6 ? "Yes" : "No"}</td></tr>`).join("");
    check1 = `
      <h3>Does the score pick out monsoons we know were weak?</h3>
      <p class="cap">Four monsoons are documented as deficient across India. We scored every year since 1991 as of 30 September and ranked
        the years by the average score of the five cities. ${hits} of the ${v.table.length} documented years rank in our top 6 of ${v.table[0].of}.</p>
      <div class="vtable-wrap"><table class="vtable"><thead><tr><th scope="col">Year</th><th scope="col">All-India monsoon</th><th scope="col">Our average score</th><th scope="col">Our rank</th><th scope="col">In our top 6</th></tr></thead><tbody>${trows}</tbody></table></div>
      ${yearsChart(v.years)}
      <div class="legend"><span><i class="sw-flag"></i>Documented weak monsoon</span><span><i class="sw-quiet"></i>Other years</span></div>
      <h4 class="small-h">What this check can and cannot show</h4>
      <ul class="cap-list">${v.caveats.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>`;
  } else {
    check1 = `<h3>Does the score pick out monsoons we know were weak?</h3><p class="cap">${esc(v.message)}</p>`;
  }
  box.innerHTML = `
  <div class="band-inner">
    <h2>How we checked it</h2>
    <p class="sub">Two checks, both limited, both shown here. One asks whether the risk score recognises known weak monsoons.
      The other asks how the next-month model did on years it never saw.</p>
    <div class="val-grid">
      <div>${check1}</div>
      <div>
        <h3>How did the next-month model do?</h3>
        <p class="cap">Trained on ${v.model.train_years[0]}&ndash;${v.model.train_years[1]}, scored on ${v.model.test_years[0]}&ndash;${v.model.test_years[1]}.
          A test score (AUC) of 0.5 means no better than guessing. In the test years ${Math.round(100 * v.model.dry_share_test)}% of months were dry
          by our definition, against ${Math.round(100 * v.model.dry_share_train)}% in the training years.</p>
        <div class="vtable-wrap"><table class="vtable"><thead><tr><th scope="col">Model</th><th scope="col">Test score (AUC)</th><th scope="col">Balanced accuracy</th><th scope="col">F1</th></tr></thead><tbody>${mrows}</tbody></table></div>
        <p class="cap">The model was chosen by cross-validation inside the training years, before the test years were looked at.
          The intervals include 0.5, so we treat next-month prediction as an experimental feature and not as a proven forecast.</p>
      </div>
    </div>
  </div>`;
  armSection(box);
}
async function loadValidation() {
  try { state.valid = await api("/api/validation"); } catch (e) { state.valid = { error: e.message }; }
  renderValidation();
}


/* ---------------- rain in the hero: its density follows the selected city's real rain ---------------- */
const rainState = { pct: 70, city: "" };
function setRainFor(c) {
  rainState.pct = c.rain_3m_pct == null ? 70 : c.rain_3m_pct;
  rainState.city = c.city;
  const note = $("#rain-note");
  if (note) note.textContent = `The rain in the background follows ${c.city}: its last three months are ${rainState.pct}% of normal.` +
    (rainState.pct < 60 ? " Slow amber streaks mean a dry spell." : "");
}
function startRain() {
  const cv = $("#rain-canvas");
  if (!cv || REDUCE || !cv.getContext) return;
  const ctx = cv.getContext("2d");
  let W = 0, H = 0, visible = true;
  const drops = [];
  const mk = () => ({ x: Math.random() * (W + 80) - 40, y: -20 - Math.random() * H, len: 10 + Math.random() * 16, v: 5 + Math.random() * 6, a: 0.16 + Math.random() * 0.34 });
  const resize = () => {
    const r = cv.getBoundingClientRect(), dpr = Math.min(2, window.devicePixelRatio || 1);
    cv.width = Math.max(1, r.width * dpr); cv.height = Math.max(1, r.height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); W = r.width; H = r.height;
  };
  if ("ResizeObserver" in window) new ResizeObserver(resize).observe(cv); else window.addEventListener("resize", resize);
  if ("IntersectionObserver" in window) new IntersectionObserver((es) => { visible = es[0].isIntersecting; }).observe(cv);
  resize();
  (function frame() {
    requestAnimationFrame(frame);
    if (!visible || document.hidden || !W) return;
    const target = Math.round(Math.max(22, Math.min(190, rainState.pct * 1.25)) * (W / 1200 + 0.35));
    for (let k = 0; k < 2; k++) { if (drops.length < target) drops.push(mk()); else if (drops.length > target) drops.pop(); }
    const dry = rainState.pct < 60, rgb = dry ? "255,193,77" : "63,208,232";
    ctx.clearRect(0, 0, W, H);
    ctx.lineWidth = dry ? 1.4 : 1.5; ctx.lineCap = "round";
    for (const d of drops) {
      d.y += d.v * (dry ? 0.6 : 1); d.x -= d.v * 0.18 * (dry ? 0.6 : 1);
      if (d.y > H + 20 || d.x < -60) { d.y = -20; d.x = Math.random() * (W + 80) - 20; }
      ctx.strokeStyle = `rgba(${rgb},${d.a})`;
      ctx.beginPath(); ctx.moveTo(d.x, d.y); ctx.lineTo(d.x + d.len * 0.18, d.y + d.len * (dry ? 0.5 : 1)); ctx.stroke();
    }
  })();
}

/* ---------------- selecting a city ---------------- */
async function select(city) {
  state.selected = city;
  state.labToken++;
  document.querySelectorAll(".gauge").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.city === city)));
  const c = state.overview.cities.find((x) => x.city === city);
  $("#detail-link").textContent = `See how ${city}'s score is built`;
  if (c.status !== "unavailable") setRainFor(c);
  if (c.status === "unavailable") {
    $("#detail").innerHTML = `<div class="notice"><h2>${esc(city)}</h2><p>${esc(c.message)}</p></div>`;
    ["#next", "#unusual", "#lab"].forEach((s) => { $(s).innerHTML = ""; });
    return;
  }
  const [h, p, a] = await Promise.allSettled([
    cached(state.history, city, `/api/city/${enc(city)}/history`),
    cached(state.pred, city, `/api/city/${enc(city)}/prediction`),
    cached(state.anom, city, `/api/city/${enc(city)}/anomalies`),
  ]);
  if (state.selected !== city) return;             // user clicked another city meanwhile
  if (h.status === "fulfilled") renderDetail(c, h.value);
  else $("#detail").innerHTML = `<div class="notice"><h2>${esc(city)}</h2><p>Could not load the history: ${esc(h.reason.message)}</p></div>`;
  renderNext(c, p.status === "fulfilled" ? p.value : null);
  renderUnusual(c, a.status === "fulfilled" ? a.value : null);
  renderLab(c);
}

/* ---------------- start ---------------- */
async function init(keepCity) {
  try {
    state.overview = await api("/api/overview");
  } catch (e) {
    $("#asof").textContent = "Could not load data. Make sure the server is running (python server.py). " + e.message;
    return;
  }
  api("/api/model").then((m) => { state.card = m; if (state.selected) { const c = state.overview.cities.find((x) => x.city === state.selected); const p = state.pred[state.selected]; if (c && p) renderNext(c, p); } }).catch(() => {});
  loadValidation();
  const scored = state.overview.cities.filter((c) => c.status !== "unavailable");
  if (!scored.length) { $("#asof").textContent = "No city has a score for the latest month in the saved data."; return; }
  const keep = keepCity && scored.find((c) => c.city === keepCity);
  state.selected = keep ? keep.city : scored.slice().sort((a, b) => b.score - a.score)[0].city;
  $("#asof").textContent = `Data as of ${fmtDate(scored[0].as_of)}, the last complete month. Rain and temperature are ERA5 estimates.`;
  renderGauges();
  select(state.selected);
}

$("#update-btn").addEventListener("click", async () => {
  const btn = $("#update-btn"), msg = $("#update-msg");
  btn.disabled = true; msg.textContent = "Downloading the newest days from Open-Meteo\u2026";
  try {
    const r = await api("/api/update", { method: "POST" });
    const keep = state.selected;
    ["history", "pred", "anom", "sens"].forEach((k) => { state[k] = {}; });
    await init(keep);
    msg.textContent = r.message;
  } catch (e) {
    msg.textContent = "Could not update: " + e.message;
  } finally { btn.disabled = false; }
});

startRain();
init();
