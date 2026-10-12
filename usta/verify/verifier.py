"""Verifier (SPEC §9, ADR-018). Runs after the model stops calling tools, identical for both
engines: code checks first (each output file's skill check.py in the sandbox, then langcheck),
then one LLM check on the main role without tools. It judges; it never fixes."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from usta.core.messages import Message
from usta.core.model import ModelRequest, SystemBlock
from usta.core.run import RunState
from usta.core.verify import FileCheck, VerifyResult
from usta.core.workspace import RunDirs
from usta.lang import detect, langcheck
from usta.ports import ModelGateway, SandboxPort
from usta.skills import SkillSet

CHECKS = {".pdf": "pdf-report", ".xlsx": "xlsx", ".docx": "docx", ".png": "charts"}
LANG_CHECKED = {".pdf", ".docx"}  # prose; xlsx cells and charts are codes and labels
EXCERPT_CHARS = 1_500
CHECK_TIMEOUT_S = 60.0

VERIFIER_PROMPT = """\
You check whether an AI agent's final answer completes the user's task. You never fix anything.
You get the task, the agent's final answer, and the files it produced with text excerpts; those
files already passed automated format checks.
Fail only when the answer clearly does not do what was asked, contradicts the files, or claims
files or results that do not exist. Do not fail for style.
Reply with JSON only: {"verdict": "pass" | "fail", "reasons": ["one short English sentence", ...]}
"""
VERIFIER_VERSION = "verify-" + hashlib.sha256(VERIFIER_PROMPT.encode("utf-8")).hexdigest()[:12]


def _parse_verdict(text: str) -> tuple[bool, list[str]]:
    start, end = text.find("{"), text.rfind("}")
    data = None
    if start != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
        except ValueError:
            data = None
    if not isinstance(data, dict) or data.get("verdict") not in ("pass", "fail"):
        return False, [f"verifier reply was not JSON with a pass/fail verdict: {text[:200]!r}"]
    if data["verdict"] == "pass":
        return True, []
    raw = data.get("reasons")
    reasons = [str(r) for r in raw] if isinstance(raw, list) else []
    return False, reasons or ["the verifier failed the answer without giving a reason"]


class Verifier:
    def __init__(
        self,
        sandbox: SandboxPort,
        models: ModelGateway,
        workspace_root: Path,
        skills: SkillSet,
    ) -> None:
        self._sandbox = sandbox
        self._models = models
        self._root = workspace_root
        self._checks = {
            ext: name
            for ext, name in CHECKS.items()
            if (skill := skills.get(name)) is not None and (skill.dir / "check.py").is_file()
        }

    async def check(self, run: RunState) -> VerifyResult:
        dirs = RunDirs.of(self._root, run.user_id, run.id)
        task_lang = detect(run.task, min_words=1)  # short tasks: tr/None mostly mean az
        expected = task_lang if task_lang in ("en", "ru") else "az"
        outputs = self._outputs(dirs.out)
        files = [
            await self._check_file(run, dirs, rel, self._checks[Path(rel).suffix.lower()])
            for rel in outputs
            if Path(rel).suffix.lower() in self._checks
        ]
        reasons = [f"{f.path}: {r}" for f in files for r in f.reasons]
        answer = langcheck(run.final_text(), expected)
        if not answer.ok:
            reasons.append(f"final answer language: {answer.reason}")
        for f in files:
            if f.ok and Path(f.path).suffix.lower() in LANG_CHECKED:
                lc = langcheck(f.text_sample, expected)
                if not lc.ok:
                    reasons.append(f"{f.path}: language: {lc.reason}")
        if reasons:
            return VerifyResult(ok=False, reasons=tuple(reasons), files=tuple(files))
        resp = await self._models.complete(self._request(run, files, outputs))
        ok, llm_reasons = _parse_verdict(resp.message.text())
        return VerifyResult(
            ok=ok, reasons=tuple(llm_reasons), files=tuple(files), cost_usd=resp.cost_usd
        )

    @staticmethod
    def _outputs(out: Path) -> list[str]:
        if not out.is_dir():
            return []
        found = []
        for current, _, names in os.walk(out, followlinks=False):
            for name in names:
                p = Path(current) / name
                if p.is_symlink() or not p.is_file():
                    continue
                found.append(p.relative_to(out).as_posix())
        return sorted(found)

    async def _check_file(self, run: RunState, dirs: RunDirs, rel: str, skill: str) -> FileCheck:
        res = await self._sandbox.exec(
            run.id,
            dirs,
            ("python", f"/skills/{skill}/check.py", f"/out/{rel}"),
            timeout_s=CHECK_TIMEOUT_S,
        )
        path = f"out/{rel}"
        try:
            data = json.loads(res.stdout.strip().splitlines()[-1])
            ok = bool(data["ok"])
            reasons = tuple(str(r) for r in data.get("reasons") or ())
            sample = str(data.get("text_sample") or "")
        except (IndexError, ValueError, KeyError, TypeError, AttributeError):
            tail = (res.stderr or res.stdout).strip()[-300:]
            return FileCheck(
                path=path,
                skill=skill,
                ok=False,
                reasons=(f"{skill} check.py crashed (exit {res.exit_code}): {tail}",),
            )
        if not ok and not reasons:
            reasons = (f"{skill} check failed without a reason",)
        return FileCheck(
            path=path, skill=skill, ok=ok, reasons=() if ok else reasons, text_sample=sample
        )

    def _request(self, run: RunState, files: list[FileCheck], outputs: list[str]) -> ModelRequest:
        checked = {f.path for f in files}
        parts = [f"Task:\n{run.task}", f"Final answer:\n{run.final_text() or '(empty)'}"]
        if files:
            parts.append(
                "Checked files:\n"
                + "\n".join(
                    f"- {f.path} [{f.skill}]\n  excerpt: {f.text_sample[:EXCERPT_CHARS]}"
                    for f in files
                )
            )
        others = [f"out/{r}" for r in outputs if f"out/{r}" not in checked]
        parts.append("Other files in out/: " + (", ".join(others) if others else "none"))
        return ModelRequest(
            role="main",
            system=(SystemBlock(text=VERIFIER_PROMPT, cache=True),),
            messages=(Message.user_text("\n\n".join(parts)),),
            prompt_version=VERIFIER_VERSION,
            run_id=run.id,
            user_id=run.user_id,
        )
