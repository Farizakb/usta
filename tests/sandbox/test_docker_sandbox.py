import asyncio
from dataclasses import replace

import pytest

from tests.conftest import SANDBOX_RUNTIME, Box
from usta.sandbox.docker import OUTPUT_CAP_BYTES, DockerSandbox, container_name

pytestmark = pytest.mark.sandbox


async def test_hello_and_azerbaijani_round_trip(box: Box) -> None:
    res = await box.run("print('Salam, Gəncə! İŞIQ ə')")
    assert res.exit_code == 0 and res.stdout == "Salam, Gəncə! İŞIQ ə\n"
    proc = await asyncio.create_subprocess_exec(
        "docker", "inspect", "-f", "{{.HostConfig.Runtime}}", container_name(box.run_id),
        stdout=asyncio.subprocess.PIPE,
    )  # fmt: skip
    runtime = (await proc.communicate())[0].decode().strip()
    assert runtime == SANDBOX_RUNTIME


async def test_state_lives_only_in_files(box: Box) -> None:
    await box.run("x = 1\nopen('/out/state.txt', 'w').write('saxla')")
    res = await box.run("print('x' in globals()); print(open('/out/state.txt').read())")
    assert res.stdout.split() == ["False", "saxla"]
    assert (box.dirs.out / "state.txt").read_text() == "saxla"


async def test_workspace_is_visible_read_only(box: Box) -> None:
    (box.dirs.files / "qeyd.txt").write_text("Gəncə", encoding="utf-8")
    res = await box.run("print(open('/workspace/qeyd.txt', encoding='utf-8').read())")
    assert res.stdout.strip() == "Gəncə"


async def test_nonzero_exit_and_stderr(box: Box) -> None:
    res = await box.run("import sys; print('xəta', file=sys.stderr); sys.exit(3)")
    assert res.exit_code == 3 and "xəta" in res.stderr and not res.timed_out


async def test_timeout_kills_and_the_next_call_works(box: Box) -> None:
    res = await box.run("while True:\n    pass", timeout_s=2)
    assert res.timed_out and res.duration_ms < 15_000
    assert (await box.run("print('ok')")).stdout == "ok\n"


async def test_output_flood_is_capped(box: Box) -> None:
    # many small writes: under gVisor a single write over 64 KiB is cut by the runtime's stdio
    # relay before it reaches the driver (see task-4 report), so one giant print would not flood.
    res = await box.run("for _ in range(3000):\n    print('ə' * 1000)")
    assert res.truncated and len(res.stdout.encode()) <= OUTPUT_CAP_BYTES


async def test_release_removes_and_next_exec_recreates(box: Box) -> None:
    await box.run("print(1)")
    await box.sandbox.release(box.run_id)
    assert (await box.run("print(2)")).stdout == "2\n"


async def test_reap_keeps_listed_runs(box: Box, sandbox_config) -> None:
    await box.run("print(1)")
    other = DockerSandbox(sandbox_config)
    assert box.run_id not in await other.reap(keep={box.run_id})
    assert box.run_id in await other.reap(keep=set())


async def test_preflight_ok_then_reports_missing_image_and_runtime(sandbox_config) -> None:
    assert await DockerSandbox(sandbox_config).preflight() == []
    problems = await DockerSandbox(
        replace(sandbox_config, image="usta-sandbox:does-not-exist", runtime="no-such-rt")
    ).preflight()
    assert any("no runtime 'no-such-rt'" in p for p in problems)
    assert any("not found" in p for p in problems)


async def test_preflight_refuses_runc_posing_as_gvisor(sandbox_config) -> None:
    problems = await DockerSandbox(replace(sandbox_config, runtime="runc", gvisor=True)).preflight()
    assert any("not gVisor" in p for p in problems)


async def _client_pids(box: Box) -> list[str]:
    proc = await asyncio.create_subprocess_exec(
        "pgrep", "-f", f"docker exec.*{container_name(box.run_id)}",
        stdout=asyncio.subprocess.PIPE,
    )  # fmt: skip
    return (await proc.communicate())[0].decode().split()


async def test_cancel_kills_the_docker_exec_client(box: Box) -> None:
    await box.run("print(1)")  # container exists
    task = asyncio.create_task(box.run("import time; time.sleep(30)"))
    await asyncio.sleep(1.5)
    assert await _client_pids(box)  # the client is running
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    assert await _client_pids(box) == []


async def test_concurrent_execs_on_one_run_both_succeed(box: Box) -> None:
    a, b = await asyncio.gather(box.run("print('a')"), box.run("print('b')"))
    assert (a.exit_code, a.stdout, b.exit_code, b.stdout) == (0, "a\n", 0, "b\n")
