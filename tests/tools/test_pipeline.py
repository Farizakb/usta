from pathlib import Path

import pytest

from tests.fakes import ECHO, InMemoryStore
from usta.core.messages import ToolCall, ToolResult
from usta.core.run import RunState
from usta.models import toolnames
from usta.tools.pipeline import ToolPipeline
from usta.tools.registry import Tool, ToolOutput, ToolRegistry


def run_state() -> RunState:
    return RunState.new(id="r1", user_id="u1", task="t", engine="own", cost_cap_usd=0.5)


def pipeline(tmp_path: Path, *tools: Tool) -> tuple[ToolPipeline, InMemoryStore]:
    store = InMemoryStore()
    return ToolPipeline(ToolRegistry(tools or (ECHO,)), audit=store, workspace_root=tmp_path), store


async def test_valid_call_is_executed_and_audited_intent_then_done(tmp_path: Path) -> None:
    p, store = pipeline(tmp_path)
    out = await p.handle(ToolCall(id="c1", name="test.echo", input={"text": "salam"}), run_state())
    assert out.result == ToolResult(call_id="c1", content="echo: salam")
    assert [r.phase for r in store.tool_calls] == ["intent", "done"]
    done = store.tool_calls[1]
    assert (done.output, done.is_error, done.run_id, done.user_id) == (
        "echo: salam",
        False,
        "r1",
        "u1",
    )


async def test_unknown_tool_returns_error_listing_real_tools(tmp_path: Path) -> None:
    p, store = pipeline(tmp_path)
    out = await p.handle(ToolCall(id="c1", name="fleet.delete_all", input={}), run_state())
    assert out.result.is_error
    assert (
        "unknown tool 'fleet.delete_all'" in out.result.content
        and "test.echo" in out.result.content
    )
    assert [r.phase for r in store.tool_calls] == ["done"]


async def test_unparsable_arguments_are_reported(tmp_path: Path) -> None:
    p, _ = pipeline(tmp_path)
    call = ToolCall(id="c1", name="test.echo", input={}, input_error="arguments are not valid JSON")
    out = await p.handle(call, run_state())
    assert out.result.is_error and "not valid JSON" in out.result.content


async def test_schema_violations_are_reported(tmp_path: Path) -> None:
    p, store = pipeline(tmp_path)
    out = await p.handle(ToolCall(id="c1", name="test.echo", input={"txt": 1}), run_state())
    assert out.result.is_error
    assert "'text' is a required property" in out.result.content
    assert [r.phase for r in store.tool_calls] == ["done"]  # never executed


async def test_tool_exception_becomes_error_result(tmp_path: Path) -> None:
    async def boom(args, ctx) -> ToolOutput:
        raise RuntimeError("disk on fire")

    tool = Tool(
        name="test.boom", description="x", input_schema={"type": "object"}, tier="local", fn=boom
    )
    p, store = pipeline(tmp_path, tool)
    out = await p.handle(ToolCall(id="c1", name="test.boom", input={}), run_state())
    assert out.result.is_error and "RuntimeError: disk on fire" in out.result.content
    assert [r.phase for r in store.tool_calls] == ["intent", "done"]


def test_registry_rejects_bad_names_and_duplicates() -> None:
    reg = ToolRegistry([ECHO])
    with pytest.raises(ValueError, match="duplicate"):
        reg.register(ECHO)
    for bad in [
        "File.read",
        "file__read",
        "file..read",
        "",
        "a_.b",
        "a._b",
        "file.read_",
        "todo\n",
    ]:
        with pytest.raises(ValueError, match="invalid tool name"):
            reg.register(
                Tool(
                    name=bad,
                    description="x",
                    input_schema={"type": "object"},
                    tier="local",
                    fn=ECHO.fn,
                )
            )


def test_registry_accepts_names_that_round_trip_on_the_wire() -> None:
    reg = ToolRegistry()
    for good in ["fleet.fuel_report", "file.read", "todo"]:
        reg.register(
            Tool(
                name=good,
                description="x",
                input_schema={"type": "object"},
                tier="local",
                fn=ECHO.fn,
            )
        )
    assert reg.names() == ["file.read", "fleet.fuel_report", "todo"]


def test_accepted_names_round_trip_through_the_wire_codec() -> None:
    for name in ["file.read", "fleet.fuel_report", "todo"]:
        assert toolnames.decode(toolnames.encode(name)) == name


def test_specs_are_sorted_for_a_stable_cached_prefix() -> None:
    zeta = Tool(
        name="zeta", description="z", input_schema={"type": "object"}, tier="local", fn=ECHO.fn
    )
    alpha = Tool(
        name="alpha", description="a", input_schema={"type": "object"}, tier="local", fn=ECHO.fn
    )
    assert [s.name for s in ToolRegistry([zeta, alpha]).specs()] == ["alpha", "zeta"]
