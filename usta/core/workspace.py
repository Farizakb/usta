"""Workspace layout (SPEC §11.1): one place computes a run's files/ and out/ directories."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunDirs:
    files: Path  # workspaces/{user}/files: the user's files, read-only for the agent
    out: Path  # workspaces/{user}/runs/{run_id}/out: this run's outputs

    @classmethod
    def of(cls, root: Path, user_id: str, run_id: str) -> RunDirs:
        user = root / user_id
        return cls(files=user / "files", out=user / "runs" / run_id / "out")
