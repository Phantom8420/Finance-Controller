"""Stand-in for Source A until Razorpay test-mode keys are wired in via
app/razorpay_client.py (Phase 5). Produces internally consistent payment
records with occasional partial refunds — mismatches get injected later, on
the ledger side, by generate_ledger.py.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from decimal import Decimal

from app.reconciliation.models import PaymentRecord

_METHODS = ["card", "upi", "netbanking", "wallet"]


def generate_mock_payments(n: int = 60, seed: int = 42) -> list[PaymentRecord]:
    rng = random.Random(seed)
    base_time = datetime(2026, 8, 1, 9, 0, 0)
    payments = []
    for i in range(n):
        amount = (Decimal(rng.randint(199, 49900)) / Decimal(100)).quantize(Decimal("0.01"))
        refund_amount = Decimal("0")
        if rng.random() < 0.12:
            refund_amount = (amount * Decimal(str(rng.choice([0.25, 0.5, 1.0])))).quantize(Decimal("0.01"))
        payments.append(
            PaymentRecord(
                payment_id=f"pay_{i:04d}",
                order_id=f"order_{i:04d}",
                amount=amount,
                method=rng.choice(_METHODS),
                captured_at=base_time + timedelta(hours=i * 3, minutes=rng.randint(0, 59)),
                refund_amount=refund_amount,
            )
        )
    return payments
