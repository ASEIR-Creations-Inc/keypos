"""Drop user_permissions.can_void: voids were removed in Phase 3 (whole-receipt refunds only).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-08
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("user_permissions", "can_void")


def downgrade() -> None:
    op.add_column("user_permissions", sa.Column("can_void", sa.Boolean(), nullable=False, server_default=sa.false()))
