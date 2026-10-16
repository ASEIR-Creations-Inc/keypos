"""Purchase orders: draft responses name their products, posting applies WAC and stock."""
from decimal import Decimal as D

from tests.conftest import sale_body, stock_of


async def test_draft_edit_and_post(client, shift, make_product):
    a, b = await make_product("10", cost="5.00"), await make_product("0", cost="5.00")
    oversold = await client.post("/sync", json={"device_id": "till-po", "actions": [
        {"action_type": "sale", "payload": sale_body((b["id"], "2", "9.00")), "client_ref": "till-po-1"},
    ]})
    assert oversold.json()["results"][0]["success"]
    assert await stock_of(client, b["id"]) == D("-2")
    lines = [{"product_id": a["id"], "qty": "10", "unit_cost": "6.00"},
             {"product_id": b["id"], "qty": "10", "unit_cost": "6.00"}]
    created = await client.post("/purchases", json={"lines": lines})
    assert created.status_code == 201, created.text
    po = created.json()
    assert {l["product_name"] for l in po["lines"]} == {a["name"], b["name"]}
    assert D(str(po["total_amount"])) == D("120.00")

    edited = await client.put(f"/purchases/{po['id']}", json={"lines": lines[:1]})
    assert edited.status_code == 200, edited.text
    assert [l["product_name"] for l in edited.json()["lines"]] == [a["name"]]

    edited = await client.put(f"/purchases/{po['id']}", json={"lines": lines})
    posted = await client.post(f"/purchases/{po['id']}/post")
    assert posted.status_code == 200, posted.text
    assert posted.json()["status"] == "posted"
    assert await stock_of(client, a["id"]) == D("20")
    assert await stock_of(client, b["id"]) == D("8")
    costs = {p["id"]: D(str(p["cost_price"])) for p in [(await client.get(f"/products/{i}")).json() for i in (a["id"], b["id"])]}
    assert costs == {a["id"]: D("5.5"), b["id"]: D("6")}
    assert (await client.put(f"/purchases/{po['id']}", json={"lines": lines})).status_code == 400


async def test_unknown_product_is_refused(client, shift):
    response = await client.post("/purchases", json={"lines": [{"product_id": 999999, "qty": "1", "unit_cost": "1"}]})
    assert response.status_code == 404
