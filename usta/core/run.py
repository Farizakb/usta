"""Run state: everything a checkpoint stores (SPEC §4.2, §4.3)."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from usta.core.messages import Message, TextBlock, ToolCall, ToolResult
from usta.core.model import ModelResponse


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    AWAITING_USER = "awaiting_user"
    UNKNOWN_OUTCOME = "unknown_outcome"
    FINISHED = "finished"


PARKED_STATUSES = frozenset(
    {RunStatus.AWAITING_APPROVAL, RunStatus.AWAITING_USER, RunStatus.UNKNOWN_OUTCOME}
)


class StopReason(StrEnum):
    DONE = "done"
    VERIFICATION_FAILED = "verification_failed"
    MAX_TURNS = "max_turns"
    BUDGET_DECLINED = "budget_declined"
    TIMEOUT = "timeout"
    PROVIDER_QUOTA = "provider_quota"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    ERROR = "error"


class TodoItem(BaseModel):
    content: str
    status: Literal["pending", "in_progress", "done"]


class PendingQuestion(BaseModel):
    kind: Literal["budget"]  # M2 adds "ask_user"
    text: str


class RunState(BaseModel):
    schema_version: int = 1
    id: str
    user_id: str
    task: str
    engine: str
    cost_cap_usd: float
    status: RunStatus = RunStatus.QUEUED
    stop_reason: StopReason | None = None
    stop_detail: str | None = None
    messages: list[Message] = Field(default_factory=list)
    turns: int = 0
    cost_usd: float = 0.0
    active_seconds: float = 0.0
    todo: list[TodoItem] = Field(default_factory=list)
    pending: PendingQuestion | None = None
    verify_failures: int = 0  # SPEC §9: one retry, then verification_failed
    todo_reminded: bool = False  # ADR-016 planning reminder sent

    @classmethod
    def new(cls, *, id: str, user_id: str, task: str, engine: str, cost_cap_usd: float) -> RunState:
        return cls(
            id=id,
            user_id=user_id,
            task=task,
            engine=engine,
            cost_cap_usd=cost_cap_usd,
            messages=[Message.user_text(task)],
        )

    @property
    def is_finished(self) -> bool:
        return self.status == RunStatus.FINISHED

    @property
    def is_parked(self) -> bool:
        return self.status in PARKED_STATUSES

    def record(self, resp: ModelResponse) -> None:
        self.messages.append(resp.message)
        self.turns += 1
        self.cost_usd += resp.cost_usd

    def append_tool_results(self, results: list[ToolResult], note: str | None = None) -> None:
        content: tuple = tuple(results)
        if note:  # after the results: Anthropic wants tool_result blocks first
            content += (TextBlock(text=note),)
        self.messages.append(Message(role="user", content=content))

    def pending_tool_calls(self) -> list[ToolCall]:
        """Calls of the last assistant message that have no results yet (crash between checkpoints)."""
        if not self.messages or self.messages[-1].role != "assistant":
            return []
        return self.messages[-1].tool_calls()

    def park(self, status: RunStatus, question: PendingQuestion) -> None:
        if status not in PARKED_STATUSES:
            raise ValueError(f"{status} is not a parked status")
        self.status = status
        self.pending = question

    def finish(self, reason: StopReason, detail: str | None = None) -> None:
        self.status = RunStatus.FINISHED
        self.stop_reason = reason
        self.stop_detail = detail
        self.pending = None

    def final_text(self) -> str:
        for msg in reversed(self.messages):
            if msg.role == "assistant":
                return msg.text()
        return ""
