from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, Text, Numeric, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class AuditLog(Base):
    """One row per event that moved stock, cash, card or account money, or changed how it is counted.

    Rows are append-only: a database trigger rejects UPDATE and DELETE.
    """
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    ref: Mapped[str | None] = mapped_column(String(60), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    cash: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    card: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    account: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    stock_movements: Mapped[list["StockMovement"]] = relationship(
        "StockMovement", back_populates="audit", order_by="StockMovement.id"
    )


class StockMovement(Base):
    """Every change to a product's stock quantity, with the quantity before and after. Append-only."""
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audit_log.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    qty_change: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    qty_before: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    qty_after: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)

    audit: Mapped["AuditLog"] = relationship("AuditLog", back_populates="stock_movements")
