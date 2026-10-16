<h1 align="center">KEYPOS</h1>

<p align="center">
  <b>A point of sale for small shops, with a full audit trail and real offline selling.</b><br>
  FastAPI · PostgreSQL · installable web app (PWA) for cheap Android phones
</p>

---

KEYPOS is a point-of-sale system built for real small shops: mini-markets, bottle stores,
kiosks and wholesalers. It was designed in a working shop, on cheap Android phones, with
unreliable internet, and with one rule: **every movement of stock, cash or card must be
traceable to a person, a shift and a reason.**

It is in daily use in a shop in Luanda, Angola (Kwanza currency, Portuguese and English).

## Screenshots

| Register | Z-report | Inventory |
|---|---|---|
| <img src="docs/images/phone-02-register.png" width="240"> | <img src="docs/images/phone-zreport.png" width="240"> | <img src="docs/images/phone-inventory.png" width="240"> |

| Sales summary | Recent sales & refunds | Day Sheet app |
|---|---|---|
| <img src="docs/images/tablet-report-sales.png" width="300"> | <img src="docs/images/phone-recent-sales.png" width="240"> | <img src="docs/images/sheet-01-login.png" width="240"> |

<sub>Screenshots use a fictional demo shop.</sub>

## Features

**Selling**
- Fast register with search-as-you-type, categories, held tickets and per-line discounts
- Cash, card, customer-account and split payments
- Prices typed at the till or fixed in the catalogue; every price change is logged

**Money you can trust**
- Shifts with opening float, counted cash and an end-of-shift **Z-report**
- **Whole-receipt refunds only**, with a mandatory reason, and only while the shift is open
- Re-issue a refunded receipt as a new linked receipt
- An **append-only audit trail**: database triggers refuse edits or deletes of audit records

**Stock**
- Live stock levels that can't be oversold online
- Purchase orders with weighted-average costing
- Stock adjustments that require a reason
- Low-stock, inventory value, profit & loss, tax and per-cashier reports

**Works offline**
- Sales made without internet are queued on the device (IndexedDB) and synced later
- Duplicate-proof sync: every sale carries a device id and client reference, so a retried sale is never recorded twice
- The device keeps its own stock count so it won't sell 11 when it has 9
- A service worker lets the app open with no connection at all

**Day Sheet**
- A separate, lightweight **KEYPOS Sheet** app for staff who only record the day's sales and expenses
- Manager approval before anything touches stock or cash; approval is all-or-nothing
- Excel (`.xlsx`) day sheets in Portuguese and English for phones with free Excel

**People**
- Roles (admin, manager, cashier, day sheet) with per-person permissions enforced by the server
- Every action is recorded under the signed-in user; 12-hour logins with refresh, and a deactivated account is signed out on its next request

## Architecture

```
frontend/   plain ES5 JavaScript PWA (runs on old Android WebViews), no build step
  sheet/    the separate Day Sheet app
backend/    FastAPI + async SQLAlchemy + PostgreSQL, Alembic migrations
  routers/  HTTP API          services/  business rules (sales, audit, day sheets, ...)
  models/   database tables   schemas/   request/response models
tests/      API and browser (Puppeteer) suites run against a disposable test database
tools/      stamp.py: content-hash cache busting for the JS files and service worker
```

The web server (nginx) serves `frontend/` and forwards `/api/` to the backend.

## Running it

Requires Python 3.12+, PostgreSQL 14+ and nginx.

```bash
cd backend
python -m venv venv && . venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env                     # set SECRET_KEY and DATABASE_URL
uvicorn main:app --host 127.0.0.1 --port 8005
```

Migrations run automatically at start-up. `python manage.py set-password <user> --generate`
resets a password from the server console. A command to create the first admin on an empty
database is not there yet (see Roadmap).

Minimal nginx site:

```nginx
server {
    listen 80;
    root /path/to/keypos/frontend;
    index index.html;
    location /api/ { proxy_pass http://127.0.0.1:8005; }
}
```

Put it behind HTTPS before real use: logins and the offline start-up both need it.

## Tests

```bash
cd backend && pytest -q                  # 101 tests, on a throwaway PostgreSQL database
cd tests && ./testenv.sh up && ./sweep.sh  # 21 API + browser suites against a test copy
```

After changing any frontend JavaScript, run `python3 tools/stamp.py` (`tests/check-shell.py` enforces it).

## Roadmap

- `manage.py create-admin` for a first install on an empty database
- Standalone builds that run without a server: Android APK and Windows/macOS/Linux desktop apps (working prototypes exist)
- Docker image for self-hosting
- Hosted option for shops that don't want to run a server

---

<p align="center">
  KEYPOS is created by <b>ASEIR Creations Inc</b>.
</p>
