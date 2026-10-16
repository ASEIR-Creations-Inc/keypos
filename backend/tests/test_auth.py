"""Login and permissions: who may do what, and who each action is credited to."""
from datetime import datetime, timedelta, timezone

from jose import jwt

from core.config import settings
from tests.conftest import ADMIN_PASSWORD, api_client, sale_body, sign_in


async def open_shift(c) -> dict:
    response = await c.post("/shifts/open", json={"opening_float": 50})
    assert response.status_code == 201, response.text
    return response.json()


async def test_everything_but_login_needs_a_signed_in_user(anonymous):
    for path in ("/products", "/settings", "/transactions", "/shifts/current", "/users", "/auth/me"):
        assert (await anonymous.get(path)).status_code == 401, path
    assert (await anonymous.post("/sync", json={"device_id": "x", "actions": []})).status_code == 401
    assert (await anonymous.post("/auth/register", json={})).status_code == 404


async def test_login_rejects_wrong_password_and_ignores_username_case(anonymous):
    wrong = await anonymous.post("/auth/login", json={"username": "admin", "password": "nope"})
    assert wrong.status_code == 401
    body = await sign_in(anonymous, "ADMIN", ADMIN_PASSWORD)
    assert body["permissions"]["is_admin"] is True
    me = (await anonymous.get("/auth/me")).json()
    assert me["id"] == body["id"] and me["username"] == "admin"


async def test_forged_token_is_rejected(anonymous):
    forged = jwt.encode({"sub": "1", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, "wrong-key", "HS256")
    anonymous.headers["Authorization"] = f"Bearer {forged}"
    assert (await anonymous.get("/products")).status_code == 401


async def test_cashier_sells_but_cannot_discount_reprice_or_refund(client, staff, make_product):
    cashier = await staff("cashier")
    await open_shift(cashier)
    typed = await make_product("10")
    priced = await make_product("10", sell_price="4.00")

    sold = await cashier.post("/transactions", json=sale_body((typed["id"], "1", "7.00")))
    assert sold.status_code == 201, sold.text
    assert sold.json()["cashier_id"] == cashier.user["id"]

    at_catalog = await cashier.post("/transactions", json=sale_body((priced["id"], "1", "4.00")))
    assert at_catalog.status_code == 201, at_catalog.text
    repriced = await cashier.post("/transactions", json=sale_body((priced["id"], "1", "3.00")))
    assert repriced.status_code == 403

    discounted = sale_body((typed["id"], "1", "7.00"))
    discounted["lines"][0]["discount"] = "1.00"
    discounted["payment_cash"] = "6.00"
    assert (await cashier.post("/transactions", json=discounted)).status_code == 403

    refund = await cashier.post(f"/transactions/{sold.json()['id']}/refund", json={"reason": "changed mind"})
    assert refund.status_code == 403


async def test_permissions_can_be_granted_per_user(staff, make_product):
    cashier = await staff("cashier", can_discount=True, can_refund=True)
    await open_shift(cashier)
    product = await make_product("10")
    body = sale_body((product["id"], "1", "7.00"))
    body["lines"][0]["discount"] = "1.00"
    body["payment_cash"] = "6.00"
    sold = await cashier.post("/transactions", json=body)
    assert sold.status_code == 201, sold.text
    refund = await cashier.post(f"/transactions/{sold.json()['id']}/refund", json={"reason": "faulty"})
    assert refund.status_code == 200, refund.text


async def test_held_ticket_reprice_needs_the_permission(staff, make_product):
    product = await make_product("10")
    for permitted in (False, True):
        cashier = await staff("cashier", can_edit_price=permitted)
        await open_shift(cashier)
        held = {**sale_body((product["id"], "1", "7.00")), "status": "held", "payment_cash": "0"}
        ticket = (await cashier.post("/transactions", json=held)).json()
        line_id = ticket["transaction_lines"][0]["id"]
        edit = await cashier.put(f"/transactions/{ticket['id']}/lines/{line_id}/price", json={"new_price": "6.00"})
        assert edit.status_code == (200 if permitted else 403), edit.text
    assert edit.json()["transaction_lines"][0]["sell_price"] in ("6.00", "6.0000")


async def test_cashier_is_kept_out_of_back_office(staff, make_product):
    cashier = await staff("cashier")
    product = await make_product("10")
    assert (await cashier.get("/products")).status_code == 200
    assert (await cashier.get("/customers")).status_code == 200
    denied = [
        await cashier.put(f"/products/{product['id']}", json={"name": "x"}),
        await cashier.post(f"/products/{product['id']}/adjust-stock", json={"change": "5", "reason": "found"}),
        await cashier.post("/products", json={"name": "new", "sell_price": "1"}),
        await cashier.get("/users"),
        await cashier.put("/settings", json={"store_name": "Mine", "tax_rate": "0"}),
        await cashier.get("/purchases"),
        await cashier.get("/audit"),
        await cashier.get("/reports/pnl?from_date=2026-01-01&to_date=2026-12-31"),
        await cashier.post("/customers", json={"name": "C"}),
    ]
    assert [r.status_code for r in denied] == [403] * len(denied)


async def test_own_access_sees_only_own_shifts_and_expenses(client, staff):
    cashier = await staff("cashier")
    mine = await open_shift(cashier)
    await client.post("/shifts/close", json={"closing_cash": 0})
    theirs = await open_shift(client)

    listed = {s["id"] for s in (await cashier.get("/shifts")).json()}
    assert mine["id"] in listed and theirs["id"] not in listed
    assert (await cashier.get(f"/shifts/{mine['id']}/report")).status_code == 200
    assert (await cashier.get(f"/shifts/{theirs['id']}/report")).status_code == 403

    admin_expense = await client.post("/expenses", json={"amount": "3", "expense_date": "2026-09-29"})
    assert admin_expense.status_code == 201, admin_expense.text
    own = await cashier.post("/expenses", json={"amount": "2", "expense_date": "2026-09-29"})
    assert own.status_code == 201, own.text
    ids = {e["id"] for e in (await cashier.get("/expenses")).json()["items"]}
    assert own.json()["id"] in ids and admin_expense.json()["id"] not in ids
    assert (await cashier.delete(f"/expenses/{admin_expense.json()['id']}")).status_code == 403


async def test_manager_cannot_create_or_change_admins(client, staff):
    manager = await staff("manager", users_access="full")
    made = await manager.post("/users", json={"name": "c", "username": "made_by_mgr", "password": "password-123"})
    assert made.status_code == 201, made.text
    escalate = await manager.post("/users", json={
        "name": "x", "username": "sneaky_admin", "password": "password-123", "role": "admin",
    })
    assert escalate.status_code == 403
    me = await manager.put(f"/users/{manager.user['id']}", json={"role": "admin"})
    assert me.status_code == 403
    admin_id = (await client.get("/auth/me")).json()["id"]
    assert (await manager.put(f"/users/{admin_id}", json={"password": "taken-over-1"})).status_code == 403


async def test_last_admin_and_self_cannot_be_switched_off(client):
    admin_id = (await client.get("/auth/me")).json()["id"]
    assert (await client.delete(f"/users/{admin_id}")).status_code == 400
    assert (await client.put(f"/users/{admin_id}", json={"is_active": False})).status_code == 400
    assert (await client.put(f"/users/{admin_id}", json={"role": "cashier"})).status_code == 400


async def test_deactivated_user_is_locked_out_at_once(client, staff):
    cashier = await staff("cashier")
    assert (await cashier.get("/products")).status_code == 200
    assert (await client.delete(f"/users/{cashier.user['id']}")).status_code == 204
    assert (await cashier.get("/products")).status_code == 401
    async with api_client() as fresh:
        login = await fresh.post("/auth/login", json={"username": cashier.user["username"], "password": "password-123"})
        assert login.status_code == 401


async def test_short_passwords_are_refused(client):
    response = await client.post("/users", json={"name": "s", "username": "shorty", "password": "1234567"})
    assert response.status_code == 422


async def test_change_own_password(staff):
    cashier = await staff("cashier")
    wrong = await cashier.post("/auth/password", json={"current_password": "nope", "new_password": "new-password-1"})
    assert wrong.status_code == 400
    ok = await cashier.post("/auth/password", json={"current_password": "password-123", "new_password": "new-password-1"})
    assert ok.status_code == 204
    async with api_client() as fresh:
        old = await fresh.post("/auth/login", json={"username": cashier.user["username"], "password": "password-123"})
        assert old.status_code == 401
        await sign_in(fresh, cashier.user["username"], "new-password-1")


async def test_user_changes_are_audited(client, staff):
    cashier = await staff("cashier")
    await client.put(f"/users/{cashier.user['id']}", json={"can_refund": True})
    entries = (await client.get("/audit?action=user_updated")).json()["entries"]
    assert any(e["ref"] == cashier.user["username"] and "can_refund" in e["summary"] for e in entries)
    created = (await client.get("/audit?action=user_created")).json()["entries"]
    assert any(e["ref"] == cashier.user["username"] for e in created)


def _token(user_id: int, issued_days_ago: float) -> str:
    issued = datetime.now(timezone.utc) - timedelta(days=issued_days_ago)
    return jwt.encode(
        {"sub": str(user_id), "iat": int(issued.timestamp()), "exp": issued + timedelta(hours=12)},
        settings.SECRET_KEY, settings.ALGORITHM,
    )


async def test_offline_sale_is_credited_to_who_rang_it_up(client, staff, make_product):
    cashier = await staff("cashier")
    await open_shift(cashier)
    product = await make_product("10")
    admin_id = (await client.get("/auth/me")).json()["id"]

    def action(ref: str, token: str) -> dict:
        return {"action_type": "sale", "client_ref": ref, "auth_token": token,
                "payload": sale_body((product["id"], "1", "2.00"))}

    push = await client.post("/sync", json={"device_id": "till-auth", "actions": [
        action("auth-1", _token(cashier.user["id"], 2)),
        action("auth-2", _token(cashier.user["id"], 9)),
        action("auth-3", "not-a-token"),
    ]})
    results = push.json()["results"]
    assert all(r["success"] for r in results), results
    cashiers = [
        (await client.get(f"/transactions/{r['record_id']}")).json()["cashier_id"] for r in results
    ]
    assert cashiers == [cashier.user["id"], admin_id, admin_id]


async def test_offline_stock_adjustment_needs_inventory_rights(client, staff, make_product):
    cashier = await staff("cashier")
    product = await make_product("10")
    push = await client.post("/sync", json={"device_id": "till-auth", "actions": [{
        "action_type": "adjustment", "client_ref": "auth-adj-1", "auth_token": _token(cashier.user["id"], 0),
        "payload": {"product_id": product["id"], "adjustment": "-3", "reason": "broken"},
    }]})
    result = push.json()["results"][0]
    assert not result["success"] and "Not allowed" in result["error"]
