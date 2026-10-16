"""Alembic environment.

Reads the database URL from application settings rather than alembic.ini, so a
migration can never run against a different database than the application.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

from app.config import get_settings
from app.core.runtime import configure_event_loop_policy

# Importing the models registers every table on Base.metadata. Without this,
# autogenerate produces an empty migration and silently "detects" that your
# whole schema should be dropped.
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.session import async_dsn, create_engine

configure_event_loop_policy()

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
_settings = get_settings()


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Detect column type changes, which Alembic ignores by default and
        # which are exactly the changes most likely to lose data.
        compare_type=True,
        compare_server_default=True,
        # Keep constraint names deterministic, matching app.db.base.
        render_as_batch=False,
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting.

    Used to review exactly what a migration will do — including the locks it
    takes — before it touches anything real.
    """
    context.configure(
        url=async_dsn(_settings),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    engine = create_engine(_settings)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run_migrations)
            await connection.commit()
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
