"""Docker-driven sandbox (SPEC §10, ADR-024): one container per run, a fresh process per call.
gVisor (runsc) everywhere; runc only as docker_hardened in the test profile (P8). Drives the
docker CLI so there is no Docker SDK dependency (M1 Plan Decision 1)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path

from usta.core.errors import SandboxError
from usta.core.sandbox import ExecResult
from usta.core.workspace import RunDirs

log = logging.getLogger(__name__)

LABEL = "usta.run"
OUTPUT_CAP_BYTES = 256_000  # per stream; code_exec caps again in characters
OUTER_GRACE_S = 10.0  # the inner `timeout` should always win; this catches a wedged runtime
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
_DOCKER_ENV = ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONFIG", "DOCKER_CONTEXT", "XDG_RUNTIME_DIR")


def container_name(run_id: str) -> str:
    if not _RUN_ID.fullmatch(run_id):
        raise SandboxError(f"run id not usable as a container name: {run_id!r}")
    return f"usta-sbx-{run_id}"


@dataclass(frozen=True)
class SandboxConfig:
    image: str
    runtime: str  # docker runtime name: runsc, runsc-kvm, or runc (test profile only)
    gvisor: bool  # True: preflight requires the runtime to be runsc (P8)
    skills_dir: Path
    uid: int
    gid: int
    cpus: str = "1"
    memory: str = "1g"
    pids: int = 128
    tmp_size: str = "256m"


async def _read_capped(stream: asyncio.StreamReader, cap: int) -> tuple[bytes, bool]:
    buf = bytearray()
    over = False
    while chunk := await stream.read(65536):
        room = cap - len(buf)
        if room > 0:
            buf += chunk[:room]
        if len(chunk) > max(room, 0):
            over = True
    return bytes(buf), over


async def _feed(proc: asyncio.subprocess.Process, data: bytes) -> None:
    assert proc.stdin is not None
    try:
        if data:
            proc.stdin.write(data)
            await proc.stdin.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass  # the process exited before reading all input; its exit code says why
    finally:
        proc.stdin.close()


def _text(data: bytes) -> str:
    # Postgres text cannot hold NUL; audit rows store this output.
    return data.decode("utf-8", errors="replace").replace("\x00", "�")


def _cut_text(data: bytes) -> str:
    """Like _text, but for a stream cut at the byte cap: drop a split trailing character
    instead of turning it into U+FFFD (which would push the text past the cap)."""
    for drop in range(4):
        try:
            data[: len(data) - drop].decode("utf-8")
        except UnicodeDecodeError:
            continue
        return _text(data[: len(data) - drop])
    return _text(data)


class DockerSandbox:
    def __init__(self, cfg: SandboxConfig, *, docker: str = "docker") -> None:
        self._cfg = cfg
        self._docker = docker
        self._started: set[str] = set()

    def run_args(self, run_id: str, dirs: RunDirs) -> list[str]:
        c = self._cfg
        # docker needs absolute bind sources; the workspace root is often relative (Settings)
        files, out, skills = dirs.files.resolve(), dirs.out.resolve(), c.skills_dir.resolve()
        for what, path in (("files", files), ("out", out), ("skills", skills)):
            if "," in str(path):
                raise SandboxError(f"{what} path contains a comma, not mountable: {path}")
        return [
            self._docker, "run", "--detach",
            "--name", container_name(run_id),
            "--label", f"{LABEL}={run_id}",
            "--runtime", c.runtime,
            "--network", "none",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--read-only",
            "--tmpfs", f"/tmp:rw,nosuid,nodev,size={c.tmp_size}",
            "--user", f"{c.uid}:{c.gid}",
            "--cpus", c.cpus,
            "--memory", c.memory,
            "--memory-swap", c.memory,
            "--pids-limit", str(c.pids),
            "--mount", f"type=bind,source={files},target=/workspace,readonly",
            "--mount", f"type=bind,source={out},target=/out",
            "--mount", f"type=bind,source={skills},target=/skills,readonly",
            "--workdir", "/out",
            c.image, "sleep", "infinity",
        ]  # fmt: skip

    async def _docker_cmd(self, *args: str, timeout_s: float = 60.0) -> tuple[int, str, str]:
        env = {k: v for k in _DOCKER_ENV if (v := os.environ.get(k))}
        proc = await asyncio.create_subprocess_exec(
            self._docker, *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )  # fmt: skip
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout_s)
        except TimeoutError as e:
            proc.kill()
            await proc.wait()
            raise SandboxError(f"docker {args[0]} timed out after {timeout_s:.0f}s") from e
        assert proc.returncode is not None
        return proc.returncode, _text(out), _text(err)

    async def _ensure(self, run_id: str, dirs: RunDirs) -> None:
        if run_id in self._started:
            return
        dirs.files.mkdir(parents=True, exist_ok=True)
        dirs.out.mkdir(parents=True, exist_ok=True)
        name = container_name(run_id)
        await self._docker_cmd("rm", "--force", name)  # a stale one from an earlier process
        code, _, err = await self._docker_cmd(*self.run_args(run_id, dirs)[1:])
        if code != 0:
            raise SandboxError(f"could not start the sandbox: {err.strip()}")
        self._started.add(run_id)

    async def exec(
        self,
        run_id: str,
        dirs: RunDirs,
        argv: Sequence[str],
        *,
        stdin: str = "",
        timeout_s: float = 60.0,
    ) -> ExecResult:
        for attempt in (1, 2):
            await self._ensure(run_id, dirs)
            result = await self._exec_once(run_id, argv, stdin, timeout_s)
            if result is not None:
                return result
            self._started.discard(run_id)  # the container is gone: recreate once
            if attempt == 2:
                raise SandboxError("the sandbox container stopped unexpectedly")
        raise AssertionError("unreachable")

    async def _exec_once(
        self, run_id: str, argv: Sequence[str], stdin: str, timeout_s: float
    ) -> ExecResult | None:
        secs = str(max(1, int(timeout_s)))
        cmd = [
            self._docker, "exec", "--interactive", container_name(run_id),
            "timeout", "--kill-after=2", secs, *argv,
        ]  # fmt: skip
        env = {k: v for k in _DOCKER_ENV if (v := os.environ.get(k))}
        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        assert proc.stdout is not None and proc.stderr is not None

        async def communicate() -> tuple[tuple[bytes, bool], tuple[bytes, bool]]:
            _, out, err = await asyncio.gather(
                _feed(proc, stdin.encode("utf-8")),
                _read_capped(proc.stdout, OUTPUT_CAP_BYTES),
                _read_capped(proc.stderr, OUTPUT_CAP_BYTES),
            )
            await proc.wait()
            return out, err

        try:
            (out, out_cut), (err, err_cut) = await asyncio.wait_for(
                communicate(), timeout_s + OUTER_GRACE_S
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            log.warning("sandbox %s: outer timeout; destroying the container", run_id)
            await self.release(run_id)
            return ExecResult(
                exit_code=-1, stdout="", stderr="", timed_out=True,
                duration_ms=int((time.monotonic() - started) * 1000),
            )  # fmt: skip
        code = proc.returncode
        assert code is not None
        stderr = _cut_text(err) if err_cut else _text(err)
        if code != 0 and stderr.startswith("Error response from daemon"):
            log.warning("sandbox %s: %s", run_id, stderr.strip())
            return None
        return ExecResult(
            exit_code=code,
            stdout=_cut_text(out) if out_cut else _text(out),
            stderr=stderr,
            timed_out=code == 124,  # GNU timeout's exit code
            truncated=out_cut or err_cut,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    async def release(self, run_id: str) -> None:
        self._started.discard(run_id)
        code, _, err = await self._docker_cmd("rm", "--force", container_name(run_id))
        if code != 0 and "No such container" not in err:
            log.warning("sandbox %s: release failed: %s", run_id, err.strip())

    async def reap(self, keep: Collection[str]) -> list[str]:
        """Remove labelled containers whose run is not in `keep` (crash leftovers)."""
        code, out, err = await self._docker_cmd(
            "ps", "--all", "--filter", f"label={LABEL}", "--format", f'{{{{.Label "{LABEL}"}}}}'
        )
        if code != 0:
            raise SandboxError(f"docker ps failed: {err.strip()}")
        removed = []
        for run_id in sorted({line.strip() for line in out.splitlines() if line.strip()}):
            if run_id not in keep:
                await self.release(run_id)
                removed.append(run_id)
        return removed

    async def preflight(self) -> list[str]:
        """Problems that must refuse startup (P8): no docker, wrong runtime, missing image."""
        c = self._cfg
        try:
            code, out, err = await self._docker_cmd("info", "--format", "{{json .Runtimes}}")
        except (OSError, SandboxError) as e:
            return [f"docker is not usable: {e}"]
        if code != 0:
            return [f"docker is not reachable: {err.strip()}"]
        problems = []
        runtimes = json.loads(out or "{}")
        rt = runtimes.get(c.runtime)
        if rt is None:
            problems.append(
                f"docker has no runtime {c.runtime!r} (has: {', '.join(sorted(runtimes))}); "
                "set USTA_GVISOR_RUNTIME or register runsc (ADR-005)"
            )
        elif c.gvisor and not str(rt.get("path", "")).endswith("runsc"):
            problems.append(f"P8: runtime {c.runtime!r} is not gVisor (path {rt.get('path')!r})")
        code, _, _ = await self._docker_cmd("image", "inspect", "--format", "{{.Id}}", c.image)
        if code != 0:
            problems.append(
                f"sandbox image {c.image!r} not found; run scripts/build_sandbox_image.sh"
            )
        if not c.skills_dir.is_dir():
            problems.append(f"skills directory not found: {c.skills_dir}")
        return problems
