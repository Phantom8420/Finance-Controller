"""Phase 5: wires real Razorpay test-mode data in as Source A, replacing
data/mock_source.py. Not usable until RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET
are set — check has_live_keys() before calling anything else here.
"""
from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal

from app.reconciliation.models import PaymentRecord


def has_live_keys() -> bool:
    return bool(os.environ.get("RAZORPAY_KEY_ID") and os.environ.get("RAZORPAY_KEY_SECRET"))


def get_client():
    import razorpay

    key_id = os.environ["RAZORPAY_KEY_ID"]
    key_secret = os.environ["RAZORPAY_KEY_SECRET"]
    return razorpay.Client(auth=(key_id, key_secret))


def seed_test_orders(n: int = 60, amount_paise: int = 50000) -> list[str]:
    """Creates n test-mode orders via the Orders API. Capturing them against
    Razorpay's documented test card numbers happens through Checkout / the
    test webhook simulator — this seeds the order side of that flow."""
    client = get_client()
    order_ids = []
    for i in range(n):
        order = client.order.create(
            {"amount": amount_paise, "currency": "INR", "receipt": f"receipt_{i:04d}"}
        )
        order_ids.append(order["id"])
    return order_ids


def fetch_payments(count: int = 100) -> list[PaymentRecord]:
    """Pulls captured payments from the test-mode Payments API and maps them
    onto our internal PaymentRecord model (paise -> rupee Decimal)."""
    client = get_client()
    payments = client.payment.all({"count": count})
    records = []
    for item in payments["items"]:
        if item["status"] != "captured":
            continue
        records.append(
            PaymentRecord(
                payment_id=item["id"],
                order_id=item["order_id"],
                amount=Decimal(item["amount"]) / Decimal(100),
                currency=item["currency"],
                method=item.get("method", "card"),
                captured_at=datetime.fromtimestamp(item["created_at"]),
                refund_amount=Decimal(item.get("amount_refunded", 0)) / Decimal(100),
            )
        )
    return records
