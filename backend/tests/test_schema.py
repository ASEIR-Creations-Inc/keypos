"""The migrated database matches the models, and the audit tables are append-only."""
import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database import Base, engine
from migrations import ALEMBIC_INI
from tests.conftest import sale_body

APPEND_ONLY = ("audit_log", "stock_movements", "refunds", "customer_payments")


async def test_migrations_produce_exactly_the_models():
    async with engine.connect() as conn:
        diff = await conn.run_sync(lambda sync: compare_metadata(
            MigrationContext.configure(sync, opts={"compare_type": True, "compare_server_default": True}),
            Base.metadata,
        ))
    assert diff == []


async def test_database_is_at_the_latest_revision():
    async with engine.connect() as conn:
        version = (await conn.execute(text("select version_num from alembic_version"))).scalar()
    head = ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()
    assert version == head


@pytest.fixture(scope="module")
async def trail_rows(client):
    """At least one row in each append-only table: a sale, its refund and a customer payment."""
    await client.post("/shifts/close", json={"closing_cash": 0})
    assert (await client.post("/shifts/open", json={"opening_float": 0})).status_code == 201
    product = (await client.post("/products", json={"name": "Schema item", "sell_price": "0", "stock_qty": "5"})).json()
    sale = (await client.post("/transactions", json=sale_body((product["id"], "1", "5.00")))).json()
    assert (await client.post(f"/transactions/{sale['id']}/refund", json={"reason": "schema test"})).status_code == 200
    customer = (await client.post("/customers", json={"name": "Schema test"})).json()
    paid = await client.post(f"/customers/{customer['id']}/payment", json={"amount": "1.00"})
    assert paid.status_code == 201, paid.text


@pytest.mark.parametrize("table", APPEND_ONLY)
@pytest.mark.parametrize("statement", ["UPDATE {t} SET id = id", "DELETE FROM {t}", "TRUNCATE {t} CASCADE"])
async def test_audit_tables_refuse_changes(table, statement, trail_rows):
    async with engine.connect() as conn:
        assert (await conn.execute(text(f"select count(*) from {table}"))).scalar() > 0
        with pytest.raises(DBAPIError, match="append-only"):
            await conn.execute(text(statement.format(t=table)))
