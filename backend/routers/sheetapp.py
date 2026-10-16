"""KEYPOS Sheet app: the only routes (besides /auth) a Day Sheet account can reach."""
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_active_user
from database import get_db
from models.user import User
from schemas.daysheets import AppCatalog, AppSheet, AppSheetSave
from services.daysheet import app

router = APIRouter(prefix="/daysheets/app", tags=["sheet-app"])


@router.get("/catalog", response_model=AppCatalog)
async def sheet_catalog(db: AsyncSession = Depends(get_db)):
    return await app.catalog(db)


@router.get("/mine", response_model=list[AppSheet])
async def my_sheets(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_active_user)):
    return await app.my_sheets(db, user)


@router.put("/{token}", response_model=AppSheet)
async def save_sheet(
    token: str, data: AppSheetSave, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_active_user),
):
    return await app.save(db, user, token, data)


@router.post("/{token}/submit", response_model=AppSheet)
async def submit_sheet(
    token: str, data: AppSheetSave, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_active_user),
):
    return await app.submit(db, user, token, data)


@router.delete("/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def discard_sheet(token: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_active_user)):
    await app.discard(db, user, token)
