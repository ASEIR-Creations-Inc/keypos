"""Who may do what: role access levels and per-action flags, enforced on the server.

Every user has an access level per area (users.py ROLE_DEFAULTS sets them from the
role, the admin can change them per user):

    none < own/read < team < full

- "read" lets a user look (e.g. a cashier picking a customer for an account sale).
- "own" lets a user work with their own records only (their shifts, their expenses).
- "team" lets a user see everyone's records.
- "full" lets a user change the area (edit products, post purchases, manage users).

Admins always pass. Day Sheet users (role "sheet") only reach /auth and the KEYPOS
Sheet app's own routes; require_staff refuses them everywhere else. The frontend hides
what a user can't use, but only these checks decide.
"""
from fastapi import Depends, HTTPException, status

from core.auth import get_current_active_user
from models.user import User, UserRole

LEVELS = {"none": 0, "own": 1, "read": 1, "team": 2, "full": 3}
AREAS = ("inventory", "purchases", "reports", "customers", "expenses", "users")
FLAGS = ("edit_price", "refund", "discount", "approve_sheets")


def is_admin(user: User) -> bool:
    return user.role == UserRole.admin


def is_sheet_user(user: User) -> bool:
    return user.role == UserRole.sheet


def access_level(user: User, area: str) -> int:
    if is_admin(user):
        return LEVELS["full"]
    perm = user.permissions
    return LEVELS.get(getattr(perm, f"{area}_access", "none") if perm else "none", 0)


def has_flag(user: User, flag: str) -> bool:
    if is_admin(user):
        return True
    perm = user.permissions
    return bool(perm and getattr(perm, f"can_{flag}", False))


def sees_everyone(user: User, area: str) -> bool:
    """team/full: the user sees all staff's records in the area, not just their own."""
    return access_level(user, area) >= LEVELS["team"]


def forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def require_access(area: str, level: str):
    """Dependency: the current user needs at least `level` in `area`."""
    needed = LEVELS[level]

    async def checker(user: User = Depends(get_current_active_user)) -> User:
        if access_level(user, area) < needed:
            raise forbidden(f"You don't have {level} access to {area}")
        return user

    return checker


def require_flag(flag: str):
    """Dependency: the current user needs the can_<flag> permission."""
    async def checker(user: User = Depends(get_current_active_user)) -> User:
        if not has_flag(user, flag):
            raise forbidden(f"You don't have permission to {flag.replace('_', ' ')}")
        return user

    return checker


async def require_staff(user: User = Depends(get_current_active_user)) -> User:
    """Every POS route: a Day Sheet account may only use the KEYPOS Sheet app."""
    if is_sheet_user(user):
        raise forbidden("This account can only use the KEYPOS Sheet app")
    return user


async def require_admin(user: User = Depends(get_current_active_user)) -> User:
    if not is_admin(user):
        raise forbidden("Only an admin can do this")
    return user


def permissions_summary(user: User) -> dict:
    """The effective permissions the frontend uses to show or hide screens and buttons."""
    return {
        "is_admin": is_admin(user),
        "sheet_only": is_sheet_user(user),
        **{f"{area}_access": _effective_level(user, area) for area in AREAS},
        **{f"can_{flag}": has_flag(user, flag) for flag in FLAGS},
    }


def _effective_level(user: User, area: str) -> str:
    if is_admin(user):
        return "full"
    perm = user.permissions
    return getattr(perm, f"{area}_access", "none") if perm else "none"
