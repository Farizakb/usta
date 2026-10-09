from pathlib import Path

import pytest

from usta.core.errors import ConfigError
from usta.core.model import Usage
from usta.models.caps import load_catalog
from usta.models.pricing import Price, cost_usd


def test_cost_counts_all_four_token_kinds() -> None:
    price = Price(input=2.0, output=10.0, cache_read=0.2, cache_write=2.5)
    usage = Usage(
        input_tokens=1_000, output_tokens=500, cache_read_tokens=10_000, cache_write_tokens=2_000
    )
    assert cost_usd(usage, price) == pytest.approx((2_000 + 5_000 + 2_000 + 5_000) / 1_000_000)


def test_shipped_catalog_has_caps_and_price_for_every_model() -> None:
    catalog = load_catalog(Path("config/models.toml"))
    assert {
        "claude-sonnet-5-5",
        "claude-haiku-4-5",
        "gemini/gemini-2.5-flash",
        "openai/gpt-6-luna",
        "fake-model",
    } <= catalog.keys()
    sonnet = catalog["claude-sonnet-5-5"]
    assert sonnet.adapter == "anthropic"
    assert (sonnet.caps.context_tokens, sonnet.caps.max_output_tokens) == (1_000_000, 128_000)
    assert sonnet.price == Price(input=2.0, output=10.0, cache_read=0.2, cache_write=2.5)
    assert catalog["fake-model"].adapter == "fake"


def test_entry_without_price_is_a_config_error(tmp_path: Path) -> None:
    bad = tmp_path / "models.toml"
    bad.write_text(
        '[models."x"]\nadapter = "litellm"\ncontext_tokens = 1\nmax_output_tokens = 1\n'
        'prompt_cache = "none"\nparallel_tool_calls = false\nnative_tools = true\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="'x'"):
        load_catalog(bad)
