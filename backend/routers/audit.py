from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.access import require_access
from database import get_db
from models.audit import AuditLog, StockMovement
from models.product import Product
from models.user import User
from schemas.audit import AuditListResponse, StockMovementRow, StockMovementsResponse
from services.audit import load_entries
from services.clock import day_end, day_start, parse_day, shop_zone

router = APIRouter(prefix="/audit", tags=["audit"])


async def _date_range(db: AsyncSession, from_date: str | None, to_date: str | None) -> list:
    """Whole days in the shop's time zone."""
    zone = await shop_zone(db)
    filters = []
    if from_date:
        filters.append(AuditLog.created_at >= day_start(parse_day(from_date), zone))
    if to_date:
        filters.append(AuditLog.created_at <= day_end(parse_day(to_date), zone))
    return filters


@router.get("", response_model=AuditListResponse)
async def list_audit(
    shift_id: int | None = Query(None),
    user_id: int | None = Query(None),
    action: str | None = Query(None),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_access("reports", "team")),
):
    """The trail itself: every stock, cash, card and account movement, newest last."""
    filters = await _date_range(db, from_date, to_date)
    if shift_id is not None:
        filters.append(AuditLog.shift_id == shift_id)
    if user_id is not None:
        filters.append(AuditLog.user_id == user_id)
    if action:
        filters.append(AuditLog.action == action)

    entries = await load_entries(db, filters, limit)
    totals = (await db.execute(
        select(
            func.coalesce(func.sum(AuditLog.cash), 0),
            func.coalesce(func.sum(AuditLog.card), 0),
            func.coalesce(func.sum(AuditLog.account), 0),
        ).where(*filters)
    )).one()
    return AuditListResponse(
        entries=entries, total_cash=totals[0], total_card=totals[1], total_account=totals[2]
    )


@router.get("/stock", response_model=StockMovementsResponse)
async def list_stock_movements(
    product_id: int | None = Query(None),
    shift_id: int | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_access("reports", "team")),
):
    """Every stock quantity change with its before/after, newest first."""
    stmt = (
        select(StockMovement, Product.name, AuditLog.created_at, AuditLog.action, AuditLog.ref,
               AuditLog.shift_id, User.name)
        .join(Product, Product.id == StockMovement.product_id)
        .join(AuditLog, AuditLog.id == StockMovement.audit_id)
        .join(User, User.id == AuditLog.user_id)
        .order_by(StockMovement.id.desc())
        .limit(limit)
    )
    if product_id is not None:
        stmt = stmt.where(StockMovement.product_id == product_id)
    if shift_id is not None:
        stmt = stmt.where(AuditLog.shift_id == shift_id)
    rows = (await db.execute(stmt)).all()
    return StockMovementsResponse(movements=[
        StockMovementRow(
            product_id=move.product_id,
            product_name=product_name,
            qty_change=move.qty_change,
            qty_before=move.qty_before,
            qty_after=move.qty_after,
            created_at=created_at,
            action=action,
            ref=ref,
            shift_id=row_shift_id,
            user_name=user_name,
        )
        for move, product_name, created_at, action, ref, row_shift_id, user_name in rows
    ])
