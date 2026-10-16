from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, Numeric, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    credit_limit: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction", back_populates="customer", lazy="raise", passive_deletes="all"
    )
    payments: Mapped[list["CustomerPayment"]] = relationship(
        "CustomerPayment", back_populates="customer", lazy="raise", passive_deletes="all"
    )


class CustomerPayment(Base):
    __tablename__ = "customer_payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    method: Mapped[str] = mapped_column(String(10), nullable=False, default="cash", server_default="cash")  # cash | card
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id"), nullable=True, index=True)
    received_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    customer: Mapped["Customer"] = relationship("Customer", back_populates="payments", lazy="joined")
    received_by: Mapped["User"] = relationship("User", back_populates="customer_payments_received")
