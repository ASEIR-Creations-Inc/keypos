"""The shop's calendar: report days, receipt dates and "today" follow the time zone in Settings."""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from services.settings import load_settings


async def shop_zone(db: AsyncSession) -> ZoneInfo:
    return ZoneInfo((await load_settings(db)).timezone)


async def shop_today(db: AsyncSession) -> date:
    return datetime.now(await shop_zone(db)).date()


def parse_day(value: str) -> date:
    """Parse "2026-10-08" (a longer ISO timestamp is cut to its date); 400 otherwise."""
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid date format: {exc}") from exc


def day_start(day: date, zone: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, zone)


def day_end(day: date, zone: ZoneInfo) -> datetime:
    return datetime.combine(day, time.max, zone)


def day_range(from_date: str, to_date: str, zone: ZoneInfo) -> tuple[datetime, datetime]:
    """Whole shop days: the first instant of from_date to the last instant of to_date."""
    first, last = parse_day(from_date), parse_day(to_date)
    if first > last:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="from_date must be before to_date")
    return day_start(first, zone), day_end(last, zone)
