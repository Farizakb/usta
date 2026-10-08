import asyncio
from pathlib import Path

import pytest

from tests.fakes import InMemoryStore, make_context
from usta.core.audit import ModelCallRecord
from usta.core.budget import Budget
from usta.core.errors import UserBudgetExceeded
from usta.core.events import Event
from usta.core.model import Usage
from usta.core.run import RunState, RunStatus, StopReason
from usta.engines.own.loop import OwnEngine
from usta.models.fake import call, reply
from usta.worker import Worker

BUDGET = Budget(cost_step_usd=0.5)


def make_worker(script, tmp_path: Path, *, cap: float = 10.0, on_event=None):
    store = InMemoryStore()
    ctx, model = make_context(script, store, tmp_path)
    worker = Worker(
        store,
        OwnEngine(BUDGET),
        ctx,
        BUDGET,
        engine_name="own",
        user_monthly_cap_usd=cap,
        on_event=on_event,
    )
    return worker, store, model, ctx


async def test_submit_and_execute_persists_and_forwards_events(tmp_path: Path) -> None:
    seen: list[Event] = []

    async def on_event(ev: Event) -> None:
        seen.append(ev)

    worker, store, _, _ = make_worker([reply("Hazır.")], tmp_path, on_event=on_event)
    run = await worker.submit("u1", "Hesabat hazırla")
    assert run.status == RunStatus.QUEUED and run.cost_cap_usd == 0.5 and run.engine == "own"
    final = await worker.execute(run.id)
    assert final.stop_reason == StopReason.DONE
    assert [e.type for e in store.events] == ["run_started", "model_call", "finished"]
    assert seen == store.events


async def test_submit_refuses_empty_task_and_exhausted_monthly_budget(tmp_path: Path) -> None:
    worker, store, _, _ = make_worker([], tmp_path, cap=1.0)
    with pytest.raises(ValueError):
        await worker.submit("u1", "   ")
    await store.model_call(
        ModelCallRecord(
            run_id="old",
            user_id="u1",
            role="main",
            provider="fake",
            model="m",
            prompt_version="p",
            attempt=1,
            request={},
            response=None,
            error=None,
            usage=Usage(),
            cost_usd=1.0,
            latency_ms=1,
        )
    )
    with pytest.raises(UserBudgetExceeded):
        await worker.submit("u1", "yenə")


async def test_budget_park_then_approve_continues(tmp_path: Path) -> None:
    script = [call("test.echo", {"text": str(i)}) for i in range(2)] + [reply("bitdi")]
    worker, store, _, _ = make_worker(script, tmp_path)
    run = await worker.execute((await worker.submit("u1", "t")).id)
    assert run.status == RunStatus.AWAITING_USER
    assert await worker.execute(run.id) == await store.load(run.id)  # parked: no-op
    run = await worker.answer_budget(run.id, approve=True)
    assert run.stop_reason == StopReason.DONE and run.cost_cap_usd == pytest.approx(1.0)


async def test_budget_park_then_decline(tmp_path: Path) -> None:
    script = [call("test.echo", {"text": str(i)}) for i in range(2)]
    worker, store, _, _ = make_worker(script, tmp_path)
    run = await worker.execute((await worker.submit("u1", "t")).id)
    run = await worker.answer_budget(run.id, approve=False)
    assert run.stop_reason == StopReason.BUDGET_DECLINED
    assert store.events[-1].type == "finished"
    with pytest.raises(ValueError):
        await worker.answer_budget(run.id, approve=True)


async def test_cancel_parked_run_finishes_it_and_cancel_running_sets_flag(tmp_path: Path) -> None:
    script = [call("test.echo", {"text": str(i)}) for i in range(2)]
    worker, store, _, _ = make_worker(script, tmp_path)
    parked = await worker.execute((await worker.submit("u1", "t")).id)
    assert (await worker.cancel(parked.id)).stop_reason == StopReason.CANCELLED

    running = await worker.submit("u1", "t2")
    running.status = RunStatus.RUNNING
    await store.checkpoint(running)
    await worker.cancel(running.id)
    assert await store.cancel_requested(running.id)


async def test_recover_resumes_a_run_that_crashed_after_a_checkpoint(tmp_path: Path) -> None:
    worker, store, _, ctx = make_worker(
        [call("test.echo", {"text": "bir"}), reply("hazır")], tmp_path
    )
    run = await worker.submit("u1", "echo et")
    # Simulate a process crash right after the model call was checkpointed.
    events = OwnEngine(BUDGET).run(await store.load(run.id), ctx)
    async for ev in events:
        if ev.type == "model_call":
            break
    await events.aclose()
    assert (await store.load(run.id)).status == RunStatus.RUNNING
    assert store.tool_calls == []  # the tool never ran

    assert await worker.recover() == [run.id]
    final = await store.load(run.id)
    assert final.stop_reason == StopReason.DONE and final.final_text() == "hazır"
    assert [r.phase for r in store.tool_calls] == ["intent", "done"]  # executed exactly once


async def test_concurrent_budget_approvals_raise_cap_once(tmp_path: Path) -> None:
    script = [call("test.echo", {"text": str(i)}) for i in range(2)] + [reply("bitdi")]
    worker, store, _, _ = make_worker(script, tmp_path)
    run = await worker.execute((await worker.submit("u1", "t")).id)
    results = await asyncio.gather(
        worker.answer_budget(run.id, approve=True),
        worker.answer_budget(run.id, approve=True),
        return_exceptions=True,
    )
    assert sum(isinstance(r, ValueError) for r in results) == 1
    final = await store.load(run.id)
    assert final.stop_reason == StopReason.DONE and final.cost_cap_usd == pytest.approx(1.0)
    assert [e.type for e in store.events].count("finished") == 1


async def test_execute_on_a_live_run_does_not_start_a_second_loop(tmp_path: Path) -> None:
    inner: list[RunState] = []

    async def on_event(ev: Event) -> None:
        if ev.type == "run_started" and not inner:
            inner.append(await worker.execute(run.id))

    worker, store, _, _ = make_worker([reply("Hazır.")], tmp_path, on_event=on_event)
    run = await worker.submit("u1", "t")
    final = await worker.execute(run.id)
    assert final.stop_reason == StopReason.DONE
    assert len(inner) == 1 and not inner[0].is_finished
    assert [e.type for e in store.events] == ["run_started", "model_call", "finished"]


async def test_raising_on_event_does_not_kill_the_run(tmp_path: Path) -> None:
    async def on_event(ev: Event) -> None:
        raise RuntimeError("subscriber down")

    worker, store, _, _ = make_worker([reply("Hazır.")], tmp_path, on_event=on_event)
    final = await worker.execute((await worker.submit("u1", "t")).id)
    assert final.stop_reason == StopReason.DONE
    assert [e.type for e in store.events] == ["run_started", "model_call", "finished"]


async def test_recover_isolates_a_failing_run(tmp_path: Path) -> None:
    worker, store, _, ctx = make_worker([reply("hazır")], tmp_path)
    first = await worker.submit("u1", "a")
    second = await worker.submit("u1", "b")
    real = OwnEngine(BUDGET)

    class Flaky:
        def run(self, run: RunState, c):
            if run.id == first.id:
                raise RuntimeError("boom")
            return real.run(run, c)

    worker._engine = Flaky()  # noqa: SLF001
    ids = await worker.recover()
    assert set(ids) == {first.id, second.id}
    assert (await store.load(second.id)).stop_reason == StopReason.DONE
    assert not (await store.load(first.id)).is_finished
