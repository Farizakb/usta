"""Run events: streamed to the CLI/UI and stored in run_events (SPEC §13)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from usta.core.base import Frozen
from usta.core.run import RunState

EventType = Literal[
    "run_started",
    "model_call",
    "tool_call",
    "tool_result",
    "todo_updated",
    "step_done",
    "parked",
    "finished",
]


class Event(Frozen):
    run_id: str
    type: EventType
    data: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def finished(cls, run: RunState) -> Event:
        return cls(
            run_id=run.id,
            type="finished",
            data={
                "stop_reason": run.stop_reason.value if run.stop_reason else None,
                "detail": run.stop_detail,
                "turns": run.turns,
                "cost_usd": round(run.cost_usd, 6),
            },
        )

    @classmethod
    def parked(cls, run: RunState) -> Event:
        return cls(
            run_id=run.id,
            type="parked",
            data={
                "status": run.status.value,
                "question": run.pending.model_dump() if run.pending else None,
            },
        )
