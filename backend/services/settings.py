from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.setting import Setting
from schemas.settings import StoreSettings


async def load_settings(db: AsyncSession) -> StoreSettings:
    """Stored values override the schema defaults; unknown keys are ignored."""
    rows = (await db.execute(select(Setting))).scalars().all()
    known = StoreSettings.model_fields.keys()
    return StoreSettings(**{r.key: r.value for r in rows if r.key in known})


async def save_settings(db: AsyncSession, data: StoreSettings) -> StoreSettings:
    """Fields the request leaves out keep their stored value (an older till doesn't send newer fields)."""
    current = await load_settings(db)
    merged = current.model_copy(update=data.model_dump(exclude_unset=True))
    for key, value in merged.model_dump().items():
        await db.merge(Setting(key=key, value=str(value)))
    await db.commit()
    return await load_settings(db)
