from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.auth import get_current_active_user
from core.access import forbidden, is_admin, require_flag
from database import get_db
from models.audit import AuditLog, StockMovement
from models.shift import Shift, ShiftStatus
from models.transaction import (
    PriceEditLog,
    Transaction,
    TransactionLine,
    TransactionStatus,
)
from models.user import User
from services.audit import log_event
from services.sales import (
    apply_totals,
    cart_discount_of,
    compute_totals,
    find_client_sale,
    open_shift_for,
    record_sale,
    refund_sale,
    require_open_shift,
)
from services.settings import load_settings
from schemas.transactions import (
    PriceEditRequest,
    RefundInfo,
    RefundPayload,
    TransactionCreate,
    TransactionLineResponse,
    TransactionResponse,
)

router = APIRouter(prefix="/transactions", tags=["transactions"])


# ── Helpers ──────────────────────────────────────────────────────

def _line_response(line: TransactionLine) -> TransactionLineResponse:
    return TransactionLineResponse(
        id=line.id,
        transaction_id=line.transaction_id,
        product_id=line.product_id,
        product_name=line.product.name if line.product else None,
        qty=line.qty,
        original_price=line.original_price,
        sell_price=line.sell_price,
        cost_price=line.cost_price,
        discount=line.discount,
        line_total=line.line_total,
        refunded_qty=line.refunded_qty,
    )


class _Links:
    """Shift state, re-issue references and oversold flags for a batch of receipts."""

    def __init__(
        self,
        open_shift_ids: set[int],
        refs: dict[int, str],
        reissued_as: dict[int, str],
        oversold_refs: set[str],
    ):
        self.open_shift_ids = open_shift_ids
        self.refs = refs
        self.reissued_as = reissued_as
        self.oversold_refs = oversold_refs


async def _links(db: AsyncSession, txns: list[Transaction]) -> _Links:
    open_ids = set((await db.execute(select(Shift.id).where(Shift.status == ShiftStatus.open))).scalars().all())
    ids = [t.id for t in txns]
    source_ids = [t.reissue_of_id for t in txns if t.reissue_of_id]
    refs = dict((await db.execute(
        select(Transaction.id, Transaction.ref_number).where(Transaction.id.in_(source_ids))
    )).all()) if source_ids else {}
    reissued_as = dict((await db.execute(
        select(Transaction.reissue_of_id, Transaction.ref_number).where(
            Transaction.reissue_of_id.in_(ids),
            Transaction.status.in_([TransactionStatus.completed, TransactionStatus.refunded]),
        )
    )).all()) if ids else {}
    ref_numbers = [t.ref_number for t in txns]
    oversold_refs = set((await db.execute(
        select(AuditLog.ref)
        .join(StockMovement, StockMovement.audit_id == AuditLog.id)
        .where(
            AuditLog.action == "sale",
            AuditLog.ref.in_(ref_numbers),
            StockMovement.qty_after < 0,
        )
    )).scalars().all()) if ref_numbers else set()
    return _Links(open_ids, refs, reissued_as, oversold_refs)


def _txn_response(txn: Transaction, links: _Links) -> TransactionResponse:
    refund = txn.refunds[-1] if txn.refunds else None
    return TransactionResponse(
        id=txn.id,
        ref_number=txn.ref_number,
        cashier_id=txn.cashier_id,
        shift_id=txn.shift_id,
        customer_id=txn.customer_id,
        customer_name=txn.customer.name if txn.customer else None,
        status=txn.status.value if isinstance(txn.status, TransactionStatus) else txn.status,
        subtotal=txn.subtotal,
        discount_amount=txn.discount_amount,
        tax_amount=txn.tax_amount,
        total_amount=txn.total_amount,
        payment_cash=txn.payment_cash,
        payment_card=txn.payment_card,
        payment_account=txn.payment_account,
        change_given=txn.change_given,
        refunded_amount=txn.refunded_amount,
        notes=txn.notes,
        is_offline=txn.is_offline,
        oversold=txn.ref_number in links.oversold_refs,
        transaction_lines=[_line_response(l) for l in txn.lines],
        created_at=txn.created_at,
        refundable=txn.status == TransactionStatus.completed and txn.shift_id in links.open_shift_ids,
        refund=RefundInfo(
            ref_number=refund.ref_number,
            amount=refund.amount,
            refund_cash=refund.refund_cash,
            refund_card=refund.refund_card,
            refund_account=refund.refund_account,
            reason=refund.reason,
            created_by=refund.created_by,
            created_at=refund.created_at,
        ) if refund else None,
        reissue_of_id=txn.reissue_of_id,
        reissue_of_ref=links.refs.get(txn.reissue_of_id) if txn.reissue_of_id else None,
        reissued_as_ref=links.reissued_as.get(txn.id),
    )


async def _respond(db: AsyncSession, txns: list[Transaction]) -> list[TransactionResponse]:
    links = await _links(db, txns)
    return [_txn_response(t, links) for t in txns]


TXN_LOAD_OPTIONS = (
    selectinload(Transaction.lines).selectinload(TransactionLine.product),
    selectinload(Transaction.customer),
    selectinload(Transaction.refunds),
)


async def _load_txn(db: AsyncSession, txn_id: int, for_update: bool = False) -> Transaction:
    stmt = select(Transaction).options(*TXN_LOAD_OPTIONS).where(Transaction.id == txn_id)
    if for_update:
        stmt = stmt.with_for_update(of=Transaction)
    txn = (await db.execute(stmt)).scalar_one_or_none()
    if not txn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return txn


async def _commit_and_respond(db: AsyncSession, txn_id: int) -> TransactionResponse:
    await db.commit()
    db.expire_all()
    return (await _respond(db, [await _load_txn(db, txn_id)]))[0]


# ── POST /api/transactions ──────────────────────────────────────

@router.post("", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    data: TransactionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """A repeated checkout (same device_id and client_ref, e.g. the till retrying after
    a lost reply) returns the sale that was already recorded instead of a second one."""
    existing_id = await find_client_sale(db, data.device_id, data.client_ref)
    if existing_id:
        return (await _respond(db, [await _load_txn(db, existing_id)]))[0]
    shift = await require_open_shift(db, user.id)
    try:
        txn = await record_sale(db, data, user.id, shift.id, seller=user)
        return await _commit_and_respond(db, txn.id)
    except IntegrityError:
        await db.rollback()
        existing_id = await find_client_sale(db, data.device_id, data.client_ref)
        if not existing_id:
            raise
        return (await _respond(db, [await _load_txn(db, existing_id)]))[0]


# ── GET /api/transactions ───────────────────────────────────────

@router.get("", response_model=list[TransactionResponse])
async def list_transactions(
    status_filter: str | None = Query(None, alias="status"),
    customer_id: int | None = Query(None),
    shift_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    stmt = select(Transaction).options(*TXN_LOAD_OPTIONS)
    if status_filter:
        try:
            status_enum = TransactionStatus(status_filter)
            stmt = stmt.where(Transaction.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {status_filter}. Valid: {', '.join(s.value for s in TransactionStatus)}",
            )
    if customer_id is not None:
        stmt = stmt.where(Transaction.customer_id == customer_id)
    if shift_id is not None:
        stmt = stmt.where(Transaction.shift_id == shift_id)
    stmt = stmt.order_by(Transaction.created_at.desc()).limit(limit).offset(offset)
    txns = list((await db.execute(stmt)).scalars().all())
    return await _respond(db, txns)


# ── GET /api/transactions/held ───────────────────────────────────

@router.get("/held", response_model=list[TransactionResponse])
async def list_held_transactions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    result = await db.execute(
        select(Transaction)
        .options(*TXN_LOAD_OPTIONS)
        .where(Transaction.cashier_id == user.id, Transaction.status == TransactionStatus.held)
        .order_by(Transaction.created_at.desc())
    )
    return await _respond(db, list(result.scalars().all()))


# ── GET /api/transactions/{txn_id} ──────────────────────────────

@router.get("/{txn_id}", response_model=TransactionResponse)
async def get_transaction(
    txn_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    return (await _respond(db, [await _load_txn(db, txn_id)]))[0]


# ── POST /api/transactions/{txn_id}/resume ──────────────────────

@router.post("/{txn_id}/resume", response_model=TransactionResponse)
async def resume_transaction(
    txn_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Take a held ticket back into the cart: returns it and deletes the held copy.

    A held ticket never touched stock or balances, so deleting it is safe; the
    register then rings it up as a normal sale. The audit trail keeps a record.
    """
    txn = await _load_txn(db, txn_id, for_update=True)
    if txn.status != TransactionStatus.held:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Transaction is not held")
    if txn.cashier_id != user.id and not is_admin(user):
        raise forbidden("This ticket was held by someone else")
    response = (await _respond(db, [txn]))[0]
    shift = await open_shift_for(db, user.id)
    log_event(
        db, "held_resumed", f"Ticket {txn.ref_number} taken back into the cart",
        user_id=user.id, shift_id=shift.id if shift else None, ref=txn.ref_number, amount=txn.total_amount,
    )
    await db.delete(txn)
    await db.commit()
    return response


# ── POST /api/transactions/{txn_id}/refund ──────────────────────

@router.post("/{txn_id}/refund", response_model=TransactionResponse)
async def refund_transaction(
    txn_id: int,
    data: RefundPayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_flag("refund")),
):
    txn = await _load_txn(db, txn_id, for_update=True)
    await refund_sale(db, txn, user.id, data.reason.strip())
    return await _commit_and_respond(db, txn_id)


# ── PUT /api/transactions/{txn_id}/lines/{line_id}/price ────────

@router.put("/{txn_id}/lines/{line_id}/price", response_model=TransactionResponse)
async def edit_line_price(
    txn_id: int,
    line_id: int,
    data: PriceEditRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_flag("edit_price")),
):
    """Only held tickets can be repriced; a paid sale is corrected by refunding it and re-issuing."""

    txn = await _load_txn(db, txn_id, for_update=True)
    if txn.status != TransactionStatus.held:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only held tickets can be repriced. Refund a paid sale and ring it up again instead.",
        )

    line = next((l for l in txn.lines if l.id == line_id), None)
    if not line:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Line not found")

    original_price = line.sell_price
    cart_discount = cart_discount_of(txn)
    line.sell_price = data.new_price

    db.add(PriceEditLog(
        transaction_line_id=line.id,
        transaction_id=txn.id,
        product_id=line.product_id,
        edited_by=user.id,
        original_price=original_price,
        new_price=data.new_price,
        difference=data.new_price - original_price,
    ))

    tax_rate = (await load_settings(db)).tax_rate
    apply_totals(txn, compute_totals(txn.lines, cart_discount, tax_rate))

    shift = await open_shift_for(db, user.id)
    log_event(
        db, "price_edit",
        f"Ticket {txn.ref_number}: {line.product.name if line.product else line.product_id} "
        f"repriced {original_price:.2f} → {data.new_price:.2f}",
        user_id=user.id, shift_id=shift.id if shift else None, ref=txn.ref_number,
        amount=data.new_price - original_price,
    )
    return await _commit_and_respond(db, txn_id)
