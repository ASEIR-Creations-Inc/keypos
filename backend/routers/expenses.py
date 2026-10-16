from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.access import forbidden, is_admin, require_access, sees_everyone
from models.user import User
from database import get_db
from models import Expense, ExpenseCategory
from schemas.expenses import (
    ExpenseCategoryCreate,
    ExpenseCategoryResponse,
    ExpenseCreate,
    ExpenseListResponse,
    ExpenseResponse,
)
from services import expenses as service

router = APIRouter(prefix="/expenses", tags=["expenses"])


def _expense_response(e: Expense) -> ExpenseResponse:
    return ExpenseResponse(
        id=e.id,
        category_id=e.category_id,
        amount=e.amount,
        description=e.description,
        expense_date=e.expense_date,
        paid_from_drawer=e.paid_from_drawer,
        shift_id=e.shift_id,
        entered_by_id=e.entered_by_id,
        created_at=e.created_at,
        category_name=e.category.name if e.category else None,
        day_sheet_id=e.day_sheet_id,
    )


async def _validate_category(db: AsyncSession, category_id: int | None) -> None:
    if category_id is None:
        return
    result = await db.execute(select(ExpenseCategory).where(ExpenseCategory.id == category_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Expense category not found")


def _check_owner(user: User, expense: Expense) -> None:
    """Staff with "own" expense access can only see and change the expenses they entered."""
    if expense.entered_by_id != user.id and not sees_everyone(user, "expenses"):
        raise forbidden("You can only work with expenses you entered")


def _check_sheet_expense(user: User, expense: Expense) -> None:
    """Expenses that came in on an uploaded day sheet are changed or deleted only by an admin."""
    if expense.day_sheet_id and not is_admin(user):
        raise forbidden("This expense came from a day sheet; only an admin can change or delete it")


async def _load_expense(db: AsyncSession, expense_id: int) -> Expense:
    result = await db.execute(
        select(Expense).options(selectinload(Expense.category)).where(Expense.id == expense_id)
    )
    expense = result.scalar_one_or_none()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    return expense


# ── GET /expenses ─────────────────────────────────────────────

@router.get("", response_model=ExpenseListResponse)
async def list_expenses(
    from_date: date | None = None,
    to_date: date | None = None,
    category_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_access("expenses", "own")),
):
    stmt = (
        select(Expense)
        .options(selectinload(Expense.category))
        .order_by(Expense.expense_date.desc())
    )
    if from_date is not None:
        stmt = stmt.where(Expense.expense_date >= from_date)
    if to_date is not None:
        stmt = stmt.where(Expense.expense_date <= to_date)
    if category_id is not None:
        stmt = stmt.where(Expense.category_id == category_id)
    if not sees_everyone(user, "expenses"):
        stmt = stmt.where(Expense.entered_by_id == user.id)

    expenses = (await db.execute(stmt)).scalars().all()
    period_total = sum((e.amount for e in expenses), Decimal("0"))
    return ExpenseListResponse(items=[_expense_response(e) for e in expenses], period_total=period_total)


# ── POST /expenses ────────────────────────────────────────────

@router.post("", response_model=ExpenseResponse, status_code=status.HTTP_201_CREATED)
async def create_expense(
    data: ExpenseCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_access("expenses", "own")),
):
    await _validate_category(db, data.category_id)
    expense = await service.record_expense(
        db,
        user_id=user.id,
        category_id=data.category_id,
        amount=data.amount,
        description=data.description,
        expense_date=data.expense_date,
        paid_from_drawer=data.paid_from_drawer,
    )
    await db.commit()
    return _expense_response(await _load_expense(db, expense.id))


# ── GET /expenses/categories ──────────────────────────────────

@router.get("/categories", response_model=list[ExpenseCategoryResponse])
async def list_expense_categories(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ExpenseCategory).order_by(ExpenseCategory.name))
    return [
        ExpenseCategoryResponse(id=c.id, name=c.name)
        for c in result.scalars().all()
    ]


# ── POST /expenses/categories ─────────────────────────────────

@router.post("/categories", response_model=ExpenseCategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_expense_category(
    data: ExpenseCategoryCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_access("expenses", "full")),
):
    dup = await db.execute(select(ExpenseCategory).where(ExpenseCategory.name == data.name))
    if dup.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Category name already exists")

    category = ExpenseCategory(name=data.name)
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return ExpenseCategoryResponse(id=category.id, name=category.name)


# ── GET /expenses/{expense_id} ────────────────────────────────

@router.get("/{expense_id}", response_model=ExpenseResponse)
async def get_expense(
    expense_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_access("expenses", "own")),
):
    expense = await _load_expense(db, expense_id)
    _check_owner(user, expense)
    return _expense_response(expense)


# ── PUT /expenses/{expense_id} ────────────────────────────────

@router.put("/{expense_id}", response_model=ExpenseResponse)
async def update_expense(
    expense_id: int,
    data: ExpenseCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_access("expenses", "own")),
):
    expense = await _load_expense(db, expense_id)
    _check_owner(user, expense)
    _check_sheet_expense(user, expense)
    await _validate_category(db, data.category_id)
    await service.update_expense(
        db,
        expense,
        user_id=user.id,
        category_id=data.category_id,
        amount=data.amount,
        description=data.description,
        expense_date=data.expense_date,
        paid_from_drawer=data.paid_from_drawer,
    )
    await db.commit()
    return _expense_response(await _load_expense(db, expense_id))


# ── DELETE /expenses/{expense_id} ─────────────────────────────

@router.delete("/{expense_id}", status_code=status.HTTP_200_OK)
async def delete_expense(
    expense_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_access("expenses", "own")),
):
    expense = await _load_expense(db, expense_id)
    _check_owner(user, expense)
    _check_sheet_expense(user, expense)
    await service.delete_expense(db, expense, user.id)
    await db.commit()
    return {"message": "Expense deleted", "id": expense_id}
