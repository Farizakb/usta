"""File tools (SPEC §7): file.list, file.read, file.search over files/ and out/; file.write
into out/ only. Paths are 'files/...' or 'out/...'; nothing outside the user's workspace."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path, PurePosixPath
from typing import Any

from usta.core.errors import ToolInputError
from usta.lang import az_casefold
from usta.tools.registry import Tool, ToolContext, ToolOutput

MAX_CHARS = 50_000  # until layer-1 offload (M3) stores large results as files
MAX_LIST = 500
MAX_HITS = 200
MAX_SEARCH_BYTES = 2_000_000
MAX_WRITE_CHARS = 1_000_000
_LINE_CHARS = 200


def resolve(path: str, ctx: ToolContext, roots: tuple[str, ...] = ("files", "out")) -> Path:
    """Map 'files/...' or 'out/...' to a real path inside the user's workspace; refuse escapes."""
    if "\x00" in path:
        raise ToolInputError(f"path contains a NUL byte: {path!r}")
    rel = PurePosixPath(path)
    dirs = {"files": ctx.files_dir, "out": ctx.out_dir}
    if rel.is_absolute() or not rel.parts or rel.parts[0] not in roots:
        allowed = " or ".join(f"{r}/" for r in roots)
        raise ToolInputError(f"path must start with {allowed}: {path!r}")
    root = dirs[rel.parts[0]].resolve()
    target = root.joinpath(*rel.parts[1:]).resolve()  # resolves symlinks
    if not target.is_relative_to(root):
        raise ToolInputError(f"path escapes the workspace: {path!r}")
    return target


def _display(target: Path, ctx: ToolContext) -> str:
    for prefix, root in (("files", ctx.files_dir), ("out", ctx.out_dir)):
        root = root.resolve()
        if target == root:
            return prefix
        if target.is_relative_to(root):
            return f"{prefix}/{target.relative_to(root).as_posix()}"
    raise ToolInputError(f"path escapes the workspace: {target}")


def _read_nofollow(target: Path) -> bytes:
    """Open without following a symlink swapped in after resolve() (M0 TOCTOU limitation)."""
    try:
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as e:
        raise ToolInputError(f"cannot open {target.name!r}: {e.strerror}") from e
    with os.fdopen(fd, "rb") as f:
        return f.read()


def _decode(data: bytes, path: str) -> str:
    """UTF-8 (with or without BOM) or BOM-marked UTF-16. Anything else is refused: Postgres
    cannot store NUL in text/jsonb, and mojibake would mislead the model."""
    encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    hint = (
        f"binary or unsupported encoding: {path!r}. file.read reads UTF-8/UTF-16 text only; "
        "open Excel, Word, PDF or other encodings with code_exec (e.g. pandas, pdfplumber, "
        "or open(path, encoding='cp1254'))"
    )
    try:
        text = data.decode(encoding)
    except UnicodeDecodeError as e:
        raise ToolInputError(hint) from e
    if "\x00" in text:
        raise ToolInputError(hint)
    return text


async def _read(args: dict[str, Any], ctx: ToolContext) -> ToolOutput:
    target = resolve(args["path"], ctx)
    if not target.is_file():
        raise ToolInputError(f"not a file: {args['path']!r}")
    text = _decode(await asyncio.to_thread(_read_nofollow, target), args["path"])
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + f"\n[truncated: showing {MAX_CHARS} of {len(text)} characters]"
    return ToolOutput(text)


def _list(target: Path, ctx: ToolContext, recursive: bool) -> str:
    if not target.exists():
        return "(empty)"
    if not target.is_dir():
        raise ToolInputError(f"not a directory: {_display(target, ctx)}")
    lines: list[str] = []
    for current, dirnames, filenames in os.walk(target, followlinks=False):
        here = Path(current)
        dirnames.sort()
        for name in sorted([*dirnames, *filenames]):
            p = here / name  # `here` is under the resolved target; symlinks are not followed
            shown = _display(p, ctx)
            if name in dirnames:
                lines.append(f"{shown}/")
            else:
                lines.append(f"{shown}  ({p.lstat().st_size} bytes)")
        if not recursive:
            break
    lines.sort()
    if not lines:
        return "(empty)"
    if len(lines) > MAX_LIST:
        return "\n".join(lines[:MAX_LIST]) + f"\n[stopped at {MAX_LIST} entries]"
    return "\n".join(lines)


async def _list_tool(args: dict[str, Any], ctx: ToolContext) -> ToolOutput:
    path = args.get("path", "files")
    target = resolve(path, ctx)
    return ToolOutput(await asyncio.to_thread(_list, target, ctx, args.get("recursive", False)))


def _search(target: Path, ctx: ToolContext, query: str) -> str:
    needle = az_casefold(query)
    hits: list[str] = []
    scanned = skipped = 0
    files = (
        [target]
        if target.is_file()
        else sorted(Path(d) / f for d, _, fs in os.walk(target, followlinks=False) for f in fs)
    )
    for f in files:
        if f.is_symlink() or not f.is_file():
            continue
        if f.stat().st_size > MAX_SEARCH_BYTES:
            skipped += 1
            continue
        try:
            text = _decode(f.read_bytes(), f.name)
        except ToolInputError:
            skipped += 1
            continue
        scanned += 1
        shown = _display(f.resolve(), ctx)
        for n, line in enumerate(text.splitlines(), start=1):
            if needle in az_casefold(line):
                hits.append(f"{shown}:{n}: {line.strip()[:_LINE_CHARS]}")
                if len(hits) >= MAX_HITS:
                    return "\n".join(hits) + f"\n[stopped at {MAX_HITS} matches]"
    summary = (
        f"{len(hits)} matches in {scanned} text files; {skipped} skipped (binary or too large)"
    )
    return ("\n".join(hits) + "\n\n" + summary) if hits else summary


async def _search_tool(args: dict[str, Any], ctx: ToolContext) -> ToolOutput:
    target = resolve(args.get("path", "files"), ctx)
    if not target.exists():
        return ToolOutput("0 matches (path does not exist)")
    return ToolOutput(await asyncio.to_thread(_search, target, ctx, args["query"]))


def _write(target: Path, content: str) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8")
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    except OSError as e:
        raise ToolInputError(f"cannot write {target.name!r}: {e.strerror}") from e
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return len(data)


async def _write_tool(args: dict[str, Any], ctx: ToolContext) -> ToolOutput:
    path = args["path"]
    raw = ctx.out_dir / PurePosixPath(path).relative_to("out") if path.startswith("out/") else None
    if raw is not None and raw.is_symlink():
        raise ToolInputError(f"refusing to write through a symlink: {path!r}")
    target = resolve(path, ctx, roots=("out",))
    if target.is_dir():
        raise ToolInputError(f"is a directory: {path!r}")
    size = await asyncio.to_thread(_write, target, args["content"])
    return ToolOutput(f"wrote {_display(target, ctx)} ({size} bytes)")


_PATH_SCHEMA = {"type": "string", "description": "files, out, or a path under them"}

FILE_LIST = Tool(
    name="file.list",
    description="List files under files/ (the user's workspace) or out/ (this run's outputs).",
    input_schema={
        "type": "object",
        "properties": {
            "path": {**_PATH_SCHEMA, "default": "files"},
            "recursive": {"type": "boolean", "default": False},
        },
        "additionalProperties": False,
    },
    tier="read",
    fn=_list_tool,
)

FILE_READ = Tool(
    name="file.read",
    description=(
        "Read a UTF-8 text file. Paths start with files/ (the user's workspace files) "
        "or out/ (files produced in this run). For Excel, Word or PDF use code_exec."
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

FILE_SEARCH = Tool(
    name="file.search",
    description=(
        "Find lines containing a text in UTF-8 text files under files/ or out/. "
        "Case-insensitive with Azerbaijani rules (İ/i, I/ı); plain text, not a regex."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1},
            "path": {**_PATH_SCHEMA, "default": "files"},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    tier="read",
    fn=_search_tool,
)

FILE_WRITE = Tool(
    name="file.write",
    description=(
        "Write a UTF-8 text file into out/ (this run's outputs), replacing it if it exists. "
        "For xlsx, docx, pdf or charts use code_exec with the matching skill."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "e.g. out/summary.md"},
            "content": {"type": "string", "maxLength": MAX_WRITE_CHARS},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    },
    tier="local",
    fn=_write_tool,
)
