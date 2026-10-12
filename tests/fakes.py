"""Test doubles. Never imported by usta/ (P8)."""

from collections import deque
from collections.abc import Callable, Collection, Sequence
from pathlib import Path

from usta.core.audit import ModelCallRecord, ToolCallRecord
from usta.core.events import Event
from usta.core.run import RunState, RunStatus
from usta.core.sandbox import ExecResult
from usta.core.verify import VerifyResult
from usta.core.workspace import RunDirs
from usta.models.fake import FakeModel, ScriptStep
from usta.models.gateway import Gateway
from usta.models.pricing import Price
from usta.ports import RunContext, VerifierPort
from usta.tools.pipeline import ToolPipeline
from usta.tools.registry import Tool, ToolContext, ToolOutput, ToolRegistry


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


async def _echo(args: dict, ctx: ToolContext) -> ToolOutput:
    return ToolOutput(f"echo: {args['text']}")


ECHO = Tool(
    name="test.echo",
    description="Echo text back.",
    input_schema={
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    },
    tier="local",
    fn=_echo,
)

# 10 input + 5 output tokens (the fake's default usage) cost $0.20 + $0.10 = $0.30.
FAKE_PRICE = Price(input=20_000, output=20_000, cache_read=0, cache_write=0)


async def _no_sleep(_seconds: float) -> None:
    return None


def make_context(
    script: list[ScriptStep],
    store: InMemoryStore,
    workspace_root: Path,
    *,
    tools: tuple[Tool, ...] = (ECHO,),
    price: Price = FAKE_PRICE,
    verifier: VerifierPort | None = None,
    skill_index: str = "",
) -> tuple[RunContext, FakeModel]:
    model = FakeModel(script)
    gateway = Gateway({"main": model}, {model.model_id: price}, audit=store, sleep=_no_sleep)
    pipeline = ToolPipeline(ToolRegistry(tools), audit=store, workspace_root=workspace_root)
    return RunContext(
        models=gateway, tools=pipeline, store=store, skill_index=skill_index, verifier=verifier
    ), model


ExecHandler = Callable[[str, RunDirs, tuple[str, ...], str], ExecResult]


class FakeSandbox:
    """SandboxPort for unit tests (P8: never wired outside the test profile)."""

    def __init__(self, handler: ExecHandler | None = None) -> None:
        self.calls: list[tuple[str, tuple[str, ...], str]] = []
        self.released: list[str] = []
        self.reaped_keep: list[set[str]] = []
        self._handler = handler or (lambda *_: ExecResult(exit_code=0, stdout="", stderr=""))

    async def exec(
        self,
        run_id: str,
        dirs: RunDirs,
        argv: Sequence[str],
        *,
        stdin: str = "",
        timeout_s: float = 60.0,
    ) -> ExecResult:
        self.calls.append((run_id, tuple(argv), stdin))
        return self._handler(run_id, dirs, tuple(argv), stdin)

    async def release(self, run_id: str) -> None:
        self.released.append(run_id)

    async def reap(self, keep: Collection[str]) -> list[str]:
        self.reaped_keep.append(set(keep))
        return []


class FakeVerifier:
    def __init__(self, results: list[VerifyResult]) -> None:
        self.results = deque(results)
        self.checked: list[int] = []  # number of messages in the run at each check

    async def check(self, run: RunState) -> VerifyResult:
        self.checked.append(len(run.messages))
        return self.results.popleft()
