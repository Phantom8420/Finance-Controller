"""One command: seed (mock or real Razorpay data) -> reconcile -> build the
proof chain -> check the whole-batch conservation invariant -> self-fuzz for
blind spots -> print a metrics summary. Run this before recording the demo
video to sanity-check the real numbers.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "data" / "fixtures"


def main(n: int = 60) -> None:
    if razorpay_client.has_live_keys():
        print("Using live Razorpay test-mode data...")
        payments = razorpay_client.fetch_payments(count=n)
    else:
        print("No Razorpay test-mode keys configured — using mock Source A data.")
        payments = generate_mock_payments(n=n)

    ledger = generate_ledger(payments)

    print(f"\n=== Layer 1: reconciling {len(payments)} payments against {len(ledger)} ledger entries ===")
    throughput, proofs = measure_throughput(payments, ledger)
    print(json.dumps(throughput, indent=2))

    chain = ProofChain()
    for proof in proofs:
        chain.append(proof)

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    chain.save(FIXTURES_DIR / "proof_chain.json")

    scores = score_reconciliation(payments, ledger, proofs)
    print("\n=== Accuracy — IN-DISTRIBUTION (rules were built to invert this exact corruption set) ===")
    print(json.dumps(scores, indent=2))

    print("\n=== Re-verify everything (zero AI calls) ===")
    reverify = chain.reverify_all()
    print(json.dumps({k: v for k, v in reverify.items() if k != "records"}, indent=2))

    print("\n=== Layer 2: whole-batch conservation check (independent of Layer 1's verdicts) ===")
    conservation = check_conservation(payments, ledger)
    print(json.dumps(conservation, indent=2))
    z3_result = try_z3_check(payments, ledger)
    if z3_result:
        print("z3 solver check:", json.dumps(z3_result, indent=2))
    else:
        print("(z3-solver not installed — decimal-based check above stands alone)")

    print("\n=== Layer 3a: developer-authored fuzz suite (fixed, always runs) ===")
    fixed_suite = run_fixed_suite()
    print(json.dumps(fixed_suite, indent=2))

    print("\n=== Layer 3b: AI-generated adversarial suite (only if GEMINI_API_KEY set) ===")
    llm_suite = run_llm_suite()
    if llm_suite is not None:
        print(json.dumps(llm_suite, indent=2))
    else:
        print("(no GEMINI_API_KEY configured — skipped)")

    print("\n=== Generalization — OUT-OF-DISTRIBUTION (the honest number) ===")
    print(json.dumps(generalization_report(fixed_suite, llm_suite), indent=2))

    known_limitations = fixed_suite["blind_spots"] + (llm_suite["blind_spots"] if llm_suite else [])
    with open(FIXTURES_DIR / "known_limitations.json", "w") as f:
        json.dump(known_limitations, f, indent=2)

    print("\n=== Stretch: cash forecast (settlement-timing projection, not a revenue forecast) ===")
    forecast = forecast_cash_position(payments, proofs)
    print(json.dumps(forecast, indent=2))

    print("\n=== Stretch: settlement Q&A ===")
    exceptions = [p for p in proofs if p.is_exception]
    if exceptions:
        sample_question = f"why didn't {exceptions[0].payment_id} settle correctly?"
        qa_result = answer_question(sample_question, payments, ledger, proofs)
        print(f"Q: {sample_question}")
        print(json.dumps(qa_result, indent=2))
    else:
        print("(no exceptions in this batch to ask about)")

    print(f"\nSaved proof chain and known limitations to {FIXTURES_DIR}")
    print("Verify the saved chain independently with: python scripts/verify_chain.py")


if __name__ == "__main__":
    main()
