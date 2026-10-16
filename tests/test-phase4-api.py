#!/usr/bin/env python3
"""Phase 4 checks: real offline mode — idempotent sync, device timestamps,
offline stock rules, Z-report offline rows, and sync status.

Self-contained: closes any open shift and works in its own one.
Run after `./testenv.sh up`:  python3 test-phase4-api.py
"""
import json
import subprocess
import sys
import urllib.error
import urllib.request

from auth import auth_headers
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

API = "http://127.0.0.1:8095/api"
DB = "pos_test"
RESULTS = []
DEVICE = "test-device-p4"
RUN = uuid.uuid4().hex[:8]  # per-run suffix: refs from an earlier run must not count as replays


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


def line(pid, qty, price):
    return {"product_id": pid, "qty": str(qty), "sell_price": str(price)}


def sync_push(actions, device=DEVICE):
    actions = [{**a, "client_ref": f"{a['client_ref']}-{RUN}"} if a.get("client_ref") else a for a in actions]
    return call("POST", "/sync", {"device_id": device, "actions": actions})


def offline_sale_action(pid, qty, price, ref, when=None, **payload_kw):
    payload = {"lines": [line(pid, qty, price)], "payment_cash": str(D(qty) * D(price)), **payload_kw}
    return {
        "action_type": "sale",
        "payload": payload,
        "client_ref": ref,
        "offline_created_at": (when or (datetime.now(timezone.utc) - timedelta(hours=2))).isoformat(),
    }


def fresh_product(name, qty, cost="1.00"):
    st, prod = call("POST", "/products", {"name": name, "sell_price": "0", "cost_price": cost, "stock_qty": str(qty), "is_active": True})
    assert st in (200, 201), prod
    return prod["id"]


def main():
    # ── Setup: tax off (other suites leave it at 10) and own open shift ──
    call("PUT", "/settings", {"store_name": "KEYPOS", "currency_symbol": "$", "tax_rate": 0, "low_stock_threshold": 5})
    call("POST", "/shifts/close", {"closing_cash": 0})
    st, shift = call("POST", "/shifts/open", {"opening_float": 100})
    check("open shift for phase 4", st in (200, 201) and shift and shift.get("id"), f"{st} {shift}")
    shift_id = shift["id"] if shift else None

    # ── Migration landed ─────────────────────────────────────────
    idx = sql("select count(*) from pg_indexes where indexname='uq_sync_queue_device_client_ref'")
    check("unique replay index exists", idx == "1")
    col = sql("select count(*) from information_schema.columns where table_name='transactions' and column_name='is_offline'")
    check("transactions.is_offline column exists", col == "1")

    # ── 1. Offline sale syncs, flagged, device time kept ─────────
    pid = fresh_product("P4 Item A", 10)
    rung_at = datetime.now(timezone.utc) - timedelta(hours=3)
    st, resp = sync_push([offline_sale_action(pid, 2, "5.00", "p4-sale-1", when=rung_at)])
    ok = st == 200 and resp["processed"] == 1 and resp["results"][0]["success"]
    check("offline sale accepted", ok, f"{st} {resp}")
    txn_id = resp["results"][0].get("record_id") if ok else None
    if txn_id:
        row = sql(f"select is_offline, shift_id, created_at from transactions where id={txn_id}")
        is_off, sh, created = row.split("|")
        check("sale flagged is_offline", is_off == "t", row)
        check("offline sale booked to open shift", sh == str(shift_id), row)
        created_dt = datetime.fromisoformat(created.replace(" ", "T"))
        if created_dt.tzinfo is None:
            created_dt = created_dt.replace(tzinfo=timezone.utc)
        drift = abs((created_dt - rung_at).total_seconds())
        check("sale keeps device timestamp", drift < 120, f"created={created} rung_at={rung_at}")
        check("stock deducted on sync", stock(pid) == D("8"), str(stock(pid)))
        check("no duplicate in queue", sql(f"select count(*) from sync_queue where client_ref='p4-sale-1-{RUN}'") == "1")

    # ── 2. Replay of the same ref never duplicates ───────────────
    st, resp = sync_push([offline_sale_action(pid, 2, "5.00", "p4-sale-1", when=rung_at)])
    r0 = resp["results"][0] if st == 200 else {}
    check("replay marked duplicate", st == 200 and r0.get("duplicate") is True, f"{st} {resp}")
    check("replay returns original record id", r0.get("record_id") == txn_id, f"{r0}")
    check("replay did not deduct stock again", stock(pid) == D("8"), str(stock(pid)))
    n_txns = sql(f"select count(*) from transactions where id={txn_id}")
    check("still exactly one transaction", n_txns == "1")

    # ── 3. Same ref, different device = a genuinely new sale ─────
    st, resp = sync_push([offline_sale_action(pid, 1, "5.00", "p4-sale-1", when=rung_at)], device="test-device-p4-B")
    r0 = resp["results"][0] if st == 200 else {}
    check("other device same ref is not a duplicate", st == 200 and r0.get("success") and not r0.get("duplicate"), f"{st} {resp}")
    check("other device sale deducted stock", stock(pid) == D("7"), str(stock(pid)))

    # ── 4. Offline oversell allowed but audited ──────────────────
    pid_b = fresh_product("P4 Item B", 3)
    st, resp = sync_push([offline_sale_action(pid_b, 9, "2.00", "p4-oversell")])
    ok = st == 200 and resp["results"][0]["success"]
    check("oversell offline sale accepted (goods already left the shop)", ok, f"{st} {resp}")
    check("stock went negative as it must", stock(pid_b) == D("-6"), str(stock(pid_b)))
    over_id = resp["results"][0].get("record_id") if ok else None
    if over_id:
        ref_num = sql(f"select ref_number from transactions where id={over_id}")
        entry = sql(f"select summary from audit_log where action='sale' and ref='{ref_num}' order by id desc limit 1")
        check("oversell carries offline marker in audit trail", "(offline)" in entry, entry)
        mv = sql(f"select count(*) from stock_movements where product_id={pid_b}")
        check("oversell has a stock movement row", int(mv) >= 1, mv)

    # ── 5. Offline account sale skips the credit limit ───────────
    st, cust = call("POST", "/customers", {"name": "P4 Credit Customer", "credit_limit": "10.00"})
    cid = cust["id"]
    pid_c = fresh_product("P4 Item C", 20)
    st, resp = sync_push([offline_sale_action(pid_c, 5, "10.00", "p4-account", customer_id=cid, payment_account="50.00", payment_cash="0")])
    check("offline account sale over credit limit accepted", st == 200 and resp["results"][0]["success"], f"{st} {resp}")
    bal = sql(f"select balance from customers where id={cid}")
    check("customer balance charged", D(bal) >= D("50"), bal)

    # ── 6. Register (online) still refuses oversell ──────────────
    st, resp = call("POST", "/transactions", {"lines": [line(pid_b, 50, "2.00")], "payment_cash": "100.00"})
    check("online sale over stock still refused", st == 400, f"{st} {resp}")

    # ── 7. Receipt numbers unique across online + offline ────────
    refs = sql("select ref_number, count(*) c from transactions where created_at::date = current_date group by ref_number having count(*) > 1")
    check("no duplicate receipt numbers today", refs == "", refs)

    # ── 8. Sync status endpoint ──────────────────────────────────
    st, resp = call("GET", f"/sync/status?device_id={DEVICE}")
    check("sync status ok", st == 200 and resp["device_id"] == DEVICE, f"{st} {resp}")
    check("sync status reports zero pending after drain", st == 200 and resp["pending_count"] == 0, f"{resp}")
    check("sync status has last synced time", st == 200 and resp.get("last_synced_at"), f"{resp}")

    # ── 9. Bad action is dead-lettered, batch keeps going ────────
    st, resp = sync_push([{"action_type": "bogus", "payload": {}, "client_ref": "p4-bogus"}])
    check("unknown action type fails gracefully", st == 200 and resp["failed"] == 1 and not resp["results"][0]["success"], f"{st} {resp}")
    dl = sql(f"select count(*) from sync_queue where client_ref='p4-bogus-{RUN}' and synced and record_id is null")
    check("unknown action dead-lettered (kept once, record_id null)", dl == "1", dl)
    pid_e = fresh_product("P4 Item E", 5)
    st, resp = sync_push([
        {"action_type": "bogus", "payload": {}, "client_ref": "p4-bogus"},
        offline_sale_action(pid_e, 1, "4.00", "p4-after-bogus"),
    ])
    ok_after = st == 200 and resp["failed"] == 1 and resp["results"][1]["success"]
    check("poisoned item does not break the rest of the batch", ok_after, f"{st} {resp}")
    dl2 = sql(f"select count(*) from sync_queue where client_ref='p4-bogus-{RUN}'")
    check("replayed poison ref is not re-queued", dl2 == "1", dl2)

    # ── 10. Offline expense + adjustment still route through audit (phase 3 regression via new path)
    st, resp = sync_push([
        {"action_type": "expense", "payload": {"amount": "12.50", "category_name": "P4 Transport", "description": "offline taxi", "paid_from_drawer": True}, "client_ref": "p4-exp"},
        {"action_type": "adjustment", "payload": {"product_id": pid, "adjustment": "-1", "reason": "offline damage found"}, "client_ref": "p4-adj"},
    ])
    check("offline expense synced", st == 200 and resp["results"][0]["success"], f"{st} {resp}")
    check("offline adjustment synced", st == 200 and resp["results"][1]["success"], f"{st} {resp}")
    check("adjustment moved stock", stock(pid) == D("6"), str(stock(pid)))

    # ── 11. Z-report shows the offline rows ──────────────────────
    st, z = call("POST", "/shifts/close", {"closing_cash": 0})
    report = (z or {}).get("report") or {}
    ok = st == 200 and report.get("offline_sales_count", 0) >= 4
    check("Z-report counts offline sales", ok, f"{st} count={report.get('offline_sales_count')}")
    check("Z-report totals offline sales", ok and D(str(report.get("offline_sales_total", 0))) > D("0"), f"{report.get('offline_sales_total')}")
    trail_off = [e for e in ((z or {}).get("activity") or []) if "offline" in json.dumps(e).lower()]
    check("Z-report trail mentions offline activity", len(trail_off) > 0, f"{len(trail_off)} entries")

    # ── 12. Syncing with no open shift still records the sale ────
    pid_d = fresh_product("P4 Item D", 5)
    st, resp = sync_push([offline_sale_action(pid_d, 1, "3.00", "p4-noshift")])
    ok = st == 200 and resp["results"][0]["success"]
    check("sale synced with no open shift accepted", ok, f"{st} {resp}")
    if ok:
        sh = sql(f"select shift_id from transactions where id={resp['results'][0]['record_id']}")
        check("no-shift sync leaves shift empty", sh in ("", "\\N", "None") or sh is None or sh == "", sh)

    # ── Summary ──────────────────────────────────────────────────
    passed = sum(1 for r in RESULTS if r)
    print(f"\n{passed}/{len(RESULTS)} checks passed")
    sys.exit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
