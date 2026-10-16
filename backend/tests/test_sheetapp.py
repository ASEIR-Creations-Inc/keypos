"""KEYPOS Sheet app: a Day Sheet account fills in a sheet, sends it, and an approver records it."""
import uuid
from datetime import date, timedelta
from decimal import Decimal

from tests.conftest import stock_of
from tests.test_daysheets import category


def sheet_body(*lines: tuple[dict, str, str], card="0", counted=None, expenses=(), lang="pt", **extra) -> dict:
    """lines are (product, qty, price); counted defaults to the cash due, so the sheet balances."""
    total = sum((Decimal(q) * Decimal(p) for _, q, p in lines), Decimal("0"))
    return {
        "lang": lang,
        "content": {
            "lines": [{"product_id": prod["id"], "product": prod["name"], "qty": q, "price": p} for prod, q, p in lines],
            "expenses": list(expenses),
            "card": card,
            "counted": counted if counted is not None else str(total - Decimal(card)),
            **extra,
        },
    }


async def sheet_user(staff):
    return await staff("sheet")


async def test_sheet_account_reaches_only_the_sheet_app(staff):
    employee = await sheet_user(staff)
    assert employee.user["permissions"]["sheet_only"] is True
    for path in ("/products", "/shifts/current", "/daysheets", "/settings", "/reports/low-stock", "/users"):
        response = await employee.get(path)
        assert response.status_code == 403, (path, response.status_code)
        assert "Sheet app" in response.json()["detail"]
    assert (await employee.post("/shifts/open", json={"opening_float": 0})).status_code == 403
    assert (await employee.get("/daysheets/app/catalog")).status_code == 200
    assert (await employee.get("/auth/me")).status_code == 200


async def test_catalog_lists_active_products_and_categories(staff, make_product, client):
    employee = await sheet_user(staff)
    product = await make_product(stock="4", sell_price="2.50")
    await category(client, "Daily")
    body = (await employee.get("/daysheets/app/catalog")).json()
    listed = {p["id"]: p for p in body["products"]}
    assert Decimal(listed[product["id"]]["stock"]) == 4
    assert Decimal(listed[product["id"]]["price"]) == Decimal("2.50")
    assert "Daily" in [c["name"] for c in body["categories"]]


async def test_save_is_idempotent_and_shows_problems(staff, make_product):
    employee = await sheet_user(staff)
    product = await make_product(stock="3")
    token = str(uuid.uuid4())
    body = sheet_body((product, "5", "2.00"))
    first = (await employee.put(f"/daysheets/app/{token}", json=body)).json()
    again = (await employee.put(f"/daysheets/app/{token}", json=body)).json()
    assert first["code"] == again["code"] and first["code"].startswith("DS-")
    assert first["status"] == "draft"
    assert any("not enough stock" in p["message"] for p in first["problems"])
    assert not any("stock is" in p["message"] for p in first["problems"])  # the count is never shown
    mine = (await employee.get("/daysheets/app/mine")).json()
    assert [s["token"] for s in mine].count(token) == 1


async def test_cannot_send_with_problems_and_nothing_is_recorded(staff, make_product, client):
    employee = await sheet_user(staff)
    product = await make_product(stock="3")
    token = str(uuid.uuid4())
    response = await employee.post(f"/daysheets/app/{token}/submit", json=sheet_body((product, "5", "2.00")))
    assert response.status_code == 400
    assert "not enough stock" in response.json()["detail"] and "stock is" not in response.json()["detail"]
    assert await stock_of(client, product["id"]) == 3


async def test_another_user_cannot_touch_my_sheet(staff, make_product):
    employee, other = await sheet_user(staff), await sheet_user(staff)
    product = await make_product()
    token = str(uuid.uuid4())
    assert (await employee.put(f"/daysheets/app/{token}", json=sheet_body((product, "1", "1.00")))).status_code == 200
    assert (await other.put(f"/daysheets/app/{token}", json=sheet_body((product, "1", "1.00")))).status_code == 404
    assert (await other.delete(f"/daysheets/app/{token}")).status_code == 404


async def test_send_approve_records_receipt_and_expenses_in_approvers_shift(staff, make_product, client, shift):
    employee = await sheet_user(staff)
    product = await make_product(stock="10")
    daily = await category(client, "Daily")
    token = str(uuid.uuid4())
    body = sheet_body(
        (product, "4", "2.50"), card="3.00", counted="6.00",
        expenses=[{"category_id": daily["id"], "amount": "1.00", "description": "Ice", "paid_from": "drawer"}],
    )
    sent = await employee.post(f"/daysheets/app/{token}/submit", json=body)
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "submitted"
    assert await stock_of(client, product["id"]) == 10

    locked = await employee.put(f"/daysheets/app/{token}", json=body)
    assert locked.status_code == 409
    assert (await employee.delete(f"/daysheets/app/{token}")).status_code == 409

    waiting = (await client.get("/daysheets?status=submitted")).json()
    sheet = next(s for s in waiting if s["code"] == sent.json()["code"])
    assert sheet["kind"] == "app"
    review = (await client.get(f"/daysheets/{sheet['id']}/review")).json()
    assert review["can_approve"] and review["problems"] == []
    assert Decimal(review["totals"]["difference"]) == 0
    assert Decimal(review["totals"]["cash_sales"]) == Decimal("7.00")

    approved = await client.post(f"/daysheets/{sheet['id']}/approve")
    assert approved.status_code == 200, approved.text
    result = approved.json()
    assert result["status"] == "approved" and result["receipt_ref"].startswith("TXN-")
    assert await stock_of(client, product["id"]) == 6

    txn = next(t for t in (await client.get("/transactions?limit=5")).json() if t["ref_number"] == result["receipt_ref"])
    assert txn["shift_id"] == shift["id"]
    assert Decimal(str(txn["payment_card"])) == Decimal("3.00")
    assert sheet["code"] in txn["notes"]

    expenses = [e for e in (await client.get("/expenses")).json()["items"] if e.get("description") == "Ice"]
    assert expenses and expenses[0]["paid_from_drawer"] is True

    trail = (await client.get(f"/shifts/{shift['id']}/report")).json()
    actions = [e["action"] for e in trail["activity"]]
    assert "day_sheet_approved" in actions

    mine = next(s for s in (await employee.get("/daysheets/app/mine")).json() if s["token"] == token)
    assert mine["status"] == "approved" and mine["receipt_ref"] == result["receipt_ref"]

    twice = await client.post(f"/daysheets/{sheet['id']}/approve")
    assert twice.status_code == 409


async def test_return_with_note_then_fix_and_send_again(staff, make_product, client, shift):
    employee = await sheet_user(staff)
    product = await make_product(stock="5")
    token = str(uuid.uuid4())
    sent = (await employee.post(f"/daysheets/app/{token}/submit", json=sheet_body((product, "2", "1.00")))).json()
    sheet_id = next(s["id"] for s in (await client.get("/daysheets?status=submitted")).json() if s["code"] == sent["code"])

    assert (await client.post(f"/daysheets/{sheet_id}/return", json={"note": "  "})).status_code == 422
    back = await client.post(f"/daysheets/{sheet_id}/return", json={"note": "Only 1 was sold"})
    assert back.status_code == 200 and back.json()["status"] == "returned"

    mine = next(s for s in (await employee.get("/daysheets/app/mine")).json() if s["token"] == token)
    assert mine["status"] == "returned" and mine["return_note"] == "Only 1 was sold"
    assert (await employee.delete(f"/daysheets/app/{token}")).status_code == 409

    fixed = await employee.post(f"/daysheets/app/{token}/submit", json=sheet_body((product, "1", "1.00")))
    assert fixed.status_code == 200 and fixed.json()["status"] == "submitted"
    approved = (await client.post(f"/daysheets/{sheet_id}/approve")).json()
    assert approved["status"] == "approved"
    assert await stock_of(client, product["id"]) == 4


async def test_approval_needs_the_permission_and_an_open_shift(staff, make_product, client):
    employee = await sheet_user(staff)
    product = await make_product(stock="5")
    token = str(uuid.uuid4())
    sent = (await employee.post(f"/daysheets/app/{token}/submit", json=sheet_body((product, "1", "1.00")))).json()
    sheet_id = next(s["id"] for s in (await client.get("/daysheets?status=submitted")).json() if s["code"] == sent["code"])

    manager = await staff("manager")
    assert manager.user["permissions"]["can_approve_sheets"] is False
    assert (await manager.post(f"/daysheets/{sheet_id}/approve")).status_code == 403
    assert (await manager.post(f"/daysheets/{sheet_id}/return", json={"note": "x"})).status_code == 403

    approver = await staff("manager", can_approve_sheets=True)
    review = (await approver.get(f"/daysheets/{sheet_id}/review")).json()
    assert not review["can_approve"]
    assert any("Open a shift" in p["message"] for p in review["problems"])
    assert (await approver.post(f"/daysheets/{sheet_id}/approve")).status_code == 400

    assert (await approver.post("/shifts/open", json={"opening_float": 0})).status_code == 201
    approved = await approver.post(f"/daysheets/{sheet_id}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["approved_by_name"] == approver.user["name"]


async def test_approval_rechecks_live_stock(staff, make_product, client, shift):
    employee = await sheet_user(staff)
    product = await make_product(stock="3")
    token = str(uuid.uuid4())
    sent = (await employee.post(f"/daysheets/app/{token}/submit", json=sheet_body((product, "3", "1.00")))).json()
    sheet_id = next(s["id"] for s in (await client.get("/daysheets?status=submitted")).json() if s["code"] == sent["code"])
    sold = await client.post("/transactions", json={
        "lines": [{"product_id": product["id"], "qty": "1", "sell_price": "1.00"}], "payment_cash": "1.00",
    })
    assert sold.status_code == 201, sold.text

    review = (await client.get(f"/daysheets/{sheet_id}/review")).json()
    assert not review["can_approve"]
    assert any("stock is 2" in p["message"] for p in review["problems"])
    assert (await client.post(f"/daysheets/{sheet_id}/approve")).status_code == 400
    assert await stock_of(client, product["id"]) == 2


async def test_draft_can_be_discarded_and_disappears(staff, make_product):
    employee = await sheet_user(staff)
    product = await make_product()
    token = str(uuid.uuid4())
    await employee.put(f"/daysheets/app/{token}", json=sheet_body((product, "1", "1.00")))
    assert (await employee.delete(f"/daysheets/app/{token}")).status_code == 204
    assert token not in [s["token"] for s in (await employee.get("/daysheets/app/mine")).json()]
    assert (await employee.put(f"/daysheets/app/{token}", json=sheet_body())).status_code == 404


async def test_excel_routes_ignore_app_sheets(staff, make_product, client):
    employee = await sheet_user(staff)
    product = await make_product()
    token = str(uuid.uuid4())
    await employee.put(f"/daysheets/app/{token}", json=sheet_body((product, "1", "1.00")))
    assert all(s["status"] != "draft" for s in (await client.get("/daysheets")).json())
    app_sheet = next(s for s in (await client.get("/daysheets?status=draft")).json() if s["kind"] == "app")
    assert (await client.get(f"/daysheets/{app_sheet['id']}/file")).status_code == 404


async def test_bad_token_is_refused(staff):
    employee = await sheet_user(staff)
    assert (await employee.put("/daysheets/app/not-a-uuid", json=sheet_body())).status_code == 400


async def test_sheet_started_offline_keeps_the_phones_date(staff, make_product):
    employee = await sheet_user(staff)
    product = await make_product()
    yesterday = date.today() - timedelta(days=1)
    started = {**sheet_body((product, "1", "1.00")), "sheet_date": yesterday.isoformat()}
    saved = (await employee.put(f"/daysheets/app/{uuid.uuid4()}", json=started)).json()
    assert saved["sheet_date"] == yesterday.isoformat()
    assert saved["code"].startswith(f"DS-{yesterday:%m%d}-")

    for odd in (date.today() + timedelta(days=1), date.today() - timedelta(days=30)):
        body = {**sheet_body((product, "1", "1.00")), "sheet_date": odd.isoformat()}
        saved = (await employee.put(f"/daysheets/app/{uuid.uuid4()}", json=body)).json()
        assert saved["sheet_date"] == date.today().isoformat()


async def test_approver_needs_edit_price_for_a_changed_set_price(staff, make_product, client):
    employee = await sheet_user(staff)
    product = await make_product(stock="5", sell_price="10.00")
    sent = (await employee.post(f"/daysheets/app/{uuid.uuid4()}/submit", json=sheet_body((product, "1", "0.01")))).json()
    assert sent["status"] == "submitted"  # the employee may type any price
    sheet_id = next(s["id"] for s in (await client.get("/daysheets?status=submitted")).json() if s["code"] == sent["code"])

    approver = await staff("manager", can_approve_sheets=False, can_edit_price=False)
    promoted = await client.put(f"/users/{approver.user['id']}", json={"can_approve_sheets": True})
    assert promoted.status_code == 200
    approver.user = (await approver.post("/auth/refresh")).json()
    assert (await approver.post("/shifts/open", json={"opening_float": 0})).status_code == 201
    review = (await approver.get(f"/daysheets/{sheet_id}/review")).json()
    assert not review["can_approve"]
    assert any("permission to change the price" in p["message"] for p in review["problems"])
    assert (await approver.post(f"/daysheets/{sheet_id}/approve")).status_code == 400


async def test_only_an_admin_can_grant_approval(staff):
    manager = await staff("manager", users_access="full")
    me = manager.user["id"]
    refused = await manager.put(f"/users/{me}", json={"can_approve_sheets": True})
    assert refused.status_code == 403
    username = f"u{uuid.uuid4().hex[:6]}"
    created = await manager.post("/users", json={
        "name": username, "username": username, "password": "password-123", "role": "cashier", "can_approve_sheets": True,
    })
    assert created.status_code == 403


async def test_approved_sheet_shows_what_was_recorded(staff, make_product, client, shift):
    employee = await sheet_user(staff)
    product = await make_product(stock="5")
    sent = (await employee.post(f"/daysheets/app/{uuid.uuid4()}/submit", json=sheet_body((product, "2", "3.00")))).json()
    sheet_id = next(s["id"] for s in (await client.get("/daysheets?status=submitted")).json() if s["code"] == sent["code"])
    assert (await client.post(f"/daysheets/{sheet_id}/approve")).status_code == 200
    assert (await client.delete(f"/products/{product['id']}")).status_code in (200, 204)

    review = (await client.get(f"/daysheets/{sheet_id}/review")).json()
    assert [(l["name"], Decimal(l["total"])) for l in review["lines"]] == [(product["name"], Decimal("6.00"))]
    assert Decimal(review["totals"]["receipt_total"]) == Decimal("6.00")
    mine = next(s for s in (await employee.get("/daysheets/app/mine")).json() if s["code"] == sent["code"])
    assert Decimal(mine["totals"]["receipt_total"]) == Decimal("6.00") and mine["problems"] == []


async def test_a_thousand_line_sheet_is_saved_and_deducts_every_line(staff, make_product, client, shift):
    """A long day: 1000 lines, products repeated on many lines. Each product loses the sum of its lines."""
    employee = await sheet_user(staff)
    products = [await make_product(stock="2000") for _ in range(3)]
    lines = [(products[i % 3], str(1 + i % 2), "1.00") for i in range(1000)]
    token = str(uuid.uuid4())

    too_long = sheet_body(*lines, (products[0], "1", "1.00"))
    assert (await employee.put(f"/daysheets/app/{token}", json=too_long)).status_code == 422

    body = sheet_body(*lines)
    saved = await employee.put(f"/daysheets/app/{token}", json=body)
    assert saved.status_code == 200, saved.text
    assert len(saved.json()["content"]["lines"]) == 1000
    sent = await employee.post(f"/daysheets/app/{token}/submit", json=body)
    assert sent.status_code == 200, sent.text

    sheet = next(s for s in (await client.get("/daysheets?status=submitted")).json() if s["code"] == sent.json()["code"])
    approved = await client.post(f"/daysheets/{sheet['id']}/approve")
    assert approved.status_code == 200, approved.text

    for n, product in enumerate(products):
        sold = sum(Decimal(q) for prod, q, _ in lines if prod is product)
        assert await stock_of(client, product["id"]) == 2000 - sold, n
    txn = next(t for t in (await client.get("/transactions?limit=5")).json() if t["ref_number"] == approved.json()["receipt_ref"])
    assert len(txn["transaction_lines"]) == 1000
    assert Decimal(str(txn["total_amount"])) == sum(Decimal(q) for _, q, _ in lines)
