"""Settlement Q&A — answers questions about specific reconciliation
outcomes, grounded only in the proof records Layer 1 already computed.
The model is never asked to re-derive a number itself here; it's shown
the actual ProofRecord data and told to cite it, or say plainly that the
data doesn't cover the question, rather than invent an answer. Requires
ANTHROPIC_API_KEY — returns a clear "not configured" result otherwise,
same "skipped, not faked" pattern as the rest of the app.
"""
from __future__ import annotations

import os
import re

from app.reconciliation.models import FEE_RATE, GST_RATE, LedgerEntry, PaymentRecord, ProofRecord

_ID_PATTERN = re.compile(r"\b(?:pay|fuzz)_[a-zA-Z0-9_]+\b")


def _find_relevant_proofs(question: str, proofs: list[ProofRecord], limit: int = 5) -> list[ProofRecord]:
    mentioned_ids = set(_ID_PATTERN.findall(question))
    if mentioned_ids:
        matches = [p for p in proofs if p.payment_id in mentioned_ids]
        if matches:
            return matches
    # No specific payment id mentioned/found — "why" questions without an
    # id usually mean "why are things flagged", so default to exceptions.
    exceptions = [p for p in proofs if p.is_exception]
    return exceptions[:limit] if exceptions else proofs[:limit]


def _context_for(proofs: list[ProofRecord], payments_by_id: dict) -> list[dict]:
    context = []
    for p in proofs:
        payment = payments_by_id.get(p.payment_id)
        context.append(
            {
                "payment_id": p.payment_id,
                "payment_amount": str(payment.amount) if payment else None,
                "refund_amount": str(payment.refund_amount) if payment else None,
                "matched": p.matched,
                "rule_type": p.rule_type,
                "confidence": p.confidence,
                "is_exception": p.is_exception,
                "reason": p.reason,
                "expected_value": str(p.expected_value) if p.expected_value is not None else None,
                "actual_value": str(p.actual_value) if p.actual_value is not None else None,
            }
        )
    return context


def answer_question(
    question: str,
    payments: list[PaymentRecord],
    ledger: list[LedgerEntry],
    proofs: list[ProofRecord],
) -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {
            "answered": False,
            "answer": None,
            "grounded_in": [],
            "reason": "ANTHROPIC_API_KEY not configured — skipped, not faked.",
        }
    try:
        import anthropic
    except ImportError:
        return {
            "answered": False,
            "answer": None,
            "grounded_in": [],
            "reason": "anthropic package not installed.",
        }

    payments_by_id = {p.payment_id: p for p in payments}
    relevant = _find_relevant_proofs(question, proofs)
    context_records = _context_for(relevant, payments_by_id)

    prompt = (
        "You are answering a merchant's question about their Razorpay payment "
        "reconciliation, using ONLY the proof records below — never invent a "
        "number that isn't in them. If the records don't cover the question, "
        "say so plainly instead of guessing. Cite the specific payment_id and "
        "rule_type/reason each part of your answer is based on.\n\n"
        f"Razorpay fee rate: {FEE_RATE}, GST on fee: {GST_RATE}\n\n"
        f"Relevant proof records:\n{context_records}\n\n"
        f"Question: {question}"
    )

    try:
        client = anthropic.Anthropic()
        model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
        response = client.messages.create(
            model=model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        answer = response.content[0].text
    except Exception as e:
        return {
            "answered": False,
            "answer": None,
            "grounded_in": [r["payment_id"] for r in context_records],
            "reason": f"model call failed: {e!r}",
        }

    return {
        "answered": True,
        "answer": answer,
        "grounded_in": [r["payment_id"] for r in context_records],
        "reason": "",
    }
