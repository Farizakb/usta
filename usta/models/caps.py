"""Model catalog loader: caps + price per model id, from config/models.toml."""

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from usta.core.errors import ConfigError
from usta.core.model import ModelCaps
from usta.models.pricing import Price


class ModelEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    adapter: Literal["anthropic", "litellm", "fake"]
    context_tokens: int
    max_output_tokens: int
    prompt_cache: Literal["explicit", "automatic", "none"]
    parallel_tool_calls: bool
    native_tools: bool
    price: Price

    @property
    def caps(self) -> ModelCaps:
        return ModelCaps(
            context_tokens=self.context_tokens,
            max_output_tokens=self.max_output_tokens,
            prompt_cache=self.prompt_cache,
            parallel_tool_calls=self.parallel_tool_calls,
            native_tools=self.native_tools,
        )


def load_catalog(path: Path) -> dict[str, ModelEntry]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    catalog: dict[str, ModelEntry] = {}
    for model_id, raw in data.get("models", {}).items():
        try:
            catalog[model_id] = ModelEntry.model_validate(raw)
        except ValidationError as e:
            raise ConfigError(f"{path}: model {model_id!r}: {e}") from e
    return catalog
