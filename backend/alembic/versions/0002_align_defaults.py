"""Align column defaults and NOT NULL between old and new databases.

Columns added by the old startup patches got database defaults, and a few old columns
still allowed NULL, while a database built from the baseline has neither. After this
revision both kinds of database have the same schema as the models.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

ACCESS_DEFAULTS = {
    "inventory_access": "read",
    "purchases_access": "none",
    "reports_access": "own",
    "customers_access": "read",
    "expenses_access": "own",
    "users_access": "none",
}
DEFAULTS = [
    ("customer_payments", "method", "'cash'"),
    ("expenses", "paid_from_drawer", "false"),
    ("transaction_lines", "refunded_qty", "0"),
    ("transactions", "refunded_amount", "0"),
    ("transactions", "payment_account", "0"),
]


def upgrade() -> None:
    for table, column, default in DEFAULTS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT {default}")
    op.execute("UPDATE transactions SET payment_account = 0 WHERE payment_account IS NULL")
    op.execute("ALTER TABLE transactions ALTER COLUMN payment_account SET NOT NULL")
    for column, default in ACCESS_DEFAULTS.items():
        op.execute(f"ALTER TABLE user_permissions ALTER COLUMN {column} SET DEFAULT '{default}'")
        op.execute(f"UPDATE user_permissions SET {column} = '{default}' WHERE {column} IS NULL")
        op.execute(f"ALTER TABLE user_permissions ALTER COLUMN {column} SET NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE transactions ALTER COLUMN payment_account DROP NOT NULL")
    for column in ACCESS_DEFAULTS:
        op.execute(f"ALTER TABLE user_permissions ALTER COLUMN {column} DROP NOT NULL")
