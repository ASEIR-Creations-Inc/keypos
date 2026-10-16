from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_BLOCKS = 20
MAX_BLOCK_LINES = 1000
Pay = Literal["cash", "card", "split"]


class SheetProblem(BaseModel):
    tab: Literal["sheet", "sales", "expenses", "summary"]
    row: int | None = None
    message: str
    block: int | None = None  # set on sheets with more than one block


class SheetLine(BaseModel):
    row: int
    product_id: int
    name: str
    qty: Decimal
    price: Decimal
    total: Decimal
    block: int = 1
    pay: Pay = "cash"
    card: Decimal = Decimal("0")  # the card part marked on the line (a reference only)


class SheetExpense(BaseModel):
    row: int
    category_id: int | None
    category: str | None
    amount: Decimal
    description: str | None
    paid_from_drawer: bool


class SheetTotals(BaseModel):
    """cash_sales = receipt_total - card; accounted = counted + drawer_expenses - starting_cash;
    difference = accounted - cash_sales (positive = extra cash, negative = short)."""
    grand_total: Decimal
    tax: Decimal
    receipt_total: Decimal
    card: Decimal
    cash_sales: Decimal
    counted: Decimal | None
    starting_cash: Decimal
    drawer_expenses: Decimal
    other_expenses: Decimal
    accounted: Decimal | None
    difference: Decimal | None
    card_marked: Decimal | None = None  # card marked on the lines; the slip (card) is what counts


class SheetBlock(BaseModel):
    """One block of lines and the receipt it becomes: card is its share of the machine slip."""
    block: int
    lines: int
    total: Decimal
    card: Decimal
    cash: Decimal
    card_marked: Decimal
    receipt_ref: str | None = None


class SheetInspection(BaseModel):
    code: str
    version: int
    latest_version: int
    lang: str
    sheet_date: date
    status: str
    created_by_name: str
    created_at: datetime | None
    refreshed_at: datetime | None
    uploaded_receipt: str | None
    sales_rows: int
    expense_rows: int
    lines: list[SheetLine]
    expenses: list[SheetExpense]
    totals: SheetTotals
    problems: list[SheetProblem]
    can_refresh: bool
    can_upload: bool


class DaySheetSummary(BaseModel):
    id: int
    code: str
    kind: str
    sheet_date: date
    lang: str
    version: int
    status: str
    created_by_name: str
    created_at: datetime | None
    refreshed_at: datetime | None
    submitted_at: datetime | None
    uploaded_at: datetime | None
    uploaded_by_name: str | None
    receipt_ref: str | None
    difference: Decimal | None
    receipt_count: int = 0


class SheetUploadResult(BaseModel):
    code: str
    version: int
    receipt_ref: str | None
    expense_count: int
    totals: SheetTotals


# ── KEYPOS Sheet app ────────────────────────────────────────────
# Problems on app sheets use the same row numbers as Excel rows (line 1 is row 2), so
# both screens show "line row - 1".

Amount = Annotated[Decimal, Field(ge=0, le=9999999)]


class AppLine(BaseModel):
    product_id: int
    product: str = Field(max_length=255)  # the name when it was picked, shown if the product goes away
    qty: Amount | None = None
    price: Amount | None = None
    block: int = Field(1, ge=1, le=MAX_BLOCKS)
    pay: Pay = "cash"
    card: Amount | None = None  # the card part of a split payment


class AppExpense(BaseModel):
    category_id: int | None = None
    amount: Amount | None = None
    description: str = Field("", max_length=500)
    paid_from: Literal["drawer", "other"] | None = None


class AppContent(BaseModel):
    """lines stay one flat list, each with its block number, so a phone on an older screen that
    drops the block keeps every line (they merge into block 1)."""
    blocks: int = Field(1, ge=1, le=MAX_BLOCKS)
    lines: list[AppLine] = Field(default_factory=list, max_length=MAX_BLOCKS * MAX_BLOCK_LINES)
    expenses: list[AppExpense] = Field(default_factory=list, max_length=200)
    card: Amount | None = None
    counted: Amount | None = None
    start: Amount | None = None

    @model_validator(mode="after")
    def blocks_fit(self) -> "AppContent":
        sizes: dict[int, int] = {}
        for l in self.lines:
            if l.block > self.blocks:
                raise ValueError(f"A line is in block {l.block}, but the sheet has {self.blocks} block(s)")
            sizes[l.block] = sizes.get(l.block, 0) + 1
        full = [b for b, n in sizes.items() if n > MAX_BLOCK_LINES]
        if full:
            raise ValueError(f"Block {full[0]} has more than {MAX_BLOCK_LINES} lines: start a new block")
        return self


class AppSheetSave(BaseModel):
    lang: Literal["pt", "en"] = "pt"
    sheet_date: date | None = None  # the phone's date when the sheet was started (it may sync days later)
    content: AppContent


class AppSheet(BaseModel):
    """A sheet as its author sees it, with the problems that would stop it being sent."""
    token: str
    code: str
    lang: str
    sheet_date: date
    status: Literal["draft", "submitted", "returned", "approved"]
    content: AppContent
    updated_at: datetime | None
    submitted_at: datetime | None
    returned_at: datetime | None
    returned_by_name: str | None
    return_note: str | None
    approved_at: datetime | None
    receipt_ref: str | None
    receipt_refs: list[str] = Field(default_factory=list)
    totals: SheetTotals
    problems: list[SheetProblem]


class CatalogProduct(BaseModel):
    id: int
    name: str
    price: Decimal
    stock: Decimal


class CatalogCategory(BaseModel):
    id: int
    name: str


class AppCatalog(BaseModel):
    products: list[CatalogProduct]
    categories: list[CatalogCategory]
    currency_symbol: str
    tax_rate: Decimal


class SheetReview(BaseModel):
    """A sent sheet as an approver sees it: checked against live stock and the approver's shift."""
    id: int
    code: str
    sheet_date: date
    status: str
    created_by_name: str
    submitted_at: datetime | None
    returned_at: datetime | None
    return_note: str | None
    approved_at: datetime | None
    approved_by_name: str | None
    receipt_ref: str | None
    receipt_refs: list[str] = Field(default_factory=list)
    blocks: list[SheetBlock] = Field(default_factory=list)
    lines: list[SheetLine]
    expenses: list[SheetExpense]
    totals: SheetTotals
    problems: list[SheetProblem]
    can_approve: bool


class SheetReturn(BaseModel):
    note: str = Field(min_length=1, max_length=500)

    @field_validator("note")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Write a note for the employee")
        return value.strip()
