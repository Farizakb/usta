import functools
from pathlib import Path

import pytest

from usta.app.wiring import build_app
from usta.cli import build_parser, format_event, main
from usta.core.events import Event
from usta.models.fake import FakeModel, call, reply


def test_parser_commands() -> None:
    p = build_parser()
    assert p.parse_args(["run", "Hesabat hazırla"]).task == "Hesabat hazırla"
    assert p.parse_args(["answer", "r1", "yes"]).decision == "yes"
    with pytest.raises(SystemExit):
        p.parse_args(["answer", "r1", "maybe"])
    assert p.parse_args(["user", "fariz", "--scope", "fleet:read"]).scope == ["fleet:read"]


def test_format_event_keeps_azerbaijani_readable() -> None:
    ev = Event(
        run_id="r1",
        type="tool_call",
        data={"call_id": "c", "name": "file.read", "input": {"path": "files/qeydlər.txt"}},
    )
    assert format_event(ev) == '  → file.read {"path": "files/qeydlər.txt"}'
    fin = Event(
        run_id="r1",
        type="finished",
        data={"stop_reason": "done", "detail": None, "turns": 2, "cost_usd": 0.0012},
    )
    assert format_event(fin) == "■ done · 2 turns · $0.0012"


def test_missing_settings_are_a_clean_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.delenv("USTA_PROFILE", raising=False)
    assert main(["recover"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("usta: ") and "profile" in err and "Traceback" not in err


@pytest.mark.pg
def test_cli_runs_a_task_end_to_end(
    clean_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv("USTA_PROFILE", "test")
    monkeypatch.setenv("USTA_DATABASE_URL", clean_db)
    monkeypatch.setenv("USTA_USER", "u1")
    monkeypatch.setenv("USTA_WORKSPACE_ROOT", str(tmp_path))
    script = [
        call("todo", {"items": [{"content": "Siyahı qur", "status": "done"}]}),
        reply("Hazırdır, ə ğ ı ş."),
    ]
    factory = functools.partial(build_app, model_overrides={"main": FakeModel(script)})

    assert main(["user", "u1", "--name", "Test"], app_factory=factory) == 0
    assert main(["run", "Siyahı qur"], app_factory=factory) == 0
    out = capsys.readouterr().out
    assert "→ todo" in out and "■ done" in out
    assert out.rstrip().endswith("Hazırdır, ə ğ ı ş.")


@pytest.mark.pg
def test_unknown_user_is_a_clean_error(
    clean_db: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv("USTA_PROFILE", "test")
    monkeypatch.setenv("USTA_DATABASE_URL", clean_db)
    monkeypatch.setenv("USTA_USER", "ghost")
    factory = functools.partial(build_app, model_overrides={"main": FakeModel([])})
    assert main(["run", "salam"], app_factory=factory) == 2
    assert "usta user ghost" in capsys.readouterr().err
