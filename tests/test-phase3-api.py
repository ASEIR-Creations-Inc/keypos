#!/usr/bin/env python3
"""Phase 3 checks: whole-receipt refunds, re-issues, and the audit trail.

Self-contained: closes any open shift and works in its own one.
Run after `./testenv.sh up`:  python3 test-phase3-api.py
"""
import json
import subprocess
import sys
import urllib.error
import urllib.request
import uuid

from auth import auth_headers
from datetime import date
from decimal import Decimal as D

API = "http://127.0.0.1:8095/api"
DB = "pos_test"
RESULTS = []
TODAY = str(date.today())


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers=auth_headers())
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


def sql_fails(query):
    out = subprocess.run(["sudo", "-u", "postgres", "psql", "-d", DB, "-tAc", query], capture_output=True, text=True)
    return out.returncode != 0


def check(name, ok, detail=""):
    RESULTS.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  -> {detail}"))


def stock(pid):
    return D(sql(f"select stock_qty from products where id={pid}"))


def line(pid, qty, price, discount=0):
    return {"product_id": pid, "qty": qty, "sell_price": price, "discount": discount}


def sale(lines, **kw):
    return call("POST", "/transactions", {"lines": lines, **kw})


def audit_entries(**params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return call("GET", f"/audit?{query}")[1]["entries"]


# ── setup ──
if sql("select id from shifts where cashier_id=1 and status='open'"):
    call("POST", "/shifts/close", {"closing_cash": 0})
A, B = [int(x) for x in sql("select id from products where is_active order by id limit 2").split("\n")]
sql(f"update products set stock_qty=10 where id in ({A},{B})")
sql(f"update products set cost_price=1 where id={B}")
st, S = call("POST", "/shifts/open", {"opening_float": 50})
SHIFT = S["id"]
call("PUT", "/settings", {"store_name": "KEYPOS", "currency_symbol": "$", "tax_rate": 10, "low_stock_threshold": 5})
CUST = call("POST", "/customers", {"name": "Phase3 Test", "credit_limit": 500})[1]["id"]
st, sup = call("POST", "/suppliers", {"name": "Phase3 Supplier"})
if st in (200, 201):
    SUP = sup["id"]
else:
    SUP = int(sql("select id from suppliers where name='Phase3 Supplier' order by id limit 1"))

# ── 1. schema: audit tables and new columns exist ──
tables = sql("select tablename from pg_tables where schemaname='public' order by tablename")
check("audit_log and stock_movements tables created", "audit_log" in tables and "stock_movements" in tables)
cols = sql("""select table_name||'.'||column_name from information_schema.columns
              where table_schema='public' order by 1""")
for col in ["transactions.reissue_of_id", "transactions.refunded_amount", "transaction_lines.refunded_qty",
            "refunds.ref_number", "customer_payments.method", "customer_payments.shift_id",
            "expenses.paid_from_drawer", "expenses.shift_id"]:
    check(f"column {col} exists", col in cols)

# ── 2. shift open is audited ──
entries = audit_entries(shift_id=SHIFT, action="shift_open")
check("shift_open audited with the float", len(entries) == 1 and D(entries[0]["amount"]) == D(50), entries)

# ── 3. sale writes an audit entry with the money split and stock movements ──
st, s1 = sale([line(A, 2, 10), line(B, 1, 5)], payment_cash=30)
check("sale accepted (25 + 2.50 tax = 27.50, change 2.50)",
      st == 201 and D(s1["total_amount"]) == D("27.50") and D(s1["change_given"]) == D("2.50"), (st, s1))
check("stock out on both lines", (stock(A), stock(B)) == (D(8), D(9)), (stock(A), stock(B)))
entries = audit_entries(shift_id=SHIFT, action="sale", limit=1)
e = entries[-1]
check("sale audit: cash 27.50 booked to the shift", (D(e["cash"]), D(e["card"]), D(e["account"]), e["shift_id"]) == (D("27.50"), D(0), D(0), SHIFT), e)
check("sale audit: stock movements with before/after",
      sorted((m["product_id"], str(m["qty_before"]), str(m["qty_after"])) for m in e["stock_movements"])
      == sorted([(A, "10.000", "8.000"), (B, "10.000", "9.000")]), e["stock_movements"])

# ── 4. whole-receipt refund ──
check("refund without reason rejected", call("POST", f"/transactions/{s1['id']}/refund", {})[0] == 422)
check("void route is gone", call("POST", f"/transactions/{s1['id']}/void")[0] in (404, 405))
st, r = call("POST", f"/transactions/{s1['id']}/refund", {"reason": "customer returned everything"})
check("refund marks the whole receipt refunded", st == 200 and r["status"] == "refunded" and D(r["refunded_amount"]) == D("27.50"), (st, r))
check("refund has an RFD reference and reason", r["refund"]["ref_number"].startswith("RFD-") and r["refund"]["reason"] == "customer returned everything", r.get("refund"))
check("refundable flag now false", r["refundable"] is False)
check("all stock back on the shelf", (stock(A), stock(B)) == (D(10), D(10)), (stock(A), stock(B)))
e = audit_entries(shift_id=SHIFT, action="refund")[-1]
check("refund audit: money back out of the drawer", (D(e["amount"]), D(e["cash"])) == (D("-27.50"), D("-27.50")), e)
check("refund audit: stock movements back in", len(e["stock_movements"]) == 2, e["stock_movements"])
check("cannot refund twice", call("POST", f"/transactions/{s1['id']}/refund", {"reason": "again"})[0] == 400)

# ── 5. re-issue of a refunded receipt ──
st, s2 = sale([line(B, 1, 5)], payment_cash=5.50, reissue_of_id=s1["id"])
check("re-issue sale accepted", st == 201 and s2["reissue_of_ref"] == s1["ref_number"], (st, s2))
check("original receipt shows what re-issued it", call("GET", f"/transactions/{s1['id']}")[1]["reissued_as_ref"] == s2["ref_number"])
check("a refunded receipt re-issues only once", sale([line(B, 1, 5)], payment_cash=5.50, reissue_of_id=s1["id"])[0] == 400)
check("cannot re-issue a receipt that was not refunded", sale([line(B, 1, 5)], payment_cash=5.50, reissue_of_id=s2["id"])[0] == 400)

# ── 6. account sale, then payments by cash and card ──
st, s3 = sale([line(A, 1, 100)], customer_id=CUST, payment_account=110)
check("account sale books 110 to the customer", st == 201 and D(sql(f"select balance from customers where id={CUST}")) == D(110))
check("account sale audited", (lambda e: (D(e["account"]), e["shift_id"]) == (D(110), SHIFT))(audit_entries(shift_id=SHIFT, action="sale")[-1]))
st, p1 = call("POST", f"/customers/{CUST}/payment", {"amount": 60, "reference": "P1", "method": "cash"})
check("cash payment booked to the open shift", st == 201 and p1["shift_id"] == SHIFT and p1["method"] == "cash", (st, p1))
e = audit_entries(shift_id=SHIFT, action="payment_received")[-1]
check("cash payment audit: +60 cash", (D(e["cash"]), D(e["card"])) == (D(60), D(0)), e)
st, p2 = call("POST", f"/customers/{CUST}/payment", {"amount": 50, "method": "card"})
check("card payment recorded as card", st == 201 and p2["method"] == "card", (st, p2))
e = audit_entries(shift_id=SHIFT, action="payment_received")[-1]
check("card payment audit: +50 card, 0 cash", (D(e["cash"]), D(e["card"])) == (D(0), D(50)), e)
check("balance settled", D(sql(f"select balance from customers where id={CUST}")) == D(0))

# ── 7. drawer expenses ──
st, e1 = call("POST", "/expenses", {"amount": 20, "description": "supplies", "expense_date": TODAY, "paid_from_drawer": True})
check("drawer expense booked to the shift", st == 201 and e1["shift_id"] == SHIFT and e1["paid_from_drawer"], (st, e1))
check("drawer expense audit: -20 cash", D(audit_entries(shift_id=SHIFT, action="expense_added")[-1]["cash"]) == D(-20))
call("PUT", f"/expenses/{e1['id']}", {"amount": 25, "description": "supplies", "expense_date": TODAY, "paid_from_drawer": True})
check("expense edit audits the cash difference", D(audit_entries(shift_id=SHIFT, action="expense_edited")[-1]["cash"]) == D(-5))
st, e2 = call("POST", "/expenses", {"amount": 7, "description": "not from drawer", "expense_date": TODAY, "paid_from_drawer": False})
check("non-drawer expense has no shift", st == 201 and e2["shift_id"] is None, (st, e2))

# ── 8. stock adjustments with a reason ──
st, p = call("POST", f"/products/{A}/adjust-stock", {"change": -1, "reason": "damaged"})
check("adjust by change accepted", st == 200 and stock(A) == D(8), (st, stock(A)))
adj = sql(f"select qty_before, qty_after, adjustment, reason from stock_adjustments where product_id={A} order by id desc limit 1")
check("adjustment row keeps before/after and reason", adj.startswith("9.000|8.000|-1.000|damaged"), adj)
e = audit_entries(shift_id=SHIFT, action="stock_adjusted")[-1]
check("adjustment audited with the movement", e["stock_movements"] and D(e["stock_movements"][0]["qty_change"]) == D(-1), e)
call("POST", f"/products/{A}/adjust-stock", {"counted_qty": 4, "reason": "stock count"})
check("adjust to a counted quantity", stock(A) == D(4), stock(A))
check("adjustment needs exactly one of change/counted_qty", call("POST", f"/products/{A}/adjust-stock", {"change": 1, "counted_qty": 5, "reason": "x"})[0] == 422)
check("adjustment needs a reason", call("POST", f"/products/{A}/adjust-stock", {"change": 1})[0] == 422)

# ── 9. purchase post is audited with the WAC change ──
st, po = call("POST", "/purchases", {"supplier_id": SUP, "lines": [{"product_id": B, "qty": 5, "unit_cost": 2}]})
st, po = call("POST", f"/purchases/{po['id']}/post")
check("purchase posted", st == 200 and po["status"] == "posted", (st, po))
check("stock received", stock(B) == D(14), stock(B))
check("WAC recalculated: (9*1 + 5*2)/14 = 1.3571", D(po["lines"][0]["wac_after"]) == D("1.3571"), po["lines"][0])
e = audit_entries(shift_id=SHIFT, action="purchase_posted")[-1]
check("purchase audit carries the cost change", e["details"]["lines"][0]["cost_after"] == "1.3571", e["details"])
check("purchase audited the stock movement", e["stock_movements"] and D(e["stock_movements"][0]["qty_change"]) == D(5), e["stock_movements"])

# ── 10. price edits: held tickets only, audited ──
st, h = sale([line(A, 1, 10)], status="held")
check("held ticket audited", audit_entries(shift_id=SHIFT, action="sale_held")[-1]["ref"] == h["ref_number"])
hid = h["transaction_lines"][0]["id"]
clerk = f"p3clerk{uuid.uuid4().hex[:6]}"
call("POST", "/users", {"name": clerk, "username": clerk, "password": "clerk-pass-1", "role": "cashier"})
clerk_token = call("POST", "/auth/login", {"username": clerk, "password": "clerk-pass-1"})[1]["access_token"]
denied = urllib.request.Request(API + f"/transactions/{h['id']}/lines/{hid}/price", data=json.dumps({"new_price": 8}).encode(),
                                method="PUT", headers={"Content-Type": "application/json", "Authorization": "Bearer " + clerk_token})
try:
    urllib.request.urlopen(denied)
    denied_status = 200
except urllib.error.HTTPError as e:
    denied_status = e.code
check("price edit without the permission refused", denied_status == 403, denied_status)
st, h2 = call("PUT", f"/transactions/{h['id']}/lines/{hid}/price", {"new_price": 8})
check("held ticket reprice accepted", st == 200 and D(h2["total_amount"]) == D("8.80"), (st, h2))
check("price edit audited", len(audit_entries(shift_id=SHIFT, action="price_edit")) == 1)
check("completed receipt cannot be repriced", call("PUT", f"/transactions/{s2['id']}/lines/{s2['transaction_lines'][0]['id']}/price", {"new_price": 1})[0] == 400)
st, res = call("POST", f"/transactions/{h['id']}/resume")
check("resume audited and ticket removed", st == 200 and len(audit_entries(shift_id=SHIFT, action="held_resumed")) == 1 and call("GET", f"/transactions/{h['id']}")[0] == 404)

# ── 11. audit endpoint totals ──
st, a = call("GET", f"/audit?shift_id={SHIFT}&limit=1000")
actions = {e["action"] for e in a["entries"]}
check("shift trail covers every money/stock action",
      {"shift_open", "sale", "refund", "payment_received", "expense_added", "expense_edited",
       "stock_adjusted", "purchase_posted", "sale_held", "price_edit", "held_resumed"} <= actions, actions)
check("no plain 'sale' noise missing: all entries have user and time",
      all(e["user_name"] and e["created_at"] for e in a["entries"]))
check("audit cash total = 27.50 - 27.50 + 5.50 + 60 - 20 - 5 = 40.50", D(a["total_cash"]) == D("40.50"), a["total_cash"])
check("audit card total = 50", D(a["total_card"]) == D(50), a["total_card"])
check("audit account total = 110", D(a["total_account"]) == D(110), a["total_account"])
st, m = call("GET", f"/audit/stock?product_id={A}&shift_id={SHIFT}")
check("stock history for a product in this shift, newest first",
      st == 200 and len(m["movements"]) == 5 and D(m["movements"][0]["qty_after"]) == D(4), (st, len(m["movements"])))

# ── 12. close the shift: Z-report shows refunds, drawer money and the trail ──
st, z = call("POST", "/shifts/close", {"closing_cash": 90.50})
rep = z["report"]
check("expected cash = 50 float + 5.50 net cash + 60 payments - 25 drawer expenses",
      D(rep["expected_cash"]) == D("90.50") and D(z["shift"]["variance"]) == D(0), rep)
check("Z: gross 130, refunds 27.50, net sales 105, tax 10.50",
      (D(rep["gross_sales"]), D(rep["total_refunds"]), D(rep["net_sales"]), D(rep["tax_collected"]))
      == (D(130), D("27.50"), D(105), D("10.50")), rep)
check("Z: payments and drawer expenses shown",
      (D(rep["customer_payments_cash"]), D(rep["customer_payments_card"]), D(rep["drawer_expenses"])) == (D(60), D(50), D(25)), rep)
check("Z lists the refunded receipt with reason, who, and its re-issue",
      len(z["refunds"]) == 1 and z["refunds"][0]["sale_ref"] == s1["ref_number"]
      and z["refunds"][0]["reason"] == "customer returned everything"
      and z["refunds"][0]["refunded_by"] and z["refunds"][0]["reissued_as"] == s2["ref_number"], z["refunds"])
check("Z activity excludes plain sales but keeps the rest",
      {e["action"] for e in z["activity"]} >= {"refund", "expense_added", "payment_received", "stock_adjusted", "price_edit"}
      and "sale" not in {e["action"] for e in z["activity"]}, [e["action"] for e in z["activity"]])
check("Z activity counts per action", z["activity_counts"].get("refund") == 1 and z["activity_counts"].get("payment_received") == 2, z["activity_counts"])

# ── 13. closed shift is frozen ──
check("no refund after the shift closed", call("POST", f"/transactions/{s3['id']}/refund", {"reason": "too late"})[0] == 400)
check("drawer expense locked after close", call("PUT", f"/expenses/{e1['id']}", {"amount": 1, "expense_date": TODAY, "paid_from_drawer": True})[0] == 400)
check("drawer expense cannot be deleted after close", call("DELETE", f"/expenses/{e1['id']}")[0] == 400)
check("non-drawer expense can still be deleted", call("DELETE", f"/expenses/{e2['id']}")[0] == 200)
check("expense deletion audited", any(e["ref"] == f"EXP-{e2['id']}" for e in audit_entries(action="expense_deleted")))

# ── 14. audit rows are append-only (database level) ──
check("audit_log rejects updates", sql_fails("update audit_log set summary='hacked' where id=(select min(id) from audit_log)"))
check("audit_log rejects truncation", sql_fails("truncate audit_log"))
check("stock_movements rejects deletes", sql_fails("delete from stock_movements where id=(select min(id) from stock_movements)"))
check("refunds rejects deletes", sql_fails(f"delete from refunds where transaction_id={s1['id']}"))
check("customer_payments rejects updates", sql_fails("update customer_payments set amount=0 where id=(select min(id) from customer_payments)"))
check("refunds row survived", sql(f"select count(*) from refunds where transaction_id={s1['id']}") == "1")

# ── 15. offline sync goes through the same audited paths ──
st, S2 = call("POST", "/shifts/open", {"opening_float": 0})
S2ID = S2["id"]
st, res = call("POST", "/sync", {"device_id": "dev3", "actions": [
    {"action_type": "sale", "payload": {"lines": [line(A, 1, 2)], "payment_cash": 2.20, "payment_card": 0, "payment_account": 0, "discount_amount": 0}},
    {"action_type": "adjustment", "payload": {"product_id": B, "adjustment": -3, "qty_before": 999, "reason": "offline count", "adjusted_by_id": 1}},
    {"action_type": "expense", "payload": {"amount": 5, "description": "offline tea", "expense_date": TODAY, "paid_from_drawer": True, "entered_by_id": 1}},
    {"action_type": "purchase", "payload": {"supplier_name": "Phase3 Supplier", "lines": [{"product_id": B, "qty": 1, "unit_cost": 3}]}},
    {"action_type": "bogus", "payload": {}},
]})
check("sync processed 4 and failed 1", st == 200 and res["processed"] == 4 and res["failed"] == 1, res)
check("offline sale deducted stock", stock(A) == D(3), stock(A))
check("offline purchase received into stock (11 + 1 = 12)", stock(B) == D(12), stock(B))
adj = sql(f"select qty_before, qty_after from stock_adjustments where product_id={B} order by id desc limit 1")
check("offline adjustment row shows server before/after (14 -> 11)", adj == "14.000|11.000", adj)
check("offline purchase received with WAC: (11*1.3571+3)/12 = 1.4940",
      D(sql(f"select cost_price from products where id={B}")) == D("1.4940"), sql(f"select cost_price from products where id={B}"))
acts = {e["action"] for e in audit_entries(shift_id=S2ID, limit=100)}
check("offline actions audited into the new shift",
      {"sale", "stock_adjusted", "expense_added", "purchase_posted"} <= acts, acts)
check("offline expense booked to the drawer shift",
      sql(f"select count(*) from expenses where shift_id={S2ID} and paid_from_drawer") == "1")

print(f"\n{sum(RESULTS)}/{len(RESULTS)} passed")
sys.exit(0 if all(RESULTS) else 1)
