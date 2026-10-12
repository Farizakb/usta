import functools
import re
from pathlib import Path

import pytest

from usta import cli
from usta.app.wiring import build_app
from usta.cli import build_parser, format_event, main
from usta.core.events import Event
from usta.core.messages import Message, TextBlock
from usta.core.model import Usage
from usta.core.run import PendingQuestion, RunState, RunStatus, StopReason
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


def _run_with_question() -> RunState:
    run = RunState.new(id="r1", user_id="u1", task="t", engine="own", cost_cap_usd=0.5)
    run.park(RunStatus.AWAITING_USER, PendingQuestion(kind="budget", text="Davam?"))
    return run


def _finished_run(reason: StopReason) -> RunState:
    run = RunState.new(id="r1", user_id="u1", task="t", engine="own", cost_cap_usd=0.5)
    run.finish(reason)
    return run


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        (Event(run_id="r1", type="run_started", data={"turns": 0}), "▶ run r1"),
        (
            Event(
                run_id="r1",
                type="model_call",
                data={
                    "turn": 1,
                    "model": "fake-model",
                    "stop": "tool_use",
                    "cost_usd": 0.0,
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
            ),
            "[turn 1] fake-model · tool_use · $0.0000",
        ),
        (
            Event(
                run_id="r1",
                type="tool_call",
                data={"call_id": "c1", "name": "todo", "input": {"items": []}},
            ),
            '  → todo {"items": []}',
        ),
        (
            Event(
                run_id="r1",
                type="tool_result",
                data={"call_id": "c1", "name": "todo", "is_error": False, "chars": 12},
            ),
            "  ← todo: ok (12 chars)",
        ),
        (
            Event(
                run_id="r1",
                type="todo_updated",
                data={
                    "items": [
                        {"content": "A", "status": "pending"},
                        {"content": "B", "status": "done"},
                    ]
                },
            ),
            "  ☐ [pending] A | [done] B",
        ),
        (
            Event(run_id="r1", type="step_done", data={"turn": 1, "cost_usd": 1.0}),
            "  · $1.0000 so far",
        ),
        (
            Event.parked(_run_with_question()),
            "⏸ awaiting_user: Davam?  (usta answer r1 yes|no)",
        ),
        (
            Event.finished(_finished_run(StopReason.DONE)),
            "■ done · 0 turns · $0.0000",
        ),
    ],
)
def test_format_event_covers_every_emitted_type(event: Event, expected: str) -> None:
    assert format_event(event) == expected


def _set_env(monkeypatch: pytest.MonkeyPatch, db: str, workspace: Path, user: str) -> None:
    monkeypatch.setenv("USTA_PROFILE", "test")
    monkeypatch.setenv("USTA_DATABASE_URL", db)
    monkeypatch.setenv("USTA_USER", user)
    monkeypatch.setenv("USTA_WORKSPACE_ROOT", str(workspace))


def _parking_factory() -> functools.partial:
    # fake-model is free, so the $0.50 cap would never be reached. The model id is priced
    # from the catalog: 200k output tokens at haiku's $5/M is $1.00, over the cap after the
    # first tool step, so the loop parks before its next model call.
    spend = Usage(output_tokens=200_000)
    script = [
        call("todo", {"items": [{"content": "Siyahı qur", "status": "in_progress"}]}, usage=spend)
    ]
    model = FakeModel(script, model_id="claude-haiku-4-5")
    return functools.partial(build_app, model_overrides={"main": model})


@pytest.mark.pg
def test_parked_run_exits_3_and_declining_the_budget_exits_1(
    clean_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _set_env(monkeypatch, clean_db, tmp_path, "u1")
    factory = _parking_factory()
    assert main(["user", "u1"], app_factory=factory) == 0
    capsys.readouterr()

    assert main(["run", "Siyahı qur"], app_factory=factory) == 3
    out = capsys.readouterr().out
    assert "usta answer" in out
    run_id = re.search(r"▶ run (\S+)", out).group(1)

    assert main(["answer", run_id, "no"], app_factory=factory) == 1
    assert "budget_declined" in capsys.readouterr().out


@pytest.mark.pg
def test_cancelling_a_parked_run_exits_0_and_says_cancelled(
    clean_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _set_env(monkeypatch, clean_db, tmp_path, "u1")
    factory = _parking_factory()
    assert main(["user", "u1"], app_factory=factory) == 0
    assert main(["run", "Siyahı qur"], app_factory=factory) == 3
    run_id = re.search(r"▶ run (\S+)", capsys.readouterr().out).group(1)

    assert main(["cancel", run_id], app_factory=factory) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "cancelled"


@pytest.mark.pg
def test_recover_on_an_empty_db_reports_zero(
    clean_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _set_env(monkeypatch, clean_db, tmp_path, "u1")
    factory = functools.partial(build_app, model_overrides={"main": FakeModel([])})
    assert main(["recover"], app_factory=factory) == 0
    assert capsys.readouterr().out.strip() == "recovered 0 run(s)"


@pytest.mark.pg
def test_invalid_user_id_is_a_clean_error(
    clean_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _set_env(monkeypatch, clean_db, tmp_path, "u1")
    factory = functools.partial(build_app, model_overrides={"main": FakeModel([])})
    assert main(["user", "../x"], app_factory=factory) == 2
    err = capsys.readouterr().err
    assert err.startswith("usta: invalid user id") and "Traceback" not in err


def test_format_verification_events() -> None:
    ok = Event(
        run_id="r",
        type="verification",
        data={"ok": True, "reasons": [], "attempt": 1, "cost_usd": 0.0},
    )
    bad = Event(
        run_id="r",
        type="verification",
        data={"ok": False, "reasons": ["a", "b"], "attempt": 1, "cost_usd": 0.0},
    )
    assert format_event(ok) == "  ✓ verified"
    assert format_event(bad) == "  ✗ verification failed: a; b"


def test_verification_failed_still_prints_the_answer_with_a_warning(capsys) -> None:
    run = RunState.new(id="r", user_id="u", task="t", engine="own", cost_cap_usd=0.5)
    run.messages.append(Message(role="assistant", content=(TextBlock(text="Nəticə"),)))
    run.finish(StopReason.VERIFICATION_FAILED, "PDF yoxdur")
    assert cli._exit_code(run) == 1
    out = capsys.readouterr().out
    assert "⚠ not verified: PDF yoxdur" in out and "Nəticə" in out
