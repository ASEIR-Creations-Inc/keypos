from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.access import forbidden, is_admin, require_access
from core.auth import hash_password
from database import get_db
from models.user import User, UserPermission, UserRole
from services.audit import active_shift_id, log_event

router = APIRouter(prefix="/users", tags=["users"])

Role = Literal["admin", "manager", "cashier", "sheet"]
Level = Literal["none", "own", "read", "team", "full"]

ACCESS_FIELDS = (
    "inventory_access", "purchases_access", "reports_access",
    "customers_access", "expenses_access", "users_access",
)
FLAG_FIELDS = ("can_edit_price", "can_refund", "can_discount", "can_approve_sheets")

ROLE_DEFAULTS = {
    "sheet": {
        "can_edit_price": False, "can_refund": False, "can_discount": False, "can_approve_sheets": False,
        "inventory_access": "none", "purchases_access": "none", "reports_access": "none",
        "customers_access": "none", "expenses_access": "none", "users_access": "none",
    },
    "cashier": {
        "can_edit_price": False, "can_refund": False, "can_discount": False, "can_approve_sheets": False,
        "inventory_access": "read", "purchases_access": "none", "reports_access": "own",
        "customers_access": "read", "expenses_access": "own", "users_access": "none",
    },
    "manager": {
        "can_edit_price": True, "can_refund": True, "can_discount": True, "can_approve_sheets": False,
        "inventory_access": "read", "purchases_access": "read", "reports_access": "team",
        "customers_access": "full", "expenses_access": "team", "users_access": "none",
    },
    "admin": {
        "can_edit_price": True, "can_refund": True, "can_discount": True, "can_approve_sheets": True,
        "inventory_access": "full", "purchases_access": "full", "reports_access": "full",
        "customers_access": "full", "expenses_access": "full", "users_access": "full",
    },
}


class UserPermissionsIn(BaseModel):
    can_edit_price: Optional[bool] = None
    can_refund: Optional[bool] = None
    can_discount: Optional[bool] = None
    can_approve_sheets: Optional[bool] = None
    inventory_access: Optional[Level] = None
    purchases_access: Optional[Level] = None
    reports_access: Optional[Level] = None
    customers_access: Optional[Level] = None
    expenses_access: Optional[Level] = None
    users_access: Optional[Level] = None


class UserCreate(UserPermissionsIn):
    name: str = Field(min_length=1, max_length=255)
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=72)
    role: Role = "cashier"


class UserUpdate(UserPermissionsIn):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    username: Optional[str] = Field(None, min_length=1, max_length=100)
    password: Optional[str] = Field(None, min_length=8, max_length=72)
    role: Optional[Role] = None
    is_active: Optional[bool] = None


def _user_response(u: User) -> dict:
    p = u.permissions
    return {
        "id": u.id,
        "name": u.name,
        "username": u.username,
        "role": u.role.value,
        "is_active": u.is_active,
        **{f: bool(p and getattr(p, f)) for f in FLAG_FIELDS},
        **{f: getattr(p, f) if p else "none" for f in ACCESS_FIELDS},
    }


async def _load_user(db: AsyncSession, user_id: int) -> User:
    user = (await db.execute(
        select(User).options(selectinload(User.permissions)).where(User.id == user_id)
    )).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


async def _ensure_username_free(db: AsyncSession, username: str, except_id: int | None = None) -> None:
    stmt = select(User.id).where(func.lower(User.username) == username.lower())
    if except_id is not None:
        stmt = stmt.where(User.id != except_id)
    if (await db.execute(stmt)).first():
        raise HTTPException(status_code=400, detail="Username already exists")


async def _other_active_admins(db: AsyncSession, user_id: int) -> int:
    return (await db.execute(
        select(func.count()).select_from(User).where(
            User.role == UserRole.admin, User.is_active.is_(True), User.id != user_id
        )
    )).scalar_one()


def _check_grants(actor: User, chosen: dict) -> None:
    """Only an admin decides who may approve day sheets (a manager can't grant it, even to themselves)."""
    if chosen.get("can_approve_sheets") and not is_admin(actor):
        raise forbidden("Only an admin can allow approving day sheets")


async def _log_user_change(db: AsyncSession, actor: User, action: str, target: User, summary: str, details: dict) -> None:
    log_event(
        db, action, summary,
        user_id=actor.id, shift_id=await active_shift_id(db, actor.id), ref=target.username,
        details=details,
    )


@router.get("")
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_access("users", "full")),
):
    result = await db.execute(
        select(User).options(selectinload(User.permissions)).order_by(User.id)
    )
    return [_user_response(u) for u in result.scalars().all()]


@router.post("", status_code=201)
async def create_user(
    data: UserCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_access("users", "full")),
):
    if data.role == "admin" and not is_admin(actor):
        raise forbidden("Only an admin can create another admin")
    username = data.username.strip()
    await _ensure_username_free(db, username)

    user = User(
        name=data.name.strip(),
        username=username,
        password_hash=hash_password(data.password),
        role=UserRole(data.role),
        is_active=True,
    )
    db.add(user)
    await db.flush()

    defaults = ROLE_DEFAULTS[data.role]
    chosen = data.model_dump(include=set(FLAG_FIELDS + ACCESS_FIELDS), exclude_none=True)
    _check_grants(actor, chosen)
    db.add(UserPermission(user_id=user.id, **{**defaults, **chosen}))
    await _log_user_change(
        db, actor, "user_created", user, f"User {username} ({data.role}) created",
        {"role": data.role, **defaults, **chosen},
    )
    await db.commit()
    return _user_response(await _load_user(db, user.id))


@router.put("/{user_id}")
async def update_user(
    user_id: int,
    data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_access("users", "full")),
):
    user = await _load_user(db, user_id)
    if (user.role == UserRole.admin or data.role == "admin") and not is_admin(actor):
        raise forbidden("Only an admin can change an admin account or make someone admin")

    removes_admin = user.role == UserRole.admin and user.is_active and (
        (data.role is not None and data.role != "admin") or data.is_active is False
    )
    if removes_admin and await _other_active_admins(db, user.id) == 0:
        raise HTTPException(status_code=400, detail="There must always be at least one active admin")
    if data.is_active is False and user.id == actor.id:
        raise HTTPException(status_code=400, detail="You can't deactivate your own account")

    changes: dict = {}
    if data.username is not None and data.username.strip() != user.username:
        await _ensure_username_free(db, data.username.strip(), except_id=user.id)
        changes["username"] = {"from": user.username, "to": data.username.strip()}
        user.username = data.username.strip()
    if data.name is not None and data.name.strip() != user.name:
        changes["name"] = {"from": user.name, "to": data.name.strip()}
        user.name = data.name.strip()
    if data.role is not None and data.role != user.role.value:
        changes["role"] = {"from": user.role.value, "to": data.role}
        user.role = UserRole(data.role)
    if data.is_active is not None and data.is_active != user.is_active:
        changes["is_active"] = {"from": user.is_active, "to": data.is_active}
        user.is_active = data.is_active
    if data.password:
        changes["password"] = "changed"
        user.password_hash = hash_password(data.password)

    perms = user.permissions or UserPermission(user_id=user.id, **ROLE_DEFAULTS[user.role.value])
    if user.permissions is None:
        db.add(perms)
    chosen = {
        field: value
        for field, value in data.model_dump(include=set(FLAG_FIELDS + ACCESS_FIELDS), exclude_none=True).items()
        if getattr(perms, field) != value
    }
    _check_grants(actor, chosen)
    for field, value in chosen.items():
        changes[field] = {"from": getattr(perms, field), "to": value}
        setattr(perms, field, value)

    if changes:
        await _log_user_change(
            db, actor, "user_updated", user,
            f"User {user.username} changed: {', '.join(changes)}", changes,
        )
    await db.commit()
    return _user_response(await _load_user(db, user.id))


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_access("users", "full")),
):
    """Soft delete: deactivate the user instead of removing the row.
    Preserves transaction/shift history and audit trail integrity."""
    user = await _load_user(db, user_id)
    if user.id == actor.id:
        raise HTTPException(status_code=400, detail="You can't deactivate your own account")
    if user.role == UserRole.admin:
        if not is_admin(actor):
            raise forbidden("Only an admin can change an admin account or make someone admin")
        if user.is_active and await _other_active_admins(db, user.id) == 0:
            raise HTTPException(status_code=400, detail="There must always be at least one active admin")
    if user.is_active:
        user.is_active = False
        await _log_user_change(
            db, actor, "user_updated", user, f"User {user.username} deactivated",
            {"is_active": {"from": True, "to": False}},
        )
    await db.commit()
