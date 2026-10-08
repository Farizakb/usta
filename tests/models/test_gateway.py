import asyncio

import pytest

from tests.fakes import FakeClock, InMemoryStore
from usta.core.errors import (
    ConfigError,
    ProviderQuotaError,
    ProviderRateLimited,
    ProviderUnavailable,
    TransientProviderError,
)
from usta.core.messages import Message
from usta.core.model import ModelRequest, SystemBlock, Usage
from usta.models.fake import DEFAULT_CAPS, FakeModel, reply
from usta.models.gateway import Gateway
from usta.models.pricing import Price

PRICE = Price(input=2.0, output=10.0, cache_read=0.2, cache_write=2.5)


def request(role: str = "main") -> ModelRequest:
    return ModelRequest(
        role=role,
        system=(SystemBlock(text="sys", cache=True),),
        messages=(Message.user_text("salam"),),
        prompt_version="p1",
        run_id="r1",
        user_id="u1",
    )


class Sleeps:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def make(script, **kw):
    store, sleeps, model = InMemoryStore(), Sleeps(), FakeModel(script)
    gw = Gateway({"main": model}, {"fake-model": PRICE}, audit=store, sleep=sleeps, **kw)
    return gw, model, store, sleeps


async def test_success_prices_the_call_and_logs_it() -> None:
    gw, _, store, _ = make([reply("ok", usage=Usage(input_tokens=1000, output_tokens=100))])
    resp = await gw.complete(request())
    assert resp.cost_usd == pytest.approx((1000 * 2 + 100 * 10) / 1_000_000)
    [rec] = store.model_calls
    assert (rec.run_id, rec.user_id, rec.role, rec.model, rec.prompt_version, rec.attempt) == (
        "r1",
        "u1",
        "main",
        "fake-model",
        "p1",
        1,
    )
    assert rec.cost_usd == resp.cost_usd and rec.error is None and rec.response is not None
    assert rec.request["messages"][0]["content"][0]["text"] == "salam"


async def test_transient_error_is_retried_with_backoff() -> None:
    gw, _, store, sleeps = make([TransientProviderError("503"), reply("ok")])
    assert (await gw.complete(request())).message.text() == "ok"
    assert sleeps.calls == [1.0]
    assert [r.error is None for r in store.model_calls] == [False, True]
    assert [r.attempt for r in store.model_calls] == [1, 2]


async def test_gives_up_after_max_attempts() -> None:
    gw, _, store, sleeps = make([TransientProviderError(x) for x in "abc"])
    with pytest.raises(TransientProviderError, match="c"):
        await gw.complete(request())
    assert sleeps.calls == [1.0, 2.0]
    assert len(store.model_calls) == 3


async def test_persistent_rate_limit_becomes_provider_quota() -> None:
    gw, *_ = make([ProviderRateLimited("429")] * 3)
    with pytest.raises(ProviderQuotaError):
        await gw.complete(request())


async def test_non_retryable_error_is_logged_and_raised_at_once() -> None:
    gw, _, store, sleeps = make([ProviderQuotaError("billing")])
    with pytest.raises(ProviderQuotaError):
        await gw.complete(request())
    assert sleeps.calls == []
    assert "billing" in (store.model_calls[0].error or "")


async def test_unexpected_exception_is_logged_then_raised() -> None:
    gw, _, store, _ = make([RuntimeError("bug")])
    with pytest.raises(RuntimeError):
        await gw.complete(request())
    assert store.model_calls[0].error == "RuntimeError: bug"


async def test_timeout_counts_as_transient() -> None:
    class Hanging:
        provider, model_id, caps = "hang", "fake-model", DEFAULT_CAPS

        async def complete(self, req: ModelRequest):
            await asyncio.sleep(10)

    store = InMemoryStore()
    gw = Gateway(
        {"main": Hanging()}, {"fake-model": PRICE}, audit=store, sleep=Sleeps(), timeout_s=0.01
    )
    with pytest.raises(TransientProviderError, match="no response within"):
        await gw.complete(request())
    assert len(store.model_calls) == 3


async def test_circuit_opens_after_consecutive_failures_and_recovers() -> None:
    clock = FakeClock()
    gw, model, _, _ = make(
        [TransientProviderError("x"), TransientProviderError("y"), reply("back")],
        max_attempts=1,
        breaker_threshold=2,
        breaker_reset_s=60,
        clock=clock,
    )
    for _ in range(2):
        with pytest.raises(TransientProviderError):
            await gw.complete(request())
    with pytest.raises(ProviderUnavailable):
        await gw.complete(request())
    assert len(model.requests) == 2  # the open circuit did not call the provider
    clock.now += 61
    assert (await gw.complete(request())).message.text() == "back"


def test_missing_price_refuses_construction() -> None:
    with pytest.raises(ConfigError, match="P7"):
        Gateway({"main": FakeModel()}, {}, audit=InMemoryStore())


async def test_routes_by_role() -> None:
    main = FakeModel([reply("main")], model_id="m")
    light = FakeModel([reply("light")], model_id="l")
    gw = Gateway({"main": main, "light": light}, {"m": PRICE, "l": PRICE}, audit=InMemoryStore())
    assert (await gw.complete(request("light"))).message.text() == "light"
    assert main.requests == []
