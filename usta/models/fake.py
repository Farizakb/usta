"""Scripted model for the `test` profile only. Startup guards refuse it elsewhere (P8)."""

import itertools
from collections import deque
from collections.abc import Callable, Iterable
from typing import Any

from usta.core.messages import Message, TextBlock, ToolCall
from usta.core.model import ModelCaps, ModelRequest, ModelResponse, Usage

DEFAULT_CAPS = ModelCaps(
    context_tokens=200_000,
    max_output_tokens=8_192,
    prompt_cache="none",
    parallel_tool_calls=True,
    native_tools=True,
)
DEFAULT_USAGE = Usage(input_tokens=10, output_tokens=5)

ScriptStep = ModelResponse | BaseException | Callable[[ModelRequest], ModelResponse]
_ids = itertools.count(1)


class FakeModel:
    provider = "fake"

    def __init__(
        self,
        script: Iterable[ScriptStep] = (),
        *,
        model_id: str = "fake-model",
        caps: ModelCaps = DEFAULT_CAPS,
    ) -> None:
        self.model_id = model_id
        self.caps = caps
        self.requests: list[ModelRequest] = []
        self._script: deque[ScriptStep] = deque(script)

    async def complete(self, req: ModelRequest) -> ModelResponse:
        self.requests.append(req)
        if not self._script:
            raise AssertionError(
                f"FakeModel script exhausted after {len(self.requests) - 1} responses"
            )
        step = self._script.popleft()
        if isinstance(step, BaseException):
            raise step
        if callable(step):
            return step(req)
        return step


def reply(text: str, *, usage: Usage = DEFAULT_USAGE) -> ModelResponse:
    return ModelResponse(
        message=Message(role="assistant", content=(TextBlock(text=text),)),
        usage=usage,
        stop="end_turn",
        model="fake-model",
    )


def call(
    name: str,
    input: dict[str, Any],
    *,
    id: str | None = None,
    text: str = "",
    usage: Usage = DEFAULT_USAGE,
) -> ModelResponse:
    blocks: tuple = (TextBlock(text=text),) if text else ()
    blocks += (ToolCall(id=id or f"call_{next(_ids)}", name=name, input=input),)
    return ModelResponse(
        message=Message(role="assistant", content=blocks),
        usage=usage,
        stop="tool_use",
        model="fake-model",
    )
