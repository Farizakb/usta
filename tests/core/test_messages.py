from usta.core.messages import Message, OpaqueBlock, TextBlock, ToolCall, ToolResult

AZ = "İSTİQAMƏT: Gəncə, IŞIQ — ğ ş ı ö ü ç ə"


def test_message_json_round_trip_keeps_block_types_and_azerbaijani_text() -> None:
    msg = Message(
        role="assistant",
        content=(
            TextBlock(text=AZ),
            ToolCall(id="c1", name="file.read", input={"path": "files/qeyd.txt"}),
            OpaqueBlock(
                provider="anthropic", data={"type": "thinking", "thinking": "", "signature": "s"}
            ),
        ),
    )
    again = Message.model_validate_json(msg.model_dump_json())
    assert again == msg
    assert again.text() == AZ
    assert [c.name for c in again.tool_calls()] == ["file.read"]


def test_user_text_and_tool_results_helpers() -> None:
    assert Message.user_text("salam").content == (TextBlock(text="salam"),)
    msg = Message(role="user", content=(ToolResult(call_id="c1", content="ok"),))
    assert msg.tool_results() == [ToolResult(call_id="c1", content="ok")]
    assert msg.text() == ""
