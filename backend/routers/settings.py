from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.access import require_admin
from models.user import User
from database import get_db
from schemas.settings import StoreSettings
from services.settings import load_settings, save_settings

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=StoreSettings)
async def get_settings(db: AsyncSession = Depends(get_db)):
    return await load_settings(db)


@router.put("", response_model=StoreSettings)
async def update_settings(
    data: StoreSettings,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await save_settings(db, data)
