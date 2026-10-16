from decimal import Decimal
from pydantic import BaseModel, Field, model_validator


# ── Categories ──────────────────────────────────────────────────

class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    color: str = Field(default="#808080", pattern=r"^#[0-9a-fA-F]{6}$")
    sort_order: int = 0


class CategoryUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    sort_order: int | None = None


class CategoryResponse(BaseModel):
    id: int
    name: str
    color: str
    sort_order: int


# ── Units ───────────────────────────────────────────────────────

class UnitCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)


class UnitResponse(BaseModel):
    id: int
    name: str


# ── Products ────────────────────────────────────────────────────

class ProductCreate(BaseModel):
    sku: str | None = Field(None, max_length=100)
    barcode: str | None = Field(None, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    category_id: int | None = None
    unit_id: int | None = None
    sell_price: Decimal = Field(..., ge=0)
    cost_price: Decimal = Field(default=Decimal("0"), ge=0)
    stock_qty: Decimal = Field(default=Decimal("0"), ge=0)
    low_stock_threshold: Decimal = Field(default=Decimal("5"), ge=0)
    image_url: str | None = Field(None, max_length=500)


class ProductUpdate(BaseModel):
    """Catalogue fields only: stock moves through adjust-stock, cost through posted purchases."""
    barcode: str | None = None
    name: str | None = Field(None, min_length=1, max_length=255)
    category_id: int | None = None
    unit_id: int | None = None
    sell_price: Decimal | None = Field(None, ge=0)
    low_stock_threshold: Decimal | None = Field(None, ge=0)
    image_url: str | None = Field(None, max_length=500)


class ProductResponse(BaseModel):
    id: int
    sku: str
    barcode: str | None
    name: str
    category_id: int | None
    category_name: str | None = None
    unit_id: int | None
    unit_name: str | None = None
    sell_price: Decimal
    cost_price: Decimal
    stock_qty: Decimal
    low_stock_threshold: Decimal
    is_active: bool
    image_url: str | None
    created_at: str | None = None


class StockAdjustRequest(BaseModel):
    """Send either change (+/-) or counted_qty (the quantity found on the shelf)."""
    change: Decimal | None = None
    counted_qty: Decimal | None = Field(None, ge=0)
    reason: str = Field(..., min_length=1, max_length=500)

    @model_validator(mode="after")
    def _one_of(self) -> "StockAdjustRequest":
        if (self.change is None) == (self.counted_qty is None):
            raise ValueError("Send either change or counted_qty")
        if not self.reason.strip():
            raise ValueError("A reason is required")
        return self
