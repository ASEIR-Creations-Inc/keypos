from datetime import datetime, date
from decimal import Decimal

from sqlalchemy import Boolean, String, Numeric, DateTime, Date, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class ExpenseCategory(Base):
    __tablename__ = "expense_categories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    expenses: Mapped[list["Expense"]] = relationship(
        "Expense", back_populates="category", lazy="raise"
    )


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("expense_categories.id"), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)
    paid_from_drawer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id"), nullable=True, index=True)
    day_sheet_id: Mapped[int | None] = mapped_column(ForeignKey("day_sheets.id"), nullable=True, index=True)
    entered_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    category: Mapped["ExpenseCategory | None"] = relationship(
        "ExpenseCategory", back_populates="expenses", lazy="joined"
    )
    entered_by: Mapped["User"] = relationship("User", back_populates="expenses_entered")
