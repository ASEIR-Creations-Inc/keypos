"""Every stock or money change leaves an audit entry booked to the right shift."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

from tests.conftest import sale_body


async def trail(client, shift_id: int, action: str) -> list[dict]:
    response = await client.get("/audit", params={"shift_id": shift_id, "action": action})
    return response.json()["entries"]


async def test_sale_entry_records_money_and_stock(client, shift, make_product):
    product = await make_product("10")
    sale = (await client.post("/transactions", json=sale_body((product["id"], "3", "2.00"), payment_cash="10.00"))).json()
    entry = next(e for e in await trail(client, shift["id"], "sale") if e["ref"] == sale["ref_number"])
    assert D(str(entry["cash"])) == D("6.00")
    [move] = entry["stock_movements"]
    assert (D(str(move["qty_before"])), D(str(move["qty_after"]))) == (D("10"), D("7"))


async def test_stock_adjustment_needs_a_reason_and_is_logged(client, shift, make_product):
    product = await make_product("10")
    refused = await client.post(f"/products/{product['id']}/adjust-stock", json={"counted_qty": "8", "reason": ""})
    assert refused.status_code == 422
    done = await client.post(f"/products/{product['id']}/adjust-stock", json={"counted_qty": "8", "reason": "count"})
    assert done.status_code == 200, done.text
    [entry] = [e for e in await trail(client, shift["id"], "stock_adjusted") if e["ref"] == product["sku"]]
    assert D(str(entry["stock_movements"][0]["qty_change"])) == D("-2")


async def test_csv_imports_are_audited(client, shift, make_product):
    product = await make_product("10", cost="2.00", sku="PYTEST-IMPORT")
    csv_text = ("sku,name,sell_price,cost_price,stock_qty,low_stock_threshold,is_active\n"
                f"PYTEST-IMPORT,{product['name']},4.00,2.50,25,,true\n"
                "PYTEST-NEW,Pytest new,6.00,3.00,7,,true\n")
    response = await client.post("/import/products", files={"file": ("p.csv", csv_text, "text/csv")})
    assert response.json()["errors"] == []
    [entry] = await trail(client, shift["id"], "products_imported")
    moves = {m["product_name"]: (D(str(m["qty_before"])), D(str(m["qty_after"]))) for m in entry["stock_movements"]}
    assert moves == {product["name"]: (D("10"), D("25")), "Pytest new": (D("0"), D("7"))}
    [changed] = entry["details"]["changed"]
    cost = changed["changes"]["cost_price"]
    assert (D(cost["from"]), D(cost["to"])) == (D("2.00"), D("2.50"))

    csv_text = "name,phone,email,credit_limit,balance\nPytest customer,5550001,,0,12.50\n"
    await client.post("/import/customers", files={"file": ("c.csv", csv_text, "text/csv")})
    [entry] = await trail(client, shift["id"], "customers_imported")
    assert D(str(entry["account"])) == D("12.50")


async def test_offline_sale_synced_without_a_shift_joins_the_next_one(client, make_product):
    product = await make_product("10")
    await client.post("/shifts/close", json={"closing_cash": 0})
    body = sale_body((product["id"], "1", "4.00"))
    rung_up = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    push = await client.post("/sync", json={"device_id": "till-late", "actions": [
        {"action_type": "sale", "payload": body, "client_ref": "till-late-1", "offline_created_at": rung_up},
    ]})
    assert push.json()["results"][0]["success"]

    shift = (await client.post("/shifts/open", json={"opening_float": 0})).json()
    [entry] = await trail(client, shift["id"], "offline_sales_attached")
    assert D(str(entry["amount"])) == D("4.00") and D(str(entry["cash"])) == D("0")
    report = (await client.get(f"/shifts/{shift['id']}/report")).json()["report"]
    assert report["offline_sales_count"] == 1
    assert D(str(report["cash_sales"])) == D("4.00")


async def test_product_edit_never_touches_stock_or_cost(client, shift, make_product):
    """Editing a product changes catalogue fields only; stock moves via adjust-stock, cost via purchases."""
    product = await make_product("16", cost="8800.00")
    unit = (await client.post("/units", json={"name": f"kg-{product['sku']}"})).json()
    edited = await client.put(f"/products/{product['id']}", json={
        "name": product["name"] + " 12kg", "sell_price": "0", "cost_price": 0, "stock_qty": 0,
        "unit_id": unit["id"], "category_id": None,
    })
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert (D(str(body["stock_qty"])), D(str(body["cost_price"]))) == (D("16"), D("8800"))
    assert body["unit_name"] == unit["name"]
    [entry] = [e for e in await trail(client, shift["id"], "product_edited") if e["ref"] == product["sku"]]
    assert entry["stock_movements"] == []
