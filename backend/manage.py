"""Server-side account setup and recovery.

    venv/bin/python manage.py create-admin <username> --name "Shop Owner"  # first admin, fresh install
    venv/bin/python manage.py set-password <username>            # prompts for the new password
    venv/bin/python manage.py set-password <username> --generate  # prints a random one

create-admin only works while the database has no admin. set-password also re-activates
the account. Both changes are written to the audit trail.
"""
import argparse
import asyncio
import getpass
import secrets
import sys

from sqlalchemy import func, select

from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import hash_password
from database import async_session_factory, engine
from migrations import migrate
from models.user import User, UserPermission, UserRole
from routers.users import ROLE_DEFAULTS
from services.audit import active_shift_id, log_event

import models  # noqa: F401  (registers every table)

MIN_LENGTH = 8


def _read_password() -> str:
    first = getpass.getpass("New password: ")
    if len(first) < MIN_LENGTH:
        sys.exit(f"Password must be at least {MIN_LENGTH} characters")
    if getpass.getpass("Repeat it: ") != first:
        sys.exit("Passwords don't match")
    return first


async def create_admin(db: AsyncSession, username: str, name: str, password: str) -> User:
    """Add the first admin; the caller commits."""
    if (await db.execute(select(User.id).where(User.role == UserRole.admin).limit(1))).first():
        sys.exit("This database already has an admin; use set-password to recover it")
    taken = (await db.execute(
        select(User.id).where(func.lower(User.username) == username.lower())
    )).first()
    if taken:
        sys.exit(f"The username {username!r} is already taken")
    user = User(name=name, username=username, password_hash=hash_password(password),
                role=UserRole.admin, is_active=True)
    user.permissions = UserPermission(**ROLE_DEFAULTS["admin"])
    db.add(user)
    await db.flush()
    log_event(
        db, "user_created", f"User {username} (admin) created from the server console",
        user_id=user.id, shift_id=None, ref=username,
        details={"role": "admin", "source": "manage.py"},
    )
    await db.flush()
    return user


async def _create_admin(username: str, name: str, password: str) -> None:
    async with engine.begin() as conn:
        await migrate(conn)
    async with async_session_factory() as db:
        await create_admin(db, username, name, password)
        await db.commit()
    await engine.dispose()


async def set_password(username: str, password: str) -> None:
    async with async_session_factory() as db:
        user = (await db.execute(
            select(User).where(func.lower(User.username) == username.lower())
        )).scalar_one_or_none()
        if not user:
            sys.exit(f"No user called {username!r}")
        user.password_hash = hash_password(password)
        reactivated = not user.is_active
        user.is_active = True
        log_event(
            db, "user_updated",
            f"Password of {user.username} reset from the server console"
            + (" (account re-activated)" if reactivated else ""),
            user_id=user.id, shift_id=await active_shift_id(db, user.id), ref=user.username,
            details={"password": "reset", "reactivated": reactivated, "source": "manage.py"},
        )
        await db.commit()
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    ca = sub.add_parser("create-admin", help="create the first admin on a fresh install")
    ca.add_argument("username")
    ca.add_argument("--name", help="display name (default: the username)")
    ca.add_argument("--generate", action="store_true", help="generate a random password and print it")
    sp = sub.add_parser("set-password", help="set a user's password and re-activate the account")
    sp.add_argument("username")
    sp.add_argument("--generate", action="store_true", help="generate a random password and print it")
    args = parser.parse_args()

    password = secrets.token_urlsafe(12) if args.generate else _read_password()
    shown = f"\nPassword: {password}" if args.generate else ""
    if args.command == "create-admin":
        asyncio.run(_create_admin(args.username, args.name or args.username, password))
        print(f"Admin {args.username} created." + shown)
        return
    asyncio.run(set_password(args.username, password))
    print(f"Password for {args.username} updated." + shown)


if __name__ == "__main__":
    main()
