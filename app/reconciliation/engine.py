"""Layer 1 — reconciliation that proves, rather than narrates.

Three stages, in order:
  1. deterministic match on payment_id (structural issues — missing or
     duplicate ledger rows — are flagged immediately, never guessed through)
  2. rule-based proof: a small deterministic script recomputes the exact
     ledger amount from a known formula (net settlement, GST-on-fee miss,
     unreflected refund) and is executed in the sandbox — accepted only if
     it reproduces the actual number
  3. LLM-assisted proof: only for gaps stage 2 can't explain, Gemini is
     asked to *write* a compute() script; it is accepted only if executing
     it reproduces the actual ledger amount, never on the model's say-so
     alone. The model is never shown the target ledger amount — only the
     raw inputs — and the generated code is statically checked for
     hardcoded constants before it's trusted, so it can't game the check
     by just returning the answer it was told to reproduce.

Anything that doesn't reproduce the number by any stage goes to the
exception list — the engine never force-matches.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from app.llm_client import generate_text, strip_code_fences
from app.reconciliation.models import FEE_RATE, GST_RATE, TOLERANCE, LedgerEntry, PaymentRecord, ProofRecord
from app.reconciliation.sandbox import SandboxError, find_foreign_constants, run_proof_code

_NET_SETTLEMENT_CODE = """
def compute(inputs):
    amount = Decimal(str(inputs["amount"]))
    fee_rate = Decimal(str(inputs["fee_rate"]))
    gst_rate = Decimal(str(inputs["gst_rate"]))
    refund = Decimal(str(inputs["refund_amount"]))
    fee = amount * fee_rate
    gst = fee * gst_rate
    return amount - fee - gst - refund
"""

_GST_FEE_MISS_CODE = """
def compute(inputs):
    amount = Decimal(str(inputs["amount"]))
    fee_rate = Decimal(str(inputs["fee_rate"]))
    refund = Decimal(str(inputs["refund_amount"]))
    fee = amount * fee_rate
    return amount - fee - refund
"""

_REFUND_NOT_REFLECTED_CODE = """
def compute(inputs):
    amount = Decimal(str(inputs["amount"]))
    fee_rate = Decimal(str(inputs["fee_rate"]))
    gst_rate = Decimal(str(inputs["gst_rate"]))
    fee = amount * fee_rate
    gst = fee * gst_rate
    return amount - fee - gst
"""

_RULES = [
    ("net_settlement", _NET_SETTLEMENT_CODE, 1.0),
    ("gst_fee_miss", _GST_FEE_MISS_CODE, 0.95),
    ("refund_not_reflected", _REFUND_NOT_REFLECTED_CODE, 0.95),
]


def _inputs_for(payment: PaymentRecord) -> dict:
    return {
        "amount": str(payment.amount),
        "fee_rate": str(FEE_RATE),
        "gst_rate": str(GST_RATE),
        "refund_amount": str(payment.refund_amount),
    }


def _try_llm_proof(payment: PaymentRecord, entry: LedgerEntry) -> Optional[tuple]:
    """Returns (code, computed_value) only if the model-generated script
    genuinely reproduces the actual ledger amount when executed. Returns
    None if no GEMINI_API_KEY is configured, or the model's attempt
    doesn't reproduce the number — either way, that's an honest exception,
    not a guess."""
    inputs = _inputs_for(payment)
    # Deliberately NOT shown the actual ledger amount: if the model knew the
    # target, it could just hardcode `return Decimal("<target>")` and
    # trivially "reproduce" any number without deriving anything — that
    # would defeat the entire point of proving instead of asserting. It
    # only ever sees the raw inputs, the same way the rule-based stages do,
    # and has to propose a plausible Razorpay-specific formula blind.
    prompt = (
        "A Razorpay merchant's internal ledger entry doesn't match the payment "
        "record it should reconcile with. Common real causes: GST applied to "
        "the wrong base or at the wrong slab, a partial refund not yet "
        "reflected, a fee miscalculation, or a rounding convention mismatch.\n\n"
        "Given only these inputs, write a Python function "
        "`compute(inputs: dict) -> Decimal` that computes what you believe the "
        "correct ledger amount should be, using only Decimal arithmetic "
        "(Decimal is already available, do not import it, no I/O, no dunder "
        "attribute access). Every numeric constant you use must be derived "
        "from the inputs dict, not invented.\n\n"
        f"inputs = {inputs}\n\n"
        "Output only the function definition, nothing else."
    )
    raw = generate_text(prompt)
    if raw is None:
        return None
    code = strip_code_fences(raw)

    # Static anti-gaming check: reject any numeric literal not traceable to
    # the inputs the model was actually given (plus ordinary percentage
    # arithmetic constants) — this is what actually prevents a hardcoded
    # "return Decimal(<target>)" from passing, independent of the prompt.
    allowed = set(inputs.values()) | {"0", "1", "2", "10", "100", "0.01"}
    foreign = find_foreign_constants(code, allowed)
    if foreign:
        return None

    try:
        computed = run_proof_code(code, inputs)
    except SandboxError:
        return None

    if abs(computed - entry.amount) <= TOLERANCE:
        return code, computed
    return None


def reconcile(payments: list[PaymentRecord], ledger: list[LedgerEntry]) -> list[ProofRecord]:
    by_payment_id: dict[str, list[LedgerEntry]] = {}
    for entry in ledger:
        if entry.ref_payment_id:
            by_payment_id.setdefault(entry.ref_payment_id, []).append(entry)

    results: list[ProofRecord] = []

    for payment in payments:
        matches = by_payment_id.get(payment.payment_id, [])
        record_id = f"proof-{payment.payment_id}"

        if not matches:
            results.append(
                ProofRecord(
                    record_id=record_id,
                    payment_id=payment.payment_id,
                    ledger_entry_id=None,
                    matched=False,
                    is_exception=True,
                    reason="no ledger entry found for this payment",
                )
            )
            continue

        if len(matches) > 1:
            results.append(
                ProofRecord(
                    record_id=record_id,
                    payment_id=payment.payment_id,
                    ledger_entry_id=",".join(m.entry_id for m in matches),
                    matched=False,
                    is_exception=True,
                    reason=f"{len(matches)} ledger entries reference the same payment — ambiguous, needs human review",
                )
            )
            continue

        entry = matches[0]
        inputs = _inputs_for(payment)
        resolved = False

        for rule_type, code, confidence in _RULES:
            try:
                # trusted=True: these three templates are fixed strings we
                # wrote ourselves (see _RULES above), never model- or
                # externally-influenced — skips the thread+timeout wrapper
                # sandbox.py uses for genuinely untrusted code. Stage 3
                # below (model-generated) and re-verification both still
                # go through the full path; this only speeds up resolving
                # our own known-safe rules.
                computed = run_proof_code(code, inputs, trusted=True)
            except SandboxError:
                continue
            if abs(computed - entry.amount) <= TOLERANCE:
                results.append(
                    ProofRecord(
                        record_id=record_id,
                        payment_id=payment.payment_id,
                        ledger_entry_id=entry.entry_id,
                        matched=True,
                        rule_type=rule_type,
                        proof_code=code,
                        inputs=inputs,
                        expected_value=computed,
                        actual_value=entry.amount,
                        verified=True,
                        confidence=confidence,
                        is_exception=False,
                        reason=f"reproduced by rule '{rule_type}'",
                    )
                )
                resolved = True
                break

        if resolved:
            continue

        llm_result = _try_llm_proof(payment, entry)
        if llm_result is not None:
            code, computed = llm_result
            results.append(
                ProofRecord(
                    record_id=record_id,
                    payment_id=payment.payment_id,
                    ledger_entry_id=entry.entry_id,
                    matched=True,
                    rule_type="llm_generated",
                    proof_code=code,
                    inputs=inputs,
                    expected_value=computed,
                    actual_value=entry.amount,
                    verified=True,
                    confidence=0.85,
                    is_exception=False,
                    reason="reproduced by model-generated proof script",
                )
            )
            continue

        results.append(
            ProofRecord(
                record_id=record_id,
                payment_id=payment.payment_id,
                ledger_entry_id=entry.entry_id,
                matched=False,
                inputs=inputs,
                actual_value=entry.amount,
                is_exception=True,
                reason="no rule or generated proof reproduces the ledger amount — flagged, not guessed",
            )
        )

    return results
