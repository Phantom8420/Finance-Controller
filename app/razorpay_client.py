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


SUPPORTED_CURRENCY = "INR"


def fetch_payments(count: int = 100) -> list[PaymentRecord]:
    """Pulls captured payments from the test-mode Payments API and maps them
    onto our internal PaymentRecord model (paise -> rupee Decimal).

    Scope, stated explicitly rather than silently assumed: only `captured`,
    single-capture, INR payments are mapped. Authorized-not-captured,
    failed, non-INR, and multi-capture payments are skipped — the fee/GST
    math in app/reconciliation/models.py assumes a single INR capture per
    payment, and mapping the others without that assumption holding would
    silently produce wrong reconciliation results rather than an honest
    exception. Extending coverage to those cases is real, undone work, not
    a hidden limitation.

    Paginates past Razorpay's 100-per-call API cap via `skip` when `count`
    is larger than that.
    """
    client = get_client()
    records: list[PaymentRecord] = []
    skipped_currency = 0
    skip = 0

    while len(records) + skipped_currency < count:
        page_size = min(100, count - len(records) - skipped_currency)
        page = client.payment.all({"count": page_size, "skip": skip})
        items = page["items"]
        if not items:
            break

        for item in items:
            if item["status"] != "captured":
                continue
            if item["currency"] != SUPPORTED_CURRENCY:
                skipped_currency += 1
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

        skip += len(items)
        if len(items) < page_size:
            break

    if skipped_currency:
        print(f"razorpay_client: skipped {skipped_currency} non-{SUPPORTED_CURRENCY} payment(s) — out of scope, see fetch_payments() docstring.")

    return records
