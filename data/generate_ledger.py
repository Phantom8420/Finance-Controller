"""Derives a synthetic merchant internal ledger from payment records,
deliberately injecting known discrepancy types so precision/recall can be
measured against real ground truth (the `injected_issue` label), never
guessed. This is the "messy side" (Source B) the reconciliation engine has
to make sense of.
"""
from __future__ import annotations

import random
from datetime import timedelta
from decimal import Decimal

from app.reconciliation.models import LedgerEntry, PaymentRecord

_ISSUE_WEIGHTS = [
    ("exact", 0.45),
    ("gst_fee_miss", 0.15),
    ("rounding", 0.12),
    ("refund_not_reflected", 0.08),  # only ever chosen for payments with a refund
    ("duplicate_entry", 0.06),
    ("missing_entry", 0.06),
    ("unexplained", 0.08),
]


def _pick_issue(rng: random.Random, has_refund: bool) -> str:
    choices = _ISSUE_WEIGHTS if has_refund else [w for w in _ISSUE_WEIGHTS if w[0] != "refund_not_reflected"]
    total = sum(w for _, w in choices)
    r = rng.random() * total
    upto = 0.0
    for issue, weight in choices:
        upto += weight
        if r <= upto:
            return issue
    return "exact"


def generate_ledger(payments: list[PaymentRecord], seed: int = 7) -> list[LedgerEntry]:
    rng = random.Random(seed)
    entries: list[LedgerEntry] = []

    for i, payment in enumerate(payments):
        issue = _pick_issue(rng, payment.refund_amount > 0)
        recorded_at = payment.captured_at + timedelta(hours=rng.randint(1, 48))

        if issue == "missing_entry":
            continue

        if issue == "exact":
            amount = payment.true_ledger_amount
        elif issue == "gst_fee_miss":
            amount = payment.true_ledger_amount + payment.gst
        elif issue == "rounding":
            noise = Decimal(rng.choice([-2, -1, 1, 2])) / Decimal(100)
            amount = payment.true_ledger_amount + noise
        elif issue == "refund_not_reflected":
            amount = payment.net_settlement  # refund deliberately not subtracted
        elif issue == "unexplained":
            garbage = Decimal(rng.randint(100, 5000)) / Decimal(100)
            amount = payment.true_ledger_amount + garbage
        else:  # duplicate_entry uses the correct amount for its primary row
            amount = payment.true_ledger_amount

        amount = amount.quantize(Decimal("0.01"))
        entries.append(
            LedgerEntry(
                entry_id=f"led_{i:04d}",
                ref_payment_id=payment.payment_id,
                amount=amount,
                recorded_at=recorded_at,
                note=f"auto-recorded ({issue})" if issue != "exact" else "auto-recorded",
                injected_issue=None if issue == "exact" else issue,
            )
        )

        if issue == "duplicate_entry":
            dup_amount = (amount + Decimal(rng.choice([-1, 1])) / Decimal(100)).quantize(Decimal("0.01"))
            entries.append(
                LedgerEntry(
                    entry_id=f"led_{i:04d}_dup",
                    ref_payment_id=payment.payment_id,
                    amount=dup_amount,
                    recorded_at=recorded_at + timedelta(hours=1),
                    note="duplicate manual entry",
                    injected_issue="duplicate_entry",
                )
            )

    return entries
