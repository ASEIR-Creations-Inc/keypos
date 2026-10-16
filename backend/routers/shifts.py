from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from core.access import forbidden, require_access, sees_everyone
from core.auth import get_current_active_user
from database import get_db
from models.audit import AuditLog
from models.shift import Shift, ShiftStatus
from models.transaction import PriceEditLog, Refund, Transaction, TransactionStatus
from models.user import User
from schemas.shifts import RefundedReceipt, ShiftClose, ShiftOpen, ShiftReport, ShiftResponse, ZReport
from services.audit import load_entries, log_event
from services.figures import DrawerFigures, SalesFigures, drawer_figures, sales_figures

router = APIRouter(prefix="/shifts", tags=["shifts"])


# ── Helpers ──────────────────────────────────────────────────────

def _shift_response(shift: Shift) -> ShiftResponse:
    return ShiftResponse(
        id=shift.id,
        cashier_id=shift.cashier_id,
        cashier_name=shift.cashier.name if shift.cashier else None,
        opening_float=shift.opening_float,
        closing_cash=shift.closing_cash,
        expected_cash=shift.expected_cash,
        variance=shift.variance,
        status=shift.status.value if isinstance(shift.status, ShiftStatus) else shift.status,
        opened_at=shift.opened_at.isoformat() if shift.opened_at else None,
        closed_at=shift.closed_at.isoformat() if shift.closed_at else None,
    )


async def _shift_figures(db: AsyncSession, shift_id: int) -> SalesFigures:
    return await sales_figures(db, [Transaction.shift_id == shift_id], [Refund.shift_id == shift_id])


def _expected_cash(shift: Shift, figures: SalesFigures, drawer: DrawerFigures) -> Decimal:
    """Float + cash taken for sales (net of change and cash refunds) + cash account payments − drawer expenses."""
    return shift.opening_float + figures.net_cash + drawer.payments_cash - drawer.drawer_expenses


async def _refunded_receipts(db: AsyncSession, shift_id: int) -> list[RefundedReceipt]:
    reissue = aliased(Transaction)
    rows = (await db.execute(
        select(Refund, Transaction.ref_number, Transaction.created_at, User.name, reissue.ref_number)
        .join(Transaction, Transaction.id == Refund.transaction_id)
        .join(User, User.id == Refund.created_by)
        .outerjoin(reissue, (reissue.reissue_of_id == Transaction.id) & reissue.status.in_(
            [TransactionStatus.completed, TransactionStatus.refunded]
        ))
        .where(Refund.shift_id == shift_id)
        .order_by(Refund.id)
    )).all()
    return [
        RefundedReceipt(
            refund_ref=refund.ref_number,
            sale_ref=sale_ref,
            sale_created_at=sale_at,
            refunded_at=refund.created_at,
            amount=refund.amount,
            refund_cash=refund.refund_cash,
            refund_card=refund.refund_card,
            refund_account=refund.refund_account,
            reason=refund.reason,
            refunded_by=user_name,
            reissued_as=reissued_as,
        )
        for refund, sale_ref, sale_at, user_name, reissued_as in rows
    ]


async def _build_z_report(db: AsyncSession, shift_id: int) -> ZReport:
    """Full Z-report: sales rung up in this shift, and refunds given in it."""
    shift_result = await db.execute(
        select(Shift).options(selectinload(Shift.cashier)).where(Shift.id == shift_id)
    )
    shift = shift_result.scalar_one_or_none()
    if not shift:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shift not found")

    figures = await _shift_figures(db, shift_id)
    drawer = await drawer_figures(db, shift_id)

    edit_row = (await db.execute(
        select(
            func.count(PriceEditLog.id).label("price_edit_count"),
            func.coalesce(func.sum(PriceEditLog.difference), Decimal("0")).label("price_edit_variance"),
        ).where(
            PriceEditLog.transaction_id.in_(
                select(Transaction.id).where(Transaction.shift_id == shift_id)
            )
        )
    )).one()

    offline_row = (await db.execute(
        select(
            func.count(Transaction.id),
            func.coalesce(func.sum(Transaction.total_amount), Decimal("0")),
        ).where(
            Transaction.shift_id == shift_id,
            Transaction.is_offline.is_(True),
            Transaction.status != TransactionStatus.held,
        )
    )).one()

    report = ShiftReport(
        total_transactions=figures.sale_count,
        gross_sales=figures.gross,
        total_discounts=figures.discounts,
        total_refunds=figures.refund_total,
        refund_count=figures.refund_count,
        net_sales=figures.net_sales,
        tax_collected=figures.net_tax,
        cash_sales=figures.net_cash,
        card_sales=figures.net_card,
        account_sales=figures.net_account,
        price_edit_count=edit_row.price_edit_count,
        price_edit_variance=edit_row.price_edit_variance,
        customer_payments_cash=drawer.payments_cash,
        customer_payments_card=drawer.payments_card,
        drawer_expenses=drawer.drawer_expenses,
        expected_cash=shift.expected_cash if shift.expected_cash is not None else _expected_cash(shift, figures, drawer),
        offline_sales_count=offline_row[0],
        offline_sales_total=offline_row[1],
    )

    counts = dict((await db.execute(
        select(AuditLog.action, func.count(AuditLog.id)).where(AuditLog.shift_id == shift_id).group_by(AuditLog.action)
    )).all())
    activity = await load_entries(db, [AuditLog.shift_id == shift_id, AuditLog.action != "sale"])

    return ZReport(
        shift=_shift_response(shift),
        report=report,
        refunds=await _refunded_receipts(db, shift_id),
        activity=activity,
        activity_counts=counts,
    )


# ── POST /api/shifts/open ──────────────────────────────────────

async def _attach_late_offline_sales(db: AsyncSession, shift_id: int, cashier_id: int) -> None:
    """Book offline sales that synced while no shift was open to the shift opening now.

    A closed shift's report is final, so they cannot go back to the shift they were
    rung up in; this way they still land on a Z-report, and its trail says why.
    """
    late = list((await db.execute(
        select(Transaction)
        .where(
            Transaction.shift_id.is_(None),
            Transaction.is_offline.is_(True),
            Transaction.cashier_id == cashier_id,
            Transaction.status == TransactionStatus.completed,
        )
        .order_by(Transaction.created_at)
        .with_for_update()
    )).scalars().all())
    if not late:
        return
    for txn in late:
        txn.shift_id = shift_id
    log_event(
        db, "offline_sales_attached",
        f"{len(late)} offline sale(s) synced while no shift was open, booked to this shift: "
        + ", ".join(t.ref_number for t in late),
        user_id=cashier_id, shift_id=shift_id,
        amount=sum((t.total_amount for t in late), Decimal("0")),
        details={
            "note": "Money was already logged on each sale's own entry; it is not repeated here.",
            "sales": [
                {"ref": t.ref_number, "rung_up_at": t.created_at, "total": t.total_amount,
                 "cash": t.payment_cash - t.change_given, "card": t.payment_card,
                 "account": t.payment_account}
                for t in late
            ],
        },
    )


@router.post("/open", response_model=ShiftResponse, status_code=status.HTTP_201_CREATED)
async def open_shift(
    data: ShiftOpen,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    existing = await db.execute(
        select(Shift).where(Shift.cashier_id == user.id, Shift.status == ShiftStatus.open)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Shift already open")

    shift = Shift(
        cashier_id=user.id,
        opening_float=data.opening_float,
        status=ShiftStatus.open,
        opened_at=datetime.now(timezone.utc),
    )
    db.add(shift)
    await db.flush()
    log_event(
        db, "shift_open", f"Shift #{shift.id} opened with a float of {data.opening_float:.2f}",
        user_id=user.id, shift_id=shift.id, amount=data.opening_float,
    )
    await _attach_late_offline_sales(db, shift.id, user.id)
    await db.commit()
    await db.refresh(shift, attribute_names=["cashier"])
    return _shift_response(shift)


# ── GET /api/shifts/current ──────────────────────────────────────

@router.get("/current", response_model=ShiftResponse)
async def current_shift(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    result = await db.execute(
        select(Shift)
        .options(selectinload(Shift.cashier))
        .where(Shift.cashier_id == user.id, Shift.status == ShiftStatus.open)
    )
    shift = result.scalar_one_or_none()
    if not shift:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No open shift")
    return _shift_response(shift)


# ── POST /api/shifts/close ──────────────────────────────────────

@router.post("/close", response_model=ZReport)
async def close_shift(
    data: ShiftClose,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    result = await db.execute(
        select(Shift)
        .where(Shift.cashier_id == user.id, Shift.status == ShiftStatus.open)
    )
    shift = result.scalar_one_or_none()
    if not shift:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No open shift to close")

    figures = await _shift_figures(db, shift.id)
    drawer = await drawer_figures(db, shift.id)
    expected_cash = _expected_cash(shift, figures, drawer)
    variance = data.closing_cash - expected_cash

    shift.closing_cash = data.closing_cash
    shift.expected_cash = expected_cash
    shift.variance = variance
    shift.status = ShiftStatus.closed
    shift.closed_at = datetime.now(timezone.utc)
    log_event(
        db, "shift_close",
        f"Shift #{shift.id} closed: counted {data.closing_cash:.2f}, expected {expected_cash:.2f}, "
        f"variance {variance:.2f}",
        user_id=user.id, shift_id=shift.id, amount=data.closing_cash,
        details={"expected_cash": expected_cash, "variance": variance, "opening_float": shift.opening_float},
    )

    await db.commit()
    await db.refresh(shift)

    return await _build_z_report(db, shift.id)


# ── GET /api/shifts/{id}/report ──────────────────────────────────

@router.get("/{shift_id}/report", response_model=ZReport)
async def get_shift_report(
    shift_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_access("reports", "own")),
):
    """Staff with "own" report access see only their own shifts' reports."""
    if not sees_everyone(user, "reports"):
        owner = (await db.execute(select(Shift.cashier_id).where(Shift.id == shift_id))).scalar_one_or_none()
        if owner is not None and owner != user.id:
            raise forbidden("You can only see reports for your own shifts")
    return await _build_z_report(db, shift_id)


# ── GET /api/shifts ──────────────────────────────────────────────

@router.get("", response_model=list[ShiftResponse])
async def list_shifts(
    shift_id: int | None = Query(None),
    status: str | None = Query(None),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_access("reports", "own")),
):
    stmt = select(Shift).options(selectinload(Shift.cashier))
    if not sees_everyone(user, "reports"):
        stmt = stmt.where(Shift.cashier_id == user.id)
    if shift_id is not None:
        stmt = stmt.where(Shift.id == shift_id)
    if status:
        try:
            status_enum = ShiftStatus(status)
            stmt = stmt.where(Shift.status == status_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    if from_date:
        stmt = stmt.where(Shift.opened_at >= datetime.fromisoformat(from_date))
    if to_date:
        stmt = stmt.where(Shift.opened_at <= datetime.fromisoformat(to_date).replace(hour=23, minute=59, second=59))
    stmt = stmt.order_by(Shift.opened_at.desc()).limit(limit).offset(offset)
    results = await db.execute(stmt)
    shifts = results.scalars().all()
    return [_shift_response(s) for s in shifts]
