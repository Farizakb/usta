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
    assert meta == {
        "name": "pdf-report",
        "description": "Build PDF reports with Azerbaijani-safe fonts.",
    }
    assert body.startswith("# pdf-report") and "build_pdf" in body


def test_quoted_values_are_unquoted() -> None:
    meta, _ = parse_skill_md("---\nname: \"xlsx\"\ndescription: 'Excel: tables'\n---\nb", "x")
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
