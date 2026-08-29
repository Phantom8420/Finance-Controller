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
