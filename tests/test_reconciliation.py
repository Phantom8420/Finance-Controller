from datetime import datetime
from decimal import Decimal

import pytest

from app.reconciliation.engine import reconcile
from app.reconciliation.models import LedgerEntry, PaymentRecord

_NOW = datetime(2026, 8, 1, 9, 0, 0)


@pytest.fixture(autouse=True)
def _no_llm_calls(monkeypatch):
    # Keep the test suite deterministic and offline regardless of local .env
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def _payment(payment_id: str = "pay_1", amount: str = "500.00", refund: str = "0") -> PaymentRecord:
    return PaymentRecord(
        payment_id=payment_id,
        order_id=f"order_{payment_id}",
        amount=Decimal(amount),
        captured_at=_NOW,
        refund_amount=Decimal(refund),
    )


def test_exact_match_resolves_with_net_settlement_rule():
    payment = _payment()
    ledger = [
        LedgerEntry(
            entry_id="led_1",
            ref_payment_id=payment.payment_id,
            amount=payment.true_ledger_amount,
            recorded_at=_NOW,
        )
    ]
    proofs = reconcile([payment], ledger)
    assert len(proofs) == 1
    assert proofs[0].verified is True
    assert proofs[0].rule_type == "net_settlement"
    assert proofs[0].is_exception is False


def test_gst_fee_miss_is_explained_by_its_rule():
    payment = _payment()
    ledger_amount = payment.true_ledger_amount + payment.gst  # gst forgotten
    ledger = [LedgerEntry(entry_id="led_1", ref_payment_id=payment.payment_id, amount=ledger_amount, recorded_at=_NOW)]
    proofs = reconcile([payment], ledger)
    assert proofs[0].verified is True
    assert proofs[0].rule_type == "gst_fee_miss"


def test_refund_not_reflected_is_explained_by_its_rule():
    payment = _payment(refund="50.00")
    ledger_amount = payment.net_settlement  # refund not subtracted
    ledger = [LedgerEntry(entry_id="led_1", ref_payment_id=payment.payment_id, amount=ledger_amount, recorded_at=_NOW)]
    proofs = reconcile([payment], ledger)
    assert proofs[0].verified is True
    assert proofs[0].rule_type == "refund_not_reflected"


def test_rounding_noise_within_tolerance_resolves():
    payment = _payment()
    ledger_amount = (payment.true_ledger_amount + Decimal("0.02")).quantize(Decimal("0.01"))
    ledger = [LedgerEntry(entry_id="led_1", ref_payment_id=payment.payment_id, amount=ledger_amount, recorded_at=_NOW)]
    proofs = reconcile([payment], ledger)
    assert proofs[0].verified is True


def test_missing_ledger_entry_becomes_exception():
    payment = _payment()
    proofs = reconcile([payment], [])
    assert proofs[0].is_exception is True
    assert "no ledger entry" in proofs[0].reason


def test_duplicate_ledger_entries_become_exception():
    payment = _payment()
    ledger = [
        LedgerEntry(
            entry_id="led_1", ref_payment_id=payment.payment_id, amount=payment.true_ledger_amount, recorded_at=_NOW
        ),
        LedgerEntry(
            entry_id="led_1_dup",
            ref_payment_id=payment.payment_id,
            amount=payment.true_ledger_amount,
            recorded_at=_NOW,
        ),
    ]
    proofs = reconcile([payment], ledger)
    assert proofs[0].is_exception is True
    assert "ambiguous" in proofs[0].reason


def test_unexplained_gap_is_never_force_matched():
    payment = _payment()
    ledger_amount = (payment.true_ledger_amount + Decimal("37.42")).quantize(Decimal("0.01"))
    ledger = [LedgerEntry(entry_id="led_1", ref_payment_id=payment.payment_id, amount=ledger_amount, recorded_at=_NOW)]
    proofs = reconcile([payment], ledger)
    assert proofs[0].is_exception is True
    assert proofs[0].verified is False
