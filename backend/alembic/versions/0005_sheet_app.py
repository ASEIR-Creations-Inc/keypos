"""KEYPOS Sheet: day sheets filled in the app, sent by a Day Sheet user and approved in the POS.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-04
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'sheet'")
    op.add_column(
        "user_permissions",
        sa.Column("can_approve_sheets", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("user_permissions", "can_approve_sheets", server_default=None)

    op.add_column("day_sheets", sa.Column("kind", sa.String(10), nullable=False, server_default="excel"))
    op.alter_column("day_sheets", "kind", server_default=None)
    op.add_column("day_sheets", sa.Column("content", JSONB(), nullable=True))
    op.add_column("day_sheets", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("day_sheets", sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("day_sheets", sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("day_sheets", sa.Column("returned_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))
    op.add_column("day_sheets", sa.Column("return_note", sa.Text(), nullable=True))
    op.create_index("ix_day_sheets_status", "day_sheets", ["status"])


def downgrade() -> None:
    op.drop_index("ix_day_sheets_status", table_name="day_sheets")
    for column in ("return_note", "returned_by", "returned_at", "submitted_at", "updated_at", "content", "kind"):
        op.drop_column("day_sheets", column)
    op.drop_column("user_permissions", "can_approve_sheets")
