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
    ("code", "stderr", "gone"),
    [
        (1, "Error response from daemon: container abc is not running", True),
        (126, 'OCI runtime exec failed: cannot execute in container "abc" in state stopped', True),
        (0, "Error response from daemon: noise", False),
        (1, "Traceback (most recent call last):", False),
    ],
)
def test_container_gone_covers_daemon_and_runtime_messages(
    code: int, stderr: str, gone: bool
) -> None:
    assert _container_gone(code, stderr) is gone
