from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator


class StoreSettings(BaseModel):
    store_name: str = Field(default="KEYPOS", max_length=100)
    currency_symbol: str = Field(default="$", max_length=5, pattern=r"^[^<>&\"']*$")
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    low_stock_threshold: Decimal = Field(default=Decimal("5"), ge=0)
    timezone: str = Field(default="UTC", max_length=64)

    @field_validator("timezone")
    @classmethod
    def known_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown time zone: {value}") from exc
        return value
