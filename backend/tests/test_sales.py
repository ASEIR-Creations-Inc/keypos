"""Register sales, refunds and repeat protection, through the real API and database."""
import asyncio
from decimal import Decimal as D

from tests.conftest import sale_body, stock_of


async def test_every_line_deducts_stock(client, shift, make_product):
    a, b = await make_product("10"), await make_product("10")
    response = await client.post("/transactions", json=sale_body((a["id"], "2", "5.00"), (b["id"], "3", "1.00")))
    assert response.status_code == 201, response.text
    assert await stock_of(client, a["id"]) == D("8")
    assert await stock_of(client, b["id"]) == D("7")


async def test_online_sale_cannot_oversell(client, shift, make_product):
    product = await make_product("1")
    response = await client.post("/transactions", json=sale_body((product["id"], "2", "5.00")))
    assert response.status_code == 400
    assert await stock_of(client, product["id"]) == D("1")


async def test_concurrent_sales_never_oversell(client, shift, make_product):
    product = await make_product("5")
    replies = await asyncio.gather(*[
        client.post("/transactions", json=sale_body((product["id"], "1", "1.00"))) for _ in range(8)
    ])
    assert sorted(r.status_code for r in replies).count(201) == 5
    assert await stock_of(client, product["id"]) == D("0")


async def test_sale_needs_an_open_shift(client, make_product):
    product = await make_product()
    await client.post("/shifts/close", json={"closing_cash": 0})
    response = await client.post("/transactions", json=sale_body((product["id"], "1", "1.00")))
    assert response.status_code in (400, 404, 409)


async def test_repeated_checkout_ref_returns_the_first_sale(client, shift, make_product):
    product = await make_product("10")
    body = sale_body((product["id"], "1", "2.00"), device_id="till-1", client_ref="till-1-abc")
    first, again = [await client.post("/transactions", json=body) for _ in range(2)]
    assert first.json()["id"] == again.json()["id"]
    other_till = await client.post("/transactions", json={**body, "device_id": "till-2"})
    assert other_till.json()["id"] != first.json()["id"]
    assert await stock_of(client, product["id"]) == D("8")


async def test_queued_copy_of_a_recorded_sale_is_not_recorded_again(client, shift, make_product):
    product = await make_product("10")
    body = sale_body((product["id"], "1", "2.00"), device_id="till-9", client_ref="till-9-lost")
    recorded = (await client.post("/transactions", json=body)).json()
    push = await client.post("/sync", json={"device_id": "till-9", "actions": [
        {"action_type": "sale", "payload": body, "client_ref": "till-9-lost"},
    ]})
    assert push.json()["results"][0]["record_id"] == recorded["id"]
    assert await stock_of(client, product["id"]) == D("9")


async def test_refund_returns_everything_and_needs_a_reason(client, shift, make_product):
    product = await make_product("10")
    sale = (await client.post("/transactions", json=sale_body((product["id"], "4", "2.50")))).json()
    assert (await client.post(f"/transactions/{sale['id']}/refund", json={"reason": "  "})).status_code == 422

    refunded = await client.post(f"/transactions/{sale['id']}/refund", json={"reason": "wrong item"})
    assert refunded.status_code == 200, refunded.text
    body = refunded.json()
    assert body["status"] == "refunded"
    assert body["refund"]["ref_number"].startswith("RFD-")
    assert D(str(body["refund"]["amount"])) == D("10.00")
    assert await stock_of(client, product["id"]) == D("10")
    assert (await client.post(f"/transactions/{sale['id']}/refund", json={"reason": "again"})).status_code == 400


async def test_no_refunds_once_the_shift_is_closed(client, shift, make_product):
    product = await make_product("10")
    sale = (await client.post("/transactions", json=sale_body((product["id"], "1", "2.00")))).json()
    await client.post("/shifts/close", json={"closing_cash": 0})
    await client.post("/shifts/open", json={"opening_float": 0})
    response = await client.post(f"/transactions/{sale['id']}/refund", json={"reason": "too late"})
    assert response.status_code == 400
    assert await stock_of(client, product["id"]) == D("9")


async def test_account_sale_and_refund_move_the_customer_balance(client, shift, make_product):
    product = await make_product("10")
    customer = (await client.post("/customers", json={"name": "Account", "credit_limit": "0"})).json()
    body = sale_body((product["id"], "2", "15.00"), customer_id=customer["id"], payment_cash="0", payment_account="30.00")
    sale = (await client.post("/transactions", json=body)).json()
    assert D(str((await client.get(f"/customers/{customer['id']}")).json()["balance"])) == D("30.00")
    await client.post(f"/transactions/{sale['id']}/refund", json={"reason": "returned"})
    assert D(str((await client.get(f"/customers/{customer['id']}")).json()["balance"])) == D("0.00")


async def test_z_report_counts_sales_refunds_and_expected_cash(client, shift, make_product):
    product = await make_product("10")
    kept = (await client.post("/transactions", json=sale_body((product["id"], "1", "7.00"),
                                                              payment_cash="10.00"))).json()
    returned = (await client.post("/transactions", json=sale_body((product["id"], "1", "3.00")))).json()
    await client.post(f"/transactions/{returned['id']}/refund", json={"reason": "faulty"})
    z = (await client.post("/shifts/close", json={"closing_cash": "107.00"})).json()
    report = z["report"]
    assert D(str(report["expected_cash"])) == D("107.00")
    assert report["refund_count"] == 1
    assert [r["sale_ref"] for r in z["refunds"]] == [returned["ref_number"]]
    assert D(str(z["shift"]["variance"])) == D("0.00")
    assert kept["ref_number"] != returned["ref_number"]
