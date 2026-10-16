import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, Text, Numeric, DateTime, ForeignKey, Boolean, Enum, Index, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class TransactionStatus(str, enum.Enum):
    completed = "completed"
    held = "held"
    voided = "voided"
    refunded = "refunded"


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index(
            "uq_transactions_device_client_ref", "device_id", "client_ref", unique=True,
            postgresql_where=text("client_ref IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ref_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)  # TXN-YYYYMMDD-XXXX
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id"), nullable=True)
    cashier_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    status: Mapped[TransactionStatus] = mapped_column(
        Enum(TransactionStatus), nullable=False, default=TransactionStatus.held
    )
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    payment_cash: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    payment_card: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    payment_account: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"), server_default="0")
    change_given: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    refunded_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"), server_default="0")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reissue_of_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), nullable=True, index=True)
    is_offline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    device_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    client_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    shift: Mapped["Shift"] = relationship("Shift", back_populates="transactions")
    customer: Mapped["Customer | None"] = relationship("Customer", back_populates="transactions")
    cashier: Mapped["User"] = relationship("User", back_populates="transactions_cashiered")
    lines: Mapped[list["TransactionLine"]] = relationship(
        "TransactionLine", back_populates="transaction", cascade="all, delete-orphan", lazy="selectin"
    )
    price_edit_logs: Mapped[list["PriceEditLog"]] = relationship(
        "PriceEditLog", back_populates="transaction", cascade="all, delete-orphan", lazy="selectin"
    )
    refunds: Mapped[list["Refund"]] = relationship(
        "Refund", back_populates="transaction", order_by="Refund.id"
    )
    reissue_of: Mapped["Transaction | None"] = relationship(
        "Transaction", remote_side="Transaction.id", foreign_keys=[reissue_of_id], lazy="select"
    )


class TransactionLine(Base):
    __tablename__ = "transaction_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    original_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)  # catalog price
    sell_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)  # actual charged
    cost_price: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)  # WAC at time of sale
    discount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    line_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    refunded_qty: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False, default=Decimal("0"), server_default="0")

    transaction: Mapped["Transaction"] = relationship("Transaction", back_populates="lines", lazy="joined")
    product: Mapped["Product"] = relationship("Product", back_populates="transaction_lines")
    price_edit_logs: Mapped[list["PriceEditLog"]] = relationship(
        "PriceEditLog", back_populates="transaction_line", lazy="selectin"
    )


class PriceEditLog(Base):
    __tablename__ = "price_edit_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    transaction_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("transaction_lines.id"), nullable=True
    )
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    edited_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    original_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    new_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    difference: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    permission_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    edited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    transaction: Mapped["Transaction"] = relationship("Transaction", back_populates="price_edit_logs", lazy="joined")
    transaction_line: Mapped["TransactionLine | None"] = relationship(
        "TransactionLine", back_populates="price_edit_logs", lazy="joined"
    )
    product: Mapped["Product"] = relationship("Product", back_populates="price_edit_logs")
    edited_by_user: Mapped["User"] = relationship("User", back_populates="price_edits_made")


class Refund(Base):
    """A whole receipt handed back, booked to the (still open) shift the sale was made in. Append-only."""
    __tablename__ = "refunds"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ref_number: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True)  # RFD-YYYYMMDD-XXXX
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), nullable=False, index=True)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id"), nullable=True, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    cost_amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=Decimal("0"))
    refund_cash: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    refund_card: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    refund_account: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    transaction: Mapped["Transaction"] = relationship("Transaction", back_populates="refunds")
