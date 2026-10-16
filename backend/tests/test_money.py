"""Pure money rules: sale totals and weighted average cost."""
from decimal import Decimal as D

import pytest
from fastapi import HTTPException

from models.transaction import TransactionLine
from routers.purchases import _calc_wac
from services.sales import compute_totals


def line(qty: str, price: str, discount: str = "0", product_id: int = 1) -> TransactionLine:
    return TransactionLine(product_id=product_id, qty=D(qty), sell_price=D(price), discount=D(discount))


def test_totals_without_tax_or_discount():
    totals = compute_totals([line("2", "10.00"), line("1", "5.50")], D("0"), D("0"))
    assert (totals.subtotal, totals.discount_amount, totals.tax_amount, totals.total_amount) == (
        D("25.50"), D("0"), D("0"), D("25.50"))


def test_tax_is_charged_after_line_and_cart_discounts():
    lines = [line("2", "10.00", discount="2.00"), line("1", "10.00")]
    totals = compute_totals(lines, D("3.00"), D("10"))
    assert totals.subtotal == D("30.00")
    assert totals.discount_amount == D("5.00")
    assert totals.tax_amount == D("2.50")
    assert totals.total_amount == D("27.50")
    assert [l.line_total for l in lines] == [D("18.00"), D("10.00")]


def test_tax_rounds_half_up_to_the_cent():
    assert compute_totals([line("1", "100.05")], D("0"), D("10")).tax_amount == D("10.01")


def test_line_amounts_round_to_the_cent():
    assert compute_totals([line("0.333", "3.00")], D("0"), D("0")).subtotal == D("1.00")


@pytest.mark.parametrize("lines, cart", [
    ([line("1", "5.00", discount="5.01")], D("0")),
    ([line("1", "5.00", discount="1.00")], D("4.01")),
])
def test_discounts_larger_than_the_amount_are_refused(lines, cart):
    with pytest.raises(HTTPException) as err:
        compute_totals(lines, cart, D("0"))
    assert err.value.status_code == 400


@pytest.mark.parametrize("stock, cost, qty, unit_cost, expected", [
    (D("10"), D("5"), D("10"), D("6"), D("5.5")),
    (D("0"), D("5"), D("4"), D("6"), D("6")),
    (D("-2"), D("5"), D("10"), D("6"), D("6")),
    (D("3"), D("1"), D("0"), D("9"), D("1")),
    (D("1"), D("1"), D("2"), D("2"), D("1.6667")),
])
def test_weighted_average_cost(stock, cost, qty, unit_cost, expected):
    assert _calc_wac(stock, cost, qty, unit_cost) == expected
