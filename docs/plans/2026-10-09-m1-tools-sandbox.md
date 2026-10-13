# M1 Tools + Sandbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Usta's M1 (SPEC §16): file tools with `az_casefold`, `code_exec` on gVisor with a pinned image and fonts, a skills loader with `pdf-report`, `xlsx`, `docx` and `charts` (each with `check.py`), the verifier, and `usta/lang`. M1 is done when a T-c-style task produces a correct xlsx and PDF that pass the checks, and the T3a sandbox-escape suite is 100% green.

**Architecture:**
- New ports: `SandboxPort` and `VerifierPort`.
- `usta.sandbox.docker.DockerSandbox` drives the `docker` CLI through asyncio subprocesses. There is one container per run, started lazily, with a fresh `python` process per call. gVisor (`runsc`) is used everywhere; plain runc is allowed only as `docker_hardened` in the `test` profile.
- `code_exec` is a tool built by a factory around the sandbox.
- Skills are repo folders with `SKILL.md`. Their helper scripts and `check.py` run inside the sandbox.
- The verifier is called by the engine when the model stops calling tools. It runs code checks first (`check.py` and `langcheck`), then one LLM check. On a fail it gives the model one retry with the reasons, then stops with `verification_failed`.
- The worker releases the run's container when the engine stream ends. `recover` reaps orphaned containers.

**Tech Stack:** Python 3.12, uv, Pydantic v2, jsonschema, Docker Engine + gVisor `runsc`, `lingua-language-detector` (new, host). The sandbox image adds pandas, openpyxl, matplotlib, reportlab, pdfplumber, python-docx and Babel. `openpyxl` is also a new dev-only host dependency, for fixtures and the T-c checker.

**Spec:** `SPEC.md` (v1.0): §7 Tools, §7.1 Skills, §9 Verifier, §10 Sandbox, §11.1 Workspace, §12 Azerbaijani, §15.1 T3a, §16 M1 row. ADRs: ADR-005, ADR-016, ADR-018, ADR-024, ADR-025, ADR-026, ADR-030, ADR-031. Executors read SPEC.md alongside this plan. The M0 plan (`docs/plans/2026-10-08-m0-foundations.md`) describes the code this builds on.

**Where to run:** WSL2 Ubuntu, `~/code/usta`, bash. Docker Engine has the runtimes `runsc` (ptrace) and `runsc-kvm` (kvm) registered (ADR-005). Sandbox tests use `USTA_TEST_SANDBOX_RUNTIME`, which defaults to `runsc`; locally, `export USTA_TEST_SANDBOX_RUNTIME=runsc-kvm` is about 10× faster.

## Global Constraints

- Everything in the M0 plan's Global Constraints still holds (P5 layering, P7, P8, LiteLLM isolation, UTF-8 without BOM, neutral naming, gitleaks).
- Sandbox (SPEC §10), verbatim: "`--runtime=runsc`, `--network=none` (P1), `--cap-drop=ALL`, `--security-opt=no-new-privileges`, non-root, read-only root fs, `tmpfs /tmp`, **no env vars passed**."
- "Limits per call: 60 s wall clock, 1 CPU, 1 GB RAM, 128 pids; stdout/stderr capped."
- "Mounts: `/workspace` = user's `files/` read-only; `/out` = `runs/{run_id}/out/` read-write; `/skills` read-only."
- "Lifecycle: one container per run, started at the first `code_exec`; each call is a fresh `python` process; state between calls only via files. Destroyed when the run parks or finishes; recreated on resume."
- "Image `usta-sandbox`: … pinned digest; scanned in CI; no runtime `pip install`."
- P8: "No fake, fallback or downgraded model or sandbox passes as real." `docker_hardened` (runc) only in `test`. A missing runtime or image refuses startup.
- Skills: "`skills/<name>/SKILL.md` (frontmatter `name`, `description`)"; "Only repo-versioned, reviewed skills."
- Verifier (SPEC §9): "Code checks first … LLM check only for what code can't judge … `pass | fail + reasons`; never fixes. `fail` → one retry with reasons appended. Second fail → `stop_reason=verification_failed`."
- `az_casefold()` (`İ→i`, `I→ı`), "unit-tested on pitfall words (`İSTİQAMƏT`, `IŞIQ`)". `langcheck` "Skips texts < ~15 words."
- New dependencies only as listed in this plan, each in its own commit, locked with `uv lock`.
- Do not edit `.env.example` (the user has an uncommitted change there). Do not read or print `.env`.

## Plan Decisions (from the 2026-10-09 grilling, Q1–Q10; all accepted)

1. **Docker CLI via `asyncio.create_subprocess_exec`** (Q1). No Docker SDK dependency. Code goes in through stdin to `docker exec -i … python -`. The gVisor runtime name comes from `USTA_GVISOR_RUNTIME` (default `runsc`; `runsc-kvm` in WSL2 dev). Startup refuses if Docker does not list that runtime, if its path is not `runsc`, or if the image is missing.
2. **Lifecycle** (Q2):
   - The container is named `usta-sbx-{run_id}` and labelled `usta.run={run_id}`.
   - The worker calls `sandbox.release(run_id)` when the engine stream ends. `recover` reaps labelled containers of runs that are not about to resume.
   - The inner limit is `timeout --kill-after=2 60` around the process. The outer limit is an asyncio timeout of 70 s, after which the container is destroyed; the next call recreates it.
   - The container runs as the host uid:gid, and `HOME` is `/tmp`.
3. **`code_exec`** (Q3):
   - Input is `{code}`, Python only.
   - Output is the exit code, stdout and stderr (each capped at 5,000 characters with a marker), and the files in `out/` that were created or changed.
   - A 200 MB cap on `out/` is checked after each call; exceeding it returns an error result.
   - Skill scripts are imported with `sys.path.insert(0, "/skills/<name>/scripts")`.
4. **T3a runs in CI on every push** in a second job (Q4). It installs a pinned, checksum-verified `runsc`, builds the image with the GitHub Actions layer cache, scans it with Trivy (critical findings with a fix fail the build), and runs `pytest -m sandbox`.
5. **Image** (Q5):
   - The base `python:3.12-slim` is pinned by digest.
   - Python packages are installed from a hash-locked `requirements.txt` (`--require-hashes`).
   - Fonts are DejaVu and Noto from Debian.
   - The tag is `usta-sandbox:1`. It is built locally and in CI and is not pushed to a registry before M5.
6. **The verifier is an engine hook** (Q6). `RunContext.verifier: VerifierPort | None`. The LLM check goes through the gateway on the `main` role with no tools, so it is audited, and its cost is added to `run.cost_usd`.
7. **`check.py` contract** (Q7):
   - Run as `python /skills/<skill>/check.py /out/<file>` inside the sandbox.
   - Prints exactly one JSON line, `{"ok": bool, "reasons": [str], "text_sample": str}`, and exits 0. Exit 2 means a usage error.
   - Checks that the file opens, that it has content, and glyph coverage (no base-14 PDF fonts, no `(cid:…)` or U+FFFD).
   - The host runs `langcheck` on the PDF and DOCX `text_sample`s and on the final answer.
   - "Totals match source" moves to the T2 checks (SPEC §7.1 is edited in Task 14).
8. **Dependencies** (Q8):
   - `lingua-language-detector` is added to the host, restricted to az/tr/en/ru at build time.
   - The SKILL.md frontmatter parser is our own and accepts only `name` and `description` (no PyYAML).
   - Babel lives only in the image.
   - `openpyxl` is added as a **dev** dependency, for fixtures and the T-c checker. The executor flags it for the user in the Task 13 report.
9. **Proof** (Q9): `fixtures/generate.py` (seed 20261009) writes `cihazlar.xlsx`, `anbar_qaliqlari.xlsx` (5 planted mismatches) and `ground_truth.json`. The live run uses `dev-openai` (`gpt-6-luna`). If luna cannot do it, there is one fallback run on `dev-api` (Claude), and the fallback is recorded.
10. **M1 skills** (Q10): `pdf-report`, `xlsx`, `docx`, `charts`. `company-glossary` and `email-reply-style` come later.
11. **Controller rulings (same session, not objected to):**
    - `file.search` matches a casefolded (`az_casefold`) substring over text files only, with at most 200 hits.
    - `file.write` writes UTF-8 text into `out/` only, creates parents, opens with `O_NOFOLLOW`, and may overwrite.
    - `file.read` keeps refusing non-UTF-8 files, but the error now says what to do instead.
    - The planning reminder (ADR-016) is appended on turn 2 when the todo list is empty and that turn called tools.
12. **Layering (P5).** import-linter layers become `cli → app → {engines, models, tools, store, worker, sandbox, verify} → {lang, skills} → ports → core`. A package joins the contract in the task that creates it, because import-linter fails on missing modules.
13. **`RunDirs` moves into core** (`usta/core/workspace.py`) so that the pipeline, the sandbox and the verifier compute `files/` and `out/` the same way.
14. **The language a run is checked against** is `detect(task, min_words=1)` when that is `en` or `ru`, and `"az"` otherwise. Short Azerbaijani tasks without `ə` are often detected as `tr`, and Usta's users write Azerbaijani, not Turkish. `detect` returns `"az"` whenever the text contains `ə` (the letter exists in none of tr/en/ru).

## Review Focus

These are the five failures most likely to hurt someone using this software that no spec bullet tests directly. Each has a test in the task that owns the code.

1. **A generated PDF shows boxes instead of `ə ğ ı ş İ`** because a built-in font was used. `check.py` must fail it, and the verifier must send the model back. Tests: Task 7 (`test_pdf_with_builtin_font_fails_check`), Task 9.
2. **Model-written code that hangs, floods output, fork-bombs or eats memory** must cost one error result. The run must continue and the next call must work. Tests: Task 4 (timeout, flood), Task 12 (fork bomb, memory bomb).
3. **Host secrets visible inside the sandbox** (API keys, `USTA_DATABASE_URL`). The container env must not contain them even when the host process does. Test: Task 12 (`test_host_secrets_never_reach_the_sandbox`).
4. **A symlink created in `/out` by sandbox code** must not let host-side file tools read or write outside the workspace. Tests: Task 2 (`file.write` refuses symlinks), Task 12 (`test_out_symlink_cannot_leak_host_files`).
5. **Verifier failures must be loud, never a silent pass.** An unparsable LLM verdict counts as a fail, and a crashed `check.py` counts as a failed file check. Tests: Task 9.

## File Map

```
usta/core/workspace.py            RunDirs (Task 2)
usta/core/sandbox.py              ExecResult (Task 4)
usta/core/verify.py               FileCheck, VerifyResult (Task 9)
usta/core/errors.py               + SandboxError (Task 4)
usta/core/run.py                  + verify_failures, todo_reminded, append_tool_results(note=) (Task 10)
usta/core/events.py               + "verification" (Task 10)
usta/ports/__init__.py            + SandboxPort (Task 4), VerifierPort (Task 9), RunContext fields (Tasks 6, 9)
usta/lang/__init__.py             az_casefold, detect, langcheck (Task 1)
usta/skills/__init__.py           Skill, SkillSet, parse_skill_md, load_skills (Task 6)
usta/sandbox/docker.py            DockerSandbox, SandboxConfig (Task 4)
usta/tools/builtin/files.py       + file.list, file.search, file.write; read fixes (Task 2)
usta/tools/builtin/code_exec.py   make_code_exec (Task 5)
usta/tools/builtin/skill_load.py  make_skill_load (Task 6)
usta/verify/verifier.py           Verifier (Task 9)
usta/engines/own/loop.py          skill index, verifier hook, planning reminder (Tasks 6, 10)
usta/engines/own/prompt.py        prompt lines, PLANNING_REMINDER, VERIFY_RETRY (Tasks 6, 10)
usta/worker.py                    sandbox release + reap (Task 10)
usta/app/{config,wiring}.py       sandbox, skills, verifier wiring + preflight (Task 11)
usta/cli.py                       "verification" event line (Task 10)
sandbox-image/                    Dockerfile, requirements.in, requirements.txt (Task 3)
scripts/build_sandbox_image.sh    (Task 3)
skills/{pdf-report,charts}/       SKILL.md, scripts/, check.py (Task 7)
skills/{xlsx,docx}/               SKILL.md, scripts/, check.py (Task 8)
fixtures/generate.py              T-c fixtures (Task 13)
evals/checks/tc.py                T-c deterministic checker (Task 13)
tests/conftest.py                 + sandbox fixtures (Task 4)
tests/fakes.py                    + FakeSandbox, FakeVerifier (Tasks 4, 10)
.github/workflows/ci.yml          + t3a job (Task 12)
```

---

### Task 1: `usta/lang`: `az_casefold`, `detect`, `langcheck`

**Files:**
- Modify: `pyproject.toml` (dependency + import-linter layer), `uv.lock`
- Create: `usta/lang/__init__.py`
- Test: `tests/lang/__init__.py`, `tests/lang/test_lang.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `az_casefold(text: str) -> str`
  - `detect(text: str, *, min_words: int = 15) -> str | None`, returning `"az" | "tr" | "en" | "ru"` or `None`
  - `langcheck(text: str, expected: str, *, detect_fn=detect) -> LangResult`
  - `LangResult(ok: bool, detected: str | None, reason: str | None)`, a frozen dataclass
  - `MIN_WORDS = 15`

- [ ] **Step 1: Add the dependency (its own commit)**

```bash
uv add 'lingua-language-detector>=2.1,<3'
uv run python -c "from lingua import Language, LanguageDetectorBuilder; d = LanguageDetectorBuilder.from_languages(Language.AZERBAIJANI, Language.TURKISH).build(); print(d.detect_language_of('Salam, necəsən? Bu gün hava çox gözəldir.'))"
```

Expected: prints `Language.AZERBAIJANI`. If the installed version is below 2.1 or the import path differs, stop and report it. Do not pick a different package.

```bash
uv run pytest -q --tb=short
git add pyproject.toml uv.lock
git commit -m "build: add lingua-language-detector for langcheck (SPEC §12, ADR-031)"
```

- [ ] **Step 2: Write the failing tests**

`tests/lang/__init__.py` is empty. `tests/lang/test_lang.py`:

```python
import pytest

from usta.lang import MIN_WORDS, LangResult, az_casefold, detect, langcheck

AZ = (
    "Keçən həftə şirkətimizin bütün avtomobilləri üçün yanacaq sərfiyyatı hesabatı hazırlandı "
    "və nəticələr iclasda müzakirə olunacaq, xüsusilə Bakı filialında artım müşahidə edildi."
)
TR = (
    "Geçen hafta şirketimizin bütün araçları için yakıt tüketimi raporu hazırlandı ve sonuçlar "
    "toplantıda tartışılacak, özellikle İstanbul şubesinde belirgin bir artış gözlendi."
)
EN = (
    "Last week the fuel consumption report for all of our company vehicles was prepared and the "
    "results will be discussed at the meeting, especially the increase seen in the Baku branch."
)
RU = (
    "На прошлой неделе был подготовлен отчёт о расходе топлива для всех автомобилей нашей "
    "компании, и результаты будут обсуждаться на совещании, особенно рост в бакинском филиале."
)


@pytest.mark.parametrize(
    ("text", "folded"),
    [
        ("İSTİQAMƏT", "istiqamət"),
        ("IŞIQ", "ışıq"),
        ("İstanbul", "istanbul"),
        ("Gəncə", "gəncə"),
        ("ÇÖÜĞ", "çöüğ"),
        ("ı", "ı"),
    ],
)
def test_az_casefold_pitfall_words(text: str, folded: str) -> None:
    assert az_casefold(text) == folded


def test_str_lower_is_wrong_and_az_casefold_is_not() -> None:
    assert "İSTİQAMƏT".lower() != "istiqamət"  # F5: Python inserts U+0307 and maps I→i
    assert az_casefold("IŞIQ") != "IŞIQ".lower()


@pytest.mark.parametrize(("text", "code"), [(AZ, "az"), (TR, "tr"), (EN, "en"), (RU, "ru")])
def test_detect_four_languages(text: str, code: str) -> None:
    assert len(text.split()) >= MIN_WORDS
    assert detect(text) == code


def test_detect_skips_short_text_unless_asked() -> None:
    assert detect("Hesabatı hazırla") is None
    assert detect("Hesabatı hazırla", min_words=1) == "az"  # ə rule


def test_schwa_means_azerbaijani() -> None:
    assert detect("ə " * 20) == "az"


def test_langcheck_pass_fail_and_skip() -> None:
    assert langcheck(AZ, "az") == LangResult(ok=True, detected="az", reason=None)
    bad = langcheck(TR, "az")
    assert not bad.ok and bad.detected == "tr" and "expected az" in (bad.reason or "")
    short = langcheck("Bəli.", "az")
    assert short.ok and short.detected is None and "skipped" in (short.reason or "")


def test_azerbaijani_without_schwa_is_suspicious() -> None:
    text = "bu gün biz ofisdə deyilik " * 4  # no ə would reach the detector in real drift
    result = langcheck(text.replace("ə", "e"), "az", detect_fn=lambda t, **_: "az")
    assert not result.ok and "without ə" in (result.reason or "")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/lang -q --tb=short`
Expected: FAIL with `ModuleNotFoundError: No module named 'usta.lang'`.

- [ ] **Step 4: Implement `usta/lang/__init__.py`**

```python
"""Azerbaijani text helpers (SPEC §12, ADR-031): casefolding and output-language checks."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache

from lingua import Language, LanguageDetector, LanguageDetectorBuilder

MIN_WORDS = 15  # below this, detection is too unreliable to act on (SPEC §12)

_CODES = {
    Language.AZERBAIJANI: "az",
    Language.TURKISH: "tr",
    Language.ENGLISH: "en",
    Language.RUSSIAN: "ru",
}
_UPPER_I = str.maketrans({"İ": "i", "I": "ı"})


def az_casefold(text: str) -> str:
    """Casefold for Azerbaijani: İ→i and I→ı before the generic casefold (F5)."""
    return unicodedata.normalize("NFC", text).translate(_UPPER_I).casefold()


@cache
def _detector() -> LanguageDetector:
    return LanguageDetectorBuilder.from_languages(*_CODES).build()


def detect(text: str, *, min_words: int = MIN_WORDS) -> str | None:
    """az / tr / en / ru, or None when the text is too short or undecidable."""
    if len(text.split()) < min_words:
        return None
    if "ə" in az_casefold(text):  # ə exists only in Azerbaijani among the four
        return "az"
    lang = _detector().detect_language_of(text)
    return _CODES.get(lang) if lang is not None else None


@dataclass(frozen=True)
class LangResult:
    ok: bool
    detected: str | None
    reason: str | None


def langcheck(
    text: str, expected: str, *, detect_fn: Callable[..., str | None] = detect
) -> LangResult:
    detected = detect_fn(text)
    if detected is None:
        return LangResult(True, None, f"skipped: fewer than {MIN_WORDS} words or undecidable")
    if detected != expected:
        return LangResult(False, detected, f"expected {expected}, detected {detected}")
    if expected == "az" and "ə" not in az_casefold(text):
        return LangResult(False, detected, "Azerbaijani text without ə (possible Turkish drift)")
    return LangResult(True, detected, None)
```

- [ ] **Step 5: Add `usta.lang` to the import-linter layers**

In `pyproject.toml`, replace the `layers = [...]` list of the first contract with:

```toml
layers = [
    "usta.cli",
    "usta.app",
    "usta.engines | usta.models | usta.tools | usta.store | usta.worker",
    "usta.lang",
    "usta.ports",
    "usta.core",
]
```

Also change the contract's `name` to `"Layers (P5): core <- ports <- libs <- adapters/engine/tools/store/worker <- app <- cli"`.

- [ ] **Step 6: Run the tests, lint and import contracts**

```bash
uv run pytest tests/lang -q --tb=short
uv run ruff format --check . && uv run ruff check . && uv run lint-imports
uv run pytest -q --tb=short
```

Expected: all pass (the 217 M0 tests plus the new ones). If `test_detect_four_languages` fails for one language, do not weaken the assertion. Report the detected value, because it is a real accuracy finding for T0.

- [ ] **Step 7: Commit**

```bash
git add usta/lang tests/lang pyproject.toml
git commit -m "feat(lang): az_casefold, detect and langcheck (SPEC §12)"
```

---

### Task 2: File tools `file.list`, `file.search`, `file.write`; `RunDirs`; `file.read` fixes

**Files:**
- Create: `usta/core/workspace.py`
- Modify: `usta/tools/builtin/files.py`, `usta/tools/builtin/__init__.py`, `usta/tools/pipeline.py` (`_context`)
- Test: `tests/core/test_workspace.py`, `tests/tools/test_files.py` (extend), `tests/tools/test_todo.py` (rename the builtin-list test)

**Interfaces:**
- Consumes: `az_casefold` (Task 1); M0's `ToolContext(run, files_dir, out_dir)`, `Tool`, `ToolOutput`, `ToolInputError`, `resolve`.
- Produces:
  - `RunDirs(files: Path, out: Path)`, a frozen dataclass with `RunDirs.of(root: Path, user_id: str, run_id: str) -> RunDirs`
  - `FILE_LIST`, `FILE_SEARCH`, `FILE_WRITE` (`Tool` objects)
  - `resolve(path, ctx, roots=("files", "out")) -> Path`
  - `builtin_tools()`, returning `[FILE_LIST, FILE_READ, FILE_SEARCH, FILE_WRITE, TODO]`
  - Constants `MAX_LIST = 500`, `MAX_HITS = 200`, `MAX_SEARCH_BYTES = 2_000_000`, `MAX_WRITE_CHARS = 1_000_000`

- [ ] **Step 1: Write the failing tests**

`tests/core/test_workspace.py`:

```python
from pathlib import Path

from usta.core.workspace import RunDirs


def test_run_dirs_layout() -> None:
    dirs = RunDirs.of(Path("/w"), "fariz", "r1")
    assert dirs.files == Path("/w/fariz/files")
    assert dirs.out == Path("/w/fariz/runs/r1/out")
```

Append to `tests/tools/test_files.py`. Merge these imports into the existing import block at the top of the file; the ones the file already has stay.

```python
from usta.tools.builtin.files import (
    FILE_LIST,
    FILE_SEARCH,
    FILE_WRITE,
    MAX_HITS,
)


async def test_list_shows_files_and_dirs_sorted(ctx: ToolContext) -> None:
    (ctx.files_dir / "b.txt").write_text("x", encoding="utf-8")
    (ctx.files_dir / "Ağ").mkdir()
    (ctx.files_dir / "Ağ" / "c.xlsx").write_bytes(b"12345")
    flat = (await FILE_LIST.fn({"path": "files"}, ctx)).content
    assert flat.splitlines() == ["files/Ağ/", "files/b.txt  (1 bytes)"]
    deep = (await FILE_LIST.fn({"path": "files", "recursive": True}, ctx)).content
    assert "files/Ağ/c.xlsx  (5 bytes)" in deep.splitlines()


async def test_list_of_missing_out_dir_is_empty(ctx: ToolContext) -> None:
    ctx.out_dir.rmdir()
    assert (await FILE_LIST.fn({"path": "out"}, ctx)).content == "(empty)"


async def test_search_is_azerbaijani_case_insensitive(ctx: ToolContext) -> None:
    (ctx.files_dir / "qeyd.txt").write_text("Birinci sətir\nİSTİQAMƏT: Gəncə\n", encoding="utf-8")
    (ctx.files_dir / "bin.dat").write_bytes(b"\x00\x01istiqamət")
    out = (await FILE_SEARCH.fn({"query": "istiqamət"}, ctx)).content
    assert "files/qeyd.txt:2: İSTİQAMƏT: Gəncə" in out
    assert "bin.dat" not in out.split("\n\n")[0]
    assert "1 skipped" in out


async def test_search_dotless_i_does_not_match_dotted(ctx: ToolContext) -> None:
    (ctx.files_dir / "a.txt").write_text("IŞIQ\n", encoding="utf-8")
    assert "a.txt:1" in (await FILE_SEARCH.fn({"query": "ışıq"}, ctx)).content
    assert "a.txt:1" not in (await FILE_SEARCH.fn({"query": "işiq"}, ctx)).content


async def test_search_caps_hits(ctx: ToolContext) -> None:
    (ctx.files_dir / "many.txt").write_text("söz\n" * (MAX_HITS + 50), encoding="utf-8")
    out = (await FILE_SEARCH.fn({"query": "söz"}, ctx)).content
    assert out.count("files/many.txt:") == MAX_HITS
    assert "[stopped at 200 matches]" in out


async def test_write_creates_utf8_file_in_out(ctx: ToolContext) -> None:
    res = await FILE_WRITE.fn({"path": "out/alt/hesabat.md", "content": "Gəncə ə"}, ctx)
    assert not res.is_error and "out/alt/hesabat.md" in res.content
    assert (ctx.out_dir / "alt" / "hesabat.md").read_bytes() == "Gəncə ə".encode()


async def test_write_refuses_files_dir(ctx: ToolContext) -> None:
    with pytest.raises(ToolInputError, match="out/"):
        await FILE_WRITE.fn({"path": "files/x.txt", "content": "x"}, ctx)


async def test_write_refuses_a_symlink_target(ctx: ToolContext, tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("host", encoding="utf-8")
    os.symlink(secret, ctx.out_dir / "link.txt")
    with pytest.raises(ToolInputError):
        await FILE_WRITE.fn({"path": "out/link.txt", "content": "pwned"}, ctx)
    assert secret.read_text(encoding="utf-8") == "host"


async def test_undecodable_file_error_suggests_code_exec(ctx: ToolContext) -> None:
    (ctx.files_dir / "cp.txt").write_bytes("Gəncə".encode("cp1254", errors="replace") + b"\xff\xfe\xfa")
    with pytest.raises(ToolInputError, match="code_exec"):
        await FILE_READ.fn({"path": "files/cp.txt"}, ctx)
```

In `tests/tools/test_todo.py`, replace `test_builtin_tools_are_file_read_and_todo` with:

```python
def test_builtin_tools() -> None:
    assert [t.name for t in builtin_tools()] == [
        "file.list",
        "file.read",
        "file.search",
        "file.write",
        "todo",
    ]
```

Keep whatever import of `builtin_tools` the old test used.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_workspace.py tests/tools -q --tb=short`
Expected: FAIL (ImportError for `usta.core.workspace` and `FILE_LIST`).

- [ ] **Step 3: Create `usta/core/workspace.py`**

```python
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
```

In `usta/tools/pipeline.py`, replace the body of `_context` with:

```python
    def _context(self, run: RunState) -> ToolContext:
        dirs = RunDirs.of(self._root, run.user_id, run.id)
        return ToolContext(run=run, files_dir=dirs.files, out_dir=dirs.out)
```

and add `from usta.core.workspace import RunDirs` to its imports.

- [ ] **Step 4: Rewrite `usta/tools/builtin/files.py`**

```python
"""File tools (SPEC §7): file.list, file.read, file.search over files/ and out/; file.write
into out/ only. Paths are 'files/...' or 'out/...'; nothing outside the user's workspace."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path, PurePosixPath
from typing import Any

from usta.core.errors import ToolInputError
from usta.lang import az_casefold
from usta.tools.registry import Tool, ToolContext, ToolOutput

MAX_CHARS = 50_000  # until layer-1 offload (M3) stores large results as files
MAX_LIST = 500
MAX_HITS = 200
MAX_SEARCH_BYTES = 2_000_000
MAX_WRITE_CHARS = 1_000_000
_LINE_CHARS = 200


def resolve(path: str, ctx: ToolContext, roots: tuple[str, ...] = ("files", "out")) -> Path:
    """Map 'files/...' or 'out/...' to a real path inside the user's workspace; refuse escapes."""
    if "\x00" in path:
        raise ToolInputError(f"path contains a NUL byte: {path!r}")
    rel = PurePosixPath(path)
    dirs = {"files": ctx.files_dir, "out": ctx.out_dir}
    if rel.is_absolute() or not rel.parts or rel.parts[0] not in roots:
        allowed = " or ".join(f"{r}/" for r in roots)
        raise ToolInputError(f"path must start with {allowed}: {path!r}")
    root = dirs[rel.parts[0]].resolve()
    target = root.joinpath(*rel.parts[1:]).resolve()  # resolves symlinks
    if not target.is_relative_to(root):
        raise ToolInputError(f"path escapes the workspace: {path!r}")
    return target


def _display(target: Path, ctx: ToolContext) -> str:
    for prefix, root in (("files", ctx.files_dir), ("out", ctx.out_dir)):
        root = root.resolve()
        if target == root:
            return prefix
        if target.is_relative_to(root):
            return f"{prefix}/{target.relative_to(root).as_posix()}"
    raise ToolInputError(f"path escapes the workspace: {target}")


def _read_nofollow(target: Path) -> bytes:
    """Open without following a symlink swapped in after resolve() (M0 TOCTOU limitation)."""
    try:
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as e:
        raise ToolInputError(f"cannot open {target.name!r}: {e.strerror}") from e
    with os.fdopen(fd, "rb") as f:
        return f.read()


def _decode(data: bytes, path: str) -> str:
    """UTF-8 (with or without BOM) or BOM-marked UTF-16. Anything else is refused: Postgres
    cannot store NUL in text/jsonb, and mojibake would mislead the model."""
    encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    hint = (
        f"binary or unsupported encoding: {path!r}. file.read reads UTF-8/UTF-16 text only; "
        "open Excel, Word, PDF or other encodings with code_exec (e.g. pandas, pdfplumber, "
        "or open(path, encoding='cp1254'))"
    )
    try:
        text = data.decode(encoding)
    except UnicodeDecodeError as e:
        raise ToolInputError(hint) from e
    if "\x00" in text:
        raise ToolInputError(hint)
    return text


async def _read(args: dict[str, Any], ctx: ToolContext) -> ToolOutput:
    target = resolve(args["path"], ctx)
    if not target.is_file():
        raise ToolInputError(f"not a file: {args['path']!r}")
    text = _decode(await asyncio.to_thread(_read_nofollow, target), args["path"])
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + f"\n[truncated: showing {MAX_CHARS} of {len(text)} characters]"
    return ToolOutput(text)


def _list(target: Path, ctx: ToolContext, recursive: bool) -> str:
    if not target.exists():
        return "(empty)"
    if not target.is_dir():
        raise ToolInputError(f"not a directory: {_display(target, ctx)}")
    lines: list[str] = []
    for current, dirnames, filenames in os.walk(target, followlinks=False):
        here = Path(current)
        dirnames.sort()
        for name in sorted([*dirnames, *filenames]):
            p = here / name  # `here` is under the resolved target; symlinks are not followed
            shown = _display(p, ctx)
            if name in dirnames:
                lines.append(f"{shown}/")
            else:
                lines.append(f"{shown}  ({p.lstat().st_size} bytes)")
        if not recursive:
            break
    lines.sort()
    if not lines:
        return "(empty)"
    if len(lines) > MAX_LIST:
        return "\n".join(lines[:MAX_LIST]) + f"\n[stopped at {MAX_LIST} entries]"
    return "\n".join(lines)


async def _list_tool(args: dict[str, Any], ctx: ToolContext) -> ToolOutput:
    path = args.get("path", "files")
    target = resolve(path, ctx)
    return ToolOutput(await asyncio.to_thread(_list, target, ctx, args.get("recursive", False)))


def _search(target: Path, ctx: ToolContext, query: str) -> str:
    needle = az_casefold(query)
    hits: list[str] = []
    scanned = skipped = 0
    files = [target] if target.is_file() else sorted(
        Path(d) / f for d, _, fs in os.walk(target, followlinks=False) for f in fs
    )
    for f in files:
        if f.is_symlink() or not f.is_file():
            continue
        if f.stat().st_size > MAX_SEARCH_BYTES:
            skipped += 1
            continue
        try:
            text = _decode(f.read_bytes(), f.name)
        except ToolInputError:
            skipped += 1
            continue
        scanned += 1
        shown = _display(f.resolve(), ctx)
        for n, line in enumerate(text.splitlines(), start=1):
            if needle in az_casefold(line):
                hits.append(f"{shown}:{n}: {line.strip()[:_LINE_CHARS]}")
                if len(hits) >= MAX_HITS:
                    return "\n".join(hits) + f"\n[stopped at {MAX_HITS} matches]"
    summary = f"{len(hits)} matches in {scanned} text files; {skipped} skipped (binary or too large)"
    return ("\n".join(hits) + "\n\n" + summary) if hits else summary


async def _search_tool(args: dict[str, Any], ctx: ToolContext) -> ToolOutput:
    target = resolve(args.get("path", "files"), ctx)
    if not target.exists():
        return ToolOutput("0 matches (path does not exist)")
    return ToolOutput(await asyncio.to_thread(_search, target, ctx, args["query"]))


def _write(target: Path, content: str) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8")
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    except OSError as e:
        raise ToolInputError(f"cannot write {target.name!r}: {e.strerror}") from e
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return len(data)


async def _write_tool(args: dict[str, Any], ctx: ToolContext) -> ToolOutput:
    path = args["path"]
    raw = ctx.out_dir / PurePosixPath(path).relative_to("out") if path.startswith("out/") else None
    if raw is not None and raw.is_symlink():
        raise ToolInputError(f"refusing to write through a symlink: {path!r}")
    target = resolve(path, ctx, roots=("out",))
    if target.is_dir():
        raise ToolInputError(f"is a directory: {path!r}")
    size = await asyncio.to_thread(_write, target, args["content"])
    return ToolOutput(f"wrote {_display(target, ctx)} ({size} bytes)")


_PATH_SCHEMA = {"type": "string", "description": "files, out, or a path under them"}

FILE_LIST = Tool(
    name="file.list",
    description="List files under files/ (the user's workspace) or out/ (this run's outputs).",
    input_schema={
        "type": "object",
        "properties": {
            "path": {**_PATH_SCHEMA, "default": "files"},
            "recursive": {"type": "boolean", "default": False},
        },
        "additionalProperties": False,
    },
    tier="read",
    fn=_list_tool,
)

FILE_READ = Tool(
    name="file.read",
    description=(
        "Read a UTF-8 text file. Paths start with files/ (the user's workspace files) "
        "or out/ (files produced in this run). For Excel, Word or PDF use code_exec."
    ),
    input_schema={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "e.g. files/notes.txt"}},
        "required": ["path"],
        "additionalProperties": False,
    },
    tier="read",
    fn=_read,
)

FILE_SEARCH = Tool(
    name="file.search",
    description=(
        "Find lines containing a text in UTF-8 text files under files/ or out/. "
        "Case-insensitive with Azerbaijani rules (İ/i, I/ı); plain text, not a regex."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1},
            "path": {**_PATH_SCHEMA, "default": "files"},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    tier="read",
    fn=_search_tool,
)

FILE_WRITE = Tool(
    name="file.write",
    description=(
        "Write a UTF-8 text file into out/ (this run's outputs), replacing it if it exists. "
        "For xlsx, docx, pdf or charts use code_exec with the matching skill."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "e.g. out/summary.md"},
            "content": {"type": "string", "maxLength": MAX_WRITE_CHARS},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    },
    tier="local",
    fn=_write_tool,
)
```

In `usta/tools/builtin/__init__.py`:

```python
from usta.tools.builtin.files import FILE_LIST, FILE_READ, FILE_SEARCH, FILE_WRITE
from usta.tools.builtin.todo import TODO
from usta.tools.registry import Tool


def builtin_tools() -> list[Tool]:
    """Tools that need nothing but the workspace. code_exec and skill.load are built in
    usta.app.wiring because they need the sandbox and the skill set."""
    return [FILE_LIST, FILE_READ, FILE_SEARCH, FILE_WRITE, TODO]
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/core tests/tools -q --tb=short`, then `uv run pytest -q --tb=short`.
Expected: all pass. The M0 test `test_undecodable_file_is_refused` keeps passing because the message still starts with `binary or unsupported encoding`. If `test_list_shows_files_and_dirs_sorted` disagrees on ordering, the expected order is plain Python `sorted()` on the displayed strings; fix the code, not the test.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff format . && uv run ruff check . && uv run lint-imports
git add usta/core/workspace.py usta/tools tests/core/test_workspace.py tests/tools
git commit -m "feat(tools): file.list, file.search (az_casefold), file.write; RunDirs; O_NOFOLLOW reads"
```

---

### Task 3: Sandbox image `usta-sandbox:1`

**Files:**
- Create: `sandbox-image/Dockerfile`, `sandbox-image/requirements.in`, `sandbox-image/requirements.txt` (generated), `scripts/build_sandbox_image.sh`
- Modify: `pyproject.toml` (pytest marker `sandbox`, addopts)
- Test: `tests/sandbox/__init__.py`, `tests/sandbox/test_image.py`

**Interfaces:**
- Produces:
  - the image `usta-sandbox:1`, running Python 3.12 with pandas, openpyxl, matplotlib, reportlab, pdfplumber, python-docx and babel;
  - fonts at `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf`, `/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf` and `/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf`;
  - `MPLCONFIGDIR=/tmp/matplotlib`, `HOME=/tmp`, workdir `/out`;
  - the pytest marker `sandbox`. Default `addopts` deselects it.

- [ ] **Step 1: Write `sandbox-image/requirements.in`**

```
# Sandbox image libraries (SPEC §10). Lock: see scripts/build_sandbox_image.sh header.
pandas
openpyxl
matplotlib
reportlab
pdfplumber
python-docx
babel
```

- [ ] **Step 2: Lock it with hashes**

```bash
uv pip compile sandbox-image/requirements.in --python-version 3.12 \
  --python-platform x86_64-manylinux_2_28 --generate-hashes \
  -o sandbox-image/requirements.txt
```

Expected: `requirements.txt` with `--hash=sha256:` lines for every package. If uv rejects the platform string, use `--python-platform linux` and record that in the report.

- [ ] **Step 3: Pin the base image digest**

```bash
docker pull python:3.12-slim
docker inspect --format '{{index .RepoDigests 0}}' python:3.12-slim
```

Copy the `sha256:…` digest into the `FROM` line below, in place of `<DIGEST>`. The committed Dockerfile must contain a real digest.

- [ ] **Step 4: Write `sandbox-image/Dockerfile`**

```dockerfile
# Usta sandbox image (SPEC §10, ADR-024). Built by scripts/build_sandbox_image.sh; no registry
# before M5. Runs with --network=none, read-only root, non-root uid, no env vars from the host.
FROM python:3.12-slim@sha256:<DIGEST>

RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-core fonts-noto-core \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes --only-binary=:all: -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt

# The root fs is read-only at run time; /tmp is a tmpfs that lives as long as the run's
# container, so matplotlib builds its font cache once per run there.
ENV HOME=/tmp MPLCONFIGDIR=/tmp/matplotlib PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_INDEX=1
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin sandbox
USER 10001
WORKDIR /out
CMD ["sleep", "infinity"]
```

If `--only-binary=:all:` fails because one package has no wheel, remove that flag and record which package in the report.

- [ ] **Step 5: Write `scripts/build_sandbox_image.sh`**

```bash
#!/usr/bin/env bash
# Build the sandbox image (SPEC §10). To change libraries: edit sandbox-image/requirements.in, then
#   uv pip compile sandbox-image/requirements.in --python-version 3.12 \
#     --python-platform x86_64-manylinux_2_28 --generate-hashes -o sandbox-image/requirements.txt
# To move the base image: update the FROM digest (docker inspect --format '{{index .RepoDigests 0}}').
set -euo pipefail
cd "$(dirname "$0")/.."
docker build -t usta-sandbox:1 sandbox-image
```

```bash
chmod +x scripts/build_sandbox_image.sh
scripts/build_sandbox_image.sh
```

Expected: the build succeeds and `docker image inspect usta-sandbox:1` exits 0.

- [ ] **Step 6: Register the pytest marker**

In `pyproject.toml` `[tool.pytest.ini_options]`, set:

```toml
addopts = "-m 'not live and not sandbox'"
markers = [
    "pg: needs Postgres (USTA_TEST_DATABASE_URL)",
    "live: calls a real model provider and spends quota; run with -m live",
    "sandbox: needs Docker, gVisor (USTA_TEST_SANDBOX_RUNTIME, default runsc) and the usta-sandbox:1 image; run with -m sandbox",
]
```

- [ ] **Step 7: Write the image test**

`tests/sandbox/__init__.py` is empty. `tests/sandbox/test_image.py`:

```python
"""The image has what skills need, and works under the hardening flags (SPEC §10)."""

import json
import os
import subprocess

import pytest

pytestmark = pytest.mark.sandbox

IMAGE = os.environ.get("USTA_TEST_SANDBOX_IMAGE", "usta-sandbox:1")
RUNTIME = os.environ.get("USTA_TEST_SANDBOX_RUNTIME", "runsc")

PROBE = """
import json, os, sys
import babel, docx, matplotlib, openpyxl, pandas, pdfplumber, reportlab
import matplotlib.font_manager as fm
fonts = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
]
print(json.dumps({
    "python": sys.version_info[:2],
    "fonts": [os.path.exists(f) for f in fonts],
    "mpl_font": os.path.basename(fm.findfont("DejaVu Sans")),
    "uid": os.getuid(),
}))
"""


def test_image_has_python_libraries_and_fonts() -> None:
    proc = subprocess.run(
        [
            "docker", "run", "--rm", "--runtime", RUNTIME, "--network", "none",
            "--read-only", "--tmpfs", "/tmp", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--user", f"{os.getuid()}:{os.getgid()}",
            "-i", IMAGE, "python", "-",
        ],
        input=PROBE, capture_output=True, text=True, timeout=120, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    info = json.loads(proc.stdout.strip().splitlines()[-1])
    assert info["python"] == [3, 12]
    assert info["fonts"] == [True, True, True]
    assert info["mpl_font"] == "DejaVuSans.ttf"
    assert info["uid"] == os.getuid() != 0
```

- [ ] **Step 8: Run it**

```bash
uv run pytest -m sandbox tests/sandbox/test_image.py -q --tb=short
uv run pytest -q --tb=short
```

Expected: the sandbox test passes and the default run is unchanged (the sandbox test is deselected).

- [ ] **Step 9: Commit**

```bash
uv run ruff format . && uv run ruff check .
git add sandbox-image scripts/build_sandbox_image.sh pyproject.toml tests/sandbox
git commit -m "feat(sandbox): pinned usta-sandbox:1 image with skills libraries and DejaVu/Noto fonts"
```

---

### Task 4: `SandboxPort` and `DockerSandbox`

**Files:**
- Create: `usta/core/sandbox.py`, `usta/sandbox/__init__.py`, `usta/sandbox/docker.py`
- Modify: `usta/core/errors.py` (+ `SandboxError`), `usta/ports/__init__.py` (+ `SandboxPort`), `pyproject.toml` (import-linter layer), `tests/conftest.py` (sandbox fixtures), `tests/fakes.py` (+ `FakeSandbox`)
- Test: `tests/sandbox/test_docker_args.py` (no Docker), `tests/sandbox/test_docker_sandbox.py` (marker `sandbox`)

**Interfaces:**
- Consumes: `RunDirs` (Task 2), `Frozen`, `UstaError`.
- Produces:
  - `ExecResult(exit_code: int, stdout: str, stderr: str, timed_out: bool = False, truncated: bool = False, duration_ms: int = 0)` (`Frozen`)
  - `SandboxError(UstaError)`
  - `SandboxPort` Protocol:
    - `async exec(run_id: str, dirs: RunDirs, argv: Sequence[str], *, stdin: str = "", timeout_s: float = 60.0) -> ExecResult`
    - `async release(run_id: str) -> None`
    - `async reap(keep: Collection[str]) -> list[str]`
  - `SandboxConfig(image: str, runtime: str, gvisor: bool, skills_dir: Path, uid: int, gid: int, cpus: str = "1", memory: str = "1g", pids: int = 128, tmp_size: str = "256m")`
  - `DockerSandbox(cfg, *, docker: str = "docker")`, with `run_args(run_id, dirs) -> list[str]`, `exec`, `release`, `reap`, and `async preflight() -> list[str]` (problems; empty means OK)
  - `container_name(run_id) -> str` (`"usta-sbx-" + run_id`), `LABEL = "usta.run"`, `OUTPUT_CAP_BYTES = 256_000`, `OUTER_GRACE_S = 10.0`
  - `tests/fakes.FakeSandbox(handler=None)`, with `.calls: list[tuple[str, tuple[str, ...], str]]` and `.released: list[str]`
  - `tests/conftest.py` fixtures `sandbox_config` and `box`; `box` yields a `Box(sandbox, run_id, dirs)` with `async run(code, timeout_s=60.0) -> ExecResult`

- [ ] **Step 1: Add the core and port types**

`usta/core/sandbox.py`:

```python
"""Result of one sandboxed process (SPEC §10)."""

from usta.core.base import Frozen


class ExecResult(Frozen):
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    truncated: bool = False  # a stream went over the sandbox's byte cap and was cut
    duration_ms: int = 0
```

Append to `usta/core/errors.py`:

```python
class SandboxError(UstaError):
    """Docker or the sandbox runtime failed (not the user's code)."""
```

In `usta/ports/__init__.py`, add these imports:

```python
from collections.abc import AsyncIterator, Collection, Sequence

from usta.core.sandbox import ExecResult
from usta.core.workspace import RunDirs
```

and this Protocol, after `ToolPipelinePort`:

```python
class SandboxPort(Protocol):
    """One container per run, a fresh process per exec (SPEC §10, ADR-024)."""

    async def exec(
        self,
        run_id: str,
        dirs: RunDirs,
        argv: Sequence[str],
        *,
        stdin: str = "",
        timeout_s: float = 60.0,
    ) -> ExecResult: ...

    async def release(self, run_id: str) -> None: ...

    async def reap(self, keep: Collection[str]) -> list[str]: ...
```

- [ ] **Step 2: Write the failing argument tests (no Docker needed)**

`tests/sandbox/test_docker_args.py`:

```python
from pathlib import Path

import pytest

from usta.core.errors import SandboxError
from usta.core.workspace import RunDirs
from usta.sandbox.docker import LABEL, DockerSandbox, SandboxConfig, container_name

CFG = SandboxConfig(
    image="usta-sandbox:1", runtime="runsc", gvisor=True, skills_dir=Path("/repo/skills"),
    uid=1000, gid=1000,
)
DIRS = RunDirs(files=Path("/w/u/files"), out=Path("/w/u/runs/r1/out"))


def test_run_args_carry_every_hardening_flag() -> None:
    args = DockerSandbox(CFG).run_args("r1", DIRS)
    joined = " ".join(args)
    for flag in (
        "--runtime runsc", "--network none", "--cap-drop ALL",
        "--security-opt no-new-privileges", "--read-only", "--user 1000:1000",
        "--cpus 1", "--memory 1g", "--memory-swap 1g", "--pids-limit 128",
        f"--label {LABEL}=r1", f"--name {container_name('r1')}",
    ):
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
```

Run: `uv run pytest tests/sandbox/test_docker_args.py -q --tb=short`
Expected: FAIL (`No module named 'usta.sandbox'`).

- [ ] **Step 3: Implement `usta/sandbox/docker.py`**

`usta/sandbox/__init__.py` is empty.

```python
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
        stderr = _text(err)
        if code != 0 and stderr.startswith("Error response from daemon"):
            log.warning("sandbox %s: %s", run_id, stderr.strip())
            return None
        return ExecResult(
            exit_code=code,
            stdout=_text(out),
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
```

- [ ] **Step 4: Add `usta.sandbox` to the import-linter layers**

Change the adapter layer line to:

```toml
    "usta.engines | usta.models | usta.tools | usta.store | usta.worker | usta.sandbox",
```

- [ ] **Step 5: Add the test fixtures and `FakeSandbox`**

Append to `tests/fakes.py`. Merge the imports into the file's import block.

```python
from collections.abc import Callable, Collection, Sequence

from usta.core.sandbox import ExecResult
from usta.core.workspace import RunDirs

ExecHandler = Callable[[str, RunDirs, tuple[str, ...], str], ExecResult]


class FakeSandbox:
    """SandboxPort for unit tests (P8: never wired outside the test profile)."""

    def __init__(self, handler: ExecHandler | None = None) -> None:
        self.calls: list[tuple[str, tuple[str, ...], str]] = []
        self.released: list[str] = []
        self.reaped_keep: list[set[str]] = []
        self._handler = handler or (lambda *_: ExecResult(exit_code=0, stdout="", stderr=""))

    async def exec(
        self,
        run_id: str,
        dirs: RunDirs,
        argv: Sequence[str],
        *,
        stdin: str = "",
        timeout_s: float = 60.0,
    ) -> ExecResult:
        self.calls.append((run_id, tuple(argv), stdin))
        return self._handler(run_id, dirs, tuple(argv), stdin)

    async def release(self, run_id: str) -> None:
        self.released.append(run_id)

    async def reap(self, keep: Collection[str]) -> list[str]:
        self.reaped_keep.append(set(keep))
        return []
```

Append to `tests/conftest.py`. Merge the imports.

```python
import uuid
from dataclasses import dataclass
from pathlib import Path

from usta.core.sandbox import ExecResult
from usta.core.workspace import RunDirs
from usta.sandbox.docker import DockerSandbox, SandboxConfig

SANDBOX_IMAGE = os.environ.get("USTA_TEST_SANDBOX_IMAGE", "usta-sandbox:1")
SANDBOX_RUNTIME = os.environ.get("USTA_TEST_SANDBOX_RUNTIME", "runsc")


@pytest.fixture
def sandbox_config(tmp_path: Path) -> SandboxConfig:
    skills = Path("skills").resolve()
    if not skills.is_dir():
        skills = tmp_path / "skills"
        skills.mkdir()
    return SandboxConfig(
        image=SANDBOX_IMAGE,
        runtime=SANDBOX_RUNTIME,
        gvisor=SANDBOX_RUNTIME != "runc",
        skills_dir=skills,
        uid=os.getuid(),
        gid=os.getgid(),
    )


@dataclass
class Box:
    sandbox: DockerSandbox
    run_id: str
    dirs: RunDirs

    async def run(self, code: str, timeout_s: float = 60.0) -> ExecResult:
        return await self.sandbox.exec(
            self.run_id, self.dirs, ("python", "-"), stdin=code, timeout_s=timeout_s
        )


@pytest.fixture
async def box(tmp_path: Path, sandbox_config: SandboxConfig):
    dirs = RunDirs(files=tmp_path / "files", out=tmp_path / "out")
    dirs.files.mkdir()
    dirs.out.mkdir()
    b = Box(DockerSandbox(sandbox_config), f"t-{uuid.uuid4().hex[:12]}", dirs)
    yield b
    await b.sandbox.release(b.run_id)
```

- [ ] **Step 6: Write the real-sandbox tests**

`tests/sandbox/test_docker_sandbox.py`:

```python
import subprocess

import pytest

from tests.conftest import SANDBOX_RUNTIME, Box
from usta.sandbox.docker import OUTPUT_CAP_BYTES, DockerSandbox, container_name

pytestmark = pytest.mark.sandbox


async def test_hello_and_azerbaijani_round_trip(box: Box) -> None:
    res = await box.run("print('Salam, Gəncə! İŞIQ ə')")
    assert res.exit_code == 0 and res.stdout == "Salam, Gəncə! İŞIQ ə\n"
    runtime = subprocess.run(
        ["docker", "inspect", "-f", "{{.HostConfig.Runtime}}", container_name(box.run_id)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
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
    res = await box.run("print('ə' * 3_000_000)")
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
    from dataclasses import replace

    assert await DockerSandbox(sandbox_config).preflight() == []
    problems = await DockerSandbox(
        replace(sandbox_config, image="usta-sandbox:does-not-exist", runtime="no-such-rt")
    ).preflight()
    assert any("no runtime 'no-such-rt'" in p for p in problems)
    assert any("not found" in p for p in problems)


async def test_preflight_refuses_runc_posing_as_gvisor(sandbox_config) -> None:
    from dataclasses import replace

    problems = await DockerSandbox(replace(sandbox_config, runtime="runc", gvisor=True)).preflight()
    assert any("not gVisor" in p for p in problems)
```

- [ ] **Step 7: Run everything**

```bash
uv run pytest tests/sandbox/test_docker_args.py -q --tb=short
uv run pytest -m sandbox tests/sandbox -q --tb=short
uv run ruff format . && uv run ruff check . && uv run lint-imports
uv run pytest -q --tb=short
```

Expected: all pass. If the `"Error response from daemon"` heuristic misfires in `test_release_removes_and_next_exec_recreates`, report the exact stderr Docker printed; do not widen the match blindly.

- [ ] **Step 8: Commit**

```bash
git add usta/core/sandbox.py usta/core/errors.py usta/ports/__init__.py usta/sandbox \
  tests/conftest.py tests/fakes.py tests/sandbox pyproject.toml
git commit -m "feat(sandbox): SandboxPort and DockerSandbox (gVisor, one container per run)"
```

---

### Task 5: `code_exec` tool

**Files:**
- Create: `usta/tools/builtin/code_exec.py`
- Test: `tests/tools/test_code_exec.py`

**Interfaces:**
- Consumes: `SandboxPort`, `ExecResult`, `RunDirs`, `FakeSandbox`, and the `box` fixture (Task 4).
- Produces:
  - `make_code_exec(sandbox: SandboxPort) -> Tool`, with name `code_exec` and tier `local`
  - Constants `STREAM_CHARS = 5_000`, `OUT_DIR_CAP_BYTES = 200 * 1024 * 1024`, `TIMEOUT_S = 60.0`

- [ ] **Step 1: Write the failing tests**

`tests/tools/test_code_exec.py`:

```python
from pathlib import Path

import pytest

from tests.conftest import Box
from tests.fakes import FakeSandbox
from usta.core.run import RunState
from usta.core.sandbox import ExecResult
from usta.tools.builtin import code_exec as ce
from usta.tools.builtin.code_exec import STREAM_CHARS, make_code_exec
from usta.tools.registry import ToolContext


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    files = tmp_path / "u1" / "files"
    out = tmp_path / "u1" / "runs" / "r1" / "out"
    files.mkdir(parents=True)
    out.mkdir(parents=True)
    run = RunState.new(id="r1", user_id="u1", task="t", engine="own", cost_cap_usd=0.5)
    return ToolContext(run=run, files_dir=files, out_dir=out)


async def test_passes_code_on_stdin_and_renders_output(ctx: ToolContext) -> None:
    sb = FakeSandbox(lambda *_: ExecResult(exit_code=0, stdout="Salam\n", stderr=""))
    res = await make_code_exec(sb).fn({"code": "print('Salam')"}, ctx)
    assert sb.calls == [("r1", ("python", "-"), "print('Salam')")]
    assert not res.is_error
    assert res.content.startswith("exit_code: 0\n")
    assert "stdout:\nSalam" in res.content


async def test_nonzero_exit_is_an_error(ctx: ToolContext) -> None:
    sb = FakeSandbox(lambda *_: ExecResult(exit_code=1, stdout="", stderr="Traceback ... ZeroDivisionError"))
    res = await make_code_exec(sb).fn({"code": "1/0"}, ctx)
    assert res.is_error and "ZeroDivisionError" in res.content


async def test_timeout_is_explained(ctx: ToolContext) -> None:
    sb = FakeSandbox(lambda *_: ExecResult(exit_code=124, stdout="", stderr="", timed_out=True))
    res = await make_code_exec(sb).fn({"code": "while True: pass"}, ctx)
    assert res.is_error and "timed out after 60 s" in res.content


async def test_lists_created_and_changed_files(ctx: ToolContext) -> None:
    (ctx.out_dir / "old.txt").write_text("same", encoding="utf-8")

    def handler(run_id, dirs, argv, stdin):
        (dirs.out / "hesabat.pdf").write_bytes(b"%PDF-1.4 x")
        return ExecResult(exit_code=0, stdout="", stderr="")

    res = await make_code_exec(FakeSandbox(handler)).fn({"code": "..."}, ctx)
    assert "files changed in out/:\n- out/hesabat.pdf (10 bytes)" in res.content
    assert "old.txt" not in res.content


async def test_long_streams_are_cut_with_a_marker(ctx: ToolContext) -> None:
    sb = FakeSandbox(lambda *_: ExecResult(exit_code=0, stdout="ə" * (STREAM_CHARS + 10), stderr="", truncated=True))
    res = await make_code_exec(sb).fn({"code": "..."}, ctx)
    assert f"[truncated: {STREAM_CHARS} of {STREAM_CHARS + 10} characters shown]" in res.content
    assert "[output over the sandbox limit was cut]" in res.content


async def test_out_dir_over_cap_is_an_error(ctx: ToolContext, monkeypatch) -> None:
    monkeypatch.setattr(ce, "OUT_DIR_CAP_BYTES", 5)

    def handler(run_id, dirs, argv, stdin):
        (dirs.out / "big.bin").write_bytes(b"123456")
        return ExecResult(exit_code=0, stdout="", stderr="")

    res = await make_code_exec(FakeSandbox(handler)).fn({"code": "..."}, ctx)
    assert res.is_error and "over the 5-byte limit" in res.content


@pytest.mark.sandbox
async def test_real_sandbox_writes_a_file_the_host_sees(box: Box) -> None:
    run = RunState.new(id=box.run_id, user_id="u1", task="t", engine="own", cost_cap_usd=0.5)
    ctx = ToolContext(run=run, files_dir=box.dirs.files, out_dir=box.dirs.out)
    res = await make_code_exec(box.sandbox).fn(
        {"code": "open('/out/qeyd.txt', 'w', encoding='utf-8').write('ə')"}, ctx
    )
    assert not res.is_error, res.content
    assert (box.dirs.out / "qeyd.txt").read_text(encoding="utf-8") == "ə"
    assert "out/qeyd.txt (2 bytes)" in res.content
```

Run: `uv run pytest tests/tools/test_code_exec.py -q --tb=short`
Expected: FAIL (`No module named 'usta.tools.builtin.code_exec'`).

- [ ] **Step 2: Implement `usta/tools/builtin/code_exec.py`**

```python
"""code_exec: run Python in the run's gVisor sandbox (SPEC §7, §10)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from usta.core.sandbox import ExecResult
from usta.core.workspace import RunDirs
from usta.ports import SandboxPort
from usta.tools.registry import Tool, ToolContext, ToolOutput

STREAM_CHARS = 5_000  # per stream; layer-1 offload (M3) will keep the rest as a file
OUT_DIR_CAP_BYTES = 200 * 1024 * 1024
TIMEOUT_S = 60.0

DESCRIPTION = """\
Run Python 3.12 code in an isolated sandbox with no network access.
- /workspace is the user's files/ folder (read-only); /out is this run's out/ folder (read-write).
  So files/x.xlsx in file tools is /workspace/x.xlsx here, and out/y.pdf is /out/y.pdf.
- /skills holds skill scripts (read-only); load the skill with skill.load first.
- Each call is a fresh process: keep state in files under /out, not in variables.
- Installed: pandas, openpyxl, matplotlib, reportlab, pdfplumber, python-docx, babel. No pip install.
- 60 s per call. print() what you need to see; each output stream is cut at 5,000 characters."""

Snapshot = dict[str, tuple[int, int]]


def _snapshot(out_dir: Path) -> Snapshot:
    snap: Snapshot = {}
    if not out_dir.is_dir():
        return snap
    for current, _, files in os.walk(out_dir, followlinks=False):
        for name in files:
            p = Path(current) / name
            st = p.lstat()
            snap["out/" + p.relative_to(out_dir).as_posix()] = (st.st_size, st.st_mtime_ns)
    return snap


def _cut(text: str) -> str:
    if len(text) <= STREAM_CHARS:
        return text
    return text[:STREAM_CHARS] + f"\n[truncated: {STREAM_CHARS} of {len(text)} characters shown]"


def _render(res: ExecResult, changed: list[str], after: Snapshot) -> str:
    head = (
        f"timed out after {TIMEOUT_S:.0f} s (process killed)"
        if res.timed_out
        else f"exit_code: {res.exit_code}"
    )
    parts = [head]
    if res.stdout:
        parts.append("stdout:\n" + _cut(res.stdout))
    if res.stderr:
        parts.append("stderr:\n" + _cut(res.stderr))
    if res.truncated:
        parts.append("[output over the sandbox limit was cut]")
    if changed:
        parts.append(
            "files changed in out/:\n" + "\n".join(f"- {p} ({after[p][0]} bytes)" for p in changed)
        )
    return "\n".join(parts)


def make_code_exec(sandbox: SandboxPort) -> Tool:
    async def run(args: dict[str, Any], ctx: ToolContext) -> ToolOutput:
        before = await asyncio.to_thread(_snapshot, ctx.out_dir)
        res = await sandbox.exec(
            ctx.run.id,
            RunDirs(files=ctx.files_dir, out=ctx.out_dir),
            ("python", "-"),
            stdin=args["code"],
            timeout_s=TIMEOUT_S,
        )
        after = await asyncio.to_thread(_snapshot, ctx.out_dir)
        changed = sorted(p for p, st in after.items() if before.get(p) != st)
        text = _render(res, changed, after)
        total = sum(size for size, _ in after.values())
        if total > OUT_DIR_CAP_BYTES:
            return ToolOutput(
                text + f"\nERROR: out/ holds {total} bytes, over the {OUT_DIR_CAP_BYTES}-byte "
                "limit; delete files you do not need before continuing.",
                is_error=True,
            )
        return ToolOutput(text, is_error=res.timed_out or res.exit_code != 0)

    return Tool(
        name="code_exec",
        description=DESCRIPTION,
        input_schema={
            "type": "object",
            "properties": {"code": {"type": "string", "minLength": 1, "maxLength": 100_000}},
            "required": ["code"],
            "additionalProperties": False,
        },
        tier="local",
        fn=run,
    )
```

- [ ] **Step 3: Run the tests**

```bash
uv run pytest tests/tools/test_code_exec.py -q --tb=short
uv run pytest -m sandbox tests/tools/test_code_exec.py -q --tb=short
uv run ruff format . && uv run ruff check . && uv run lint-imports && uv run pytest -q --tb=short
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add usta/tools/builtin/code_exec.py tests/tools/test_code_exec.py
git commit -m "feat(tools): code_exec on the run's sandbox with output caps and out/ change list"
```

---
### Task 6: Skills loader, `skill.load`, skill index in the cached prefix

**Files:**
- Create: `usta/skills/__init__.py`, `usta/tools/builtin/skill_load.py`
- Modify: `usta/ports/__init__.py` (`RunContext.skill_index`), `usta/engines/own/loop.py` (`build_request`), `usta/engines/own/prompt.py` (prompt lines), `pyproject.toml` (layer)
- Test: `tests/skills/__init__.py`, `tests/skills/test_loader.py`, `tests/engines/test_own_loop.py` (append)

**Interfaces:**
- Consumes: `ConfigError`, `Tool`, `ToolOutput`, `RunContext`.
- Produces:
  - `Skill(name: str, description: str, body: str, dir: Path)`, a frozen dataclass
  - `SkillSet(skills)`, with `.get(name) -> Skill | None`, `.names() -> list[str]` (sorted) and `.index_text() -> str` (`""` when empty)
  - `parse_skill_md(text: str, source: str) -> tuple[dict[str, str], str]`
  - `load_skills(root: Path) -> SkillSet` (a missing root gives an empty set)
  - `make_skill_load(skills: SkillSet) -> Tool`, with name `skill.load` and tier `local`
  - `RunContext.skill_index: str = ""`
  - `build_request(run, tools, skill_index: str = "") -> ModelRequest`

- [ ] **Step 1: Write the failing tests**

`tests/skills/__init__.py` is empty. `tests/skills/test_loader.py`:

```python
from pathlib import Path

import pytest

from usta.core.errors import ConfigError
from usta.core.run import RunState
from usta.skills import load_skills, parse_skill_md
from usta.tools.builtin.skill_load import make_skill_load
from usta.tools.registry import ToolContext

GOOD = """---
name: pdf-report
description: Build PDF reports with Azerbaijani-safe fonts.
---
# pdf-report

Use usta_pdf.build_pdf.
"""


def write_skill(root: Path, name: str, text: str) -> None:
    (root / name).mkdir(parents=True)
    (root / name / "SKILL.md").write_text(text, encoding="utf-8")


def test_parse_frontmatter_and_body() -> None:
    meta, body = parse_skill_md(GOOD, "x")
    assert meta == {"name": "pdf-report", "description": "Build PDF reports with Azerbaijani-safe fonts."}
    assert body.startswith("# pdf-report") and "build_pdf" in body


def test_quoted_values_are_unquoted() -> None:
    meta, _ = parse_skill_md('---\nname: "xlsx"\ndescription: \'Excel: tables\'\n---\nb', "x")
    assert meta == {"name": "xlsx", "description": "Excel: tables"}


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("no frontmatter", "must start with ---"),
        ("---\nname: a\n", "closing ---"),
        ("---\nname: a\n---\nbody", "description"),
        ("---\nname: a\ndescription: d\nlicense: MIT\n---\nb", "unsupported key 'license'"),
        ("---\nname: a\ndescription: d\n  more\n---\nb", "key: value"),
    ],
)
def test_bad_frontmatter_is_refused(text: str, error: str) -> None:
    with pytest.raises(ConfigError, match=error):
        parse_skill_md(text, "skills/a/SKILL.md")


def test_load_skills_sorted_index_and_name_must_match_dir(tmp_path: Path) -> None:
    write_skill(tmp_path, "pdf-report", GOOD)
    write_skill(tmp_path, "charts", "---\nname: charts\ndescription: Charts as PNG.\n---\nbody")
    (tmp_path / "_shared").mkdir()  # ignored: leading underscore
    skills = load_skills(tmp_path)
    assert skills.names() == ["charts", "pdf-report"]
    assert skills.index_text().splitlines()[1:] == [
        "- charts: Charts as PNG.",
        "- pdf-report: Build PDF reports with Azerbaijani-safe fonts.",
    ]
    write_skill(tmp_path, "docx", GOOD)  # says name: pdf-report
    with pytest.raises(ConfigError, match="does not match its folder"):
        load_skills(tmp_path)


def test_folder_without_skill_md_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "xlsx").mkdir()
    with pytest.raises(ConfigError, match="SKILL.md"):
        load_skills(tmp_path)


def test_missing_root_is_empty(tmp_path: Path) -> None:
    skills = load_skills(tmp_path / "nope")
    assert skills.names() == [] and skills.index_text() == ""


async def test_skill_load_returns_body(tmp_path: Path) -> None:
    write_skill(tmp_path, "pdf-report", GOOD)
    tool = make_skill_load(load_skills(tmp_path))
    assert tool.name == "skill.load"
    assert tool.input_schema["properties"]["name"]["enum"] == ["pdf-report"]
    run = RunState.new(id="r1", user_id="u1", task="t", engine="own", cost_cap_usd=0.5)
    ctx = ToolContext(run=run, files_dir=tmp_path, out_dir=tmp_path)
    out = await tool.fn({"name": "pdf-report"}, ctx)
    assert "build_pdf" in out.content and "/skills/pdf-report/" in out.content
```

Append to `tests/engines/test_own_loop.py`:

```python
from usta.engines.own.loop import build_request


def test_skill_index_is_a_second_cached_system_block() -> None:
    run = RunState.new(id="r1", user_id="u1", task="t", engine="own", cost_cap_usd=0.5)
    plain = build_request(run, ())
    assert len(plain.system) == 1 and plain.system[0].cache
    with_index = build_request(run, (), skill_index="Skills:\n- charts: PNG charts")
    assert [b.cache for b in with_index.system] == [False, True]
    assert with_index.system[1].text.startswith("Skills:")
    assert with_index.prompt_version.startswith(PROMPT_VERSION + "+sk-")
    assert with_index.prompt_version == build_request(run, (), skill_index="Skills:\n- charts: PNG charts").prompt_version
```

Run: `uv run pytest tests/skills tests/engines -q --tb=short`
Expected: FAIL (`No module named 'usta.skills'`).

- [ ] **Step 2: Implement `usta/skills/__init__.py`**

```python
"""Skills (SPEC §7.1, ADR-026): skills/<name>/SKILL.md with `name` and `description`
frontmatter, scripts/ and an optional check.py. Only repo-versioned skills; the frontmatter
parser accepts exactly those two keys (no PyYAML, M1 Plan Decision 8)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from usta.core.errors import ConfigError

_NAME = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_KEYS = ("name", "description")


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    dir: Path


class SkillSet:
    def __init__(self, skills: Iterable[Skill] = ()) -> None:
        self._skills = {s.name: s for s in skills}

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def names(self) -> list[str]:
        return sorted(self._skills)

    def index_text(self) -> str:
        """Names and descriptions for the cached prefix; bodies load via skill.load."""
        if not self._skills:
            return ""
        lines = ["Skills (load one with skill.load before using it):"]
        lines += [f"- {n}: {self._skills[n].description}" for n in self.names()]
        return "\n".join(lines)


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_skill_md(text: str, source: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ConfigError(f"{source}: SKILL.md must start with --- frontmatter")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise ConfigError(f"{source}: frontmatter has no closing ---") from None
    meta: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep or line[:1].isspace():
            raise ConfigError(f"{source}: frontmatter lines must be `key: value`, got {line!r}")
        key = key.strip()
        if key not in _KEYS:
            raise ConfigError(f"{source}: unsupported key {key!r} (allowed: name, description)")
        meta[key] = _unquote(value.strip())
    for key in _KEYS:
        if not meta.get(key):
            raise ConfigError(f"{source}: frontmatter needs a non-empty {key}")
    return meta, "\n".join(lines[end + 1 :]).strip() + "\n"


def load_skills(root: Path) -> SkillSet:
    if not root.is_dir():
        return SkillSet()
    skills = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        if d.name.startswith(("_", ".")):
            continue
        md = d / "SKILL.md"
        if not md.is_file():
            raise ConfigError(f"{d}: skill folder without SKILL.md")
        meta, body = parse_skill_md(md.read_text(encoding="utf-8"), str(md))
        if meta["name"] != d.name:
            raise ConfigError(f"{md}: name {meta['name']!r} does not match its folder {d.name!r}")
        if not _NAME.fullmatch(d.name):
            raise ConfigError(f"{md}: skill names are lowercase letters, digits and '-'")
        skills.append(Skill(meta["name"], meta["description"], body, d.resolve()))
    return SkillSet(skills)
```

- [ ] **Step 3: Implement `usta/tools/builtin/skill_load.py`**

```python
"""skill.load: return a skill's SKILL.md body (SPEC §7.1). The index is in the cached prefix."""

from __future__ import annotations

from typing import Any

from usta.core.errors import ToolInputError
from usta.skills import SkillSet
from usta.tools.registry import Tool, ToolContext, ToolOutput


def make_skill_load(skills: SkillSet) -> Tool:
    async def load(args: dict[str, Any], ctx: ToolContext) -> ToolOutput:
        skill = skills.get(args["name"])
        if skill is None:
            raise ToolInputError(f"unknown skill {args['name']!r}; available: {skills.names()}")
        return ToolOutput(
            f"{skill.body.rstrip()}\n\n(This skill's files are at /skills/{skill.name}/ "
            "inside code_exec.)"
        )

    return Tool(
        name="skill.load",
        description="Load a skill's instructions. Do this before producing that kind of file.",
        input_schema={
            "type": "object",
            "properties": {"name": {"enum": skills.names()}},
            "required": ["name"],
            "additionalProperties": False,
        },
        tier="local",
        fn=load,
    )
```

- [ ] **Step 4: Put the index into the request**

In `usta/ports/__init__.py`, add a field to `RunContext`, after `store`:

```python
    skill_index: str = ""  # SkillSet.index_text(); joins the cached prefix (SPEC §7.1)
```

and change its docstring's last sentence to "The run token (M2) is added when it exists."

In `usta/engines/own/loop.py`, add `import hashlib` and replace `build_request` with:

```python
def build_request(
    run: RunState, tools: tuple[ToolSpec, ...], skill_index: str = ""
) -> ModelRequest:
    system = (SystemBlock(text=SYSTEM_PROMPT, cache=not skill_index),)
    version = PROMPT_VERSION
    if skill_index:  # stable per skill set, so the cached prefix stays byte-identical (R10)
        system += (SystemBlock(text=skill_index, cache=True),)
        version += "+sk-" + hashlib.sha256(skill_index.encode("utf-8")).hexdigest()[:8]
    return ModelRequest(
        role="main",
        system=system,
        messages=tuple(run.messages),
        tools=tools,
        prompt_version=version,
        run_id=run.id,
        user_id=run.user_id,
    )
```

Change the call site in `OwnEngine.run` to `build_request(run, ctx.tools.specs(), ctx.skill_index)`.

In `usta/engines/own/prompt.py`, replace the `SYSTEM_PROMPT` bullet list with:

```python
SYSTEM_PROMPT = """\
You are Usta, a work agent for a telematics and security company in Azerbaijan.
You complete multi-step tasks with the tools provided and finish with a short answer.

- Reply in the user's language. Azerbaijani is the default.
- Workspace files are under files/; files produced in this run are under out/. In code_exec the
  same folders are /workspace (read-only) and /out.
- To produce Excel, Word, PDF or chart files, load the matching skill with skill.load first and
  follow it; build the file with code_exec and save it under /out.
- For tasks with three or more steps, keep a task list with the todo tool and update it as you go.
- If a tool returns an error, read it and adjust; do not repeat the same failing call.
- When the task is done, reply with the result and make no further tool calls. Name the files you
  produced.
"""
```

- [ ] **Step 5: Add `usta.skills` to the import-linter lib layer**

```toml
    "usta.lang | usta.skills",
```

- [ ] **Step 6: Run and commit**

```bash
uv run pytest tests/skills tests/engines -q --tb=short
uv run ruff format . && uv run ruff check . && uv run lint-imports && uv run pytest -q --tb=short
git add usta/skills usta/tools/builtin/skill_load.py usta/ports/__init__.py usta/engines/own \
  tests/skills tests/engines pyproject.toml
git commit -m "feat(skills): SKILL.md loader, skill.load, skill index in the cached prefix"
```

---

### Task 7: Skills `pdf-report` and `charts`

**Files:**
- Create: `skills/pdf-report/SKILL.md`, `skills/pdf-report/scripts/usta_pdf.py`, `skills/pdf-report/check.py`, `skills/charts/SKILL.md`, `skills/charts/scripts/usta_charts.py`, `skills/charts/check.py`
- Modify: `tests/conftest.py` (`Box.check`)
- Test: `tests/skills/test_pdf_charts.py` (marker `sandbox`), `tests/skills/test_repo_skills.py`

**Interfaces:**
- Consumes: `box` (Task 4), `load_skills` (Task 6), the image (Task 3).
- Produces, inside the sandbox:
  - `usta_pdf`: `register_fonts()`, `styles() -> dict[str, ParagraphStyle]`, `table(rows, header=True, col_widths=None) -> Table`, `build_pdf(path, title, blocks) -> str`, `fmt_number(x, decimals=2) -> str`, `fmt_azn(x) -> str`, `fmt_date(d) -> str`
  - `usta_charts`: `bar_chart(path, labels, values, title, xlabel="", ylabel="") -> str`, `line_chart(path, x, series, title, xlabel="", ylabel="") -> str`
- Produces, on the host:
  - the `check.py` contract: `python check.py <file>` prints one JSON line `{"ok", "reasons", "text_sample"}`, exits 0 when it could check and 2 on a usage error
  - `Box.check(skill, rel) -> dict`

- [ ] **Step 1: Add `Box.check` to `tests/conftest.py`**

Add `import json` and this method to `Box`:

```python
    async def check(self, skill: str, rel: str) -> dict:
        res = await self.sandbox.exec(
            self.run_id, self.dirs, ("python", f"/skills/{skill}/check.py", f"/out/{rel}")
        )
        assert res.exit_code == 0, res.stderr
        return json.loads(res.stdout.strip().splitlines()[-1])
```

- [ ] **Step 2: Write the failing tests**

`tests/skills/test_pdf_charts.py`:

```python
import pytest

from tests.conftest import Box

pytestmark = pytest.mark.sandbox

PDF = """
import sys
sys.path.insert(0, "/skills/pdf-report/scripts")
sys.path.insert(0, "/skills/charts/scripts")
from usta_charts import bar_chart
from usta_pdf import build_pdf, fmt_azn, fmt_number, table

bar_chart("/out/qrafik.png", ["Bakı", "Gəncə", "Şəki"], [12, 7, 3], "Cihazlar (İyun)")
build_pdf("/out/hesabat.pdf", "Yanacaq sərfiyyatı hesabatı", [
    "## Xülasə",
    "Keçən həftə ümumi sərfiyyat artdı; ən çox Gəncə filialında. İŞIQ, ığ, şə, öü, ç.",
    table([["Maşın", "Litr", "Məbləğ"], ["10-AB-123", fmt_number(42.5), fmt_azn(73.1)]]),
    "/out/qrafik.png",
])
print("ok")
"""


async def test_pdf_with_azerbaijani_text_table_and_chart_passes(box: Box) -> None:
    res = await box.run(PDF)
    assert res.exit_code == 0, res.stderr
    result = await box.check("pdf-report", "hesabat.pdf")
    assert result["ok"], result["reasons"]
    sample = result["text_sample"]
    for word in ("Yanacaq sərfiyyatı", "Gəncə", "İŞIQ", "Məbləğ"):
        assert word in sample
    assert "AZN" in sample or "₼" in sample
    chart = await box.check("charts", "qrafik.png")
    assert chart["ok"], chart["reasons"]


async def test_pdf_with_builtin_font_fails_check(box: Box) -> None:
    code = (
        "from reportlab.pdfgen import canvas\n"
        "c = canvas.Canvas('/out/pis.pdf'); c.setFont('Helvetica', 12)\n"
        "c.drawString(72, 720, 'Gence seheri'); c.save()\n"
    )
    assert (await box.run(code)).exit_code == 0
    result = await box.check("pdf-report", "pis.pdf")
    assert not result["ok"]
    assert any("built-in PDF fonts" in r for r in result["reasons"])


async def test_not_a_pdf_fails_check(box: Box) -> None:
    (box.dirs.out / "fake.pdf").write_text("not a pdf", encoding="utf-8")
    result = await box.check("pdf-report", "fake.pdf")
    assert not result["ok"] and "cannot open" in result["reasons"][0]


async def test_blank_or_tiny_png_fails_check(box: Box) -> None:
    code = (
        "from PIL import Image\n"
        "Image.new('RGB', (400, 300), 'white').save('/out/bos.png')\n"
        "Image.new('RGB', (50, 50), 'red').save('/out/kicik.png')\n"
    )
    assert (await box.run(code)).exit_code == 0
    blank = await box.check("charts", "bos.png")
    tiny = await box.check("charts", "kicik.png")
    assert not blank["ok"] and any("blank" in r for r in blank["reasons"])
    assert not tiny["ok"] and any("too small" in r for r in tiny["reasons"])


async def test_check_usage_error_exits_2(box: Box) -> None:
    res = await box.sandbox.exec(box.run_id, box.dirs, ("python", "/skills/pdf-report/check.py"))
    assert res.exit_code == 2 and "usage" in res.stderr
```

`tests/skills/test_repo_skills.py`:

```python
from pathlib import Path

from usta.skills import load_skills


def test_repo_skills_load_and_have_check_scripts() -> None:
    skills = load_skills(Path("skills"))
    for name in ("charts", "pdf-report"):
        skill = skills.get(name)
        assert skill is not None, name
        assert (skill.dir / "check.py").is_file()
        assert (skill.dir / "scripts").is_dir()
        assert f"/skills/{name}/scripts" in skill.body
```

Run: `uv run pytest tests/skills/test_repo_skills.py -q --tb=short`
Expected: FAIL (`skill is not None`).

- [ ] **Step 3: Write `skills/pdf-report/SKILL.md`**

````markdown
---
name: pdf-report
description: Build PDF reports (A4, Azerbaijani-safe fonts, headings, tables, charts) in code_exec.
---
# pdf-report

Build PDF reports inside `code_exec` with the helpers in `/skills/pdf-report/scripts/usta_pdf.py`.

**Never use ReportLab's built-in fonts (Helvetica, Times, Courier).** They cannot show
ə ğ ı ş İ, and the automatic check fails such files. The helpers register DejaVu Sans for you.

```python
import sys
sys.path.insert(0, "/skills/pdf-report/scripts")
from usta_pdf import build_pdf, table, fmt_number, fmt_azn, fmt_date

build_pdf("/out/hesabat.pdf", "Yanacaq sərfiyyatı hesabatı", [
    "## Xülasə",                       # a line starting with "## " is a heading
    "Keçən həftə ümumi sərfiyyat ...",  # any other string is a paragraph
    table([["Maşın", "Litr"], ["10-AB-123", fmt_number(42.5)]]),  # first row is the header
    "/out/qrafik.png",                 # a .png path embeds an image (make charts with the charts skill)
])
```

- `fmt_number(1234.5)` → `1 234,50`, `fmt_azn(73.1)` → `73,10 ₼`, `fmt_date(date)` → `9 okt 2026` (Babel, `az` locale).
- Write the report in the user's language. Use short headings and a summary first.
- Save under `/out` with a descriptive file name in the user's language, e.g. `/out/uygunsuzluqlar_hesabati.pdf`.
- After the run, the verifier runs `/skills/pdf-report/check.py` on every PDF in `/out`.
````

- [ ] **Step 4: Write `skills/pdf-report/scripts/usta_pdf.py`**

```python
"""PDF report helpers for the Usta sandbox. ReportLab's built-in fonts cannot render
ə ğ ı ş İ (SPEC F6), so everything here uses DejaVu Sans from the image."""

from __future__ import annotations

from datetime import date

from babel.dates import format_date
from babel.numbers import format_currency, format_decimal
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONT_DIR = "/usr/share/fonts/truetype/dejavu"
_registered = False


def register_fonts() -> None:
    global _registered
    if _registered:
        return
    pdfmetrics.registerFont(TTFont("DejaVuSans", f"{FONT_DIR}/DejaVuSans.ttf"))
    pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", f"{FONT_DIR}/DejaVuSans-Bold.ttf"))
    pdfmetrics.registerFontFamily(
        "DejaVuSans",
        normal="DejaVuSans",
        bold="DejaVuSans-Bold",
        italic="DejaVuSans",
        boldItalic="DejaVuSans-Bold",
    )
    _registered = True


def styles() -> dict[str, ParagraphStyle]:
    register_fonts()
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "UstaTitle", parent=base["Title"], fontName="DejaVuSans-Bold", fontSize=18, leading=22
        ),
        "h2": ParagraphStyle(
            "UstaH2", parent=base["Heading2"], fontName="DejaVuSans-Bold", fontSize=13,
            leading=16, spaceBefore=6,
        ),
        "body": ParagraphStyle(
            "UstaBody", parent=base["BodyText"], fontName="DejaVuSans", fontSize=10, leading=14
        ),
        "cell": ParagraphStyle(
            "UstaCell", parent=base["BodyText"], fontName="DejaVuSans", fontSize=9, leading=11
        ),
    }  # fmt: skip


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def table(rows: list[list], header: bool = True, col_widths: list[float] | None = None) -> Table:
    st = styles()
    data = [[Paragraph(_esc(str(c)), st["cell"]) for c in row] for row in rows]
    t = Table(data, colWidths=col_widths, repeatRows=1 if header else 0)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF5")))
    t.setStyle(TableStyle(style))
    return t


def build_pdf(path: str, title: str, blocks: list) -> str:
    """blocks: strings (paragraphs; '## ' starts a heading; a path ending in .png embeds an
    image) or flowables such as table(...)."""
    st = styles()
    story: list = [Paragraph(_esc(title), st["title"]), Spacer(1, 4 * mm)]
    for block in blocks:
        if isinstance(block, str) and block.lower().endswith(".png"):
            story.append(Image(block, width=170 * mm, height=95 * mm, kind="proportional"))
        elif isinstance(block, str) and block.startswith("## "):
            story.append(Paragraph(_esc(block[3:]), st["h2"]))
        elif isinstance(block, str):
            story.append(Paragraph(_esc(block), st["body"]))
        else:
            story.append(block)
        story.append(Spacer(1, 3 * mm))
    doc = SimpleDocTemplate(
        path, pagesize=A4, title=title,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
    )  # fmt: skip
    doc.build(story)
    return path


def fmt_number(x: float, decimals: int = 2) -> str:
    return format_decimal(x, format=f"#,##0.{'0' * decimals}" if decimals else "#,##0", locale="az")


def fmt_azn(x: float) -> str:
    return format_currency(x, "AZN", locale="az")


def fmt_date(d: date) -> str:
    return format_date(d, format="medium", locale="az")
```

- [ ] **Step 5: Write `skills/pdf-report/check.py`**

```python
"""check.py for pdf-report (SPEC §7.1, §9): python check.py <file.pdf>
Prints one JSON line {"ok", "reasons", "text_sample"}; exit 0 when checked, 2 on usage error."""

import json
import sys

BASE14 = ("Courier", "Helvetica", "Times", "Symbol", "ZapfDingbats")
SAMPLE_CHARS = 4000


def emit(ok: bool, reasons: list[str], sample: str) -> None:
    print(json.dumps({"ok": ok, "reasons": reasons, "text_sample": sample}, ensure_ascii=False))


def check(path: str) -> None:
    import pdfplumber

    try:
        pdf = pdfplumber.open(path)
    except Exception as e:
        emit(False, [f"cannot open PDF: {type(e).__name__}: {e}"], "")
        return
    reasons: list[str] = []
    texts: list[str] = []
    fonts: set[str] = set()
    with pdf:
        if not pdf.pages:
            reasons.append("PDF has no pages")
        for page in pdf.pages:
            texts.append(page.extract_text() or "")
            fonts.update(c.get("fontname", "") for c in page.chars)
    text = "\n".join(texts)
    if not text.strip():
        reasons.append("PDF has no extractable text")
    builtin = sorted(f for f in fonts if f.split("+")[-1].startswith(BASE14))
    if builtin:
        reasons.append(
            "uses built-in PDF fonts that cannot show Azerbaijani letters: "
            + ", ".join(builtin)
            + "; build it with /skills/pdf-report/scripts/usta_pdf.py (DejaVu Sans)"
        )
    if "(cid:" in text or "�" in text:
        reasons.append("text has characters without a glyph mapping ((cid:…) or U+FFFD)")
    emit(not reasons, reasons, text[:SAMPLE_CHARS])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: check.py <file.pdf>", file=sys.stderr)
        sys.exit(2)
    check(sys.argv[1])
```

- [ ] **Step 6: Write the charts skill**

`skills/charts/SKILL.md`:

````markdown
---
name: charts
description: Draw bar and line charts as PNG with Azerbaijani-safe fonts, for reports or on their own.
---
# charts

Make charts inside `code_exec` with `/skills/charts/scripts/usta_charts.py` (matplotlib, DejaVu Sans,
150 dpi PNG).

```python
import sys
sys.path.insert(0, "/skills/charts/scripts")
from usta_charts import bar_chart, line_chart

bar_chart("/out/qrafik.png", ["Bakı", "Gəncə"], [12, 7], "Cihazlar", ylabel="Say")
line_chart("/out/trend.png", ["B.e", "Ç.a", "Ç"], {"FMB920": [3, 4, 6]}, "Həftəlik trend")
```

- Titles and labels in the user's language. One message per chart.
- To put a chart in a PDF, pass its path to `build_pdf` (pdf-report skill).
- The verifier runs `/skills/charts/check.py` on every PNG in `/out`. Blank or tiny images fail.
````

`skills/charts/scripts/usta_charts.py`:

```python
"""Chart helpers for the Usta sandbox: matplotlib with DejaVu Sans (covers ə ğ ı ş İ)."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams["font.family"] = "DejaVu Sans"


def _save(fig, ax, path: str, title: str, xlabel: str, ylabel: str) -> str:
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def bar_chart(
    path: str, labels: list[str], values: list[float], title: str, xlabel: str = "", ylabel: str = ""
) -> str:
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar([str(label) for label in labels], values, color="#3B6EA5")
    return _save(fig, ax, path, title, xlabel, ylabel)


def line_chart(
    path: str,
    x: list,
    series: dict[str, list[float]],
    title: str,
    xlabel: str = "",
    ylabel: str = "",
) -> str:
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for name, values in series.items():
        ax.plot([str(v) for v in x], values, marker="o", label=name)
    if len(series) > 1:
        ax.legend()
    return _save(fig, ax, path, title, xlabel, ylabel)
```

`skills/charts/check.py`:

```python
"""check.py for charts (SPEC §7.1, §9): python check.py <file.png>
Prints one JSON line {"ok", "reasons", "text_sample"}; exit 0 when checked, 2 on usage error."""

import json
import sys

MIN_W, MIN_H = 300, 200


def emit(ok: bool, reasons: list[str]) -> None:
    print(json.dumps({"ok": ok, "reasons": reasons, "text_sample": ""}, ensure_ascii=False))


def check(path: str) -> None:
    from PIL import Image

    try:
        img = Image.open(path)
        img.load()
    except Exception as e:
        emit(False, [f"cannot open image: {type(e).__name__}: {e}"])
        return
    reasons = []
    if img.format != "PNG":
        reasons.append(f"expected PNG, got {img.format}")
    w, h = img.size
    if w < MIN_W or h < MIN_H:
        reasons.append(f"image too small: {w}x{h} (min {MIN_W}x{MIN_H})")
    lo, hi = img.convert("L").getextrema()
    if lo == hi:
        reasons.append("image is blank (a single colour)")
    emit(not reasons, reasons)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: check.py <file.png>", file=sys.stderr)
        sys.exit(2)
    check(sys.argv[1])
```

- [ ] **Step 7: Run the tests**

```bash
uv run pytest tests/skills -q --tb=short
uv run pytest -m sandbox tests/skills -q --tb=short
uv run ruff format . && uv run ruff check . && uv run pytest -q --tb=short
```

Expected: all pass. If `fmt_azn` renders the currency differently (e.g. `73,10 ₼` vs `AZN 73,10`), keep the code and update only the SKILL.md example to the real output. The test accepts either `AZN` or `₼`. If ruff's `E402` or `I` rules complain about `skills/*/scripts`, fix the code to comply rather than excluding the folder.

- [ ] **Step 8: Commit**

```bash
git add skills/pdf-report skills/charts tests/conftest.py tests/skills
git commit -m "feat(skills): pdf-report and charts with Azerbaijani-safe fonts and check.py"
```

---

### Task 8: Skills `xlsx` and `docx`

**Files:**
- Create: `skills/xlsx/SKILL.md`, `skills/xlsx/scripts/usta_xlsx.py`, `skills/xlsx/check.py`, `skills/docx/SKILL.md`, `skills/docx/scripts/usta_docx.py`, `skills/docx/check.py`
- Test: `tests/skills/test_xlsx_docx.py` (marker `sandbox`), `tests/skills/test_repo_skills.py` (extend)

**Interfaces:**
- Consumes: `Box.check` (Task 7).
- Produces, inside the sandbox:
  - `usta_xlsx.write_xlsx(path: str, sheets: dict[str, list[list]]) -> str`
  - `usta_docx.new_document() -> Document`
  - `usta_docx.add_table(doc, rows, header=True)`
  - the `check.py` contract as in Task 7

- [ ] **Step 1: Write the failing tests**

`tests/skills/test_xlsx_docx.py`:

```python
import pytest

from tests.conftest import Box

pytestmark = pytest.mark.sandbox

XLSX = """
import sys
sys.path.insert(0, "/skills/xlsx/scripts")
from usta_xlsx import write_xlsx
write_xlsx("/out/uygunsuzluqlar.xlsx", {
    "Uyğunsuzluqlar": [["Anbar", "Model", "Siyahıda", "Qalıq", "Fərq"],
                       ["Gəncə anbarı", "FMB920", 3, 1, -2]],
    "Mənbə: [köhnə]/x": [["Qeyd"], ["İŞIQ"]],
})
"""

DOCX = """
import sys
sys.path.insert(0, "/skills/docx/scripts")
from usta_docx import add_table, new_document
doc = new_document()
doc.add_heading("Müqavilə xülasəsi", level=1)
doc.add_paragraph("Ödəniş şərtləri: hər ayın 5-nə qədər. Cərimə: gecikmənin hər günü üçün 0,1%.")
add_table(doc, [["Bənd", "Məzmun"], ["4.2", "Gecikmə cəriməsi"]])
doc.save("/out/xulase.docx")
"""


async def test_xlsx_with_azerbaijani_headers_passes(box: Box) -> None:
    res = await box.run(XLSX)
    assert res.exit_code == 0, res.stderr
    result = await box.check("xlsx", "uygunsuzluqlar.xlsx")
    assert result["ok"], result["reasons"]
    assert "Gəncə anbarı" in result["text_sample"] and "İŞIQ" in result["text_sample"]


async def test_xlsx_with_error_values_or_no_data_fails(box: Box) -> None:
    code = (
        "from openpyxl import Workbook\n"
        "wb = Workbook(); wb.active.append(['Cəm', '#REF!']); wb.save('/out/xeta.xlsx')\n"
        "Workbook().save('/out/bos.xlsx')\n"
    )
    assert (await box.run(code)).exit_code == 0
    err = await box.check("xlsx", "xeta.xlsx")
    empty = await box.check("xlsx", "bos.xlsx")
    assert not err["ok"] and any("#REF!" in r for r in err["reasons"])
    assert not empty["ok"] and any("no data" in r for r in empty["reasons"])


async def test_docx_with_heading_paragraph_and_table_passes(box: Box) -> None:
    res = await box.run(DOCX)
    assert res.exit_code == 0, res.stderr
    result = await box.check("docx", "xulase.docx")
    assert result["ok"], result["reasons"]
    assert "Ödəniş şərtləri" in result["text_sample"] and "Gecikmə cəriməsi" in result["text_sample"]


async def test_empty_docx_fails(box: Box) -> None:
    assert (await box.run("from docx import Document; Document().save('/out/bos.docx')")).exit_code == 0
    result = await box.check("docx", "bos.docx")
    assert not result["ok"] and any("no text" in r for r in result["reasons"])
```

In `tests/skills/test_repo_skills.py`, change the tuple to `("charts", "docx", "pdf-report", "xlsx")` and add:

```python
def test_repo_has_exactly_the_m1_skills() -> None:
    assert load_skills(Path("skills")).names() == ["charts", "docx", "pdf-report", "xlsx"]
```

Run: `uv run pytest tests/skills/test_repo_skills.py -q --tb=short`
Expected: FAIL.

- [ ] **Step 2: Write the xlsx skill**

`skills/xlsx/SKILL.md`:

````markdown
---
name: xlsx
description: Read and write Excel workbooks (tables with headers, several sheets) in code_exec.
---
# xlsx

**Reading:** use pandas: `pd.read_excel("/workspace/cihazlar.xlsx", sheet_name=None)` gives every sheet.
Print `df.columns` and `df.head()` first; column names are often Azerbaijani (`Qalıq`, `Anbar`).
Strip spaces and compare text with `str.casefold()` only after replacing `İ→i`, `I→ı`.

**Writing:** use `/skills/xlsx/scripts/usta_xlsx.py`. It writes a bold, frozen header row and sets column widths.

```python
import sys
sys.path.insert(0, "/skills/xlsx/scripts")
from usta_xlsx import write_xlsx

write_xlsx("/out/uygunsuzluqlar.xlsx", {
    "Uyğunsuzluqlar": [["Anbar", "Model", "Siyahıda", "Qalıq", "Fərq"], ["Gəncə anbarı", "FMB920", 3, 1, -2]],
})
```

- The first row of each sheet is the header. Keep numbers as numbers (not strings).
- Sheet names: up to 31 characters; `[]:*?/\` are replaced.
- The verifier runs `/skills/xlsx/check.py` on every `.xlsx` in `/out`. Empty workbooks and error values (`#REF!`, `#DIV/0!` …) fail.
````

`skills/xlsx/scripts/usta_xlsx.py`:

```python
"""Excel writing helper for the Usta sandbox (openpyxl)."""

from __future__ import annotations

import re

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

_BAD_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")


def _sheet_title(name: str) -> str:
    return _BAD_SHEET_CHARS.sub("_", name)[:31] or "Sheet"


def write_xlsx(path: str, sheets: dict[str, list[list]]) -> str:
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(title=_sheet_title(name))
        for row in rows:
            ws.append(list(row))
        if rows:
            for cell in ws[1]:
                cell.font = Font(bold=True)
                cell.fill = PatternFill("solid", fgColor="E8EEF5")
            ws.freeze_panes = "A2"
        for column in ws.columns:
            width = max((len(str(c.value)) for c in column if c.value is not None), default=0)
            ws.column_dimensions[get_column_letter(column[0].column)].width = min(60, width + 2)
    wb.save(path)
    return path
```

`skills/xlsx/check.py`:

```python
"""check.py for xlsx (SPEC §7.1, §9): python check.py <file.xlsx>
Prints one JSON line {"ok", "reasons", "text_sample"}; exit 0 when checked, 2 on usage error."""

import json
import sys

ERRORS = {"#REF!", "#VALUE!", "#DIV/0!", "#NAME?", "#N/A", "#NUM!", "#NULL!"}
SAMPLE_CHARS = 4000


def emit(ok: bool, reasons: list[str], sample: str) -> None:
    print(json.dumps({"ok": ok, "reasons": reasons, "text_sample": sample}, ensure_ascii=False))


def check(path: str) -> None:
    from openpyxl import load_workbook

    try:
        wb = load_workbook(path, read_only=True)
    except Exception as e:
        emit(False, [f"cannot open workbook: {type(e).__name__}: {e}"], "")
        return
    reasons: list[str] = []
    texts: list[str] = []
    values = 0
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            for v in row:
                if v is None or v == "":
                    continue
                values += 1
                if isinstance(v, str):
                    if v.strip().upper() in ERRORS:
                        reasons.append(f"sheet {ws.title!r} has an error value {v.strip()}")
                    elif not v.startswith("="):
                        texts.append(v)
    wb.close()
    if values == 0:
        reasons.append("workbook has no data")
    emit(not reasons, sorted(set(reasons)), " | ".join(texts)[:SAMPLE_CHARS])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: check.py <file.xlsx>", file=sys.stderr)
        sys.exit(2)
    check(sys.argv[1])
```

- [ ] **Step 3: Write the docx skill**

`skills/docx/SKILL.md`:

````markdown
---
name: docx
description: Write Word documents (headings, paragraphs, tables) and read .docx files in code_exec.
---
# docx

**Reading:** `from docx import Document; d = Document("/workspace/x.docx")`, then read
`d.paragraphs` and `d.tables`.

**Writing:** use `/skills/docx/scripts/usta_docx.py`. It sets Arial 11, which covers ə ğ ı ş İ in Word and LibreOffice.

```python
import sys
sys.path.insert(0, "/skills/docx/scripts")
from usta_docx import add_table, new_document

doc = new_document()
doc.add_heading("Müqavilə xülasəsi", level=1)
doc.add_paragraph("Ödəniş şərtləri: ...")
add_table(doc, [["Bənd", "Məzmun"], ["4.2", "Gecikmə cəriməsi"]])
doc.save("/out/muqavile_xulasesi.docx")
```

- Write in the user's language, unless the user asks for a document for someone else (e.g. a reply to a customer who wrote in Russian).
- The verifier runs `/skills/docx/check.py` on every `.docx` in `/out`. Documents without text fail.
````

`skills/docx/scripts/usta_docx.py`:

```python
"""Word writing helpers for the Usta sandbox (python-docx)."""

from __future__ import annotations

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt

FONT = "Arial"  # present in Word and mapped to Liberation Sans in LibreOffice; covers Azerbaijani


def new_document():
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = FONT
    style.font.size = Pt(11)
    style.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:cs"), FONT)
    return doc


def add_table(doc, rows: list[list], header: bool = True):
    cols = max(len(r) for r in rows)
    t = doc.add_table(rows=0, cols=cols)
    t.style = "Table Grid"
    for i, row in enumerate(rows):
        cells = t.add_row().cells
        for j, value in enumerate(row):
            cells[j].text = str(value)
            if header and i == 0:
                for run in cells[j].paragraphs[0].runs:
                    run.bold = True
    return t
```

`skills/docx/check.py`:

```python
"""check.py for docx (SPEC §7.1, §9): python check.py <file.docx>
Prints one JSON line {"ok", "reasons", "text_sample"}; exit 0 when checked, 2 on usage error."""

import json
import sys

SAMPLE_CHARS = 4000


def emit(ok: bool, reasons: list[str], sample: str) -> None:
    print(json.dumps({"ok": ok, "reasons": reasons, "text_sample": sample}, ensure_ascii=False))


def check(path: str) -> None:
    from docx import Document

    try:
        doc = Document(path)
    except Exception as e:
        emit(False, [f"cannot open document: {type(e).__name__}: {e}"], "")
        return
    texts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            texts.extend(c.text for c in row.cells if c.text.strip())
    text = "\n".join(texts)
    reasons = []
    if not text.strip():
        reasons.append("document has no text")
    if "�" in text:
        reasons.append("text contains U+FFFD replacement characters (broken encoding)")
    emit(not reasons, reasons, text[:SAMPLE_CHARS])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: check.py <file.docx>", file=sys.stderr)
        sys.exit(2)
    check(sys.argv[1])
```

If `style.element.get_or_add_rPr().get_or_add_rFonts()` is not available in the installed python-docx, replace that line with `style.element.rPr.rFonts.set(qn("w:cs"), FONT)` after accessing `style.font.name` (which creates `rPr`/`rFonts`). Record the change in the report.

- [ ] **Step 4: Run and commit**

```bash
uv run pytest tests/skills -q --tb=short
uv run pytest -m sandbox tests/skills -q --tb=short
uv run ruff format . && uv run ruff check . && uv run pytest -q --tb=short
git add skills/xlsx skills/docx tests/skills
git commit -m "feat(skills): xlsx and docx with check.py"
```

---

### Task 9: Verifier

**Files:**
- Create: `usta/core/verify.py`, `usta/verify/__init__.py`, `usta/verify/verifier.py`
- Modify: `usta/ports/__init__.py` (`VerifierPort`, `RunContext.verifier`), `pyproject.toml` (layer)
- Test: `tests/verify/__init__.py`, `tests/verify/test_verifier.py`

**Interfaces:**
- Consumes: `SandboxPort`, `ExecResult`, `RunDirs`, `ModelGateway`, `SkillSet`/`Skill`, `detect`/`langcheck`, `FakeSandbox`, `InMemoryStore`, `FAKE_PRICE`.
- Produces:
  - `FileCheck(path: str, skill: str, ok: bool, reasons: tuple[str, ...] = (), text_sample: str = "")` (`Frozen`)
  - `VerifyResult(ok: bool, reasons: tuple[str, ...] = (), files: tuple[FileCheck, ...] = (), cost_usd: float = 0.0)` (`Frozen`)
  - `VerifierPort.check(run: RunState) -> VerifyResult` (async)
  - `RunContext.verifier: VerifierPort | None = None`
  - `Verifier(sandbox, models, workspace_root, skills)`
  - Constants `CHECKS`, `VERIFIER_PROMPT`, `VERIFIER_VERSION`

- [ ] **Step 1: Core types and port**

`usta/core/verify.py`:

```python
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
```

In `usta/ports/__init__.py`, import `from usta.core.verify import VerifyResult` and add:

```python
class VerifierPort(Protocol):
    """Runs after the model stops calling tools; identical for both engines (SPEC §9)."""

    async def check(self, run: RunState) -> VerifyResult: ...
```

Then add a field to `RunContext`, after `skill_index`:

```python
    verifier: VerifierPort | None = None  # None: runs finish `done` unchecked (tests only)
```

`RunContext` is declared before `VerifierPort` in the file, so move `VerifierPort` above `RunContext`.

- [ ] **Step 2: Write the failing tests**

`tests/verify/__init__.py` is empty. `tests/verify/test_verifier.py`:

```python
import json
from pathlib import Path

import pytest

from tests.fakes import FAKE_PRICE, FakeSandbox, InMemoryStore
from usta.core.messages import Message, TextBlock
from usta.core.run import RunState
from usta.core.sandbox import ExecResult
from usta.models.fake import FakeModel, reply
from usta.models.gateway import Gateway
from usta.skills import Skill, SkillSet
from usta.verify.verifier import VERIFIER_VERSION, Verifier

AZ_ANSWER = (
    "Hesabat hazırdır: out/hesabat.pdf faylında beş uyğunsuzluq göstərilib, ən böyük fərq "
    "Gəncə anbarında FMB920 modeli üzrə müşahidə olunur və cədvəl də əlavə edilib."
)
EN_ANSWER = (
    "The report is ready: the file out/hesabat.pdf lists five mismatches, the largest one is "
    "in the Ganja warehouse for the FMB920 model and a table is attached."
)


def skills(tmp_path: Path, *names: str) -> SkillSet:
    out = []
    for n in names:
        d = tmp_path / "skills" / n
        d.mkdir(parents=True)
        (d / "check.py").write_text("# stub", encoding="utf-8")
        out.append(Skill(n, f"{n} skill", "body", d))
    return SkillSet(out)


def make(tmp_path: Path, script, handler=None, skill_names=("pdf-report", "xlsx")):
    store = InMemoryStore()
    model = FakeModel(script)
    gateway = Gateway({"main": model}, {model.model_id: FAKE_PRICE}, audit=store)
    sandbox = FakeSandbox(handler)
    verifier = Verifier(sandbox, gateway, tmp_path / "ws", skills(tmp_path, *skill_names))
    run = RunState.new(
        id="r1", user_id="u1", task="Uyğunsuzluqları göstər", engine="own", cost_cap_usd=0.5
    )
    run.messages.append(Message(role="assistant", content=(TextBlock(text=AZ_ANSWER),)))
    out = tmp_path / "ws" / "u1" / "runs" / "r1" / "out"
    out.mkdir(parents=True)
    return verifier, run, out, sandbox, model


def check_json(ok: bool, reasons=(), sample: str = "") -> ExecResult:
    payload = {"ok": ok, "reasons": list(reasons), "text_sample": sample}
    return ExecResult(exit_code=0, stdout=json.dumps(payload, ensure_ascii=False) + "\n", stderr="")


async def test_no_files_and_llm_pass(tmp_path: Path) -> None:
    v, run, _, sandbox, model = make(tmp_path, [reply('{"verdict": "pass", "reasons": []}')])
    result = await v.check(run)
    assert result.ok and result.reasons == () and result.cost_usd == pytest.approx(0.30)
    assert sandbox.calls == []
    req = model.requests[0]
    assert req.role == "main" and req.tools == () and req.prompt_version == VERIFIER_VERSION
    prompt = req.messages[0].text()
    assert "Uyğunsuzluqları göstər" in prompt and AZ_ANSWER in prompt


async def test_failed_file_check_skips_the_llm(tmp_path: Path) -> None:
    def handler(run_id, dirs, argv, stdin):
        assert argv == ("python", "/skills/pdf-report/check.py", "/out/hesabat.pdf")
        return check_json(False, ["uses built-in PDF fonts: Helvetica"])

    v, run, out, _, model = make(tmp_path, [], handler)
    (out / "hesabat.pdf").write_bytes(b"%PDF")
    result = await v.check(run)
    assert not result.ok and model.requests == []
    assert result.reasons == ("out/hesabat.pdf: uses built-in PDF fonts: Helvetica",)


async def test_crashed_check_is_a_failure(tmp_path: Path) -> None:
    v, run, out, _, _ = make(
        tmp_path, [], lambda *_: ExecResult(exit_code=1, stdout="", stderr="Traceback: boom")
    )
    (out / "a.xlsx").write_bytes(b"x")
    result = await v.check(run)
    assert not result.ok and "check.py crashed (exit 1): Traceback: boom" in result.reasons[0]


async def test_files_without_a_check_skill_are_not_checked(tmp_path: Path) -> None:
    v, run, out, sandbox, _ = make(tmp_path, [reply('{"verdict": "pass"}')], skill_names=())
    (out / "q.png").write_bytes(b"x")
    (out / "notes.md").write_text("x", encoding="utf-8")
    assert (await v.check(run)).ok and sandbox.calls == []


async def test_wrong_answer_language_fails_without_llm(tmp_path: Path) -> None:
    v, run, _, _, model = make(tmp_path, [])
    run.messages[-1] = Message(role="assistant", content=(TextBlock(text=EN_ANSWER),))
    result = await v.check(run)
    assert not result.ok and model.requests == []
    assert "final answer language: expected az, detected en" in result.reasons[0]


async def test_pdf_text_in_the_wrong_language_fails(tmp_path: Path) -> None:
    v, run, out, _, _ = make(tmp_path, [], lambda *_: check_json(True, sample=EN_ANSWER))
    (out / "hesabat.pdf").write_bytes(b"%PDF")
    result = await v.check(run)
    assert not result.ok and result.reasons[0].startswith("out/hesabat.pdf: language:")


async def test_llm_fail_reasons_are_returned(tmp_path: Path) -> None:
    v, run, out, _, model = make(
        tmp_path,
        [reply('Here: {"verdict": "fail", "reasons": ["PDF is missing"]}')],
        lambda *_: check_json(True, sample="Cədvəl: Gəncə anbarı FMB920"),
    )
    (out / "c.xlsx").write_bytes(b"x")
    result = await v.check(run)
    assert not result.ok and result.reasons == ("PDF is missing",)
    assert "out/c.xlsx [xlsx]" in model.requests[0].messages[0].text()


@pytest.mark.parametrize("text", ["looks fine", '{"verdict": "maybe"}', '{"verdict": "fail"}'])
async def test_unusable_verdicts_fail_loudly(tmp_path: Path, text: str) -> None:
    v, run, _, _, _ = make(tmp_path, [reply(text)])
    result = await v.check(run)
    assert not result.ok and result.reasons


async def test_symlinks_in_out_are_ignored(tmp_path: Path) -> None:
    v, run, out, sandbox, _ = make(tmp_path, [reply('{"verdict": "pass"}')])
    (out / "link.pdf").symlink_to("/etc/hostname")
    assert (await v.check(run)).ok and sandbox.calls == []
```

Run: `uv run pytest tests/verify -q --tb=short`
Expected: FAIL (`No module named 'usta.verify'`).

- [ ] **Step 3: Implement `usta/verify/verifier.py`**

`usta/verify/__init__.py` is empty.

```python
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
```

- [ ] **Step 4: Add `usta.verify` to the adapter layer**

```toml
    "usta.engines | usta.models | usta.tools | usta.store | usta.worker | usta.sandbox | usta.verify",
```

- [ ] **Step 5: Run and commit**

```bash
uv run pytest tests/verify -q --tb=short
uv run ruff format . && uv run ruff check . && uv run lint-imports && uv run pytest -q --tb=short
git add usta/core/verify.py usta/verify usta/ports/__init__.py tests/verify pyproject.toml
git commit -m "feat(verify): verifier with check.py, langcheck and one LLM check (SPEC §9)"
```

If `test_wrong_answer_language_fails_without_llm` shows lingua detecting something other than `en` for `EN_ANSWER`, report it and do not change the assertion.

---

### Task 10: Engine and worker integration: verifier hook, planning reminder, sandbox release, CLI

**Files:**
- Modify: `usta/core/run.py`, `usta/core/events.py`, `usta/engines/own/loop.py`, `usta/engines/own/prompt.py`, `usta/worker.py`, `usta/cli.py`, `tests/fakes.py` (`FakeVerifier`, `make_context` params)
- Test: `tests/engines/test_own_loop.py`, `tests/test_worker.py`, `tests/test_cli.py`, `tests/core/test_run.py`

**Interfaces:**
- Consumes: `VerifierPort`, `VerifyResult`, `SandboxPort`, `FakeSandbox`.
- Produces:
  - `RunState.verify_failures: int = 0`, `RunState.todo_reminded: bool = False`
  - `RunState.append_tool_results(results, note: str | None = None)`
  - `EventType` gains `"verification"`
  - `PLANNING_REMINDER`, `VERIFY_RETRY` in `prompt.py`
  - `Worker(..., sandbox: SandboxPort | None = None)`
  - `tests.fakes.FakeVerifier(results)`
  - `make_context(..., verifier=None, skill_index="")`

- [ ] **Step 1: Write the failing tests**

Append to `tests/core/test_run.py`:

```python
from usta.core.messages import TextBlock, ToolResult


def test_append_tool_results_with_a_note() -> None:
    run = RunState.new(id="r", user_id="u", task="t", engine="own", cost_cap_usd=0.5)
    run.append_tool_results([ToolResult(call_id="c1", content="ok")], note="Xatırlatma")
    msg = run.messages[-1]
    assert msg.role == "user" and msg.tool_results()[0].call_id == "c1"
    assert isinstance(msg.content[-1], TextBlock) and msg.content[-1].text == "Xatırlatma"


def test_old_checkpoints_load_with_defaults() -> None:
    raw = RunState.new(id="r", user_id="u", task="t", engine="own", cost_cap_usd=0.5).model_dump()
    raw.pop("verify_failures")
    raw.pop("todo_reminded")
    run = RunState.model_validate(raw)
    assert run.verify_failures == 0 and run.todo_reminded is False
```

Add to `tests/fakes.py`:

```python
from collections import deque

from usta.core.verify import VerifyResult
from usta.ports import VerifierPort


class FakeVerifier:
    def __init__(self, results: list[VerifyResult]) -> None:
        self.results = deque(results)
        self.checked: list[int] = []  # number of messages in the run at each check

    async def check(self, run: RunState) -> VerifyResult:
        self.checked.append(len(run.messages))
        return self.results.popleft()
```

Change `make_context` to accept `verifier: VerifierPort | None = None` and `skill_index: str = ""` (keyword-only, after `price`) and pass them on: `RunContext(models=gateway, tools=pipeline, store=store, skill_index=skill_index, verifier=verifier)`.

In `tests/engines/test_own_loop.py`, give `drive` a `verifier=None` keyword and pass it to `make_context(script, store, tmp_path, verifier=verifier)`. Add a `tools` keyword the same way (default `(ECHO,)` from `tests.fakes`). Then append:

```python
from tests.fakes import ECHO, FakeVerifier
from usta.core.messages import TextBlock
from usta.core.verify import VerifyResult
from usta.engines.own.prompt import PLANNING_REMINDER
from usta.tools.builtin.todo import TODO

PASS = VerifyResult(ok=True)


def fail(*reasons: str, cost: float = 0.0) -> VerifyResult:
    return VerifyResult(ok=False, reasons=reasons, cost_usd=cost)


async def test_verified_run_finishes_done(tmp_path: Path) -> None:
    v = FakeVerifier([PASS])
    run, events, _, _ = await drive([reply("Hazırdır.")], tmp_path, verifier=v)
    assert run.stop_reason == StopReason.DONE
    types = [e.type for e in events]
    assert types[-2:] == ["verification", "finished"]
    assert events[-2].data == {"ok": True, "reasons": [], "attempt": 1, "cost_usd": 0.0}


async def test_failed_verification_retries_once_with_reasons(tmp_path: Path) -> None:
    v = FakeVerifier([fail("PDF yoxdur"), PASS])
    run, events, model, _ = await drive([reply("Bitdi."), reply("İndi bitdi.")], tmp_path, verifier=v)
    assert run.stop_reason == StopReason.DONE and run.verify_failures == 1
    retry = model.requests[1].messages[-1]
    assert retry.role == "user" and "- PDF yoxdur" in retry.text()
    assert [e.data["attempt"] for e in events if e.type == "verification"] == [1, 2]


async def test_second_failure_stops_verification_failed(tmp_path: Path) -> None:
    v = FakeVerifier([fail("a"), fail("b", "c")])
    run, _, _, store = await drive([reply("1"), reply("2")], tmp_path, verifier=v)
    assert run.stop_reason == StopReason.VERIFICATION_FAILED and run.stop_detail == "b; c"
    assert (await store.load("r1")).stop_reason == StopReason.VERIFICATION_FAILED
    assert run.final_text() == "2"  # the output is still there to show with a warning


async def test_verifier_cost_counts_toward_the_run(tmp_path: Path) -> None:
    v = FakeVerifier([VerifyResult(ok=True, cost_usd=0.07)])
    run, _, _, _ = await drive([reply("ok")], tmp_path, verifier=v)
    assert run.cost_usd == pytest.approx(0.30 + 0.07)


async def test_planning_reminder_once_on_turn_two_without_todo(tmp_path: Path) -> None:
    script = [call("test.echo", {"text": "1"}), call("test.echo", {"text": "2"}),
              call("test.echo", {"text": "3"}), reply("ok")]
    run, _, model, _ = await drive(script, tmp_path)
    after_turn = [m for m in run.messages if m.role == "user"][1:]  # skip the task
    notes = [m.content[-1].text for m in after_turn if isinstance(m.content[-1], TextBlock)]
    assert notes == [PLANNING_REMINDER] and run.todo_reminded
    assert isinstance(after_turn[1].content[-1], TextBlock)  # attached to turn 2's results


async def test_no_planning_reminder_when_todo_exists(tmp_path: Path) -> None:
    items = {"items": [{"content": "Faylı oxu", "status": "in_progress"}]}
    script = [call("todo", items), call("test.echo", {"text": "2"}), reply("ok")]
    run, _, _, _ = await drive(script, tmp_path, tools=(ECHO, TODO))
    assert not run.todo_reminded
```

If `pytest` is not yet imported in `test_own_loop.py`, add `import pytest`.

Append to `tests/test_worker.py` (give `make_worker` a `sandbox=None` keyword passed to `Worker(..., sandbox=sandbox)`):

```python
from tests.fakes import FakeSandbox


async def test_sandbox_is_released_when_a_run_finishes_or_parks(tmp_path: Path) -> None:
    sb = FakeSandbox()
    worker, store, _, _ = make_worker([reply("ok")], tmp_path, sandbox=sb)
    run = await worker.submit("u1", "Tapşırıq")
    await worker.execute(run.id)
    assert sb.released == [run.id]


async def test_recover_reaps_containers_of_runs_not_resuming(tmp_path: Path) -> None:
    sb = FakeSandbox()
    worker, store, _, _ = make_worker([reply("ok")], tmp_path, sandbox=sb)
    run = await worker.submit("u1", "Tapşırıq")
    await worker.recover()
    assert sb.reaped_keep == [{run.id}]
```

Append to `tests/test_cli.py`:

```python
from usta import cli
from usta.core.messages import Message, TextBlock


def test_format_verification_events() -> None:
    ok = Event(run_id="r", type="verification", data={"ok": True, "reasons": [], "attempt": 1, "cost_usd": 0.0})
    bad = Event(run_id="r", type="verification", data={"ok": False, "reasons": ["a", "b"], "attempt": 1, "cost_usd": 0.0})
    assert format_event(ok) == "  ✓ verified"
    assert format_event(bad) == "  ✗ verification failed: a; b"


def test_verification_failed_still_prints_the_answer_with_a_warning(capsys) -> None:
    run = RunState.new(id="r", user_id="u", task="t", engine="own", cost_cap_usd=0.5)
    run.messages.append(Message(role="assistant", content=(TextBlock(text="Nəticə"),)))
    run.finish(StopReason.VERIFICATION_FAILED, "PDF yoxdur")
    assert cli._exit_code(run) == 1
    out = capsys.readouterr().out
    assert "⚠ not verified: PDF yoxdur" in out and "Nəticə" in out
```

Reuse whatever imports of `Event`, `format_event`, `RunState` and `StopReason` `test_cli.py` already has; add the missing ones.

Run: `uv run pytest tests/core tests/engines tests/test_worker.py tests/test_cli.py -q --tb=short`
Expected: FAIL.

- [ ] **Step 2: `RunState` and events**

In `usta/core/run.py`, import `TextBlock` from `usta.core.messages`. Add these fields after `pending`:

```python
    verify_failures: int = 0  # SPEC §9: one retry, then verification_failed
    todo_reminded: bool = False  # ADR-016 planning reminder sent
```

Replace `append_tool_results` with:

```python
    def append_tool_results(self, results: list[ToolResult], note: str | None = None) -> None:
        content: tuple = tuple(results)
        if note:  # after the results: Anthropic wants tool_result blocks first
            content += (TextBlock(text=note),)
        self.messages.append(Message(role="user", content=content))
```

In `usta/core/events.py`, add `"verification",` to `EventType`, before `"parked"`.

- [ ] **Step 3: Prompt constants**

Append to `usta/engines/own/prompt.py`:

```python
PLANNING_REMINDER = (
    "Reminder: if this task has three or more steps, write a task list with the todo tool now "
    "and keep it updated as you work."
)
VERIFY_RETRY = (
    "Automatic verification found problems with your result:\n{reasons}\n"
    "Fix them (use tools if needed), then give your final answer again."
)
```

- [ ] **Step 4: The loop**

In `usta/engines/own/loop.py`, import `Message` from `usta.core.messages` and `PLANNING_REMINDER, VERIFY_RETRY` from the prompt module. Replace the block

```python
                calls = resp.tool_calls()
                if not calls:
                    yield await self._finish(run, ctx, timer, StopReason.DONE)
                    return
```

with

```python
                calls = resp.tool_calls()
                if not calls:
                    if ctx.verifier is None:
                        yield await self._finish(run, ctx, timer, StopReason.DONE)
                        return
                    verdict = await ctx.verifier.check(run)
                    run.cost_usd += verdict.cost_usd
                    timer.tick()
                    yield Event(
                        run_id=run.id,
                        type="verification",
                        data={
                            "ok": verdict.ok,
                            "reasons": list(verdict.reasons),
                            "attempt": run.verify_failures + 1,
                            "cost_usd": verdict.cost_usd,
                        },
                    )
                    if verdict.ok:
                        yield await self._finish(run, ctx, timer, StopReason.DONE)
                        return
                    if run.verify_failures >= 1:
                        detail = "; ".join(verdict.reasons)[:1000]
                        yield await self._finish(
                            run, ctx, timer, StopReason.VERIFICATION_FAILED, detail
                        )
                        return
                    run.verify_failures += 1
                    reasons = "\n".join(f"- {r}" for r in verdict.reasons)
                    run.messages.append(Message.user_text(VERIFY_RETRY.format(reasons=reasons)))
                    await ctx.store.checkpoint(run)
                    continue
```

In `_execute`, replace `run.append_tool_results(results)` with:

```python
        note = None
        if run.turns == 2 and not run.todo and not run.todo_reminded:  # ADR-016
            run.todo_reminded = True
            note = PLANNING_REMINDER
        run.append_tool_results(results, note=note)
```

- [ ] **Step 5: The worker**

In `usta/worker.py`, import `SandboxPort` from `usta.ports`. Add the keyword `sandbox: SandboxPort | None = None` to `__init__` (after `on_event`) and store it as `self._sandbox`. Replace `_execute_claimed` and `recover`, and add `_release`:

```python
    async def _execute_claimed(self, run_id: str) -> RunState:
        run = await self._store.load(run_id)
        if run.is_finished or run.is_parked:
            return run
        try:
            async for event in self._engine.run(run, self._ctx):
                await self._emit(event, run.user_id)
        finally:
            await self._release(run.id)  # SPEC §10: destroyed on park or finish
        return run

    async def _release(self, run_id: str) -> None:
        if self._sandbox is None:
            return
        try:
            await self._sandbox.release(run_id)
        except Exception:
            logger.exception("sandbox release failed for run %s", run_id)

    async def recover(self) -> list[str]:
        """On startup: resume runs a crash left running or queued (ADR-014 rule 3), after
        removing sandbox containers of runs that are not resuming."""
        run_ids = await self._store.ids_with_status(RunStatus.RUNNING, RunStatus.QUEUED)
        if self._sandbox is not None:
            try:
                await self._sandbox.reap(keep=set(run_ids))
            except Exception:
                logger.exception("recover: sandbox reap failed; continuing")
        for run_id in run_ids:
            try:
                await self.execute(run_id)
            except Exception:
                logger.exception("recover: run %s failed; continuing with the rest", run_id)
        return run_ids
```

- [ ] **Step 6: The CLI**

In `usta/cli.py` `format_event`, add before `case "parked":`:

```python
        case "verification":
            if d["ok"]:
                return "  ✓ verified"
            return "  ✗ verification failed: " + "; ".join(d["reasons"])
```

Replace `_exit_code` with:

```python
def _exit_code(run: RunState) -> int:
    if run.is_parked:
        return 3
    if run.is_finished and run.stop_reason == StopReason.VERIFICATION_FAILED:
        print(f"\n⚠ not verified: {run.stop_detail}\n\n{run.final_text()}")  # SPEC §9
        return 1
    if run.is_finished and run.stop_reason != StopReason.DONE:
        return 1
    if run.is_finished:
        print("\n" + run.final_text())
    return 0
```

- [ ] **Step 7: Run and commit**

```bash
uv run pytest tests/core tests/engines tests/test_worker.py tests/test_cli.py -q --tb=short
uv run ruff format . && uv run ruff check . && uv run lint-imports && uv run pytest -q --tb=short
git add usta/core usta/engines usta/worker.py usta/cli.py tests
git commit -m "feat(engine): verifier hook with one retry, planning reminder, sandbox release on park/finish"
```

---
### Task 11: Composition root: sandbox, skills, verifier, startup preflight

**Files:**
- Modify: `usta/app/config.py`, `usta/app/wiring.py`, `config/profiles/*.toml` (comment only, if needed)
- Test: `tests/app/test_wiring.py`, `tests/test_cli.py` (factories and scripts)

**Interfaces:**
- Consumes: everything from Tasks 1–10.
- Produces:
  - `Settings.gvisor_runtime: str = "runsc"` (env `USTA_GVISOR_RUNTIME`)
  - `Settings.skills_dir: Path = Path("skills")` (env `USTA_SKILLS_DIR`)
  - `Profile.sandbox_image: str = "usta-sandbox:1"`
  - `build_sandbox(profile, settings) -> DockerSandbox`
  - `build_app(settings, *, env=os.environ, model_overrides=None, sandbox_override: SandboxPort | None = None, on_event=None) -> App`

- [ ] **Step 1: Write the failing tests**

In `tests/app/test_wiring.py`:

1. Pass `sandbox_override=FakeSandbox()` to the `build_app` call in `test_two_tool_task_runs_end_to_end_through_real_wiring`. Append `reply('{"verdict": "pass", "reasons": []}')` to its `script`, because the verifier's LLM check now uses one model call. Change `assert n_calls == 3` to `assert n_calls == 4`.
2. Add these tests:

```python
from tests.fakes import FakeSandbox
from usta.app.config import load_profile
from usta.app.wiring import build_sandbox


async def test_sandbox_overrides_are_refused_outside_the_test_profile() -> None:
    settings = Settings(profile="dev-openai", database_url="postgresql+asyncpg://x@127.0.0.1/x")
    with pytest.raises(ConfigError, match="P8: sandbox overrides"):
        await build_app(settings, env={"OPENAI_API_KEY": "k"}, sandbox_override=FakeSandbox())


def test_build_sandbox_uses_gvisor_runtime_except_in_test() -> None:
    dev = Settings(
        profile="dev-openai", database_url="x", gvisor_runtime="runsc-kvm", skills_dir=Path("skills")
    )
    sb = build_sandbox(load_profile("dev-openai", dev.config_dir), dev)
    args = sb.run_args("r1", RunDirs(files=Path("/w/f"), out=Path("/w/o")))
    assert "runsc-kvm" in args and "usta-sandbox:1" in args
    test = Settings(profile="test", database_url="x")
    assert "runc" in build_sandbox(load_profile("test", test.config_dir), test).run_args(
        "r1", RunDirs(files=Path("/w/f"), out=Path("/w/o"))
    )


@pytest.mark.pg
async def test_code_exec_and_skills_are_wired(clean_db: str, tmp_path: Path) -> None:
    sb = FakeSandbox(lambda *_: ExecResult(exit_code=0, stdout="4\n", stderr=""))
    script = [
        call("skill.load", {"name": "xlsx"}),
        call("code_exec", {"code": "print(2 + 2)"}),
        reply("Nəticə 4-dür."),
        reply('{"verdict": "pass", "reasons": []}'),
    ]
    model = FakeModel(script)
    settings = Settings(profile="test", database_url=clean_db, workspace_root=tmp_path)
    app = await build_app(settings, env={}, model_overrides={"main": model}, sandbox_override=sb)
    try:
        await app.store.add_user("u1", "Test")
        run = await app.worker.execute((await app.worker.submit("u1", "2+2 hesabla")).id)
        assert run.stop_reason == StopReason.DONE
        assert sb.calls[0][1:] == (("python", "-"), "print(2 + 2)")
        assert sb.released == [run.id]
        first = model.requests[0]
        assert {t.name for t in first.tools} >= {"code_exec", "skill.load", "file.write"}
        assert "pdf-report" in first.system[-1].text and first.system[-1].cache
        assert model.requests[-1].tools == ()  # the verifier's request
    finally:
        await app.aclose()
```

Add the imports `from usta.core.sandbox import ExecResult` and `from usta.core.workspace import RunDirs`.

In `tests/test_cli.py`, every `functools.partial(build_app, model_overrides=...)` gains `sandbox_override=FakeSandbox()`. Every script whose run reaches `done` gains a trailing `reply('{"verdict": "pass", "reasons": []}')`. Add `from tests.fakes import FakeSandbox`.

Run: `uv run pytest tests/app tests/test_cli.py -q --tb=short`
Expected: FAIL (`build_sandbox` missing, unexpected keyword `sandbox_override`).

- [ ] **Step 2: Settings and profile**

In `usta/app/config.py`, add to `Settings`:

```python
    gvisor_runtime: str = "runsc"  # docker runtime name for gVisor; runsc-kvm in WSL2 dev (ADR-005)
    skills_dir: Path = Path("skills")
```

and to `Profile`, after `sandbox`:

```python
    sandbox_image: str = "usta-sandbox:1"
```

- [ ] **Step 3: Wiring**

In `usta/app/wiring.py`, add these imports:

```python
from usta.ports import ModelPort, RunContext, SandboxPort
from usta.sandbox.docker import DockerSandbox, SandboxConfig
from usta.skills import load_skills
from usta.tools.builtin.code_exec import make_code_exec
from usta.tools.builtin.skill_load import make_skill_load
from usta.verify.verifier import Verifier
```

Add `build_sandbox`:

```python
def build_sandbox(profile: Profile, settings: Settings) -> DockerSandbox:
    gvisor = profile.sandbox == "gvisor"  # docker_hardened (runc) is test-only; guards enforce it
    return DockerSandbox(
        SandboxConfig(
            image=profile.sandbox_image,
            runtime=settings.gvisor_runtime if gvisor else "runc",
            gvisor=gvisor,
            skills_dir=settings.skills_dir.resolve(),
            uid=os.getuid(),
            gid=os.getgid(),
        )
    )
```

In `build_app`:
- Add the keyword parameter `sandbox_override: SandboxPort | None = None` before `on_event`.
- Directly after the existing `model_overrides` P8 check, add:

```python
    if sandbox_override is not None and profile.name != "test":
        raise ConfigError("P8: sandbox overrides are allowed only in the test profile")
    skills = load_skills(settings.skills_dir)
    sandbox: SandboxPort
    if sandbox_override is not None:
        sandbox = sandbox_override
    else:
        docker_sandbox = build_sandbox(profile, settings)
        if problems := await docker_sandbox.preflight():
            raise ConfigError("startup refused:\n- " + "\n- ".join(problems))
        sandbox = docker_sandbox
```

- Replace the pipeline and worker construction with:

```python
    tools = [*builtin_tools(), make_code_exec(sandbox)]
    if skills.names():
        tools.append(make_skill_load(skills))
    pipeline = ToolPipeline(
        ToolRegistry(tools), audit=store, workspace_root=settings.workspace_root
    )
    b = profile.budget
    budget = Budget(
        max_turns=b.max_turns,
        cost_step_usd=b.cost_cap_usd,
        max_active_seconds=b.max_active_seconds,
    )
    ctx = RunContext(
        models=gateway,
        tools=pipeline,
        store=store,
        skill_index=skills.index_text(),
        verifier=Verifier(sandbox, gateway, settings.workspace_root, skills),
    )
    worker = Worker(
        store,
        OwnEngine(budget),
        ctx,
        budget,
        engine_name="own",
        user_monthly_cap_usd=b.user_monthly_cap_usd,
        on_event=on_event,
        sandbox=sandbox,
    )
```

The preflight runs before `create_async_engine`, so a missing image or runtime fails fast and leaks no pool.

- [ ] **Step 4: Run, lint and commit**

```bash
uv run pytest tests/app tests/test_cli.py -q --tb=short
uv run ruff format . && uv run ruff check . && uv run lint-imports && uv run pytest -q --tb=short
git add usta/app tests/app tests/test_cli.py
git commit -m "feat(app): wire sandbox, code_exec, skills and verifier; refuse startup without gVisor/image"
```

- [ ] **Step 5: Manual startup check (real Docker)**

```bash
USTA_PROFILE=dev-openai USTA_GVISOR_RUNTIME=no-such-rt OPENAI_API_KEY=dummy \
  USTA_DATABASE_URL=postgresql+asyncpg://x@127.0.0.1/x uv run usta recover; echo "exit=$?"
```

Expected: `exit=2`, and the message lists `docker has no runtime 'no-such-rt'`. No traceback. Paste the output into the report. (The dummy key is a literal placeholder, not a secret.)

---

### Task 12: T3a sandbox-escape suite and the CI `t3a` job

**Files:**
- Create: `tests/sandbox/test_escapes.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: the `box` fixture, `SANDBOX_RUNTIME`, `FILE_READ`, `ToolContext`, `DockerSandbox.preflight`.
- Produces: the T3a suite (marker `sandbox`) and the CI job `t3a`.

- [ ] **Step 1: Write the escape tests**

`tests/sandbox/test_escapes.py`:

```python
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
    runtime = subprocess.run(
        ["docker", "inspect", "-f", "{{.HostConfig.Runtime}}", container_name(box.run_id)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert runtime == SANDBOX_RUNTIME
    assert await box.sandbox.preflight() == []


async def test_network_is_unreachable(box: Box) -> None:
    result = await run_json(box, """
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
""")
    assert set(result.values()) == {"blocked"}, result


async def test_workspace_skills_and_root_fs_are_read_only(box: Box) -> None:
    result = await run_json(box, """
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
""")
    assert result == {
        "/workspace/x.txt": "blocked", "/skills/x.txt": "blocked", "/etc/x": "blocked",
        "/usr/x": "blocked", "/x": "blocked", "/tmp/x": "ok", "/out/x": "ok",
    }  # fmt: skip
    assert not (box.dirs.files / "x.txt").exists()


async def test_host_paths_are_invisible(box: Box, tmp_path: Path) -> None:
    secret = tmp_path / "host-secret.txt"
    secret.write_text("gizli", encoding="utf-8")
    result = await run_json(box, f"""
import os
r = {{}}
for name, path in [("host_file", {str(secret)!r}), ("docker_sock", "/var/run/docker.sock"),
                   ("host_home", {str(Path.home())!r})]:
    r[name] = "VISIBLE" if os.path.exists(path) else "missing"
r["pid1"] = open("/proc/1/cmdline", "rb").read().replace(b"\\0", b" ").decode().strip()
print(json.dumps(r))
""")
    assert result["host_file"] == result["docker_sock"] == result["host_home"] == "missing"
    assert result["pid1"].startswith("sleep")


async def test_runs_unprivileged(box: Box) -> None:
    result = await run_json(box, """
import os
status = dict(line.split(":", 1) for line in open("/proc/self/status") if ":" in line)
print(json.dumps({"uid": os.getuid(), "cap_eff": status.get("CapEff", "").strip()}))
""")
    assert result["uid"] != 0
    assert result["cap_eff"] in ("0000000000000000", ""), result  # "" -> report it; see Step 3


async def test_pids_are_limited(box: Box) -> None:
    result = await run_json(box, """
import subprocess
procs = []
for _ in range(300):
    try:
        procs.append(subprocess.Popen(["sleep", "30"]))
    except OSError:
        break
print(json.dumps({"started": len(procs)}))
for p in procs:
    p.kill()
""")
    assert result["started"] < 128


async def test_fork_bomb_is_contained(box: Box) -> None:
    res = await box.run(
        "import os\nwhile True:\n    try:\n        os.fork()\n    except OSError:\n        pass\n",
        timeout_s=5,
    )
    assert res.timed_out or res.exit_code != 0
    assert res.duration_ms < 30_000
    assert (await box.run("print('ok')")).stdout == "ok\n"


async def test_memory_bomb_is_contained(box: Box) -> None:
    res = await box.run(
        "chunks = []\nwhile True:\n    chunks.append(bytearray(100 * 1024 * 1024))\n", timeout_s=30
    )
    assert res.exit_code != 0
    assert (await box.run("print('ok')")).stdout == "ok\n"


async def test_tmp_is_size_limited(box: Box) -> None:
    result = await run_json(box, """
try:
    with open("/tmp/big", "wb") as f:
        for _ in range(300):
            f.write(b"0" * 1024 * 1024)
    r = "WROTE"
except OSError:
    r = "blocked"
print(json.dumps({"tmp": r}))
""")
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
```

- [ ] **Step 2: Run locally**

```bash
uv run pytest -m sandbox tests/sandbox -q --tb=short
USTA_TEST_SANDBOX_RUNTIME=runsc-kvm uv run pytest -m sandbox tests/sandbox -q --tb=short
```

Expected: all pass on both platforms.

- [ ] **Step 3: Handle failures as findings, not test edits**

If an escape test fails, the sandbox has a hole. Fix `DockerSandbox` (or the image), never the assertion, and record the finding in the report.

Two exceptions are allowed, and both must be reported:
- If gVisor does not expose `CapEff` in `/proc/self/status`, keep the `""` branch and note it.
- If `10.0.2.2` is meaningless on the platform, it still must be `blocked`.

- [ ] **Step 4: Add the CI job**

The trivy-action tags were hijacked in March 2026; this is the same supply-chain campaign behind F8. So:
- Pin every third-party action in this job by **full commit SHA**, with the tag as a trailing comment.
- Pick versions released at least two weeks ago, after that incident.
- Verify each SHA with `gh api repos/<owner>/<repo>/git/ref/tags/<tag>`.
- Pin the `runsc` release that the dev machine uses (`release-20260928.0`). Verify the download path with `curl -fsI` first, and use the path that exists.

Append to `.github/workflows/ci.yml`:

```yaml
  t3a:
    # T3a (SPEC §15.1): fake model + real gVisor sandbox, every push. runsc's default platform
    # (systrap) works on GitHub's VMs; WSL2 dev uses runsc-kvm (ADR-005).
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - name: Install gVisor runsc (pinned, checksum-verified)
        env:
          RUNSC_RELEASE: "20260928.0"
        run: |
          set -euo pipefail
          ARCH=$(uname -m)
          URL="https://storage.googleapis.com/gvisor/releases/release/${RUNSC_RELEASE}/${ARCH}"
          curl -fsSL -O "${URL}/runsc" -O "${URL}/runsc.sha512"
          sha512sum -c runsc.sha512
          sudo install -m 0755 runsc /usr/local/bin/runsc
          sudo /usr/local/bin/runsc install
          sudo systemctl restart docker
          docker info --format '{{json .Runtimes}}' | grep -q '"runsc"'
      - uses: docker/setup-buildx-action@<SHA> # <tag>
      - name: Build sandbox image
        uses: docker/build-push-action@<SHA> # <tag>
        with:
          context: sandbox-image
          tags: usta-sandbox:1
          load: true
          cache-from: type=gha,scope=sandbox
          cache-to: type=gha,scope=sandbox,mode=max
      - name: Scan sandbox image (critical, fixable)
        uses: aquasecurity/trivy-action@<SHA> # <tag>
        with:
          image-ref: usta-sandbox:1
          severity: CRITICAL
          ignore-unfixed: true
          exit-code: "1"
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --locked
      - run: uv run pytest -q --tb=short -m sandbox
        env:
          USTA_TEST_SANDBOX_RUNTIME: runsc
```

Replace each `<SHA> # <tag>` with the verified values. Leave no placeholder in the committed file.

- [ ] **Step 5: Commit, push, watch CI**

```bash
uv run ruff format . && uv run ruff check .
git add tests/sandbox/test_escapes.py .github/workflows/ci.yml
git commit -m "test(t3a): sandbox escape suite; CI job on real gVisor with Trivy scan"
git push
gh run watch --exit-status "$(gh run list --branch "$(git branch --show-current)" --limit 1 --json databaseId -q '.[0].databaseId')"
```

Expected: the `t1`, `t3a` and `gitleaks` jobs are green. If Trivy fails on a critical CVE with a fix available, rebuild against a newer base digest (Task 3, Step 3). Do not add an ignore file without a ruling from the controller.

---

### Task 13: T-c fixtures and the deterministic T-c checker

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (dev dependency `openpyxl`)
- Create: `fixtures/__init__.py`, `fixtures/generate.py`, `evals/__init__.py`, `evals/checks/__init__.py`, `evals/checks/tc.py`
- Test: `tests/evals/__init__.py`, `tests/evals/test_tc.py`

**Interfaces:**
- Consumes: `az_casefold` (Task 1).
- Produces:
  - `fixtures.generate`: `SEED = 20261009`, `MODELS`, `WAREHOUSES`, `N_MISMATCHES = 5`, `build(seed=SEED) -> tuple[list[list], list[list], list[dict]]` (device rows with header, stock rows with header, truth), and `write(files_dir: Path, truth_path: Path, seed=SEED) -> None`, which writes `cihazlar.xlsx` and `anbar_qaliqlari.xlsx` into `files_dir` and the truth JSON to `truth_path`
  - `evals.checks.tc.check_tc(xlsx: Path, truth: list[dict], warehouses=WAREHOUSES, models=MODELS) -> list[str]` (problems; empty means correct)
  - CLI `uv run python -m evals.checks.tc <xlsx> <truth.json>`, exiting 0 or 1

- [ ] **Step 1: Add the dev dependency (its own commit)**

```bash
uv add --dev 'openpyxl>=3.1,<4'
uv run pytest -q --tb=short
git add pyproject.toml uv.lock
git commit -m "build(dev): add openpyxl for T-c fixtures and checks (dev only)"
```

Flag this new dependency in your report (M1 Plan Decision 8).

- [ ] **Step 2: Write the failing tests**

`tests/evals/__init__.py` is empty. `tests/evals/test_tc.py`:

```python
import json
from pathlib import Path

from openpyxl import Workbook, load_workbook

from evals.checks.tc import check_tc
from fixtures.generate import MODELS, N_MISMATCHES, WAREHOUSES, build, write


def test_build_is_deterministic_and_plants_the_mismatches() -> None:
    devices, stock, truth = build()
    assert build() == (devices, stock, truth)
    assert devices[0] == ["IMEI", "Model", "Anbar", "Status"]
    assert stock[0] == ["Anbar", "Model", "Qalıq"]
    assert len(truth) == N_MISMATCHES
    assert all(t["ferq"] != 0 and t["qaliq"] >= 0 for t in truth)
    assert 15 <= len(devices) - 1 <= 60
    assert len({row[0] for row in devices[1:]}) == len(devices) - 1  # unique IMEIs
    listed = {(w, m): 0 for w in WAREHOUSES for m in MODELS}
    for _, model, wh, _ in devices[1:]:
        listed[(wh, model)] += 1
    for wh, model, qty in stock[1:]:
        planted = [t for t in truth if (t["anbar"], t["model"]) == (wh, model)]
        assert (qty != listed[(wh, model)]) == bool(planted)


def test_write_puts_truth_outside_the_workspace(tmp_path: Path) -> None:
    files, truth_path = tmp_path / "files", tmp_path / "secret" / "truth.json"
    write(files, truth_path)
    assert sorted(p.name for p in files.iterdir()) == ["anbar_qaliqlari.xlsx", "cihazlar.xlsx"]
    assert len(json.loads(truth_path.read_text(encoding="utf-8"))) == N_MISMATCHES
    ws = load_workbook(files / "anbar_qaliqlari.xlsx").active
    assert [c.value for c in ws[1]] == ["Anbar", "Model", "Qalıq"]


def table(tmp_path: Path, rows: list[list]) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.append(["Anbar", "Model", "Siyahıda", "Qalıq", "Fərq"])
    for r in rows:
        ws.append(r)
    path = tmp_path / "out.xlsx"
    wb.save(path)
    return path


def rows_for(truth: list[dict]) -> list[list]:
    return [[t["anbar"], t["model"], t["siyahida"], t["qaliq"], t["ferq"]] for t in truth]


def test_correct_table_passes(tmp_path: Path) -> None:
    _, _, truth = build()
    assert check_tc(table(tmp_path, rows_for(truth)), truth) == []


def test_case_and_dotted_i_do_not_matter(tmp_path: Path) -> None:
    _, _, truth = build()
    rows = [[r[0].upper(), r[1].lower(), *r[2:]] for r in rows_for(truth)]
    assert check_tc(table(tmp_path, rows), truth) == []


def test_missing_extra_and_wrong_numbers_are_reported(tmp_path: Path) -> None:
    _, _, truth = build()
    rows = rows_for(truth)
    missing = rows[0]
    rows = rows[1:]
    rows[0] = [rows[0][0], rows[0][1], 99, 98, 1]
    planted = {(t["anbar"], t["model"]) for t in truth}
    extra = next((w, m) for w in WAREHOUSES for m in MODELS if (w, m) not in planted)
    rows.append([extra[0], extra[1], 2, 2, 0])
    problems = check_tc(table(tmp_path, rows), truth)
    assert f"missing mismatch: {missing[0]} / {missing[1]}" in problems
    assert any(p.startswith("wrong numbers for") for p in problems)
    assert f"not a mismatch: {extra[0]} / {extra[1]}" in problems
```

Run: `uv run pytest tests/evals -q --tb=short`
Expected: FAIL (`No module named 'evals'`).

- [ ] **Step 3: Implement `fixtures/generate.py`**

`fixtures/__init__.py`, `evals/__init__.py` and `evals/checks/__init__.py` are empty.

```python
"""Seeded synthetic fixtures (SPEC §7.3). M1: the T-c pair, a device list and the warehouse
stock with planted mismatches. Ground truth goes OUTSIDE the user's workspace, or the agent
could read the answer.
    uv run python -m fixtures.generate <files_dir> <truth.json>"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from openpyxl import Workbook

SEED = 20261009
MODELS = ["FMB003", "FMB140", "FMB920", "FMC130", "FMC650"]
WAREHOUSES = ["Bakı mərkəzi anbarı", "Gəncə anbarı", "Sumqayıt anbarı"]
N_MISMATCHES = 5


def build(seed: int = SEED) -> tuple[list[list], list[list], list[dict]]:
    rng = random.Random(seed)
    counts: dict[tuple[str, str], int] = {}
    devices: list[list] = []
    imeis: set[str] = set()
    for wh in WAREHOUSES:
        for model in MODELS:
            n = rng.randint(1, 4)
            counts[(wh, model)] = n
            for _ in range(n):
                imei = "35" + "".join(str(rng.randint(0, 9)) for _ in range(13))
                while imei in imeis:
                    imei = "35" + "".join(str(rng.randint(0, 9)) for _ in range(13))
                imeis.add(imei)
                devices.append([imei, model, wh, "anbarda"])
    rng.shuffle(devices)
    stock = dict(counts)
    truth = []
    for wh, model in sorted(rng.sample(sorted(counts), N_MISMATCHES)):
        delta = rng.choice([-2, -1, 1, 2])
        if counts[(wh, model)] + delta < 0:
            delta = -delta
        stock[(wh, model)] = counts[(wh, model)] + delta
        truth.append(
            {
                "anbar": wh,
                "model": model,
                "siyahida": counts[(wh, model)],
                "qaliq": stock[(wh, model)],
                "ferq": delta,
            }
        )
    device_rows = [["IMEI", "Model", "Anbar", "Status"], *devices]
    stock_rows = [["Anbar", "Model", "Qalıq"], *([w, m, stock[(w, m)]] for w, m in sorted(stock))]
    return device_rows, stock_rows, truth


def _save(path: Path, title: str, rows: list[list]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = title
    for row in rows:
        ws.append(row)
    wb.save(path)


def write(files_dir: Path, truth_path: Path, seed: int = SEED) -> None:
    devices, stock, truth = build(seed)
    files_dir.mkdir(parents=True, exist_ok=True)
    truth_path.parent.mkdir(parents=True, exist_ok=True)
    _save(files_dir / "cihazlar.xlsx", "Cihazlar", devices)
    _save(files_dir / "anbar_qaliqlari.xlsx", "Qalıqlar", stock)
    truth_path.write_text(json.dumps(truth, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python -m fixtures.generate <files_dir> <truth.json>")
    write(Path(sys.argv[1]), Path(sys.argv[2]))
```

- [ ] **Step 4: Implement `evals/checks/tc.py`**

```python
"""Deterministic T-c check (SPEC §15.1, T2): does an agent-made xlsx list exactly the planted
mismatches with the right numbers? Layout-agnostic: a row belongs to a (warehouse, model) pair
when exactly one warehouse name and one model name appear in its text cells.
    uv run python -m evals.checks.tc <xlsx> <truth.json>"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from openpyxl import load_workbook

from fixtures.generate import MODELS, WAREHOUSES
from usta.lang import az_casefold


def _rows(path: Path) -> list[tuple[str, set[float]]]:
    wb = load_workbook(path, read_only=True, data_only=True)
    rows = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            text = " | ".join(az_casefold(v) for v in row if isinstance(v, str))
            nums = {
                float(v) for v in row if isinstance(v, int | float) and not isinstance(v, bool)
            }
            rows.append((text, nums))
    wb.close()
    return rows


def check_tc(
    xlsx: Path,
    truth: list[dict],
    warehouses: list[str] = WAREHOUSES,
    models: list[str] = MODELS,
) -> list[str]:
    found: dict[tuple[str, str], list[set[float]]] = {}
    for text, nums in _rows(xlsx):
        whs = [w for w in warehouses if az_casefold(w) in text]
        ms = [m for m in models if az_casefold(m) in text]
        if len(whs) == 1 and len(ms) == 1:
            found.setdefault((whs[0], ms[0]), []).append(nums)
    expected = {(t["anbar"], t["model"]): t for t in truth}
    problems = []
    for key, t in expected.items():
        if key not in found:
            problems.append(f"missing mismatch: {key[0]} / {key[1]}")
        elif not any({float(t["siyahida"]), float(t["qaliq"])} <= nums for nums in found[key]):
            problems.append(
                f"wrong numbers for {key[0]} / {key[1]}: expected list {t['siyahida']} "
                f"and stock {t['qaliq']}"
            )
    for key in sorted(set(found) - set(expected)):
        problems.append(f"not a mismatch: {key[0]} / {key[1]}")
    return problems


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python -m evals.checks.tc <xlsx> <truth.json>")
    issues = check_tc(Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")))
    print("\n".join(issues) or "T-c check passed")
    sys.exit(1 if issues else 0)
```

- [ ] **Step 5: Run and commit**

```bash
uv run pytest tests/evals -q --tb=short
uv run ruff format . && uv run ruff check . && uv run lint-imports && uv run pytest -q --tb=short
git add fixtures evals tests/evals
git commit -m "feat(evals): seeded T-c fixtures and a deterministic mismatch checker"
```

---

### Task 14: M1 proof run and docs (controller-run, like M0 Task 15)

**Files:**
- Create: `scripts/m1_proof.sh`, `docs/milestones/m1-proof.md`
- Modify: `SPEC.md` (§7.1 check.py bullet, §20), `docs/adr/ADR-024-sandbox-lifecycle.md`, `docs/adr/ADR-026-skills.md`, `docs/adr/ADR-005-linux-first-gvisor.md`, this plan (Done Criteria ticks)

This task spends real model quota. The controller runs Steps 2–4 itself. A subagent may do Steps 1, 5 and 6.

- [ ] **Step 1: Write `scripts/m1_proof.sh`**

```bash
#!/usr/bin/env bash
# M1 proof (SPEC §16): T-c-style task on a real model; correct xlsx + PDF passing checks.
# Usage: scripts/m1_proof.sh [profile]   (default dev-openai). Loads .env without printing it.
set -euo pipefail
cd "$(dirname "$0")/.."
PROFILE="${1:-dev-openai}"
set -a; source .env; set +a
export USTA_PROFILE="$PROFILE" USTA_USER=m1proof
export USTA_GVISOR_RUNTIME="${USTA_GVISOR_RUNTIME:-runsc-kvm}"
TRUTH="$(mktemp -d)/ground_truth.json"
uv run usta user m1proof --name "M1 proof" || true  # already exists on a re-run
uv run python -m fixtures.generate "workspaces/m1proof/files" "$TRUTH"
TASK="Bu Excel faylındakı cihaz siyahısını (files/cihazlar.xlsx) anbar qalıqları ilə \
(files/anbar_qaliqlari.xlsx) müqayisə et və uyğunsuzluqları cədvəldə göstər. Cədvəli \
out/uygunsuzluqlar.xlsx faylına yaz və nəticəni PDF hesabat kimi də hazırla."
uv run usta run "$TASK" | tee /dev/stderr | grep -oE '▶ run [0-9a-f-]+' | awk '{print $3}' > .m1_run_id
RUN_ID="$(cat .m1_run_id)"; rm -f .m1_run_id
OUT="workspaces/m1proof/runs/$RUN_ID/out"
ls -la "$OUT"
XLSX="$(find "$OUT" -name '*.xlsx' | head -n 1)"
uv run python -m evals.checks.tc "$XLSX" "$TRUTH"
echo "run: $RUN_ID  truth: $TRUTH"
```

`chmod +x scripts/m1_proof.sh`. If `usta user` exits non-zero for an existing user, keep `|| true`. If `usta run` prints the run id differently, adapt the `grep` to the actual `▶ run <id>` line from `format_event`.

- [ ] **Step 2: Preconditions**

```bash
scripts/build_sandbox_image.sh
USTA_TEST_SANDBOX_RUNTIME=runsc-kvm uv run pytest -m sandbox -q --tb=short
uv run pytest -q --tb=short
```

All must pass. `docker compose -f deploy/compose.dev.yml up -d` must be running, and the DB migrated (`uv run alembic upgrade head` with `.env` loaded).

- [ ] **Step 3: The live run**

```bash
scripts/m1_proof.sh dev-openai 2>&1 | tee /tmp/m1-proof.log
```

Pass means all of:
- the run ends with `■ done` and a `✓ verified` line;
- `out/` holds an `.xlsx` and a `.pdf`;
- the verifier's check.py results for both are ok (visible as `verified` with no file reasons);
- `T-c check passed`.

If `gpt-6-luna` fails, there is one fallback run with `scripts/m1_proof.sh dev-api`. Record both attempts with their stop reasons and costs. Do not loop on retries.

- [ ] **Step 4: Evidence from the database**

Pull the run's cost, its turns, the `model_calls` count, and the `tool_calls` tools in order, with `psql` or a short `uv run python` snippet. Then open the PDF and confirm by eye that `ə ğ ı ş İ` render (screenshot optional).

- [ ] **Step 5: Write `docs/milestones/m1-proof.md`**

Include:
- the command;
- the CLI transcript, trimmed of nothing secret (it holds no keys);
- run id, model, turns, cost, and verification events;
- the `ls` of `out/`;
- the `T-c check passed` line;
- local T3a results on `runsc-kvm` and the CI link for the `t3a` job;
- whether the fallback was needed.

- [ ] **Step 6: Spec and ADR updates**

- **SPEC §7.1:** replace "Every output skill has `check.py` (page count, totals match source, glyph coverage, output language). These are the verifier's first-stage checks." with: "Every output skill has `check.py` (the file opens, has content, glyph coverage), printing `{ok, reasons, text_sample}`; the host runs `langcheck` on PDF/DOCX text samples and the final answer. These are the verifier's first-stage checks. Task-specific facts (totals match the source) are T2 checks against fixture ground truth."
- **SPEC §20:** correct item 2's cost note to the measured value. Add "M1 proof recorded in `docs/milestones/m1-proof.md`."
- **ADR-024:** add a "## Implementation (M1)" section covering:
  - the Docker CLI driver;
  - inner `timeout --kill-after=2` and outer +10 s (container destroyed);
  - container naming and labels, release on park/finish, reap on recover;
  - host uid:gid, and `HOME`/`MPLCONFIGDIR` under `/tmp`;
  - the 200 MB `out/` cap checked after each call.
- **ADR-026:** note that the frontmatter is limited to `name` and `description`, and state the `check.py` JSON contract.
- **ADR-005:** dev uses `USTA_GVISOR_RUNTIME=runsc-kvm`; CI uses `runsc` (systrap) on GitHub VMs.
- **This plan:** tick the Done Criteria below.

- [ ] **Step 7: Commit and push**

```bash
git add scripts/m1_proof.sh docs SPEC.md
git commit -m "docs(m1): proof run, spec and ADR updates"
git push
```

---

## M1 Done Criteria (SPEC §16)

- [x] CI is green on GitHub: `gitleaks`, `t1` (ruff, lint-imports, pytest on Postgres) and `t3a` (real gVisor, Trivy). Run https://github.com/Farizakb/usta/actions/runs/38256976086 on f1a3865: green.
- [x] T3a is 100%: every test in `tests/sandbox/test_escapes.py` passes in CI (`runsc`) and locally (`runsc-kvm`). Local `runsc-kvm` sandbox suite: 38 passed.
- [x] A T-c-style task on a real model ends `done` and verified. Its xlsx and PDF pass `check.py`, and `evals.checks.tc` reports no problems (Task 14). Run `deafd444` on `dev-openai`: 13 turns, $0.0026, `T-c check passed` (`docs/milestones/m1-proof.md`).
- [x] The final whole-branch review is approved (Opus: approved with fixes; the fixes landed in 1dfa934–61e0b4b; the scoped re-review is clean).
- [x] Evidence report: the files changed, the commands run, the test counts (default, `-m sandbox`), the CI link and the proof transcript. Known limitations are listed below. See `docs/milestones/m1-proof.md` (default 335 passed, sandbox 39 passed on `runsc-kvm`).

## Known Limitations Carried Out of M1

- The verifier runs where the engine would finish. A crash between the model's final reply and the checkpoint resumes with an assistant-last history (the same pre-existing pattern as M0's final replies).
- Each process tracks its started containers itself. Two processes on one run would fight over its container. This is the same cross-process gap as the M0 lease limitation.
- `check.py` glyph coverage relies on font names (no base-14) and `(cid:…)`/U+FFFD markers. It does not read embedded font cmaps.
- The DOCX font is Arial, so coverage depends on the viewer's font set.
- The `out/` cap is checked after each call. Within one call, `/out` (a bind mount) has no quota beyond the disk; `/tmp` is limited to 256 MB.
- `langcheck` reads only the first 4,000 characters of each file's text.
- The verifier always runs on `main`. The `main` vs `light` comparison is M3 (SPEC §9 item 4).
- gVisor cuts a single stdout write over 64 KiB through `docker exec` to 65536 bytes with exit 0, and `truncated` is not set. Programs should write in smaller chunks; output is capped at 5,000 characters per stream anyway.
- `code_exec` streams are cut at 5,000 characters each, until layer-1 offload (M3).
- The T-c checker matches warehouse and model names verbatim (casefolded). An agent that abbreviates names fails the check.
- `company-glossary` and `email-reply-style` are not built, and the promotion-rule script (SPEC §7) is not in M1.
- The Trivy scan runs only in CI, not before a local build.
- LiteLLM prints its "Provider List" help banner on stderr several times per call for `gpt-6-luna` (its cost lookup does not know the model). This is cosmetic noise; costs come from `config/models.toml`.
- There is one container start per run (about 0.6 s) and one matplotlib font-cache build per run (about 1–3 s, on the first chart).
