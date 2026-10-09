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


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le", "utf-16-be", "utf-8-sig", "utf-8"])
async def test_reads_bom_encoded_azerbaijani_text(ctx: ToolContext, encoding: str) -> None:
    text = "Salam dünya: İSTİQAMƏT, ğ ş ı ö ü ç ə"
    data = text.encode(encoding)
    if encoding == "utf-16-le":
        data = b"\xff\xfe" + data
    elif encoding == "utf-16-be":
        data = b"\xfe\xff" + data
    (ctx.files_dir / "x.txt").write_bytes(data)
    assert (await FILE_READ.fn({"path": "files/x.txt"}, ctx)).content == text


async def test_file_with_nul_bytes_is_refused(ctx: ToolContext) -> None:
    (ctx.files_dir / "a.bin").write_bytes(b"PK\x03\x04\x00\x00data")
    with pytest.raises(ToolInputError, match="binary or unsupported encoding"):
        await FILE_READ.fn({"path": "files/a.bin"}, ctx)


async def test_undecodable_file_is_refused(ctx: ToolContext) -> None:
    (ctx.files_dir / "a.txt").write_bytes(b"\xff\xfeab\xc3")  # BOM then a truncated UTF-16 unit
    (ctx.files_dir / "b.txt").write_bytes(b"caf\xe9")  # latin-1, not UTF-8
    for name in ("a.txt", "b.txt"):
        with pytest.raises(ToolInputError, match="binary or unsupported encoding"):
            await FILE_READ.fn({"path": f"files/{name}"}, ctx)
