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
    assert not result.ok and "check.py exited 1: Traceback: boom" in result.reasons[0]


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


@pytest.mark.parametrize("code", [1, 2])
async def test_nonzero_exit_fails_even_with_ok_json(tmp_path: Path, code: int) -> None:
    ok_json = check_json(True, sample="x").stdout
    v, run, out, _, model = make(
        tmp_path, [], lambda *_: ExecResult(exit_code=code, stdout=ok_json, stderr="usage")
    )
    (out / "a.xlsx").write_bytes(b"x")
    result = await v.check(run)
    assert not result.ok and model.requests == []
    assert f"check.py exited {code}" in result.reasons[0]


@pytest.mark.parametrize(
    "stdout",
    ['{"ok": "false", "reasons": [], "text_sample": ""}', '{"ok": true, "reasons": "x"}'],
)
async def test_non_strict_check_output_is_unparseable(tmp_path: Path, stdout: str) -> None:
    v, run, out, _, _ = make(
        tmp_path, [], lambda *_: ExecResult(exit_code=0, stdout=stdout + "\n", stderr="")
    )
    (out / "a.xlsx").write_bytes(b"x")
    result = await v.check(run)
    assert not result.ok and "check.py output unparseable" in result.reasons[0]


async def test_english_task_expects_english(tmp_path: Path) -> None:
    v, run, _, _, _ = make(tmp_path, [reply('{"verdict": "pass"}')])
    run.task = "Show the mismatches between the warehouse and the invoices"
    run.messages[-1] = Message(role="assistant", content=(TextBlock(text=EN_ANSWER),))
    assert (await v.check(run)).ok


async def test_too_many_output_files_fail_without_running_the_checks(tmp_path: Path) -> None:
    v, run, out, sandbox, model = make(tmp_path, [])
    for i in range(21):
        (out / f"f{i:02d}.xlsx").write_bytes(b"x")
    result = await v.check(run)
    assert not result.ok and sandbox.calls == [] and model.requests == []
    assert "too many output files to verify (21 > 20)" in result.reasons[0]
    assert len(result.files) == 1 and not result.files[0].ok


async def test_twenty_output_files_are_still_checked(tmp_path: Path) -> None:
    v, run, out, sandbox, _ = make(
        tmp_path, [reply('{"verdict": "pass"}')], lambda *_: check_json(True)
    )
    for i in range(20):
        (out / f"f{i:02d}.xlsx").write_bytes(b"x")
    assert (await v.check(run)).ok and len(sandbox.calls) == 20
