from pathlib import Path

import pytest

from usta.app.config import Profile, RoleConfig, load_profile
from usta.app.guards import validate_startup
from usta.core.errors import ConfigError
from usta.models.caps import ModelEntry, load_catalog

CONFIG = Path("config")
CATALOG = load_catalog(CONFIG / "models.toml")


@pytest.mark.parametrize(
    ("name", "env"),
    [
        ("test", {}),
        ("dev-free", {"GEMINI_API_KEY": "k"}),
        ("dev-openai", {"OPENAI_API_KEY": "k"}),
        ("dev-api", {"ANTHROPIC_API_KEY": "k"}),
        ("dev-sub", {}),
        ("prod", {"ANTHROPIC_API_KEY": "k"}),
    ],
)
def test_shipped_profiles_pass_their_guards(name: str, env: dict) -> None:
    validate_startup(load_profile(name, CONFIG), CATALOG, env)


def test_dev_sub_refuses_an_api_key_p4() -> None:
    with pytest.raises(ConfigError, match="P4.*ANTHROPIC_API_KEY"):
        validate_startup(load_profile("dev-sub", CONFIG), CATALOG, {"ANTHROPIC_API_KEY": "sk"})


def test_fake_model_and_docker_hardened_only_in_test_p8() -> None:
    p = load_profile("test", CONFIG).model_copy(update={"name": "dev-free"})
    with pytest.raises(ConfigError) as info:
        validate_startup(p, CATALOG, {})
    assert "docker_hardened" in str(info.value) and "fake model" in str(info.value)


def test_missing_catalog_entry_and_missing_key_are_listed_together() -> None:
    p = load_profile("dev-free", CONFIG)
    p = p.model_copy(update={"roles": {**p.roles, "light": RoleConfig(model="unknown/model")}})
    with pytest.raises(ConfigError) as info:
        validate_startup(p, CATALOG, {})
    assert "P7" in str(info.value) and "GEMINI_API_KEY" in str(info.value)


def test_model_without_native_tools_is_refused() -> None:
    no_tools = CATALOG["fake-model"].model_copy(update={"native_tools": False})
    catalog: dict[str, ModelEntry] = {**CATALOG, "fake-model": no_tools}
    with pytest.raises(ConfigError, match="native tool"):
        validate_startup(load_profile("test", CONFIG), catalog, {})


def test_single_user_profile_must_bind_loopback() -> None:
    p = load_profile("dev-free", CONFIG).model_copy(update={"bind": "0.0.0.0"})
    with pytest.raises(ConfigError, match="127.0.0.1"):
        validate_startup(p, CATALOG, {"GEMINI_API_KEY": "k"})


def test_unknown_profile_and_typos_fail_loudly(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unknown profile"):
        load_profile("nope", CONFIG)
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "x.toml").write_text(
        'engine = "own"\nsandbox = "gvisor"\nsandbx = "typo"\n[roles.main]\nmodel = "fake-model"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="sandbx"):
        load_profile("x", tmp_path)


def test_profile_without_main_role_is_refused() -> None:
    p = Profile(
        name="t", engine="own", sandbox="gvisor", roles={"light": RoleConfig(model="fake-model")}
    )
    with pytest.raises(ConfigError, match="main role"):
        validate_startup(p, CATALOG, {})


def test_profile_file_cannot_rename_itself_p8(tmp_path: Path) -> None:
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "x.toml").write_text(
        'name = "test"\nengine = "own"\nsandbox = "docker_hardened"\n[roles.main]\nmodel = "fake-model"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="name"):
        load_profile("x", tmp_path)
