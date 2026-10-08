"""Tool registry. Tool names are dotted lowercase; '__' is reserved for wire encoding."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator

from usta.core.events import Event
from usta.core.model import ToolSpec
from usta.core.run import RunState

Tier = Literal["read", "local", "egress", "external_write"]
# No segment may end in "_": such names cannot round-trip through toolnames.encode/decode.
_NAME = re.compile(r"^[a-z](?:[a-z0-9_]*[a-z0-9])?(?:\.[a-z](?:[a-z0-9_]*[a-z0-9])?)*$")


@dataclass(frozen=True)
class ToolOutput:
    content: str
    is_error: bool = False
    event: Event | None = None


@dataclass(frozen=True)
class ToolContext:
    run: RunState
    files_dir: Path  # workspaces/{user}/files (read-only for the agent)
    out_dir: Path  # workspaces/{user}/runs/{run_id}/out


ToolFn = Callable[[dict[str, Any], ToolContext], Awaitable[ToolOutput]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    tier: Tier
    fn: ToolFn

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name, description=self.description, input_schema=self.input_schema
        )


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if not _NAME.match(tool.name) or "__" in tool.name:
            raise ValueError(f"invalid tool name {tool.name!r}")
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool {tool.name!r}")
        Draft202012Validator.check_schema(tool.input_schema)
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self) -> tuple[ToolSpec, ...]:
        """Sorted by name so the cached prompt prefix stays byte-stable (R10)."""
        return tuple(self._tools[n].spec() for n in self.names())
