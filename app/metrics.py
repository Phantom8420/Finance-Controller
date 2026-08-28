"""Metrics — the track's own bar, made concrete: throughput, measured
accuracy against real injected ground truth (never the model's own
claims), and an honest exception rate.

`score_reconciliation()` below is an **in-distribution** benchmark: the
mismatch formulas in data/generate_ledger.py were built as the exact
algebraic inverse of the rules in app/reconciliation/engine.py, so a
perfect score there mostly proves the two were written consistently with
each other, not that the rules generalize. `generalization_report()` is
the honest counterpart, built from Layer 3's adversarial suites, which
were deliberately NOT designed to match the rule set — that's the number
that actually speaks to how the engine performs on cases it wasn't tuned
for. Report both, not just the flattering one.
"""
from __future__ import annotations

import time
from typing import Optional

from app.reconciliation.engine import reconcile
from app.reconciliation.models import LedgerEntry, PaymentRecord

_SHOULD_BE_EXCEPTION = {"missing_entry", "duplicate_entry", "unexplained"}


def _ground_truth_by_payment(payments: list[PaymentRecord], ledger: list[LedgerEntry]) -> dict:
    entries_by_payment: dict[str, list[LedgerEntry]] = {}
    for e in ledger:
        if e.ref_payment_id:
            entries_by_payment.setdefault(e.ref_payment_id, []).append(e)

    ground_truth = {}
    for p in payments:
        entries = entries_by_payment.get(p.payment_id, [])
        if not entries:
            ground_truth[p.payment_id] = "missing_entry"
        elif len(entries) > 1:
            ground_truth[p.payment_id] = "duplicate_entry"
        else:
            ground_truth[p.payment_id] = entries[0].injected_issue  # None if clean
    return ground_truth


def score_reconciliation(payments: list[PaymentRecord], ledger: list[LedgerEntry], proofs: list) -> dict:
    ground_truth = _ground_truth_by_payment(payments, ledger)
    proofs_by_payment = {pr.payment_id: pr for pr in proofs if pr.payment_id}

    tp = fp = fn = tn = 0
    for payment_id, issue in ground_truth.items():
        proof = proofs_by_payment.get(payment_id)
        predicted_exception = proof.is_exception if proof else True
        true_exception = issue in _SHOULD_BE_EXCEPTION

        if true_exception and predicted_exception:
            tp += 1
        elif true_exception and not predicted_exception:
            fn += 1  # the dangerous case: something wrong got force-matched
        elif not true_exception and predicted_exception:
            fp += 1  # safe but over-cautious: cost a human review that wasn't needed
        else:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    exception_rate = (tp + fp) / len(ground_truth) if ground_truth else 0.0

    return {
        "total_records": len(ground_truth),
        "true_positives_exceptions_correctly_flagged": tp,
        "false_positives_over_cautious": fp,
        "false_negatives_wrongly_force_matched": fn,
        "true_negatives_correctly_resolved": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "exception_rate": round(exception_rate, 4),
    }


def generalization_report(fixed_suite: dict, llm_suite: Optional[dict] = None) -> dict:
    """The honest counterpart to score_reconciliation(): how the same
    engine performs on adversarial cases it was never tuned against,
    reported plainly alongside (not instead of) the in-distribution
    number. A low resolution rate here is expected and informative, not a
    failure to hide — it's the system finding and reporting its own
    limits."""
    report = {
        "fixed_suite_generated": fixed_suite["generated"],
        "fixed_suite_resolved": fixed_suite["resolved"],
        "fixed_suite_resolution_rate": (
            round(fixed_suite["resolved"] / fixed_suite["generated"], 4) if fixed_suite["generated"] else None
        ),
    }
    if llm_suite is not None:
        report["llm_suite_generated"] = llm_suite["generated"]
        report["llm_suite_resolved"] = llm_suite["resolved"]
        report["llm_suite_resolution_rate"] = (
            round(llm_suite["resolved"] / llm_suite["generated"], 4) if llm_suite["generated"] else None
        )
    return report


def measure_throughput(payments: list[PaymentRecord], ledger: list[LedgerEntry]) -> tuple[dict, list]:
    start = time.perf_counter()
    proofs = reconcile(payments, ledger)
    elapsed = time.perf_counter() - start
    rate = len(payments) / elapsed if elapsed > 0 else float("inf")
    return (
        {"records": len(payments), "seconds": round(elapsed, 4), "records_per_second": round(rate, 2)},
        proofs,
    )
