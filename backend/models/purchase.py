import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, Numeric, DateTime, ForeignKey, Enum, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class PurchaseStatus(str, enum.Enum):
    draft = "draft"
    posted = "posted"


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(
        "PurchaseOrder", back_populates="supplier", lazy="raise"
    )


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    ref_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    status: Mapped[PurchaseStatus] = mapped_column(
        Enum(PurchaseStatus), nullable=False, default=PurchaseStatus.draft
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    posted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    supplier: Mapped["Supplier | None"] = relationship("Supplier", back_populates="purchase_orders", lazy="joined")
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        "PurchaseOrderLine", back_populates="purchase_order", cascade="all, delete-orphan", lazy="selectin"
    )
    created_by: Mapped["User"] = relationship("User", foreign_keys=[created_by_id])
    posted_by: Mapped["User | None"] = relationship("User", foreign_keys=[posted_by_id])


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    wac_before: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    wac_after: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)

    purchase_order: Mapped["PurchaseOrder"] = relationship(
        "PurchaseOrder", back_populates="lines", lazy="joined"
    )
    product: Mapped["Product"] = relationship("Product", back_populates="purchase_lines")
