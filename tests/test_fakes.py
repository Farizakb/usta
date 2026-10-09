import pytest

from tests.fakes import InMemoryStore
from usta.core.audit import ModelCallRecord
from usta.core.model import Usage
from usta.core.run import RunState, RunStatus


async def test_in_memory_store_round_trips_state_like_postgres() -> None:
    store = InMemoryStore()
    run = RunState.new(id="r1", user_id="u1", task="ə", engine="own", cost_cap_usd=0.5)
    await store.create(run)
    run.status = RunStatus.RUNNING
    await store.checkpoint(run)
    loaded = await store.load("r1")
    assert loaded == run and loaded is not run
    assert await store.ids_with_status(RunStatus.RUNNING) == ["r1"]
    assert await store.cancel_requested("r1") is False
    await store.request_cancel("r1")
    assert await store.cancel_requested("r1") is True


async def test_in_memory_month_cost_sums_model_calls_per_user() -> None:
    store = InMemoryStore()
    for user, cost in [("u1", 0.1), ("u1", 0.2), ("u2", 5.0)]:
        await store.model_call(
            ModelCallRecord(
                run_id="r",
                user_id=user,
                role="main",
                provider="fake",
                model="m",
                prompt_version="p",
                attempt=1,
                request={},
                response=None,
                error=None,
                usage=Usage(),
                cost_usd=cost,
                latency_ms=1,
            )
        )
    assert await store.user_month_cost("u1") == pytest.approx(0.3)
