"""Runs the full pipeline (mock or real data) and exports a single JSON
file the custom frontend (frontend/) reads via fetch. Same pipeline as
scripts/seed_demo_data.py, plus chart-ready aggregates derived from the
real results — nothing here is fabricated for display purposes.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app import razorpay_client
from app.forecast import forecast_cash_position
from app.invariants.conservation_check import check_conservation, try_z3_check
from app.metrics import generalization_report, measure_throughput, score_reconciliation
from app.reconciliation.proof_chain import ProofChain
from app.selftest.adversarial_gen import run_fixed_suite, run_llm_suite
from data.generate_ledger import generate_ledger
from data.mock_source import generate_mock_payments

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
_DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def _rule_type_breakdown(proofs) -> list:
    counts = Counter(p.rule_type if p.rule_type else "exception" for p in proofs)
    return [{"label": k, "count": v} for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]


def _exception_reason_breakdown(proofs) -> list:
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


def main(n: int = 60) -> None:
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

    scores = score_reconciliation(payments, ledger, proofs)
    reverify = chain.reverify_all()
    conservation = check_conservation(payments, ledger)
    z3_result = try_z3_check(payments, ledger)
    fixed_suite = run_fixed_suite()
    llm_suite = run_llm_suite()
    generalization = generalization_report(fixed_suite, llm_suite)
    forecast = forecast_cash_position(payments, proofs)

    payload = {
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
        "exceptions": [
            {"payment_id": p.payment_id, "reason": p.reason} for p in proofs if p.is_exception
        ],
    }

    FRONTEND_DIR.mkdir(parents=True, exist_ok=True)
    (FRONTEND_DIR / "data.json").write_text(json.dumps(payload, indent=2))
    print(f"Wrote {FRONTEND_DIR / 'data.json'}")


if __name__ == "__main__":
    main()
