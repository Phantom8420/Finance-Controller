"""Runs the full pipeline (mock or real data) and writes frontend/data.json
- kept for standalone use (e.g. inspecting a snapshot outside Streamlit),
though the primary path is now the embedded dashboard inside
app/dashboard/streamlit_app.py, which calls app.dashboard_data.build_payload
directly on a live run instead of reading this file.
"""
from __future__ import annotations

import argparse
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


def main(n: int = 60, mock: bool = False) -> None:
    if razorpay_client.has_live_keys() and not mock:
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

    out = FRONTEND_DIR / ("data.demo.json" if mock else "data.json")
    FRONTEND_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", type=int, default=60, help="batch size")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="force mock data (with injected mismatches) into data.demo.json; open the dashboard with ?demo",
    )
    args = parser.parse_args()
    main(n=args.n, mock=args.mock)
