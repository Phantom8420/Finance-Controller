"""Standalone external verification.

Loads a saved proof chain from disk and independently re-verifies it, with
no dependency on the process that produced it — no session state, no
in-memory objects held over from a run. This is what "audit outside the
app" actually means: run this on its own, any time, against the last
saved chain, and it re-derives every hash link and re-executes every proof
script from scratch.

Usage: python scripts/verify_chain.py [path-to-proof_chain.json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.reconciliation.proof_chain import ProofChain

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "fixtures" / "proof_chain.json"


def main(path: str = str(DEFAULT_PATH)) -> None:
    chain_path = Path(path)
    if not chain_path.exists():
        print(f"No saved chain at {chain_path}. Run scripts/seed_demo_data.py or the dashboard first.")
        sys.exit(2)

    chain = ProofChain.load(chain_path)
    result = chain.reverify_all()
    print(json.dumps({k: v for k, v in result.items() if k != "records"}, indent=2))

    if result["chain_intact"] and result["all_math_ok"]:
        print(f"\n{result['checked']}/{result['checked']} proofs independently re-verified from disk. Chain intact.")
    else:
        print("\nVerification FAILED for one or more records:")
        for r in result["records"]:
            if not (r["math_ok"] and r["link_ok"]):
                print(f"  - {r}")
        sys.exit(1)


if __name__ == "__main__":
    main(*sys.argv[1:])
