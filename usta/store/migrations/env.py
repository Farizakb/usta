"""Alembic env: async engine, owner role URL from USTA_MIGRATION_DATABASE_URL."""

import asyncio
import os

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from usta.store.tables import metadata

target_metadata = metadata


def _url() -> str:
    url = os.environ.get("USTA_MIGRATION_DATABASE_URL")
    if not url:
        raise RuntimeError("USTA_MIGRATION_DATABASE_URL is not set (owner role; see .env.example)")
    return url


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_run_online())
