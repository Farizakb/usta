"""Protocols between the core and everything else (P5). Only usta.app wires concrete classes."""

from collections.abc import AsyncIterator, Collection, Sequence
from dataclasses import dataclass
from typing import Protocol

from usta.core.audit import ModelCallRecord, ToolCallRecord
from usta.core.events import Event
from usta.core.messages import ToolCall
from usta.core.model import ModelCaps, ModelRequest, ModelResponse, ToolSpec
from usta.core.run import RunState, RunStatus
from usta.core.sandbox import ExecResult
from usta.core.tools import ToolOutcome
from usta.core.workspace import RunDirs


class ModelPort(Protocol):
    provider: str
    model_id: str
    caps: ModelCaps

    async def complete(self, req: ModelRequest) -> ModelResponse: ...


class ModelGateway(Protocol):
    """What engines call: routes by req.role; logging, retries and cost happen behind it."""

    async def complete(self, req: ModelRequest) -> ModelResponse: ...


class AuditSink(Protocol):
    async def model_call(self, rec: ModelCallRecord) -> None: ...
    async def tool_call(self, rec: ToolCallRecord) -> None: ...


class RunStore(Protocol):
    async def create(self, run: RunState) -> None: ...
    async def load(self, run_id: str) -> RunState: ...
    async def checkpoint(self, run: RunState) -> None: ...
    async def ids_with_status(self, *statuses: RunStatus) -> list[str]: ...
    async def request_cancel(self, run_id: str) -> None: ...
    async def cancel_requested(self, run_id: str) -> bool: ...
    async def append_event(self, event: Event, user_id: str) -> None: ...
    async def user_month_cost(self, user_id: str) -> float: ...


class ToolPipelinePort(Protocol):
    def specs(self) -> tuple[ToolSpec, ...]: ...
    async def handle(self, call: ToolCall, run: RunState) -> ToolOutcome: ...


class SandboxPort(Protocol):
    """One container per run, a fresh process per exec (SPEC §10, ADR-024)."""

    async def exec(
        self,
        run_id: str,
        dirs: RunDirs,
        argv: Sequence[str],
        *,
        stdin: str = "",
        timeout_s: float = 60.0,
    ) -> ExecResult: ...

    async def release(self, run_id: str) -> None: ...

    async def reap(self, keep: Collection[str]) -> list[str]: ...


@dataclass(frozen=True)
class RunContext:
    """What an engine gets; identical for both engines (SPEC §3.3). The run token (M2) is added when it exists."""

    models: ModelGateway
    tools: ToolPipelinePort
    store: RunStore
    skill_index: str = ""  # SkillSet.index_text(); joins the cached prefix (SPEC §7.1)


class EnginePort(Protocol):
    def run(self, run: RunState, ctx: RunContext) -> AsyncIterator[Event]: ...
