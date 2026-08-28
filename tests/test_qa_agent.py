from datetime import datetime
from decimal import Decimal

import pytest

from app.qa_agent import _find_relevant_proofs, answer_question
from app.reconciliation.engine import reconcile
from app.reconciliation.models import LedgerEntry, PaymentRecord

_NOW = datetime(2026, 8, 1, 9, 0, 0)


@pytest.fixture(autouse=True)
def _no_llm_calls(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def _sample_proofs():
    payments = [
        PaymentRecord(payment_id="pay_0001", order_id="o1", amount=Decimal("500.00"), captured_at=_NOW),
        PaymentRecord(payment_id="pay_0002", order_id="o2", amount=Decimal("300.00"), captured_at=_NOW),
    ]
    ledger = [
        LedgerEntry(
            entry_id="led_1", ref_payment_id="pay_0001", amount=payments[0].true_ledger_amount, recorded_at=_NOW
        )
        # pay_0002 has no ledger entry -> exception
    ]
    return payments, reconcile(payments, ledger)


def test_answer_question_gracefully_skips_without_api_key():
    payments, proofs = _sample_proofs()
    result = answer_question("why didn't pay_0002 settle?", payments, [], proofs)
    assert result["answered"] is False
    assert result["answer"] is None
    assert "not configured" in result["reason"]


def test_find_relevant_proofs_matches_mentioned_payment_id():
    _, proofs = _sample_proofs()
    matches = _find_relevant_proofs("why didn't pay_0002 settle correctly?", proofs)
    assert len(matches) == 1
    assert matches[0].payment_id == "pay_0002"


def test_find_relevant_proofs_falls_back_to_exceptions():
    _, proofs = _sample_proofs()
    matches = _find_relevant_proofs("what's still unresolved?", proofs)
    assert all(p.is_exception for p in matches)
    assert len(matches) >= 1
