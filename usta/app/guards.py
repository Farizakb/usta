"""Startup guards (SPEC §5.1): P4, P7, P8, ADR-021. Every problem is listed, then startup stops."""

from collections.abc import Mapping

from usta.app.config import Profile
from usta.core.errors import ConfigError
from usta.models.caps import ModelEntry


def validate_startup(
    profile: Profile, catalog: Mapping[str, ModelEntry], env: Mapping[str, str]
) -> None:
    problems: list[str] = []
    is_test = profile.name == "test"

    if "main" not in profile.roles:
        problems.append("profile has no main role")
    if not is_test and profile.sandbox == "docker_hardened":
        problems.append("P8: the docker_hardened sandbox is allowed only in the test profile")
    if not profile.multi_user and profile.bind != "127.0.0.1":
        problems.append(f"single-user profiles must bind 127.0.0.1, not {profile.bind}")
    if profile.name == "dev-sub":
        if env.get("ANTHROPIC_API_KEY"):
            problems.append(
                "P4: dev-sub runs on the Claude subscription; unset ANTHROPIC_API_KEY "
                "(it would override the subscription login)"
            )
        if profile.multi_user:
            problems.append("P4: dev-sub is single-user only")

    for role, rc in profile.roles.items():
        entry = catalog.get(rc.model)
        if entry is None:
            problems.append(
                f"P7: role {role}: model {rc.model!r} has no entry (caps + price) in models.toml"
            )
            continue
        if not entry.native_tools:
            problems.append(f"ADR-021: role {role}: model {rc.model!r} has no native tool calling")
        if entry.adapter == "fake" and not is_test:
            problems.append(f"P8: role {role}: the fake model is allowed only in the test profile")
    for role, rc in profile.roles.items():
        if rc.api_key_env and not env.get(rc.api_key_env):
            problems.append(f"role {role}: environment variable {rc.api_key_env} is not set")

    if problems:
        raise ConfigError("startup refused:\n- " + "\n- ".join(problems))
