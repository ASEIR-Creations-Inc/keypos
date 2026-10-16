from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.access import require_access
from database import get_db
from models import Supplier
from models.user import User
from schemas.purchases import SupplierCreate, SupplierUpdate, SupplierResponse

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


def _supplier_response(s: Supplier) -> SupplierResponse:
    return SupplierResponse(
        id=s.id,
        name=s.name,
        contact=s.contact,
        phone=s.phone,
        address=s.address,
        is_active=s.is_active,
    )


# ── GET /suppliers ──────────────────────────────────────────────

@router.get("", response_model=list[SupplierResponse], dependencies=[Depends(require_access("purchases", "read"))])
async def list_suppliers(
    active: bool | None = True,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Supplier)
    if active is True:
        stmt = stmt.where(Supplier.is_active == True)  # noqa: E712
    elif active is False:
        stmt = stmt.where(Supplier.is_active == False)  # noqa: E712
    stmt = stmt.order_by(Supplier.name)
    result = await db.execute(stmt)
    suppliers = result.scalars().all()
    return [_supplier_response(s) for s in suppliers]


# ── GET /suppliers/{id} ────────────────────────────────────────

@router.get("/{supplier_id}", response_model=SupplierResponse, dependencies=[Depends(require_access("purchases", "read"))])
async def get_supplier(supplier_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Supplier).where(Supplier.id == supplier_id))
    supplier = result.scalar_one_or_none()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return _supplier_response(supplier)


# ── POST /suppliers ────────────────────────────────────────────

@router.post("", response_model=SupplierResponse, status_code=status.HTTP_201_CREATED)
async def create_supplier(
    data: SupplierCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_access("purchases", "full")),
):
    dup = await db.execute(
        select(Supplier).where(
            Supplier.name == data.name,
            Supplier.is_active == True,  # noqa: E712
        )
    )
    if dup.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Supplier name already exists")

    supplier = Supplier(
        name=data.name,
        contact=data.contact,
        phone=data.phone,
        address=data.address,
    )
    db.add(supplier)
    await db.commit()
    await db.refresh(supplier)
    return _supplier_response(supplier)


# ── PUT /suppliers/{id} ────────────────────────────────────────

@router.put("/{supplier_id}", response_model=SupplierResponse)
async def update_supplier(
    supplier_id: int,
    data: SupplierUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_access("purchases", "full")),
):
    result = await db.execute(select(Supplier).where(Supplier.id == supplier_id))
    supplier = result.scalar_one_or_none()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")

    update_data = data.model_dump(exclude_unset=True)
    if "name" in update_data:
        dup = await db.execute(
            select(Supplier).where(
                Supplier.name == update_data["name"],
                Supplier.id != supplier_id,
                Supplier.is_active == True,  # noqa: E712
            )
        )
        if dup.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Supplier name already exists")

    for field, value in update_data.items():
        setattr(supplier, field, value)

    await db.commit()
    await db.refresh(supplier)
    return _supplier_response(supplier)


# ── DELETE /suppliers/{id}  (soft delete) ──────────────────────

@router.delete("/{supplier_id}", status_code=status.HTTP_200_OK)
async def delete_supplier(
    supplier_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_access("purchases", "full")),
):
    result = await db.execute(select(Supplier).where(Supplier.id == supplier_id))
    supplier = result.scalar_one_or_none()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    supplier.is_active = False
    await db.commit()
    await db.refresh(supplier)
    return {"message": "Supplier deactivated", "id": supplier.id}
