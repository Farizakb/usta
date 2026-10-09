"""Live check of the dev own-loop model: tool call + tool-result round trip.

Run: pytest -m live tests/models/test_litellm_live.py  (USTA_LIVE_PROFILE selects the profile)
"""

import os
from pathlib import Path

import pytest

from tests.models.contract import READ_SPEC
from usta.app.config import load_profile
from usta.core.messages import Message, ToolResult
from usta.core.model import ModelRequest, SystemBlock
from usta.models.caps import load_catalog
from usta.models.litellm_adapter import LiteLLMModel

pytestmark = pytest.mark.live


async def test_live_model_calls_a_tool_and_accepts_the_result() -> None:
    profile = os.environ.get("USTA_LIVE_PROFILE", "dev-openai")
    rc = load_profile(profile, Path("config")).roles["main"]
    key = os.environ.get(rc.api_key_env or "")
    assert key, f"{rc.api_key_env} must be set for live tests"
    entry = load_catalog(Path("config/models.toml"))[rc.model]
    model = LiteLLMModel(
        rc.model,
        entry.caps,
        api_key=key,
        max_output_tokens=1024,
        api_base=rc.api_base,
        effort=rc.effort,
    )
    req = ModelRequest(
        role="main",
        system=(
            SystemBlock(text="Use the file.read tool to read files before answering.", cache=True),
        ),
        messages=(Message.user_text("files/qeyd.txt faylını oxu və nə yazıldığını de."),),
        tools=(READ_SPEC,),
        prompt_version="live-v1",
    )
    first = await model.complete(req)
    [call] = first.tool_calls()
    assert call.name == "file.read" and call.input.get("path") and call.input_error is None
    assert first.usage.output_tokens > 0

    result = ToolResult(call_id=call.id, content="Sabah saat 10-da iclas var.")
    follow = req.model_copy(
        update={"messages": req.messages + (first.message, Message(role="user", content=(result,)))}
    )
    second = await model.complete(follow)
    assert second.message.text().strip()
    assert second.tool_calls() == []
