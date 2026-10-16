"""Day sheets filled in the KEYPOS Sheet app, sent by their author and approved in the POS.

- save: the phone keeps the sheet and saves it here whenever it's online. The phone picks
  the sheet's token, so a retried save updates the same sheet instead of making a second.
- submit: the author sends the sheet once it has no problems; it is then locked for them.
- return: an approver sends it back with a note; the author can change it and send again.
- approve: an approver records it in their own open shift (one receipt per block of lines,
  plus the expenses), re-checked against live stock at that moment.

The checks are the Excel sheet's (service.py). The author's check skips the shift and
permission rules, which only apply to whoever records the sheet.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.access import forbidden, has_flag
from models.daysheet import DaySheet
from models.user import User
from schemas.daysheets import (
    AppCatalog, AppContent, AppSheet, AppSheetSave, CatalogCategory, CatalogProduct, SheetExpense, SheetLine,
    SheetReview, SheetTotals,
)
from services.audit import active_shift_id, log_event
from services.clock import shop_today
from services.daysheet.layout import ExpenseInput, SalesInput, SheetInputs
from services.daysheet.service import (
    Evaluation, _categories, _check_all, _live_products, _new_code, _user_name, bad_request, not_found,
    problem_text, receipt_refs, record_sheet, recorded_blocks, records_expenses, visible,
)
from services.sales import open_shift_for
from services.settings import load_settings

EDITABLE = ("draft", "returned")
MAX_SHEET_AGE = timedelta(days=7)


def _raw(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _sales(content: AppContent) -> list[SalesInput]:
    """Line n of its block is row n + 1; the block is named only when the sheet has several."""
    several = content.blocks > 1
    seen: dict[int, int] = {}
    rows = []
    for l in content.lines:
        seen[l.block] = seen.get(l.block, 0) + 1
        rows.append(SalesInput(
            row=seen[l.block] + 1, product=l.product, qty=_raw(l.qty), price=_raw(l.price), product_id=l.product_id,
            block=l.block if several else None, pay=l.pay, card=_raw(l.card),
        ))
    return rows


def _inputs(content: AppContent, categories: dict[int, str]) -> SheetInputs:
    """The app's content in the Excel sheet's terms."""
    return SheetInputs(
        sales=_sales(content),
        expenses=[
            ExpenseInput(
                row=i + 2,
                category=(categories.get(e.category_id, f"#{e.category_id}") if e.category_id else ""),
                amount=_raw(e.amount),
                description=e.description.strip(),
                paid_from=e.paid_from or "",
            )
            for i, e in enumerate(content.expenses)
        ],
        card=_raw(content.card),
        counted=_raw(content.counted),
        start=_raw(content.start),
    )


async def _evaluate(db: AsyncSession, content: AppContent, recorder: User | None) -> Evaluation:
    """recorder None: the author's check (any price may be typed; stock is never shown as a number).
    Otherwise the approver's, who records the sheet: their open shift, their expenses permission, and
    can_edit_price for any line charged differently from a set catalogue price."""
    ev = Evaluation()
    if recorder is not None and not await open_shift_for(db, recorder.id):
        ev.problem("sheet", "Open a shift before approving: the sheet is recorded in your shift")
    categories = dict(await _categories(db))
    await _check_all(
        db, ev, _inputs(content, categories), [],
        may_reprice=recorder is None or has_flag(recorder, "edit_price"),
        may_record=recorder is None or records_expenses(recorder),
        show_stock=recorder is not None,
    )
    return ev


def _start_date(sent: date | None, today: date) -> date:
    """The phone's date for a sheet started offline, within the last week; otherwise the shop's today."""
    return sent if sent and today - MAX_SHEET_AGE <= sent <= today else today


def _content(sheet: DaySheet) -> AppContent:
    return AppContent.model_validate(sheet.content or {})


async def _app_sheet(db: AsyncSession, sheet: DaySheet, ev: Evaluation | None = None) -> AppSheet:
    content = _content(sheet)
    if ev is None:
        ev = _recorded(sheet) if sheet.status == "approved" else await _evaluate(db, content, None)
    refs = await receipt_refs(db, sheet)
    return AppSheet(
        token=sheet.token, code=sheet.code, lang=sheet.lang, sheet_date=sheet.sheet_date, status=sheet.status,
        content=content, updated_at=sheet.updated_at, submitted_at=sheet.submitted_at,
        returned_at=sheet.returned_at, returned_by_name=await _user_name(db, sheet.returned_by),
        return_note=sheet.return_note, approved_at=sheet.uploaded_at,
        receipt_ref=(refs[0] if refs else None), receipt_refs=refs, totals=ev.totals, problems=ev.problems,
    )


def _token(token: str) -> str:
    try:
        return str(uuid.UUID(token))
    except ValueError as exc:
        raise bad_request("Invalid sheet id") from exc


async def _own_sheet(db: AsyncSession, user: User, token: str, lock: bool = False) -> DaySheet | None:
    stmt = select(DaySheet).where(DaySheet.token == _token(token))
    if lock:
        stmt = stmt.with_for_update()
    sheet = (await db.execute(stmt)).scalar_one_or_none()
    if sheet and (sheet.kind != "app" or sheet.created_by != user.id or sheet.status == "discarded"):
        raise not_found()
    return sheet


def _locked(sheet: DaySheet) -> HTTPException:
    word = "approved" if sheet.status == "approved" else "sent for approval"
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"{sheet.code} was already {word}")


async def _store(db: AsyncSession, user: User, token: str, data: AppSheetSave) -> DaySheet:
    sheet = await _own_sheet(db, user, token, lock=True)
    now = datetime.now(timezone.utc)
    if sheet is None:
        day = _start_date(data.sheet_date, await shop_today(db))
        sheet = DaySheet(
            code=await _new_code(db, day), token=_token(token), kind="app", lang=data.lang, sheet_date=day,
            version=1, status="draft", created_by=user.id,
        )
        db.add(sheet)
    elif sheet.status not in EDITABLE:
        raise _locked(sheet)
    sheet.lang = data.lang
    sheet.content = data.content.model_dump(mode="json")
    sheet.updated_at = now
    return sheet


# ── The author (KEYPOS Sheet app) ───────────────────────────────

async def catalog(db: AsyncSession) -> AppCatalog:
    live = await _live_products(db)
    settings = await load_settings(db)
    products = sorted((p for p in live.values() if p.active), key=lambda p: (p.name.casefold(), p.id))
    return AppCatalog(
        products=[CatalogProduct(id=p.id, name=p.name, price=p.sell_price, stock=p.stock) for p in products],
        categories=[CatalogCategory(id=cid, name=name) for cid, name in await _categories(db)],
        currency_symbol=settings.currency_symbol,
        tax_rate=settings.tax_rate,
    )


async def my_sheets(db: AsyncSession, user: User, limit: int = 50) -> list[AppSheet]:
    rows = (await db.execute(
        select(DaySheet)
        .where(DaySheet.kind == "app", DaySheet.created_by == user.id, DaySheet.status != "discarded")
        .order_by(DaySheet.id.desc())
        .limit(limit)
    )).scalars().all()
    return [await _app_sheet(db, sheet) for sheet in rows]


async def save(db: AsyncSession, user: User, token: str, data: AppSheetSave) -> AppSheet:
    sheet = await _store(db, user, token, data)
    await db.commit()
    return await _app_sheet(db, sheet)


async def submit(db: AsyncSession, user: User, token: str, data: AppSheetSave) -> AppSheet:
    sheet = await _store(db, user, token, data)
    ev = await _evaluate(db, data.content, None)
    if ev.problems:
        await db.rollback()
        raise bad_request(f"The sheet can't be sent yet: {problem_text(ev.problems)}")
    resent = sheet.status == "returned"
    sheet.status = "submitted"
    sheet.submitted_at = datetime.now(timezone.utc)
    t = ev.totals
    log_event(
        db, "day_sheet_submitted",
        f"Day sheet {sheet.code} {'sent again' if resent else 'sent'} for approval by {user.name}: "
        f"{len(ev.lines)} line(s)" + (f" in {len(ev.blocks)} blocks" if len(ev.blocks) > 1 else "")
        + f" {t.receipt_total:.2f}, {len(ev.expenses)} expense(s)",
        user_id=user.id, shift_id=None, ref=sheet.code, amount=t.receipt_total,
    )
    await db.commit()
    return await _app_sheet(db, sheet, ev)


async def discard(db: AsyncSession, user: User, token: str) -> None:
    """Drop a draft that was never sent. Once sent, a sheet stays on record."""
    sheet = await _own_sheet(db, user, token, lock=True)
    if sheet is None:
        raise not_found()
    if sheet.status != "draft" or sheet.submitted_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"{sheet.code} was sent and can't be deleted")
    sheet.status = "discarded"
    sheet.updated_at = datetime.now(timezone.utc)
    await db.commit()


# ── The approver (POS) ──────────────────────────────────────────

async def _sent_sheet(db: AsyncSession, user: User, sheet_id: int, lock: bool = False) -> DaySheet:
    stmt = select(DaySheet).where(DaySheet.id == sheet_id, DaySheet.kind == "app")
    if lock:
        stmt = stmt.with_for_update()
    sheet = (await db.execute(stmt)).scalar_one_or_none()
    if not sheet or sheet.status in ("draft", "discarded") or not visible(user, sheet):
        raise not_found()
    return sheet


def _may_approve(user: User) -> None:
    if not has_flag(user, "approve_sheets"):
        raise forbidden("You don't have permission to approve day sheets")


def _recorded(sheet: DaySheet) -> Evaluation:
    """An approved sheet exactly as it was recorded, whatever has changed in the catalogue since."""
    saved = sheet.summary or {}
    return Evaluation(
        lines=[SheetLine.model_validate(l) for l in saved.get("recorded_lines", [])],
        expenses=[SheetExpense.model_validate(e) for e in saved.get("recorded_expenses", [])],
        totals=SheetTotals.model_validate({k: saved.get(k) for k in SheetTotals.model_fields}),
        blocks=recorded_blocks(sheet),
    )


async def review(db: AsyncSession, user: User, sheet_id: int) -> SheetReview:
    sheet = await _sent_sheet(db, user, sheet_id)
    pending = sheet.status == "submitted"
    approver = has_flag(user, "approve_sheets")
    if sheet.status == "approved":
        ev = _recorded(sheet)
    else:
        ev = await _evaluate(db, _content(sheet), user if pending and approver else None)
    refs = await receipt_refs(db, sheet)
    return SheetReview(
        id=sheet.id, code=sheet.code, sheet_date=sheet.sheet_date, status=sheet.status,
        created_by_name=await _user_name(db, sheet.created_by) or "", submitted_at=sheet.submitted_at,
        returned_at=sheet.returned_at, return_note=sheet.return_note, approved_at=sheet.uploaded_at,
        approved_by_name=await _user_name(db, sheet.uploaded_by), receipt_ref=(refs[0] if refs else None),
        receipt_refs=refs, blocks=ev.blocks, lines=ev.lines, expenses=ev.expenses, totals=ev.totals, problems=ev.problems if pending else [],
        can_approve=pending and not ev.problems and approver,
    )


def _waiting(sheet: DaySheet) -> None:
    if sheet.status != "submitted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{sheet.code} is not waiting for approval (it is {sheet.status})",
        )


async def approve(db: AsyncSession, user: User, sheet_id: int) -> SheetReview:
    _may_approve(user)
    sheet = await _sent_sheet(db, user, sheet_id, lock=True)
    _waiting(sheet)
    ev = await _evaluate(db, _content(sheet), user)
    if ev.problems:
        raise bad_request(f"{sheet.code} can't be approved: {problem_text(ev.problems)}")
    author = await _user_name(db, sheet.created_by) or "?"
    await record_sheet(
        db, user, sheet, ev,
        label=f"Day sheet {sheet.code} ({sheet.sheet_date:%d/%m/%Y}) by {author}",
        action="day_sheet_approved", verb="approved", seller=None,
        details={"submitted_by": author, "submitted_at": sheet.submitted_at},
    )
    sheet.status = "approved"
    sheet.summary = {
        **(sheet.summary or {}),
        "recorded_lines": [l.model_dump(mode="json") for l in ev.lines],
        "recorded_expenses": [e.model_dump(mode="json") for e in ev.expenses],
    }
    await db.commit()
    return await review(db, user, sheet.id)


async def send_back(db: AsyncSession, user: User, sheet_id: int, note: str) -> SheetReview:
    _may_approve(user)
    sheet = await _sent_sheet(db, user, sheet_id, lock=True)
    _waiting(sheet)
    sheet.status = "returned"
    sheet.returned_at = datetime.now(timezone.utc)
    sheet.returned_by = user.id
    sheet.return_note = note
    log_event(
        db, "day_sheet_returned", f"Day sheet {sheet.code} returned to {await _user_name(db, sheet.created_by)}: {note}",
        user_id=user.id, shift_id=await active_shift_id(db, user.id), ref=sheet.code, details={"note": note},
    )
    await db.commit()
    return await review(db, user, sheet.id)
