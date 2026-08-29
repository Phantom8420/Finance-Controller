"""Runs the full pipeline (mock or real data) and writes frontend/data.json
- kept for standalone use (e.g. inspecting a snapshot outside Streamlit),
though the primary path is now the embedded dashboard inside
app/dashboard/streamlit_app.py, which calls app.dashboard_data.build_payload
directly on a live run instead of reading this file.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app import razorpay_client
from app.dashboard_data import build_payload
from app.metrics import measure_throughput
from app.reconciliation.proof_chain import ProofChain
from data.generate_ledger import generate_ledger
from data.mock_source import generate_mock_payments

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


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

    payload = build_payload(payments, ledger, proofs, chain, throughput, data_source)

    FRONTEND_DIR.mkdir(parents=True, exist_ok=True)
    (FRONTEND_DIR / "data.json").write_text(json.dumps(payload, indent=2))
    print(f"Wrote {FRONTEND_DIR / 'data.json'}")


if __name__ == "__main__":
    main()
