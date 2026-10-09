"""Postgres RunStore + AuditSink (ADR-014, ADR-029). Audit tables are insert-only for usta_app."""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable

from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from usta.core.audit import ModelCallRecord, ToolCallRecord
from usta.core.errors import UnknownUser, UstaError
from usta.core.events import Event
from usta.core.run import RunState, RunStatus
from usta.store.tables import model_calls, run_checkpoints, run_events, runs, tool_calls, users

USER_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


class PgRunStore:
    def __init__(self, engine: AsyncEngine, *, profile: str) -> None:
        self._engine = engine
        self._profile = profile
        # Last checkpoint seq this instance loaded or wrote, per run. checkpoint() inserts exactly
        # known + 1, so a writer holding a stale view hits the (run_id, seq) PK and fails loudly.
        self._seq: dict[str, int] = {}

    async def add_user(self, user_id: str, display_name: str, scopes: Iterable[str] = ()) -> None:
        if not USER_ID.match(user_id):
            raise UstaError(
                f"invalid user id {user_id!r}: use 1-32 of a-z 0-9 _ - (it becomes a directory name)"
            )
        stmt = pg_insert(users).values(id=user_id, display_name=display_name, scopes=list(scopes))
        stmt = stmt.on_conflict_do_update(
            index_elements=[users.c.id],
            set_={"display_name": stmt.excluded.display_name, "scopes": stmt.excluded.scopes},
        )
        async with self._engine.begin() as conn:
            await conn.execute(stmt)

    async def create(self, run: RunState) -> None:
        try:
            async with self._engine.begin() as conn:
                await conn.execute(
                    insert(runs).values(
                        id=run.id,
                        user_id=run.user_id,
                        task=run.task,
                        engine=run.engine,
                        profile=self._profile,
                        status=run.status.value,
                        turns=run.turns,
                        cost_usd=run.cost_usd,
                    )
                )
                await conn.execute(
                    insert(run_checkpoints).values(
                        run_id=run.id, seq=0, state=run.model_dump(mode="json")
                    )
                )
            self._seq[run.id] = 0
        except IntegrityError as e:
            if "runs_user_id_fkey" in str(e.orig):
                raise UnknownUser(
                    f"unknown user {run.user_id!r}; add it with `usta user {run.user_id}`"
                ) from e
            raise

    async def load(self, run_id: str) -> RunState:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    select(run_checkpoints.c.seq, run_checkpoints.c.state)
                    .where(run_checkpoints.c.run_id == run_id)
                    .order_by(run_checkpoints.c.seq.desc())
                    .limit(1)
                )
            ).one_or_none()
        if row is None:
            raise KeyError(f"no run {run_id}")
        seq, state = row
        self._seq[run_id] = seq
        return RunState.model_validate(state)

    async def checkpoint(self, run: RunState) -> None:
        if run.id not in self._seq:
            await self.load(run.id)  # never seen by this instance: the current max is the base
        seq = self._seq[run.id] + 1
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(run_checkpoints).values(
                    run_id=run.id, seq=seq, state=run.model_dump(mode="json")
                )
            )
            await conn.execute(
                update(runs)
                .where(runs.c.id == run.id)
                .values(
                    status=run.status.value,
                    stop_reason=run.stop_reason.value if run.stop_reason else None,
                    turns=run.turns,
                    cost_usd=run.cost_usd,
                    updated_at=func.now(),
                    finished_at=func.now() if run.is_finished else None,
                )
            )
        self._seq[run.id] = seq  # only after the transaction committed

    async def ids_with_status(self, *statuses: RunStatus) -> list[str]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                select(runs.c.id)
                .where(runs.c.status.in_([s.value for s in statuses]))
                .order_by(runs.c.created_at)
            )
            return [str(r) for r in rows.scalars()]

    async def request_cancel(self, run_id: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                update(runs).where(runs.c.id == run_id).values(cancel_requested=True)
            )

    async def cancel_requested(self, run_id: str) -> bool:
        async with self._engine.connect() as conn:
            value = (
                await conn.execute(select(runs.c.cancel_requested).where(runs.c.id == run_id))
            ).scalar_one_or_none()
        return bool(value)

    async def append_event(self, event: Event, user_id: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(run_events).values(
                    id=str(uuid.uuid4()),
                    run_id=event.run_id,
                    user_id=user_id,
                    type=event.type,
                    data=event.data,
                )
            )

    async def events(self, run_id: str) -> list[Event]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                select(run_events.c.type, run_events.c.data)
                .where(run_events.c.run_id == run_id)
                .order_by(run_events.c.created_at)
            )
            return [Event(run_id=run_id, type=r.type, data=r.data) for r in rows]

    async def user_month_cost(self, user_id: str) -> float:
        async with self._engine.connect() as conn:
            total = (
                await conn.execute(
                    select(func.coalesce(func.sum(model_calls.c.cost_usd), 0.0)).where(
                        model_calls.c.user_id == user_id,
                        # UTC month start, independent of the session TimeZone (AT TIME ZONE 'UTC' both ways).
                        model_calls.c.created_at
                        >= func.timezone(
                            "UTC",
                            func.date_trunc("month", func.timezone("UTC", func.now())),
                        ),
                    )
                )
            ).scalar_one()
        return float(total)

    async def model_call(self, rec: ModelCallRecord) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(model_calls).values(
                    id=str(uuid.uuid4()),
                    run_id=rec.run_id,
                    user_id=rec.user_id,
                    role=rec.role,
                    provider=rec.provider,
                    model=rec.model,
                    prompt_version=rec.prompt_version,
                    attempt=rec.attempt,
                    request=rec.request,
                    response=rec.response,
                    error=rec.error,
                    input_tokens=rec.usage.input_tokens,
                    output_tokens=rec.usage.output_tokens,
                    cache_read_tokens=rec.usage.cache_read_tokens,
                    cache_write_tokens=rec.usage.cache_write_tokens,
                    cost_usd=rec.cost_usd,
                    latency_ms=rec.latency_ms,
                )
            )

    async def tool_call(self, rec: ToolCallRecord) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(tool_calls).values(
                    id=str(uuid.uuid4()),
                    run_id=rec.run_id,
                    user_id=rec.user_id,
                    call_id=rec.call_id,
                    tool=rec.tool,
                    phase=rec.phase,
                    input=rec.input,
                    output=rec.output,
                    is_error=rec.is_error,
                    latency_ms=rec.latency_ms,
                )
            )
