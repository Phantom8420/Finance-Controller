"""Streamlit shell around the custom black/teal/orange dashboard: native
sidebar controls (batch size, Run pipeline) trigger a real pipeline run,
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
from app.embedded_dashboard import build_embedded_html, build_empty_state_html
from app.metrics import measure_throughput
from app.reconciliation.proof_chain import ProofChain
from data.generate_ledger import generate_ledger
from data.mock_source import generate_mock_payments

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "fixtures"

st.set_page_config(page_title="AI Finance Controller", layout="wide")

n = st.sidebar.slider("Batch size", 20, 200, 60, step=10)
run_clicked = st.sidebar.button("Run pipeline", type="primary")
st.sidebar.caption("Prove it, balance it, break it — Track 04")

if "payload" not in st.session_state:
    st.session_state.payload = None

if run_clicked:
    if razorpay_client.has_live_keys():
        st.sidebar.success("Using live Razorpay test-mode data")
        payments = razorpay_client.fetch_payments(count=n)
        data_source = "razorpay_test_mode"
    else:
        st.sidebar.info("No Razorpay keys configured — using mock Source A data")
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

if st.session_state.payload is None:
    components.html(build_empty_state_html(), height=400)
    st.stop()

components.html(build_embedded_html(st.session_state.payload), height=950, scrolling=True)
