from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


# ── Expense Category ──────────────────────────────────────────

class ExpenseCategoryCreate(BaseModel):
    name: str


class ExpenseCategoryResponse(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


# ── Expense ───────────────────────────────────────────────────

class ExpenseCreate(BaseModel):
    category_id: int | None = None
    amount: Decimal
    description: str | None = None
    expense_date: date
    paid_from_drawer: bool = False


class ExpenseResponse(BaseModel):
    id: int
    category_id: int | None
    amount: Decimal
    description: str | None
    expense_date: date
    paid_from_drawer: bool
    shift_id: int | None
    entered_by_id: int
    created_at: datetime | None
    category_name: str | None
    day_sheet_id: int | None = None

    model_config = ConfigDict(from_attributes=True)


class ExpenseListResponse(BaseModel):
    items: list[ExpenseResponse]
    period_total: Decimal
