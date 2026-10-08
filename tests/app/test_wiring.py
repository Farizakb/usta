from pathlib import Path

import pytest
from sqlalchemy import text

from usta.app.config import Settings
from usta.app.wiring import build_app
from usta.core.errors import ConfigError
from usta.core.run import StopReason
from usta.models.fake import FakeModel, call, reply

TODO_ITEMS = [
    {"content": "Hesabatı yoxla", "status": "pending"},
    {"content": "Müştəriyə zəng et", "status": "pending"},
]


@pytest.mark.pg
async def test_two_tool_task_runs_end_to_end_through_real_wiring(
    clean_db: str, tmp_path: Path
) -> None:
    files = tmp_path / "u1" / "files"
    files.mkdir(parents=True)
    (files / "qeydler.txt").write_text(
        "1. Hesabatı yoxla\n2. Müştəriyə zəng et\n", encoding="utf-8"
    )
    script = [
        call("file.read", {"path": "files/qeydler.txt"}),
        call("todo", {"items": TODO_ITEMS}),
        reply("İki tapşırıq tapdım və siyahıya saldım."),
    ]
    settings = Settings(profile="test", database_url=clean_db, workspace_root=tmp_path)
    app = await build_app(settings, env={}, model_overrides={"main": FakeModel(script)})
    try:
        await app.store.add_user("u1", "Test")
        run = await app.worker.execute(
            (await app.worker.submit("u1", "Qeydləri oxu və siyahı qur")).id
        )
        assert run.stop_reason == StopReason.DONE
        assert [t.content for t in run.todo] == ["Hesabatı yoxla", "Müştəriyə zəng et"]
        async with app.db.connect() as conn:
            n_calls = (
                await conn.execute(
                    text("SELECT count(*) FROM model_calls WHERE run_id = :r"), {"r": run.id}
                )
            ).scalar_one()
            tools = (
                await conn.execute(
                    text(
                        "SELECT tool, phase FROM tool_calls WHERE run_id = :r ORDER BY created_at"
                    ),
                    {"r": run.id},
                )
            ).all()
            n_events = (
                await conn.execute(
                    text("SELECT count(*) FROM run_events WHERE run_id = :r"), {"r": run.id}
                )
            ).scalar_one()
        assert n_calls == 3
        assert [tuple(t) for t in tools] == [
            ("file.read", "intent"),
            ("file.read", "done"),
            ("todo", "intent"),
            ("todo", "done"),
        ]
        assert n_events >= 9
    finally:
        await app.aclose()


async def test_model_overrides_are_refused_outside_the_test_profile() -> None:
    settings = Settings(profile="dev-free", database_url="postgresql+asyncpg://x@127.0.0.1/x")
    with pytest.raises(ConfigError, match="P8"):
        await build_app(
            settings, env={"GEMINI_API_KEY": "k"}, model_overrides={"main": FakeModel()}
        )


async def test_sdk_engine_is_not_wired_before_m3() -> None:
    settings = Settings(profile="dev-sub", database_url="postgresql+asyncpg://x@127.0.0.1/x")
    with pytest.raises(ConfigError, match="M3"):
        await build_app(settings, env={})
