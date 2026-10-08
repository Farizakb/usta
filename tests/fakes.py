"""Test doubles. Never imported by usta/ (P8)."""

from usta.core.audit import ModelCallRecord, ToolCallRecord
from usta.core.events import Event
from usta.core.run import RunState, RunStatus


class InMemoryStore:
    """RunStore + AuditSink double. Stores checkpoints as JSON, like Postgres does."""

    def __init__(self) -> None:
        self.checkpoints: dict[str, list[dict]] = {}
        self.cancel: set[str] = set()
        self.events: list[Event] = []
        self.model_calls: list[ModelCallRecord] = []
        self.tool_calls: list[ToolCallRecord] = []

    async def create(self, run: RunState) -> None:
        self.checkpoints[run.id] = [run.model_dump(mode="json")]

    async def load(self, run_id: str) -> RunState:
        return RunState.model_validate(self.checkpoints[run_id][-1])

    async def checkpoint(self, run: RunState) -> None:
        self.checkpoints[run.id].append(run.model_dump(mode="json"))

    async def ids_with_status(self, *statuses: RunStatus) -> list[str]:
        return [rid for rid, cps in self.checkpoints.items() if cps[-1]["status"] in statuses]

    async def request_cancel(self, run_id: str) -> None:
        self.cancel.add(run_id)

    async def cancel_requested(self, run_id: str) -> bool:
        return run_id in self.cancel

    async def append_event(self, event: Event, user_id: str) -> None:
        self.events.append(event)

    async def user_month_cost(self, user_id: str) -> float:
        return sum(r.cost_usd for r in self.model_calls if r.user_id == user_id)

    async def model_call(self, rec: ModelCallRecord) -> None:
        self.model_calls.append(rec)

    async def tool_call(self, rec: ToolCallRecord) -> None:
        self.tool_calls.append(rec)


class FakeClock:
    """Monotonic clock for tests: each call returns `now`, then advances it by `step`."""

    def __init__(self, step: float = 0.0) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        t = self.now
        self.now += self.step
        return t
