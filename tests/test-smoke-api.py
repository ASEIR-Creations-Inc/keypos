#!/usr/bin/env python3
"""Call every GET route the API publishes and fail on any server error.

Path parameters are filled with real ids from the test copy, so detail routes are
exercised too. Also deletes a throwaway category, unit and customer, whose routes
used to depend on implicitly loaded collections.
Run after `./testenv.sh up`:  python3 test-smoke-api.py
"""
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request

from auth import auth_headers
import uuid

ROOT = "http://127.0.0.1:8095"
DB = "pos_test"
RESULTS = []

ID_SQL = {
    "product_id": "select max(id) from products",
    "category_id": "select max(id) from categories",
    "unit_id": "select max(id) from units",
    "customer_id": "select max(id) from customers",
    "supplier_id": "select max(id) from suppliers",
    "purchase_id": "select max(id) from purchase_orders",
    "txn_id": "select max(id) from transactions",
    "transaction_id": "select max(id) from transactions",
    "shift_id": "select max(id) from shifts",
    "user_id": "select max(id) from users",
    "expense_id": "select max(id) from expenses",
}
QUERY = {"/api/sync/status": "?device_id=smoke"}


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(ROOT + path, data=data, method=method, headers=auth_headers())
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return r.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def sql(query):
    out = subprocess.run(["sudo", "-u", "postgres", "psql", "-d", DB, "-tAc", query], capture_output=True, text=True, check=True)
    return out.stdout.strip()


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  -> {detail}"))


def fill(path):
    def one(match):
        query = ID_SQL.get(match.group(1))
        return sql(query) if query else "1"
    return re.sub(r"\{(\w+)\}", one, path)


def main():
    with urllib.request.urlopen("http://127.0.0.1:8015/openapi.json") as r:
        spec = json.loads(r.read())
    gets = sorted(p for p, ops in spec["paths"].items() if "get" in ops)
    check(f"openapi lists GET routes ({len(gets)})", len(gets) > 30, len(gets))
    for path in gets:
        url = fill(path) + QUERY.get(path, "")
        st, raw = call("GET", url)
        check(f"GET {url} -> {st}", st < 500, raw[:300])

    run = uuid.uuid4().hex[:6]
    st, raw = call("POST", "/api/categories", {"name": f"Smoke {run}", "color": "#123456"})
    cat_id = json.loads(raw)["id"]
    st, raw = call("POST", "/api/units", {"name": f"sm{run}"})
    unit_id = json.loads(raw)["id"]
    st, raw = call("POST", "/api/products", {"name": f"Smoke item {run}", "sell_price": "1", "cost_price": "1",
                                             "stock_qty": "0", "category_id": cat_id, "unit_id": unit_id})
    prod_id = json.loads(raw)["id"]
    st, raw = call("DELETE", f"/api/categories/{cat_id}")
    check("delete category that has a product", st == 204, raw)
    st, raw = call("DELETE", f"/api/units/{unit_id}")
    check("delete unit that has a product", st == 204, raw)
    check("product kept, moved to no category/unit",
          sql(f"select coalesce(category_id::text,'-')||coalesce(unit_id::text,'-') from products where id={prod_id}") == "--")

    st, raw = call("POST", "/api/customers", {"name": f"Smoke cust {run}"})
    cust_id = json.loads(raw)["id"]
    st, raw = call("DELETE", f"/api/customers/{cust_id}")
    check("delete customer with no history", st == 204, raw)
    used = sql("select customer_id from transactions where customer_id is not null limit 1")
    if used:
        st, raw = call("DELETE", f"/api/customers/{used}")
        check("delete customer with sales is refused", st == 409, raw)

    passed = sum(RESULTS)
    print(f"\n{passed}/{len(RESULTS)} passed")
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
