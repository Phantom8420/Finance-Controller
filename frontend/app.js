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

async function main() {
  const res = await fetch("data.json");
  if (!res.ok) {
    document.getElementById("subtitle").textContent =
      "data.json not found — run: python scripts/export_dashboard_data.py";
    return;
  }
  render(await res.json());
}

function render(data) {
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

  document.getElementById("reverify-btn").addEventListener("click", () => {
    alert(
      data.reverify.chain_intact && data.reverify.all_math_ok
        ? `${data.reverify.checked}/${data.reverify.checked} proofs independently re-verified. Chain intact. Zero AI calls.`
        : "Verification found an issue — see scripts/verify_chain.py output."
    );
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
        <span class="legend-text">${b.label}</span>
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
      (e) => `<div class="list-item">
      <span class="list-pill">${e.payment_id}</span>
      <span class="list-label list-sub">${e.reason}</span>
      <button class="list-btn">Review</button>
    </div>`
    )
    .join("");
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

main();
