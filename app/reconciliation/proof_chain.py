"""Append-only hash chain over ProofRecords, plus the live re-verification
that powers the dashboard's "Re-verify everything" button.

Re-verification re-executes every stored proof script from its stored raw
inputs and re-derives every hash link — it never trusts the stored
`verified`/`confidence` fields, and it makes zero AI calls.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

from app.reconciliation.models import TOLERANCE, ProofRecord
from app.reconciliation.sandbox import SandboxError, run_proof_code


def _hash_record(record: ProofRecord, prev_hash: Optional[str]) -> str:
    payload = record.to_jsonable()
    payload.pop("hash", None)
    payload["prev_hash"] = prev_hash
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


class ProofChain:
    def __init__(self):
        self.records: list[ProofRecord] = []

    def append(self, record: ProofRecord) -> ProofRecord:
        prev_hash = self.records[-1].hash if self.records else None
        record.prev_hash = prev_hash
        record.hash = _hash_record(record, prev_hash)
        self.records.append(record)
        return record

    def save(self, path: Path) -> None:
        payload = [r.to_jsonable() for r in self.records]
        path.write_text(json.dumps(payload, indent=2))

    @classmethod
    def load(cls, path: Path) -> "ProofChain":
        chain = cls()
        raw = json.loads(path.read_text())
        for item in raw:
            record = ProofRecord(
                record_id=item["record_id"],
                payment_id=item.get("payment_id"),
                ledger_entry_id=item.get("ledger_entry_id"),
                matched=item["matched"],
                rule_type=item.get("rule_type"),
                proof_code=item.get("proof_code"),
                inputs=item.get("inputs", {}),
                expected_value=Decimal(item["expected_value"]) if item.get("expected_value") is not None else None,
                actual_value=Decimal(item["actual_value"]) if item.get("actual_value") is not None else None,
                verified=item["verified"],
                confidence=item["confidence"],
                is_exception=item["is_exception"],
                reason=item.get("reason", ""),
                prev_hash=item.get("prev_hash"),
                hash=item.get("hash"),
                # Must round-trip exactly, not default to "now" — created_at
                # is part of the hashed payload, so a fresh timestamp here
                # would make every reloaded record fail hash verification
                # even though nothing was actually tampered with. (Real bug,
                # caught by scripts/verify_chain.py failing on every record.)
                created_at=datetime.fromisoformat(item["created_at"]),
            )
            chain.records.append(record)
        return chain

    def reverify_all(self) -> dict:
        results = []
        chain_ok = True
        prev_hash = None
        for record in self.records:
            math_ok = True
            recomputed: Optional[Decimal] = None
            if record.proof_code and not record.is_exception:
                try:
                    recomputed = run_proof_code(record.proof_code, record.inputs)
                    math_ok = record.actual_value is not None and abs(recomputed - record.actual_value) <= TOLERANCE
                except SandboxError:
                    math_ok = False

            expected_hash = _hash_record(record, prev_hash)
            link_ok = (record.prev_hash == prev_hash) and (record.hash == expected_hash)
            if not link_ok:
                chain_ok = False

            results.append(
                {
                    "record_id": record.record_id,
                    "math_ok": math_ok,
                    "link_ok": link_ok,
                    "recomputed_value": str(recomputed) if recomputed is not None else None,
                }
            )
            prev_hash = record.hash

        return {
            "chain_intact": chain_ok,
            "all_math_ok": all(r["math_ok"] for r in results),
            "checked": len(results),
            "records": results,
        }
