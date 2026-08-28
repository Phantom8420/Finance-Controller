from datetime import datetime
from decimal import Decimal

from app.forecast import forecast_cash_position
from app.reconciliation.engine import reconcile
from app.reconciliation.models import LedgerEntry, PaymentRecord

_NOW = datetime(2026, 8, 1, 9, 0, 0)


def test_forecast_separates_confirmed_pending_and_at_risk():
    payments = [
        PaymentRecord(payment_id="pay_ok", order_id="o1", amount=Decimal("500.00"), captured_at=_NOW),
        PaymentRecord(payment_id="pay_missing", order_id="o2", amount=Decimal("300.00"), captured_at=_NOW),
    ]
    ledger = [
        LedgerEntry(
            entry_id="led_ok",
            ref_payment_id="pay_ok",
            amount=payments[0].true_ledger_amount,
            recorded_at=_NOW,
        )
        # pay_missing has no ledger entry -> exception -> at-risk, not pending
    ]
    proofs = reconcile(payments, ledger)
    result = forecast_cash_position(payments, proofs, horizon_days=3, settlement_lag_days=2)

    assert result["confirmed_settled_today"] == str(payments[0].true_ledger_amount.quantize(Decimal("0.01")))
    assert result["at_risk_count"] == 1
    assert Decimal(result["at_risk_amount"]) == payments[1].true_ledger_amount
    assert len(result["timeline"]) == 3
    assert len(result["assumptions"]) == 3


def test_forecast_timeline_is_non_decreasing():
    payments = [
        PaymentRecord(payment_id=f"pay_{i}", order_id=f"o{i}", amount=Decimal("100.00"), captured_at=_NOW)
        for i in range(5)
    ]
    # no ledger at all -> every payment is an exception (at-risk, not pending)
    proofs = reconcile(payments, [])
    result = forecast_cash_position(payments, proofs, horizon_days=5, settlement_lag_days=2)

    values = [Decimal(day["projected_cash"]) for day in result["timeline"]]
    assert values == sorted(values)
