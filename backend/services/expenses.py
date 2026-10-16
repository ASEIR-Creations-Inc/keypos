"""Expenses, including cash paid out of the till during a shift.

An expense paid from the drawer is booked to the open shift and lowers the cash the
shift is expected to hand in. Once that shift is closed the expense can no longer be
changed or deleted, so the printed Z-report stays true.
"""
from datetime import date
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from models.expense import Expense
from models.shift import Shift, ShiftStatus
from services.audit import active_shift_id, log_event

ZERO = Decimal("0")


def _describe(expense: Expense) -> str:
    where = " from the drawer" if expense.paid_from_drawer else ""
    text = f"{expense.amount:.2f}{where}"
    return f"{text} ({expense.description})" if expense.description else text


def _snapshot(expense: Expense) -> dict:
    return {
        "expense_id": expense.id,
        "category_id": expense.category_id,
        "amount": expense.amount,
        "description": expense.description,
        "expense_date": expense.expense_date,
        "paid_from_drawer": expense.paid_from_drawer,
    }


def _drawer_cash(expense: Expense) -> Decimal:
    return -expense.amount if expense.paid_from_drawer else ZERO


async def _drawer_shift(db: AsyncSession, user_id: int, paid_from_drawer: bool, strict: bool) -> int | None:
    if not paid_from_drawer:
        return None
    shift_id = await active_shift_id(db, user_id)
    if shift_id is None and strict:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Open a shift before paying an expense out of the drawer",
        )
    return shift_id


async def _require_editable(db: AsyncSession, expense: Expense) -> None:
    if not expense.shift_id:
        return
    shift = await db.get(Shift, expense.shift_id)
    if shift and shift.status == ShiftStatus.closed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This expense was paid from the drawer in a closed shift and can no longer be changed",
        )


async def record_expense(
    db: AsyncSession,
    *,
    user_id: int,
    category_id: int | None,
    amount: Decimal,
    description: str | None,
    expense_date: date,
    paid_from_drawer: bool,
    strict: bool = True,
) -> Expense:
    """strict=False (offline sync) books a drawer expense without a shift when none is open."""
    shift_id = await _drawer_shift(db, user_id, paid_from_drawer, strict)
    expense = Expense(
        category_id=category_id,
        amount=amount,
        description=description,
        expense_date=expense_date,
        paid_from_drawer=paid_from_drawer and shift_id is not None,
        shift_id=shift_id,
        entered_by_id=user_id,
    )
    db.add(expense)
    await db.flush()
    log_event(
        db, "expense_added", f"Expense #{expense.id}: {_describe(expense)}",
        user_id=user_id, shift_id=shift_id or await active_shift_id(db, user_id), ref=f"EXP-{expense.id}",
        amount=amount, cash=_drawer_cash(expense), details=_snapshot(expense),
    )
    return expense


async def update_expense(
    db: AsyncSession,
    expense: Expense,
    *,
    user_id: int,
    category_id: int | None,
    amount: Decimal,
    description: str | None,
    expense_date: date,
    paid_from_drawer: bool,
) -> Expense:
    """A drawer expense stays in the shift it was paid in; the audit entry records the cash difference."""
    await _require_editable(db, expense)
    before = _snapshot(expense)
    before_cash = _drawer_cash(expense)
    if paid_from_drawer and not expense.shift_id:
        expense.shift_id = await _drawer_shift(db, user_id, True, strict=True)
    if not paid_from_drawer:
        expense.shift_id = None

    expense.category_id = category_id
    expense.amount = amount
    expense.description = description
    expense.expense_date = expense_date
    expense.paid_from_drawer = paid_from_drawer

    log_event(
        db, "expense_edited", f"Expense #{expense.id} changed to {_describe(expense)}",
        user_id=user_id, shift_id=expense.shift_id or await active_shift_id(db, user_id), ref=f"EXP-{expense.id}",
        amount=amount, cash=_drawer_cash(expense) - before_cash,
        details={"before": before, "after": _snapshot(expense)},
    )
    return expense


async def delete_expense(db: AsyncSession, expense: Expense, user_id: int) -> None:
    await _require_editable(db, expense)
    log_event(
        db, "expense_deleted", f"Expense #{expense.id} deleted: {_describe(expense)}",
        user_id=user_id, shift_id=expense.shift_id or await active_shift_id(db, user_id), ref=f"EXP-{expense.id}",
        amount=-expense.amount, cash=-_drawer_cash(expense), details=_snapshot(expense),
    )
    await db.delete(expense)
