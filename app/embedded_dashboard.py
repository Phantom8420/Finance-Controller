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
