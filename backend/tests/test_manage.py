"""manage.py create-admin: the first account on a fresh install."""
import pytest
from sqlalchemy import select, update

import manage
from models.audit import AuditLog
from models.user import User, UserRole


async def test_create_admin_refused_when_an_admin_exists(db):
    with pytest.raises(SystemExit, match="already has an admin"):
        await manage.create_admin(db, "second_admin", "Second", "password-123")


async def test_create_admin_on_a_database_without_admins(db):
    await db.execute(update(User).where(User.role == UserRole.admin).values(role=UserRole.manager))
    try:
        user = await manage.create_admin(db, "owner", "Shop Owner", "password-123")
        assert user.role == UserRole.admin and user.is_active
        assert user.permissions.users_access == "full" and user.permissions.can_approve_sheets
        entry = (await db.execute(select(AuditLog).where(AuditLog.user_id == user.id))).scalar_one()
        assert entry.action == "user_created" and entry.details["source"] == "manage.py"
        with pytest.raises(SystemExit, match="already has an admin"):
            await manage.create_admin(db, "another", "Another", "password-123")
    finally:
        await db.rollback()


async def test_create_admin_rejects_a_taken_username(db):
    await db.execute(update(User).where(User.role == UserRole.admin).values(role=UserRole.manager))
    try:
        with pytest.raises(SystemExit, match="already taken"):
            await manage.create_admin(db, "ADMIN", "Clash", "password-123")
    finally:
        await db.rollback()
