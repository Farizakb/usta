import pytest

from usta.core.events import Event
from usta.core.messages import Message, TextBlock, ToolCall, ToolResult
from usta.core.model import ModelResponse, Usage
from usta.core.run import PendingQuestion, RunState, RunStatus, StopReason


def make_run() -> RunState:
    return RunState.new(
        id="r1", user_id="u1", task="Hesabat hazırla", engine="own", cost_cap_usd=0.5
    )


def assistant(*blocks) -> ModelResponse:
    return ModelResponse(
        message=Message(role="assistant", content=blocks),
        usage=Usage(input_tokens=10, output_tokens=5),
        stop="end_turn",
        model="m",
        cost_usd=0.25,
    )


def test_new_run_is_queued_with_task_as_first_message() -> None:
    run = make_run()
    assert run.status == RunStatus.QUEUED
    assert run.messages == [Message.user_text("Hesabat hazırla")]
    assert (run.turns, run.cost_usd, run.stop_reason) == (0, 0.0, None)


def test_record_adds_message_turn_and_cost() -> None:
    run = make_run()
    run.record(assistant(TextBlock(text="hazır")))
    assert (run.turns, run.cost_usd) == (1, 0.25)
    assert run.final_text() == "hazır"


def test_pending_tool_calls_only_when_last_message_is_assistant_with_calls() -> None:
    run = make_run()
    assert run.pending_tool_calls() == []
    call = ToolCall(id="c1", name="todo", input={})
    run.record(assistant(call))
    assert run.pending_tool_calls() == [call]
    run.append_tool_results([ToolResult(call_id="c1", content="ok")])
    assert run.pending_tool_calls() == []


def test_append_tool_results_uses_one_user_message() -> None:
    run = make_run()
    run.append_tool_results(
        [ToolResult(call_id="a", content="1"), ToolResult(call_id="b", content="2")]
    )
    assert run.messages[-1].role == "user"
    assert [r.call_id for r in run.messages[-1].tool_results()] == ["a", "b"]


def test_park_and_finish() -> None:
    run = make_run()
    with pytest.raises(ValueError):
        run.park(RunStatus.RUNNING, PendingQuestion(kind="budget", text="?"))
    run.park(RunStatus.AWAITING_USER, PendingQuestion(kind="budget", text="Davam?"))
    assert run.is_parked and run.pending is not None
    run.finish(StopReason.BUDGET_DECLINED, "no")
    assert run.is_finished and not run.is_parked and run.pending is None
    assert Event.finished(run).data == {
        "stop_reason": "budget_declined",
        "detail": "no",
        "turns": 0,
        "cost_usd": 0.0,
    }


def test_state_json_round_trip() -> None:
    run = make_run()
    run.record(assistant(ToolCall(id="c1", name="file.read", input={"path": "files/ə.txt"})))
    again = RunState.model_validate_json(run.model_dump_json())
    assert again == run
    assert again.status == RunStatus.QUEUED


def test_append_tool_results_with_a_note() -> None:
    run = RunState.new(id="r", user_id="u", task="t", engine="own", cost_cap_usd=0.5)
    run.append_tool_results([ToolResult(call_id="c1", content="ok")], note="Xatırlatma")
    msg = run.messages[-1]
    assert msg.role == "user" and msg.tool_results()[0].call_id == "c1"
    assert isinstance(msg.content[-1], TextBlock) and msg.content[-1].text == "Xatırlatma"


def test_old_checkpoints_load_with_defaults() -> None:
    raw = RunState.new(id="r", user_id="u", task="t", engine="own", cost_cap_usd=0.5).model_dump()
    raw.pop("verify_failures")
    raw.pop("todo_reminded")
    run = RunState.model_validate(raw)
    assert run.verify_failures == 0 and run.todo_reminded is False
