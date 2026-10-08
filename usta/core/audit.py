"""Append-only audit records (P7, ADR-029)."""

from typing import Any, Literal

from usta.core.base import Frozen
from usta.core.model import Usage


class ModelCallRecord(Frozen):
    run_id: str | None
    user_id: str | None
    role: str
    provider: str
    model: str
    prompt_version: str
    attempt: int
    request: dict[str, Any]
    response: dict[str, Any] | None
    error: str | None
    usage: Usage
    cost_usd: float
    latency_ms: int


class ToolCallRecord(Frozen):
    run_id: str
    user_id: str
    call_id: str
    tool: str
    phase: Literal["intent", "done"]
    input: dict[str, Any]
    output: str | None = None
    is_error: bool | None = None
    latency_ms: int | None = None
