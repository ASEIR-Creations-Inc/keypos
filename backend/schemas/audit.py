from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class StockMovementEntry(BaseModel):
    product_id: int
    product_name: str | None
    qty_change: Decimal
    qty_before: Decimal
    qty_after: Decimal


class AuditEntry(BaseModel):
    id: int
    created_at: datetime
    user_id: int
    user_name: str | None
    shift_id: int | None
    action: str
    ref: str | None
    amount: Decimal | None
    cash: Decimal
    card: Decimal
    account: Decimal
    summary: str
    details: dict | None
    stock_movements: list[StockMovementEntry]


class AuditListResponse(BaseModel):
    entries: list[AuditEntry]
    total_cash: Decimal
    total_card: Decimal
    total_account: Decimal


class StockMovementRow(StockMovementEntry):
    created_at: datetime
    action: str
    ref: str | None
    user_name: str | None
    shift_id: int | None


class StockMovementsResponse(BaseModel):
    movements: list[StockMovementRow]
