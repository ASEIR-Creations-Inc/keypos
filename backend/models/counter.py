from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class RefCounter(Base):
    """Last number issued per reference prefix, e.g. key "TXN-20260929" -> 12."""
    __tablename__ = "ref_counters"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
