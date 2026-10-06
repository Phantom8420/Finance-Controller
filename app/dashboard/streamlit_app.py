"""Streamlit shell around the custom black/teal/orange dashboard: a centred
landing page (batch size, Run pipeline) triggers a real pipeline run, then
the dashboard takes over the whole screen with "Run again" in its nav dock;
whose results are injected into the same frontend/{index.html,styles.css,
app.js} used by the standalone static site — rendered here via
st.components.v1.html(), so there's one canonical design, fed by a live
run instead of a pre-generated snapshot.

Run with: streamlit run app/dashboard/streamlit_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit.components.v1 as components
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from app import razorpay_client
from app.dashboard_data import build_payload
from app.embedded_dashboard import (
    build_embedded_html,
    build_fullscreen_css,
    build_landing_html,
    build_page_css,
)
from app.metrics import measure_throughput
from app.reconciliation.proof_chain import ProofChain
from data.generate_ledger import generate_ledger
from data.mock_source import generate_mock_payments

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "fixtures"

st.set_page_config(page_title="AI Finance Controller", layout="wide", initial_sidebar_state="collapsed")

st.markdown(build_page_css(), unsafe_allow_html=True)

if "payload" not in st.session_state:
    st.session_state.payload = None
    st.session_state.n = 60

# "Run again" lives in the dashboard's nav dock; the dock clicks this button
# (kept off-screen) because only Python can run the pipeline.
rerun_clicked = st.button("Run again", key="rerun")
run_clicked = False

if st.session_state.payload is None:
    st.markdown(build_landing_html(), unsafe_allow_html=True)
    st.session_state.n = st.slider("Batch size", 20, 200, st.session_state.n, step=10)
    run_clicked = st.button("Run pipeline", type="primary", use_container_width=True)

if run_clicked or rerun_clicked:
    n = st.session_state.n
    if razorpay_client.has_live_keys():
        payments = razorpay_client.fetch_payments(count=n)
        data_source = "razorpay_test_mode"
    else:
        payments = generate_mock_payments(n=n)
        data_source = "mock"

    ledger = generate_ledger(payments)
    throughput, proofs = measure_throughput(payments, ledger)

    chain = ProofChain()
    for proof in proofs:
        chain.append(proof)

    # Persisted to disk on every run — this is what lets
    # scripts/verify_chain.py independently re-verify outside the app,
    # against the same chain this run just showed.
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    chain.save(FIXTURES_DIR / "proof_chain.json")

    with st.spinner("Running Layer 3 self-tests…"):
        payload = build_payload(payments, ledger, proofs, chain, throughput, data_source)

    st.session_state.payload = payload
    st.rerun()

if st.session_state.payload is not None:
    st.markdown(build_fullscreen_css(), unsafe_allow_html=True)
    components.html(build_embedded_html(st.session_state.payload), height=900, scrolling=True)
