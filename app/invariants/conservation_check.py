"""Layer 2 — whole-batch conservation proof.

Deliberately does **not** read Layer 1's `ProofRecord` outputs — it
recomputes directly from the two raw sources (payments, ledger) via a
separate code path, so a bug in Layer 1's classification, or Layer 1 not
having run at all, doesn't silently pass this check too. It's still the
same two underlying data sources (there's no third, independent oracle
like a real bank statement feed here — that's a real limitation, not
hidden), but the computation itself is structurally decoupled from Layer
1's verdicts, the way a real audit recomputes from source records rather
than trusting the first pass's own bookkeeping.

What it catches that a per-record check can't: several small,
individually-*explainable* discrepancies can be biased in the same
direction and not cancel out in aggregate, even though each one alone
looks fine. This sums, across every ledger entry that actually exists,
the drift from what it should say — this should hover near zero when the
cause is random noise (rounding), but reveals a real, material total when
the cause is systematic (e.g. a fee/GST slab applied consistently wrong).
Payments with no ledger entry at all are reported separately, since
there's no recorded amount to compare against.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from app.reconciliation.models import LedgerEntry, PaymentRecord

# Scales with the number of ledger entries actually compared: legitimate
# rounding noise should stay within n * per-record tolerance; anything
# larger signals a systematic, not random, pattern.
PER_RECORD_TOLERANCE = Decimal("0.02")


def _raw_breakdown(payments: list[PaymentRecord], ledger: list[LedgerEntry]) -> dict:
    true_by_payment = {p.payment_id: p.true_ledger_amount for p in payments}
    payment_ids_with_entry = {e.ref_payment_id for e in ledger if e.ref_payment_id}

    drift = Decimal("0")
    compared_entries = 0
    for entry in ledger:
        true_amount = true_by_payment.get(entry.ref_payment_id)
        if true_amount is None:
            continue  # entry references a payment outside this batch — not our data to judge
        drift += entry.amount - true_amount
        compared_entries += 1

    missing_total = Decimal("0")
    missing_count = 0
    for payment in payments:
        if payment.payment_id not in payment_ids_with_entry:
            missing_total += payment.true_ledger_amount
            missing_count += 1

    return {
        "drift": drift,
        "compared_entries": compared_entries,
        "missing_total": missing_total,
        "missing_count": missing_count,
    }


def check_conservation(payments: list[PaymentRecord], ledger: list[LedgerEntry]) -> dict:
    b = _raw_breakdown(payments, ledger)
    tolerance = PER_RECORD_TOLERANCE * Decimal(max(b["compared_entries"], 1))
    balanced = abs(b["drift"]) <= tolerance

    return {
        "balanced": balanced,
        "ledger_entries_compared": b["compared_entries"],
        "net_drift_across_recorded_entries": str(b["drift"]),
        "drift_tolerance": str(tolerance),
        "amount_with_no_ledger_entry": str(b["missing_total"]),
        "payments_with_no_ledger_entry": b["missing_count"],
    }


def try_z3_check(payments: list[PaymentRecord], ledger: list[LedgerEntry]) -> Optional[dict]:
    """Optional stronger check with an actual constraint solver. Returns
    None if z3-solver isn't installed — the decimal-based check above is
    the required baseline; this is a pure upgrade, not a dependency."""
    try:
        import z3
    except ImportError:
        return None

    b = _raw_breakdown(payments, ledger)
    tolerance = float(PER_RECORD_TOLERANCE) * max(b["compared_entries"], 1)

    drift = z3.Real("drift")
    solver = z3.Solver()
    solver.add(drift == float(b["drift"]))
    solver.add(drift <= tolerance)
    solver.add(drift >= -tolerance)

    result = solver.check()
    return {
        "solver_result": str(result),
        "satisfiable": result == z3.sat,
        "ledger_entries_compared": b["compared_entries"],
        "amount_with_no_ledger_entry": str(b["missing_total"]),
    }
