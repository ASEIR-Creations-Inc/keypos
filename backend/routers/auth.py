from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.access import permissions_summary
from core.auth import create_access_token, get_current_active_user, hash_password, verify_password
from core.config import settings
from database import get_db
from models.user import User
from schemas.auth import LoginRequest, PasswordChange, TokenResponse, UserMeResponse
from services.audit import active_shift_id, log_event

router = APIRouter(tags=["auth"])

# Checked when the username doesn't exist, so a wrong username takes as long as a wrong password.
_DUMMY_HASH = hash_password("not-a-real-password")


def _me(user: User) -> UserMeResponse:
    return UserMeResponse(
        id=user.id,
        name=user.name,
        username=user.username,
        role=user.role.value,
        permissions=permissions_summary(user),
    )


def _token_response(user: User) -> TokenResponse:
    token = create_access_token({"user_id": user.id, "username": user.username, "role": user.role.value})
    return TokenResponse(
        **_me(user).model_dump(),
        access_token=token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(
        select(User).options(selectinload(User.permissions)).where(
            func.lower(User.username) == body.username.strip().lower(), User.is_active.is_(True)
        )
    )).scalar_one_or_none()
    password_ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not password_ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    return _token_response(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(user: User = Depends(get_current_active_user)):
    return _token_response(user)


@router.get("/me", response_model=UserMeResponse)
async def me(user: User = Depends(get_current_active_user)):
    return _me(user)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordChange,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is wrong")
    user.password_hash = hash_password(body.new_password)
    log_event(
        db, "user_updated", f"User {user.username} changed their own password",
        user_id=user.id, shift_id=await active_shift_id(db, user.id), ref=user.username,
        details={"password": "changed"},
    )
    await db.commit()
