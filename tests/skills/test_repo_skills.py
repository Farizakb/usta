from pathlib import Path

from usta.skills import load_skills


def test_repo_skills_load_and_have_check_scripts() -> None:
    skills = load_skills(Path("skills"))
    for name in ("charts", "docx", "pdf-report", "xlsx"):
        skill = skills.get(name)
        assert skill is not None, name
        assert (skill.dir / "check.py").is_file()
        assert (skill.dir / "scripts").is_dir()
        assert f"/skills/{name}/scripts" in skill.body


def test_repo_has_exactly_the_m1_skills() -> None:
    assert load_skills(Path("skills")).names() == ["charts", "docx", "pdf-report", "xlsx"]
