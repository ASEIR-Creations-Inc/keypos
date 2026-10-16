import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, Boolean, DateTime, Numeric, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False)  # hex color e.g. #FF5733
    sort_order: Mapped[int] = mapped_column(default=0)

    products: Mapped[list["Product"]] = relationship("Product", back_populates="category", lazy="raise", passive_deletes="all")


class Unit(Base):
    __tablename__ = "units"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)  # pcs, kg, g, box, ltr

    products: Mapped[list["Product"]] = relationship("Product", back_populates="unit", lazy="raise", passive_deletes="all")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sku: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    barcode: Mapped[str | None] = mapped_column(String(100), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("units.id"), nullable=True)
    sell_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    cost_price: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)  # WAC
    stock_qty: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=Decimal("0"))
    low_stock_threshold: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=Decimal("5"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    category: Mapped["Category"] = relationship("Category", back_populates="products", lazy="select")
    unit: Mapped["Unit"] = relationship("Unit", back_populates="products", lazy="select")
    transaction_lines: Mapped[list["TransactionLine"]] = relationship("TransactionLine", back_populates="product", lazy="raise")
    purchase_lines: Mapped[list["PurchaseOrderLine"]] = relationship("PurchaseOrderLine", back_populates="product", lazy="raise")
    stock_adjustments: Mapped[list["StockAdjustment"]] = relationship("StockAdjustment", back_populates="product", lazy="raise")
    price_edit_logs: Mapped[list["PriceEditLog"]] = relationship("PriceEditLog", back_populates="product", lazy="raise")
