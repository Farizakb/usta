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
