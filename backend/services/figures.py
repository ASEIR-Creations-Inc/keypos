"""Sales totals shared by the Z-report, shift close and the sales reports.

Sales count on the day (and in the shift) they were rung up; refunds count on the
day and in the shift they were given. A refunded sale therefore still shows in
gross sales, and its refund is subtracted separately. Held sales, and the voids
left over from before voiding was removed, are left out entirely.
"""
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.customer import CustomerPayment
from models.expense import Expense
from models.transaction import Refund, Transaction, TransactionLine, TransactionStatus

ZERO = Decimal("0")
SOLD = (TransactionStatus.completed, TransactionStatus.refunded)


def _sum(column) -> ColumnElement:
    return func.coalesce(func.sum(column), ZERO)


@dataclass(frozen=True)
class SalesFigures:
    sale_count: int
    gross: Decimal
    discounts: Decimal
    tax: Decimal
    cash: Decimal
    card: Decimal
    account: Decimal
    refund_count: int
    refund_total: Decimal
    refund_tax: Decimal
    refund_cash: Decimal
    refund_card: Decimal
    refund_account: Decimal

    @property
    def net_sales(self) -> Decimal:
        """Sales after discounts and refunds, excluding tax."""
        return self.gross - self.discounts - (self.refund_total - self.refund_tax)

    @property
    def net_tax(self) -> Decimal:
        return self.tax - self.refund_tax

    @property
    def net_cash(self) -> Decimal:
        return self.cash - self.refund_cash

    @property
    def net_card(self) -> Decimal:
        return self.card - self.refund_card

    @property
    def net_account(self) -> Decimal:
        return self.account - self.refund_account


async def sales_figures(
    db: AsyncSession,
    sale_filters: list[ColumnElement[bool]],
    refund_filters: list[ColumnElement[bool]],
) -> SalesFigures:
    sales = (await db.execute(
        select(
            func.count(Transaction.id),
            _sum(Transaction.subtotal),
            _sum(Transaction.discount_amount),
            _sum(Transaction.tax_amount),
            _sum(Transaction.payment_cash - Transaction.change_given),
            _sum(Transaction.payment_card),
            _sum(Transaction.payment_account),
        ).where(Transaction.status.in_(SOLD), *sale_filters)
    )).one()
    refunds = (await db.execute(
        select(
            func.count(Refund.id),
            _sum(Refund.amount),
            _sum(Refund.tax_amount),
            _sum(Refund.refund_cash),
            _sum(Refund.refund_card),
            _sum(Refund.refund_account),
        ).where(*refund_filters)
    )).one()
    return SalesFigures(*sales, *refunds)


async def cost_of_goods(
    db: AsyncSession,
    sale_filters: list[ColumnElement[bool]],
    refund_filters: list[ColumnElement[bool]],
) -> Decimal:
    """Cost of everything sold, less the cost of goods that came back through refunds."""
    sold = (await db.execute(
        select(_sum(TransactionLine.qty * TransactionLine.cost_price))
        .join(Transaction, Transaction.id == TransactionLine.transaction_id)
        .where(Transaction.status.in_(SOLD), *sale_filters)
    )).scalar_one()
    returned = (await db.execute(select(_sum(Refund.cost_amount)).where(*refund_filters))).scalar_one()
    return sold - returned


@dataclass(frozen=True)
class DrawerFigures:
    """Money that moved through the till outside of sales: account payments in, expenses paid out."""
    payments_cash: Decimal
    payments_card: Decimal
    drawer_expenses: Decimal


async def drawer_figures(db: AsyncSession, shift_id: int) -> DrawerFigures:
    payments = (await db.execute(
        select(
            _sum(case((CustomerPayment.method == "cash", CustomerPayment.amount), else_=ZERO)),
            _sum(case((CustomerPayment.method == "card", CustomerPayment.amount), else_=ZERO)),
        ).where(CustomerPayment.shift_id == shift_id)
    )).one()
    expenses = (await db.execute(
        select(_sum(Expense.amount)).where(Expense.shift_id == shift_id, Expense.paid_from_drawer.is_(True))
    )).scalar_one()
    return DrawerFigures(payments[0], payments[1], expenses)
