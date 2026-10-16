from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, ConfigDict


# ── Customer ──────────────────────────────────────────────────

class CustomerCreate(BaseModel):
    name: str
    phone: str | None = None
    email: str | None = None
    credit_limit: Decimal = Decimal("0")


class CustomerResponse(BaseModel):
    id: int
    name: str
    phone: str | None
    email: str | None
    credit_limit: Decimal
    balance: Decimal
    created_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


# ── Ledger ────────────────────────────────────────────────────

class LedgerEntry(BaseModel):
    date: datetime
    type: str  # "opening", "sale", "refund" or "payment"
    ref: str
    amount: Decimal
    balance_after: Decimal


class CustomerLedger(BaseModel):
    customer: CustomerResponse
    entries: list[LedgerEntry]


# ── Payment ───────────────────────────────────────────────────

class PaymentCreate(BaseModel):
    amount: Decimal = Field(..., gt=0)
    reference: str | None = None
    method: Literal["cash", "card"] = "cash"


class PaymentResponse(BaseModel):
    id: int
    customer_id: int
    amount: Decimal
    reference: str | None
    method: str
    shift_id: int | None
    received_by_id: int
    created_at: datetime | None

    model_config = ConfigDict(from_attributes=True)
