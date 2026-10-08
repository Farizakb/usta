"""In-process run worker (ADR-014). Runs are Postgres rows; parked runs are rows, not tasks."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from usta.core.budget import Budget
from usta.core.errors import UserBudgetExceeded
from usta.core.events import Event
from usta.core.run import RunState, RunStatus, StopReason
from usta.ports import EnginePort, RunContext, RunStore

EventCallback = Callable[[Event], Awaitable[None]]


class Worker:
    def __init__(
        self,
        store: RunStore,
        engine: EnginePort,
        ctx: RunContext,
        budget: Budget,
        *,
        engine_name: str,
        user_monthly_cap_usd: float,
        on_event: EventCallback | None = None,
    ) -> None:
        self._store = store
        self._engine = engine
        self._ctx = ctx
        self._budget = budget
        self._engine_name = engine_name
        self._user_cap = user_monthly_cap_usd
        self._on_event = on_event

    async def submit(self, user_id: str, task: str) -> RunState:
        if not task.strip():
            raise ValueError("task is empty")
        spent = await self._store.user_month_cost(user_id)
        if spent >= self._user_cap:
            raise UserBudgetExceeded(
                f"user {user_id!r} has spent ${spent:.2f} of ${self._user_cap:.2f} this month"
            )
        run = RunState.new(
            id=str(uuid.uuid4()),
            user_id=user_id,
            task=task,
            engine=self._engine_name,
            cost_cap_usd=self._budget.cost_step_usd,
        )
        await self._store.create(run)
        return run

    async def execute(self, run_id: str) -> RunState:
        run = await self._store.load(run_id)
        if run.is_finished or run.is_parked:
            return run
        async for event in self._engine.run(run, self._ctx):
            await self._emit(event, run.user_id)
        return run

    async def answer_budget(self, run_id: str, approve: bool) -> RunState:
        run = await self._store.load(run_id)
        if (
            run.status != RunStatus.AWAITING_USER
            or run.pending is None
            or run.pending.kind != "budget"
        ):
            raise ValueError(f"run {run_id} is not waiting for a budget answer")
        if not approve:
            run.finish(StopReason.BUDGET_DECLINED, "user declined to extend the budget")
            await self._store.checkpoint(run)
            await self._emit(Event.finished(run), run.user_id)
            return run
        run.cost_cap_usd += self._budget.cost_step_usd
        run.pending = None
        run.status = RunStatus.QUEUED
        await self._store.checkpoint(run)
        return await self.execute(run_id)

    async def cancel(self, run_id: str) -> RunState:
        run = await self._store.load(run_id)
        if run.is_finished:
            return run
        if run.is_parked or run.status == RunStatus.QUEUED:
            run.finish(StopReason.CANCELLED, "cancelled by user")
            await self._store.checkpoint(run)
            await self._emit(Event.finished(run), run.user_id)
            return run
        await self._store.request_cancel(run_id)  # running: the loop stops at its next step
        return run

    async def recover(self) -> list[str]:
        """On startup: resume runs a crash left running or queued (ADR-014 rule 3)."""
        run_ids = await self._store.ids_with_status(RunStatus.RUNNING, RunStatus.QUEUED)
        for run_id in run_ids:
            await self.execute(run_id)
        return run_ids

    async def _emit(self, event: Event, user_id: str) -> None:
        await self._store.append_event(event, user_id)
        if self._on_event is not None:
            await self._on_event(event)
