# M1 Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix five defects that the 2026-10-14 review of M0 and M1 on `main` (`2e6748c..origin/main`) found: the verifier can be forged, `file.search` misses ASCII `I`, the monthly cap is skipped on budget approval, empty assistant turns cause a 400, and `xlsx/check.py` misses formula errors.

**Architecture:** Each fix stays inside the module that owns the defect. There are no new modules, ports, dependencies or schema changes. Each task has its own red/green test cycle and its own commit.

**Tech Stack:** Python 3.12, uv, pytest (asyncio), openpyxl inside the `usta-sandbox:1` image, Docker + gVisor for `-m sandbox` tests.

**Spec:** `SPEC.md` v1.0: §7 Tools (the `file.search` row, line 306), §7.1 Skills, §9 Verifier, §10 Sandbox, and the budget/cost-cap rules. The M1 plan (`docs/plans/2026-10-09-m1-tools-sandbox.md`) describes the code being fixed.

**Where to run:** WSL2 Ubuntu, `~/code/usta`. Create a branch from the merged main: `git fetch origin && git switch -c m1-review-fixes origin/main`. For local sandbox tests, `export USTA_TEST_SANDBOX_RUNTIME=runsc-kvm`, which is about 10× faster than `runsc`.

## Global Constraints

- No new, bumped or deduplicated dependencies. No DB schema or migration changes.
- Files are UTF-8 without BOM. The test data contains Azerbaijani text.
- Gates before each commit: `uv run ruff format --check .`, `uv run ruff check .`, `uv run lint-imports` and `uv run pytest -q --tb=short`. Tasks 1 and 5 also need `uv run pytest -q --tb=short -m sandbox`.
- Stage files by explicit path only. Never stage `.env.example`, `.env`, `BLUEPRINT.md` or `az_token_benchmark.py`. Never use `--no-verify`.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- P8: no silent fallback may pass as a real result. A check that cannot judge something must fail it, not pass it.

## Decisions (made while planning; the user can override them at review)

1. **#1:** check processes run with `python -I` (isolated mode, which implies `-E -s -P`). This ignores the user site, `.pth` files, `PYTHON*` env vars, and the script dir and cwd on `sys.path`. The checks import only the stdlib and installed packages, so nothing they need is lost. A separate fresh container for checks would isolate more, but it costs a cold start per check and is out of scope.
2. **#5:** `file.search` treats `i ı I İ` as the same letter. Search is a recall tool: a false hit costs one wasted read, while a miss makes the model decide that data does not exist. `az_casefold` itself is not changed, because language detection uses it. The M1 test `test_search_dotless_i_does_not_match_dotted` pins the old behaviour and is replaced.
3. **#6:** when the user approves more budget after the monthly cap is reached, `answer_budget` raises `UserBudgetExceeded`, the same error `submit` raises. The run stays parked, and the user can still decline or cancel it. The worker does not finish the run on the user's behalf.
4. **#2:** both adapters send an assistant turn that would have empty content as the placeholder text `(empty reply)`. They do not drop the turn, which would break the user/assistant alternation and lose the record that the model answered empty.
5. **#4:** `xlsx/check.py` fails any formula cell, because the sandbox has no formula engine and an unevaluated formula cannot be verified. SKILL.md already shows writing computed values; it now says so explicitly. Cost: users get static values, not live formulas, until a formula engine is added.

## Review Focus

1. A `.pth` file planted in the user site must not run during a check, just like `usercustomize.py`. Pinned in Task 1.
2. Every skill's `check.py` must still pass good files under `-I`. Pinned in Task 1: `Box.check` uses the production argv, so all existing sandbox skill tests run under `-I`.
3. A query typed with `ı` must still find text written with `i` or `I`. Pinned in Task 2.
4. Declining the budget question must keep working after the monthly cap is hit. Pinned in Task 3.
5. An assistant turn with tool calls and no text must stay unchanged on the wire, with no placeholder. Pinned in Task 4.

---

### Task 1: Isolated check processes in the verifier (#1)

**Files:**
- Modify: `usta/verify/verifier.py` (the argv in `_check_file`, about line 117)
- Modify: `tests/conftest.py:108-113` (`Box.check`)
- Modify: `tests/verify/test_verifier.py:68` (argv assertion)
- Test: `tests/sandbox/test_escapes.py` (new test at the end)

**Interfaces:**
- Produces: `usta.verify.verifier.check_argv(skill: str, rel: str) -> tuple[str, ...]`, which returns `("python", "-I", f"/skills/{skill}/check.py", f"/out/{rel}")`. Task 5 relies on `Box.check` going through it.

- [ ] **Step 1: Write the failing tests**

In `tests/verify/test_verifier.py`, `test_failed_file_check_skips_the_llm`, change the assertion to:

```python
        assert argv == ("python", "-I", "/skills/pdf-report/check.py", "/out/hesabat.pdf")
```

In `tests/conftest.py`, add `from usta.verify.verifier import check_argv` to the imports and make `Box.check` use the production argv:

```python
    async def check(self, skill: str, rel: str) -> dict:
        res = await self.sandbox.exec(self.run_id, self.dirs, check_argv(skill, rel))
        assert res.exit_code == 0, res.stderr
        return json.loads(res.stdout.strip().splitlines()[-1])
```

Append to `tests/sandbox/test_escapes.py`. Match the file's existing imports and fixtures; it uses `box: Box` like `tests/skills`.

```python
FORGE = r'''
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
'''


async def test_agent_cannot_forge_a_check_verdict(box: Box) -> None:
    assert (await box.run(FORGE)).exit_code == 0
    result = await box.check("xlsx", "bad.xlsx")
    assert result["ok"] is False
    assert any("cannot read workbook" in r for r in result["reasons"])
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `uv run pytest -q --tb=short tests/verify/test_verifier.py tests/sandbox/test_escapes.py -m "sandbox or not sandbox"`
Expected: collection fails with `ImportError: cannot import name 'check_argv'`.

- [ ] **Step 3: Add `check_argv` without `-I`, to see the real red**

In `usta/verify/verifier.py`, at module level near the other constants:

```python
def check_argv(skill: str, rel: str) -> tuple[str, ...]:
    return ("python", f"/skills/{skill}/check.py", f"/out/{rel}")
```

In `_check_file`, replace the inline tuple with `check_argv(skill, rel)`.

Run the same command again.
Expected: two failures. `test_failed_file_check_skips_the_llm` fails because the argv has no `-I`. `test_agent_cannot_forge_a_check_verdict` fails because `result["ok"] is True`: the forged verdict wins.

- [ ] **Step 4: Implement the fix**

```python
def check_argv(skill: str, rel: str) -> tuple[str, ...]:
    # -I: no user site, .pth, PYTHON* env or script dir on sys.path. /tmp (HOME) is writable
    # by the agent's code for the whole run, so a planted usercustomize.py would forge verdicts.
    return ("python", "-I", f"/skills/{skill}/check.py", f"/out/{rel}")
```

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `uv run pytest -q --tb=short` and then `uv run pytest -q --tb=short -m sandbox`
Expected: both PASS. The sandbox run includes every `tests/skills` check test, now under `-I` (Review Focus 1 and 2).

- [ ] **Step 6: Commit**

```bash
git add usta/verify/verifier.py tests/conftest.py tests/verify/test_verifier.py tests/sandbox/test_escapes.py
git commit -m "fix(verify): run check.py with python -I so planted usercustomize/.pth cannot forge verdicts"
```

---

### Task 2: `file.search` matches every form of i (#5)

**Files:**
- Modify: `usta/tools/builtin/files.py:152-153` (`_search`), `:175` (match), `:256-259` (tool description)
- Modify: `SPEC.md:306` (`file.search` row)
- Test: `tests/tools/test_files.py:130-133` (replace `test_search_dotless_i_does_not_match_dotted`)

**Interfaces:**
- Produces: private `_search_fold(text: str) -> str` in `files.py`. Nothing outside the module uses it.

- [ ] **Step 1: Write the failing test**

Replace `test_search_dotless_i_does_not_match_dotted` in `tests/tools/test_files.py` with:

```python
async def test_search_treats_every_form_of_i_alike(ctx: ToolContext) -> None:
    (ctx.files_dir / "a.txt").write_text("IMEI;Model\nIŞIQ\nİstiqamət\n", encoding="utf-8")
    for query, line in [
        ("imei", 1),  # ASCII header: az_casefold alone maps I→ı and missed this
        ("ışıq", 2),
        ("işiq", 2),
        ("istiqamət", 3),
        ("ıstıqamət", 3),  # typed with ı, text has İ/i
    ]:
        out = (await FILE_SEARCH.fn({"query": query}, ctx)).content
        assert f"a.txt:{line}:" in out, query
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest -q --tb=short tests/tools/test_files.py -k every_form_of_i`
Expected: FAIL, `AssertionError: imei`.

- [ ] **Step 3: Implement the fix**

In `usta/tools/builtin/files.py`, above `_search`:

```python
def _search_fold(text: str) -> str:
    """az_casefold, then ı→i: search wants recall, so i ı I İ all match each other."""
    return az_casefold(text).replace("ı", "i")
```

In `_search`, use `needle = _search_fold(query)` and `if needle in _search_fold(line):`.

Change the `FILE_SEARCH` description to:

```python
    description=(
        "Find lines containing a text in UTF-8 text files under files/ or out/. "
        "Case-insensitive; i, ı, I and İ all match each other; plain text, not a regex."
    ),
```

In `SPEC.md:306`, change the cell `` `az_casefold` grep `` to `` `az_casefold` grep, i/ı/I/İ alike ``.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `uv run pytest -q --tb=short tests/tools/test_files.py`
Expected: PASS, including the unchanged `test_search_is_azerbaijani_case_insensitive`.

- [ ] **Step 5: Commit**

```bash
git add usta/tools/builtin/files.py tests/tools/test_files.py SPEC.md
git commit -m "fix(tools): file.search matches i/ı/I/İ alike so ASCII headers like IMEI are found"
```

---

### Task 3: Budget approval respects the monthly cap (#6)

**Files:**
- Modify: `usta/worker.py:89-110` (`answer_budget`)
- Test: `tests/test_worker.py` (two new tests after `test_budget_park_then_decline`)

**Interfaces:**
- Consumes: `RunStore.user_month_cost(user_id) -> float` and `UserBudgetExceeded`, which already exist.
- Produces: `answer_budget(run_id, approve=True)` raises `UserBudgetExceeded` when the month's spend is at or above `user_monthly_cap_usd`. The run is left parked and unchanged.

- [ ] **Step 1: Write the failing tests**

```python
async def test_budget_approval_refused_once_monthly_cap_is_spent(tmp_path: Path) -> None:
    script = [call("test.echo", {"text": str(i)}) for i in range(2)] + [reply("bitdi")]
    worker, store, _, _ = make_worker(script, tmp_path, cap=0.5)
    run = await worker.execute((await worker.submit("u1", "t")).id)
    assert run.status == RunStatus.AWAITING_USER
    assert await store.user_month_cost("u1") >= 0.5  # precondition: this run used the month
    with pytest.raises(UserBudgetExceeded):
        await worker.answer_budget(run.id, approve=True)
    after = await store.load(run.id)
    assert after.status == RunStatus.AWAITING_USER and after.cost_cap_usd == pytest.approx(0.5)


async def test_budget_decline_still_works_once_monthly_cap_is_spent(tmp_path: Path) -> None:
    script = [call("test.echo", {"text": str(i)}) for i in range(2)]
    worker, _, _, _ = make_worker(script, tmp_path, cap=0.5)
    run = await worker.execute((await worker.submit("u1", "t")).id)
    run = await worker.answer_budget(run.id, approve=False)
    assert run.stop_reason == StopReason.BUDGET_DECLINED
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `uv run pytest -q --tb=short tests/test_worker.py -k monthly_cap`
Expected: `test_budget_approval_refused_once_monthly_cap_is_spent` FAILS with `DID NOT RAISE`, and the decline test passes. If the precondition assert fails instead, the fake run spends less than 0.5. Lower `cap` to what `store.user_month_cost` reports after parking, and keep the precondition.

- [ ] **Step 3: Implement the fix**

In `answer_budget`, between the decline branch and `run.cost_cap_usd += ...`:

```python
            spent = await self._store.user_month_cost(run.user_id)
            if spent >= self._user_cap:  # same rule as submit(); the run stays parked
                raise UserBudgetExceeded(
                    f"user {run.user_id!r} has spent ${spent:.2f} of "
                    f"${self._user_cap:.2f} this month"
                )
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `uv run pytest -q --tb=short tests/test_worker.py tests/test_cli.py`
Expected: PASS. The CLI already turns `UstaError` into an error exit (`usta/cli.py:133`).

- [ ] **Step 5: Commit**

```bash
git add usta/worker.py tests/test_worker.py
git commit -m "fix(worker): budget approval re-checks the user's monthly cap"
```

---

### Task 4: Empty assistant turns get a placeholder on the wire (#2)

**Files:**
- Modify: `usta/core/messages.py` (add the constant)
- Modify: `usta/models/anthropic_adapter.py:97-118` (`_message`)
- Modify: `usta/models/litellm_adapter.py:108-110` (`_messages`, assistant branch)
- Test: `tests/models/test_anthropic_adapter.py`, `tests/models/test_litellm_adapter.py`

**Interfaces:**
- Produces: `usta.core.messages.EMPTY_REPLY = "(empty reply)"`.

- [ ] **Step 1: Write the failing tests**

`tests/models/test_anthropic_adapter.py` (add `TextBlock` to the `usta.core.messages` import):

```python
@pytest.mark.parametrize("content", [(), (TextBlock(text=""),)])
async def test_empty_assistant_turn_is_sent_as_placeholder(content: tuple) -> None:
    seen: dict = {}
    req = CONTRACT_REQUEST.model_copy(
        update={
            "messages": (
                Message.user_text("a"),
                Message(role="assistant", content=content),
                Message.user_text("b"),
            )
        }
    )
    await make_model(capture(seen)).complete(req)
    assert seen["body"]["messages"][1]["content"] == [{"type": "text", "text": "(empty reply)"}]
```

`tests/models/test_litellm_adapter.py`:

```python
async def test_empty_assistant_turn_is_sent_as_placeholder() -> None:
    fake = FakeCompletion(WIRE)
    req = CONTRACT_REQUEST.model_copy(
        update={
            "messages": (
                Message.user_text("a"),
                Message(role="assistant", content=()),
                Message.user_text("b"),
            )
        }
    )
    await make(fake).complete(req)
    assert fake.kwargs["messages"][2] == {"role": "assistant", "content": "(empty reply)"}


async def test_tool_call_turn_without_text_keeps_null_content() -> None:
    fake = FakeCompletion(WIRE)
    await make(fake).complete(CONTRACT_REQUEST)
    assert fake.kwargs["messages"][2]["content"] is None  # Review Focus 5
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `uv run pytest -q --tb=short tests/models -k "placeholder or null_content"`
Expected: both placeholder tests FAIL (Anthropic gets `[]`, LiteLLM gets `None`). `null_content` passes.

- [ ] **Step 3: Implement the fix**

`usta/core/messages.py`, after the imports:

```python
EMPTY_REPLY = "(empty reply)"  # sent for an assistant turn with no content; APIs reject empty turns
```

`anthropic_adapter.py`, `_message`, before `return`:

```python
    if not content and msg.role == "assistant":
        content.append({"type": "text", "text": EMPTY_REPLY})
```

`litellm_adapter.py`, assistant branch:

```python
        if m.role == "assistant":
            calls = m.tool_calls()
            msg: dict[str, Any] = {
                "role": "assistant",
                "content": m.text() or (None if calls else EMPTY_REPLY),
            }
            if calls:
```

In both adapters, import `EMPTY_REPLY` from `usta.core.messages`, alongside the existing imports from that module.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `uv run pytest -q --tb=short tests/models tests/engines`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add usta/core/messages.py usta/models/anthropic_adapter.py usta/models/litellm_adapter.py tests/models/test_anthropic_adapter.py tests/models/test_litellm_adapter.py
git commit -m "fix(models): send empty assistant turns as a placeholder instead of empty content"
```

---

### Task 5: `xlsx/check.py` fails unevaluated formulas (#4)

**Files:**
- Modify: `skills/xlsx/check.py:36-40`
- Modify: `skills/xlsx/SKILL.md:22-25`
- Test: `tests/skills/test_xlsx_docx.py` (new test after `test_xlsx_with_error_values_or_no_data_fails`)

**Interfaces:**
- Consumes: `Box.check`, which runs the production argv from Task 1.

- [ ] **Step 1: Write the failing test**

```python
async def test_xlsx_with_formulas_fails(box: Box) -> None:
    code = (
        "from openpyxl import Workbook\n"
        "wb = Workbook(); ws = wb.active\n"
        "ws.append(['Siyahıda', 'Qalıq', 'Nisbət']); ws.append([3, 0, '=A2/B2'])\n"
        "wb.save('/out/formul.xlsx')\n"
    )
    assert (await box.run(code)).exit_code == 0
    result = await box.check("xlsx", "formul.xlsx")
    assert not result["ok"]
    assert any("formula" in r and "C2" in r for r in result["reasons"])
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest -q --tb=short -m sandbox tests/skills/test_xlsx_docx.py -k formulas`
Expected: FAIL. `result["ok"]` is True, because the formula is skipped.

- [ ] **Step 3: Implement the fix**

`iter_rows(values_only=True)` gives no cell coordinates. Switch to cells; read-only mode supports this:

```python
                for row in ws.iter_rows():
                    cells = [c for c in row if c.value is not None and c.value != ""]
                    if not cells:
                        continue
                    if seen_header:
                        data_rows += 1
                    seen_header = True
                    for c in cells:
                        v = c.value
                        values += 1
                        if isinstance(v, str):
                            if v.strip().upper() in ERRORS:
                                reasons.append(f"sheet {ws.title!r} has an error value {v.strip()}")
                            elif v.startswith("="):
                                # no formula engine in the sandbox: an unevaluated formula
                                # cannot be checked (#DIV/0!, #REF!), so it fails (P8)
                                reasons.append(
                                    f"sheet {ws.title!r} cell {c.coordinate} has a formula; "
                                    "write computed values"
                                )
                            else:
                                texts.append(v)
```

`EmptyCell` objects in read-only mode have `value None` and are filtered out before `.coordinate` is read.

In `skills/xlsx/SKILL.md`, replace the last bullet with:

```markdown
- Write computed values, not formulas: compute in pandas, then write the numbers. The verifier cannot evaluate formulas, so any cell starting with `=` fails.
- The verifier runs `/skills/xlsx/check.py` on every `.xlsx` in `/out`. Empty workbooks, error values (`#REF!`, `#DIV/0!` ...) and formulas fail.
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `uv run pytest -q --tb=short -m sandbox tests/skills` and then `uv run pytest -q --tb=short`
Expected: PASS. The existing xlsx tests still pass; `test_corrupt_sheet_xml_keeps_json_contract` still gets JSON.

- [ ] **Step 5: Commit**

```bash
git add skills/xlsx/check.py skills/xlsx/SKILL.md tests/skills/test_xlsx_docx.py
git commit -m "fix(skills): xlsx check fails formula cells it cannot evaluate"
```

---

### Task 6: Record the deferred review findings

**Files:**
- Modify: `docs/plans/2026-10-09-m1-tools-sandbox.md` (section `## Known Limitations Carried Out of M1`, about line 4558)

- [ ] **Step 1: Append to the section**

```markdown
- **2026-10-14 review, deferred** (fixed items are in `docs/plans/2026-10-14-m1-review-fixes.md`):
  - M3: `usta/models/gateway.py:115` retries a 429 after a fixed 1 s, then 2 s, and ignores `Retry-After`. A short rate-limit burst ends the run as `provider_quota`.
  - M2: `code_exec._snapshot` and `Verifier._outputs` use `os.walk` without `onerror`. A `chmod 000` directory in `out/` escapes both the size cap and the checks.
  - M2: `usta/sandbox/docker.py:266` reports a timeout that escalated to SIGKILL (exit 137) as a plain non-zero exit, not as a timeout.
  - M2: `skills/pdf-report/scripts/usta_pdf.py:82` treats any string block ending in `.png` as an image path, so a paragraph ending in a file name crashes the build.
  - Already listed: a crash during verification makes resume send an assistant-last history (`loop.py:117`).
```

- [ ] **Step 2: Commit**

```bash
git add docs/plans/2026-10-09-m1-tools-sandbox.md
git commit -m "docs(m1): record deferred findings from the 2026-10-14 review"
```

---

## Done Criteria

- [ ] `uv run ruff format --check . && uv run ruff check . && uv run lint-imports` is clean.
- [ ] `uv run pytest -q --tb=short` passes; the count is the 335 baseline plus the new tests, minus the one replaced.
- [ ] `uv run pytest -q --tb=short -m sandbox` passes on `runsc-kvm` locally, and CI `t3a` (runsc) is green.
- [ ] Push `m1-review-fixes` and open a PR to `main`.
