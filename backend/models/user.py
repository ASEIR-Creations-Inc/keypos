import enum
from datetime import datetime

from sqlalchemy import String, Boolean, DateTime, ForeignKey, Enum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class UserRole(str, enum.Enum):
    admin = "admin"
    manager = "manager"
    cashier = "cashier"
    sheet = "sheet"  # Day Sheet only: fills in sheets in the KEYPOS Sheet app, nothing else


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole), nullable=False, default=UserRole.cashier
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    permissions: Mapped["UserPermission"] = relationship(
        "UserPermission", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )

    # History collections: never loaded implicitly (query them explicitly when needed)
    transactions_cashiered = relationship("Transaction", back_populates="cashier", lazy="raise")
    customer_payments_received = relationship("CustomerPayment", back_populates="received_by", lazy="raise")
    expenses_entered = relationship("Expense", back_populates="entered_by", lazy="raise")
    shift_opened = relationship("Shift", back_populates="cashier", lazy="raise")
    stock_adjustments_made = relationship("StockAdjustment", back_populates="adjusted_by", lazy="raise")
    purchase_orders_created = relationship("PurchaseOrder", back_populates="created_by", foreign_keys="PurchaseOrder.created_by_id", lazy="raise")
    purchase_orders_posted = relationship("PurchaseOrder", back_populates="posted_by", foreign_keys="PurchaseOrder.posted_by_id", lazy="raise")
    price_edits_made = relationship("PriceEditLog", back_populates="edited_by_user", lazy="raise")


class UserPermission(Base):
    __tablename__ = "user_permissions"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    can_edit_price: Mapped[bool] = mapped_column(Boolean, default=False)
    can_refund: Mapped[bool] = mapped_column(Boolean, default=False)
    can_discount: Mapped[bool] = mapped_column(Boolean, default=False)
    can_approve_sheets: Mapped[bool] = mapped_column(Boolean, default=False)
    can_view_reports: Mapped[bool] = mapped_column(Boolean, default=False)
    can_manage_inventory: Mapped[bool] = mapped_column(Boolean, default=False)
    permission_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    inventory_access: Mapped[str] = mapped_column(String(20), default="read", server_default="read")
    purchases_access: Mapped[str] = mapped_column(String(20), default="none", server_default="none")
    reports_access: Mapped[str] = mapped_column(String(20), default="own", server_default="own")
    customers_access: Mapped[str] = mapped_column(String(20), default="read", server_default="read")
    expenses_access: Mapped[str] = mapped_column(String(20), default="own", server_default="own")
    users_access: Mapped[str] = mapped_column(String(20), default="none", server_default="none")

    user: Mapped["User"] = relationship("User", back_populates="permissions")
