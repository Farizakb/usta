from pathlib import Path

import pytest

from tests.fakes import ECHO, FakeClock, FakeVerifier, InMemoryStore, make_context
from usta.core.budget import Budget
from usta.core.errors import ProviderQuotaError
from usta.core.messages import Message, TextBlock, ToolCall
from usta.core.model import ModelResponse, Usage
from usta.core.run import RunState, RunStatus, StopReason
from usta.core.verify import VerifyResult
from usta.engines.own.loop import OwnEngine, build_request
from usta.engines.own.prompt import PLANNING_REMINDER, PROMPT_VERSION
from usta.models.fake import call, reply
from usta.tools.builtin.todo import TODO


async def drive(
    script,
    tmp_path: Path,
    *,
    budget: Budget | None = None,
    clock=None,
    run: RunState | None = None,
    verifier=None,
    tools=(ECHO,),
):
    budget = budget or Budget()
    store = InMemoryStore()
    ctx, model = make_context(script, store, tmp_path, tools=tools, verifier=verifier)
    run = run or RunState.new(
        id="r1", user_id="u1", task="Tapşırıq", engine="own", cost_cap_usd=budget.cost_step_usd
    )
    await store.create(run)
    engine = OwnEngine(budget, clock=clock) if clock else OwnEngine(budget)
    events = [ev async for ev in engine.run(run, ctx)]
    return run, events, model, store


async def test_text_reply_finishes_done(tmp_path: Path) -> None:
    run, events, model, store = await drive([reply("Hazırdır.")], tmp_path)
    assert run.stop_reason == StopReason.DONE and run.final_text() == "Hazırdır."
    assert [e.type for e in events] == ["run_started", "model_call", "finished"]
    assert (await store.load("r1")).stop_reason == StopReason.DONE  # checkpointed
    req = model.requests[0]
    assert req.system[0].cache and req.prompt_version == PROMPT_VERSION
    assert [t.name for t in req.tools] == ["test.echo"]
    assert (req.run_id, req.user_id) == ("r1", "u1")


async def test_tool_call_then_reply(tmp_path: Path) -> None:
    run, events, model, _ = await drive([call("test.echo", {"text": "bir"}), reply("ok")], tmp_path)
    assert run.stop_reason == StopReason.DONE and run.turns == 2
    assert [e.type for e in events] == [
        "run_started",
        "model_call",
        "tool_call",
        "tool_result",
        "step_done",
        "model_call",
        "finished",
    ]
    last_sent = model.requests[1].messages[-1]
    assert last_sent.role == "user" and last_sent.tool_results()[0].content == "echo: bir"


async def test_parallel_calls_produce_one_results_message_in_order(tmp_path: Path) -> None:
    both = ModelResponse(
        message=Message(
            role="assistant",
            content=(
                ToolCall(id="a", name="test.echo", input={"text": "1"}),
                ToolCall(id="b", name="test.echo", input={"text": "2"}),
            ),
        ),
        usage=Usage(input_tokens=10, output_tokens=5),
        stop="tool_use",
        model="fake-model",
    )
    run, *_ = await drive([both, reply("ok")], tmp_path)
    results = run.messages[2].tool_results()
    assert [r.call_id for r in results] == ["a", "b"]


async def test_max_turns(tmp_path: Path) -> None:
    script = [call("test.echo", {"text": str(i)}) for i in range(3)]
    run, events, model, _ = await drive(
        script, tmp_path, budget=Budget(max_turns=2, cost_step_usd=100)
    )
    assert run.stop_reason == StopReason.MAX_TURNS and len(model.requests) == 2
    assert events[-1].data["stop_reason"] == "max_turns"


async def test_cost_cap_parks_and_asks_to_continue(tmp_path: Path) -> None:
    script = [call("test.echo", {"text": str(i)}) for i in range(3)]  # $0.30 per call
    run, events, model, store = await drive(script, tmp_path, budget=Budget(cost_step_usd=0.5))
    assert run.status == RunStatus.AWAITING_USER and run.stop_reason is None
    assert run.pending is not None and run.pending.kind == "budget" and "+$0.50" in run.pending.text
    assert len(model.requests) == 2
    assert events[-1].type == "parked"
    assert (await store.load("r1")).status == RunStatus.AWAITING_USER


async def test_active_time_limit(tmp_path: Path) -> None:
    script = [call("test.echo", {"text": str(i)}) for i in range(5)]
    run, _, model, _ = await drive(
        script,
        tmp_path,
        budget=Budget(max_active_seconds=1200, cost_step_usd=100),
        clock=FakeClock(step=300),
    )
    assert run.stop_reason == StopReason.TIMEOUT and len(model.requests) == 1


async def test_cancel_request_stops_before_the_next_model_call(tmp_path: Path) -> None:
    store = InMemoryStore()
    ctx, model = make_context([reply("never")], store, tmp_path)
    run = RunState.new(id="r1", user_id="u1", task="t", engine="own", cost_cap_usd=0.5)
    await store.create(run)
    await store.request_cancel("r1")
    _ = [e async for e in OwnEngine(Budget()).run(run, ctx)]
    assert run.stop_reason == StopReason.CANCELLED and model.requests == []


async def test_provider_quota(tmp_path: Path) -> None:
    run, *_ = await drive([ProviderQuotaError("Console cap reached")], tmp_path)
    assert run.stop_reason == StopReason.PROVIDER_QUOTA and "Console cap" in (run.stop_detail or "")


async def test_unexpected_error_is_an_explicit_error_stop(tmp_path: Path) -> None:
    run, events, *_ = await drive([RuntimeError("boom")], tmp_path)
    assert run.stop_reason == StopReason.ERROR and run.stop_detail == "RuntimeError: boom"
    assert events[-1].type == "finished"


async def test_refusal_and_max_tokens_never_execute_tools(tmp_path: Path) -> None:
    for stop, detail in [("refusal", "refused"), ("max_tokens", "max_tokens")]:
        truncated = call("test.echo", {"text": "x"}).model_copy(update={"stop": stop})
        run, _, _, store = await drive([truncated], tmp_path)
        assert run.stop_reason == StopReason.ERROR and detail in (run.stop_detail or "")
        assert store.tool_calls == []


async def test_made_up_tool_and_bad_arguments_are_fed_back_and_the_run_continues(
    tmp_path: Path,
) -> None:
    bad_args = ModelResponse(
        message=Message(
            role="assistant",
            content=(
                ToolCall(
                    id="c2", name="test.echo", input={}, input_error="arguments are not valid JSON"
                ),
            ),
        ),
        usage=Usage(),
        stop="tool_use",
        model="fake-model",
    )
    script = [call("fleet.delete_all", {}), bad_args, reply("Bağışlayın, düzəltdim.")]
    run, *_ = await drive(script, tmp_path, budget=Budget(cost_step_usd=100))
    assert run.stop_reason == StopReason.DONE
    errors = [m.tool_results()[0] for m in run.messages if m.role == "user" and m.tool_results()]
    assert all(r.is_error for r in errors) and "unknown tool" in errors[0].content
    assert "not valid JSON" in errors[1].content


async def test_resume_executes_tool_calls_left_without_results(tmp_path: Path) -> None:
    run = RunState.new(id="r1", user_id="u1", task="t", engine="own", cost_cap_usd=0.5)
    run.record(call("test.echo", {"text": "yarımçıq"}, id="c9"))  # crashed before tools ran
    run.status = RunStatus.RUNNING
    run, _, model, _ = await drive([reply("bitdi")], tmp_path, run=run)
    assert run.stop_reason == StopReason.DONE
    sent = model.requests[0].messages[-1]
    assert (
        sent.tool_results()[0].call_id == "c9"
        and sent.tool_results()[0].content == "echo: yarımçıq"
    )


async def test_truncated_turn_is_never_checkpointed_as_running(tmp_path: Path) -> None:
    # A crash between record() and finish must not leave a running run whose last
    # message holds refused/truncated tool calls: resume would execute them.
    for stop in ("refusal", "max_tokens"):
        truncated = call("test.echo", {"text": "x"}).model_copy(update={"stop": stop})
        run, _, _, store = await drive([truncated], tmp_path)
        after_model = [cp for cp in store.checkpoints["r1"] if len(cp["messages"]) > 1]
        assert after_model and all(cp["status"] == "finished" for cp in after_model)
        assert run.stop_reason == StopReason.ERROR and stop in (run.stop_detail or "").replace(
            "refused", "refusal"
        )


async def test_tool_audit_sink_records_executed_calls(tmp_path: Path) -> None:
    # Positive control: store.tool_calls is the pipeline's audit sink, so `== []` above is meaningful.
    _, _, _, store = await drive([call("test.echo", {"text": "a"}), reply("ok")], tmp_path)
    assert [(r.tool, r.phase) for r in store.tool_calls] == [
        ("test.echo", "intent"),
        ("test.echo", "done"),
    ]


def test_skill_index_is_a_second_cached_system_block() -> None:
    run = RunState.new(id="r1", user_id="u1", task="t", engine="own", cost_cap_usd=0.5)
    plain = build_request(run, ())
    assert len(plain.system) == 1 and plain.system[0].cache
    with_index = build_request(run, (), skill_index="Skills:\n- charts: PNG charts")
    assert [b.cache for b in with_index.system] == [False, True]
    assert with_index.system[1].text.startswith("Skills:")
    assert with_index.prompt_version.startswith(PROMPT_VERSION + "+sk-")
    assert (
        with_index.prompt_version
        == build_request(run, (), skill_index="Skills:\n- charts: PNG charts").prompt_version
    )


PASS = VerifyResult(ok=True)


def fail(*reasons: str, cost: float = 0.0) -> VerifyResult:
    return VerifyResult(ok=False, reasons=reasons, cost_usd=cost)


async def test_verified_run_finishes_done(tmp_path: Path) -> None:
    v = FakeVerifier([PASS])
    run, events, _, _ = await drive([reply("Hazırdır.")], tmp_path, verifier=v)
    assert run.stop_reason == StopReason.DONE
    types = [e.type for e in events]
    assert types[-2:] == ["verification", "finished"]
    assert events[-2].data == {"ok": True, "reasons": [], "attempt": 1, "cost_usd": 0.0}


async def test_failed_verification_retries_once_with_reasons(tmp_path: Path) -> None:
    v = FakeVerifier([fail("PDF yoxdur"), PASS])
    run, events, model, _ = await drive(
        [reply("Bitdi."), reply("İndi bitdi.")], tmp_path, verifier=v
    )
    assert run.stop_reason == StopReason.DONE and run.verify_failures == 1
    retry = model.requests[1].messages[-1]
    assert retry.role == "user" and "- PDF yoxdur" in retry.text()
    assert [e.data["attempt"] for e in events if e.type == "verification"] == [1, 2]


async def test_second_failure_stops_verification_failed(tmp_path: Path) -> None:
    v = FakeVerifier([fail("a"), fail("b", "c")])
    run, _, _, store = await drive([reply("1"), reply("2")], tmp_path, verifier=v)
    assert run.stop_reason == StopReason.VERIFICATION_FAILED and run.stop_detail == "b; c"
    assert (await store.load("r1")).stop_reason == StopReason.VERIFICATION_FAILED
    assert run.final_text() == "2"  # the output is still there to show with a warning


async def test_verifier_cost_counts_toward_the_run(tmp_path: Path) -> None:
    v = FakeVerifier([VerifyResult(ok=True, cost_usd=0.07)])
    run, _, _, _ = await drive([reply("ok")], tmp_path, verifier=v)
    assert run.cost_usd == pytest.approx(0.30 + 0.07)


async def test_planning_reminder_once_on_turn_two_without_todo(tmp_path: Path) -> None:
    script = [
        call("test.echo", {"text": "1"}),
        call("test.echo", {"text": "2"}),
        call("test.echo", {"text": "3"}),
        reply("ok"),
    ]
    run, _, model, _ = await drive(script, tmp_path)
    after_turn = [m for m in run.messages if m.role == "user"][1:]  # skip the task
    notes = [m.content[-1].text for m in after_turn if isinstance(m.content[-1], TextBlock)]
    assert notes == [PLANNING_REMINDER] and run.todo_reminded
    assert isinstance(after_turn[1].content[-1], TextBlock)  # attached to turn 2's results


async def test_no_planning_reminder_when_todo_exists(tmp_path: Path) -> None:
    items = {"items": [{"content": "Faylı oxu", "status": "in_progress"}]}
    script = [call("todo", items), call("test.echo", {"text": "2"}), reply("ok")]
    run, _, _, _ = await drive(script, tmp_path, tools=(ECHO, TODO))
    assert not run.todo_reminded
