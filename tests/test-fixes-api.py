#!/usr/bin/env python3
"""Checks for the post-Phase-4 fixes:

1. A sale is never recorded twice when the till loses the server's reply
   (online retry, online-then-queued, and simultaneous repeats).
2. CSV product and customer imports write an audit entry with stock movements.
3. An offline sale synced while no shift is open is booked to the next shift.

Self-contained: closes any open shift and works in its own ones.
Run after `./testenv.sh up`:  python3 test-fixes-api.py
"""
import json
import subprocess
import sys
import uuid
import urllib.error
import urllib.request

from auth import auth_headers
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

API = "http://127.0.0.1:8095/api"
DB = "pos_test"
RESULTS = []
DEVICE = "test-device-fix"


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers=auth_headers())
    return _send(req)


def upload(path, filename, text):
    boundary = "----keypos" + uuid.uuid4().hex
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
        f"Content-Type: text/csv\r\n\r\n{text}\r\n--{boundary}--\r\n"
    ).encode()
    req = urllib.request.Request(
        API + path, data=body, method="POST",
        headers=auth_headers(f"multipart/form-data; boundary={boundary}"),
    )
    return _send(req)


def _send(req):
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw.decode()


def sql(query):
    out = subprocess.run(["sudo", "-u", "postgres", "psql", "-d", DB, "-tAc", query], capture_output=True, text=True, check=True)
    return out.stdout.strip()


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  -> {detail}"))


def stock(pid):
    return D(sql(f"select stock_qty from products where id={pid}"))


def fresh_product(name, qty, cost="1.00", sku=None):
    body = {"name": name, "sell_price": "0", "cost_price": cost, "stock_qty": str(qty), "is_active": True}
    if sku:
        body["sku"] = sku
    st, prod = call("POST", "/products", body)
    assert st in (200, 201), prod
    return prod


def sale(pid, ref, device=DEVICE, qty=1, price="5.00"):
    return {
        "lines": [{"product_id": pid, "qty": str(qty), "sell_price": price}],
        "payment_cash": str(D(qty) * D(price)),
        "device_id": device,
        "client_ref": ref,
    }


def txn_count(ref):
    return int(sql(f"select count(*) from transactions where client_ref='{ref}'"))


def main():
    run = uuid.uuid4().hex[:8]
    call("PUT", "/settings", {"store_name": "KEYPOS", "currency_symbol": "$", "tax_rate": 0, "low_stock_threshold": 5})
    call("POST", "/shifts/close", {"closing_cash": 0})
    st, shift = call("POST", "/shifts/open", {"opening_float": 100})
    check("open shift", st in (200, 201), f"{st} {shift}")

    # ── 1. Duplicate sales ──
    pid = fresh_product(f"Fix dup {run}", 20)["id"]

    ref = f"{DEVICE}-retry-{run}"
    st1, t1 = call("POST", "/transactions", sale(pid, ref))
    st2, t2 = call("POST", "/transactions", sale(pid, ref))
    check("online sale accepted", st1 == 201, f"{st1} {t1}")
    check("repeated online checkout returns the first sale", st2 in (200, 201) and t2["id"] == t1["id"], f"{st2} {t2}")
    check("repeated online checkout: one receipt, stock down once", txn_count(ref) == 1 and stock(pid) == 19,
          f"count={txn_count(ref)} stock={stock(pid)}")

    ref = f"{DEVICE}-lostreply-{run}"
    st, t = call("POST", "/transactions", sale(pid, ref))
    queued = {
        "action_type": "sale", "payload": sale(pid, ref), "client_ref": ref,
        "offline_created_at": datetime.now(timezone.utc).isoformat(),
    }
    st, res = call("POST", "/sync", {"device_id": DEVICE, "actions": [queued]})
    r0 = res["results"][0] if st == 200 else {}
    check("queued copy of a recorded sale syncs as success", r0.get("success") is True, f"{st} {res}")
    check("queued copy points at the online sale", r0.get("record_id") == t["id"], f"{r0} vs {t['id']}")
    check("online sale + queued copy: one receipt, stock down once", txn_count(ref) == 1 and stock(pid) == 18,
          f"count={txn_count(ref)} stock={stock(pid)}")
    st, res = call("POST", "/sync", {"device_id": DEVICE, "actions": [queued]})
    check("second push of the copy is a replay", res["results"][0].get("duplicate") is True and stock(pid) == 18, res)

    ref = f"{DEVICE}-other-{run}"
    call("POST", "/transactions", sale(pid, ref))
    st, t_other = call("POST", "/transactions", sale(pid, ref, device="another-till"))
    check("same ref from another till is its own sale", st == 201 and txn_count(ref) == 2 and stock(pid) == 16,
          f"{st} count={txn_count(ref)} stock={stock(pid)}")

    ref = f"{DEVICE}-burst-{run}"
    with ThreadPoolExecutor(max_workers=6) as pool:
        replies = list(pool.map(lambda _: call("POST", "/transactions", sale(pid, ref)), range(6)))
    ids = {body["id"] for st, body in replies if st in (200, 201)}
    check("6 simultaneous repeats all answered", all(st in (200, 201) for st, _ in replies), [st for st, _ in replies])
    check("6 simultaneous repeats: one receipt, stock down once",
          len(ids) == 1 and txn_count(ref) == 1 and stock(pid) == 15, f"ids={ids} stock={stock(pid)}")

    st, t_noref = call("POST", "/transactions", {k: v for k, v in sale(pid, None).items() if k != "client_ref"})
    check("sale without a ref still works (older tills)", st == 201 and stock(pid) == 14, f"{st} {t_noref}")

    # ── 2. CSV import audit ──
    sku = f"FIXSKU{run}"
    existing = fresh_product(f"Fix import {run}", 10, cost="2.00", sku=sku)
    new_sku = f"FIXNEW{run}"
    csv_text = (
        "sku,name,sell_price,cost_price,stock_qty,low_stock_threshold,is_active\n"
        f"{sku},Fix import {run},4.00,2.50,25,,true\n"
        f"{new_sku},Fix import new {run},6.00,3.00,7,,true\n"
    )
    st, summary = upload("/import/products", f"products-{run}.csv", csv_text)
    check("product import ran", st == 200 and summary["imported_count"] == 1 and summary["updated_count"] == 1
          and not summary["errors"], f"{st} {summary}")
    check("imported stock values applied", stock(existing["id"]) == 25, stock(existing["id"]))
    new_id = int(sql(f"select id from products where sku='{new_sku}'"))
    check("new product created with its stock", stock(new_id) == 7, stock(new_id))

    st, trail = call("GET", f"/audit?action=products_imported&shift_id={shift['id']}")
    entry = next((e for e in trail["entries"] if e["ref"] == f"products-{run}.csv"), None)
    check("product import has an audit entry in the open shift", entry is not None, trail)
    moves = {m["product_id"]: m for m in entry["stock_movements"]} if entry else {}
    old_move = moves.get(existing["id"], {})
    check("import audit: stock 10 → 25 recorded",
          D(old_move.get("qty_before", "-1")) == 10 and D(old_move.get("qty_after", "-1")) == 25, old_move)
    check("import audit: new product 0 → 7 recorded", D(moves.get(new_id, {}).get("qty_after", "-1")) == 7, moves)
    changed = entry["details"]["changed"] if entry else []
    cost_change = next((c["changes"].get("cost_price") for c in changed if c["product_id"] == existing["id"]), None)
    check("import audit: cost 2.00 → 2.50 recorded",
          cost_change and D(cost_change["from"]) == D("2.00") and D(cost_change["to"]) == D("2.50"), changed)

    phone = f"555{run}"
    st, cust = call("POST", "/customers", {"name": f"Fix cust {run}", "phone": phone, "credit_limit": "100"})
    csv_text = (
        "name,phone,email,credit_limit,balance\n"
        f"Fix cust {run},{phone},,100,40\n"
        f"Fix new cust {run},777{run},,50,15\n"
    )
    st, summary = upload("/import/customers", f"customers-{run}.csv", csv_text)
    check("customer import ran", st == 200 and summary["updated_count"] == 1 and summary["imported_count"] == 1, summary)
    st, trail = call("GET", f"/audit?action=customers_imported&shift_id={shift['id']}")
    entry = next((e for e in trail["entries"] if e["ref"] == f"customers-{run}.csv"), None)
    check("customer import has an audit entry", entry is not None, trail)
    check("customer import audit: account change 0 → 40 and new 15 = +55",
          entry and D(entry["account"]) == D("55") and len(entry["details"]["balance_changes"]) == 2, entry)

    # ── 3. Offline sale synced with no shift open ──
    st, closed = call("POST", "/shifts/close", {"closing_cash": 0})
    check("close shift", st == 200, closed)
    late_ref = f"{DEVICE}-late-{run}"
    rung_up = datetime.now(timezone.utc) - timedelta(minutes=30)
    st, res = call("POST", "/sync", {"device_id": DEVICE, "actions": [{
        "action_type": "sale", "payload": sale(pid, late_ref, price="7.00"), "client_ref": late_ref,
        "offline_created_at": rung_up.isoformat(),
    }]})
    late_id = res["results"][0].get("record_id")
    check("offline sale syncs with no shift open", res["results"][0].get("success") and late_id, res)
    check("it has no shift yet", sql(f"select coalesce(shift_id::text,'none') from transactions where id={late_id}") == "none")

    st, closed_report = call("GET", f"/shifts/{shift['id']}/report")
    count_before = closed_report["report"]["total_transactions"]

    st, shift2 = call("POST", "/shifts/open", {"opening_float": 50})
    check("next shift opens", st in (200, 201), shift2)
    check("late offline sale booked to the next shift",
          sql(f"select shift_id from transactions where id={late_id}") == str(shift2["id"]))
    st, z = call("GET", f"/shifts/{shift2['id']}/report")
    check("next shift's report counts it", z["report"]["total_transactions"] == 1
          and D(z["report"]["cash_sales"]) == D("7.00") and z["report"]["offline_sales_count"] == 1, z["report"])
    attached = [a for a in z["activity"] if a["action"] == "offline_sales_attached"]
    late_txn_ref = sql(f"select ref_number from transactions where id={late_id}")
    check("next shift's trail explains it", len(attached) == 1 and late_txn_ref in attached[0]["summary"]
          and D(attached[0]["cash"]) == 0 and D(attached[0]["amount"]) == D("7.00"), attached)
    st, closed_report = call("GET", f"/shifts/{shift['id']}/report")
    check("closed shift's report unchanged", closed_report["report"]["total_transactions"] == count_before)

    st, shift3 = call("POST", "/shifts/close", {"closing_cash": 57})
    st, shift3 = call("POST", "/shifts/open", {"opening_float": 0})
    check("already-attached sale is not attached again",
          sql(f"select shift_id from transactions where id={late_id}") == str(shift2["id"]))

    passed = sum(RESULTS)
    print(f"\n{passed}/{len(RESULTS)} passed")
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
