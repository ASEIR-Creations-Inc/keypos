from decimal import Decimal

from pydantic import BaseModel, Field
from typing import Optional


# ── Supplier schemas ────────────────────────────────────────────

class SupplierCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    contact: str | None = None
    phone: str | None = None
    address: str | None = None


class SupplierUpdate(BaseModel):
    name: str | None = None
    contact: str | None = None
    phone: str | None = None
    address: str | None = None
    is_active: bool | None = None


class SupplierResponse(BaseModel):
    id: int
    name: str
    contact: str | None
    phone: str | None
    address: str | None
    is_active: bool


# ── Purchase line schemas ──────────────────────────────────────

class PurchaseLineCreate(BaseModel):
    product_id: int
    qty: Decimal = Field(..., gt=0)
    unit_cost: Decimal = Field(..., gt=0)


class PurchaseLineResponse(BaseModel):
    id: int
    product_id: int
    product_name: str
    qty: Decimal
    unit_cost: Decimal
    total_cost: Decimal
    wac_before: Decimal
    wac_after: Decimal


# ── Purchase order schemas ─────────────────────────────────────

class PurchaseCreate(BaseModel):
    supplier_id: Optional[int] = None
    lines: list[PurchaseLineCreate]


class PurchaseUpdate(BaseModel):
    supplier_id: Optional[int] = None
    lines: list[PurchaseLineCreate]


class PurchaseResponse(BaseModel):
    id: int
    supplier_id: Optional[int] = None
    supplier_name: str
    ref_number: str
    status: str
    total_amount: Decimal
    created_by_id: int
    posted_by_id: int | None
    created_at: str | None
    posted_at: str | None
    lines: list[PurchaseLineResponse]
