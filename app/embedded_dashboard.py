"""Assembles frontend/{index.html,styles.css,app.js} into one self-
contained HTML string with live data injected, for rendering inside
Streamlit via st.components.v1.html(). The frontend/ files stay the
single source of truth for the design — this just inlines and feeds them
a real payload at render time, instead of duplicating the design as a
Python string or relying on a stale pre-generated data.json.
"""
from __future__ import annotations

import json
from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

_EMPTY_STATE_TEMPLATE = """<!doctype html>
<html><head><meta charset="UTF-8" /><style>{css}</style></head>
<body style="display:flex;align-items:center;justify-content:center;min-height:100vh;">
  <div class="shell" style="max-width:480px;display:flex;flex-direction:column;align-items:center;text-align:center;padding:40px 32px;">
    <div class="brand-mark" style="margin-bottom:16px;">🧾</div>
    <div style="font-size:20px;font-weight:700;">AI Finance Controller</div>
    <div style="color:var(--muted);font-size:13px;margin:6px 0 22px;">
      Prove it, balance it, break it — Razorpay AI Buildathon, Track 04
    </div>
    <div class="card" style="width:100%;">
      <div style="font-size:13.5px;">
        Click <strong style="color:var(--teal)">Run pipeline</strong> in the sidebar to reconcile a batch.
      </div>
    </div>
  </div>
</body></html>"""


def build_empty_state_html() -> str:
    """Landing state, before the first pipeline run — same shell, brand
    mark, and card styling as the real dashboard, so the two don't look
    like two different apps."""
    css = (FRONTEND_DIR / "styles.css").read_text(encoding="utf-8")
    return _EMPTY_STATE_TEMPLATE.format(css=css)


_SIDEBAR_CSS = """
<style>
[data-testid="stSidebar"] {
  background: #030303;
  border-right: 1px solid rgba(255,255,255,0.08);
}
[data-testid="stSidebar"] * {
  font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

.sidebar-brand {
  display: flex; align-items: center; gap: 12px;
  padding-bottom: 18px; margin-bottom: 20px;
  border-bottom: 1px solid rgba(255,255,255,0.1);
}
.sidebar-brand .mark {
  width: 40px; height: 40px; border-radius: 50%; flex-shrink: 0;
  border: 1.5px solid #7ec8c2;
  display: flex; align-items: center; justify-content: center;
  font-size: 18px;
}
.sidebar-brand .title { font-weight: 700; font-size: 15px; color: #fff; line-height: 1.3; }
.sidebar-brand .subtitle { font-size: 11px; color: rgba(255,255,255,0.55); margin-top: 1px; }

.sidebar-status {
  border: 1px solid rgba(255,255,255,0.12); border-radius: 12px;
  padding: 10px 12px; margin-top: 14px; font-size: 11.5px;
  color: rgba(255,255,255,0.7); line-height: 1.6;
}
.sidebar-status b { color: #7ec8c2; }

/* slider */
[data-testid="stSlider"] [role="slider"] {
  background-color: #7ec8c2 !important;
  border-color: #7ec8c2 !important;
}
[data-testid="stTickBar"] { display: none; }
[data-baseweb="slider"] > div > div:nth-child(2) { background: #7ec8c2 !important; }

/* primary button, pill-styled to match the dashboard's own CTA */
[data-testid="stSidebar"] .stButton > button {
  background: transparent !important;
  border: 1.5px solid #7ec8c2 !important;
  color: #7ec8c2 !important;
  border-radius: 999px !important;
  font-weight: 600 !important;
  transition: background 0.15s ease, color 0.15s ease;
}
[data-testid="stSidebar"] .stButton > button:hover {
  background: #7ec8c2 !important;
  color: #000 !important;
}

/* alert boxes (success/info) */
[data-testid="stSidebar"] [data-testid="stAlert"] {
  border-radius: 12px !important;
  border: 1px solid rgba(255,255,255,0.12) !important;
}
</style>
"""


def build_sidebar_css() -> str:
    """Reskins Streamlit's native sidebar widgets (slider, button, alerts)
    to match the embedded dashboard's design system, since those widgets
    have to stay real Streamlit components — they trigger an actual
    Python pipeline run, which nothing inside the sandboxed iframe can do."""
    return _SIDEBAR_CSS


def build_sidebar_brand_html() -> str:
    return (
        '<div class="sidebar-brand">'
        '<div class="mark">🧾</div>'
        "<div>"
        '<div class="title">AI Finance Controller</div>'
        '<div class="subtitle">Track 04 · Prove it, balance it, break it</div>'
        "</div>"
        "</div>"
    )


def build_sidebar_status_html(data_source: str, batch_size: int) -> str:
    label = "Razorpay test-mode" if data_source == "razorpay_test_mode" else "Mock"
    return (
        '<div class="sidebar-status">'
        f"<div>Source: <b>{label}</b></div>"
        f"<div>Records: <b>{batch_size}</b></div>"
        "</div>"
    )


def build_embedded_html(data: dict) -> str:
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    css = (FRONTEND_DIR / "styles.css").read_text(encoding="utf-8")
    js = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    html = html.replace(
        '<link rel="stylesheet" href="styles.css" />',
        f"<style>{css}</style>",
    )
    data_script = f"<script>window.__DASHBOARD_DATA__ = {json.dumps(data)};</script>"
    html = html.replace(
        '<script src="app.js"></script>',
        f"{data_script}\n<script>{js}</script>",
    )
    return html
