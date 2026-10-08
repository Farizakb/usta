"""todo: the run's task list (ADR-016). Full replacement on each call."""

from __future__ import annotations

from typing import Any

from usta.core.events import Event
from usta.core.run import TodoItem
from usta.tools.registry import Tool, ToolContext, ToolOutput


async def _todo(args: dict[str, Any], ctx: ToolContext) -> ToolOutput:
    ctx.run.todo = [TodoItem(**item) for item in args["items"]]
    rendered = "\n".join(f"[{i.status}] {i.content}" for i in ctx.run.todo) or "(empty)"
    event = Event(
        run_id=ctx.run.id,
        type="todo_updated",
        data={"items": [i.model_dump() for i in ctx.run.todo]},
    )
    return ToolOutput(rendered, event=event)


TODO = Tool(
    name="todo",
    description=(
        "Replace this run's task list. Use it for tasks with three or more steps; "
        "keep exactly one item in_progress and mark items done as you finish them."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "minLength": 1},
                        "status": {"enum": ["pending", "in_progress", "done"]},
                    },
                    "required": ["content", "status"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    },
    tier="local",
    fn=_todo,
)
