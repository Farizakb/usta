from pathlib import Path

import pytest
from sqlalchemy import text

from tests.fakes import FakeSandbox
from usta.app.config import Settings, load_profile
from usta.app.wiring import build_app, build_sandbox
from usta.core.errors import ConfigError
from usta.core.run import StopReason
from usta.core.sandbox import ExecResult
from usta.core.workspace import RunDirs
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
        reply('{"verdict": "pass", "reasons": []}'),
    ]
    settings = Settings(profile="test", database_url=clean_db, workspace_root=tmp_path)
    app = await build_app(
        settings,
        env={},
        model_overrides={"main": FakeModel(script)},
        sandbox_override=FakeSandbox(),
    )
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
        assert n_calls == 4
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


async def test_sandbox_overrides_are_refused_outside_the_test_profile() -> None:
    settings = Settings(profile="dev-openai", database_url="postgresql+asyncpg://x@127.0.0.1/x")
    with pytest.raises(ConfigError, match="P8: sandbox overrides"):
        await build_app(settings, env={"OPENAI_API_KEY": "k"}, sandbox_override=FakeSandbox())


async def test_startup_refuses_when_a_verifier_check_script_is_missing(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    for name in ("pdf-report", "xlsx", "docx", "charts"):
        d = skills / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n---\nbody\n")
        if name != "docx":
            (d / "check.py").write_text("# stub")
    settings = Settings(
        profile="test", database_url="postgresql+asyncpg://x@127.0.0.1/x", skills_dir=skills
    )
    with pytest.raises(ConfigError, match=r"(?s)startup refused:.*docx.*check\.py"):
        await build_app(settings, env={}, sandbox_override=FakeSandbox())


def test_build_sandbox_uses_gvisor_runtime_except_in_test() -> None:
    dev = Settings(
        profile="dev-openai",
        database_url="x",
        gvisor_runtime="runsc-kvm",
        skills_dir=Path("skills"),
    )
    sb = build_sandbox(load_profile("dev-openai", dev.config_dir), dev)
    args = sb.run_args("r1", RunDirs(files=Path("/w/f"), out=Path("/w/o")))
    assert "runsc-kvm" in args and "usta-sandbox:1" in args
    test = Settings(profile="test", database_url="x")
    assert "runc" in build_sandbox(load_profile("test", test.config_dir), test).run_args(
        "r1", RunDirs(files=Path("/w/f"), out=Path("/w/o"))
    )


@pytest.mark.pg
async def test_code_exec_and_skills_are_wired(clean_db: str, tmp_path: Path) -> None:
    sb = FakeSandbox(lambda *_: ExecResult(exit_code=0, stdout="4\n", stderr=""))
    script = [
        call("skill.load", {"name": "xlsx"}),
        call("code_exec", {"code": "print(2 + 2)"}),
        reply("Nəticə 4-dür."),
        reply('{"verdict": "pass", "reasons": []}'),
    ]
    model = FakeModel(script)
    settings = Settings(profile="test", database_url=clean_db, workspace_root=tmp_path)
    app = await build_app(settings, env={}, model_overrides={"main": model}, sandbox_override=sb)
    try:
        await app.store.add_user("u1", "Test")
        run = await app.worker.execute((await app.worker.submit("u1", "2+2 hesabla")).id)
        assert run.stop_reason == StopReason.DONE
        assert sb.calls[0][1:] == (("python", "-"), "print(2 + 2)")
        assert sb.released == [run.id]
        first = model.requests[0]
        assert {t.name for t in first.tools} >= {"code_exec", "skill.load", "file.write"}
        assert "pdf-report" in first.system[-1].text and first.system[-1].cache
        assert model.requests[-1].tools == ()  # the verifier's request
    finally:
        await app.aclose()
