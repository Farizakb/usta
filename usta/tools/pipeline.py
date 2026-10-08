"""Tool pipeline shared by both engines (SPEC §7):
registry -> JSON-schema validation -> audit(intent) -> execute -> audit(done).
M2 inserts verdict + taint after validation; M3 inserts layer-1 offload after execute."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from usta.core.audit import ToolCallRecord
from usta.core.errors import ToolInputError
from usta.core.messages import ToolCall, ToolResult
from usta.core.model import ToolSpec
from usta.core.run import RunState
from usta.core.tools import ToolOutcome
from usta.ports import AuditSink
from usta.tools.registry import ToolContext, ToolOutput, ToolRegistry

log = logging.getLogger(__name__)


class ToolPipeline:
    def __init__(
        self,
        registry: ToolRegistry,
        audit: AuditSink,
        workspace_root: Path,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._registry = registry
        self._audit = audit
        self._root = workspace_root
        self._clock = clock

    def specs(self) -> tuple[ToolSpec, ...]:
        return self._registry.specs()

    async def handle(self, call: ToolCall, run: RunState) -> ToolOutcome:
        tool = self._registry.get(call.name)
        if tool is None:
            available = ", ".join(self._registry.names())
            return await self._reject(
                call, run, f"unknown tool {call.name!r}; available: {available}"
            )
        if call.input_error:
            return await self._reject(
                call, run, f"invalid arguments for {call.name}: {call.input_error}"
            )
        errors = sorted(
            Draft202012Validator(tool.input_schema).iter_errors(call.input),
            key=lambda e: list(e.absolute_path),
        )
        if errors:
            detail = "; ".join(_format(e) for e in errors)
            return await self._reject(call, run, f"invalid arguments for {call.name}: {detail}")

        await self._audit.tool_call(self._record(call, run, "intent"))
        started = self._clock()
        try:
            out = await tool.fn(call.input, self._context(run))
        except ToolInputError as e:
            out = ToolOutput(str(e), is_error=True)
        except Exception as e:  # reported to the model, logged, audited; never swallowed silently
            log.exception("tool %s failed in run %s", call.name, run.id)
            out = ToolOutput(f"{call.name} failed: {type(e).__name__}: {e}", is_error=True)
        latency_ms = int((self._clock() - started) * 1000)
        await self._audit.tool_call(
            self._record(call, run, "done", out.content, out.is_error, latency_ms)
        )
        return ToolOutcome(
            result=ToolResult(call_id=call.id, content=out.content, is_error=out.is_error),
            event=out.event,
        )

    def _context(self, run: RunState) -> ToolContext:
        user_dir = self._root / run.user_id
        return ToolContext(
            run=run, files_dir=user_dir / "files", out_dir=user_dir / "runs" / run.id / "out"
        )

    async def _reject(self, call: ToolCall, run: RunState, message: str) -> ToolOutcome:
        await self._audit.tool_call(self._record(call, run, "done", message, True, 0))
        return ToolOutcome(result=ToolResult(call_id=call.id, content=message, is_error=True))

    @staticmethod
    def _record(
        call: ToolCall,
        run: RunState,
        phase: str,
        output: str | None = None,
        is_error: bool | None = None,
        latency_ms: int | None = None,
    ) -> ToolCallRecord:
        return ToolCallRecord(
            run_id=run.id,
            user_id=run.user_id,
            call_id=call.id,
            tool=call.name,
            phase=phase,
            input=call.input,
            output=output,
            is_error=is_error,
            latency_ms=latency_ms,
        )


def _format(error: ValidationError) -> str:
    where = "/".join(str(p) for p in error.absolute_path) or "(root)"
    return f"{where}: {error.message}"
