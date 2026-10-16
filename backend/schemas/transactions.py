from decimal import Decimal
from pydantic import BaseModel, Field, model_validator
from datetime import datetime
from typing import Literal, Optional


# ── Requests ────────────────────────────────────────────────────

class TransactionLineCreate(BaseModel):
    product_id: int
    qty: Decimal = Field(..., gt=0)
    sell_price: Decimal = Field(..., ge=0)
    discount: Decimal = Field(default=Decimal("0"), ge=0)


class TransactionCreate(BaseModel):
    lines: list[TransactionLineCreate]
    payment_cash: Decimal = Field(default=Decimal("0"), ge=0)
    payment_card: Decimal = Field(default=Decimal("0"), ge=0)
    payment_account: Decimal = Field(default=Decimal("0"), ge=0)
    customer_id: int | None = None
    discount_amount: Decimal = Field(
        default=Decimal("0"), ge=0,
        description="Cart-level discount on top of line discounts. Responses report the combined discount.",
    )
    notes: str | None = None
    status: Literal["held", "completed"] | None = None
    reissue_of_id: int | None = Field(
        default=None, description="Refunded receipt this sale replaces (the items the customer kept)."
    )
    device_id: str | None = Field(default=None, max_length=100)
    client_ref: str | None = Field(
        default=None, max_length=100,
        description="Made once per checkout on the till; a repeat with the same device_id and ref returns the first sale.",
    )


class RefundPayload(BaseModel):
    """Refunds always cover the whole receipt."""
    reason: str = Field(..., min_length=1, max_length=500)

    @model_validator(mode="after")
    def _not_blank(self) -> "RefundPayload":
        if not self.reason.strip():
            raise ValueError("A reason is required")
        return self


class PriceEditRequest(BaseModel):
    new_price: Decimal = Field(..., ge=0)


# ── Responses ───────────────────────────────────────────────────

class TransactionLineResponse(BaseModel):
    id: int
    transaction_id: int
    product_id: int
    product_name: str | None = None
    qty: Decimal
    original_price: Decimal
    sell_price: Decimal
    cost_price: Decimal
    discount: Decimal
    line_total: Decimal
    refunded_qty: Decimal = Decimal("0")


class TransactionResponse(BaseModel):
    id: int
    ref_number: str
    cashier_id: int
    shift_id: int | None
    customer_id: int | None
    customer_name: str | None = None
    status: str
    subtotal: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    payment_cash: Decimal
    payment_card: Decimal
    payment_account: Decimal
    change_given: Decimal
    refunded_amount: Decimal = Decimal("0")
    notes: str | None = None
    oversold: bool = False
    is_offline: bool = False
    transaction_lines: list[TransactionLineResponse]
    created_at: Optional[datetime] = None
    refundable: bool = False
    refund: "RefundInfo | None" = None
    reissue_of_id: int | None = None
    reissue_of_ref: str | None = None
    reissued_as_ref: str | None = None


class RefundInfo(BaseModel):
    ref_number: str | None
    amount: Decimal
    refund_cash: Decimal
    refund_card: Decimal
    refund_account: Decimal
    reason: str | None
    created_by: int
    created_at: Optional[datetime] = None


TransactionResponse.model_rebuild()
