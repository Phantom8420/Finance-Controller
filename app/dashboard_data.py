"""Builds the single data payload both the CLI export script
(scripts/export_dashboard_data.py) and the Streamlit dashboard's embedded
custom frontend render. One shared function so the two never drift out of
sync with each other - a lesson learned the hard way once already (the
deployed static site shipping with no data.json at all).
"""
from __future__ import annotations

from collections import Counter
from typing import Optional

from app.forecast import forecast_cash_position
from app.invariants.conservation_check import check_conservation, try_z3_check
from app.metrics import generalization_report, score_reconciliation
from app.reconciliation.models import LedgerEntry, PaymentRecord, ProofRecord
from app.reconciliation.proof_chain import ProofChain
from app.selftest.adversarial_gen import run_fixed_suite, run_llm_suite


def _rule_type_breakdown(proofs: list[ProofRecord]) -> list:
    counts = Counter(p.rule_type if p.rule_type else "exception" for p in proofs)
    return [{"label": k, "count": v} for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]


def _exception_reason_breakdown(proofs: list[ProofRecord]) -> list:
    def _bucket(reason: str) -> str:
        if "no ledger entry" in reason:
            return "missing entry"
        if "ambiguous" in reason:
            return "duplicate entry"
        if "no rule or generated proof" in reason:
            return "unexplained gap"
        return "other"

    counts = Counter(_bucket(p.reason) for p in proofs if p.is_exception)
    total = sum(counts.values()) or 1
    return [
        {"label": k, "count": v, "pct": round(100 * v / total, 1)}
        for k, v in sorted(counts.items(), key=lambda kv: -kv[1])
    ]


def _record_rows(
    payments: list[PaymentRecord], proofs: list[ProofRecord], reverify_records: list[dict]
) -> list[dict]:
    """One row per proof, joined with its payment and its live re-verify
    result, so the frontend can drill from a record down to the proof."""
    by_payment = {p.payment_id: p for p in payments}
    checks = {r["record_id"]: r for r in reverify_records}
    rows = []
    for proof in proofs:
        payment = by_payment.get(proof.payment_id)
        check = checks.get(proof.record_id, {})
        rows.append(
            {
                "record_id": proof.record_id,
                "payment_id": proof.payment_id,
                "ledger_entry_id": proof.ledger_entry_id,
                "method": payment.method if payment else None,
                "amount": str(payment.amount) if payment else None,
                "captured_at": payment.captured_at.isoformat() if payment else None,
                "rule_type": proof.rule_type,
                "is_exception": proof.is_exception,
                "verified": proof.verified,
                "confidence": proof.confidence,
                "reason": proof.reason,
                "expected_value": str(proof.expected_value) if proof.expected_value is not None else None,
                "actual_value": str(proof.actual_value) if proof.actual_value is not None else None,
                "proof_code": proof.proof_code,
                "inputs": {k: str(v) for k, v in proof.inputs.items()},
                "hash": proof.hash,
                "prev_hash": proof.prev_hash,
                "math_ok": check.get("math_ok"),
                "link_ok": check.get("link_ok"),
                "recomputed_value": check.get("recomputed_value"),
            }
        )
    return rows


def build_payload(
    payments: list[PaymentRecord],
    ledger: list[LedgerEntry],
    proofs: list[ProofRecord],
    chain: ProofChain,
    throughput: dict,
    data_source: str,
    run_self_tests: bool = True,
) -> dict:
    """Everything the frontend needs, computed once, from one real run.
    `run_self_tests=False` skips Layer 3 (useful for callers that already
    have fixed/llm suite results and don't want to recompute them)."""
    scores = score_reconciliation(payments, ledger, proofs)
    reverify = chain.reverify_all()
    conservation = check_conservation(payments, ledger)
    z3_result = try_z3_check(payments, ledger)

    if run_self_tests:
        fixed_suite = run_fixed_suite()
        llm_suite = run_llm_suite()
    else:
        fixed_suite = {"generated": 0, "resolved": 0, "blind_spots_found": 0, "blind_spots": []}
        llm_suite = None

    generalization = generalization_report(fixed_suite, llm_suite)
    forecast = forecast_cash_position(payments, proofs)

    return {
        "data_source": data_source,
        "batch_size": len(payments),
        "throughput": throughput,
        "scores": scores,
        "reverify": {k: v for k, v in reverify.items() if k != "records"},
        "conservation": conservation,
        "z3": z3_result,
        "generalization": generalization,
        "forecast": forecast,
        "rule_type_breakdown": _rule_type_breakdown(proofs),
        "exception_reason_breakdown": _exception_reason_breakdown(proofs),
        "records": _record_rows(payments, proofs, reverify["records"]),
        "exceptions": [{"payment_id": p.payment_id, "reason": p.reason} for p in proofs if p.is_exception],
    }
