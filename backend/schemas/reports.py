from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel


# ── Shared base ──────────────────────────────────────────────────────
class ReportDateRange(BaseModel):
    from_date: datetime
    to_date: datetime


# ── Sales Summary ────────────────────────────────────────────────────
class SalesSummaryResponse(ReportDateRange):
    transaction_count: int
    gross_sales: Decimal
    total_discounts: Decimal
    total_tax: Decimal
    cash_sales: Decimal
    card_sales: Decimal
    account_sales: Decimal
    refund_count: int
    refund_total: Decimal
    void_count: int
    net_sales: Decimal


# ── Profit & Loss ────────────────────────────────────────────────────
class PnLResponse(ReportDateRange):
    revenue: Decimal
    cogs: Decimal
    gross_profit: Decimal
    gross_margin_pct: Decimal
    total_expenses: Decimal
    net_profit: Decimal


# ── Tax Report ───────────────────────────────────────────────────────
class TaxDayEntry(BaseModel):
    tax_date: date
    tax_amount: Decimal


class TaxReportResponse(ReportDateRange):
    daily_breakdown: list[TaxDayEntry]
    total_tax: Decimal


# ── Cashier Report ───────────────────────────────────────────────────
class CashierEntry(BaseModel):
    cashier_id: int
    cashier_name: str
    transaction_count: int
    gross_sales: Decimal
    discounts: Decimal
    net_sales: Decimal
    cash: Decimal
    card: Decimal
    account: Decimal


class CashierReportResponse(ReportDateRange):
    cashiers: list[CashierEntry]


# ── Price Edits Report ───────────────────────────────────────────────
class PriceEditEntry(BaseModel):
    edited_at: datetime
    cashier_name: str
    product_name: str
    original_price: Decimal
    new_price: Decimal
    difference: Decimal


class PriceEditsReportResponse(ReportDateRange):
    edits: list[PriceEditEntry]
    total_edits: int
    net_variance: Decimal


# ── Inventory Value Report ───────────────────────────────────────────
class InventoryItem(BaseModel):
    product_id: int
    sku: str
    name: str
    stock_qty: Decimal
    cost_price: Decimal
    stock_value: Decimal


class InventoryValueReportResponse(BaseModel):
    products: list[InventoryItem]
    total_inventory_value: Decimal


# ── Low Stock Report ─────────────────────────────────────────────────
class LowStockEntry(BaseModel):
    product_id: int
    sku: str
    name: str
    stock_qty: Decimal
    low_stock_threshold: Decimal
    deficit: Decimal


class LowStockReportResponse(BaseModel):
    products: list[LowStockEntry]


# ── Stock Adjustments Report ─────────────────────────────────────────
class StockAdjustmentEntry(BaseModel):
    created_at: datetime
    product_name: str
    sku: str
    qty_before: Decimal
    qty_after: Decimal
    adjustment: Decimal
    reason: str | None
    adjusted_by_name: str


class StockAdjustmentsReportResponse(ReportDateRange):
    adjustments: list[StockAdjustmentEntry]
