from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, LargeBinary, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class DaySheet(Base):
    """A day sheet: one day's sales and expenses, recorded once as a receipt plus expenses.

    kind "excel": a file the POS issued, filled in offline, refreshed during the day and
    uploaded once (status open -> uploaded). token is the hidden id inside the file; each
    refresh issues the next version, and only the newest version is accepted.

    kind "app": filled in the KEYPOS Sheet app and kept in content (status draft ->
    submitted -> approved, or back to returned with a note; a draft may be discarded).
    token is the id the phone gave the sheet, so a retried save can't create a second one.

    code (DS-MMDD-XXXX) is the id people read, for both kinds.
    """
    __tablename__ = "day_sheets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    token: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    lang: Mapped[str] = mapped_column(String(5), nullable=False)
    sheet_date: Mapped[date] = mapped_column(Date, nullable=False)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="excel")  # excel | app
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open", index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id"), nullable=True)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    content: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    returned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    return_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)  # newest version, for re-download
