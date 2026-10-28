"""File tools (SPEC §7): file.list, file.read, file.search over files/ and out/; file.write
into out/ only. Paths are 'files/...' or 'out/...'; nothing outside the user's workspace."""

from __future__ import annotations

import asyncio
import os
import stat
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


def resolve_in(
    path: str, ctx: ToolContext, roots: tuple[str, ...] = ("files", "out")
) -> tuple[Path, Path]:
    """(resolved root, resolved target) for 'files/...' or 'out/...'; refuses escapes."""
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
    return root, target


def resolve(path: str, ctx: ToolContext, roots: tuple[str, ...] = ("files", "out")) -> Path:
    return resolve_in(path, ctx, roots)[1]


def _display(target: Path, ctx: ToolContext) -> str:
    for prefix, root in (("files", ctx.files_dir), ("out", ctx.out_dir)):
        root = root.resolve()
        if target == root:
            return prefix
        if target.is_relative_to(root):
            return f"{prefix}/{target.relative_to(root).as_posix()}"
    raise ToolInputError(f"path escapes the workspace: {target}")


def _open_under(root: Path, target: Path, flags: int, *, make_dirs: bool = False) -> int:
    """Open `target` (checked by resolve_in to be under `root`) by walking from `root` one
    component at a time with O_NOFOLLOW. out/ is mounted read-write into the sandbox, so a
    directory swapped for a symlink after resolve_in() must not redirect the open outside
    the workspace. Raises OSError; callers turn it into ToolInputError."""
    parts = target.relative_to(root).parts
    if not parts:
        raise IsADirectoryError(21, "is the folder root, not a file")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for name in parts[:-1]:
            if make_dirs:
                try:
                    os.mkdir(name, 0o755, dir_fd=fd)
                except FileExistsError:
                    pass
            nxt = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return os.open(parts[-1], flags | os.O_NOFOLLOW, 0o644, dir_fd=fd)
    finally:
        os.close(fd)


def _read_under(root: Path, target: Path, shown: str) -> bytes:
    try:
        fd = _open_under(root, target, os.O_RDONLY | os.O_NONBLOCK)
    except OSError as e:
        raise ToolInputError(f"cannot open {shown!r}: {e.strerror}") from e
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise ToolInputError(f"not a regular file: {shown!r}")
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
    root, target = resolve_in(args["path"], ctx)
    if not target.is_file():
        raise ToolInputError(f"not a file: {args['path']!r}")
    data = await asyncio.to_thread(_read_under, root, target, args["path"])
    text = _decode(data, args["path"])
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


def _search_fold(text: str) -> str:
    """az_casefold, then ı→i: search wants recall, so i ı I İ all match each other."""
    return az_casefold(text).replace("ı", "i")


def _search(root: Path, target: Path, ctx: ToolContext, query: str) -> str:
    needle = _search_fold(query)
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
        shown = _display(f, ctx)
        try:
            if f.stat().st_size > MAX_SEARCH_BYTES:
                skipped += 1
                continue
            text = _decode(_read_under(root, f, shown), f.name)
        except (OSError, ToolInputError):
            skipped += 1
            continue
        scanned += 1
        for n, line in enumerate(text.splitlines(), start=1):
            if needle in _search_fold(line):
                hits.append(f"{shown}:{n}: {line.strip()[:_LINE_CHARS]}")
                if len(hits) >= MAX_HITS:
                    return "\n".join(hits) + f"\n[stopped at {MAX_HITS} matches]"
    summary = (
        f"{len(hits)} matches in {scanned} text files; {skipped} skipped (binary or too large)"
    )
    return ("\n".join(hits) + "\n\n" + summary) if hits else summary


async def _search_tool(args: dict[str, Any], ctx: ToolContext) -> ToolOutput:
    root, target = resolve_in(args.get("path", "files"), ctx)
    if not target.exists():
        return ToolOutput("0 matches (path does not exist)")
    return ToolOutput(await asyncio.to_thread(_search, root, target, ctx, args["query"]))


def _write(root: Path, target: Path, path: str, content: str) -> int:
    data = content.encode("utf-8")
    try:
        root.mkdir(parents=True, exist_ok=True)  # the run's own out/ dir
        fd = _open_under(
            root,
            target,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NONBLOCK,
            make_dirs=True,
        )
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    except OSError as e:
        raise ToolInputError(f"cannot write {path!r}: {e.strerror}") from e
    return len(data)


async def _write_tool(args: dict[str, Any], ctx: ToolContext) -> ToolOutput:
    path = args["path"]
    raw = ctx.out_dir / PurePosixPath(path).relative_to("out") if path.startswith("out/") else None
    if raw is not None and raw.is_symlink():
        raise ToolInputError(f"refusing to write through a symlink: {path!r}")
    root, target = resolve_in(path, ctx, roots=("out",))
    if target == root:
        raise ToolInputError("out/ is a folder; give a file path like out/summary.md")
    size = await asyncio.to_thread(_write, root, target, path, args["content"])
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
        "Case-insensitive; i, ı, I and İ all match each other; plain text, not a regex."
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
