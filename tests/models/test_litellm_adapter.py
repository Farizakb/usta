import json
from types import SimpleNamespace
from typing import Any

import pytest

from tests.models.contract import CONTRACT_REQUEST, assert_contract_response
from usta.core.errors import ConfigError, ProviderError, ProviderRateLimited, TransientProviderError
from usta.core.messages import Message, ToolResult
from usta.models.fake import DEFAULT_CAPS
from usta.models.litellm_adapter import LiteLLMModel

WIRE = {
    "id": "x",
    "model": "gemini/gemini-2.5-flash",
    "choices": [
        {
            "index": 0,
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": "Oxuyuram.",
                "tool_calls": [
                    {
                        "id": "toolu_2",
                        "type": "function",
                        "function": {
                            "name": "file__read",
                            "arguments": '{"path": "files/qeyd.txt"}',
                        },
                    }
                ],
            },
        }
    ],
    "usage": {
        "prompt_tokens": 1012,
        "completion_tokens": 7,
        "prompt_tokens_details": {"cached_tokens": 900},
        "cache_creation_input_tokens": 100,
    },
}


class FakeCompletion:
    def __init__(self, wire: dict | None = None, error: Exception | None = None) -> None:
        self.wire, self.error, self.kwargs = wire, error, {}

    async def __call__(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return SimpleNamespace(model_dump=lambda: self.wire)


def make(fake: FakeCompletion, **kw: Any) -> LiteLLMModel:
    return LiteLLMModel(
        "gemini/gemini-2.5-flash",
        DEFAULT_CAPS,
        api_key="k-1",
        max_output_tokens=512,
        completion=fake,
        **kw,
    )


def with_tool_call(arguments: str, finish: str = "tool_calls") -> dict:
    wire = json.loads(json.dumps(WIRE))
    wire["choices"][0]["finish_reason"] = finish
    wire["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = arguments
    return wire


async def test_round_trip_meets_contract_and_wire_shape() -> None:
    fake = FakeCompletion(WIRE)
    model = make(fake)
    assert model.provider == "litellm:gemini"
    assert_contract_response(await model.complete(CONTRACT_REQUEST))
    kw = fake.kwargs
    assert kw["model"] == "gemini/gemini-2.5-flash"
    assert kw["api_key"] == "k-1"
    assert kw["max_tokens"] == 512
    assert kw["messages"][0] == {
        "role": "system",
        "content": [
            {"type": "text", "text": "You are Usta.", "cache_control": {"type": "ephemeral"}}
        ],
    }
    assert kw["messages"][2]["tool_calls"][0]["function"] == {
        "name": "file__read",
        "arguments": '{"path": "files/a.txt"}',
    }
    assert kw["messages"][3] == {
        "role": "tool",
        "tool_call_id": "toolu_1",
        "content": "İSTİQAMƏT: Bakı",
    }
    assert kw["tools"][0]["function"]["name"] == "file__read"


async def test_error_tool_results_are_marked_in_content() -> None:
    fake = FakeCompletion(WIRE)
    req = CONTRACT_REQUEST.model_copy(
        update={
            "messages": (
                Message(
                    role="user", content=(ToolResult(call_id="c", content="no", is_error=True),)
                ),
            )
        }
    )
    await make(fake).complete(req)
    assert fake.kwargs["messages"][-1]["content"] == "ERROR: no"


async def test_invalid_json_arguments_become_input_error() -> None:
    resp = await make(FakeCompletion(with_tool_call('{"path": "files/'))).complete(CONTRACT_REQUEST)
    [call] = resp.tool_calls()
    assert call.input == {} and "not valid JSON" in (call.input_error or "")


async def test_tool_calls_win_over_a_stop_finish_reason() -> None:
    resp = await make(FakeCompletion(with_tool_call('{"path": "x"}', finish="stop"))).complete(
        CONTRACT_REQUEST
    )
    assert resp.stop == "tool_use"


async def test_length_finish_reason_is_max_tokens_even_with_tool_calls() -> None:
    resp = await make(FakeCompletion(with_tool_call('{"pa', finish="length"))).complete(
        CONTRACT_REQUEST
    )
    assert resp.stop == "max_tokens"


class ProviderBoom(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"status {status}")
        self.status_code = status
        self.llm_provider = "gemini"


@pytest.mark.parametrize(
    ("status", "error"),
    [(429, ProviderRateLimited), (503, TransientProviderError), (400, ProviderError)],
)
async def test_provider_errors_are_mapped(status: int, error: type) -> None:
    with pytest.raises(ProviderError) as info:
        await make(FakeCompletion(error=ProviderBoom(status))).complete(CONTRACT_REQUEST)
    assert type(info.value) is error


async def test_our_own_bugs_are_not_disguised_as_provider_errors() -> None:
    with pytest.raises(TypeError):
        await make(FakeCompletion(error=TypeError("bug"))).complete(CONTRACT_REQUEST)


async def test_retries_are_disabled() -> None:
    fake = FakeCompletion(WIRE)
    await make(fake).complete(CONTRACT_REQUEST)
    assert fake.kwargs["num_retries"] == 0


def test_no_key_and_no_api_base_is_a_config_error() -> None:
    with pytest.raises(ConfigError):
        LiteLLMModel("gemini/x", DEFAULT_CAPS, api_key=None, max_output_tokens=512)


async def test_no_key_with_api_base_uses_placeholder_key() -> None:
    fake = FakeCompletion(WIRE)
    model = LiteLLMModel(
        "ollama/x",
        DEFAULT_CAPS,
        api_key=None,
        max_output_tokens=512,
        api_base="http://localhost:11434",
        completion=fake,
    )
    await model.complete(CONTRACT_REQUEST)
    assert fake.kwargs["api_key"] == "no-key"
    assert fake.kwargs["api_base"] == "http://localhost:11434"
