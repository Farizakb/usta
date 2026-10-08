"""file.read (M0). file.list, file.search and file.write arrive in M1."""

from __future__ import annotations

import asyncio
from pathlib import Path, PurePosixPath
from typing import Any

from usta.core.errors import ToolInputError
from usta.tools.registry import Tool, ToolContext, ToolOutput

MAX_CHARS = 50_000  # until layer-1 offload (M3) stores large results as files


def resolve(path: str, ctx: ToolContext) -> Path:
    """Map 'files/...' or 'out/...' to a real path inside the user's workspace; refuse escapes."""
    if "\x00" in path:
        raise ToolInputError(f"path contains a NUL byte: {path!r}")
    rel = PurePosixPath(path)
    roots = {"files": ctx.files_dir, "out": ctx.out_dir}
    if rel.is_absolute() or not rel.parts or rel.parts[0] not in roots:
        raise ToolInputError(f"path must start with files/ or out/: {path!r}")
    root = roots[rel.parts[0]].resolve()
    target = root.joinpath(*rel.parts[1:]).resolve()  # resolves symlinks
    if not target.is_relative_to(root):
        raise ToolInputError(f"path escapes the workspace: {path!r}")
    return target


async def _read(args: dict[str, Any], ctx: ToolContext) -> ToolOutput:
    target = resolve(args["path"], ctx)
    if not target.is_file():
        raise ToolInputError(f"not a file: {args['path']!r}")
    text = (await asyncio.to_thread(target.read_bytes)).decode("utf-8", errors="replace")
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + f"\n[truncated: showing {MAX_CHARS} of {len(text)} characters]"
    return ToolOutput(text)


FILE_READ = Tool(
    name="file.read",
    description=(
        "Read a UTF-8 text file. Paths start with files/ (the user's workspace files) "
        "or out/ (files produced in this run)."
    ),
    input_schema={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "e.g. files/notes.txt"}},
        "required": ["path"],
        "additionalProperties": False,
    },
    tier="read",
    fn=_read,
)
