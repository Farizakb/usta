import json
from pathlib import Path

import httpx2
import pytest

from tests.models.contract import CONTRACT_REQUEST, assert_contract_response
from usta.core.errors import (
    ConfigError,
    ProviderError,
    ProviderQuotaError,
    ProviderRateLimited,
    TransientProviderError,
)
from usta.core.messages import Message, TextBlock, ToolResult
from usta.models.anthropic_adapter import AnthropicModel
from usta.models.caps import load_catalog

CAPS = load_catalog(Path("config/models.toml"))["claude-sonnet-5-5"].caps

WIRE_RESPONSE = {
    "id": "msg_1",
    "type": "message",
    "role": "assistant",
    "model": "claude-sonnet-5-5",
    "content": [
        {"type": "thinking", "thinking": "", "signature": "sig-abc"},
        {"type": "text", "text": "Oxuyuram."},
        {
            "type": "tool_use",
            "id": "toolu_2",
            "name": "file__read",
            "input": {"path": "files/qeyd.txt"},
        },
    ],
    "stop_reason": "tool_use",
    "stop_sequence": None,
    "usage": {
        "input_tokens": 12,
        "output_tokens": 7,
        "cache_creation_input_tokens": 100,
        "cache_read_input_tokens": 900,
    },
}


def make_model(handler, **kw) -> AnthropicModel:
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return AnthropicModel(
        "claude-sonnet-5-5",
        CAPS,
        api_key="test-key",
        max_output_tokens=1024,
        http_client=client,
        **kw,
    )


def capture(seen: dict):
    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json=WIRE_RESPONSE)

    return handler


async def test_round_trip_meets_contract_and_wire_shape() -> None:
    seen: dict = {}
    resp = await make_model(capture(seen), effort="medium").complete(CONTRACT_REQUEST)
    assert_contract_response(resp)
    body = seen["body"]
    assert body["model"] == "claude-sonnet-5-5"
    assert body["max_tokens"] == 1024
    assert body["output_config"] == {"effort": "medium"}
    assert "fallbacks" not in body
    assert body["system"] == [
        {"type": "text", "text": "You are Usta.", "cache_control": {"type": "ephemeral"}}
    ]
    assert body["tools"][0]["name"] == "file__read"
    assert body["messages"][1]["content"] == [
        {
            "type": "tool_use",
            "id": "toolu_1",
            "name": "file__read",
            "input": {"path": "files/a.txt"},
        }
    ]
    assert body["messages"][2]["content"] == [
        {
            "type": "tool_result",
            "tool_use_id": "toolu_1",
            "content": "İSTİQAMƏT: Bakı",
            "is_error": False,
        }
    ]


async def test_thinking_blocks_are_sent_back_unchanged() -> None:
    first = await make_model(capture({})).complete(CONTRACT_REQUEST)
    follow_up = CONTRACT_REQUEST.model_copy(
        update={
            "messages": CONTRACT_REQUEST.messages
            + (
                first.message,
                Message(role="user", content=(ToolResult(call_id="toolu_2", content="ok"),)),
            )
        }
    )
    seen: dict = {}
    await make_model(capture(seen)).complete(follow_up)
    echoed = seen["body"]["messages"][3]["content"]
    assert echoed[0] == {"type": "thinking", "thinking": "", "signature": "sig-abc"}
    assert echoed[2]["type"] == "tool_use" and echoed[2]["name"] == "file__read"


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (402, ProviderQuotaError),
        (429, ProviderRateLimited),
        (529, TransientProviderError),
        (500, TransientProviderError),
        (400, ProviderError),
    ],
)
async def test_http_errors_map_to_usta_errors(status: int, error: type) -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            status, json={"type": "error", "error": {"type": "x", "message": "boom"}}
        )

    with pytest.raises(ProviderError) as info:
        await make_model(handler).complete(CONTRACT_REQUEST)
    assert type(info.value) is error


async def test_connection_error_is_transient() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down", request=request)

    with pytest.raises(TransientProviderError):
        await make_model(handler).complete(CONTRACT_REQUEST)


def test_empty_api_key_is_refused() -> None:
    with pytest.raises(ConfigError):
        AnthropicModel("claude-sonnet-5-5", CAPS, api_key="", max_output_tokens=1024)


async def test_base_url_env_var_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://proxy.invalid")
    seen: dict = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["host"] = request.url.host
        return httpx2.Response(200, json=WIRE_RESPONSE)

    await make_model(handler).complete(CONTRACT_REQUEST)
    assert seen == {"host": "api.anthropic.com"}


async def test_profile_api_base_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["host"] = request.url.host
        return httpx2.Response(200, json=WIRE_RESPONSE)

    await make_model(handler, api_base="https://gateway.example").complete(CONTRACT_REQUEST)
    assert seen["host"] == "gateway.example"


@pytest.mark.parametrize("content", [(), (TextBlock(text=""),)])
async def test_empty_assistant_turn_is_sent_as_placeholder(content: tuple) -> None:
    seen: dict = {}
    req = CONTRACT_REQUEST.model_copy(
        update={
            "messages": (
                Message.user_text("a"),
                Message(role="assistant", content=content),
                Message.user_text("b"),
            )
        }
    )
    await make_model(capture(seen)).complete(req)
    assert seen["body"]["messages"][1]["content"] == [{"type": "text", "text": "(empty reply)"}]
