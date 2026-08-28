"""Single-screen demo dashboard: proof chain, live re-verification, the
whole-batch conservation status, and self-discovered blind spots.

Run with: streamlit run app/dashboard/streamlit_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from app import razorpay_client
from app.forecast import forecast_cash_position
from app.invariants.conservation_check import check_conservation, try_z3_check
from app.metrics import generalization_report, measure_throughput, score_reconciliation
from app.qa_agent import answer_question
from app.reconciliation.proof_chain import ProofChain
from app.selftest.adversarial_gen import run_fixed_suite, run_llm_suite
from data.generate_ledger import generate_ledger
from data.mock_source import generate_mock_payments

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "fixtures"

st.set_page_config(page_title="AI Finance Controller", layout="wide")
st.title("AI Finance Controller")
st.caption("Prove it, balance it, break it — Razorpay AI Buildathon, Track 04")

n = st.sidebar.slider("Batch size", 20, 200, 60, step=10)
run_clicked = st.sidebar.button("Run pipeline", type="primary")

for key in ("chain", "payments", "ledger", "proofs", "throughput"):
    if key not in st.session_state:
        st.session_state[key] = None

if run_clicked:
    if razorpay_client.has_live_keys():
        st.sidebar.success("Using live Razorpay test-mode data")
        payments = razorpay_client.fetch_payments(count=n)
    else:
        st.sidebar.info("No Razorpay keys configured — using mock Source A data")
        payments = generate_mock_payments(n=n)

    ledger = generate_ledger(payments)
    throughput, proofs = measure_throughput(payments, ledger)

    chain = ProofChain()
    for proof in proofs:
        chain.append(proof)

    # Persisted to disk on every run — this is what lets
    # scripts/verify_chain.py independently re-verify outside the app,
    # against the same chain the dashboard just showed you.
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    chain.save(FIXTURES_DIR / "proof_chain.json")

    st.session_state.payments = payments
    st.session_state.ledger = ledger
    st.session_state.proofs = proofs
    st.session_state.chain = chain
    st.session_state.throughput = throughput

if st.session_state.chain is None:
    st.info("Click **Run pipeline** in the sidebar to reconcile a batch.")
    st.stop()

payments = st.session_state.payments
ledger = st.session_state.ledger
proofs = st.session_state.proofs
chain = st.session_state.chain
throughput = st.session_state.throughput

scores = score_reconciliation(payments, ledger, proofs)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Records/sec", throughput["records_per_second"])
col2.metric("Precision (in-distribution)", scores["precision"])
col3.metric("Recall (in-distribution)", scores["recall"])
col4.metric("Exception rate", scores["exception_rate"])
st.caption(
    "⚠️ Precision/recall above are measured against mismatches this "
    "engine's own rules were built to invert — see the **Layer 3** tab for "
    "the honest, out-of-distribution number."
)

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    [
        "Layer 1 — Reconciliation",
        "Re-verify everything",
        "Layer 2 — Conservation",
        "Layer 3 — Blind spots",
        "Ask the ledger (Q&A)",
        "Cash forecast",
    ]
)

with tab1:
    st.subheader("Per-record proofs")
    rows = [
        {
            "payment_id": p.payment_id,
            "matched": p.matched,
            "rule_type": p.rule_type,
            "confidence": p.confidence,
            "is_exception": p.is_exception,
            "reason": p.reason,
        }
        for p in proofs
    ]
    st.dataframe(rows, use_container_width=True)

    exceptions = [p for p in proofs if p.is_exception]
    if exceptions:
        st.subheader(f"Exception list ({len(exceptions)})")
        for p in exceptions:
            st.write(f"- **{p.payment_id}**: {p.reason}")

with tab2:
    st.subheader("Re-verify everything")
    st.caption("Re-executes every stored proof from raw inputs and re-checks the hash chain. Zero AI calls.")
    if st.button("Re-verify now"):
        result = chain.reverify_all()
        if result["chain_intact"] and result["all_math_ok"]:
            st.success(f"{result['checked']}/{result['checked']} proofs independently re-verified. Chain intact.")
        else:
            st.error("Verification failed for one or more records — see details below.")
        st.dataframe(result["records"], use_container_width=True)

    st.caption(
        f"This chain is also saved to `data/fixtures/proof_chain.json` after every run — "
        "re-verify it independently, outside this app, with:"
    )
    st.code("python scripts/verify_chain.py", language="bash")

with tab3:
    st.subheader("Whole-batch conservation proof")
    st.caption(
        "Recomputed directly from the raw payment and ledger records — this does not read "
        "Layer 1's verdicts, so a bug there wouldn't silently pass this check too."
    )
    conservation = check_conservation(payments, ledger)
    st.json(conservation)
    if conservation["balanced"]:
        st.success("No net systematic drift across recorded ledger entries.")
    else:
        st.warning(
            f"₹{conservation['net_drift_across_recorded_entries']} net drift across "
            f"{conservation['ledger_entries_compared']} recorded ledger entries — a real, "
            "systematic pattern, not random rounding noise. "
            f"₹{conservation['amount_with_no_ledger_entry']} across "
            f"{conservation['payments_with_no_ledger_entry']} payments has no ledger entry at all."
        )

    z3_result = try_z3_check(payments, ledger)
    if z3_result:
        st.caption("z3 constraint-solver check")
        st.json(z3_result)
    else:
        st.caption("z3-solver not installed — decimal-based check above stands alone.")

with tab4:
    st.subheader("Developer-authored fuzz suite")
    st.caption(
        "Fixed, hand-written edge cases (not AI-generated) that stress the exact rule set Layer 1 "
        "relies on — the honest, out-of-distribution accuracy number."
    )
    fixed_suite = run_fixed_suite()

    st.subheader("AI-generated adversarial suite")
    st.caption("Gemini invents its own bookkeeping-mistake scenarios — requires GEMINI_API_KEY.")
    llm_suite = run_llm_suite()
    if llm_suite is None:
        st.info("No GEMINI_API_KEY configured — this suite is skipped, not faked.")

    report = generalization_report(fixed_suite, llm_suite)
    st.json(report)

    if fixed_suite["blind_spots"]:
        st.subheader("Known limitations (fixed suite)")
        st.dataframe(fixed_suite["blind_spots"], use_container_width=True)
    if llm_suite and llm_suite["blind_spots"]:
        st.subheader("Known limitations (AI-generated suite)")
        st.dataframe(llm_suite["blind_spots"], use_container_width=True)

with tab5:
    st.subheader("Ask the ledger")
    st.caption(
        "Grounded only in the proof records already computed above — never re-derives a number "
        "itself, cites exactly which record(s) it used. Requires GEMINI_API_KEY."
    )
    question = st.text_input("Ask about a specific payment (e.g. \"why didn't pay_0011 settle?\") or the batch in general")
    if st.button("Ask") and question:
        result = answer_question(question, payments, ledger, proofs)
        if result["answered"]:
            st.write(result["answer"])
            st.caption(f"Grounded in: {', '.join(result['grounded_in']) or '(none)'}")
        else:
            st.info(f"Not answered — {result['reason']}")

with tab6:
    st.subheader("Cash forecast")
    st.caption(
        "A settlement-timing projection of money already captured — not a revenue forecast. "
        "Every assumption is listed explicitly below, not baked in silently."
    )
    horizon = st.slider("Horizon (days)", 3, 14, 7)
    forecast = forecast_cash_position(payments, proofs, horizon_days=horizon)

    fcol1, fcol2, fcol3 = st.columns(3)
    fcol1.metric("Confirmed settled today", f"₹{forecast['confirmed_settled_today']}")
    fcol2.metric("Pending", f"₹{forecast['pending_amount']}", f"{forecast['pending_count']} records")
    fcol3.metric("At risk (excluded)", f"₹{forecast['at_risk_amount']}", f"{forecast['at_risk_count']} records")

    st.line_chart(
        {"projected_cash": [float(day["projected_cash"]) for day in forecast["timeline"]]},
    )

    st.subheader("Assumptions")
    for a in forecast["assumptions"]:
        st.write(f"- {a}")
