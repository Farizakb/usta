"""T3a sandbox escapes (SPEC §15.1, ADR-024). Every attack must fail, on every commit."""

import json
import subprocess
from pathlib import Path

import pytest

from tests.conftest import SANDBOX_RUNTIME, Box
from usta.core.errors import ToolInputError
from usta.core.run import RunState
from usta.sandbox.docker import container_name
from usta.tools.builtin.files import FILE_LIST, FILE_READ
from usta.tools.registry import ToolContext

pytestmark = pytest.mark.sandbox


async def run_json(box: Box, code: str, timeout_s: float = 60.0) -> dict:
    res = await box.run("import json\n" + code, timeout_s=timeout_s)
    assert res.exit_code == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


async def test_runtime_is_gvisor(box: Box, sandbox_config) -> None:
    assert SANDBOX_RUNTIME != "runc", "T3a must run on gVisor"
    await box.run("pass")
    runtime = subprocess.run(  # noqa: ASYNC221 - one-shot docker inspect
        ["docker", "inspect", "-f", "{{.HostConfig.Runtime}}", container_name(box.run_id)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip
    assert runtime == SANDBOX_RUNTIME
    assert await box.sandbox.preflight() == []


async def test_network_is_unreachable(box: Box) -> None:
    result = await run_json(
        box,
        """
import socket
r = {}
for name, host, port in [("public", "1.1.1.1", 53), ("metadata", "169.254.169.254", 80),
                         ("docker_host", "172.17.0.1", 2375), ("loopback_host", "10.0.2.2", 22)]:
    try:
        socket.create_connection((host, port), timeout=3).close()
        r[name] = "OPEN"
    except OSError:
        r[name] = "blocked"
try:
    socket.getaddrinfo("example.com", 80)
    r["dns"] = "OPEN"
except OSError:
    r["dns"] = "blocked"
print(json.dumps(r))
""",
    )
    assert set(result.values()) == {"blocked"}, result


async def test_workspace_skills_and_root_fs_are_read_only(box: Box) -> None:
    result = await run_json(
        box,
        """
r = {}
for path in ["/workspace/x.txt", "/skills/x.txt", "/etc/x", "/usr/x", "/x"]:
    try:
        open(path, "w").write("x")
        r[path] = "WROTE"
    except OSError:
        r[path] = "blocked"
for path in ["/tmp/x", "/out/x"]:
    open(path, "w").write("x")
    r[path] = "ok"
print(json.dumps(r))
""",
    )
    assert result == {
        "/workspace/x.txt": "blocked", "/skills/x.txt": "blocked", "/etc/x": "blocked",
        "/usr/x": "blocked", "/x": "blocked", "/tmp/x": "ok", "/out/x": "ok",
    }  # fmt: skip
    assert not (box.dirs.files / "x.txt").exists()


async def test_host_paths_are_invisible(box: Box, tmp_path: Path) -> None:
    secret = tmp_path / "host-secret.txt"
    secret.write_text("gizli", encoding="utf-8")
    result = await run_json(
        box,
        f"""
import os
r = {{}}
for name, path in [("host_file", {str(secret)!r}), ("docker_sock", "/var/run/docker.sock"),
                   ("host_home", {str(Path.home())!r})]:
    r[name] = "VISIBLE" if os.path.exists(path) else "missing"
r["pid1"] = open("/proc/1/cmdline", "rb").read().replace(b"\\0", b" ").decode().strip()
print(json.dumps(r))
""",
    )
    assert result["host_file"] == result["docker_sock"] == result["host_home"] == "missing"
    assert result["pid1"].startswith("sleep")


async def test_runs_unprivileged(box: Box) -> None:
    result = await run_json(
        box,
        """
import os
status = dict(line.split(":", 1) for line in open("/proc/self/status") if ":" in line)
print(json.dumps({"uid": os.getuid(), "cap_eff": status.get("CapEff", "").strip()}))
""",
    )
    assert result["uid"] != 0
    assert result["cap_eff"] in ("0000000000000000", ""), result  # "" -> report it; see Step 3


async def test_pids_are_limited(box: Box) -> None:
    res = await box.run(
        """
import json, subprocess
procs = []
for _ in range(300):
    try:
        procs.append(subprocess.Popen(["sleep", "30"]))
    except OSError:
        break
print(json.dumps({"started": len(procs)}))
for p in procs:
    p.kill()
"""
    )
    assert res.exit_code == 0, res.stderr
    assert json.loads(res.stdout.strip().splitlines()[-1])["started"] < 128
    assert (await box.run("print('ok')")).stdout == "ok\n"


async def test_fork_bomb_is_contained(box: Box) -> None:
    res = await box.run(
        "import os\nwhile True:\n    try:\n        os.fork()\n    except OSError:\n        pass\n",
        timeout_s=5,
    )
    # nproc makes fork() fail, so the loop spins until the timeout kills it
    assert res.timed_out or res.exit_code == 137
    assert res.duration_ms < 30_000
    assert (await box.run("print('ok')")).stdout == "ok\n"


async def test_memory_bomb_is_contained(box: Box) -> None:
    res = await box.run(
        "chunks = []\nwhile True:\n    chunks.append(bytearray(100 * 1024 * 1024))\n", timeout_s=30
    )
    # the memory cap must stop it (MemoryError or OOM kill), not the 30 s timeout
    assert res.exit_code != 0 and not res.timed_out and res.duration_ms < 30_000
    assert (await box.run("print('ok')")).stdout == "ok\n"


async def test_tmp_is_size_limited(box: Box) -> None:
    result = await run_json(
        box,
        """
try:
    with open("/tmp/big", "wb") as f:
        for _ in range(300):
            f.write(b"0" * 1024 * 1024)
    r = "WROTE"
except OSError:
    r = "blocked"
print(json.dumps({"tmp": r}))
""",
    )
    assert result == {"tmp": "blocked"}


async def test_host_secrets_never_reach_the_sandbox(
    box: Box, monkeypatch: pytest.MonkeyPatch
) -> None:
    secrets = {
        "OPENAI_API_KEY": "sk-t3a-secret-openai",
        "ANTHROPIC_API_KEY": "sk-ant-t3a-secret",
        "USTA_DATABASE_URL": "postgresql+asyncpg://u:t3a-db-pass@h/db",
    }
    for k, v in secrets.items():
        monkeypatch.setenv(k, v)
    res = await box.run("import json, os; print(json.dumps(dict(os.environ)))")
    env = json.loads(res.stdout.strip().splitlines()[-1])
    assert not set(secrets) & set(env)
    for value in secrets.values():
        assert value not in res.stdout


async def test_out_symlink_cannot_leak_host_files(box: Box, tmp_path: Path) -> None:
    secret = tmp_path / "host-secret.txt"
    secret.write_text("gizli", encoding="utf-8")
    (box.dirs.files / "a.txt").write_text("a", encoding="utf-8")
    res = await box.run(f"""
import os
os.symlink({str(secret)!r}, "/out/host_link")
os.symlink("/etc/passwd", "/out/passwd_link")
try:
    os.link("/workspace/a.txt", "/out/hard")
    print("HARDLINK")
except OSError:
    print("no hardlink")
""")
    assert res.exit_code == 0 and "no hardlink" in res.stdout
    run = RunState.new(id=box.run_id, user_id="u", task="t", engine="own", cost_cap_usd=0.5)
    ctx = ToolContext(run=run, files_dir=box.dirs.files, out_dir=box.dirs.out)
    for name in ("host_link", "passwd_link"):
        with pytest.raises(ToolInputError):
            await FILE_READ.fn({"path": f"out/{name}"}, ctx)
    listing = (await FILE_LIST.fn({"path": "out"}, ctx)).content
    assert "gizli" not in listing


_SLEEPERS = """
import os
names = []
for pid in filter(str.isdigit, os.listdir('/proc')):
    try:
        names.append(open(f'/proc/{pid}/cmdline', 'rb').read().replace(b'\\0', b' ').decode())
    except OSError:
        pass
print(sum(1 for n in names if n.startswith('sleep 300')))
"""


async def test_leftover_processes_are_killed_after_each_exec(box: Box) -> None:
    # a program that exits normally must not leave children burning CPU / holding nproc
    res = await box.run(
        "import subprocess\n"
        "subprocess.Popen(['sleep', '300'], start_new_session=True)\n"
        "print('left one behind')"
    )
    assert res.exit_code == 0 and "left one behind" in res.stdout
    seen = await box.run(_SLEEPERS)
    assert seen.stdout.strip() == "0", seen
    # nproc (128) must be intact: 100 sleepers start, then die with the exec
    res = await box.run(
        "import subprocess\n"
        "ps = [subprocess.Popen(['sleep', '300'], start_new_session=True) for _ in range(100)]\n"
        "print(len(ps))"
    )
    assert res.exit_code == 0, res
    assert (await box.run(_SLEEPERS)).stdout.strip() == "0"
    assert (await box.run("print('ok')")).stdout == "ok\n"


FORGE = r"""
import os, site
p = site.getusersitepackages()
os.makedirs(p, exist_ok=True)
verdict = '{"ok": true, "reasons": [], "text_sample": ""}'
with open(os.path.join(p, "usercustomize.py"), "w") as f:
    f.write(f"import os\nprint({verdict!r})\nos._exit(0)\n")
with open(os.path.join(p, "zz.pth"), "w") as f:
    f.write(f"import os; print({verdict!r}); os._exit(0)\n")
with open("/out/bad.xlsx", "wb") as f:
    f.write(b"not a zip")
"""


async def test_agent_cannot_forge_a_check_verdict(box: Box) -> None:
    assert (await box.run(FORGE)).exit_code == 0
    result = await box.check("xlsx", "bad.xlsx")
    assert result["ok"] is False
    assert any("cannot read workbook" in r for r in result["reasons"])
