"""Reports: only what is still on sale shows up in stock alerts; days are the shop's days."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from services.clock import day_range
from tests.conftest import sale_body


async def test_low_stock_leaves_out_deleted_products(client, make_product):
    kept = await make_product("1", low_stock_threshold="5")
    gone = await make_product("1", low_stock_threshold="5")
    assert (await client.delete(f"/products/{gone['id']}")).status_code in (200, 204)

    response = await client.get("/reports/low-stock")
    assert response.status_code == 200, response.text
    ids = {p["product_id"] for p in response.json()["products"]}
    assert kept["id"] in ids
    assert gone["id"] not in ids


def test_day_range_covers_whole_local_days():
    start, end = day_range("2026-10-08", "2026-10-09", ZoneInfo("Africa/Luanda"))
    assert start == datetime(2026, 10, 7, 23, 0, tzinfo=ZoneInfo("UTC"))
    assert end.astimezone(ZoneInfo("UTC")).replace(microsecond=0) == datetime(2026, 10, 9, 22, 59, 59, tzinfo=ZoneInfo("UTC"))


@pytest.fixture
async def luanda(client):
    """The shop's time zone set to Angola (UTC+1) for one test, then back."""
    before = (await client.get("/settings")).json()
    response = await client.put("/settings", json={**before, "timezone": "Africa/Luanda"})
    assert response.status_code == 200, response.text
    yield
    await client.put("/settings", json=before)


async def test_unknown_time_zone_is_refused(client):
    before = (await client.get("/settings")).json()
    assert before["timezone"] == "UTC"
    assert (await client.put("/settings", json={**before, "timezone": "Mars/Olympus"})).status_code == 422


async def test_saving_settings_without_timezone_keeps_it(client, luanda):
    """An older till that doesn't know the field must not reset it."""
    old_client_body = {"store_name": "Shop", "currency_symbol": "Kz", "tax_rate": "0", "low_stock_threshold": "5"}
    response = await client.put("/settings", json=old_client_body)
    assert response.status_code == 200, response.text
    assert response.json()["timezone"] == "Africa/Luanda"


async def test_reports_use_the_shop_day(client, db, shift, make_product, luanda):
    """A sale at 23:30 UTC on 1 Jan is 00:30 on 2 Jan in Luanda, so it belongs to 2 Jan."""
    product = await make_product("5")
    sale = await client.post("/transactions", json=sale_body((product["id"], "1", "10.00")))
    assert sale.status_code == 201, sale.text
    await db.execute(text("UPDATE transactions SET created_at = '2031-01-01 23:30:00+00' WHERE id = :id"),
                     {"id": sale.json()["id"]})
    await db.commit()

    async def count(day: str) -> int:
        r = await client.get("/reports/sales-summary", params={"from_date": day, "to_date": day})
        assert r.status_code == 200, r.text
        return r.json()["transaction_count"]

    assert await count("2031-01-01") == 0
    assert await count("2031-01-02") == 1

    tax = await client.get("/reports/tax", params={"from_date": "2031-01-01", "to_date": "2031-01-02"})
    assert tax.status_code == 200, tax.text
    assert [d["tax_date"] for d in tax.json()["daily_breakdown"]] == [str(date(2031, 1, 2))]
