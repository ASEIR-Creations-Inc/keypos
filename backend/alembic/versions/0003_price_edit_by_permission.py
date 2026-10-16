"""Price edits are allowed by the editor's can_edit_price permission, not a one-time token.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-29
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("price_edit_log", "permission_token", nullable=True)


def downgrade() -> None:
    op.execute("UPDATE price_edit_log SET permission_token = 'permission' WHERE permission_token IS NULL")
    op.alter_column("price_edit_log", "permission_token", nullable=False)
