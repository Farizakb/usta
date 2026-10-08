"""LiteLLM adapter, library mode: free tiers, local servers, other providers (ADR-020).

The ONLY module that imports litellm (import-linter, F8). It receives only its own key.
"""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable
from typing import Any

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")  # no network fetch on import

import litellm  # noqa: E402

from usta.core.messages import Message, TextBlock, ToolCall  # noqa: E402
from usta.core.model import (  # noqa: E402
    ModelCaps,
    ModelRequest,
    ModelResponse,
    ModelStop,
    SystemBlock,
    Usage,
)
from usta.models.errors import map_status  # noqa: E402
from usta.models.toolnames import decode, encode  # noqa: E402

Completion = Callable[..., Awaitable[Any]]
_STOP: dict[str | None, ModelStop] = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "content_filter": "refusal",
}


class LiteLLMModel:
    def __init__(
        self,
        model_id: str,
        caps: ModelCaps,
        *,
        api_key: str | None,
        max_output_tokens: int,
        api_base: str | None = None,
        effort: str | None = None,
        completion: Completion | None = None,
    ) -> None:
        self.model_id = model_id
        self.caps = caps
        self.provider = "litellm:" + model_id.split("/", 1)[0]
        self._api_key = api_key
        self._api_base = api_base
        self._max_output = max_output_tokens
        self._effort = effort
        self._completion = completion or litellm.acompletion

    async def complete(self, req: ModelRequest) -> ModelResponse:
        kwargs: dict[str, Any] = {
            "model": self.model_id,
            "messages": _messages(req),
            "max_tokens": req.max_output_tokens or self._max_output,
        }
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._api_base:
            kwargs["api_base"] = self._api_base
        if self._effort:
            kwargs["reasoning_effort"] = self._effort
        if req.tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": encode(t.name),
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in req.tools
            ]
        try:
            raw = await self._completion(**kwargs)
        except Exception as e:
            status = getattr(e, "status_code", None)
            if status is None and getattr(e, "llm_provider", None) is None:
                raise  # our bug, not the provider's: never disguise it
            raise map_status(status, str(e)) from e
        return _response(raw.model_dump() if hasattr(raw, "model_dump") else raw, self.model_id)


def _system_part(block: SystemBlock) -> dict[str, Any]:
    part: dict[str, Any] = {"type": "text", "text": block.text}
    if block.cache:
        part["cache_control"] = {"type": "ephemeral"}
    return part


def _messages(req: ModelRequest) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if req.system:
        out.append({"role": "system", "content": [_system_part(b) for b in req.system]})
    for m in req.messages:
        if m.role == "assistant":
            msg: dict[str, Any] = {"role": "assistant", "content": m.text() or None}
            calls = m.tool_calls()
            if calls:
                msg["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {
                            "name": encode(c.name),
                            "arguments": json.dumps(c.input, ensure_ascii=False),
                        },
                    }
                    for c in calls
                ]
            out.append(msg)
        else:
            for r in m.tool_results():
                content = f"ERROR: {r.content}" if r.is_error else r.content
                out.append({"role": "tool", "tool_call_id": r.call_id, "content": content})
            if text := m.text():
                out.append({"role": "user", "content": text})
    return out


def _parse_args(raw: Any) -> tuple[dict[str, Any], str | None]:
    if isinstance(raw, dict):
        return raw, None
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError as e:
        return {}, f"arguments are not valid JSON ({e.msg})"
    if not isinstance(parsed, dict):
        return {}, "arguments must be a JSON object"
    return parsed, None


def _response(d: dict[str, Any], model_id: str) -> ModelResponse:
    choice = d["choices"][0]
    msg = choice.get("message") or {}
    blocks: list = []
    if msg.get("content"):
        blocks.append(TextBlock(text=msg["content"]))
    for tc in msg.get("tool_calls") or []:
        fn = tc["function"]
        args, err = _parse_args(fn.get("arguments"))
        blocks.append(ToolCall(id=tc["id"], name=decode(fn["name"]), input=args, input_error=err))
    finish = choice.get("finish_reason")
    if finish == "length":
        stop: ModelStop = "max_tokens"
    elif any(isinstance(b, ToolCall) for b in blocks):
        stop = "tool_use"
    else:
        stop = _STOP.get(finish, "other")
    u = d.get("usage") or {}
    cache_read = (
        (u.get("prompt_tokens_details") or {}).get("cached_tokens")
        or u.get("cache_read_input_tokens")
        or 0
    )
    cache_write = u.get("cache_creation_input_tokens") or 0
    usage = Usage(
        input_tokens=max(0, (u.get("prompt_tokens") or 0) - cache_read - cache_write),
        output_tokens=u.get("completion_tokens") or 0,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
    )
    return ModelResponse(
        message=Message(role="assistant", content=tuple(blocks)),
        usage=usage,
        stop=stop,
        model=d.get("model") or model_id,
    )
