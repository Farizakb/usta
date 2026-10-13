"""Verifier results (SPEC §9)."""

from usta.core.base import Frozen


class FileCheck(Frozen):
    path: str  # out/...
    skill: str
    ok: bool
    reasons: tuple[str, ...] = ()
    text_sample: str = ""


class VerifyResult(Frozen):
    ok: bool
    reasons: tuple[str, ...] = ()
    files: tuple[FileCheck, ...] = ()
    cost_usd: float = 0.0  # the LLM check's cost; the engine adds it to the run
