from pathlib import Path

from tests.fakes import InMemoryStore
from usta.core.messages import ToolCall
from usta.core.run import RunState, TodoItem
from usta.tools.builtin import builtin_tools
from usta.tools.pipeline import ToolPipeline
from usta.tools.registry import ToolRegistry


async def test_todo_replaces_the_list_and_emits_an_event(tmp_path: Path) -> None:
    run = RunState.new(id="r1", user_id="u1", task="t", engine="own", cost_cap_usd=0.5)
    p = ToolPipeline(ToolRegistry(builtin_tools()), audit=InMemoryStore(), workspace_root=tmp_path)
    items = [
        {"content": "Hesabatı yoxla", "status": "in_progress"},
        {"content": "Zəng et", "status": "pending"},
    ]
    out = await p.handle(ToolCall(id="c1", name="todo", input={"items": items}), run)
    assert not out.result.is_error
    assert run.todo == [TodoItem(**i) for i in items]
    assert "[in_progress] Hesabatı yoxla" in out.result.content
    assert out.event is not None and out.event.type == "todo_updated"
    assert out.event.data == {"items": items}


async def test_todo_rejects_unknown_status(tmp_path: Path) -> None:
    run = RunState.new(id="r1", user_id="u1", task="t", engine="own", cost_cap_usd=0.5)
    p = ToolPipeline(ToolRegistry(builtin_tools()), audit=InMemoryStore(), workspace_root=tmp_path)
    bad = {"items": [{"content": "x", "status": "maybe"}]}
    out = await p.handle(ToolCall(id="c1", name="todo", input=bad), run)
    assert out.result.is_error and run.todo == []


def test_builtin_tools() -> None:
    assert [t.name for t in builtin_tools()] == [
        "file.list",
        "file.read",
        "file.search",
        "file.write",
        "todo",
    ]
