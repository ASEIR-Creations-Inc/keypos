from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field

from schemas.audit import AuditEntry


# ── Requests ────────────────────────────────────────────────────

class ShiftOpen(BaseModel):
    opening_float: Decimal = Field(..., ge=0)


class ShiftClose(BaseModel):
    closing_cash: Decimal = Field(..., ge=0)


# ── Responses ───────────────────────────────────────────────────

class ShiftResponse(BaseModel):
    id: int
    cashier_id: int
    cashier_name: str | None = None
    opening_float: Decimal
    closing_cash: Decimal | None = None
    expected_cash: Decimal | None = None
    variance: Decimal | None = None
    status: str
    opened_at: str | None = None
    closed_at: str | None = None


class ShiftReport(BaseModel):
    total_transactions: int
    gross_sales: Decimal
    total_discounts: Decimal
    total_refunds: Decimal
    refund_count: int = 0
    net_sales: Decimal
    tax_collected: Decimal
    cash_sales: Decimal
    card_sales: Decimal
    account_sales: Decimal
    price_edit_count: int
    price_edit_variance: Decimal
    customer_payments_cash: Decimal = Decimal("0")
    customer_payments_card: Decimal = Decimal("0")
    drawer_expenses: Decimal = Decimal("0")
    expected_cash: Decimal = Decimal("0")
    offline_sales_count: int = 0
    offline_sales_total: Decimal = Decimal("0")


class RefundedReceipt(BaseModel):
    refund_ref: str | None
    sale_ref: str
    sale_created_at: datetime | None
    refunded_at: datetime | None
    amount: Decimal
    refund_cash: Decimal
    refund_card: Decimal
    refund_account: Decimal
    reason: str | None
    refunded_by: str | None
    reissued_as: str | None = None


class ZReport(BaseModel):
    shift: ShiftResponse
    report: ShiftReport
    refunds: list[RefundedReceipt] = []
    activity: list[AuditEntry] = []
    activity_counts: dict[str, int] = {}
