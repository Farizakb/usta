from pathlib import Path

from usta.core.workspace import RunDirs


def test_run_dirs_layout() -> None:
    dirs = RunDirs.of(Path("/w"), "fariz", "r1")
    assert dirs.files == Path("/w/fariz/files")
    assert dirs.out == Path("/w/fariz/runs/r1/out")
