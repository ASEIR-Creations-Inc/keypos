from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.access import require_access
from database import get_db
from models.product import Category, Product
from models.user import User
from schemas.products import CategoryCreate, CategoryResponse, CategoryUpdate

router = APIRouter(prefix="/categories", tags=["categories"])


def _cat_response(cat: Category) -> CategoryResponse:
    return CategoryResponse(
        id=cat.id, name=cat.name, color=cat.color, sort_order=cat.sort_order
    )


@router.get("", response_model=list[CategoryResponse])
async def list_categories(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Category).order_by(Category.sort_order, Category.name))
    return [_cat_response(c) for c in result.scalars().all()]


@router.post("", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    data: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_access("inventory", "full")),
):
    cat = Category(name=data.name, color=data.color, sort_order=data.sort_order)
    db.add(cat)
    await db.flush()
    await db.commit()
    return _cat_response(cat)


@router.put("/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: int,
    data: CategoryUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_access("inventory", "full")),
):
    result = await db.execute(select(Category).where(Category.id == category_id))
    cat = result.scalar_one_or_none()
    if not cat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(cat, field, value)
    await db.commit()
    await db.refresh(cat)
    return _cat_response(cat)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_access("inventory", "full")),
):
    result = await db.execute(select(Category).where(Category.id == category_id))
    cat = result.scalar_one_or_none()
    if not cat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    await db.execute(update(Product).where(Product.category_id == category_id).values(category_id=None))
    await db.delete(cat)
    await db.commit()
