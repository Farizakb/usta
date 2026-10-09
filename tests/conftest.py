"""Shared fixtures. Postgres tests need USTA_TEST_DATABASE_URL: an owner role on a throwaway DB."""

import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine

from usta.core.sandbox import ExecResult
from usta.core.workspace import RunDirs
from usta.sandbox.docker import DockerSandbox, SandboxConfig

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


SANDBOX_IMAGE = os.environ.get("USTA_TEST_SANDBOX_IMAGE", "usta-sandbox:1")
SANDBOX_RUNTIME = os.environ.get("USTA_TEST_SANDBOX_RUNTIME", "runsc")


@pytest.fixture
def sandbox_config(tmp_path: Path) -> SandboxConfig:
    skills = Path("skills").resolve()
    if not skills.is_dir():
        skills = tmp_path / "skills"
        skills.mkdir()
    return SandboxConfig(
        image=SANDBOX_IMAGE,
        runtime=SANDBOX_RUNTIME,
        gvisor=SANDBOX_RUNTIME != "runc",
        skills_dir=skills,
        uid=os.getuid(),
        gid=os.getgid(),
    )


@dataclass
class Box:
    sandbox: DockerSandbox
    run_id: str
    dirs: RunDirs

    async def run(self, code: str, timeout_s: float = 60.0) -> ExecResult:
        return await self.sandbox.exec(
            self.run_id, self.dirs, ("python", "-"), stdin=code, timeout_s=timeout_s
        )

    async def check(self, skill: str, rel: str) -> dict:
        res = await self.sandbox.exec(
            self.run_id, self.dirs, ("python", f"/skills/{skill}/check.py", f"/out/{rel}")
        )
        assert res.exit_code == 0, res.stderr
        return json.loads(res.stdout.strip().splitlines()[-1])


@pytest.fixture
async def box(tmp_path: Path, sandbox_config: SandboxConfig):
    dirs = RunDirs(files=tmp_path / "files", out=tmp_path / "out")
    dirs.files.mkdir()
    dirs.out.mkdir()
    b = Box(DockerSandbox(sandbox_config), f"t-{uuid.uuid4().hex[:12]}", dirs)
    yield b
    await b.sandbox.release(b.run_id)
