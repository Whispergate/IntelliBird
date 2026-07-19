"""Alembic environment - async SQLAlchemy + DATABASE_URL from env."""
from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from app.models.base import Base  # noqa: E402
import app.models  # noqa: F401,E402 - ensures all tables are registered on Base.metadata

target_metadata = Base.metadata

# TimescaleDB-generated indexes that Alembic autogenerate must ignore
TIMESCALE_AUTO_INDEXES: set[str] = {"events_observed_at_idx"}


def include_name(name, type_, parent_names):  # type: ignore[no-untyped-def]
    if type_ == "index" and name in TIMESCALE_AUTO_INDEXES:
        return False
    return True


def get_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set - required by alembic/env.py")
    return url


def do_run_migrations(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_name=include_name,
        render_as_batch=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = create_async_engine(get_url(), poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
