"""Composition root: the only module that knows concrete adapters (P5)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from usta.app.config import Profile, RoleConfig, Settings, load_profile
from usta.app.guards import validate_startup
from usta.core.budget import Budget
from usta.core.errors import ConfigError
from usta.core.model import Role
from usta.engines.own.loop import OwnEngine
from usta.models.caps import ModelEntry, load_catalog
from usta.models.fake import FakeModel
from usta.models.gateway import Gateway
from usta.ports import ModelPort, RunContext
from usta.store.pg import PgRunStore
from usta.tools.builtin import builtin_tools
from usta.tools.pipeline import ToolPipeline
from usta.tools.registry import ToolRegistry
from usta.worker import EventCallback, Worker


@dataclass
class App:
    profile: Profile
    db: AsyncEngine
    store: PgRunStore
    worker: Worker

    async def aclose(self) -> None:
        await self.db.dispose()


def build_model(
    model_id: str, entry: ModelEntry, rc: RoleConfig, env: Mapping[str, str]
) -> ModelPort:
    key = env.get(rc.api_key_env) if rc.api_key_env else None
    if entry.adapter == "anthropic":
        from usta.models.anthropic_adapter import AnthropicModel

        return AnthropicModel(
            model_id,
            entry.caps,
            api_key=key or "",
            max_output_tokens=rc.max_output_tokens,
            effort=rc.effort,
            api_base=rc.api_base,
        )
    if entry.adapter == "litellm":
        from usta.models.litellm_adapter import LiteLLMModel  # litellm loads only when used

        return LiteLLMModel(
            model_id,
            entry.caps,
            api_key=key,
            max_output_tokens=rc.max_output_tokens,
            api_base=rc.api_base,
            effort=rc.effort,
        )
    return FakeModel(model_id=model_id, caps=entry.caps)  # guards allow this only in `test`


async def build_app(
    settings: Settings,
    *,
    env: Mapping[str, str] = os.environ,
    model_overrides: Mapping[Role, ModelPort] | None = None,
    on_event: EventCallback | None = None,
) -> App:
    profile = load_profile(settings.profile, settings.config_dir)
    catalog = load_catalog(settings.config_dir / "models.toml")
    validate_startup(profile, catalog, env)
    if profile.engine != "own":
        raise ConfigError("engine=sdk arrives in M3; use an engine=own profile")
    if model_overrides and profile.name != "test":
        raise ConfigError("P8: model overrides are allowed only in the test profile")

    overrides = model_overrides or {}
    models: dict[Role, ModelPort] = {
        role: overrides.get(role) or build_model(rc.model, catalog[rc.model], rc, env)
        for role, rc in profile.roles.items()
    }
    unknown = sorted({m.model_id for m in models.values()} - catalog.keys())
    if unknown:
        raise ConfigError(f"P7: no catalog entry for {unknown}")

    db = create_async_engine(settings.database_url, pool_pre_ping=True)
    store = PgRunStore(db, profile=profile.name)
    gateway = Gateway(
        models, {m.model_id: catalog[m.model_id].price for m in models.values()}, audit=store
    )
    pipeline = ToolPipeline(
        ToolRegistry(builtin_tools()), audit=store, workspace_root=settings.workspace_root
    )
    b = profile.budget
    budget = Budget(
        max_turns=b.max_turns,
        cost_step_usd=b.cost_cap_usd,
        max_active_seconds=b.max_active_seconds,
    )
    worker = Worker(
        store,
        OwnEngine(budget),
        RunContext(models=gateway, tools=pipeline, store=store),
        budget,
        engine_name="own",
        user_monthly_cap_usd=b.user_monthly_cap_usd,
        on_event=on_event,
    )
    return App(profile=profile, db=db, store=store, worker=worker)
