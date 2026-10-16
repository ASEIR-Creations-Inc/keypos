import csv
import io
import re
from datetime import datetime, date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_active_user
from core.access import require_access
from database import get_db
from models.user import User
from models.product import Product, Category, Unit
from models.customer import Customer
from models.transaction import Transaction, TransactionStatus
from models.expense import Expense
from models.purchase import Supplier
from schemas.importexport import ImportSummaryResponse
from services.audit import active_shift_id, changed_fields, log_event, record_stock
from services.clock import day_end, day_start, parse_day, shop_zone

router = APIRouter(tags=["import-export"])

# ── Helpers ─────────────────────────────────────────────────────────


def _safe_float(value: str | None, default: float = 0.0) -> float:
    """Convert a CSV field to float safely."""
    if value is None or value.strip() == "":
        return default
    try:
        return float(value.strip())
    except ValueError:
        return default


def _safe_str(value: str | None) -> str:
    """Convert a CSV field to string, stripped."""
    if value is None:
        return ""
    return value.strip()


def _safe_bool(value: str | None) -> bool:
    """Convert a CSV field to bool."""
    if value is None:
        return True
    v = value.strip().lower()
    return v not in ("0", "false", "no", "")


def _read_csv_dict(file: UploadFile) -> tuple[list[dict], list[str]]:
    """Read uploaded CSV and return list of dicts. Returns (rows, errors)."""
    errors: list[str] = []
    try:
        contents = file.file.read().decode("utf-8")
    except UnicodeDecodeError:
        return [], ["File must be UTF-8 encoded CSV"]

    reader = csv.DictReader(io.StringIO(contents))
    if not reader.fieldnames:
        return [], ["CSV file is empty or has no header row"]

    rows = []
    for i, row in enumerate(reader, start=2):  # row 2 = first data row
        # strip whitespace from keys and values
        cleaned = {k.strip(): (v.strip() if v else "") for k, v in row.items()}
        rows.append(cleaned)

    return rows, errors


def _build_csv_response(
    fieldnames: list[str],
    rows_iter,
    filename: str,
) -> StreamingResponse:
    """Stream a CSV back to the client."""

    def generate():
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        yield buffer.getvalue()
        buffer.truncate(0)
        buffer.seek(0)

        for row in rows_iter:
            writer.writerow(row)
            yield buffer.getvalue()
            buffer.truncate(0)
            buffer.seek(0)

    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _date_tag() -> str:
    """Current date as YYYYMMDD for filenames."""
    return datetime.now().strftime("%Y%m%d")


# ── Helpers for CSV row generation ─────────────────────────────────
def _product_row_text(p: Product) -> dict:
    return {
        "sku": p.sku or "",
        "barcode": p.barcode or "",
        "name": p.name,
        "category": p.category.name if p.category else "",
        "unit": p.unit.name if p.unit else "",
        "sell_price": str(p.sell_price),
        "cost_price": str(p.cost_price),
        "stock_qty": str(p.stock_qty),
        "low_stock_threshold": str(p.low_stock_threshold),
        "is_active": str(p.is_active),
    }


def _customer_row_text(c: Customer) -> dict:
    return {
        "name": c.name,
        "phone": c.phone or "",
        "email": c.email or "",
        "credit_limit": str(c.credit_limit),
        "balance": str(c.balance),
    }


def _supplier_row_text(s) -> dict:
    return {
        "name": s.name,
        "contact": s.contact or "",
        "phone": s.phone or "",
        "address": s.address or "",
    }


# ════════════════════════════════════════════════════════════════════
# EXPORT ENDPOINTS
# ════════════════════════════════════════════════════════════════════

PRODUCT_EXPORT_COLUMNS = [
    "sku", "barcode", "name", "category", "unit",
    "sell_price", "cost_price", "stock_qty",
    "low_stock_threshold", "is_active",
]


@router.get("/export/products")
async def export_products(
    user: User = Depends(require_access("inventory", "full")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Product).options(
            selectinload(Product.category),
            selectinload(Product.unit),
        ).order_by(Product.id)
    )
    products = result.scalars().all()

    def rows_gen():
        for p in products:
            yield _product_row_text(p)

    return _build_csv_response(PRODUCT_EXPORT_COLUMNS, rows_gen(), f"products_{_date_tag()}.csv")


CUSTOMER_EXPORT_COLUMNS = ["name", "phone", "email", "credit_limit", "balance"]


@router.get("/export/customers")
async def export_customers(
    user: User = Depends(require_access("customers", "full")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Customer).order_by(Customer.id))
    customers = result.scalars().all()

    return _build_csv_response(
        CUSTOMER_EXPORT_COLUMNS,
        (_customer_row_text(c) for c in customers),
        f"customers_{_date_tag()}.csv",
    )


SUPPLIER_EXPORT_COLUMNS = ["name", "contact", "phone", "address"]


@router.get("/export/suppliers")
async def export_suppliers(
    user: User = Depends(require_access("purchases", "full")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Supplier).order_by(Supplier.id))
    suppliers = result.scalars().all()

    return _build_csv_response(
        SUPPLIER_EXPORT_COLUMNS,
        (_supplier_row_text(s) for s in suppliers),
        f"suppliers_{_date_tag()}.csv",
    )


SALES_EXPORT_COLUMNS = [
    "ref_number", "date", "cashier", "customer",
    "subtotal", "discount", "tax", "total",
    "payment_cash", "payment_card", "payment_account",
    "status",
]


@router.get("/export/sales")
async def export_sales(
    from_date: str = Query(default=None),
    to_date: str = Query(default=None),
    user: User = Depends(require_access("reports", "full")),
    db: AsyncSession = Depends(get_db),
):
    zone = await shop_zone(db)
    f = day_start(parse_day(from_date), zone) if from_date else None
    t = day_end(parse_day(to_date), zone) if to_date else None

    stmt = (
        select(Transaction)
        .options(
            selectinload(Transaction.cashier),
            selectinload(Transaction.customer),
        )
        .order_by(Transaction.created_at)
    )
    filters = []
    if f is not None:
        filters.append(Transaction.created_at >= f)
    if t is not None:
        filters.append(Transaction.created_at <= t)
    if filters:
        stmt = stmt.where(and_(*filters))
    result = await db.execute(stmt)
    transactions = result.scalars().all()

    def rows_gen():
        for txn in transactions:
            yield {
                "ref_number": txn.ref_number,
                "date": txn.created_at.astimezone(zone).strftime("%Y-%m-%d %H:%M:%S"),
                "cashier": txn.cashier.name if txn.cashier else "",
                "customer": txn.customer.name if txn.customer else "",
                "subtotal": str(txn.subtotal),
                "discount": str(txn.discount_amount),
                "tax": str(txn.tax_amount),
                "total": str(txn.total_amount),
                "payment_cash": str(txn.payment_cash),
                "payment_card": str(txn.payment_card),
                "payment_account": str(txn.payment_account),
                "status": txn.status.value if txn.status else "",
            }

    return _build_csv_response(SALES_EXPORT_COLUMNS, rows_gen(), f"sales_{_date_tag()}.csv")


EXPENSE_EXPORT_COLUMNS = ["date", "category", "amount", "description"]


@router.get("/export/expenses")
async def export_expenses(
    from_date: str = Query(default=None),
    to_date: str = Query(default=None),
    user: User = Depends(require_access("expenses", "full")),
    db: AsyncSession = Depends(get_db),
):
    f = None
    t = None
    if from_date:
        try:
            f = datetime.fromisoformat(from_date).date()
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid from_date format: {exc}")
    if to_date:
        try:
            t = datetime.fromisoformat(to_date).date()
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid to_date format: {exc}")

    stmt = (
        select(Expense)
        .options(selectinload(Expense.category))
        .order_by(Expense.expense_date)
    )
    filters = []
    if f is not None:
        filters.append(Expense.expense_date >= f)
    if t is not None:
        filters.append(Expense.expense_date <= t)
    if filters:
        stmt = stmt.where(and_(*filters))
    result = await db.execute(stmt)
    expenses = result.scalars().all()

    def rows_gen():
        for exp in expenses:
            yield {
                "date": exp.expense_date.strftime("%Y-%m-%d"),
                "category": exp.category.name if exp.category else "",
                "amount": str(exp.amount),
                "description": exp.description or "",
            }

    return _build_csv_response(EXPENSE_EXPORT_COLUMNS, rows_gen(), f"expenses_{_date_tag()}.csv")


# ════════════════════════════════════════════════════════════════════
# TEMPLATE ENDPOINTS  (single example row so user knows the format)
# ════════════════════════════════════════════════════════════════════


@router.get("/templates/products")
async def template_products(
    user: User = Depends(get_current_active_user),
):
    example = [{
        "sku": "PROD-001",
        "barcode": "1234567890123",
        "name": "Example Product",
        "category": "General",
        "unit": "pcs",
        "sell_price": "10.00",
        "cost_price": "5.00",
        "stock_qty": "100",
        "low_stock_threshold": "10",
        "is_active": "True",
    }]
    return _build_csv_response(PRODUCT_EXPORT_COLUMNS, iter(example), "products_import_template.csv")


@router.get("/templates/customers")
async def template_customers(
    user: User = Depends(get_current_active_user),
):
    example = [{
        "name": "John Customer",
        "phone": "0917-123-4567",
        "email": "john@example.com",
        "credit_limit": "5000.00",
        "balance": "0.00",
    }]
    return _build_csv_response(CUSTOMER_EXPORT_COLUMNS, iter(example), "customers_import_template.csv")


@router.get("/templates/suppliers")
async def template_suppliers(
    user: User = Depends(get_current_active_user),
):
    example = [{
        "name": "Acme Supplies",
        "contact": "Jane Doe",
        "phone": "0917-987-6543",
        "address": "123 Business St, Manila",
    }]
    return _build_csv_response(SUPPLIER_EXPORT_COLUMNS, iter(example), "suppliers_import_template.csv")


# ════════════════════════════════════════════════════════════════════
# IMPORT ENDPOINTS
# ════════════════════════════════════════════════════════════════════


@router.post("/import/products", response_model=ImportSummaryResponse)
async def import_products(
    file: UploadFile = File(...),
    user: User = Depends(require_access("inventory", "full")),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a .csv")

    rows, parse_errors = _read_csv_dict(file)
    if parse_errors:
        return ImportSummaryResponse(
            imported_count=0, updated_count=0, skipped_count=0, errors=parse_errors,
        )

    imported, updated, skipped, errors = 0, 0, 0, []
    stock_targets: list[tuple[Product, Decimal]] = []
    created_products: list[Product] = []
    changed_products: list[dict] = []

    try:
        for i, row in enumerate(rows, start=2):
            name = _safe_str(row.get("name"))
            sell_price_str = row.get("sell_price", "").strip()
            sku = _safe_str(row.get("sku"))

            # Skip if missing required fields
            if not name or not sell_price_str:
                skipped += 1
                reason = "missing name" if not name else "missing sell_price"
                errors.append(f"Row {i}: skipped — {reason}")
                continue

            try:
                sell_price = Decimal(str(_safe_float(sell_price_str)))
                cost_price = Decimal(str(_safe_float(row.get("cost_price", "0"))))
                # Ensure cost_price is not negative
                if cost_price < 0:
                    cost_price = Decimal("0")
            except Exception as e:
                skipped += 1
                errors.append(f"Row {i}: invalid number — {e}")
                continue

            # Look up existing by SKU
            if sku:
                existing = await db.execute(select(Product).where(Product.sku == sku))
                product = existing.scalar_one_or_none()
            else:
                product = None

            if product:
                # UPDATE — stock is set at the end so it is recorded as a stock movement
                updates = {
                    "name": name,
                    "barcode": _safe_str(row.get("barcode")) or product.barcode,
                    "sell_price": sell_price,
                    "cost_price": cost_price,
                    "is_active": _safe_bool(row.get("is_active")),
                }
                if row.get("low_stock_threshold", "").strip():
                    updates["low_stock_threshold"] = Decimal(str(_safe_float(row.get("low_stock_threshold"))))
                changes = changed_fields(product, updates)
                for field, change in changes.items():
                    setattr(product, field, change["to"])
                if row.get("stock_qty", "").strip():
                    stock_targets.append((product, Decimal(str(_safe_float(row.get("stock_qty"))))))
                if changes:
                    changed_products.append({"product_id": product.id, "sku": product.sku, "changes": changes})
                # category and unit — look up and set if provided
                cat_name = _safe_str(row.get("category"))
                if cat_name:
                    cat_res = await db.execute(select(Category).where(Category.name == cat_name))
                    cat = cat_res.scalar_one_or_none()
                    if cat:
                        product.category_id = cat.id
                unit_name = _safe_str(row.get("unit"))
                if unit_name:
                    unit_res = await db.execute(select(Unit).where(Unit.name == unit_name))
                    unit_obj = unit_res.scalar_one_or_none()
                    if unit_obj:
                        product.unit_id = unit_obj.id
                updated += 1
            else:
                # CREATE — need category and unit
                cat_name = _safe_str(row.get("category"))
                unit_name = _safe_str(row.get("unit"))

                cat = None
                if cat_name:
                    cat_res = await db.execute(select(Category).where(Category.name == cat_name))
                    cat = cat_res.scalar_one_or_none()
                    if not cat:
                        cat = Category(name=cat_name, color="#CCCCCC")
                        db.add(cat)
                        await db.flush()

                unit_obj = None
                if unit_name:
                    unit_res = await db.execute(select(Unit).where(Unit.name == unit_name))
                    unit_obj = unit_res.scalar_one_or_none()
                    if not unit_obj:
                        unit_obj = Unit(name=unit_name)
                        db.add(unit_obj)
                        await db.flush()

                new_product = Product(
                    sku=sku or None,
                    barcode=_safe_str(row.get("barcode")) or None,
                    name=name,
                    category_id=cat.id if cat else None,
                    unit_id=unit_obj.id if unit_obj else None,
                    sell_price=sell_price,
                    cost_price=cost_price,
                    stock_qty=Decimal("0"),
                    low_stock_threshold=Decimal(str(_safe_float(row.get("low_stock_threshold", "0")))),
                    is_active=_safe_bool(row.get("is_active")),
                )
                db.add(new_product)
                stock_targets.append((new_product, Decimal(str(_safe_float(row.get("stock_qty", "0"))))))
                created_products.append(new_product)
                imported += 1

        await db.flush()
        if imported or updated:
            entry = log_event(
                db, "products_imported",
                f"CSV import {file.filename}: {imported} products created, {updated} updated",
                user_id=user.id, shift_id=await active_shift_id(db, user.id), ref=file.filename,
                details={
                    "created": [
                        {"product_id": p.id, "sku": p.sku, "name": p.name,
                         "sell_price": p.sell_price, "cost_price": p.cost_price}
                        for p in created_products
                    ],
                    "changed": changed_products,
                },
            )
            for product, qty in stock_targets:
                record_stock(entry, product, qty)
        await db.commit()
    except Exception as e:
        await db.rollback()
        errors.append(f"Import failed: {str(e)}")

    return ImportSummaryResponse(
        imported_count=imported,
        updated_count=updated,
        skipped_count=skipped,
        errors=errors,
    )


@router.post("/import/customers", response_model=ImportSummaryResponse)
async def import_customers(
    file: UploadFile = File(...),
    user: User = Depends(require_access("customers", "full")),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a .csv")

    rows, parse_errors = _read_csv_dict(file)
    if parse_errors:
        return ImportSummaryResponse(
            imported_count=0, updated_count=0, skipped_count=0, errors=parse_errors,
        )

    imported, updated, skipped, errors = 0, 0, 0, []
    balance_changes: list[dict] = []

    for i, row in enumerate(rows, start=2):
        name = _safe_str(row.get("name"))
        phone = _safe_str(row.get("phone"))

        if not name:
            skipped += 1
            errors.append(f"Row {i}: skipped — missing name")
            continue

        # Match by phone if phone is provided
        existing = None
        if phone:
            result = await db.execute(select(Customer).where(Customer.phone == phone))
            existing = result.scalar_one_or_none()

        if existing:
            # UPDATE
            existing.name = name
            existing.email = _safe_str(row.get("email")) or existing.email
            cl_str = row.get("credit_limit", "").strip()
            bal_str = row.get("balance", "").strip()
            if cl_str:
                try:
                    existing.credit_limit = Decimal(str(_safe_float(cl_str)))
                except Exception as e:
                    errors.append(f"Row {i}: invalid credit_limit — {e}")
            if bal_str:
                try:
                    new_balance = Decimal(str(_safe_float(bal_str)))
                    if new_balance != existing.balance:
                        balance_changes.append({
                            "customer_id": existing.id, "name": name,
                            "from": existing.balance, "to": new_balance,
                        })
                        existing.balance = new_balance
                except Exception as e:
                    errors.append(f"Row {i}: invalid balance — {e}")
            updated += 1
        else:
            # CREATE
            opening = Decimal(str(_safe_float(row.get("balance", "0"))))
            new_customer = Customer(
                name=name,
                phone=phone or None,
                email=_safe_str(row.get("email")) or None,
                credit_limit=Decimal(str(_safe_float(row.get("credit_limit", "0")))),
                balance=opening,
            )
            db.add(new_customer)
            if opening:
                balance_changes.append({"customer_id": None, "name": name, "from": Decimal("0"), "to": opening})
            imported += 1

    if imported or updated:
        balance_delta = sum((c["to"] - c["from"] for c in balance_changes), Decimal("0"))
        log_event(
            db, "customers_imported",
            f"CSV import {file.filename}: {imported} customers created, {updated} updated, "
            f"{len(balance_changes)} account balances set",
            user_id=user.id, shift_id=await active_shift_id(db, user.id), ref=file.filename,
            account=balance_delta,
            details={"balance_changes": balance_changes},
        )
    await db.commit()
    return ImportSummaryResponse(
        imported_count=imported,
        updated_count=updated,
        skipped_count=skipped,
        errors=errors,
    )


@router.post("/import/suppliers", response_model=ImportSummaryResponse)
async def import_suppliers(
    file: UploadFile = File(...),
    user: User = Depends(require_access("purchases", "full")),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a .csv")

    rows, parse_errors = _read_csv_dict(file)
    if parse_errors:
        return ImportSummaryResponse(
            imported_count=0, updated_count=0, skipped_count=0, errors=parse_errors,
        )

    imported, updated, skipped, errors = 0, 0, 0, []

    try:
        for i, row in enumerate(rows, start=2):
            name = _safe_str(row.get("name"))

            if not name:
                skipped += 1
                errors.append(f"Row {i}: skipped — missing name")
                continue

            # Match by name
            result = await db.execute(select(Supplier).where(Supplier.name == name))
            existing = result.scalar_one_or_none()

            if existing:
                # UPDATE
                existing.contact = _safe_str(row.get("contact")) or existing.contact
                existing.phone = _safe_str(row.get("phone")) or existing.phone
                existing.address = _safe_str(row.get("address")) or existing.address
                updated += 1
            else:
                # CREATE
                new_supplier = Supplier(
                    name=name,
                    contact=_safe_str(row.get("contact")) or None,
                    phone=_safe_str(row.get("phone")) or None,
                    address=_safe_str(row.get("address")) or None,
                )
                db.add(new_supplier)
                imported += 1

        await db.commit()
    except Exception as e:
        await db.rollback()
        errors.append(f"Import failed: {str(e)}")

    return ImportSummaryResponse(
        imported_count=imported,
        updated_count=updated,
        skipped_count=skipped,
        errors=errors,
    )
