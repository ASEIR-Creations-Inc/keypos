from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.access import require_access
from database import get_db
from models.product import Category, Product, Unit
from models.sync import StockAdjustment
from models.user import User
from schemas.products import (
    ProductCreate,
    ProductResponse,
    ProductUpdate,
    StockAdjustRequest,
)
from services.audit import active_shift_id, changed_fields, log_event, record_stock

router = APIRouter(prefix="/products", tags=["products"])


def _product_response(p: Product) -> ProductResponse:
    return ProductResponse(
        id=p.id,
        sku=p.sku,
        barcode=p.barcode,
        name=p.name,
        category_id=p.category_id,
        category_name=p.category.name if p.category else None,
        unit_id=p.unit_id,
        unit_name=p.unit.name if p.unit else None,
        sell_price=p.sell_price,
        cost_price=p.cost_price,
        stock_qty=p.stock_qty,
        low_stock_threshold=p.low_stock_threshold,
        is_active=p.is_active,
        image_url=p.image_url,
        created_at=p.created_at.isoformat() if p.created_at else None,
    )


def _auto_sku(existing_skus: set[str]) -> str:
    """Generate next PRD-XXXXX SKU that doesn't conflict."""
    for i in range(1, 999_999):
        candidate = f"PRD-{i:05d}"
        if candidate not in existing_skus:
            return candidate
    raise HTTPException(status_code=500, detail="SKU namespace exhausted")


# ── GET /products ──────────────────────────────────────────────

@router.get("", response_model=list[ProductResponse])
async def list_products(
    search: Optional[str] = Query(None, max_length=255),
    category_id: Optional[int] = Query(None),
    low_stock: Optional[bool] = Query(None),
    is_active: Optional[bool] = Query(True),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Product).options(selectinload(Product.category), selectinload(Product.unit))

    filters = []
    if is_active is True:
        filters.append(Product.is_active == True)  # noqa: E712

    if search:
        like = f"%{search}%"
        filters.append(
            Product.name.ilike(like)
            | Product.sku.ilike(like)
            | (Product.barcode.ilike(like) if Product.barcode is not None else False)
        )

    if category_id is not None:
        filters.append(Product.category_id == category_id)

    if low_stock:
        filters.append(Product.stock_qty <= Product.low_stock_threshold)

    if filters:
        stmt = stmt.where(*filters)

    stmt = stmt.order_by(Product.category_id, Product.name)
    result = await db.execute(stmt)
    products = result.scalars().unique().all()
    return [_product_response(p) for p in products]


# ── GET /products/barcode/{barcode} ────────────────────────────

@router.get("/barcode/{barcode}", response_model=ProductResponse)
async def get_product_by_barcode(barcode: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Product).options(selectinload(Product.category), selectinload(Product.unit)).where(Product.barcode == barcode, Product.is_active == True)  # noqa: E712
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return _product_response(product)


# ── GET /products/{id} ─────────────────────────────────────────

@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(product_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Product).options(selectinload(Product.category), selectinload(Product.unit)).where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if not product or not product.is_active:
        raise HTTPException(status_code=404, detail="Product not found")
    return _product_response(product)


# ── POST /products ─────────────────────────────────────────────

@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    data: ProductCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_access("inventory", "full")),
):
    # Auto-generate SKU if not provided
    if not data.sku:
        skus_result = await db.execute(select(Product.sku))
        existing = {row[0] for row in skus_result.all()}
        data.sku = _auto_sku(existing)

    product = Product(
        sku=data.sku,
        barcode=data.barcode,
        name=data.name,
        category_id=data.category_id,
        unit_id=data.unit_id,
        sell_price=data.sell_price,
        cost_price=data.cost_price,
        stock_qty=Decimal("0"),
        low_stock_threshold=data.low_stock_threshold,
        image_url=data.image_url,
    )
    db.add(product)
    await db.flush()
    entry = log_event(
        db, "product_created",
        f"Product {product.name} ({product.sku}) created, stock {data.stock_qty:g}, cost {data.cost_price:.2f}",
        user_id=user.id, shift_id=await active_shift_id(db, user.id), ref=product.sku,
        details={"product_id": product.id, "sell_price": data.sell_price, "cost_price": data.cost_price},
    )
    record_stock(entry, product, data.stock_qty)
    await db.commit()
    return await _reload(db, product.id)


# ── PUT /products/{id} ─────────────────────────────────────────

@router.put("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: int,
    data: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_access("inventory", "full")),
):
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    changes = changed_fields(product, data.model_dump(exclude_unset=True))
    for field, change in changes.items():
        setattr(product, field, change["to"])

    if changes:
        log_event(
            db, "product_edited",
            f"Product {product.name} ({product.sku}) edited: "
            + ", ".join(f"{f} {c['from']} → {c['to']}" for f, c in changes.items()),
            user_id=user.id, shift_id=await active_shift_id(db, user.id), ref=product.sku,
            details={"product_id": product.id, "changes": changes},
        )

    await db.commit()
    return await _reload(db, product.id)


# ── POST /products/{id}/adjust-stock ───────────────────────────

@router.post("/{product_id}/adjust-stock", response_model=ProductResponse)
async def adjust_stock(
    product_id: int,
    data: StockAdjustRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_access("inventory", "full")),
):
    """Count correction, damage, theft and so on. Either a change (+/-) or the counted quantity."""
    product = (await db.execute(
        select(Product).where(Product.id == product_id).with_for_update()
    )).scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    before = product.stock_qty or Decimal("0")
    after = data.counted_qty if data.counted_qty is not None else before + data.change
    if after == before:
        raise HTTPException(status_code=400, detail="Stock is already at that quantity")

    reason = data.reason.strip()
    entry = log_event(
        db, "stock_adjusted",
        f"Stock of {product.name} adjusted {before:g} → {after:g} ({after - before:+g}). Reason: {reason}",
        user_id=user.id, shift_id=await active_shift_id(db, user.id), ref=product.sku,
        details={"product_id": product.id, "reason": reason},
    )
    record_stock(entry, product, after)
    db.add(StockAdjustment(
        product_id=product.id, qty_before=before, qty_after=after, adjustment=after - before,
        reason=reason, adjusted_by_id=user.id,
    ))
    await db.commit()
    return await _reload(db, product.id)


# ── DELETE /products/{id}  (soft delete) ───────────────────────

@router.delete("/{product_id}", status_code=status.HTTP_200_OK)
async def delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_access("inventory", "full")),
):
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.is_active:
        product.is_active = False
        log_event(
            db, "product_deactivated",
            f"Product {product.name} ({product.sku}) deactivated with {product.stock_qty:g} in stock",
            user_id=user.id, shift_id=await active_shift_id(db, user.id), ref=product.sku,
            details={"product_id": product.id, "stock_qty": product.stock_qty},
        )
    await db.commit()
    return {"message": "Product deactivated", "id": product_id}


async def _reload(db: AsyncSession, product_id: int) -> ProductResponse:
    db.expire_all()
    result = await db.execute(
        select(Product)
        .options(selectinload(Product.category), selectinload(Product.unit))
        .where(Product.id == product_id)
    )
    return _product_response(result.scalar_one())