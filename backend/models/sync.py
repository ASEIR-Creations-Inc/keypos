from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, Text, Numeric, DateTime, ForeignKey, Boolean, Integer, Index, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class SyncQueue(Base):
    __tablename__ = "sync_queue"
    __table_args__ = (
        Index(
            "uq_sync_queue_device_client_ref", "device_id", "client_ref", unique=True,
            postgresql_where=text("client_ref IS NOT NULL AND synced"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(100), nullable=False)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    synced: Mapped[bool] = mapped_column(Boolean, default=False)
    client_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    record_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StockAdjustment(Base):
    __tablename__ = "stock_adjustments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    qty_before: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    qty_after: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    adjustment: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    adjusted_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    product: Mapped["Product"] = relationship(
        "Product", back_populates="stock_adjustments", lazy="joined"
    )
    adjusted_by: Mapped["User"] = relationship(
        "User", back_populates="stock_adjustments_made"
    )
