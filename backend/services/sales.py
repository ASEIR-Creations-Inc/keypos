"""Sale and refund rules shared by the register API and offline sync.

A sale is never edited or cancelled after it is paid. To correct one, the whole receipt
is refunded and the items the customer keeps are rung up on a new receipt that points
back to it (reissue_of_id). Refunds are only possible while the sale's shift is open.

Money model for a sale:
    subtotal        = sum of round(sell_price * qty) over the lines
    discount_amount = line discounts + cart discount
    tax_amount      = round((subtotal - discount_amount) * tax_rate / 100)
    total_amount    = subtotal - discount_amount + tax_amount

Stock and customer rows are locked (SELECT ... FOR UPDATE, in id order) and re-read
before they change, and everything happens in the caller's database transaction.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import lazyload

from core.access import forbidden, has_flag
from models.customer import Customer
from models.product import Product
from models.shift import Shift, ShiftStatus
from models.audit import AuditLog
from models.transaction import Refund, Transaction, TransactionLine, TransactionStatus
from models.user import User
from schemas.transactions import TransactionCreate
from services.audit import log_event, record_stock
from services.clock import shop_today
from services.settings import load_settings

ZERO = Decimal("0")
CENT = Decimal("0.01")

REF_TABLES = {"TXN": "transactions", "PO": "purchase_orders", "RFD": "refunds"}


def to_cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


# ── Reference numbers ───────────────────────────────────────────

async def next_ref(db: AsyncSession, prefix: str) -> str:
    """Issue PREFIX-YYYYMMDD-NNNN atomically; the counter row stays locked until commit.

    The first number of a day continues after the highest one already stored, so
    numbering never collides with rows created before the counter existed.
    """
    day_key = f"{prefix}-{await shop_today(db):%Y%m%d}"
    table = REF_TABLES[prefix]
    result = await db.execute(
        text(
            f"""
            INSERT INTO ref_counters (key, value)
            VALUES (:key, (
                SELECT COALESCE(MAX(CAST(substring(ref_number FROM '([0-9]+)$') AS BIGINT)), 0) + 1
                FROM {table} WHERE ref_number LIKE :pattern
            ))
            ON CONFLICT (key) DO UPDATE SET value = ref_counters.value + 1
            RETURNING value
            """
        ),
        {"key": day_key, "pattern": f"{day_key}-%"},
    )
    return f"{day_key}-{result.scalar_one():04d}"


# ── Row locking ─────────────────────────────────────────────────

async def lock_products(db: AsyncSession, product_ids: set[int]) -> dict[int, Product]:
    result = await db.execute(
        select(Product)
        .options(lazyload("*"))
        .where(Product.id.in_(product_ids))
        .order_by(Product.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    products = {p.id: p for p in result.scalars().all()}
    missing = product_ids - products.keys()
    if missing:
        raise bad_request(f"Product {min(missing)} not found")
    return products


async def lock_customer(db: AsyncSession, customer_id: int) -> Customer:
    result = await db.execute(
        select(Customer)
        .options(lazyload("*"))
        .where(Customer.id == customer_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    customer = result.scalar_one_or_none()
    if not customer:
        raise bad_request(f"Customer {customer_id} not found")
    return customer


async def open_shift_for(db: AsyncSession, cashier_id: int) -> Shift | None:
    result = await db.execute(
        select(Shift).where(Shift.cashier_id == cashier_id, Shift.status == ShiftStatus.open)
    )
    return result.scalar_one_or_none()


async def require_open_shift(db: AsyncSession, cashier_id: int) -> Shift:
    shift = await open_shift_for(db, cashier_id)
    if not shift:
        raise bad_request("No open shift. Open a shift first.")
    return shift


# ── Stock and customer balance ──────────────────────────────────

def qty_by_product(lines: list[TransactionLine]) -> dict[int, Decimal]:
    totals: dict[int, Decimal] = {}
    for line in lines:
        totals[line.product_id] = totals.get(line.product_id, ZERO) + line.qty
    return totals


async def move_stock(
    db: AsyncSession,
    quantities: dict[int, Decimal],
    sign: int,
    entry: AuditLog,
    allow_negative: bool = False,
) -> None:
    """sign=-1 takes the quantities out of stock, sign=+1 puts them back; each change is logged on entry."""
    if not quantities:
        return
    products = await lock_products(db, set(quantities))
    for product_id, qty in quantities.items():
        product = products[product_id]
        if sign < 0 and not allow_negative and product.stock_qty < qty:
            raise bad_request(
                f"Insufficient stock for {product.name}: {product.stock_qty:g} available, {qty:g} needed"
            )
        record_stock(entry, product, product.stock_qty + sign * qty)


async def charge_account(db: AsyncSession, customer_id: int, amount: Decimal, enforce_limit: bool = True) -> None:
    """A credit limit of 0 means no limit."""
    customer = await lock_customer(db, customer_id)
    new_balance = (customer.balance or ZERO) + amount
    if enforce_limit and customer.credit_limit and new_balance > customer.credit_limit:
        raise bad_request(
            f"Credit limit exceeded. Limit: {customer.credit_limit}, "
            f"current balance: {customer.balance}, sale amount: {amount}"
        )
    customer.balance = new_balance


async def credit_account(db: AsyncSession, customer_id: int, amount: Decimal) -> Customer:
    customer = await lock_customer(db, customer_id)
    customer.balance = (customer.balance or ZERO) - amount
    return customer


# ── Totals ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class SaleTotals:
    subtotal: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal


def compute_totals(lines: list[TransactionLine], cart_discount: Decimal, tax_rate: Decimal) -> SaleTotals:
    subtotal = ZERO
    line_discounts = ZERO
    for line in lines:
        gross = to_cents(line.sell_price * line.qty)
        if line.discount > gross:
            raise bad_request(f"Discount on product {line.product_id} is larger than the line amount")
        line.line_total = gross - line.discount
        subtotal += gross
        line_discounts += line.discount
    if cart_discount > subtotal - line_discounts:
        raise bad_request("Discount is larger than the sale amount")
    discount_amount = line_discounts + cart_discount
    taxable = subtotal - discount_amount
    tax_amount = to_cents(taxable * tax_rate / Decimal("100"))
    return SaleTotals(subtotal, discount_amount, tax_amount, taxable + tax_amount)


def apply_totals(txn: Transaction, totals: SaleTotals) -> None:
    txn.subtotal = totals.subtotal
    txn.discount_amount = totals.discount_amount
    txn.tax_amount = totals.tax_amount
    txn.total_amount = totals.total_amount


def cart_discount_of(txn: Transaction) -> Decimal:
    return txn.discount_amount - sum((line.discount for line in txn.lines), ZERO)


# ── Sale ────────────────────────────────────────────────────────

async def find_client_sale(db: AsyncSession, device_id: str | None, client_ref: str | None) -> int | None:
    """Id of the sale a till already recorded under this checkout ref, if any."""
    if not client_ref:
        return None
    return (await db.execute(
        select(Transaction.id).where(
            Transaction.device_id == device_id,
            Transaction.client_ref == client_ref,
        )
    )).scalar_one_or_none()


def check_sale_permissions(seller: User, data: TransactionCreate, products: dict[int, Product]) -> None:
    """Discounts need can_discount. Charging other than a set catalog price needs
    can_edit_price; a product priced 0 has its price typed at the till, so that is not an edit."""
    discounted = data.discount_amount > 0 or any(l.discount > 0 for l in data.lines)
    if discounted and not has_flag(seller, "discount"):
        raise forbidden("You don't have permission to give discounts")
    repriced = any(
        (products[l.product_id].sell_price or ZERO) > 0 and l.sell_price != products[l.product_id].sell_price
        for l in data.lines
    )
    if repriced and not has_flag(seller, "edit_price"):
        raise forbidden("You don't have permission to change prices")


async def record_sale(
    db: AsyncSession,
    data: TransactionCreate,
    cashier_id: int,
    shift_id: int | None,
    offline: bool = False,
    offline_at: datetime | None = None,
    seller: User | None = None,
) -> Transaction:
    """Create a completed or held sale.

    Offline sales already happened at the till, so they may push stock negative and
    are not refused for going over a credit limit. offline_at is when the till rang
    the sale up; the receipt keeps that time even though it syncs later.
    seller: when given, discounts and price changes are checked against their permissions
    (offline sales are not: they already happened).
    """
    if not data.lines:
        raise bad_request("Transaction must have at least one line.")
    held = data.status == "held"
    original = await _reissue_source(db, data.reissue_of_id) if data.reissue_of_id else None

    products = await lock_products(db, {l.product_id for l in data.lines})
    if seller is not None:
        check_sale_permissions(seller, data, products)
    lines = [
        TransactionLine(
            product_id=l.product_id,
            qty=l.qty,
            original_price=products[l.product_id].sell_price,
            sell_price=l.sell_price,
            cost_price=products[l.product_id].cost_price,
            discount=l.discount,
            refunded_qty=ZERO,
        )
        for l in data.lines
    ]
    tax_rate = (await load_settings(db)).tax_rate
    totals = compute_totals(lines, data.discount_amount, tax_rate)

    paid = data.payment_cash + data.payment_card + data.payment_account
    change_given = paid - totals.total_amount
    if not held:
        if change_given < 0:
            raise bad_request("Insufficient payment")
        if change_given > data.payment_cash:
            raise bad_request("Only cash can be overpaid; card and account amounts must not exceed the total")
        if data.payment_account > 0 and not data.customer_id:
            raise bad_request("An account sale needs a customer")

    txn = Transaction(
        ref_number=await next_ref(db, "TXN"),
        cashier_id=cashier_id,
        shift_id=shift_id,
        customer_id=data.customer_id,
        status=TransactionStatus.held if held else TransactionStatus.completed,
        payment_cash=data.payment_cash,
        payment_card=data.payment_card,
        payment_account=data.payment_account,
        change_given=change_given,
        refunded_amount=ZERO,
        notes=data.notes,
        reissue_of_id=original.id if original else None,
        is_offline=offline,
        device_id=data.device_id,
        client_ref=data.client_ref,
        lines=lines,
    )
    if offline and offline_at:
        txn.created_at = offline_at
    apply_totals(txn, totals)
    db.add(txn)

    if held:
        log_event(
            db, "sale_held", f"Ticket {txn.ref_number} saved for later ({len(lines)} lines)",
            user_id=cashier_id, shift_id=shift_id, ref=txn.ref_number, amount=txn.total_amount,
            details={"lines": _lines_detail(lines, products)},
        )
        await db.flush()
        return txn

    cash_in = data.payment_cash - change_given
    summary = f"Sale {txn.ref_number}: {_money(txn.total_amount)}"
    if original:
        summary += f", re-issue of refunded {original.ref_number}"
    if offline:
        summary += " (offline)"
    entry = log_event(
        db, "sale", summary,
        user_id=cashier_id, shift_id=shift_id, ref=txn.ref_number, amount=txn.total_amount,
        cash=cash_in, card=data.payment_card, account=data.payment_account,
        details={
            "customer_id": data.customer_id,
            "reissue_of": original.ref_number if original else None,
            "subtotal": txn.subtotal, "discount": txn.discount_amount, "tax": txn.tax_amount,
            "cash_tendered": data.payment_cash, "change_given": change_given,
            "offline_at": offline_at.isoformat() if offline_at else None,
            "lines": _lines_detail(lines, products),
        },
    )
    await move_stock(db, qty_by_product(lines), -1, entry, allow_negative=offline)
    if data.payment_account > 0:
        await charge_account(db, data.customer_id, data.payment_account, enforce_limit=not offline)

    await db.flush()
    return txn


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


def _lines_detail(lines: list[TransactionLine], products: dict[int, Product]) -> list[dict]:
    return [
        {
            "product_id": l.product_id,
            "name": products[l.product_id].name if l.product_id in products else None,
            "qty": l.qty,
            "price": l.sell_price,
            "discount": l.discount,
            "total": l.line_total,
        }
        for l in lines
    ]


async def _reissue_source(db: AsyncSession, original_id: int) -> Transaction:
    """The refunded receipt a new sale replaces. Each refunded receipt can be re-issued once."""
    original = await db.get(Transaction, original_id)
    if not original:
        raise bad_request(f"Receipt {original_id} not found")
    if original.status != TransactionStatus.refunded:
        raise bad_request(f"{original.ref_number} has not been refunded, so it cannot be re-issued")
    already = (await db.execute(
        select(Transaction.ref_number).where(
            Transaction.reissue_of_id == original_id,
            Transaction.status.in_([TransactionStatus.completed, TransactionStatus.refunded]),
        )
    )).scalars().first()
    if already:
        raise bad_request(f"{original.ref_number} was already re-issued as {already}")
    return original


# ── Refund ──────────────────────────────────────────────────────

async def refund_sale(db: AsyncSession, txn: Transaction, user_id: int, reason: str) -> Refund:
    """Refund the whole receipt: all stock goes back and the money goes back the way it was paid.

    Only possible while the shift the sale was made in is still open; the refund is booked
    to that shift, so its Z-report shows both the sale and the refund.
    """
    if txn.status == TransactionStatus.refunded:
        raise bad_request(f"{txn.ref_number} has already been refunded")
    if txn.status != TransactionStatus.completed:
        raise bad_request(f"Only completed sales can be refunded ({txn.ref_number} is {txn.status.value})")
    shift = await db.get(Shift, txn.shift_id) if txn.shift_id else None
    if not shift or shift.status != ShiftStatus.open:
        raise bad_request(
            f"The shift for {txn.ref_number} is closed, so it can no longer be refunded"
        )

    cash = txn.payment_cash - txn.change_given
    card = txn.payment_card
    account = txn.payment_account
    refund = Refund(
        ref_number=await next_ref(db, "RFD"),
        transaction_id=txn.id,
        shift_id=shift.id,
        created_by=user_id,
        amount=txn.total_amount,
        tax_amount=txn.tax_amount,
        cost_amount=sum((l.cost_price * l.qty for l in txn.lines), ZERO),
        refund_cash=cash,
        refund_card=card,
        refund_account=account,
        reason=reason,
    )
    db.add(refund)

    entry = log_event(
        db, "refund", f"Refund {refund.ref_number} of {txn.ref_number}: {_money(txn.total_amount)}. Reason: {reason}",
        user_id=user_id, shift_id=shift.id, ref=refund.ref_number, amount=-txn.total_amount,
        cash=-cash, card=-card, account=-account,
        details={"sale": txn.ref_number, "reason": reason, "customer_id": txn.customer_id},
    )
    await move_stock(db, qty_by_product(txn.lines), +1, entry)
    if account > 0 and txn.customer_id:
        await credit_account(db, txn.customer_id, account)

    for line in txn.lines:
        line.refunded_qty = line.qty
    txn.refunded_amount = txn.total_amount
    txn.status = TransactionStatus.refunded

    await db.flush()
    return refund
