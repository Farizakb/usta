"""Settings from the environment and named profiles from config/profiles/*.toml (SPEC §5.1)."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from usta.core.errors import ConfigError
from usta.core.model import Role


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="USTA_", extra="ignore")

    profile: str
    database_url: str
    user: str = ""
    config_dir: Path = Path("config")
    workspace_root: Path = Path("workspaces")


class RoleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str
    api_key_env: str | None = None
    api_base: str | None = None
    max_output_tokens: int = 8192
    effort: str | None = None


class BudgetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_turns: int = 40
    cost_cap_usd: float = 0.50
    max_active_seconds: float = 1200.0
    user_monthly_cap_usd: float = 10.0


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    engine: Literal["own", "sdk"]
    sandbox: Literal["gvisor", "docker_hardened"]
    bind: str = "127.0.0.1"
    multi_user: bool = False
    roles: dict[Role, RoleConfig]
    budget: BudgetConfig = Field(default_factory=BudgetConfig)


def load_profile(name: str, config_dir: Path) -> Profile:
    path = config_dir / "profiles" / f"{name}.toml"
    if not path.is_file():
        raise ConfigError(f"unknown profile {name!r}: {path} not found")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    try:
        return Profile.model_validate({"name": name, **data})
    except ValidationError as e:
        raise ConfigError(f"{path}: {e}") from e
