"""Day sheets: Excel sheets issued by the POS and uploaded once as a receipt plus expenses.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-01
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "day_sheets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(20), nullable=False, unique=True),
        sa.Column("token", sa.String(36), nullable=False, unique=True),
        sa.Column("lang", sa.String(5), nullable=False),
        sa.Column("sheet_date", sa.Date(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("shift_id", sa.Integer(), sa.ForeignKey("shifts.id"), nullable=True),
        sa.Column("transaction_id", sa.Integer(), sa.ForeignKey("transactions.id"), nullable=True),
        sa.Column("file_name", sa.String(255), nullable=True),
        sa.Column("summary", JSONB(), nullable=True),
        sa.Column("file_data", sa.LargeBinary(), nullable=True),
    )
    op.add_column("expenses", sa.Column("day_sheet_id", sa.Integer(), sa.ForeignKey("day_sheets.id"), nullable=True))
    op.create_index("ix_expenses_day_sheet_id", "expenses", ["day_sheet_id"])


def downgrade() -> None:
    op.drop_index("ix_expenses_day_sheet_id", table_name="expenses")
    op.drop_column("expenses", "day_sheet_id")
    op.drop_table("day_sheets")
