from datetime import datetime
from decimal import Decimal

from app.reconciliation.engine import reconcile
from app.reconciliation.models import LedgerEntry, PaymentRecord
from app.reconciliation.proof_chain import ProofChain

_NOW = datetime(2026, 8, 1, 9, 0, 0)


def _sample_proofs():
    payments = [
        PaymentRecord(payment_id=f"pay_{i}", order_id=f"order_{i}", amount=Decimal("500.00"), captured_at=_NOW)
        for i in range(3)
    ]
    ledger = [
        LedgerEntry(
            entry_id=f"led_{i}", ref_payment_id=p.payment_id, amount=p.true_ledger_amount, recorded_at=_NOW
        )
        for i, p in enumerate(payments)
    ]
    return reconcile(payments, ledger)


def test_reverify_all_passes_in_memory():
    chain = ProofChain()
    for proof in _sample_proofs():
        chain.append(proof)

    result = chain.reverify_all()
    assert result["chain_intact"] is True
    assert result["all_math_ok"] is True


def test_chain_round_trips_through_disk(tmp_path):
    # Regression test: an earlier version of ProofChain.load() didn't
    # restore created_at, so every reloaded record got a fresh timestamp
    # and failed hash verification even though nothing was tampered with.
    chain = ProofChain()
    for proof in _sample_proofs():
        chain.append(proof)

    path = tmp_path / "chain.json"
    chain.save(path)

    reloaded = ProofChain.load(path)
    result = reloaded.reverify_all()
    assert result["chain_intact"] is True
    assert result["all_math_ok"] is True
    assert result["checked"] == len(chain.records)


def test_tampering_breaks_chain_integrity(tmp_path):
    chain = ProofChain()
    for proof in _sample_proofs():
        chain.append(proof)

    path = tmp_path / "chain.json"
    chain.save(path)

    raw = path.read_text().replace('"matched": true', '"matched": false', 1)
    path.write_text(raw)

    reloaded = ProofChain.load(path)
    result = reloaded.reverify_all()
    assert result["chain_intact"] is False
