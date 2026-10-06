from datetime import datetime
from decimal import Decimal

import pytest

from app.dashboard_data import build_payload
from app.embedded_dashboard import build_embedded_html, build_empty_state_html
from app.reconciliation.engine import reconcile
from app.reconciliation.models import LedgerEntry, PaymentRecord
from app.reconciliation.proof_chain import ProofChain

_NOW = datetime(2026, 8, 1, 9, 0, 0)


@pytest.fixture(autouse=True)
def _no_llm_calls(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def _sample_run():
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
    proofs = reconcile(payments, ledger)
    chain = ProofChain()
    for proof in proofs:
        chain.append(proof)
    return payments, ledger, proofs, chain


def test_build_payload_has_expected_shape():
    payments, ledger, proofs, chain = _sample_run()
    throughput = {"records": 2, "seconds": 0.01, "records_per_second": 200.0}
    payload = build_payload(payments, ledger, proofs, chain, throughput, "mock", run_self_tests=False)

    for key in (
        "data_source",
        "batch_size",
        "throughput",
        "scores",
        "reverify",
        "conservation",
        "generalization",
        "forecast",
        "rule_type_breakdown",
        "exception_reason_breakdown",
        "exceptions",
    ):
        assert key in payload

    assert payload["batch_size"] == 2
    assert payload["data_source"] == "mock"
    assert len(payload["exceptions"]) == 1
    assert payload["exceptions"][0]["payment_id"] == "pay_0002"
    assert payload["reverify"]["chain_intact"] is True


def test_build_payload_is_json_serializable():
    import json

    payments, ledger, proofs, chain = _sample_run()
    throughput = {"records": 2, "seconds": 0.01, "records_per_second": 200.0}
    payload = build_payload(payments, ledger, proofs, chain, throughput, "mock", run_self_tests=False)
    json.dumps(payload)  # raises if anything non-serializable (e.g. a raw Decimal) leaked through


def test_build_payload_includes_per_record_proofs():
    payments, ledger, proofs, chain = _sample_run()
    throughput = {"records": 2, "seconds": 0.01, "records_per_second": 200.0}
    payload = build_payload(payments, ledger, proofs, chain, throughput, "mock", run_self_tests=False)

    records = payload["records"]
    assert [r["payment_id"] for r in records] == ["pay_0001", "pay_0002"]
    assert [r["is_exception"] for r in records] == [False, True]
    for r in records:
        assert r["hash"] and r["math_ok"] is not None and r["link_ok"] is True
        assert all(isinstance(v, str) for v in r["inputs"].values())


def test_build_embedded_html_inlines_css_and_injects_data():
    payments, ledger, proofs, chain = _sample_run()
    throughput = {"records": 2, "seconds": 0.01, "records_per_second": 200.0}
    payload = build_payload(payments, ledger, proofs, chain, throughput, "mock", run_self_tests=False)

    html = build_embedded_html(payload)

    assert '<link rel="stylesheet"' not in html  # inlined, not a broken external reference
    assert "<style>" in html
    assert "window.__DASHBOARD_DATA__" in html
    assert '<script src="app.js">' not in html  # inlined, not a broken external reference
    assert "pay_0002" in html  # real data actually made it into the page


def test_empty_state_shares_the_same_design_language():
    html = build_empty_state_html()
    assert "<style>" in html
    assert 'class="shell"' in html  # same shell/card classes as the real dashboard
    assert 'class="card"' in html
    assert "Run pipeline" in html
