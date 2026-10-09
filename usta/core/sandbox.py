"""Result of one sandboxed process (SPEC §10)."""

from usta.core.base import Frozen


class ExecResult(Frozen):
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    truncated: bool = False  # a stream went over the sandbox's byte cap and was cut
    duration_ms: int = 0
