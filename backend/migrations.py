"""Database migrations, run when the API starts.

Schema changes are Alembic revisions in alembic/versions. Databases created before
Alembic (Phase 5) have no alembic_version table: they are brought up to the baseline
with the idempotent LEGACY_PATCHES that used to run at every start, then stamped with
revision 0001 so Alembic takes over from there.
"""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

BASELINE = "0001"
BASELINE_TABLES = frozenset({
    "audit_log", "categories", "customer_payments", "customers", "expense_categories", "expenses",
    "price_edit_log", "products", "purchase_order_lines", "purchase_orders", "ref_counters", "refunds",
    "settings", "shifts", "stock_adjustments", "stock_movements", "suppliers", "sync_queue",
    "transaction_lines", "transactions", "units", "user_permissions", "users",
})
ALEMBIC_INI = Path(__file__).resolve().parent / "alembic.ini"

APPEND_ONLY_TABLES = ("audit_log", "stock_movements", "refunds", "customer_payments")

LEGACY_PATCHES = [
    "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS refunded_amount NUMERIC(12, 2) NOT NULL DEFAULT 0",
    "ALTER TABLE transaction_lines ADD COLUMN IF NOT EXISTS refunded_qty NUMERIC(10, 3) NOT NULL DEFAULT 0",
    "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS reissue_of_id INTEGER REFERENCES transactions(id)",
    "CREATE INDEX IF NOT EXISTS ix_transactions_reissue_of_id ON transactions (reissue_of_id)",
    "ALTER TABLE refunds ADD COLUMN IF NOT EXISTS ref_number VARCHAR(50) UNIQUE",
    "ALTER TABLE customer_payments ADD COLUMN IF NOT EXISTS method VARCHAR(10) NOT NULL DEFAULT 'cash'",
    "ALTER TABLE customer_payments ADD COLUMN IF NOT EXISTS shift_id INTEGER REFERENCES shifts(id)",
    "CREATE INDEX IF NOT EXISTS ix_customer_payments_shift_id ON customer_payments (shift_id)",
    "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS paid_from_drawer BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS shift_id INTEGER REFERENCES shifts(id)",
    "CREATE INDEX IF NOT EXISTS ix_expenses_shift_id ON expenses (shift_id)",
    "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS is_offline BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE sync_queue ADD COLUMN IF NOT EXISTS client_ref VARCHAR(100)",
    "ALTER TABLE sync_queue ADD COLUMN IF NOT EXISTS record_id INTEGER",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_sync_queue_device_client_ref "
    "ON sync_queue (device_id, client_ref) WHERE client_ref IS NOT NULL AND synced",
    "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS device_id VARCHAR(100)",
    "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS client_ref VARCHAR(100)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_transactions_device_client_ref "
    "ON transactions (device_id, client_ref) WHERE client_ref IS NOT NULL",
    """
    CREATE OR REPLACE FUNCTION forbid_change() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION '% is append-only; % is not allowed', TG_TABLE_NAME, TG_OP;
    END
    $$ LANGUAGE plpgsql
    """,
    *(
        statement
        for table in APPEND_ONLY_TABLES
        for statement in (
            f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}",
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION forbid_change()",
            f"DROP TRIGGER IF EXISTS {table}_no_truncate ON {table}",
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
            f"FOR EACH STATEMENT EXECUTE FUNCTION forbid_change()",
        )
    ),
]



async def migrate(conn: AsyncConnection) -> None:
    await conn.run_sync(_migrate)


def _migrate(conn: Connection) -> None:
    config = Config(str(ALEMBIC_INI))
    config.attributes["connection"] = conn
    tables = set(inspect(conn).get_table_names())
    if "alembic_version" not in tables and tables & BASELINE_TABLES:
        missing = BASELINE_TABLES - tables
        if missing:
            raise RuntimeError(
                f"Pre-Alembic database is missing tables {sorted(missing)}; "
                "upgrade it with the Phase 4b code (commit 481439b) first."
            )
        for statement in LEGACY_PATCHES:
            conn.execute(text(statement))
        command.stamp(config, BASELINE)
    command.upgrade(config, "head")
