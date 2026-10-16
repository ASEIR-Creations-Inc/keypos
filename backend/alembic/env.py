"""Alembic environment: async engine, URL from core.config, metadata from models.

When the API starts, main.py passes its own connection in config.attributes["connection"],
so migrations run inside the startup transaction instead of opening a second engine.
"""
import asyncio

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import models  # noqa: F401  (registers every table on Base.metadata)
from core.config import settings
from database import Base

target_metadata = Base.metadata


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    engine = create_async_engine(context.config.get_main_option("sqlalchemy.url") or settings.DATABASE_URL)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline (SQL script) mode is not used for KEYPOS; run against a database.")

connection = context.config.attributes.get("connection")
if connection is not None:
    _run(connection)
else:
    asyncio.run(_run_async())
