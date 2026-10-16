"""Where things live in a day sheet, and the values a person types into one.

book.py writes these cells and parse.py reads them back; both use this file so the
two can't drift apart.
"""
from dataclasses import dataclass, field
from decimal import Decimal

TEMPLATE_VERSION = 4
ROWS = 300
FIRST = 2
LAST = FIRST + ROWS - 1

SALES_PRODUCT, SALES_QTY, SALES_PRICE = "B", "C", "D"
EXP_CATEGORY, EXP_AMOUNT, EXP_DESCRIPTION, EXP_PAID_FROM = "B", "C", "D", "E"
CARD_CELL, COUNTED_CELL, START_CELL = "B8", "B12", "B14"

PRODUCTS_TAB, LISTS_TAB, META_TAB = "Products", "Lists", "Meta"

Raw = str | int | float | None


@dataclass(frozen=True)
class CatalogItem:
    id: int
    name: str
    fixed_price: Decimal
    stock: Decimal


@dataclass(frozen=True)
class SalesInput:
    row: int
    product: str
    qty: Raw
    price: Raw  # None: not typed, so the sheet shows the product's fixed price
    product_id: int | None = None  # set when the product was picked (Sheet app), not typed
    block: int | None = None  # Sheet app with several blocks; row is then the line within its block, + 1
    pay: str = "cash"
    card: Raw = None  # the card part of a split payment


@dataclass(frozen=True)
class ExpenseInput:
    row: int
    category: str
    amount: Raw
    description: str
    paid_from: str


@dataclass
class SheetInputs:
    sales: list[SalesInput] = field(default_factory=list)
    expenses: list[ExpenseInput] = field(default_factory=list)
    card: Raw = None
    counted: Raw = None
    start: Raw = None


@dataclass(frozen=True)
class SheetMeta:
    token: str
    code: str
    version: int
    lang: str
