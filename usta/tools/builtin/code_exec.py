"""code_exec: run Python in the run's gVisor sandbox (SPEC §7, §10)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from usta.core.sandbox import ExecResult
from usta.core.workspace import RunDirs
from usta.ports import SandboxPort
from usta.tools.registry import Tool, ToolContext, ToolOutput

STREAM_CHARS = 5_000  # per stream; layer-1 offload (M3) will keep the rest as a file
OUT_DIR_CAP_BYTES = 200 * 1024 * 1024
TIMEOUT_S = 60.0

DESCRIPTION = """\
Run Python 3.12 code in an isolated sandbox with no network access.
- /workspace is the user's files/ folder (read-only); /out is this run's out/ folder (read-write).
  So files/x.xlsx in file tools is /workspace/x.xlsx here, and out/y.pdf is /out/y.pdf.
- /skills holds skill scripts (read-only); load the skill with skill.load first.
- Each call is a fresh process: keep state in files under /out, not in variables.
- Installed: pandas, openpyxl, matplotlib, reportlab, pdfplumber, python-docx, babel. No pip install.
- 60 s per call. print() what you need to see; each output stream is cut at 5,000 characters."""

Snapshot = dict[str, tuple[int, int]]


def _snapshot(out_dir: Path) -> Snapshot:
    snap: Snapshot = {}
    if not out_dir.is_dir():
        return snap
    for current, _, files in os.walk(out_dir, followlinks=False):
        for name in files:
            p = Path(current) / name
            st = p.lstat()
            snap["out/" + p.relative_to(out_dir).as_posix()] = (st.st_size, st.st_mtime_ns)
    return snap


def _cut(text: str) -> str:
    if len(text) <= STREAM_CHARS:
        return text
    return text[:STREAM_CHARS] + f"\n[truncated: {STREAM_CHARS} of {len(text)} characters shown]"


def _render(res: ExecResult, changed: list[str], after: Snapshot) -> str:
    head = (
        f"timed out after {TIMEOUT_S:.0f} s (process killed)"
        if res.timed_out
        else f"exit_code: {res.exit_code}"
    )
    parts = [head]
    if res.stdout:
        parts.append("stdout:\n" + _cut(res.stdout))
    if res.stderr:
        parts.append("stderr:\n" + _cut(res.stderr))
    if res.truncated:
        parts.append("[output over the sandbox limit was cut]")
    if changed:
        parts.append(
            "files changed in out/:\n" + "\n".join(f"- {p} ({after[p][0]} bytes)" for p in changed)
        )
    return "\n".join(parts)


def make_code_exec(sandbox: SandboxPort) -> Tool:
    async def run(args: dict[str, Any], ctx: ToolContext) -> ToolOutput:
        before = await asyncio.to_thread(_snapshot, ctx.out_dir)
        res = await sandbox.exec(
            ctx.run.id,
            RunDirs(files=ctx.files_dir, out=ctx.out_dir),
            ("python", "-"),
            stdin=args["code"],
            timeout_s=TIMEOUT_S,
        )
        after = await asyncio.to_thread(_snapshot, ctx.out_dir)
        changed = sorted(p for p, st in after.items() if before.get(p) != st)
        text = _render(res, changed, after)
        total = sum(size for size, _ in after.values())
        if total > OUT_DIR_CAP_BYTES:
            return ToolOutput(
                text + f"\nERROR: out/ holds {total} bytes, over the {OUT_DIR_CAP_BYTES}-byte "
                "limit; delete files you do not need before continuing.",
                is_error=True,
            )
        return ToolOutput(text, is_error=res.timed_out or res.exit_code != 0)

    return Tool(
        name="code_exec",
        description=DESCRIPTION,
        input_schema={
            "type": "object",
            "properties": {"code": {"type": "string", "minLength": 1, "maxLength": 100_000}},
            "required": ["code"],
            "additionalProperties": False,
        },
        tier="local",
        fn=run,
    )
