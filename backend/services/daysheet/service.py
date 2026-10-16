"""Day sheets: issue, check, refresh and upload the Excel sheet a shop fills in during the day.

- issue: a new sheet with today's products, stock and expense categories.
- inspect: everything the POS would record from a sheet, and every problem that blocks it.
- refresh: the same sheet with the rows already typed, rebuilt on the current catalogue,
  as the next version. Records nothing.
- upload: one receipt for all the sales rows (cash/card split from the card machine slip)
  and one expense per expense row, in the uploader's open shift, all or nothing. A sheet
  is uploaded once, and only its newest version is accepted.

Sheet app sheets may have several blocks of lines: one receipt per block, with the slip
shared out between them (allocate_card).

Products are matched like the sheet's own formulas (exact name, then the only name
starting with the text, then the only name containing it), first against the catalogue
inside the file and then against the live POS, so a product created after the sheet was
made is still found. Stock is checked against live stock, not the copy in the file.
"""
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from core.access import LEVELS, access_level, has_flag, is_admin, sees_everyone
from models.daysheet import DaySheet
from models.expense import ExpenseCategory
from models.product import Product
from models.transaction import Transaction
from models.user import User
from schemas.daysheets import (
    DaySheetSummary, SheetBlock, SheetExpense, SheetInspection, SheetLine, SheetProblem, SheetTotals,
    SheetUploadResult,
)
from schemas.transactions import TransactionCreate, TransactionLineCreate
from services.audit import log_details, log_event
from services.clock import shop_today
from services.daysheet.book import build_workbook, file_name
from services.daysheet.layout import CatalogItem, ExpenseInput, Raw, SalesInput, SheetInputs, SheetMeta
from services.daysheet.parse import read_sheet, to_decimal
from services.daysheet.strings import T
from services.expenses import record_expense
from services.sales import open_shift_for, record_sale, to_cents
from services.settings import load_settings

ZERO = Decimal("0")
QTY = Decimal("0.001")
MAX_AMOUNT = Decimal("9999999")
CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
DEVICE = "daysheet"


@dataclass(frozen=True)
class LiveProduct:
    id: int
    name: str
    sell_price: Decimal
    stock: Decimal
    active: bool


@dataclass
class Evaluation:
    """What a sheet would record, the problems blocking it, and the cleaned-up inputs for a refresh."""
    lines: list[SheetLine] = field(default_factory=list)
    expenses: list[SheetExpense] = field(default_factory=list)
    problems: list[SheetProblem] = field(default_factory=list)
    totals: SheetTotals | None = None
    blocks: list[SheetBlock] = field(default_factory=list)
    cleaned: SheetInputs = field(default_factory=SheetInputs)

    def problem(self, tab: str, message: str, row: int | None = None, block: int | None = None) -> None:
        self.problems.append(SheetProblem(tab=tab, row=row, message=message, block=block))


def where(row: int, block: int | None) -> str:
    """How people number lines: row 2 is line 1; "block 2 line 5" on sheets with several blocks."""
    return (f"block {block} " if block else "") + f"line {row - 1}"


def problem_text(problems: list[SheetProblem], limit: int = 3) -> str:
    shown = "; ".join((where(p.row, p.block) + ": " if p.row else "") + p.message for p in problems[:limit])
    more = f" (and {len(problems) - limit} more)" if len(problems) > limit else ""
    return shown + more


def _share(amount: int, weights: list[int]) -> list[int]:
    """amount (cents) split in proportion to weights; leftover cents go to the largest remainders."""
    total = sum(weights)
    if not total:
        return [0] * len(weights)
    shares = [amount * w // total for w in weights]
    order = sorted(range(len(weights)), key=lambda i: (-(amount * weights[i] % total), i))
    for i in order[:amount - sum(shares)]:
        shares[i] += 1
    return shares


def allocate_card(blocks: list[tuple[Decimal, Decimal]], slip: Decimal) -> list[Decimal]:
    """Each block's share of the card machine slip, from (receipt total, card marked on its lines).

    Marked card stays with its block; the rest of the slip follows each block's unmarked total.
    If the marks add up to more than the slip, the slip wins and the marks are scaled down to it.
    The shares always add up to the slip and never pass a block's total (slip <= sum of totals)."""
    caps = [int(to_cents(total) * 100) for total, _ in blocks]
    marks = [min(int(to_cents(marked) * 100), cap) for (_, marked), cap in zip(blocks, caps)]
    cents = int(to_cents(slip) * 100)
    if sum(marks) >= cents:
        shares = _share(cents, marks)
    else:
        rest = _share(cents - sum(marks), [cap - mark for cap, mark in zip(caps, marks)])
        shares = [mark + extra for mark, extra in zip(marks, rest)]
    return [Decimal(c) / 100 for c in shares]


def bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def match_name(text: str, names: list[str]) -> tuple[int | None, int]:
    """(position, candidates): exact name, else the only name starting with text, else the only one containing it."""
    wanted = text.strip().casefold()
    if not wanted:
        return None, 0
    folded = [n.strip().casefold() for n in names]
    for i, name in enumerate(folded):
        if name == wanted:
            return i, 1
    starts = [i for i, n in enumerate(folded) if n.startswith(wanted)]
    if len(starts) == 1:
        return starts[0], 1
    contains = [i for i, n in enumerate(folded) if wanted in n]
    if len(contains) == 1:
        return contains[0], 1
    return None, len(contains)


# ── Loading ─────────────────────────────────────────────────────

async def _live_products(db: AsyncSession) -> dict[int, LiveProduct]:
    rows = (await db.execute(
        select(Product.id, Product.name, Product.sell_price, Product.stock_qty, Product.is_active)
    )).all()
    return {
        r.id: LiveProduct(r.id, r.name, r.sell_price or ZERO, r.stock_qty or ZERO, bool(r.is_active))
        for r in rows
    }


def _catalog(live: dict[int, LiveProduct]) -> list[CatalogItem]:
    active = sorted((p for p in live.values() if p.active), key=lambda p: (p.name.casefold(), p.id))
    return [CatalogItem(p.id, p.name, p.sell_price, p.stock) for p in active]


async def _categories(db: AsyncSession) -> list[tuple[int, str]]:
    rows = (await db.execute(select(ExpenseCategory.id, ExpenseCategory.name).order_by(ExpenseCategory.name))).all()
    return [(r.id, r.name) for r in rows]


async def _sheet_by_token(db: AsyncSession, token: str, lock: bool = False) -> DaySheet:
    stmt = select(DaySheet).where(DaySheet.token == token, DaySheet.kind == "excel")
    if lock:
        stmt = stmt.with_for_update()
    sheet = (await db.execute(stmt)).scalar_one_or_none()
    if not sheet:
        raise bad_request("This day sheet wasn't issued by this POS. Download a new sheet from the Day Sheet screen.")
    return sheet


async def _user_name(db: AsyncSession, user_id: int | None) -> str | None:
    return (await db.execute(select(User.name).where(User.id == user_id))).scalar_one_or_none() if user_id else None


async def _receipt_ref(db: AsyncSession, transaction_id: int | None) -> str | None:
    if not transaction_id:
        return None
    return (await db.execute(select(Transaction.ref_number).where(Transaction.id == transaction_id))).scalar_one_or_none()


# ── Checking ────────────────────────────────────────────────────

def _number(ev: Evaluation, tab: str, row: int | None, raw: Raw, label: str, block: int | None = None) -> Decimal | None:
    try:
        value = to_decimal(raw)
    except ValueError:
        ev.problem(tab, f"{label} \"{raw}\" isn't a number", row, block)
        return None
    if value is not None and (value < 0 or value > MAX_AMOUNT):
        ev.problem(tab, f"{label} {value} is out of range", row, block)
        return None
    return value


def _count(value: Decimal) -> str:
    """4.000 -> "4", 2.500 -> "2.5"."""
    return f"{value.normalize():f}" if value else "0"


def _plain(value: Decimal | None) -> Raw:
    """A cleaned number written back into a refreshed sheet."""
    if value is None:
        return None
    return int(value) if value == value.to_integral_value() else float(value)


def _check_sales(
    ev: Evaluation,
    rows: list[SalesInput],
    snapshot: list[CatalogItem],
    live: dict[int, LiveProduct],
    may_reprice: bool,
    show_stock: bool = True,
) -> None:
    """Stock is checked per product across all rows, whatever block they are in."""
    snap_names = [item.name for item in snapshot]
    active = [p for p in live.values() if p.active]
    active_names = [p.name for p in active]
    sold: dict[int, Decimal] = {}
    rows_of: dict[int, list[SalesInput]] = {}

    for row in rows:
        def problem(message: str) -> None:
            ev.problem("sales", message, row.row, row.block)

        product, fixed = None, ZERO
        if row.product_id is not None:
            product = live.get(row.product_id)
            if not product or not product.active:
                problem(f"{row.product} is no longer an active product in the POS")
                product = None
            else:
                fixed = product.sell_price
        elif not row.product:
            problem("No product")
        else:
            at, candidates = match_name(row.product, snap_names)
            if at is not None:
                product, fixed = live.get(snapshot[at].id), snapshot[at].fixed_price
                if not product or not product.active:
                    problem(f"{snapshot[at].name} is no longer an active product in the POS")
                    product = None
            else:
                live_at, live_candidates = match_name(row.product, active_names)
                if live_at is not None:
                    product = active[live_at]
                    fixed = product.sell_price
                elif max(candidates, live_candidates) > 1:
                    problem(f"\"{row.product}\" matches {max(candidates, live_candidates)} products: type more of the name")
                else:
                    problem(f"\"{row.product}\" was not found in the POS")

        qty = _number(ev, "sales", row.row, row.qty, "Quantity", row.block)
        if qty is not None:
            qty = qty.quantize(QTY)
        typed_price = _number(ev, "sales", row.row, row.price, "Price", row.block)
        price = typed_price if typed_price is not None else (fixed if fixed > 0 else None)
        ev.cleaned.sales.append(SalesInput(
            row=row.row,
            product=product.name if product else row.product,
            qty=_plain(qty) if qty is not None else row.qty,
            price=_plain(typed_price) if typed_price is not None else row.price,
        ))
        if qty is None or qty <= 0:
            if row.qty is None or qty is not None:
                problem("No quantity")
            continue
        if row.price is not None and typed_price is None:
            continue
        if price is None or price <= 0:
            problem("No price")
            continue
        price = to_cents(price)
        if not product:
            continue
        if product.sell_price > 0 and price != product.sell_price and not may_reprice:
            problem(f"You don't have permission to change the price of {product.name}")
            continue
        total = to_cents(price * qty)
        card = _card_part(ev, row, total)
        if card is None:
            continue
        ev.lines.append(SheetLine(
            row=row.row, product_id=product.id, name=product.name, qty=qty, price=price, total=total,
            block=row.block or 1, pay=row.pay, card=card,
        ))
        sold[product.id] = sold.get(product.id, ZERO) + qty
        rows_of.setdefault(product.id, []).append(row)

    for product_id, qty in sold.items():
        product = live[product_id]
        if qty > product.stock:
            lines = rows_of[product_id]
            short = f"the sheet sells {_count(qty)}, stock is {_count(product.stock)}" if show_stock else "not enough stock"
            if any(r.block for r in lines):
                at = ", ".join(where(r.row, r.block) for r in lines)
            else:
                at = ("line " if len(lines) == 1 else "lines ") + ", ".join(str(r.row - 1) for r in lines)
            ev.problem("sales", f"{product.name}: {short} ({at})", lines[-1].row, lines[-1].block)


def _card_part(ev: Evaluation, row: SalesInput, total: Decimal) -> Decimal | None:
    """The card part marked on a line (a reference only), or None when a split line is incomplete."""
    if row.pay == "card":
        return total
    if row.pay != "split":
        return ZERO
    card = _number(ev, "sales", row.row, row.card, "Card part", row.block)
    if card is None or card <= 0:
        if row.card is None or card is not None:
            ev.problem("sales", "Split payment: enter the card part", row.row, row.block)
        return None
    if to_cents(card) > total:
        ev.problem("sales", f"Card part {to_cents(card):.2f} is more than the line total {total:.2f}", row.row, row.block)
        return None
    return to_cents(card)


def _check_expenses(ev: Evaluation, rows: list[ExpenseInput], categories: list[tuple[int, str]], may_record: bool) -> None:
    if rows and not may_record:
        ev.problem("expenses", "You don't have permission to record expenses")
    by_name = {name.strip().casefold(): (cid, name) for cid, name in categories}
    for row in rows:
        category = by_name.get(row.category.strip().casefold()) if row.category else None
        amount = _number(ev, "expenses", row.row, row.amount, "Amount")
        ev.cleaned.expenses.append(ExpenseInput(
            row=row.row, category=category[1] if category else row.category,
            amount=_plain(amount) if amount is not None else row.amount,
            description=row.description, paid_from=row.paid_from,
        ))
        ok = True
        if row.category and not category:
            ev.problem("expenses", f"Category \"{row.category}\" doesn't exist in the POS", row.row)
            ok = False
        if amount is None or amount <= 0:
            if row.amount is None or amount is not None:
                ev.problem("expenses", "No amount", row.row)
            ok = False
        if row.paid_from not in ("drawer", "other"):
            ev.problem("expenses", "Paid from must be Drawer or Other", row.row)
            ok = False
        if len(row.description) > 500:
            ev.problem("expenses", "Description is longer than 500 characters", row.row)
            ok = False
        if ok:
            ev.expenses.append(SheetExpense(
                row=row.row, category_id=category[0] if category else None,
                category=category[1] if category else None, amount=to_cents(amount),
                description=row.description or None, paid_from_drawer=row.paid_from == "drawer",
            ))


def _check_summary(ev: Evaluation, inputs: SheetInputs, tax_rate: Decimal) -> None:
    card = _number(ev, "summary", None, inputs.card, "Card slip total")
    counted = _number(ev, "summary", None, inputs.counted, "Cash counted")
    start = _number(ev, "summary", None, inputs.start, "Starting cash")
    ev.cleaned.card, ev.cleaned.counted, ev.cleaned.start = (
        _plain(card) if card is not None else inputs.card,
        _plain(counted) if counted is not None else inputs.counted,
        _plain(start) if start is not None else inputs.start,
    )
    by_block: dict[int, list[SheetLine]] = {}
    for line in ev.lines:
        by_block.setdefault(line.block, []).append(line)
    blocks = []
    for number, lines in sorted(by_block.items()):
        subtotal = sum((l.total for l in lines), ZERO)
        receipt_b = subtotal + to_cents(subtotal * tax_rate / Decimal("100"))
        blocks.append((number, lines, subtotal, receipt_b, min(sum((l.card for l in lines), ZERO), receipt_b)))
    grand = sum((b[2] for b in blocks), ZERO)
    receipt = sum((b[3] for b in blocks), ZERO)
    tax = receipt - grand
    card_value = to_cents(card or ZERO)
    drawer = sum((e.amount for e in ev.expenses if e.paid_from_drawer), ZERO)
    other = sum((e.amount for e in ev.expenses if not e.paid_from_drawer), ZERO)
    start_value = to_cents(start or ZERO)
    has_sales = bool(inputs.sales)

    if has_sales and inputs.card is None:
        ev.problem("summary", "Enter the card machine slip total on the Summary tab (0 if there were no card sales)")
    if card_value > receipt:
        ev.problem("summary", f"The card slip total {card_value:.2f} is more than the day's sales {receipt:.2f}")
    if has_sales and inputs.counted is None:
        ev.problem("summary", "Enter the cash counted on the Summary tab")
    if not inputs.sales and not inputs.expenses:
        ev.problem("sheet", "The sheet has no sales or expenses yet")

    shares = allocate_card([(b[3], b[4]) for b in blocks], card_value) if card_value <= receipt else [ZERO] * len(blocks)
    ev.blocks = [
        SheetBlock(block=number, lines=len(lines), total=total, card=share, cash=total - share, card_marked=marked)
        for (number, lines, _, total, marked), share in zip(blocks, shares)
    ]
    cash_sales = receipt - card_value
    accounted = to_cents(counted) + drawer - start_value if counted is not None else None
    ev.totals = SheetTotals(
        grand_total=grand, tax=tax, receipt_total=receipt, card=card_value, cash_sales=cash_sales,
        counted=to_cents(counted) if counted is not None else None, starting_cash=start_value,
        drawer_expenses=drawer, other_expenses=other, accounted=accounted,
        difference=accounted - cash_sales if accounted is not None else None,
        card_marked=sum((b[4] for b in blocks), ZERO),
    )


async def _evaluate(
    db: AsyncSession, user: User, sheet: DaySheet, meta: SheetMeta, snapshot: list[CatalogItem], inputs: SheetInputs,
) -> tuple[Evaluation, dict[int, LiveProduct]]:
    ev = Evaluation()
    if sheet.status == "uploaded":
        receipt = await _receipt_ref(db, sheet.transaction_id)
        when = f" on {sheet.uploaded_at:%d/%m/%Y %H:%M}" if sheet.uploaded_at else ""
        ev.problem("sheet", f"{sheet.code} was already uploaded{when}" + (f" as {receipt}" if receipt else ""))
    elif meta.version < sheet.version:
        ev.problem("sheet", f"This is version {meta.version} of {sheet.code}, but version {sheet.version} exists. Use the newest file.")
    elif meta.version > sheet.version:
        ev.problem("sheet", f"This file says version {meta.version}, but the POS only issued up to version {sheet.version}.")
    if not await open_shift_for(db, user.id):
        ev.problem("sheet", "Open a shift before uploading")
    return ev, await _check_all(db, ev, inputs, snapshot, may_reprice=has_flag(user, "edit_price"), may_record=records_expenses(user))


def records_expenses(user: User) -> bool:
    return access_level(user, "expenses") >= LEVELS["own"]


async def _check_all(
    db: AsyncSession, ev: Evaluation, inputs: SheetInputs, snapshot: list[CatalogItem], *,
    may_reprice: bool, may_record: bool, show_stock: bool = True,
) -> dict[int, LiveProduct]:
    """show_stock False: say "not enough stock" without the count (Day Sheet users never see stock)."""
    live = await _live_products(db)
    _check_sales(ev, inputs.sales, snapshot, live, may_reprice, show_stock)
    _check_expenses(ev, inputs.expenses, await _categories(db), may_record)
    _check_summary(ev, inputs, (await load_settings(db)).tax_rate)
    return live


def _current(sheet: DaySheet, meta: SheetMeta) -> bool:
    return sheet.status == "open" and meta.version == sheet.version


# ── Public operations ───────────────────────────────────────────

async def _new_code(db: AsyncSession, day: date) -> str:
    while True:
        code = f"DS-{day:%m%d}-" + "".join(secrets.choice(CODE_CHARS) for _ in range(4))
        if not (await db.execute(select(DaySheet.id).where(DaySheet.code == code))).first():
            return code


def _meta_of(sheet: DaySheet) -> SheetMeta:
    return SheetMeta(token=sheet.token, code=sheet.code, version=sheet.version, lang=sheet.lang)


async def _build(db: AsyncSession, sheet: DaySheet, inputs: SheetInputs | None, live: dict[int, LiveProduct] | None = None) -> tuple[bytes, str]:
    live = live if live is not None else await _live_products(db)
    categories = [name for _, name in await _categories(db)]
    data = build_workbook(_meta_of(sheet), sheet.sheet_date, datetime.now(timezone.utc), _catalog(live), categories, inputs)
    sheet.file_data = data
    return data, file_name(_meta_of(sheet), sheet.sheet_date)


async def issue_sheet(db: AsyncSession, user: User, lang: str) -> tuple[DaySheet, bytes, str]:
    if lang not in T:
        raise bad_request(f"Language must be one of: {', '.join(T)}")
    day = await shop_today(db)
    sheet = DaySheet(
        code=await _new_code(db, day), token=str(uuid.uuid4()), lang=lang, sheet_date=day,
        version=1, status="open", created_by=user.id,
    )
    db.add(sheet)
    data, name = await _build(db, sheet, None)
    await db.commit()
    return sheet, data, name


async def inspect_sheet(db: AsyncSession, user: User, data: bytes) -> SheetInspection:
    meta, snapshot, inputs = read_sheet(data)
    sheet = await _sheet_by_token(db, meta.token)
    ev, _ = await _evaluate(db, user, sheet, meta, snapshot, inputs)
    return SheetInspection(
        code=sheet.code,
        version=meta.version,
        latest_version=sheet.version,
        lang=sheet.lang,
        sheet_date=sheet.sheet_date,
        status=sheet.status,
        created_by_name=await _user_name(db, sheet.created_by) or "",
        created_at=sheet.created_at,
        refreshed_at=sheet.refreshed_at,
        uploaded_receipt=await _receipt_ref(db, sheet.transaction_id),
        sales_rows=len(inputs.sales),
        expense_rows=len(inputs.expenses),
        lines=ev.lines,
        expenses=ev.expenses,
        totals=ev.totals,
        problems=ev.problems,
        can_refresh=_current(sheet, meta),
        can_upload=_current(sheet, meta) and not ev.problems,
    )


async def refresh_sheet(db: AsyncSession, user: User, data: bytes) -> tuple[DaySheet, bytes, str]:
    """Rebuild the sheet on the current catalogue with the rows already typed, as the next version."""
    meta, snapshot, inputs = read_sheet(data)
    sheet = await _sheet_by_token(db, meta.token, lock=True)
    ev, live = await _evaluate(db, user, sheet, meta, snapshot, inputs)
    if not _current(sheet, meta):
        raise bad_request(ev.problems[0].message)
    sheet.version += 1
    sheet.refreshed_at = datetime.now(timezone.utc)
    body, name = await _build(db, sheet, ev.cleaned, live)
    await db.commit()
    return sheet, body, name


async def sheet_file(db: AsyncSession, user: User, sheet_id: int) -> tuple[DaySheet, bytes, str]:
    """The newest version again, e.g. when a refreshed file didn't reach the phone."""
    sheet = await db.get(DaySheet, sheet_id)
    if not sheet or sheet.kind != "excel" or not visible(user, sheet):
        raise not_found()
    if sheet.status != "open":
        raise bad_request(f"{sheet.code} was already uploaded")
    data = (await db.execute(select(DaySheet.file_data).where(DaySheet.id == sheet_id))).scalar_one()
    return sheet, data, file_name(_meta_of(sheet), sheet.sheet_date)


async def upload_sheet(db: AsyncSession, user: User, data: bytes, uploaded_name: str | None) -> SheetUploadResult:
    meta, snapshot, inputs = read_sheet(data)
    sheet = await _sheet_by_token(db, meta.token, lock=True)
    ev, _ = await _evaluate(db, user, sheet, meta, snapshot, inputs)
    if ev.problems:
        raise bad_request(f"The sheet can't be uploaded: {problem_text(ev.problems)}")
    label = f"Day sheet {sheet.code} v{meta.version} ({sheet.sheet_date:%d/%m/%Y})"
    txns = await record_sheet(
        db, user, sheet, ev, label=label, action="day_sheet_uploaded", verb="uploaded", seller=user,
        details={"version": meta.version, "file_name": uploaded_name},
    )
    sheet.status = "uploaded"
    sheet.file_name = (uploaded_name or "")[:255] or None
    await db.commit()
    return SheetUploadResult(
        code=sheet.code, version=meta.version, receipt_ref=txns[0].ref_number if txns else None,
        expense_count=len(ev.expenses), totals=ev.totals,
    )


async def record_sheet(
    db: AsyncSession,
    user: User,
    sheet: DaySheet,
    ev: Evaluation,
    *,
    label: str,
    action: str,
    verb: str,
    seller: User | None,
    details: dict,
) -> list[Transaction]:
    """Record a checked sheet in the user's open shift: one receipt per block of sales (its share
    of the card slip as card, the rest cash) and one expense per expense row, plus the audit entry
    with the cash check. The caller sets the sheet's status and commits, so it is all or nothing."""
    shift = await open_shift_for(db, user.id)
    totals = ev.totals
    txns: list[Transaction] = []
    for block in ev.blocks:
        lines = [l for l in ev.lines if l.block == block.block]
        txn = await record_sale(
            db,
            TransactionCreate(
                lines=[TransactionLineCreate(product_id=l.product_id, qty=l.qty, sell_price=l.price) for l in lines],
                payment_cash=block.cash,
                payment_card=block.card,
                notes=label if len(ev.blocks) == 1 else f"{label}, block {block.block}",
                device_id=DEVICE,
                client_ref=sheet.token if block.block == 1 else f"{sheet.token}#{block.block}",
            ),
            cashier_id=user.id,
            shift_id=shift.id,
            seller=seller,
        )
        block.receipt_ref = txn.ref_number
        txns.append(txn)
    for item in ev.expenses:
        expense = await record_expense(
            db, user_id=user.id, category_id=item.category_id, amount=item.amount,
            description=item.description, expense_date=sheet.sheet_date, paid_from_drawer=item.paid_from_drawer,
        )
        expense.day_sheet_id = sheet.id

    difference = totals.difference or ZERO
    verdict = "extra cash" if difference > 0 else "short" if difference < 0 else "balanced"
    if len(txns) > 1:
        parts = [f"{len(txns)} receipts " + ", ".join(f"{t.ref_number} {t.total_amount:.2f}" for t in txns)]
    else:
        parts = [f"receipt {txns[0].ref_number} {totals.receipt_total:.2f}" if txns else "no sales"]
    if ev.expenses:
        parts.append(f"{len(ev.expenses)} expense(s) {totals.drawer_expenses + totals.other_expenses:.2f}")
    parts.append(f"cash difference {difference:+.2f} ({verdict})")
    summary = log_details({
        **totals.model_dump(), **details, "lines": len(ev.lines), "expenses": len(ev.expenses),
        "receipts": [b.model_dump() for b in ev.blocks],
    })
    log_event(
        db, action, f"{label} {verb}: " + ", ".join(parts),
        user_id=user.id, shift_id=shift.id, ref=sheet.code, amount=totals.receipt_total, details=summary,
    )
    sheet.uploaded_at = datetime.now(timezone.utc)
    sheet.uploaded_by = user.id
    sheet.shift_id = shift.id
    sheet.transaction_id = txns[0].id if txns else None
    sheet.summary = summary
    return txns


def recorded_blocks(sheet: DaySheet) -> list[SheetBlock]:
    return [SheetBlock.model_validate(b) for b in (sheet.summary or {}).get("receipts", [])]


async def receipt_refs(db: AsyncSession, sheet: DaySheet) -> list[str]:
    """Every receipt a recorded sheet became (sheets recorded before blocks have just one)."""
    refs = [b.receipt_ref for b in recorded_blocks(sheet) if b.receipt_ref]
    if refs:
        return refs
    ref = await _receipt_ref(db, sheet.transaction_id)
    return [ref] if ref else []


def not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Day sheet not found")


def sees_all_sheets(user: User) -> bool:
    return is_admin(user) or sees_everyone(user, "reports")


def visible(user: User, sheet: DaySheet) -> bool:
    """Your own sheets; everyone's for admins and team reports; approvers also see sheets sent from the app."""
    return (
        sheet.created_by == user.id or sheet.uploaded_by == user.id or sees_all_sheets(user)
        or (sheet.kind == "app" and has_flag(user, "approve_sheets"))
    )


async def list_sheets(db: AsyncSession, user: User, sheet_status: str | None = None) -> list[DaySheetSummary]:
    """Recent sheets (30), leaving out app drafts still being filled in; or every sheet with one
    status (e.g. all those waiting for approval)."""
    creator, uploader = aliased(User), aliased(User)
    stmt = (
        select(DaySheet, creator.name, uploader.name, Transaction.ref_number)
        .join(creator, creator.id == DaySheet.created_by)
        .outerjoin(uploader, uploader.id == DaySheet.uploaded_by)
        .outerjoin(Transaction, Transaction.id == DaySheet.transaction_id)
        .order_by(DaySheet.id.desc())
    )
    if sheet_status:
        stmt = stmt.where(DaySheet.status == sheet_status).limit(500)
    else:
        stmt = stmt.where(DaySheet.status.not_in(("discarded", "draft"))).limit(30)
    if not sees_all_sheets(user):
        mine = (DaySheet.created_by == user.id) | (DaySheet.uploaded_by == user.id)
        if has_flag(user, "approve_sheets"):
            mine = mine | (DaySheet.kind == "app")
        stmt = stmt.where(mine)
    rows = (await db.execute(stmt)).all()
    return [
        DaySheetSummary(
            id=sheet.id, code=sheet.code, kind=sheet.kind, sheet_date=sheet.sheet_date, lang=sheet.lang, version=sheet.version,
            status=sheet.status, created_by_name=created, created_at=sheet.created_at,
            refreshed_at=sheet.refreshed_at, submitted_at=sheet.submitted_at, uploaded_at=sheet.uploaded_at,
            uploaded_by_name=uploaded,
            receipt_ref=ref,
            receipt_count=len(recorded_blocks(sheet)) or (1 if ref else 0),
            difference=Decimal(sheet.summary["difference"]) if sheet.summary and sheet.summary.get("difference") is not None else None,
        )
        for sheet, created, uploaded, ref in rows
    ]
