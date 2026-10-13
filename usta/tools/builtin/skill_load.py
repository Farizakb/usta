"""skill.load: return a skill's SKILL.md body (SPEC §7.1). The index is in the cached prefix."""

from __future__ import annotations

from typing import Any

from usta.core.errors import ToolInputError
from usta.skills import SkillSet
from usta.tools.registry import Tool, ToolContext, ToolOutput


def make_skill_load(skills: SkillSet) -> Tool:
    async def load(args: dict[str, Any], ctx: ToolContext) -> ToolOutput:
        skill = skills.get(args["name"])
        if skill is None:
            raise ToolInputError(f"unknown skill {args['name']!r}; available: {skills.names()}")
        return ToolOutput(
            f"{skill.body.rstrip()}\n\n(This skill's files are at /skills/{skill.name}/ "
            "inside code_exec.)"
        )

    return Tool(
        name="skill.load",
        description="Load a skill's instructions. Do this before producing that kind of file.",
        input_schema={
            "type": "object",
            "properties": {"name": {"enum": skills.names()}},
            "required": ["name"],
            "additionalProperties": False,
        },
        tier="local",
        fn=load,
    )
