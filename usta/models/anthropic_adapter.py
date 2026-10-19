"""Anthropic adapter: the production path (ADR-020). The only module that imports `anthropic`."""

from __future__ import annotations

from typing import Any

import anthropic

from usta.core.errors import ConfigError, TransientProviderError
from usta.core.messages import (
    EMPTY_REPLY,
    Message,
    OpaqueBlock,
    TextBlock,
    ToolCall,
    ToolResult,
)
from usta.core.model import (
    ModelCaps,
    ModelRequest,
    ModelResponse,
    ModelStop,
    SystemBlock,
    Usage,
)
from usta.models.errors import map_status
from usta.models.toolnames import decode, encode

_STOP: dict[str | None, ModelStop] = {
    "end_turn": "end_turn",
    "stop_sequence": "end_turn",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "refusal": "refusal",
}


DEFAULT_BASE_URL = "https://api.anthropic.com"


class AnthropicModel:
    provider = "anthropic"

    def __init__(
        self,
        model_id: str,
        caps: ModelCaps,
        *,
        api_key: str,
        max_output_tokens: int,
        effort: str | None = None,
        api_base: str | None = None,
        http_client: Any = None,
    ) -> None:
        if not api_key:
            raise ConfigError(
                "anthropic adapter needs an explicit API key (no credential fallback)"
            )
        self.model_id = model_id
        self.caps = caps
        self._max_output = max_output_tokens
        self._effort = effort
        # Retries live in the gateway (one policy, every attempt logged), so the SDK's are off.
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            # Always explicit: the SDK would otherwise read ANTHROPIC_BASE_URL from the environment.
            base_url=api_base or DEFAULT_BASE_URL,
            max_retries=0,
            http_client=http_client,
        )

    async def complete(self, req: ModelRequest) -> ModelResponse:
        kwargs: dict[str, Any] = {
            "model": self.model_id,
            "max_tokens": req.max_output_tokens or self._max_output,
            "system": [_system_block(b) for b in req.system],
            "messages": [_message(m) for m in req.messages],
        }
        if req.tools:
            kwargs["tools"] = [
                {
                    "name": encode(t.name),
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in req.tools
            ]
        if self._effort:
            kwargs["output_config"] = {"effort": self._effort}
        try:
            msg = await self._client.messages.create(**kwargs)
        except anthropic.APIStatusError as e:
            raise map_status(e.status_code, str(e)) from e
        except anthropic.APIConnectionError as e:  # includes APITimeoutError
            raise TransientProviderError(str(e)) from e
        return _response(msg)


def _system_block(block: SystemBlock) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "text", "text": block.text}
    if block.cache:
        out["cache_control"] = {"type": "ephemeral"}
    return out


def _message(msg: Message) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    for b in msg.content:
        if isinstance(b, TextBlock):
            if b.text:  # the API rejects empty text blocks
                content.append({"type": "text", "text": b.text})
        elif isinstance(b, ToolCall):
            content.append(
                {"type": "tool_use", "id": b.id, "name": encode(b.name), "input": b.input}
            )
        elif isinstance(b, ToolResult):
            content.append(
                {
                    "type": "tool_result",
                    "tool_use_id": b.call_id,
                    "content": b.content,
                    "is_error": b.is_error,
                }
            )
        elif isinstance(b, OpaqueBlock) and b.provider == "anthropic":
            content.append(b.data)
    if not content and msg.role == "assistant":
        content.append({"type": "text", "text": EMPTY_REPLY})
    return {"role": msg.role, "content": content}


def _response(msg: Any) -> ModelResponse:
    blocks: list = []
    for b in msg.content:
        if b.type == "text":
            blocks.append(TextBlock(text=b.text))
        elif b.type == "tool_use":
            blocks.append(ToolCall(id=b.id, name=decode(b.name), input=dict(b.input)))
        else:  # thinking, redacted_thinking, ...: must be echoed back unchanged
            blocks.append(
                OpaqueBlock(provider="anthropic", data=b.model_dump(mode="json", exclude_none=True))
            )
    u = msg.usage
    return ModelResponse(
        message=Message(role="assistant", content=tuple(blocks)),
        usage=Usage(
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_tokens=u.cache_read_input_tokens or 0,
            cache_write_tokens=u.cache_creation_input_tokens or 0,
        ),
        stop=_STOP.get(msg.stop_reason, "other"),
        model=msg.model,
    )
