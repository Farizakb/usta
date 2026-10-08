"""Model-layer value types shared by every adapter (SPEC §3.3, ADR-021)."""

from typing import Any, Literal

from usta.core.base import Frozen
from usta.core.messages import Message, ToolCall

Role = Literal["main", "light"]
ModelStop = Literal["end_turn", "tool_use", "max_tokens", "refusal", "other"]


class ModelCaps(Frozen):
    context_tokens: int
    max_output_tokens: int
    prompt_cache: Literal["explicit", "automatic", "none"]
    parallel_tool_calls: bool
    native_tools: bool  # False -> startup refuses the model


class ToolSpec(Frozen):
    name: str
    description: str
    input_schema: dict[str, Any]


class SystemBlock(Frozen):
    text: str
    cache: bool = False  # cache marker after this block (R10)


class ModelRequest(Frozen):
    role: Role
    system: tuple[SystemBlock, ...]
    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...] = ()
    prompt_version: str
    run_id: str | None = None
    user_id: str | None = None
    max_output_tokens: int | None = None  # None -> the role's configured default


class Usage(Frozen):
    input_tokens: int = 0  # uncached input (Anthropic semantics)
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


class ModelResponse(Frozen):
    message: Message  # role == "assistant"
    usage: Usage
    stop: ModelStop
    model: str
    cost_usd: float = 0.0  # set by the gateway from the price table (P7)

    def tool_calls(self) -> list[ToolCall]:
        return self.message.tool_calls()
