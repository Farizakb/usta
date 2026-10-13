from pathlib import Path

import pytest

from tests.conftest import Box
from tests.fakes import FakeSandbox
from usta.core.run import RunState
from usta.core.sandbox import ExecResult
from usta.tools.builtin import code_exec as ce
from usta.tools.builtin.code_exec import STREAM_CHARS, make_code_exec
from usta.tools.registry import ToolContext


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    files = tmp_path / "u1" / "files"
    out = tmp_path / "u1" / "runs" / "r1" / "out"
    files.mkdir(parents=True)
    out.mkdir(parents=True)
    run = RunState.new(id="r1", user_id="u1", task="t", engine="own", cost_cap_usd=0.5)
    return ToolContext(run=run, files_dir=files, out_dir=out)


async def test_passes_code_on_stdin_and_renders_output(ctx: ToolContext) -> None:
    sb = FakeSandbox(lambda *_: ExecResult(exit_code=0, stdout="Salam\n", stderr=""))
    res = await make_code_exec(sb).fn({"code": "print('Salam')"}, ctx)
    assert sb.calls == [("r1", ("python", "-"), "print('Salam')")]
    assert not res.is_error
    assert res.content.startswith("exit_code: 0\n")
    assert "stdout:\nSalam" in res.content


async def test_nonzero_exit_is_an_error(ctx: ToolContext) -> None:
    sb = FakeSandbox(
        lambda *_: ExecResult(exit_code=1, stdout="", stderr="Traceback ... ZeroDivisionError")
    )
    res = await make_code_exec(sb).fn({"code": "1/0"}, ctx)
    assert res.is_error and "ZeroDivisionError" in res.content


async def test_timeout_is_explained(ctx: ToolContext) -> None:
    sb = FakeSandbox(lambda *_: ExecResult(exit_code=124, stdout="", stderr="", timed_out=True))
    res = await make_code_exec(sb).fn({"code": "while True: pass"}, ctx)
    assert res.is_error and "timed out after 60 s" in res.content


async def test_lists_created_and_changed_files(ctx: ToolContext) -> None:
    (ctx.out_dir / "old.txt").write_text("same", encoding="utf-8")

    def handler(run_id, dirs, argv, stdin):
        (dirs.out / "hesabat.pdf").write_bytes(b"%PDF-1.4 x")
        return ExecResult(exit_code=0, stdout="", stderr="")

    res = await make_code_exec(FakeSandbox(handler)).fn({"code": "..."}, ctx)
    assert "files changed in out/:\n- out/hesabat.pdf (10 bytes)" in res.content
    assert "old.txt" not in res.content


async def test_long_streams_are_cut_with_a_marker(ctx: ToolContext) -> None:
    sb = FakeSandbox(
        lambda *_: ExecResult(
            exit_code=0, stdout="ə" * (STREAM_CHARS + 10), stderr="", truncated=True
        )
    )
    res = await make_code_exec(sb).fn({"code": "..."}, ctx)
    assert f"[truncated: {STREAM_CHARS} of {STREAM_CHARS + 10} characters shown]" in res.content
    assert "[output over the sandbox limit was cut]" in res.content


async def test_out_dir_over_cap_is_an_error(ctx: ToolContext, monkeypatch) -> None:
    monkeypatch.setattr(ce, "OUT_DIR_CAP_BYTES", 5)

    def handler(run_id, dirs, argv, stdin):
        (dirs.out / "big.bin").write_bytes(b"123456")
        return ExecResult(exit_code=0, stdout="", stderr="")

    res = await make_code_exec(FakeSandbox(handler)).fn({"code": "..."}, ctx)
    assert res.is_error and "over the 5-byte limit" in res.content


@pytest.mark.sandbox
async def test_real_sandbox_writes_a_file_the_host_sees(box: Box) -> None:
    run = RunState.new(id=box.run_id, user_id="u1", task="t", engine="own", cost_cap_usd=0.5)
    ctx = ToolContext(run=run, files_dir=box.dirs.files, out_dir=box.dirs.out)
    res = await make_code_exec(box.sandbox).fn(
        {"code": "open('/out/qeyd.txt', 'w', encoding='utf-8').write('ə')"}, ctx
    )
    assert not res.is_error, res.content
    assert (box.dirs.out / "qeyd.txt").read_text(encoding="utf-8") == "ə"
    assert "out/qeyd.txt (2 bytes)" in res.content
