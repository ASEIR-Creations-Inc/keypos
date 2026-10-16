from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.access import require_access
from database import get_db
from models import PurchaseOrder, PurchaseOrderLine, Supplier, Product, PurchaseStatus
from models.user import User
from schemas.purchases import PurchaseCreate, PurchaseLineCreate, PurchaseUpdate, PurchaseResponse
from models.audit import AuditLog
from services.audit import active_shift_id, log_details, log_event, record_stock
from services.sales import lock_products, next_ref

router = APIRouter(prefix="/purchases", tags=["purchases"])


def _calc_wac(current_stock: Decimal, current_cost: Decimal, incoming_qty: Decimal, incoming_cost: Decimal) -> Decimal:
    """Weighted Average Cost: ((stock * cost) + (qty * unit_cost)) / (stock + qty).

    With no stock on hand (or oversold, negative stock) every unit left after the
    delivery was bought at unit_cost, so that is the new cost.
    """
    if current_stock <= 0:
        return incoming_cost
    total_value = (current_stock * current_cost) + (incoming_qty * incoming_cost)
    total_qty = current_stock + incoming_qty
    return (total_value / total_qty).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def receive_into_stock(entry: AuditLog, product: Product, qty: Decimal, unit_cost: Decimal) -> tuple[Decimal, Decimal]:
    """Add received goods to stock at weighted average cost; returns (cost before, cost after)."""
    wac_before = product.cost_price
    wac_after = _calc_wac(product.stock_qty, product.cost_price, qty, unit_cost)
    record_stock(entry, product, product.stock_qty + qty)
    product.cost_price = wac_after
    return wac_before, wac_after


def purchase_entry(
    db: AsyncSession, ref: str, total: Decimal, line_count: int, user_id: int, shift_id: int | None, note: str = ""
) -> AuditLog:
    """Audit entry for received goods; the caller fills details once the cost changes are known."""
    return log_event(
        db, "purchase_posted", f"Purchase {ref} received: {line_count} lines, {total:.2f}{note}",
        user_id=user_id, shift_id=shift_id, ref=ref, amount=total,
    )


def _response_from_po(po: PurchaseOrder) -> PurchaseResponse:
    lines = []
    for line in po.lines:
        product_name = line.product.name if line.product else "Unknown"
        lines.append({
            "id": line.id,
            "product_id": line.product_id,
            "product_name": product_name,
            "qty": line.qty,
            "unit_cost": line.unit_cost,
            "total_cost": line.total_cost,
            "wac_before": line.wac_before,
            "wac_after": line.wac_after,
        })
    return PurchaseResponse(
        id=po.id,
        supplier_id=po.supplier_id,
        supplier_name=po.supplier.name if po.supplier else "Unknown",
        ref_number=po.ref_number,
        status=po.status.value if isinstance(po.status, PurchaseStatus) else po.status,
        total_amount=po.total_amount,
        created_by_id=po.created_by_id,
        posted_by_id=po.posted_by_id,
        created_at=po.created_at.isoformat() if po.created_at else None,
        posted_at=po.posted_at.isoformat() if po.posted_at else None,
        lines=lines,
    )


async def _validate_supplier(db: AsyncSession, supplier_id: int | None) -> None:
    if supplier_id is None:
        return
    sup_result = await db.execute(select(Supplier).where(Supplier.id == supplier_id, Supplier.is_active == True))  # noqa: E712
    if not sup_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Supplier not found or inactive")



async def _load_po(db: AsyncSession, purchase_id: int) -> PurchaseOrder:
    """The order with its lines and their products, re-read from the database (404 if missing)."""
    po = (await db.execute(
        select(PurchaseOrder)
        .options(selectinload(PurchaseOrder.lines).joinedload(PurchaseOrderLine.product))
        .where(PurchaseOrder.id == purchase_id)
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return po

async def _draft_lines(
    db: AsyncSession, lines: list[PurchaseLineCreate]
) -> tuple[list[PurchaseOrderLine], Decimal]:
    """Draft order lines and their total; WAC fields are filled in when the order is posted.

    The products are loaded (one query) so the response can name them without lazy loads.
    """
    ids = {l.product_id for l in lines}
    products = {p.id: p for p in (await db.execute(select(Product).where(Product.id.in_(ids)))).scalars()}
    missing = sorted(ids - products.keys())
    if missing:
        raise HTTPException(status_code=404, detail=f"Product {missing[0]} not found")
    drafts = [
        PurchaseOrderLine(
            product=products[l.product_id],
            qty=l.qty,
            unit_cost=l.unit_cost,
            total_cost=(l.qty * l.unit_cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            wac_before=Decimal("0"),
            wac_after=Decimal("0"),
        )
        for l in lines
    ]
    return drafts, sum((d.total_cost for d in drafts), Decimal("0"))

# ── GET /purchases ─────────────────────────────────────────────

@router.get("", response_model=list[PurchaseResponse], dependencies=[Depends(require_access("purchases", "read"))])
async def list_purchases(
    status_filter: str | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(PurchaseOrder)
        .options(selectinload(PurchaseOrder.lines).joinedload(PurchaseOrderLine.product))
        .order_by(PurchaseOrder.created_at.desc())
    )
    if status_filter is not None:
        try:
            status_enum = PurchaseStatus(status_filter)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status_filter}")
        stmt = stmt.where(PurchaseOrder.status == status_enum)
    result = await db.execute(stmt)
    orders = result.scalars().unique().all()
    return [_response_from_po(po) for po in orders]


# ── GET /purchases/{id} ────────────────────────────────────────

@router.get("/{purchase_id}", response_model=PurchaseResponse, dependencies=[Depends(require_access("purchases", "read"))])
async def get_purchase(purchase_id: int, db: AsyncSession = Depends(get_db)):
    po = await _load_po(db, purchase_id)
    return _response_from_po(po)


# ── POST /purchases  (create draft) ────────────────────────────

@router.post("", response_model=PurchaseResponse, status_code=status.HTTP_201_CREATED)
async def create_purchase(
    data: PurchaseCreate,
    user: User = Depends(require_access("purchases", "full")),
    db: AsyncSession = Depends(get_db),
):
    await _validate_supplier(db, data.supplier_id)

    ref_number = await next_ref(db, "PO")

    # Validate products and build lines
    purchase = PurchaseOrder(
        supplier_id=data.supplier_id,
        ref_number=ref_number,
        status=PurchaseStatus.draft,
        created_by_id=1,
    )
    purchase.lines, purchase.total_amount = await _draft_lines(db, data.lines)
    db.add(purchase)
    await db.commit()
    return _response_from_po(await _load_po(db, purchase.id))


# ── PUT /purchases/{id}  (edit draft only) ────────────────────

@router.put("/{purchase_id}", response_model=PurchaseResponse)
async def update_purchase(
    purchase_id: int,
    data: PurchaseUpdate,
    user: User = Depends(require_access("purchases", "full")),
    db: AsyncSession = Depends(get_db),
):
    po = await _load_po(db, purchase_id)
    if po.status != PurchaseStatus.draft:
        raise HTTPException(status_code=400, detail="Cannot edit a posted purchase order")
    await _validate_supplier(db, data.supplier_id)
    po.supplier_id = data.supplier_id

    # Delete existing lines
    for line in po.lines:
        await db.delete(line)

    lines, po.total_amount = await _draft_lines(db, data.lines)
    for line in lines:
        line.purchase_order_id = po.id
        db.add(line)
    await db.commit()
    return _response_from_po(await _load_po(db, po.id))


# ── POST /purchases/{id}/post  (WAC engine) ───────────────────

@router.post("/{purchase_id}/post", response_model=PurchaseResponse)
async def post_purchase(
    purchase_id: int,
    user: User = Depends(require_access("purchases", "full")),
    db: AsyncSession = Depends(get_db),
):
    po = await _load_po(db, purchase_id)
    if po.status != PurchaseStatus.draft:
        raise HTTPException(status_code=400, detail="Purchase order is already posted")

    products = await lock_products(db, {line.product_id for line in po.lines})
    shift_id = await active_shift_id(db, user.id)
    entry = purchase_entry(db, po.ref_number, po.total_amount, len(po.lines), user.id, shift_id)
    details = []
    for line in po.lines:
        product = products[line.product_id]
        line.wac_before, line.wac_after = receive_into_stock(entry, product, line.qty, line.unit_cost)
        details.append({
            "product_id": product.id, "name": product.name, "qty": line.qty, "unit_cost": line.unit_cost,
            "cost_before": line.wac_before, "cost_after": line.wac_after,
        })
    entry.details = log_details({"lines": details})

    # Transition status
    po.status = PurchaseStatus.posted
    po.posted_by_id = user.id
    po.posted_at = datetime.now(timezone.utc)

    await db.commit()
    return _response_from_po(await _load_po(db, po.id))


# ── DELETE /purchases/{id}  (draft only) ──────────────────────

@router.delete("/{purchase_id}", status_code=status.HTTP_200_OK)
async def delete_purchase(
    purchase_id: int,
    user: User = Depends(require_access("purchases", "full")),
    db: AsyncSession = Depends(get_db),
):
    po = await _load_po(db, purchase_id)
    if po.status != PurchaseStatus.draft:
        raise HTTPException(status_code=400, detail="Cannot delete a posted purchase order")

    # Delete lines first (cascade should handle, but be explicit)
    for line in po.lines:
        await db.delete(line)
    await db.delete(po)
    await db.commit()
    return {"message": "Purchase order deleted", "id": purchase_id}
