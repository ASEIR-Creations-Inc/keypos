from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.access import require_access
from database import get_db
from models.product import Product, Unit
from models.user import User
from schemas.products import UnitCreate, UnitResponse

router = APIRouter(prefix="/units", tags=["units"])


def _unit_response(unit: Unit) -> UnitResponse:
    return UnitResponse(id=unit.id, name=unit.name)


@router.get("", response_model=list[UnitResponse])
async def list_units(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Unit).order_by(Unit.name))
    return [_unit_response(u) for u in result.scalars().all()]


@router.post("", response_model=UnitResponse, status_code=status.HTTP_201_CREATED)
async def create_unit(
    data: UnitCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_access("inventory", "full")),
):
    # Check for duplicate
    existing = await db.execute(select(Unit).where(Unit.name == data.name))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Unit '{data.name}' already exists",
        )
    unit = Unit(name=data.name)
    db.add(unit)
    await db.flush()
    await db.commit()
    return _unit_response(unit)


@router.put("/{unit_id}", response_model=UnitResponse)
async def update_unit(
    unit_id: int,
    data: UnitCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_access("inventory", "full")),
):
    result = await db.execute(select(Unit).where(Unit.id == unit_id))
    unit = result.scalar_one_or_none()
    if not unit:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unit not found")
    # Check if the new name conflicts with another unit
    conflict = await db.execute(select(Unit).where(Unit.name == data.name, Unit.id != unit_id))
    if conflict.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Unit '{data.name}' already exists",
        )
    unit.name = data.name
    await db.commit()
    return _unit_response(unit)


@router.delete("/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_unit(
    unit_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_access("inventory", "full")),
):
    result = await db.execute(select(Unit).where(Unit.id == unit_id))
    unit = result.scalar_one_or_none()
    if not unit:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unit not found")
    await db.execute(update(Product).where(Product.unit_id == unit_id).values(unit_id=None))
    await db.delete(unit)
    await db.commit()
