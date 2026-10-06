// Black/white frame, three accents for meaning: light teal = healthy/
// verified/confirmed, dark teal = secondary category, orange = exception/
// at-risk/pending review.
const TEAL = "#7ec8c2";
const TEAL_DARK = "#33605a";
const ACCENT_ORANGE = "#ff6b35";
const RULE_COLORS = [TEAL, TEAL_DARK, "rgba(126,200,194,0.5)", "rgba(51,96,90,0.6)"];

function colorForRule(label, rank) {
  if (label === "exception") return ACCENT_ORANGE;
  return RULE_COLORS[Math.min(rank, RULE_COLORS.length - 1)];
}

function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

const state = { data: null, view: "dashboard", filter: "all", query: "", selected: null };

function short(hash) {
  return hash ? `${hash.slice(0, 10)}…${hash.slice(-6)}` : "—";
}

async function main() {
  // Embedded mode (inside Streamlit): data is injected directly, no fetch
  // needed or possible from a sandboxed srcdoc iframe.
  if (window.__DASHBOARD_DATA__) {
    render(window.__DASHBOARD_DATA__);
    return;
  }
  // Standalone mode: served as static files, data.json sits alongside.
  const demo = new URLSearchParams(location.search).has("demo");
  const res = await fetch(demo ? "data.demo.json" : "data.json");
  if (!res.ok) {
    document.getElementById("subtitle").textContent =
      `${demo ? "data.demo.json" : "data.json"} not found — run: python scripts/export_dashboard_data.py${demo ? " --mock" : ""}`;
    return;
  }
  render(await res.json());
}

function render(data) {
  state.data = data;
  data.records = data.records || [];
  document.getElementById("subtitle").textContent =
    `${data.data_source === "mock" ? "Mock" : "Razorpay test-mode"} data · ${data.batch_size} records · Track 04`;

  renderDonut(data.rule_type_breakdown, data.scores.precision);
  renderRingGrid(data);
  renderProgress(data);
  renderExceptions(data);
  renderConservationGoal(data.conservation);
  renderForecast(data.forecast);
  renderAtRisk(data.forecast);
  renderGeneralization(data.generalization);
  renderReconStrip(data);
  renderRecords();
  renderDetail();
  renderForecastView(data.forecast);
  initReconControls();

  document.getElementById("reverify-btn").addEventListener("click", () => {
    const statusEl = document.getElementById("reverify-status");
    statusEl.textContent =
      data.reverify.chain_intact && data.reverify.all_math_ok
        ? `${data.reverify.checked}/${data.reverify.checked} proofs independently re-verified. Chain intact.`
        : "Verification found an issue — see scripts/verify_chain.py output.";
    statusEl.style.color = data.reverify.chain_intact && data.reverify.all_math_ok ? TEAL : ACCENT_ORANGE;
  });

  initNav();
  initHeaderIcons(data);
}

// ---------- Navigation: three real views (dashboard overview, the
// reconciliation record browser, the forecast), driven by the dock and kept
// in the URL hash when the page allows it.
const VIEWS = ["dashboard", "reconciliation", "forecast"];

function setActiveTab(name) {
  if (!VIEWS.includes(name)) name = "dashboard";
  state.view = name;
  document.querySelectorAll("[data-target]").forEach((el) => el.classList.toggle("active", el.dataset.target === name));
  document.querySelectorAll(".view").forEach((v) => (v.hidden = v.dataset.view !== name));
  try {
    if (location.hash.slice(1) !== name) history.replaceState(null, "", `#${name}`);
  } catch (e) {
    /* sandboxed iframe: hash routing is a nicety, not required */
  }
}

function initNav() {
  document.querySelectorAll("[data-target]").forEach((el) => {
    if (el.tagName === "A") return; // Docs link navigates normally, not a tab
    el.addEventListener("click", () => setActiveTab(el.dataset.target));
  });
  setActiveTab(location.hash.slice(1) || "dashboard");
}

// ---------- Header icons: search filters the exceptions list live, flag
// jumps to it, settings shows real batch metadata from this run.
function initHeaderIcons(data) {
  const searchBtn = document.getElementById("search-btn");
  const searchInput = document.getElementById("search-input");
  const flagBtn = document.getElementById("flag-btn");
  const settingsBtn = document.getElementById("settings-btn");
  const settingsPanel = document.getElementById("settings-panel");

  function closePopovers() {
    searchInput.style.display = "none";
    settingsPanel.style.display = "none";
  }

  function showRecords(filter) {
    state.filter = filter;
    syncFilterButtons();
    setActiveTab("reconciliation");
    renderRecords();
  }

  searchBtn.addEventListener("click", () => {
    const opening = searchInput.style.display === "none";
    closePopovers();
    searchInput.style.display = opening ? "block" : "none";
    if (opening) searchInput.focus();
  });

  searchInput.addEventListener("input", () => {
    state.query = searchInput.value.trim().toLowerCase();
    document.getElementById("recon-search").value = searchInput.value;
    showRecords(state.filter);
  });

  flagBtn.addEventListener("click", () => {
    closePopovers();
    showRecords("exceptions");
  });

  settingsBtn.addEventListener("click", () => {
    const opening = settingsPanel.style.display === "none";
    closePopovers();
    if (opening) {
      settingsPanel.innerHTML = `
        <div style="color:var(--muted);margin-bottom:6px;">BATCH INFO</div>
        <div>Source: ${data.data_source}</div>
        <div>Records: ${data.batch_size}</div>
        <div>Throughput: ${data.throughput.records_per_second} rec/s</div>
        <div style="margin-top:6px;color:var(--muted);">Regenerate with:</div>
        <code style="font-size:10.5px;">python scripts/export_dashboard_data.py</code>`;
      settingsPanel.style.display = "block";
    }
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".header-icons")) closePopovers();
  });
}

function ringPath(cx, cy, r, fracStart, fracEnd) {
  const a0 = 2 * Math.PI * fracStart - Math.PI / 2;
  const a1 = 2 * Math.PI * fracEnd - Math.PI / 2;
  const x0 = cx + r * Math.cos(a0), y0 = cy + r * Math.sin(a0);
  const x1 = cx + r * Math.cos(a1), y1 = cy + r * Math.sin(a1);
  const large = fracEnd - fracStart > 0.5 ? 1 : 0;
  return `M ${x0} ${y0} A ${r} ${r} 0 ${large} 1 ${x1} ${y1}`;
}

function renderDonut(breakdown, precision) {
  const centerEl = document.getElementById("donut-center");
  centerEl.textContent = precision.toFixed(2);
  centerEl.style.color = TEAL;
  document.getElementById("donut-sub").textContent = `${breakdown.length} outcome type(s) across the batch`;

  const total = breakdown.reduce((s, b) => s + b.count, 0) || 1;
  const svg = document.getElementById("donut");
  const cx = 75, cy = 75, r = 60;
  let acc = 0;
  let paths = `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="rgba(255,255,255,0.12)" stroke-width="16"/>`;
  breakdown.forEach((b, i) => {
    const frac = b.count / total;
    const start = acc, end = acc + frac - 0.01; // small gap between segments
    const color = colorForRule(b.label, i);
    paths += `<path d="${ringPath(cx, cy, r, start, Math.max(end, start))}" fill="none"
      stroke="${color}" stroke-width="16" stroke-linecap="round"/>`;
    acc += frac;
  });
  svg.innerHTML = paths;

  const legend = document.getElementById("donut-legend");
  legend.innerHTML = breakdown
    .map((b, i) => {
      const pct = Math.round((100 * b.count) / total);
      const color = colorForRule(b.label, i);
      return `<div class="donut-legend-item">
        <span class="legend-dot filled" style="background:${color};border-color:${color}"></span>
        <span class="legend-text">${esc(b.label)}</span>
        <span class="legend-value">${b.count} · ${pct}%</span>
      </div>`;
    })
    .join("");
}

function ringTile(label, valueText, frac, color) {
  const r = 20, cx = 24, cy = 24;
  const circumference = 2 * Math.PI * r;
  const dash = Math.max(0, Math.min(1, frac)) * circumference;
  return `<div class="ring-tile">
    <svg width="48" height="48" viewBox="0 0 48 48">
      <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="rgba(255,255,255,0.15)" stroke-width="5"/>
      <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${color}" stroke-width="5"
        stroke-dasharray="${dash} ${circumference - dash}" stroke-linecap="round"
        transform="rotate(-90 ${cx} ${cy})"/>
    </svg>
    <div>
      <div class="label">${label}</div>
      <div class="value" style="color:${color}">${valueText}</div>
    </div>
  </div>`;
}

function renderRingGrid(data) {
  const el = document.getElementById("ring-grid");
  el.innerHTML = [
    ringTile("Layer 1 recall", data.scores.recall.toFixed(2), data.scores.recall, TEAL),
    ringTile("Layer 2", data.conservation.balanced ? "balanced" : "drift found", data.conservation.balanced ? 1 : 0.3, data.conservation.balanced ? TEAL : ACCENT_ORANGE),
    ringTile("Layer 3", `${(data.generalization.fixed_suite_resolution_rate * 100).toFixed(0)}%`, data.generalization.fixed_suite_resolution_rate, TEAL),
    ringTile("Re-verify", data.reverify.chain_intact ? "intact" : "broken", data.reverify.chain_intact ? 1 : 0.2, data.reverify.chain_intact ? TEAL : ACCENT_ORANGE),
  ].join("");
}

function renderProgress(data) {
  const total = data.batch_size || 1;
  const verified = total - data.exceptions.length;
  document.getElementById("confirmed-value").textContent = `₹${data.forecast.confirmed_settled_today}`;
  document.getElementById("verified-count").textContent = `${verified} / ${total}`;
  document.getElementById("exception-count").textContent = `${data.exceptions.length} / ${total}`;
  document.getElementById("verified-bar").style.width = `${(100 * verified) / total}%`;
  document.getElementById("exception-bar").style.width = `${(100 * data.exceptions.length) / total}%`;
}

function renderExceptions(data) {
  document.getElementById("exception-total-tag").textContent = `${data.exceptions.length} flagged`;
  const el = document.getElementById("exception-list");
  if (!data.exceptions.length) {
    el.innerHTML = `<div class="list-item"><span class="list-label">No exceptions in this batch</span></div>`;
    return;
  }
  el.innerHTML = data.exceptions
    .map(
      (e) => `<div class="list-item" data-payment-id="${esc(e.payment_id)}">
      <span class="list-pill">${esc(e.payment_id)}</span>
      <span class="list-label list-sub">${esc(e.reason)}</span>
      <button class="list-btn" data-payment-id="${esc(e.payment_id)}">Review</button>
    </div>`
    )
    .join("");

  el.querySelectorAll(".list-btn").forEach((btn) => {
    btn.addEventListener("click", () => openRecord(btn.dataset.paymentId));
  });
}

function renderConservationGoal(conservation) {
  const svg = document.getElementById("conservation-ring");
  const r = 30, cx = 36, cy = 36;
  const circumference = 2 * Math.PI * r;
  const frac = conservation.balanced ? 1 : 0.35;
  const dash = frac * circumference;
  const color = conservation.balanced ? TEAL : ACCENT_ORANGE;
  svg.innerHTML = `
    <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="rgba(255,255,255,0.15)" stroke-width="6"/>
    <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${color}" stroke-width="6"
      stroke-dasharray="${dash} ${circumference - dash}" stroke-linecap="round"
      transform="rotate(-90 ${cx} ${cy})"/>`;
  const valueEl = document.getElementById("conservation-value");
  valueEl.style.color = color;
  valueEl.textContent = conservation.balanced
    ? "Balanced"
    : `₹${conservation.net_drift_across_recorded_entries} drift`;
}

function renderForecast(forecast) {
  document.getElementById("forecast-value").textContent = `₹${forecast.confirmed_settled_today}`;
  document.getElementById("forecast-sub").textContent = `over a ${forecast.timeline.length}-day horizon`;
  document.getElementById("badge-confirmed").textContent = `₹${forecast.confirmed_settled_today} confirmed`;
  document.getElementById("badge-pending").textContent = `₹${forecast.pending_amount} pending`;

  const values = forecast.timeline.map((d) => parseFloat(d.projected_cash));
  const min = Math.min(...values), max = Math.max(...values);
  const range = max - min || 1;
  const w = 320, h = 90, pad = 6;
  const points = values
    .map((v, i) => {
      const x = pad + (i * (w - 2 * pad)) / (values.length - 1 || 1);
      const y = h - pad - ((v - min) / range) * (h - 2 * pad);
      return `${x},${y}`;
    })
    .join(" ");
  const areaPoints = `${pad},${h - pad} ${points} ${w - pad},${h - pad}`;
  document.getElementById("linechart").innerHTML = `
    <polygon points="${areaPoints}" fill="rgba(126,200,194,0.12)" />
    <polyline points="${points}" fill="none" stroke="${TEAL}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>`;
}

function renderAtRisk(forecast) {
  document.getElementById("at-risk-value").textContent = `₹${forecast.at_risk_amount}`;
  document.getElementById("at-risk-caption").textContent =
    `${forecast.at_risk_count} record(s) excluded from the forecast entirely, not counted as incoming cash.`;
}

function renderGeneralization(gen) {
  const pct = (gen.fixed_suite_resolution_rate * 100).toFixed(1);
  document.getElementById("generalization-value").textContent = `${pct}%`;
}

// ---------- Reconciliation view ----------
function statCell(label, value, tone) {
  return `<div class="stat-cell"><div class="stat-cell-label">${label}</div>
    <div class="stat-cell-value ${tone || ""}">${value}</div></div>`;
}

function renderReconStrip(data) {
  const s = data.scores;
  const excCount = data.exceptions.length;
  document.getElementById("recon-strip").innerHTML = [
    statCell("Records", data.batch_size),
    statCell("Verified", data.batch_size - excCount, "teal"),
    statCell("Exceptions", excCount, excCount ? "orange" : ""),
    statCell("Precision", s.precision.toFixed(2), "teal"),
    statCell("Recall", s.recall.toFixed(2), "teal"),
    statCell("Conservation", data.conservation.balanced ? "Balanced" : "Drift", data.conservation.balanced ? "teal" : "orange"),
  ].join("");
}

function filteredRecords() {
  const q = state.query;
  return state.data.records.filter((r) => {
    if (state.filter === "exceptions" && !r.is_exception) return false;
    if (state.filter === "verified" && r.is_exception) return false;
    return !q || (r.payment_id || "").toLowerCase().includes(q);
  });
}

function renderRecords() {
  if (!state.data) return;
  const body = document.getElementById("records-body");
  if (!state.data.records.length) {
    body.innerHTML = `<tr><td colspan="5" class="card-sub">This snapshot has no per-record data. Re-run scripts/export_dashboard_data.py to include it.</td></tr>`;
    document.getElementById("records-empty").hidden = true;
    return;
  }
  const rows = filteredRecords();
  body.innerHTML = rows
    .map(
      (r) => `<tr class="${r.payment_id === state.selected ? "selected" : ""}" data-payment-id="${esc(r.payment_id)}" tabindex="0">
        <td><span class="mono">${esc(r.payment_id)}</span></td>
        <td>${esc(r.method || "—")}</td>
        <td class="num">${r.amount ? "₹" + esc(r.amount) : "—"}</td>
        <td>${esc(r.rule_type || "—")}</td>
        <td><span class="pill ${r.is_exception ? "warn" : "ok"}">${r.is_exception ? "Exception" : "Verified"}</span></td>
      </tr>`
    )
    .join("");
  document.getElementById("records-empty").hidden = rows.length > 0;
}

function openRecord(paymentId) {
  state.selected = paymentId;
  state.query = "";
  state.filter = "all";
  document.getElementById("recon-search").value = "";
  syncFilterButtons();
  setActiveTab("reconciliation");
  renderRecords();
  renderDetail();
  const row = document.querySelector(`#records-body tr[data-payment-id="${CSS.escape(paymentId)}"]`);
  if (row) row.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function syncFilterButtons() {
  document.querySelectorAll("#recon-filter .seg-btn").forEach((b) => b.classList.toggle("active", b.dataset.filter === state.filter));
}

function initReconControls() {
  document.querySelectorAll("#recon-filter .seg-btn").forEach((b) =>
    b.addEventListener("click", () => {
      state.filter = b.dataset.filter;
      syncFilterButtons();
      renderRecords();
    })
  );
  document.getElementById("recon-search").addEventListener("input", (e) => {
    state.query = e.target.value.trim().toLowerCase();
    renderRecords();
  });
  const select = (tr) => {
    if (!tr) return;
    state.selected = tr.dataset.paymentId;
    renderRecords();
    renderDetail();
  };
  const body = document.getElementById("records-body");
  body.addEventListener("click", (e) => select(e.target.closest("tr[data-payment-id]")));
  body.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      select(e.target.closest("tr[data-payment-id]"));
    }
  });
}

function kv(label, value) {
  return `<div class="kv"><span>${label}</span><span class="mono">${value}</span></div>`;
}

function renderDetail() {
  const el = document.getElementById("detail-card");
  const r = state.data.records.find((x) => x.payment_id === state.selected);
  if (!r) {
    el.innerHTML = `<div class="detail-empty"><div class="card-title">Proof drill-down</div>
      <div class="card-sub" style="margin-top:6px;">Select a record to see its proof: the rule, the inputs, the generated check, and where it sits in the hash chain.</div></div>`;
    return;
  }
  const delta =
    r.expected_value != null && r.actual_value != null
      ? parseFloat(r.actual_value) - parseFloat(r.expected_value)
      : null;
  const mathBadge = r.math_ok == null ? "" : `<span class="pill ${r.math_ok ? "ok" : "warn"}">math ${r.math_ok ? "re-checked" : "failed"}</span>`;
  const linkBadge = r.link_ok == null ? "" : `<span class="pill ${r.link_ok ? "ok" : "warn"}">link ${r.link_ok ? "intact" : "broken"}</span>`;
  const inputs = Object.entries(r.inputs || {}).map(([k, v]) => kv(esc(k), esc(v))).join("");
  el.innerHTML = `
    <div class="detail-head">
      <div>
        <div class="card-title mono">${esc(r.payment_id)}</div>
        <div class="card-sub">${esc(r.reason)}</div>
      </div>
      <span class="pill ${r.is_exception ? "warn" : "ok"}">${r.is_exception ? "Exception" : "Verified"}</span>
    </div>
    <div class="detail-section">
      ${kv("Amount", r.amount ? "₹" + esc(r.amount) : "—")}
      ${kv("Method", esc(r.method || "—"))}
      ${kv("Captured", esc(r.captured_at || "—"))}
      ${kv("Ledger entry", esc(r.ledger_entry_id || "none"))}
      ${kv("Rule", esc(r.rule_type || "none"))}
      ${kv("Confidence", r.confidence != null ? r.confidence.toFixed(2) : "—")}
    </div>
    ${r.expected_value != null || r.actual_value != null ? `<div class="detail-title">Expected vs ledger</div>
    <div class="detail-section">
      ${kv("Expected (rule)", esc(r.expected_value ?? "—"))}
      ${kv("Ledger amount", esc(r.actual_value ?? "—"))}
      ${delta != null ? kv("Difference", `<span style="color:${Math.abs(delta) > 0.02 ? ACCENT_ORANGE : TEAL}">${delta.toFixed(4)}</span>`) : ""}
    </div>` : ""}
    ${inputs ? `<div class="detail-title">Inputs</div><div class="detail-section">${inputs}</div>` : ""}
    ${r.proof_code ? `<div class="detail-title">Proof script</div><pre class="code">${esc(r.proof_code.trim())}</pre>` : ""}
    <div class="detail-title">Hash chain</div>
    <div class="detail-section">
      ${kv("hash", `<span title="${esc(r.hash)}">${esc(short(r.hash))}</span>`)}
      ${kv("prev_hash", `<span title="${esc(r.prev_hash)}">${esc(short(r.prev_hash))}</span>`)}
      ${r.recomputed_value != null ? kv("re-computed", esc(r.recomputed_value)) : ""}
    </div>
    <div class="badge-row">${mathBadge}${linkBadge}</div>`;
}

// ---------- Forecast view ----------
function renderForecastView(f) {
  document.getElementById("forecast-strip").innerHTML = [
    statCell("Confirmed settled", "₹" + esc(f.confirmed_settled_today), "teal"),
    statCell("Pending", `₹${esc(f.pending_amount)} <small>(${f.pending_count})</small>`, f.pending_count ? "orange" : ""),
    statCell("At risk · excluded", `₹${esc(f.at_risk_amount)} <small>(${f.at_risk_count})</small>`, f.at_risk_count ? "orange" : ""),
    statCell("Horizon", `${f.timeline.length} days`),
  ].join("");

  document.getElementById("forecast-assumptions").innerHTML = f.assumptions.map((a) => `<li>${esc(a)}</li>`).join("");
  document.getElementById("forecast-table").innerHTML = f.timeline
    .map((d) => `<tr><td>Day ${d.day}</td><td class="num">₹${esc(d.projected_cash)}</td></tr>`)
    .join("");

  const values = f.timeline.map((d) => parseFloat(d.projected_cash));
  const lo = Math.min(...values), hi = Math.max(...values);
  // a flat series is a real answer (nothing pending), so centre it rather
  // than stretching float noise to fill the chart
  const pad = hi === lo ? Math.max(Math.abs(hi) * 0.1, 1) : (hi - lo) * 0.15;
  const min = lo - pad, max = hi + pad;
  const W = 640, H = 260, L = 72, R = 16, T = 16, B = 34;
  const x = (i) => L + (i * (W - L - R)) / (values.length - 1 || 1);
  const y = (v) => T + (1 - (v - min) / (max - min)) * (H - T - B);
  const fmt = (v) => "₹" + Math.round(v).toLocaleString("en-IN");
  const grid = [0, 1, 2, 3]
    .map((k) => {
      const v = min + ((max - min) * k) / 3;
      return `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="rgba(255,255,255,0.1)"/>
        <text x="${L - 8}" y="${y(v) + 4}" text-anchor="end" class="axis">${fmt(v)}</text>`;
    })
    .join("");
  const pts = values.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  const dots = values
    .map((v, i) => `<circle cx="${x(i)}" cy="${y(v)}" r="4" fill="#000" stroke="${TEAL}" stroke-width="2"><title>Day ${f.timeline[i].day}: ₹${f.timeline[i].projected_cash}</title></circle>`)
    .join("");
  const labels = values.map((_, i) => `<text x="${x(i)}" y="${H - 10}" text-anchor="middle" class="axis">D${f.timeline[i].day}</text>`).join("");
  document.getElementById("forecast-chart").innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Projected cash by day">
    ${grid}
    <polygon points="${L},${H - B} ${pts} ${x(values.length - 1)},${H - B}" fill="rgba(126,200,194,0.12)"/>
    <polyline points="${pts}" fill="none" stroke="${TEAL}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>
    ${dots}${labels}</svg>`;
}

// In Streamlit the dashboard is a full-screen iframe. The pipeline can only
// run from Python, so "Run again" clicks the app's own button in the parent
// page (the srcdoc frame is same-origin).
function initRerun() {
  const btn = document.getElementById("rerun-btn");
  if (!btn) return;
  let parentDoc = null;
  try {
    parentDoc = window.frameElement && window.parent.document;
  } catch (e) {
    /* cross-origin: no Streamlit to talk to */
  }
  if (!parentDoc) return;
  btn.hidden = false;
  btn.addEventListener("click", () => {
    const target = [...parentDoc.querySelectorAll("button")].find((b) => b.textContent.trim() === "Run again");
    if (!target) return;
    btn.querySelector("span").textContent = "Running…";
    target.click();
  });
}

initRerun();
main();
