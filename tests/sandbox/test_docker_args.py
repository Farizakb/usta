from pathlib import Path

import pytest

from usta.core.errors import SandboxError
from usta.core.workspace import RunDirs
from usta.sandbox.docker import LABEL, DockerSandbox, SandboxConfig, _container_gone, container_name

CFG = SandboxConfig(
    image="usta-sandbox:1", runtime="runsc", gvisor=True, skills_dir=Path("/repo/skills"),
    uid=1000, gid=1000,
)  # fmt: skip
DIRS = RunDirs(files=Path("/w/u/files"), out=Path("/w/u/runs/r1/out"))


def test_run_args_carry_every_hardening_flag() -> None:
    args = DockerSandbox(CFG).run_args("r1", DIRS)
    joined = " ".join(args)
    for flag in (
        "--runtime runsc", "--network none", "--cap-drop ALL",
        "--security-opt no-new-privileges", "--read-only", "--user 1000:1000",
        "--cpus 1", "--memory 1g", "--memory-swap 1g", "--pids-limit 4096",
        "--ulimit nproc=128:128",
        f"--label {LABEL}=r1", f"--name {container_name('r1')}",
    ):  # fmt: skip
        assert flag in joined, flag
    assert "type=bind,source=/w/u/files,target=/workspace,readonly" in args
    assert "type=bind,source=/w/u/runs/r1/out,target=/out" in args
    assert "type=bind,source=/repo/skills,target=/skills,readonly" in args
    assert any(a.startswith("/tmp:rw,nosuid,nodev,size=256m") for a in args)
    assert "-e" not in args and "--env" not in args and "--env-file" not in args  # P: no env vars
    assert args[-3:] == ["usta-sandbox:1", "sleep", "infinity"]


@pytest.mark.parametrize("bad", ["", "../x", "a b", "r1;rm", "x" * 200])
def test_bad_run_ids_are_refused(bad: str) -> None:
    with pytest.raises(SandboxError):
        container_name(bad)


def test_mount_paths_with_commas_are_refused() -> None:
    dirs = RunDirs(files=Path("/w/a,b/files"), out=Path("/w/a,b/out"))
    with pytest.raises(SandboxError, match="comma"):
        DockerSandbox(CFG).run_args("r1", dirs)


@pytest.mark.parametrize(
    ("code", "stdout", "stderr", "gone"),
    [
        (1, "", "Error response from daemon: container abc is not running", True),
        (
            126,
            "",
            'OCI runtime exec failed: cannot execute in container "abc" in state stopped',
            True,
        ),
        # seen on CI (systrap): the runtime's message is relayed on stdout
        (
            126,
            'OCI runtime exec failed: cannot execute in container "abc" in state stopped\r\n',
            "",
            True,
        ),
        (0, "", "Error response from daemon: noise", False),
        (1, "", "Traceback (most recent call last):", False),
        (1, "partial output", "", False),
    ],
)
def test_container_gone_covers_daemon_and_runtime_messages(
    code: int, stdout: str, stderr: str, gone: bool
) -> None:
    assert _container_gone(code, stdout, stderr) is gone


@pytest.mark.parametrize(
    ("inspect", "gone"),
    [
        ((0, "false\n", ""), True),  # stopped
        ((1, "", "Error: No such object"), True),  # removed
        ((0, "true\n", ""), False),  # user code merely printed the daemon's words
    ],
)
async def test_gone_text_is_confirmed_with_inspect(
    inspect: tuple[int, str, str], gone: bool
) -> None:
    sb = DockerSandbox(CFG)
    seen: list[tuple[str, ...]] = []

    async def fake(*args: str, timeout_s: float = 60.0) -> tuple[int, str, str]:
        seen.append(args)
        return inspect

    sb._docker_cmd = fake  # type: ignore[method-assign]
    text = "Error response from daemon: printed by user code"
    assert await sb._confirmed_gone("r1", 1, "", text) is gone
    assert seen == [("inspect", "-f", "{{.State.Running}}", container_name("r1"))]


async def test_no_inspect_when_the_text_does_not_match() -> None:
    sb = DockerSandbox(CFG)

    async def boom(*args: str, timeout_s: float = 60.0) -> tuple[int, str, str]:
        raise AssertionError("must not be called")

    sb._docker_cmd = boom  # type: ignore[method-assign]
    assert await sb._confirmed_gone("r1", 1, "", "Traceback") is False


async def test_cancelling_a_docker_command_kills_the_client(tmp_path: Path) -> None:
    import asyncio
    import os

    pidfile = tmp_path / "pid"
    fake = tmp_path / "fakedocker"
    fake.write_text(f"#!/bin/sh\necho $$ > {pidfile}\nexec sleep 300\n")
    fake.chmod(0o755)
    task = asyncio.create_task(DockerSandbox(CFG, docker=str(fake))._docker_cmd("ps"))
    for _ in range(100):
        if pidfile.exists() and pidfile.read_text().strip():
            break
        await asyncio.sleep(0.05)
    pid = int(pidfile.read_text())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
