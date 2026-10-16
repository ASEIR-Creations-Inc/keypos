"""pytest setup: a throwaway schema in the pos_pytest database, built by the real migrations.

pos_pytest is owned by pos_user (created once with `sudo -u postgres createdb -O pos_user
pos_pytest`); every run drops and recreates its public schema, so tests never see live
data. Set TEST_DATABASE_URL to use another database.
"""
import os
import re
from decimal import Decimal
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
ADMIN_PASSWORD = "pytest-only"


def _test_database_url() -> str:
    if os.environ.get("TEST_DATABASE_URL"):
        return os.environ["TEST_DATABASE_URL"]
    live = re.search(r"^DATABASE_URL=(.+)$", (BACKEND / ".env").read_text(), re.M).group(1).strip()
    return live.rsplit("/", 1)[0] + "/pos_pytest"


os.environ["DATABASE_URL"] = _test_database_url()

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402

from core.auth import hash_password  # noqa: E402
from database import async_session_factory, engine  # noqa: E402
from main import app  # noqa: E402
from migrations import migrate  # noqa: E402
from models.user import User, UserPermission, UserRole  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
async def database():
    assert engine.url.database == "pos_pytest" or os.environ.get("TEST_DATABASE_URL"), engine.url
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await migrate(conn)
    async with async_session_factory() as db:
        admin = User(name="Admin", username="admin", password_hash=hash_password(ADMIN_PASSWORD), role=UserRole.admin)
        admin.permissions = UserPermission()
        db.add(admin)
        await db.commit()
    yield
    await engine.dispose()


@pytest.fixture
async def db():
    async with async_session_factory() as session:
        yield session


def api_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test/api")


async def sign_in(c: httpx.AsyncClient, username: str, password: str) -> dict:
    response = await c.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    body = response.json()
    c.headers["Authorization"] = f"Bearer {body['access_token']}"
    return body


@pytest.fixture(scope="session")
async def client():
    """Signed in as the admin."""
    async with api_client() as c:
        await sign_in(c, "admin", ADMIN_PASSWORD)
        yield c


@pytest.fixture
async def anonymous():
    async with api_client() as c:
        yield c


@pytest.fixture
async def staff(client: httpx.AsyncClient):
    """Factory: create a user (role defaults, plus overrides) and return a client signed in as them."""
    opened: list[httpx.AsyncClient] = []

    async def make(role: str = "cashier", **permissions) -> httpx.AsyncClient:
        username = f"{role}_{os.urandom(3).hex()}"
        response = await client.post("/users", json={
            "name": username, "username": username, "password": "password-123", "role": role, **permissions,
        })
        assert response.status_code == 201, response.text
        c = api_client()
        opened.append(c)
        c.user = await sign_in(c, username, "password-123")
        return c

    yield make
    for c in opened:
        await c.aclose()


@pytest.fixture
async def shift(client: httpx.AsyncClient) -> dict:
    """A fresh open shift for user 1 (any shift left open by an earlier test is closed)."""
    await client.post("/shifts/close", json={"closing_cash": 0})
    response = await client.post("/shifts/open", json={"opening_float": 100})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def make_product(client: httpx.AsyncClient):
    count = 0

    async def make(stock: str = "10", cost: str = "2.00", **extra) -> dict:
        nonlocal count
        count += 1
        body = {"name": f"Item {count} {os.urandom(3).hex()}", "sell_price": "0", "cost_price": cost,
                "stock_qty": stock, **extra}
        response = await client.post("/products", json=body)
        assert response.status_code == 201, response.text
        return response.json()

    return make


async def stock_of(client: httpx.AsyncClient, product_id: int) -> Decimal:
    response = await client.get(f"/products/{product_id}")
    return Decimal(str(response.json()["stock_qty"]))


def sale_body(*lines: tuple[int, str, str], **extra) -> dict:
    """lines are (product_id, qty, price); paid in exact cash unless overridden."""
    total = sum((Decimal(q) * Decimal(p) for _, q, p in lines), Decimal("0"))
    return {
        "lines": [{"product_id": pid, "qty": q, "sell_price": p} for pid, q, p in lines],
        "payment_cash": str(total),
        **extra,
    }
