"""Shared adapter contract (SPEC §5): messages + tools + tool results + usage incl. cache
tokens round-trip. Each adapter test serves wire data equivalent to CONTRACT_RESPONSE."""

from usta.core.messages import Message, TextBlock, ToolCall, ToolResult
from usta.core.model import ModelRequest, ModelResponse, SystemBlock, ToolSpec, Usage

READ_SPEC = ToolSpec(
    name="file.read",
    description="Read a file.",
    input_schema={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
)

CONTRACT_REQUEST = ModelRequest(
    role="main",
    system=(SystemBlock(text="You are Usta.", cache=True),),
    messages=(
        Message.user_text("Qeydləri oxu."),
        Message(
            role="assistant",
            content=(ToolCall(id="toolu_1", name="file.read", input={"path": "files/a.txt"}),),
        ),
        Message(role="user", content=(ToolResult(call_id="toolu_1", content="İSTİQAMƏT: Bakı"),)),
    ),
    tools=(READ_SPEC,),
    prompt_version="contract-v1",
)

CONTRACT_RESPONSE = ModelResponse(
    message=Message(
        role="assistant",
        content=(
            TextBlock(text="Oxuyuram."),
            ToolCall(id="toolu_2", name="file.read", input={"path": "files/qeyd.txt"}),
        ),
    ),
    usage=Usage(input_tokens=12, output_tokens=7, cache_read_tokens=900, cache_write_tokens=100),
    stop="tool_use",
    model="contract-model",
)


def assert_contract_response(resp: ModelResponse) -> None:
    assert resp.message.role == "assistant"
    assert resp.message.text() == "Oxuyuram."
    [call] = resp.tool_calls()
    assert (call.id, call.name, call.input, call.input_error) == (
        "toolu_2",
        "file.read",
        {"path": "files/qeyd.txt"},
        None,
    )
    assert resp.stop == "tool_use"
    assert resp.usage == Usage(
        input_tokens=12, output_tokens=7, cache_read_tokens=900, cache_write_tokens=100
    )
