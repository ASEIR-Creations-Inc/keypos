"""Server-side account recovery.

    venv/bin/python manage.py set-password <username>            # prompts for the new password
    venv/bin/python manage.py set-password <username> --generate  # prints a random one

The account is also re-activated. The change is written to the audit trail.
"""
import argparse
import asyncio
import getpass
import secrets
import sys

from sqlalchemy import func, select

from core.auth import hash_password
from database import async_session_factory, engine
from models.user import User
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
    sp = sub.add_parser("set-password", help="set a user's password and re-activate the account")
    sp.add_argument("username")
    sp.add_argument("--generate", action="store_true", help="generate a random password and print it")
    args = parser.parse_args()

    password = secrets.token_urlsafe(12) if args.generate else _read_password()
    asyncio.run(set_password(args.username, password))
    print(f"Password for {args.username} updated." + (f"\nNew password: {password}" if args.generate else ""))


if __name__ == "__main__":
    main()
