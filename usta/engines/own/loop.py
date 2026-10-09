"""Usta's own asyncio turn loop (SPEC §4.1). M0: no context management, sequential tools."""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import AsyncIterator, Callable

from usta.core.budget import Budget
from usta.core.errors import ProviderQuotaError
from usta.core.events import Event
from usta.core.messages import ToolCall
from usta.core.model import ModelRequest, SystemBlock, ToolSpec
from usta.core.run import PendingQuestion, RunState, RunStatus, StopReason
from usta.engines.own.prompt import PROMPT_VERSION, SYSTEM_PROMPT
from usta.ports import RunContext

log = logging.getLogger(__name__)


def build_request(
    run: RunState, tools: tuple[ToolSpec, ...], skill_index: str = ""
) -> ModelRequest:
    system = (SystemBlock(text=SYSTEM_PROMPT, cache=not skill_index),)
    version = PROMPT_VERSION
    if skill_index:  # stable per skill set, so the cached prefix stays byte-identical (R10)
        system += (SystemBlock(text=skill_index, cache=True),)
        version += "+sk-" + hashlib.sha256(skill_index.encode("utf-8")).hexdigest()[:8]
    return ModelRequest(
        role="main",
        system=system,
        messages=tuple(run.messages),
        tools=tools,
        prompt_version=version,
        run_id=run.id,
        user_id=run.user_id,
    )


class _ActiveTimer:
    """Adds wall-clock time to run.active_seconds while the loop runs; parked time never counts."""

    def __init__(self, run: RunState, clock: Callable[[], float]) -> None:
        self._run = run
        self._clock = clock
        self._last = clock()

    def tick(self) -> None:
        now = self._clock()
        self._run.active_seconds += now - self._last
        self._last = now


class OwnEngine:
    name = "own"

    def __init__(self, budget: Budget, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._budget = budget
        self._clock = clock

    async def run(self, run: RunState, ctx: RunContext) -> AsyncIterator[Event]:
        timer = _ActiveTimer(run, self._clock)
        run.status = RunStatus.RUNNING
        yield Event(run_id=run.id, type="run_started", data={"turns": run.turns})
        try:
            if pending := run.pending_tool_calls():  # crashed between checkpoints
                async for ev in self._execute(pending, run, ctx):
                    yield ev
                timer.tick()
                await ctx.store.checkpoint(run)
            while True:
                timer.tick()
                if await ctx.store.cancel_requested(run.id):
                    yield await self._finish(
                        run, ctx, timer, StopReason.CANCELLED, "cancelled by user"
                    )
                    return
                limit = self._budget.check(run)
                if limit == "max_turns":
                    yield await self._finish(
                        run, ctx, timer, StopReason.MAX_TURNS, f"{run.turns} turns"
                    )
                    return
                if limit == "timeout":
                    detail = f"{run.active_seconds:.0f}s of active time"
                    yield await self._finish(run, ctx, timer, StopReason.TIMEOUT, detail)
                    return
                if limit == "cost":
                    run.park(
                        RunStatus.AWAITING_USER,
                        PendingQuestion(
                            kind="budget",
                            text=(
                                f"This run has spent ${run.cost_usd:.2f} of its "
                                f"${run.cost_cap_usd:.2f} budget. Continue with "
                                f"+${self._budget.cost_step_usd:.2f}?"
                            ),
                        ),
                    )
                    await ctx.store.checkpoint(run)
                    yield Event.parked(run)
                    return

                resp = await ctx.models.complete(
                    build_request(run, ctx.tools.specs(), ctx.skill_index)
                )
                run.record(resp)
                timer.tick()
                # Refused/truncated turns must not be checkpointed as running: a crash then
                # would make resume execute their (incomplete) tool calls. _finish checkpoints.
                bad_stop = {
                    "refusal": "model refused the request",
                    "max_tokens": "model output hit max_tokens before finishing",
                }.get(resp.stop)
                if bad_stop is None:
                    await ctx.store.checkpoint(run)
                yield Event(
                    run_id=run.id,
                    type="model_call",
                    data={
                        "turn": run.turns,
                        "model": resp.model,
                        "stop": resp.stop,
                        "cost_usd": resp.cost_usd,
                        "usage": resp.usage.model_dump(),
                    },
                )
                if bad_stop is not None:
                    yield await self._finish(run, ctx, timer, StopReason.ERROR, bad_stop)
                    return
                calls = resp.tool_calls()
                if not calls:
                    yield await self._finish(run, ctx, timer, StopReason.DONE)
                    return
                async for ev in self._execute(calls, run, ctx):
                    yield ev
                timer.tick()
                await ctx.store.checkpoint(run)
                yield Event(
                    run_id=run.id,
                    type="step_done",
                    data={"turn": run.turns, "cost_usd": round(run.cost_usd, 6)},
                )
        except ProviderQuotaError as e:
            yield await self._finish(run, ctx, timer, StopReason.PROVIDER_QUOTA, str(e))
        except Exception as e:
            log.exception("run %s failed", run.id)
            yield await self._finish(run, ctx, timer, StopReason.ERROR, f"{type(e).__name__}: {e}")

    async def _execute(
        self, calls: list[ToolCall], run: RunState, ctx: RunContext
    ) -> AsyncIterator[Event]:
        results = []
        for call in calls:  # sequential; parallel execution is a later optimisation
            yield Event(
                run_id=run.id,
                type="tool_call",
                data={"call_id": call.id, "name": call.name, "input": call.input},
            )
            outcome = await ctx.tools.handle(call, run)
            results.append(outcome.result)
            if outcome.event is not None:
                yield outcome.event
            yield Event(
                run_id=run.id,
                type="tool_result",
                data={
                    "call_id": call.id,
                    "name": call.name,
                    "is_error": outcome.result.is_error,
                    "chars": len(outcome.result.content),
                },
            )
        run.append_tool_results(results)

    async def _finish(
        self,
        run: RunState,
        ctx: RunContext,
        timer: _ActiveTimer,
        reason: StopReason,
        detail: str | None = None,
    ) -> Event:
        timer.tick()
        run.finish(reason, detail)
        await ctx.store.checkpoint(run)
        return Event.finished(run)
