from datetime import datetime
from decimal import Decimal
import sqlalchemy.orm

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from core.access import require_access, sees_everyone
from database import get_db
from models.user import User
from models.product import Product
from models.transaction import Transaction, PriceEditLog, Refund, TransactionStatus
from models.expense import Expense
from models.sync import StockAdjustment
from models.purchase import PurchaseOrder, PurchaseOrderLine, Supplier
from services.clock import day_range, shop_zone
from services.figures import SOLD, cost_of_goods, sales_figures
from schemas.reports import (
    SalesSummaryResponse,
    PnLResponse,
    TaxDayEntry,
    TaxReportResponse,
    CashierEntry,
    CashierReportResponse,
    PriceEditEntry,
    PriceEditsReportResponse,
    InventoryItem,
    InventoryValueReportResponse,
    LowStockEntry,
    LowStockReportResponse,
    StockAdjustmentEntry,
    StockAdjustmentsReportResponse,
)

router = APIRouter(prefix="/reports", tags=["reports"])

# ── Helpers ─────────────────────────────────────────────────────────

ZERO = 0
ONE = 1


async def _parse_dates(db: AsyncSession, from_date: str, to_date: str) -> tuple[datetime, datetime]:
    """Whole days in the shop's time zone, from the first instant of from_date to the last of to_date."""
    return day_range(from_date, to_date, await shop_zone(db))


# ── GET /api/reports/sales-summary ──────────────────────────────────

def _in_range(column, f: datetime, t: datetime) -> list:
    return [column >= f, column <= t]


async def _range_figures(db: AsyncSession, f: datetime, t: datetime, *sale_filters, refund_filters=()):
    return await sales_figures(
        db,
        [*_in_range(Transaction.created_at, f, t), *sale_filters],
        [*_in_range(Refund.created_at, f, t), *refund_filters],
    )


@router.get("/sales-summary", response_model=SalesSummaryResponse)
async def sales_summary(
    from_date: str = Query(..., alias="from_date"),
    to_date: str = Query(..., alias="to_date"),
    user: User = Depends(require_access("reports", "team")),
    db: AsyncSession = Depends(get_db),
):
    f, t = await _parse_dates(db, from_date, to_date)
    figures = await _range_figures(db, f, t)
    void_count = (await db.execute(
        select(func.count(Transaction.id)).where(
            Transaction.status == TransactionStatus.voided, *_in_range(Transaction.created_at, f, t)
        )
    )).scalar_one()

    return SalesSummaryResponse(
        from_date=f,
        to_date=t,
        transaction_count=figures.sale_count,
        gross_sales=figures.gross,
        total_discounts=figures.discounts,
        total_tax=figures.net_tax,
        cash_sales=figures.net_cash,
        card_sales=figures.net_card,
        account_sales=figures.net_account,
        refund_count=figures.refund_count,
        refund_total=figures.refund_total,
        void_count=void_count,
        net_sales=figures.net_sales,
    )


# ── GET /api/reports/pnl ──────────────────────────────────────────

@router.get("/pnl", response_model=PnLResponse)
async def pnl_report(
    from_date: str = Query(..., alias="from_date"),
    to_date: str = Query(..., alias="to_date"),
    user: User = Depends(require_access("reports", "team")),
    db: AsyncSession = Depends(get_db),
):
    """Revenue excludes tax and is net of discounts and refunds."""
    f, t = await _parse_dates(db, from_date, to_date)
    revenue = (await _range_figures(db, f, t)).net_sales
    cogs = await cost_of_goods(
        db, _in_range(Transaction.created_at, f, t), _in_range(Refund.created_at, f, t)
    )

    exp_q = select(
        func.coalesce(func.sum(Expense.amount), ZERO).label("expenses"),
    ).where(
        and_(Expense.expense_date >= f.date(), Expense.expense_date <= t.date())
    )
    total_expenses = (await db.execute(exp_q)).one().expenses

    gross_profit = revenue - cogs
    gross_margin_pct = (gross_profit / revenue * ONE) * 100 if revenue else ZERO
    net_profit = gross_profit - total_expenses

    return PnLResponse(
        from_date=f,
        to_date=t,
        revenue=revenue,
        cogs=cogs,
        gross_profit=gross_profit,
        gross_margin_pct=gross_margin_pct,
        total_expenses=total_expenses,
        net_profit=net_profit,
    )


# ── GET /api/reports/tax ──────────────────────────────────────────

@router.get("/tax", response_model=TaxReportResponse)
async def tax_report(
    from_date: str = Query(..., alias="from_date"),
    to_date: str = Query(..., alias="to_date"),
    user: User = Depends(require_access("reports", "team")),
    db: AsyncSession = Depends(get_db),
):
    """Tax collected per day, less tax handed back in refunds that day."""
    f, t = await _parse_dates(db, from_date, to_date)

    zone = f.tzinfo.key
    sale_day = func.date(func.timezone(zone, Transaction.created_at))
    refund_day = func.date(func.timezone(zone, Refund.created_at))
    collected = await db.execute(
        select(sale_day, func.sum(Transaction.tax_amount))
        .where(Transaction.status.in_(SOLD), *_in_range(Transaction.created_at, f, t))
        .group_by(sale_day)
    )
    returned = await db.execute(
        select(refund_day, func.sum(Refund.tax_amount))
        .where(*_in_range(Refund.created_at, f, t))
        .group_by(refund_day)
    )
    by_day: dict = {}
    for day, amount in collected.all():
        by_day[day] = by_day.get(day, Decimal("0")) + amount
    for day, amount in returned.all():
        by_day[day] = by_day.get(day, Decimal("0")) - amount

    daily = [TaxDayEntry(tax_date=day, tax_amount=by_day[day]) for day in sorted(by_day)]
    total = sum((d.tax_amount for d in daily), Decimal("0"))

    return TaxReportResponse(from_date=f, to_date=t, daily_breakdown=daily, total_tax=total)


# ── GET /api/reports/cashier ───────────────────────────────────────

@router.get("/cashier", response_model=CashierReportResponse)
async def cashier_report(
    from_date: str = Query(..., alias="from_date"),
    to_date: str = Query(..., alias="to_date"),
    user_id: int | None = Query(None, alias="user_id"),
    user: User = Depends(require_access("reports", "own")),
    db: AsyncSession = Depends(get_db),
):
    """Per cashier: sales they rang up, less refunds they gave, in the date range."""
    f, t = await _parse_dates(db, from_date, to_date)
    if not sees_everyone(user, "reports"):
        user_id = user.id

    sellers = select(Transaction.cashier_id).where(
        Transaction.status.in_(SOLD), *_in_range(Transaction.created_at, f, t)
    )
    refunders = select(Refund.created_by).where(*_in_range(Refund.created_at, f, t))
    users_q = select(User.id, User.name).where(User.id.in_(sellers.union(refunders))).order_by(User.id)
    if user_id is not None:
        users_q = users_q.where(User.id == user_id)
    users = (await db.execute(users_q)).all()

    cashiers = []
    for uid, name in users:
        figures = await _range_figures(
            db, f, t, Transaction.cashier_id == uid, refund_filters=[Refund.created_by == uid]
        )
        cashiers.append(CashierEntry(
            cashier_id=uid,
            cashier_name=name,
            transaction_count=figures.sale_count,
            gross_sales=figures.gross,
            discounts=figures.discounts,
            net_sales=figures.net_sales,
            cash=figures.net_cash,
            card=figures.net_card,
            account=figures.net_account,
        ))

    return CashierReportResponse(from_date=f, to_date=t, cashiers=cashiers)


# ── GET /api/reports/price-edits ───────────────────────────────────

@router.get("/price-edits", response_model=PriceEditsReportResponse)
async def price_edits_report(
    from_date: str = Query(..., alias="from_date"),
    to_date: str = Query(..., alias="to_date"),
    user: User = Depends(require_access("reports", "team")),
    db: AsyncSession = Depends(get_db),
):
    f, t = await _parse_dates(db, from_date, to_date)

    rows = await db.execute(
        select(
            PriceEditLog,
            User.name.label("editor_name"),
            Product.name.label("product_name"),
        )
        .join(User, User.id == PriceEditLog.edited_by)
        .join(Product, Product.id == PriceEditLog.product_id)
        .where(
            and_(PriceEditLog.edited_at >= f, PriceEditLog.edited_at <= t)
        )
        .order_by(PriceEditLog.edited_at)
    )

    edit_rows = rows.all()
    edits = [
        PriceEditEntry(
            edited_at=e.PriceEditLog.edited_at,
            cashier_name=e.editor_name,
            product_name=e.product_name,
            original_price=e.PriceEditLog.original_price,
            new_price=e.PriceEditLog.new_price,
            difference=e.PriceEditLog.difference,
        )
        for e in edit_rows
    ]
    total_edits = len(edits)
    net_variance = sum((e.difference for e in edits), ZERO)

    return PriceEditsReportResponse(
        from_date=f, to_date=t, edits=edits, total_edits=total_edits, net_variance=net_variance,
    )


# ── GET /api/reports/inventory-value ───────────────────────────────

@router.get("/inventory-value", response_model=InventoryValueReportResponse)
async def inventory_value_report(
    user: User = Depends(require_access("reports", "team")),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        select(Product)
        .where(Product.is_active == True)  # noqa: E712
        .order_by(Product.id)
    )
    products = rows.scalars().all()

    items = []
    total = ZERO
    for p in products:
        val = p.stock_qty * p.cost_price
        items.append(
            InventoryItem(
                product_id=p.id,
                sku=p.sku,
                name=p.name,
                stock_qty=p.stock_qty,
                cost_price=p.cost_price,
                stock_value=val,
            )
        )
        total += val

    return InventoryValueReportResponse(products=items, total_inventory_value=total)


# ── GET /api/reports/low-stock ─────────────────────────────────────

@router.get("/low-stock", response_model=LowStockReportResponse)
async def low_stock_report(
    user: User = Depends(require_access("inventory", "read")),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        select(Product)
        .where(Product.is_active == True)  # noqa: E712
        .where(Product.stock_qty <= Product.low_stock_threshold)
        .order_by(Product.stock_qty.asc())
    )
    products = rows.scalars().all()

    entries = [
        LowStockEntry(
            product_id=p.id,
            sku=p.sku,
            name=p.name,
            stock_qty=p.stock_qty,
            low_stock_threshold=p.low_stock_threshold,
            deficit=p.low_stock_threshold - p.stock_qty,
        )
        for p in products
    ]

    return LowStockReportResponse(products=entries)


# ── GET /api/reports/stock-adjustments ─────────────────────────────

@router.get("/stock-adjustments", response_model=StockAdjustmentsReportResponse)
async def stock_adjustments_report(
    from_date: str = Query(..., alias="from_date"),
    to_date: str = Query(..., alias="to_date"),
    user: User = Depends(require_access("reports", "team")),
    db: AsyncSession = Depends(get_db),
):
    f, t = await _parse_dates(db, from_date, to_date)

    rows = await db.execute(
        select(
            StockAdjustment,
            Product.name.label("product_name"),
            Product.sku.label("sku"),
            User.name.label("adjustor_name"),
        )
        .join(Product, Product.id == StockAdjustment.product_id)
        .join(User, User.id == StockAdjustment.adjusted_by_id)
        .where(
            and_(StockAdjustment.created_at >= f, StockAdjustment.created_at <= t)
        )
        .order_by(StockAdjustment.created_at)
    )

    adj_rows = rows.all()
    adjustments = [
        StockAdjustmentEntry(
            created_at=a.StockAdjustment.created_at,
            product_name=a.product_name,
            sku=a.sku,
            qty_before=a.StockAdjustment.qty_before,
            qty_after=a.StockAdjustment.qty_after,
            adjustment=a.StockAdjustment.adjustment,
            reason=a.StockAdjustment.reason,
            adjusted_by_name=a.adjustor_name,
        )
        for a in adj_rows
    ]

    return StockAdjustmentsReportResponse(
        from_date=f, to_date=t, adjustments=adjustments,
    )


# ── Purchases Report ──────────────────────────────────────────────
@router.get("/purchases")
async def purchases_report(
    from_date: str = Query(None),
    to_date: str = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_access("reports", "team")),
):
    f, t = await _parse_dates(db, from_date, to_date)

    stmt = (
        select(PurchaseOrder)
        .options(
            sqlalchemy.orm.selectinload(PurchaseOrder.lines).selectinload(PurchaseOrderLine.product),
            sqlalchemy.orm.selectinload(PurchaseOrder.created_by),
        )
        .where(PurchaseOrder.created_at >= f, PurchaseOrder.created_at <= t)
        .order_by(PurchaseOrder.created_at.desc())
    )
    result = await db.execute(stmt)
    orders = result.unique().scalars().all()

    total_cost = Decimal("0")
    order_list = []
    for po in orders:
        lines = []
        for ln in po.lines:
            lines.append({
                "product_name": ln.product.name if ln.product else "?",
                "sku": ln.product.sku if ln.product else "?",
                "qty": float(ln.qty),
                "unit_cost": float(ln.unit_cost),
                "total_cost": float(ln.total_cost),
                "wac_before": float(ln.wac_before),
                "wac_after": float(ln.wac_after),
            })
        total_cost += po.total_amount
        order_list.append({
            "id": po.id,
            "ref_number": po.ref_number,
            "status": po.status.value if hasattr(po.status, "value") else str(po.status),
            "supplier_name": po.supplier.name if po.supplier else "?",
            "created_by_name": po.created_by.username if po.created_by else "?",
            "created_at": po.created_at.isoformat() if po.created_at else None,
            "total_amount": float(po.total_amount),
            "lines": lines,
        })

    return {
        "from_date": f.isoformat(),
        "to_date": t.isoformat(),
        "total_orders": len(order_list),
        "total_cost": float(total_cost),
        "orders": order_list,
    }
