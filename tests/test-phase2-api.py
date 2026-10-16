#!/usr/bin/env python3
"""Phase 2 money and stock checks against the disposable test environment.

Updated for the Phase 3 rules: voiding is gone (a paid receipt is corrected by
refunding the whole receipt), and refunds always cover the entire receipt.

Run after `./testenv.sh up`:  python3 test-phase2-api.py
"""
import json
import subprocess
import sys
import urllib.error
import urllib.request

from auth import auth_headers
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal as D

API = "http://127.0.0.1:8095/api"
DB = "pos_test"
RESULTS = []


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


def check(name, ok, detail=""):
    RESULTS.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  -> {detail}"))


def stock(pid):
    return D(sql(f"select stock_qty from products where id={pid}"))


def balance(cid):
    return D(sql(f"select balance from customers where id={cid}"))


def line(pid, qty, price, discount=0):
    return {"product_id": pid, "qty": qty, "sell_price": price, "discount": discount}


def sale(lines, **kw):
    return call("POST", "/transactions", {"lines": lines, **kw})


# ── setup ──
A, B = [int(x) for x in sql("select id from products where is_active order by id limit 2").split("\n")]
sql(f"update products set stock_qty=10 where id in ({A},{B})")
CUST = int(sql("insert into customers (name, credit_limit, balance) values ('Phase2 Test', 1000, 0) returning id").split("\n")[0])
if not sql("select id from shifts where cashier_id=1 and status='open'"):
    call("POST", "/shifts/open", {"opening_float": 100})
SHIFT = int(sql("select id from shifts where cashier_id=1 and status='open'"))
call("PUT", "/settings", {"store_name": "KEYPOS", "currency_symbol": "$", "tax_rate": 10, "low_stock_threshold": 5})
z_before = call("GET", f"/shifts/{SHIFT}/report")[1]["report"]
summ_before = call("GET", f"/reports/sales-summary?from_date={date.today()}&to_date={date.today()}")[1]
pnl_before = call("GET", f"/reports/pnl?from_date={date.today()}&to_date={date.today()}")[1]

# ── 1. multi-line sale deducts every line; discounts are charged ──
st, t1 = sale([line(A, 2, 5), line(B, 3, 4, 1)], discount_amount=2, payment_cash=20.90)
check("multi-line sale accepted", st == 201, t1)
check("totals: subtotal 22, discount 3, tax 1.90, total 20.90",
      (D(t1["subtotal"]), D(t1["discount_amount"]), D(t1["tax_amount"]), D(t1["total_amount"])) == (D("22"), D("3"), D("1.90"), D("20.90")), t1)
check("line totals include line discount", [D(l["line_total"]) for l in t1["transaction_lines"]] == [D("10"), D("11")], t1["transaction_lines"])
check("stock deducted on BOTH lines", (stock(A), stock(B)) == (D(8), D(7)), (stock(A), stock(B)))

# ── 2. rejected sales change nothing ──
st, err = sale([line(A, 1, 5), line(B, 100, 1)], payment_cash=200)
check("insufficient stock rejected", st == 400 and "Insufficient stock" in err["detail"], err)
check("rejected sale left stock alone", (stock(A), stock(B)) == (D(8), D(7)))
check("account sale needs a customer", sale([line(A, 1, 5)], payment_account=5.5)[0] == 400)
check("card cannot be overpaid", sale([line(A, 1, 5)], payment_card=50)[0] == 400)
check("underpayment rejected", sale([line(A, 1, 5)], payment_cash=1)[0] == 400)
check("discount above line amount rejected", sale([line(A, 1, 5, 6)], payment_cash=10)[0] == 400)

# ── 3. voiding is gone; an account sale is corrected by refunding it ──
st, err = call("POST", f"/transactions/{t1['id']}/void")
check("void route no longer exists", st in (404, 405), (st, err))
st, t2 = sale([line(A, 1, 100)], customer_id=CUST, payment_account=110)
check("account sale charged to customer", st == 201 and balance(CUST) == D(110), (st, t2, balance(CUST)))
st, r = call("POST", f"/transactions/{t2['id']}/refund", {"reason": "wrong item"})
check("refund of account sale accepted", st == 200 and r["status"] == "refunded", (st, r))
check("refund cleared the customer balance", balance(CUST) == D(0), balance(CUST))
check("refund put the stock back", stock(A) == D(8), stock(A))
check("cannot refund twice", call("POST", f"/transactions/{t2['id']}/refund", {"reason": "x"})[0] == 400)

# ── 4. credit limit ──
check("credit limit enforced", sale([line(A, 1, 1000)], customer_id=CUST, payment_account=1100)[0] == 400)

# ── 5. refunds always cover the whole receipt ──
st, t3 = sale([line(A, 1, 10), line(B, 1, 30)], customer_id=CUST, payment_account=44)
check("refund needs a reason", call("POST", f"/transactions/{t3['id']}/refund", {})[0] == 422)
check("blank reason rejected", call("POST", f"/transactions/{t3['id']}/refund", {"reason": "  "})[0] == 422)
lineA = next(l for l in t3["transaction_lines"] if l["product_id"] == A)
st, r3 = call("POST", f"/transactions/{t3['id']}/refund", {"reason": "damaged", "line_ids": [lineA["id"]]})
check("whole receipt refunded even if line_ids sent", st == 200 and r3["status"] == "refunded", (st, r3))
check("refunded_amount equals the receipt total", D(r3["refunded_amount"]) == D(t3["total_amount"]) == D("44"), r3.get("refunded_amount"))
check("every line marked fully refunded", all(D(l["refunded_qty"]) == D(l["qty"]) for l in r3["transaction_lines"]), r3["transaction_lines"])
check("all stock back and balance zero", (stock(A), stock(B), balance(CUST)) == (D(8), D(7), D(0)), (stock(A), stock(B), balance(CUST)))
check("one refund record with an RFD number and the tax",
      sql(f"select count(*) from refunds where transaction_id={t3['id']}") == "1"
      and sql(f"select tax_amount from refunds where transaction_id={t3['id']}") == "4.00"
      and sql(f"select ref_number from refunds where transaction_id={t3['id']}").startswith("RFD-"))
check("response carries the refund info", r3["refund"] and D(r3["refund"]["amount"]) == D("44") and r3["refund"]["reason"] == "damaged", r3.get("refund"))
check("refunded receipt is no longer refundable", r3["refundable"] is False, r3.get("refundable"))

# ── 6. cash refund comes out of the drawer ──
st, t4 = sale([line(A, 2, 10)], payment_cash=22)
call("POST", f"/transactions/{t4['id']}/refund", {"reason": "customer changed mind"})
check("cash refund recorded as cash", sql(f"select refund_cash, refund_card, refund_account from refunds where transaction_id={t4['id']}") == "22.00|0.00|0.00")

# ── 7. held tickets ──
stock_before_hold = stock(A)
st, h = sale([line(A, 3, 5)], status="held", notes="held")
check("held ticket does not touch stock", st == 201 and h["status"] == "held" and stock(A) == stock_before_hold, (st, h))
st, rs = call("POST", f"/transactions/{h['id']}/resume")
check("resume returns the ticket lines", st == 200 and len(rs["transaction_lines"]) == 1, rs)
check("resumed ticket is removed", call("GET", f"/transactions/{h['id']}")[0] == 404)

# ── 8. concurrent sales: unique numbers, exact stock ──
sql(f"update products set stock_qty=10 where id={A}")
with ThreadPoolExecutor(12) as pool:
    outcomes = list(pool.map(lambda _: sale([line(A, 1, 1)], payment_cash=1.10), range(12)))
ok = [b for s, b in outcomes if s == 201]
check("10 of 12 concurrent sales succeed with stock 10", len(ok) == 10, [s for s, _ in outcomes])
check("stock is exactly 0 after concurrent sales", stock(A) == D(0), stock(A))
refs = [b["ref_number"] for b in ok]
check("concurrent receipt numbers are unique", len(set(refs)) == len(refs), refs)
today = date.today().strftime("%Y%m%d")
check("receipt numbers follow TXN-YYYYMMDD-NNNN", all(r.startswith(f"TXN-{today}-") for r in refs), refs)
with ThreadPoolExecutor(6) as pool:
    pos = list(pool.map(lambda _: call("POST", "/purchases", {"supplier_id": None, "lines": [{"product_id": B, "qty": 1, "unit_cost": 1}]}), range(6)))
po_refs = [b["ref_number"] for s, b in pos if s == 201]
check("concurrent purchase numbers are unique", len(po_refs) == 6 and len(set(po_refs)) == 6, [s for s, _ in pos])

# ── 9. Z-report and ledger ──
# In-shift sales: t1 (22 gross / 3 disc / 1.90 tax / cash 20.90), t2 (100 / 10 / account 110, refunded),
# t3 (40 / 4 / account 44, refunded), t4 (20 / 2 / cash 22, refunded), 10 x 1.00 (+1.00 tax, cash 11).
z = call("GET", f"/shifts/{SHIFT}/report")[1]["report"]
diff = lambda k: D(str(z[k])) - D(str(z_before[k]))
check("Z gross counts every rung-up sale", diff("gross_sales") == D("192"), diff("gross_sales"))
check("Z refunds = 110 + 44 + 22 = 176", diff("total_refunds") == D("176"), diff("total_refunds"))
check("Z refund count = 3", diff("refund_count") == 3, diff("refund_count"))
check("Z net sales = 192 - 3 - 160 = 29", diff("net_sales") == D("29"), diff("net_sales"))
check("Z tax = 18.90 - 16 = 2.90", diff("tax_collected") == D("2.90"), diff("tax_collected"))
check("Z cash = 53.90 - 22 = 31.90", diff("cash_sales") == D("31.90"), diff("cash_sales"))
check("Z account nets to 0", diff("account_sales") == D("0"), diff("account_sales"))
st, ledger = call("GET", f"/customers/{CUST}/ledger")
entries = ledger["entries"]
check("ledger shows 2 sales and 2 refunds", sorted(e["type"] for e in entries) == ["refund", "refund", "sale", "sale"], [e["type"] for e in entries])
check("newest ledger balance matches customer balance", D(entries[0]["balance_after"]) == balance(CUST), entries[0])
st, maria = call("GET", "/customers/1/ledger")
if st == 200:  # customer #1 only exists in pre-2026-10-07 data (the fresh-start wipe removed it)
    check("legacy ledger ends on the stored balance", D(maria["entries"][0]["balance_after"]) == balance(1), maria["entries"][0])
check("customer with history cannot be deleted", call("DELETE", f"/customers/{CUST}")[0] == 409)

# ── 10. reports agree (deltas, so leftover data from earlier runs does not matter) ──
st, summ = call("GET", f"/reports/sales-summary?from_date={date.today()}&to_date={date.today()}")
check("sales summary: +176 refunded, +29 net",
      st == 200
      and D(str(summ["refund_total"])) - D(str(summ_before["refund_total"])) == D("176")
      and D(str(summ["net_sales"])) - D(str(summ_before["net_sales"])) == D("29"), summ)
st, pnl = call("GET", f"/reports/pnl?from_date={date.today()}&to_date={date.today()}")
check("P&L revenue = net sales ex tax",
      st == 200 and D(str(pnl["revenue"])) - D(str(pnl_before["revenue"])) == D("29"), pnl)
for path in ["cashier", "tax"]:
    st, _ = call("GET", f"/reports/{path}?from_date={date.today()}&to_date={date.today()}")
    check(f"{path} report ok", st == 200)

print(f"\n{sum(RESULTS)}/{len(RESULTS)} passed")
sys.exit(0 if all(RESULTS) else 1)
