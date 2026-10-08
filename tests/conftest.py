"""Shared fixtures. Postgres tests need USTA_TEST_DATABASE_URL: an owner role on a throwaway DB."""

import asyncio
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine

TABLES = "users, runs, run_checkpoints, model_calls, tool_calls, run_events"


async def _execute(url: str, *statements: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            for statement in statements:
                await conn.execute(text(statement))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def migrated_db() -> str:
    url = os.environ.get("USTA_TEST_DATABASE_URL")
    if not url:
        pytest.fail(
            "USTA_TEST_DATABASE_URL is not set. Start Postgres with "
            "`docker compose -f deploy/compose.dev.yml up -d` and load .env (see .env.example)."
        )
    asyncio.run(_execute(url, "DROP SCHEMA IF EXISTS public CASCADE", "CREATE SCHEMA public"))
    os.environ["USTA_MIGRATION_DATABASE_URL"] = url
    command.upgrade(Config("alembic.ini"), "head")
    return url


@pytest.fixture
def clean_db(migrated_db: str) -> str:
    asyncio.run(_execute(migrated_db, f"TRUNCATE {TABLES} CASCADE"))
    return migrated_db


@pytest.fixture
async def db_engine(clean_db: str):
    engine = create_async_engine(clean_db)
    yield engine
    await engine.dispose()


@pytest.fixture
async def app_role_engine(clean_db: str):
    """Runs as usta_app, so store tests prove the app role's grants are enough."""
    engine = create_async_engine(clean_db)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_role(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("SET ROLE usta_app")
        cursor.close()
        # Commit, or the pool's rollback after a failed statement silently undoes SET ROLE.
        dbapi_connection.commit()

    yield engine
    await engine.dispose()
