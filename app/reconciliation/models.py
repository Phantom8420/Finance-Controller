from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

# Razorpay's documented test-mode fee schedule (standard domestic card rate).
FEE_RATE = Decimal("0.02")
GST_RATE = Decimal("0.18")  # applied on the fee, not on the payment amount
TOLERANCE = Decimal("0.02")  # 2 paise — accounts for rounding noise, nothing more


class PaymentRecord(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    payment_id: str
    order_id: str
    amount: Decimal
    currency: str = "INR"
    method: str = "card"
    captured_at: datetime
    refund_amount: Decimal = Decimal("0")

    @property
    def fee(self) -> Decimal:
        return (self.amount * FEE_RATE).quantize(Decimal("0.01"))

    @property
    def gst(self) -> Decimal:
        return (self.fee * GST_RATE).quantize(Decimal("0.01"))

    @property
    def net_settlement(self) -> Decimal:
        return self.amount - self.fee - self.gst

    @property
    def true_ledger_amount(self) -> Decimal:
        """What a correct merchant ledger entry for this payment should say."""
        return self.net_settlement - self.refund_amount


class LedgerEntry(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    entry_id: str
    ref_payment_id: Optional[str] = None
    amount: Decimal
    recorded_at: datetime
    note: str = ""
    # Ground-truth label, only present because *we* injected the mismatch —
    # used for scoring precision/recall, never read by the reconciliation engine.
    injected_issue: Optional[str] = None


class ProofRecord(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    record_id: str
    payment_id: Optional[str]
    ledger_entry_id: Optional[str]
    matched: bool
    rule_type: Optional[str] = None
    proof_code: Optional[str] = None
    inputs: dict = {}
    expected_value: Optional[Decimal] = None
    actual_value: Optional[Decimal] = None
    verified: bool = False
    confidence: float = 0.0
    is_exception: bool = False
    reason: str = ""
    prev_hash: Optional[str] = None
    hash: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_jsonable(self) -> dict:
        d = self.model_dump()
        for key in ("expected_value", "actual_value"):
            if d.get(key) is not None:
                d[key] = str(d[key])
        d["created_at"] = self.created_at.isoformat()
        return d
