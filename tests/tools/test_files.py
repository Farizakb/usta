import os
from pathlib import Path

import pytest

from usta.core.errors import ToolInputError
from usta.core.run import RunState
from usta.tools.builtin.files import FILE_READ, MAX_CHARS
from usta.tools.registry import ToolContext


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    files = tmp_path / "u1" / "files"
    out = tmp_path / "u1" / "runs" / "r1" / "out"
    files.mkdir(parents=True)
    out.mkdir(parents=True)
    run = RunState.new(id="r1", user_id="u1", task="t", engine="own", cost_cap_usd=0.5)
    return ToolContext(run=run, files_dir=files, out_dir=out)


async def test_reads_workspace_and_output_files_as_utf8(ctx: ToolContext) -> None:
    (ctx.files_dir / "qeyd.txt").write_text("İSTİQAMƏT: Gəncə\n", encoding="utf-8")
    (ctx.out_dir / "hesabat.md").write_text("# Hesabat", encoding="utf-8")
    assert (await FILE_READ.fn({"path": "files/qeyd.txt"}, ctx)).content == "İSTİQAMƏT: Gəncə\n"
    assert (await FILE_READ.fn({"path": "out/hesabat.md"}, ctx)).content == "# Hesabat"


@pytest.mark.parametrize(
    "path",
    [
        "files/../../../etc/passwd",
        "/etc/passwd",
        "etc/passwd",
        "runs/r1/out/x",
        "files/../../u2/files/x",
    ],
)
async def test_paths_outside_the_workspace_are_refused(ctx: ToolContext, path: str) -> None:
    with pytest.raises(ToolInputError):
        await FILE_READ.fn({"path": path}, ctx)


async def test_nul_byte_in_path_is_refused_cleanly(ctx: ToolContext) -> None:
    with pytest.raises(ToolInputError, match="NUL"):
        await FILE_READ.fn({"path": "files/a\x00b"}, ctx)


async def test_symlink_escape_is_refused(ctx: ToolContext, tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("token", encoding="utf-8")
    os.symlink(secret, ctx.files_dir / "link.txt")
    with pytest.raises(ToolInputError, match="escapes"):
        await FILE_READ.fn({"path": "files/link.txt"}, ctx)


async def test_missing_file_and_directory_are_clear_errors(ctx: ToolContext) -> None:
    with pytest.raises(ToolInputError, match="not a file"):
        await FILE_READ.fn({"path": "files/yoxdur.txt"}, ctx)
    with pytest.raises(ToolInputError, match="not a file"):
        await FILE_READ.fn({"path": "files"}, ctx)


async def test_large_files_are_truncated_with_a_marker(ctx: ToolContext) -> None:
    (ctx.files_dir / "big.txt").write_text("ə" * (MAX_CHARS + 10), encoding="utf-8")
    out = (await FILE_READ.fn({"path": "files/big.txt"}, ctx)).content
    assert out.startswith("ə" * MAX_CHARS)
    assert out.endswith(f"[truncated: showing {MAX_CHARS} of {MAX_CHARS + 10} characters]")
