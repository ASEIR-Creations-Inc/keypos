# Import all models so SQLAlchemy metadata registers them before create_all runs.
# This module acts as the single entry point — main.py imports `models` once.
from database import Base

from models.user import User, UserPermission, UserRole
from models.product import Product, Category, Unit
from models.transaction import Transaction, TransactionLine, PriceEditLog, Refund, TransactionStatus
from models.purchase import PurchaseOrder, PurchaseOrderLine, Supplier, PurchaseStatus
from models.customer import Customer, CustomerPayment
from models.expense import Expense, ExpenseCategory
from models.shift import Shift, ShiftStatus
from models.sync import SyncQueue, StockAdjustment
from models.setting import Setting
from models.counter import RefCounter
from models.audit import AuditLog, StockMovement
from models.daysheet import DaySheet

__all__ = [
    "Base",
    "User", "UserPermission", "UserRole",
    "Product", "Category", "Unit",
    "Transaction", "TransactionLine", "PriceEditLog", "Refund", "TransactionStatus",
    "PurchaseOrder", "PurchaseOrderLine", "Supplier", "PurchaseStatus",
    "Customer", "CustomerPayment",
    "Expense", "ExpenseCategory",
    "Shift", "ShiftStatus",
    "SyncQueue", "StockAdjustment",
    "Setting",
    "RefCounter",
    "AuditLog", "StockMovement",
    "DaySheet",
]
