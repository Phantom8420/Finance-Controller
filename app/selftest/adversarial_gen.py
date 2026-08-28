"""Layer 3 — the system hunts its own blind spots.

Two distinct, honestly-labeled sources of adversarial cases:

  - `run_fixed_suite()` — a developer-authored regression/fuzz suite: three
    hand-written scenario generators (boundary rounding, chained partial
    refunds, wrong GST slab) that stress the exact rule set Layer 1 relies
    on. Deterministic, seeded, always available, no API key required. This
    is *not* the system inventing its own tests — it's a fixed suite the
    system runs against itself every time.

  - `run_llm_suite()` — genuinely AI-generated cases: when
    ANTHROPIC_API_KEY is set, Claude is asked to invent a plausible
    bookkeeping mistake and write the code that produces it, executed in
    the same sandbox as everything else in Layer 1. This is the part that
    's actually autonomous; it's additive to the fixed suite, not a
    replacement, and returns None when no key is configured.

Both feed the same `reconcile()` engine used on real data. Anything that
can't be resolved is logged as a known limitation — found before a human
hit it, whichever suite found it.
"""
from __future__ import annotations

import os
import random
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Callable, Optional

from app.reconciliation.engine import reconcile
from app.reconciliation.models import FEE_RATE, GST_RATE, LedgerEntry, PaymentRecord
from app.reconciliation.sandbox import SandboxError, find_foreign_constants, run_proof_code

_BASE_TIME = datetime(2026, 8, 1, 0, 0, 0)


def _boundary_rounding_case(rng: random.Random, i: int) -> tuple[PaymentRecord, LedgerEntry]:
    amount = (Decimal(rng.randint(100, 99999)) / Decimal(100)).quantize(Decimal("0.01"))
    payment = PaymentRecord(
        payment_id=f"fuzz_round_{i}",
        order_id=f"fuzz_order_round_{i}",
        amount=amount,
        captured_at=_BASE_TIME + timedelta(hours=i),
    )
    # noise straddling the 0.02 tolerance edge — some in-bounds, some just over
    noise = Decimal(rng.choice([-3, -2, 2, 3])) / Decimal(100)
    entry = LedgerEntry(
        entry_id=f"fuzz_round_led_{i}",
        ref_payment_id=payment.payment_id,
        amount=(payment.true_ledger_amount + noise).quantize(Decimal("0.01")),
        recorded_at=payment.captured_at,
        note="dev-authored fuzz case: boundary rounding",
    )
    return payment, entry


def _chained_refund_case(rng: random.Random, i: int) -> tuple[PaymentRecord, LedgerEntry]:
    amount = (Decimal(rng.randint(1000, 99999)) / Decimal(100)).quantize(Decimal("0.01"))
    refund_total = (amount * Decimal("0.3")).quantize(Decimal("0.01"))
    payment = PaymentRecord(
        payment_id=f"fuzz_refund_{i}",
        order_id=f"fuzz_order_refund_{i}",
        amount=amount,
        captured_at=_BASE_TIME + timedelta(hours=i),
        refund_amount=refund_total,
    )
    # ledger only reflects the first of two sequential partial refunds
    half_refund = (refund_total / 2).quantize(Decimal("0.01"))
    entry = LedgerEntry(
        entry_id=f"fuzz_refund_led_{i}",
        ref_payment_id=payment.payment_id,
        amount=(payment.net_settlement - half_refund).quantize(Decimal("0.01")),
        recorded_at=payment.captured_at,
        note="dev-authored fuzz case: chained partial refunds, only one reflected",
    )
    return payment, entry


def _near_miss_gst_case(rng: random.Random, i: int) -> tuple[PaymentRecord, LedgerEntry]:
    amount = (Decimal(rng.randint(1000, 99999)) / Decimal(100)).quantize(Decimal("0.01"))
    payment = PaymentRecord(
        payment_id=f"fuzz_gst_{i}",
        order_id=f"fuzz_order_gst_{i}",
        amount=amount,
        captured_at=_BASE_TIME + timedelta(hours=i),
    )
    # a plausible bookkeeping slip: GST at 12% instead of the correct 18%
    wrong_gst = (payment.fee * Decimal("0.12")).quantize(Decimal("0.01"))
    ledger_amount = (payment.amount - payment.fee - wrong_gst).quantize(Decimal("0.01"))
    entry = LedgerEntry(
        entry_id=f"fuzz_gst_led_{i}",
        ref_payment_id=payment.payment_id,
        amount=ledger_amount,
        recorded_at=payment.captured_at,
        note="dev-authored fuzz case: GST applied at wrong slab (12% vs 18%)",
    )
    return payment, entry


_DEVELOPER_AUTHORED_GENERATORS: list[Callable[[random.Random, int], tuple[PaymentRecord, LedgerEntry]]] = [
    _boundary_rounding_case,
    _chained_refund_case,
    _near_miss_gst_case,
]


def _score(payments: list[PaymentRecord], ledger: list[LedgerEntry]) -> dict:
    proofs = reconcile(payments, ledger)
    blind_spots = [
        {"record_id": p.record_id, "payment_id": p.payment_id, "reason": p.reason}
        for p in proofs
        if p.is_exception
    ]
    return {
        "generated": len(payments),
        "resolved": len(proofs) - len(blind_spots),
        "blind_spots_found": len(blind_spots),
        "blind_spots": blind_spots,
    }


def run_fixed_suite(n_per_generator: int = 8, seed: int = 99) -> dict:
    """The always-on, developer-authored regression/fuzz suite."""
    rng = random.Random(seed)
    payments: list[PaymentRecord] = []
    ledger: list[LedgerEntry] = []

    for generator in _DEVELOPER_AUTHORED_GENERATORS:
        for i in range(n_per_generator):
            payment, entry = generator(rng, i)
            payments.append(payment)
            ledger.append(entry)

    return _score(payments, ledger)


# Kept as an alias for backward compatibility with earlier call sites.
run_self_test = run_fixed_suite


def _llm_case(rng: random.Random, i: int, client, model: str) -> Optional[tuple[PaymentRecord, LedgerEntry]]:
    amount = (Decimal(rng.randint(1000, 99999)) / Decimal(100)).quantize(Decimal("0.01"))
    payment = PaymentRecord(
        payment_id=f"fuzz_llm_{i}",
        order_id=f"fuzz_order_llm_{i}",
        amount=amount,
        captured_at=_BASE_TIME + timedelta(hours=i),
    )
    inputs = {
        "amount": str(payment.amount),
        "fee_rate": str(FEE_RATE),
        "gst_rate": str(GST_RATE),
        "refund_amount": str(payment.refund_amount),
    }
    prompt = (
        "Invent one plausible, subtle bookkeeping mistake a merchant's finance "
        "team could make recording a Razorpay payment in their internal ledger "
        "(e.g. a wrong tax slab, a fee applied twice, a rounding convention "
        "error — something subtler than a random number). Write a Python "
        "function `compute(inputs: dict) -> Decimal` that produces the ledger "
        "amount your invented mistake would produce, using only Decimal "
        "arithmetic, no imports, no I/O, no dunder attribute access. Every "
        "numeric constant must be derived from inputs.\n\n"
        f"inputs = {inputs}\n\n"
        "Output only the function definition, nothing else."
    )
    try:
        response = client.messages.create(model=model, max_tokens=400, messages=[{"role": "user", "content": prompt}])
        code = response.content[0].text
    except Exception:
        return None

    allowed = set(inputs.values()) | {"0", "1", "2", "10", "100", "0.01"}
    if find_foreign_constants(code, allowed):
        return None

    try:
        ledger_amount = run_proof_code(code, inputs)
    except SandboxError:
        return None

    entry = LedgerEntry(
        entry_id=f"fuzz_llm_led_{i}",
        ref_payment_id=payment.payment_id,
        amount=ledger_amount.quantize(Decimal("0.01")),
        recorded_at=payment.captured_at,
        note="AI-generated: model-invented bookkeeping mistake",
    )
    return payment, entry


def run_llm_suite(n: int = 6, seed: int = 123) -> Optional[dict]:
    """Genuinely AI-generated adversarial cases. Returns None if
    ANTHROPIC_API_KEY isn't configured — additive to run_fixed_suite(),
    never a silent replacement for it."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        return None

    client = anthropic.Anthropic()
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
    rng = random.Random(seed)

    payments: list[PaymentRecord] = []
    ledger: list[LedgerEntry] = []
    for i in range(n):
        result = _llm_case(rng, i, client, model)
        if result is None:
            continue
        payment, entry = result
        payments.append(payment)
        ledger.append(entry)

    if not payments:
        return {"generated": 0, "resolved": 0, "blind_spots_found": 0, "blind_spots": []}

    return _score(payments, ledger)
