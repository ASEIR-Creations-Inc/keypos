import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, Numeric, DateTime, ForeignKey, Enum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class ShiftStatus(str, enum.Enum):
    open = "open"
    closed = "closed"


class Shift(Base):
    __tablename__ = "shifts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cashier_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    opening_float: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    closing_cash: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    expected_cash: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    variance: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[ShiftStatus] = mapped_column(
        Enum(ShiftStatus), nullable=False, default=ShiftStatus.open
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    cashier: Mapped["User"] = relationship("User", back_populates="shift_opened")
    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction", back_populates="shift", lazy="raise"
    )
