"""Audit trail: who moved stock, cash, card or account money, when, and in which shift.

Every write path that changes stock quantities, cost prices, customer balances or the
money in a shift calls log_event() inside the same database transaction as the change,
so an entry exists exactly when the change was committed.
"""
import json
from decimal import Decimal

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.audit import AuditLog, StockMovement
from models.product import Product
from models.shift import Shift, ShiftStatus
from models.user import User
from schemas.audit import AuditEntry, StockMovementEntry

ZERO = Decimal("0")

def log_details(details: dict | None) -> dict | None:
    """JSON-safe copy of details (Decimals and dates become strings)."""
    return json.loads(json.dumps(details, default=str)) if details else None


def log_event(
    db: AsyncSession,
    action: str,
    summary: str,
    *,
    user_id: int,
    shift_id: int | None,
    ref: str | None = None,
    amount: Decimal | None = None,
    cash: Decimal = ZERO,
    card: Decimal = ZERO,
    account: Decimal = ZERO,
    details: dict | None = None,
) -> AuditLog:
    """cash/card/account are signed: money into the business is positive, money paid out negative."""
    entry = AuditLog(
        user_id=user_id,
        shift_id=shift_id,
        action=action,
        ref=ref,
        amount=amount,
        cash=cash,
        card=card,
        account=account,
        summary=summary,
        details=log_details(details),
        stock_movements=[],
    )
    db.add(entry)
    return entry


async def active_shift_id(db: AsyncSession, user_id: int) -> int | None:
    """The user's open shift, so back-office changes made during a shift show on its report."""
    return (await db.execute(
        select(Shift.id).where(Shift.cashier_id == user_id, Shift.status == ShiftStatus.open)
    )).scalar_one_or_none()


def changed_fields(obj: object, updates: dict) -> dict[str, dict]:
    """{field: {"from": old, "to": new}} for the updates that actually change obj."""
    return {
        field: {"from": getattr(obj, field), "to": value}
        for field, value in updates.items()
        if getattr(obj, field) != value
    }


def record_stock(entry: AuditLog, product: Product, new_qty: Decimal) -> None:
    """Set a product's stock and attach the before/after movement to the audit entry."""
    before = product.stock_qty or ZERO
    if new_qty == before:
        return
    entry.stock_movements.append(
        StockMovement(product_id=product.id, qty_change=new_qty - before, qty_before=before, qty_after=new_qty)
    )
    product.stock_qty = new_qty


# ── Reading the trail back ──────────────────────────────────────

async def load_entries(
    db: AsyncSession, filters: list[ColumnElement[bool]], limit: int | None = None
) -> list[AuditEntry]:
    """Audit entries matching filters, oldest first, with user and product names."""
    stmt = (
        select(AuditLog, User.name)
        .join(User, User.id == AuditLog.user_id)
        .where(*filters)
        .order_by(AuditLog.id.desc() if limit else AuditLog.id)
    )
    if limit:
        stmt = stmt.limit(limit)
    rows = (await db.execute(stmt)).all()
    if limit:
        rows.reverse()
    movements = await _movements_by_entry(db, [entry.id for entry, _ in rows])
    return [
        AuditEntry(
            id=entry.id,
            created_at=entry.created_at,
            user_id=entry.user_id,
            user_name=user_name,
            shift_id=entry.shift_id,
            action=entry.action,
            ref=entry.ref,
            amount=entry.amount,
            cash=entry.cash,
            card=entry.card,
            account=entry.account,
            summary=entry.summary,
            details=entry.details,
            stock_movements=movements.get(entry.id, []),
        )
        for entry, user_name in rows
    ]


async def _movements_by_entry(db: AsyncSession, entry_ids: list[int]) -> dict[int, list[StockMovementEntry]]:
    if not entry_ids:
        return {}
    rows = (await db.execute(
        select(StockMovement, Product.name)
        .join(Product, Product.id == StockMovement.product_id)
        .where(StockMovement.audit_id.in_(entry_ids))
        .order_by(StockMovement.id)
    )).all()
    grouped: dict[int, list[StockMovementEntry]] = {}
    for move, product_name in rows:
        grouped.setdefault(move.audit_id, []).append(StockMovementEntry(
            product_id=move.product_id,
            product_name=product_name,
            qty_change=move.qty_change,
            qty_before=move.qty_before,
            qty_after=move.qty_after,
        ))
    return grouped
