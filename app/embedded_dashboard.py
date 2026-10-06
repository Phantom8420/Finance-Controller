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

_PAGE_CSS = """
<style>
html, body, [data-testid="stApp"] { background: #000; }
header[data-testid="stHeader"], [data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"], [data-testid="stToolbar"] { display: none; }
.block-container {
  min-height: 100vh; max-width: 420px;
  display: flex; flex-direction: column; justify-content: center; gap: 0.9rem;
}
/* the dock clicks this from inside the iframe, so it only has to exist */
.st-key-rerun { position: fixed; left: -9999px; }

.landing { text-align: center; }
.landing .mark {
  width: 56px; height: 56px; border-radius: 50%; margin: 0 auto 14px;
  border: 1.5px solid #7ec8c2; font-size: 24px;
  display: flex; align-items: center; justify-content: center;
}
.landing .title { font-size: 24px; font-weight: 700; color: #fff; }
.landing .subtitle { font-size: 13px; color: rgba(255,255,255,0.55); margin-top: 6px; }

[data-testid="stSlider"] [role="slider"] { background-color: #7ec8c2 !important; border-color: #7ec8c2 !important; }
[data-testid="stTickBar"] { display: none; }
[data-baseweb="slider"] > div > div:nth-child(2) { background: #7ec8c2 !important; }

.stButton > button {
  background: transparent !important; border: 1.5px solid #7ec8c2 !important;
  color: #7ec8c2 !important; border-radius: 999px !important; font-weight: 600 !important;
  transition: background 0.15s ease, color 0.15s ease;
}
.stButton > button:hover { background: #7ec8c2 !important; color: #000 !important; }
</style>
"""

# After a run the dashboard owns the screen: the iframe is pinned to the
# viewport and Streamlit's own padding goes away.
_FULLSCREEN_CSS = """
<style>
.block-container { max-width: none; padding: 0; min-height: 0; }
iframe { position: fixed; inset: 0; width: 100vw; height: 100vh; border: 0; z-index: 1000; }
</style>
"""


def build_page_css() -> str:
    return _PAGE_CSS


def build_fullscreen_css() -> str:
    return _FULLSCREEN_CSS


def build_landing_html() -> str:
    return (
        '<div class="landing">'
        '<div class="mark">🧾</div>'
        '<div class="title">AI Finance Controller</div>'
        '<div class="subtitle">Track 04 · Prove it, balance it, break it</div>'
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
