from decimal import Decimal
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.access import require_access
from database import get_db
from models import Customer, CustomerPayment, Refund, Transaction, TransactionStatus
from models.user import User
from services.audit import active_shift_id, log_event
from services.sales import credit_account
from schemas.customers import (
    CustomerCreate,
    CustomerLedger,
    CustomerResponse,
    LedgerEntry,
    PaymentCreate,
    PaymentResponse,
)

router = APIRouter(prefix="/customers", tags=["customers"])


def _customer_response(c: Customer) -> CustomerResponse:
    return CustomerResponse(
        id=c.id,
        name=c.name,
        phone=c.phone,
        email=c.email,
        credit_limit=c.credit_limit,
        balance=c.balance,
        created_at=c.created_at,
    )


# ── GET /customers ────────────────────────────────────────────

@router.get("", response_model=list[CustomerResponse], dependencies=[Depends(require_access("customers", "read"))])
async def list_customers(
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Customer).order_by(Customer.name)
    if search:
        stmt = stmt.where(Customer.name.ilike(f"%{search}%"))
    result = await db.execute(stmt)
    customers = result.scalars().all()
    return [_customer_response(c) for c in customers]


# ── POST /customers ───────────────────────────────────────────

@router.post("", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def create_customer(
    data: CustomerCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_access("customers", "full")),
):
    customer = Customer(
        name=data.name,
        phone=data.phone,
        email=data.email,
        credit_limit=data.credit_limit,
    )
    db.add(customer)
    await db.commit()
    await db.refresh(customer)
    return _customer_response(customer)


# ── GET /customers/{id} ───────────────────────────────────────

@router.get("/{customer_id}", response_model=CustomerResponse, dependencies=[Depends(require_access("customers", "read"))])
async def get_customer(customer_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return _customer_response(customer)


# ── PUT /customers/{id} ───────────────────────────────────────

@router.put("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: int,
    data: CustomerCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_access("customers", "full")),
):
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    customer.name = data.name
    customer.phone = data.phone
    customer.email = data.email
    customer.credit_limit = data.credit_limit

    await db.commit()
    await db.refresh(customer)
    return _customer_response(customer)


# ── GET /customers/{id}/ledger ────────────────────────────────

@router.get("/{customer_id}/ledger", response_model=CustomerLedger, dependencies=[Depends(require_access("customers", "read"))])
async def get_customer_ledger(customer_id: int, db: AsyncSession = Depends(get_db)):
    """Account history: sales put on account, refunds back to the account, and payments.

    Running balances are worked back from the stored balance, so the newest entry always
    matches it. Any difference older history cannot explain shows as an opening balance.
    """
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    sales = (await db.execute(
        select(Transaction.created_at, Transaction.ref_number, Transaction.payment_account)
        .where(
            Transaction.customer_id == customer_id,
            Transaction.status.in_([TransactionStatus.completed, TransactionStatus.refunded]),
            Transaction.payment_account > 0,
        )
    )).all()
    refunds = (await db.execute(
        select(Refund.created_at, Transaction.ref_number, Refund.refund_account)
        .join(Transaction, Transaction.id == Refund.transaction_id)
        .where(Transaction.customer_id == customer_id, Refund.refund_account > 0)
    )).all()
    payments = (await db.execute(
        select(CustomerPayment).where(CustomerPayment.customer_id == customer_id)
    )).scalars().all()

    # (date, type, ref, amount, effect on balance)
    moves = [(d, "sale", ref, amt, amt) for d, ref, amt in sales]
    moves += [(d, "refund", ref, amt, -amt) for d, ref, amt in refunds]
    moves += [(p.created_at, "payment", p.reference or f"PAY-{p.id}", p.amount, -p.amount) for p in payments]
    moves.sort(key=lambda m: m[0])

    running = customer.balance - sum((m[4] for m in moves), Decimal("0"))
    entries: list[LedgerEntry] = []
    if running != 0:
        opening_date = moves[0][0] if moves else customer.created_at
        entries.append(LedgerEntry(
            date=opening_date, type="opening", ref="Opening balance", amount=running, balance_after=running,
        ))
    for date, kind, ref, amount, effect in moves:
        running += effect
        entries.append(LedgerEntry(date=date, type=kind, ref=ref, amount=amount, balance_after=running))

    entries.reverse()
    return CustomerLedger(customer=_customer_response(customer), entries=entries)


# ── POST /customers/{id}/payment ──────────────────────────────

@router.post("/{customer_id}/payment", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
async def make_payment(
    customer_id: int,
    data: PaymentCreate,
    user: User = Depends(require_access("customers", "full")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    customer = await credit_account(db, customer_id, data.amount)

    cash = data.amount if data.method == "cash" else Decimal("0")
    card = data.amount if data.method == "card" else Decimal("0")
    shift_id = await active_shift_id(db, user.id)
    payment = CustomerPayment(
        customer_id=customer_id,
        amount=data.amount,
        reference=data.reference,
        method=data.method,
        shift_id=shift_id,
        received_by_id=user.id,
    )
    db.add(payment)
    await db.flush()
    log_event(
        db, "payment_received",
        f"Payment {data.amount:.2f} ({data.method}) from {customer.name}"
        + (f", ref {data.reference}" if data.reference else ""),
        user_id=user.id, shift_id=shift_id, ref=data.reference or f"PAY-{payment.id}",
        amount=data.amount, cash=cash, card=card,
        details={"customer_id": customer_id, "balance_after": customer.balance},
    )
    await db.commit()
    await db.refresh(payment)

    return PaymentResponse(
        id=payment.id,
        customer_id=payment.customer_id,
        amount=payment.amount,
        reference=payment.reference,
        method=payment.method,
        shift_id=payment.shift_id,
        received_by_id=payment.received_by_id,
        created_at=payment.created_at,
    )

@router.delete("/{customer_id}", status_code=204, dependencies=[Depends(require_access("customers", "full"))])
async def delete_customer(customer_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    has_history = (await db.execute(select(
        exists().where(Transaction.customer_id == customer_id)
        | exists().where(CustomerPayment.customer_id == customer_id)
    ))).scalar()
    if has_history or customer.balance:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This customer has sales, payments or a balance and cannot be deleted",
        )
    await db.delete(customer)
    await db.commit()
