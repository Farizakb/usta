"""Usta's own message types. No provider shape reaches the loop (ADR-020)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field

from usta.core.base import Frozen

EMPTY_REPLY = "(empty reply)"  # sent for an assistant turn with no content; APIs reject empty turns


class TextBlock(Frozen):
    type: Literal["text"] = "text"
    text: str


class ToolCall(Frozen):
    type: Literal["tool_call"] = "tool_call"
    id: str
    name: str
    input: dict[str, Any]
    input_error: str | None = None  # provider sent arguments we could not parse


class ToolResult(Frozen):
    type: Literal["tool_result"] = "tool_result"
    call_id: str
    content: str
    is_error: bool = False


class OpaqueBlock(Frozen):
    """Provider-specific block echoed back unchanged (e.g. Anthropic thinking blocks)."""

    type: Literal["opaque"] = "opaque"
    provider: str
    data: dict[str, Any]


ContentBlock = Annotated[
    TextBlock | ToolCall | ToolResult | OpaqueBlock, Field(discriminator="type")
]


class Message(Frozen):
    role: Literal["user", "assistant"]
    content: tuple[ContentBlock, ...]

    @classmethod
    def user_text(cls, text: str) -> Message:
        return cls(role="user", content=(TextBlock(text=text),))

    def text(self) -> str:
        return "".join(b.text for b in self.content if isinstance(b, TextBlock))

    def tool_calls(self) -> list[ToolCall]:
        return [b for b in self.content if isinstance(b, ToolCall)]

    def tool_results(self) -> list[ToolResult]:
        return [b for b in self.content if isinstance(b, ToolResult)]
