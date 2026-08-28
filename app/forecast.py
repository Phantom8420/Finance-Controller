"""Cash forecast — projects near-term cash position from what Layer 1 has
already verified, spread across Razorpay's documented settlement cycle.

This is a projection built from explicitly-stated assumptions, not a
prediction claiming certainty — every assumption it relies on is listed in
the output rather than baked in silently. It deliberately does not model
future refunds/chargebacks beyond what's already in the batch: it answers
"when does money already captured actually land", not "how much revenue
will we make."
"""
from __future__ import annotations

from decimal import Decimal

from app.reconciliation.models import PaymentRecord, ProofRecord

DEFAULT_SETTLEMENT_LAG_DAYS = 2  # Razorpay's standard T+2 cycle — a documented, stated assumption


def forecast_cash_position(
    payments: list[PaymentRecord],
    proofs: list[ProofRecord],
    horizon_days: int = 7,
    settlement_lag_days: int = DEFAULT_SETTLEMENT_LAG_DAYS,
) -> dict:
    proofs_by_payment = {p.payment_id: p for p in proofs if p.payment_id}

    confirmed_settled = Decimal("0")
    pending_amount = Decimal("0")
    pending_count = 0
    at_risk_amount = Decimal("0")  # tied up in exceptions — genuinely uncertain, not "pending"
    at_risk_count = 0

    for payment in payments:
        proof = proofs_by_payment.get(payment.payment_id)
        if proof and proof.verified and proof.actual_value is not None:
            confirmed_settled += proof.actual_value
        elif proof and proof.is_exception:
            at_risk_amount += payment.true_ledger_amount
            at_risk_count += 1
        else:
            pending_amount += payment.true_ledger_amount
            pending_count += 1

    # Spread pending amount evenly across the settlement-lag window — the
    # simplest honest assumption available without a real settlement
    # schedule. Per-payment actual timing would come from Razorpay's
    # Settlements API directly (Phase 5, once real keys are wired in).
    lag = max(settlement_lag_days, 1)
    daily_pending = (pending_amount / Decimal(lag)) if pending_amount else Decimal("0")

    timeline = []
    running_total = confirmed_settled
    for day in range(horizon_days):
        if day < lag:
            running_total += daily_pending
        timeline.append({"day": day, "projected_cash": str(running_total.quantize(Decimal("0.01")))})

    return {
        "confirmed_settled_today": str(confirmed_settled.quantize(Decimal("0.01"))),
        "pending_amount": str(pending_amount.quantize(Decimal("0.01"))),
        "pending_count": pending_count,
        "at_risk_amount": str(at_risk_amount.quantize(Decimal("0.01"))),
        "at_risk_count": at_risk_count,
        "assumptions": [
            f"Pending (unresolved, not flagged) amounts settle evenly over the next {lag} day(s) "
            f"— Razorpay's documented T+{lag} cycle.",
            f"₹{at_risk_amount} tied to {at_risk_count} exception(s) is excluded from the "
            "projection entirely, not counted as incoming cash, until a human resolves it.",
            "No future refunds/chargebacks are modeled beyond what's already in this batch — "
            "this is a settlement-timing projection of money already captured, not a revenue forecast.",
        ],
        "timeline": timeline,
    }
