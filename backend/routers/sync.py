from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.access import LEVELS, access_level
from core.auth import get_current_active_user, verify_token
from database import get_db
from models.expense import ExpenseCategory
from models.purchase import PurchaseOrder, PurchaseOrderLine, PurchaseStatus, Supplier
from models.sync import StockAdjustment, SyncQueue
from models.user import User
from routers.purchases import purchase_entry, receive_into_stock
from schemas.transactions import TransactionCreate
from services import expenses as expense_service
from services.audit import active_shift_id, log_details, log_event, record_stock
from services.clock import shop_today
from services.sales import find_client_sale, lock_products, next_ref, open_shift_for, record_sale
from schemas.sync import (
    SyncActionResult,
    SyncRequest,
    SyncResponse,
    SyncStatusResponse,
)

router = APIRouter(prefix="/sync", tags=["sync"])

# An action made offline is credited to the person signed in when it was made, as long
# as that login was issued within this window; otherwise to whoever is syncing it.
OFFLINE_LOGIN_MAX_AGE = timedelta(days=7)


@dataclass(frozen=True)
class Author:
    """Who made a queued action. Plain values: the session rolls back between actions."""
    id: int
    can_adjust_stock: bool
    can_post_purchases: bool


def _author_of(user: User) -> Author:
    return Author(
        id=user.id,
        can_adjust_stock=access_level(user, "inventory") >= LEVELS["full"],
        can_post_purchases=access_level(user, "purchases") >= LEVELS["full"],
    )


async def _resolve_author(db: AsyncSession, token: str | None, syncing: Author) -> Author:
    if not token:
        return syncing
    try:
        user_id = verify_token(token, max_age=OFFLINE_LOGIN_MAX_AGE)
    except HTTPException:
        return syncing
    if user_id == syncing.id:
        return syncing
    user = (await db.execute(
        select(User).options(selectinload(User.permissions)).where(User.id == user_id)
    )).scalar_one_or_none()
    return _author_of(user) if user else syncing


# ── POST /api/sync — bulk push offline queue ────────────────────

@router.post("", response_model=SyncResponse, status_code=status.HTTP_200_OK)
async def push_sync(
    data: SyncRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Process bulk offline queue push. Each action queued then processed.

    Actions carry a client_ref generated once on the device; a ref this device has
    already synced is answered from the queue row instead of being processed twice,
    so a retried push can never duplicate a sale.
    """
    syncing = _author_of(user)
    results: list[SyncActionResult] = []
    processed = 0
    failed = 0

    for idx, action in enumerate(data.actions):
        result = SyncActionResult(index=idx, action_type=action.action_type, success=False)
        try:
            replay_id = await _find_replay(db, data.device_id, action.client_ref)
            if replay_id is not None:
                result.success = True
                result.duplicate = True
                result.record_id = replay_id
                processed += 1
                results.append(result)
                continue

            # Save to sync_queue first
            queue_entry = SyncQueue(
                device_id=data.device_id,
                action_type=action.action_type,
                payload=action.payload,
                client_ref=action.client_ref,
                synced=False,
            )
            db.add(queue_entry)
            await db.flush()

            author = await _resolve_author(db, action.auth_token, syncing)
            if action.action_type == "sale":
                record_id = await _process_sale(
                    db, action.payload, data.device_id, action.client_ref, author.id,
                    action.offline_created_at,
                )
            elif action.action_type == "expense":
                record_id = await _process_expense(db, action.payload, author.id)
            elif action.action_type == "adjustment":
                if not author.can_adjust_stock:
                    raise ValueError("Not allowed to adjust stock")
                record_id = await _process_adjustment(db, action.payload, data.device_id, author.id)
            elif action.action_type == "purchase":
                if not author.can_post_purchases:
                    raise ValueError("Not allowed to post purchases")
                record_id = await _process_purchase(db, action.payload, data.device_id, author.id)
            else:
                # Dead-letter: an action type this server does not know can never be
                # processed, so the row is kept (synced, record_id NULL) for review
                # instead of blocking the device's pending count forever.
                queue_entry.synced = True
                queue_entry.synced_at = datetime.now(timezone.utc)
                await db.commit()
                raise ValueError(f"Unknown action_type: {action.action_type}")

            # Mark sync_queue entry as synced
            queue_entry.synced = True
            queue_entry.synced_at = datetime.now(timezone.utc)
            queue_entry.record_id = record_id
            await db.commit()

            result.success = True
            result.record_id = record_id
            processed += 1

        except Exception as e:
            try:
                await db.rollback()
            except Exception:
                pass
            result.error = str(e)
            failed += 1

        results.append(result)

    return SyncResponse(
        device_id=data.device_id,
        received=len(data.actions),
        processed=processed,
        failed=failed,
        results=results,
    )


# ── GET /api/sync/status — device sync info ─────────────────────

@router.get("/status", response_model=SyncStatusResponse)
async def sync_status(
    device_id: str = Query(..., description="Device identifier"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Return last sync time and pending count for a device."""
    now = datetime.now(timezone.utc)

    # Last synced: most recent synced_at for this device
    last_result = await db.execute(
        select(SyncQueue.synced_at)
        .where(SyncQueue.device_id == device_id, SyncQueue.synced.is_(True))
        .order_by(SyncQueue.synced_at.desc())
        .limit(1)
    )
    last_row = last_result.first()
    last_synced_at = last_row[0] if last_row else None

    # Pending count: actions not yet synced
    pending_result = await db.execute(
        select(func.count())
        .where(SyncQueue.device_id == device_id, SyncQueue.synced.is_(False))
    )
    pending_count = pending_result.scalar() or 0

    return SyncStatusResponse(
        device_id=device_id,
        last_synced_at=last_synced_at,
        pending_count=pending_count,
        server_time=now,
    )


# ── Internal action processors ──────────────────────────────────

async def _find_replay(db: AsyncSession, device_id: str, client_ref: str | None) -> int | None:
    """Record id of an action this device already synced under the same client_ref, if any."""
    if not client_ref:
        return None
    row = (await db.execute(
        select(SyncQueue.record_id)
        .where(
            SyncQueue.device_id == device_id,
            SyncQueue.client_ref == client_ref,
            SyncQueue.synced.is_(True),
        )
        .limit(1)
    )).first()
    return row[0] if row else None


async def _process_sale(
    db: AsyncSession,
    payload: dict,
    device_id: str,
    client_ref: str | None,
    cashier_id: int,
    offline_at: datetime | None = None,
) -> int:
    """Record an offline sale with the same totals, stock and account rules as the register.

    It is booked to the cashier's open shift when there is one, and keeps the time
    it was rung up on the device. A sale the register endpoint already recorded under
    the same checkout ref (the till lost the reply and queued it) is not recorded again.
    """
    data = TransactionCreate.model_validate(
        {**payload, "status": None, "device_id": device_id, "client_ref": client_ref}
    )
    existing_id = await find_client_sale(db, device_id, client_ref)
    if existing_id:
        return existing_id
    shift = await open_shift_for(db, cashier_id)
    txn = await record_sale(
        db, data, cashier_id, shift.id if shift else None, offline=True, offline_at=offline_at
    )
    return txn.id


async def _process_expense(db: AsyncSession, payload: dict, user_id: int) -> int:
    """Record an offline expense through the same service the Expenses screen uses.

    strict=False: a drawer expense synced without an open shift is still saved,
    just not booked to a shift.
    """
    category_name = payload.get("category_name")
    category_id = None
    if category_name:
        res = await db.execute(
            select(ExpenseCategory).where(ExpenseCategory.name == category_name)
        )
        cat = res.scalar_one_or_none()
        if cat:
            category_id = cat.id
        else:
            new_cat = ExpenseCategory(name=category_name)
            db.add(new_cat)
            await db.flush()
            category_id = new_cat.id

    expense = await expense_service.record_expense(
        db,
        user_id=user_id,
        category_id=category_id,
        amount=Decimal(str(payload["amount"])),
        description=payload.get("description"),
        expense_date=date.fromisoformat(payload["expense_date"]) if payload.get("expense_date") else await shop_today(db),
        paid_from_drawer=bool(payload.get("paid_from_drawer", False)),
        strict=False,
    )
    await db.flush()
    return expense.id


async def _process_adjustment(db: AsyncSession, payload: dict, device_id: str, user_id: int) -> int:
    """Apply an offline stock adjustment to the server's quantity, with an audit trail.

    The device's qty_before is ignored: the adjustment is applied to the stock the
    server actually holds, so a late sync cannot overwrite sales made in between.
    """
    product_id = payload["product_id"]
    product = (await lock_products(db, {product_id}))[product_id]
    adjustment = Decimal(str(payload["adjustment"]))
    reason = (payload.get("reason") or "").strip() or "offline adjustment"

    before = product.stock_qty or Decimal("0")
    after = before + adjustment
    if after == before:
        raise ValueError("Adjustment does not change the stock quantity")

    entry = log_event(
        db, "stock_adjusted",
        f"Stock of {product.name} adjusted {before:g} → {after:g} ({adjustment:+g}), "
        f"synced from {device_id}. Reason: {reason}",
        user_id=user_id, shift_id=await active_shift_id(db, user_id), ref=product.sku,
        details={"product_id": product_id, "reason": reason, "offline": True, "device_id": device_id},
    )
    record_stock(entry, product, after)
    adj = StockAdjustment(
        product_id=product_id,
        qty_before=before,
        qty_after=after,
        adjustment=adjustment,
        reason=reason,
        adjusted_by_id=user_id,
    )
    db.add(adj)
    await db.flush()
    return adj.id


async def _process_purchase(
    db: AsyncSession, payload: dict, device_id: str, current_user_id: int
) -> int:
    """Post an offline purchase with the same WAC engine and audit trail as the Purchases screen."""
    supplier_id = payload.get("supplier_id")
    if supplier_id:
        res = await db.execute(select(Supplier).where(Supplier.id == supplier_id))
        if not res.scalar_one_or_none():
            raise ValueError(f"Supplier {supplier_id} not found")
    else:
        supplier_name = payload.get("supplier_name")
        if not supplier_name:
            raise ValueError("Purchase requires supplier_id or supplier_name")
        res = await db.execute(select(Supplier).where(Supplier.name == supplier_name))
        supplier = res.scalar_one_or_none()
        if not supplier:
            raise ValueError(f"Supplier '{supplier_name}' not found")
        supplier_id = supplier.id

    lines_data = payload.get("lines", [])
    if not lines_data:
        raise ValueError("Purchase must have at least one line")

    products = await lock_products(db, {ld["product_id"] for ld in lines_data})
    ref_number = await next_ref(db, "PO")
    total_amount = sum(
        (
            (Decimal(str(ld["qty"])) * Decimal(str(ld["unit_cost"]))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            for ld in lines_data
        ),
        Decimal("0"),
    )

    entry = purchase_entry(
        db, ref_number, total_amount, len(lines_data), current_user_id,
        await active_shift_id(db, current_user_id), note=f", synced from {device_id}",
    )
    po_lines: list[PurchaseOrderLine] = []
    details = []
    for ld in lines_data:
        product = products[ld["product_id"]]
        qty = Decimal(str(ld["qty"]))
        unit_cost = Decimal(str(ld["unit_cost"]))
        wac_before, wac_after = receive_into_stock(entry, product, qty, unit_cost)
        po_lines.append(PurchaseOrderLine(
            product_id=ld["product_id"],
            qty=qty,
            unit_cost=unit_cost,
            total_cost=(qty * unit_cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            wac_before=wac_before,
            wac_after=wac_after,
        ))
        details.append({
            "product_id": product.id, "name": product.name, "qty": qty, "unit_cost": unit_cost,
            "cost_before": wac_before, "cost_after": wac_after,
        })
    entry.details = log_details({"lines": details, "offline": True, "device_id": device_id})

    po = PurchaseOrder(
        supplier_id=supplier_id,
        ref_number=ref_number,
        status=PurchaseStatus.posted,
        total_amount=total_amount,
        created_by_id=current_user_id,
        posted_by_id=current_user_id,
        posted_at=datetime.now(timezone.utc),
        lines=po_lines,
    )
    db.add(po)
    await db.flush()
    return po.id
