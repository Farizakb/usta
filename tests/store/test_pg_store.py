import uuid

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine

from usta.core.audit import ModelCallRecord, ToolCallRecord
from usta.core.errors import UnknownUser, UstaError
from usta.core.events import Event
from usta.core.messages import Message, ToolCall
from usta.core.model import ModelResponse, Usage
from usta.core.run import RunState, RunStatus, StopReason
from usta.store.pg import PgRunStore

pytestmark = pytest.mark.pg
AZ_TASK = "Keçən həftənin yanacaq hesabatı: İSTİQAMƏT, IŞIQ — ğ ş ı ö ü ç ə"
UTC_MONTH_START = "(date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')"


@pytest.fixture
async def store(app_role_engine) -> PgRunStore:
    s = PgRunStore(app_role_engine, profile="test")
    await s.add_user("u1", "Test İstifadəçi", ["fleet:read"])
    return s


@pytest.fixture
async def far_tz_engine(clean_db: str):
    """Runs as usta_app with a session TimeZone far from UTC (UTC+14)."""
    engine = create_async_engine(
        clean_db, connect_args={"server_settings": {"timezone": "Pacific/Kiritimati"}}
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _set_role(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("SET ROLE usta_app")
        cursor.close()
        # Commit, or the pool's rollback after a failed statement silently undoes SET ROLE.
        dbapi_connection.commit()

    yield engine
    await engine.dispose()


def new_run(user_id: str = "u1") -> RunState:
    return RunState.new(
        id=str(uuid.uuid4()), user_id=user_id, task=AZ_TASK, engine="own", cost_cap_usd=0.5
    )


def model_record(user_id: str, cost: float) -> ModelCallRecord:
    return ModelCallRecord(
        run_id=str(uuid.uuid4()),
        user_id=user_id,
        role="main",
        provider="fake",
        model="m",
        prompt_version="p",
        attempt=1,
        request={"q": "ə"},
        response=None,
        error=None,
        usage=Usage(input_tokens=1),
        cost_usd=cost,
        latency_ms=3,
    )


async def test_create_then_load_round_trips_azerbaijani_text(store: PgRunStore) -> None:
    run = new_run()
    run.record(
        ModelResponse(
            message=Message(
                role="assistant",
                content=(ToolCall(id="c", name="file.read", input={"path": "files/ə.txt"}),),
            ),
            usage=Usage(),
            stop="tool_use",
            model="m",
        )
    )
    await store.create(run)
    loaded = await store.load(run.id)
    assert loaded == run
    assert loaded.task == AZ_TASK


async def test_checkpoint_appends_and_updates_the_summary_row(store: PgRunStore, db_engine) -> None:
    run = new_run()
    await store.create(run)
    run.status, run.turns, run.cost_usd = RunStatus.RUNNING, 2, 0.25
    await store.checkpoint(run)
    run.finish(StopReason.DONE)
    await store.checkpoint(run)
    assert (await store.load(run.id)).stop_reason == StopReason.DONE
    async with db_engine.connect() as conn:
        seqs = (
            (
                await conn.execute(
                    text("SELECT seq FROM run_checkpoints WHERE run_id = :r ORDER BY seq"),
                    {"r": run.id},
                )
            )
            .scalars()
            .all()
        )
        row = (
            await conn.execute(
                text(
                    "SELECT status, stop_reason, turns, cost_usd, finished_at FROM runs WHERE id = :r"
                ),
                {"r": run.id},
            )
        ).one()
    assert seqs == [0, 1, 2]
    assert (row.status, row.stop_reason, row.turns, row.cost_usd) == ("finished", "done", 2, 0.25)
    assert row.finished_at is not None


async def test_ids_with_status_and_cancel_flag(store: PgRunStore) -> None:
    a, b = new_run(), new_run()
    await store.create(a)
    await store.create(b)
    b.status = RunStatus.RUNNING
    await store.checkpoint(b)
    assert await store.ids_with_status(RunStatus.RUNNING) == [b.id]
    assert set(await store.ids_with_status(RunStatus.RUNNING, RunStatus.QUEUED)) == {a.id, b.id}
    assert await store.cancel_requested(b.id) is False
    await store.request_cancel(b.id)
    assert await store.cancel_requested(b.id) is True


async def test_events_are_appended_in_order(store: PgRunStore) -> None:
    run = new_run()
    await store.create(run)
    for kind in ("run_started", "model_call", "finished"):
        await store.append_event(Event(run_id=run.id, type=kind, data={"t": "ə"}), "u1")
    assert [e.type for e in await store.events(run.id)] == ["run_started", "model_call", "finished"]


async def test_audit_rows_and_month_cost(store: PgRunStore, db_engine) -> None:
    for user, cost in [("u1", 0.1), ("u1", 0.2), ("u2", 5.0)]:
        await store.model_call(model_record(user, cost))
    old = model_record("u1", 9.0)
    await store.model_call(old)
    async with db_engine.begin() as conn:  # owner backdates one row to last month
        await conn.execute(
            text(
                "UPDATE model_calls SET created_at = now() - interval '40 days' WHERE cost_usd = 9.0"
            )
        )
    assert await store.user_month_cost("u1") == pytest.approx(0.3)
    assert await store.user_month_cost("nobody") == 0.0
    await store.tool_call(
        ToolCallRecord(
            run_id=str(uuid.uuid4()),
            user_id="u1",
            call_id="c",
            tool="todo",
            phase="intent",
            input={"items": []},
        )
    )


async def test_month_boundary_is_utc(far_tz_engine, db_engine) -> None:
    store = PgRunStore(far_tz_engine, profile="test")
    await store.model_call(model_record("u1", 9.0))  # one minute before the UTC month start
    await store.model_call(model_record("u1", 0.2))  # one minute after the UTC month start
    async with db_engine.begin() as conn:  # owner pins both rows to the boundary
        await conn.execute(
            text(
                f"UPDATE model_calls SET created_at = {UTC_MONTH_START} - interval '1 minute' WHERE cost_usd = 9.0"
            )
        )
        await conn.execute(
            text(
                f"UPDATE model_calls SET created_at = {UTC_MONTH_START} + interval '1 minute' WHERE cost_usd = 0.2"
            )
        )
    assert await store.user_month_cost("u1") == pytest.approx(0.2)


async def test_unknown_user_is_a_clear_error(store: PgRunStore) -> None:
    with pytest.raises(UnknownUser, match="usta user ghost"):
        await store.create(new_run("ghost"))


@pytest.mark.parametrize("bad", ["../x", "Fariz", "", "a" * 33, "u 1"])
async def test_invalid_user_ids_are_refused(store: PgRunStore, bad: str) -> None:
    with pytest.raises(UstaError, match="invalid user id"):
        await store.add_user(bad, "x")


async def test_add_user_is_an_upsert(store: PgRunStore, db_engine) -> None:
    await store.add_user("u1", "Yeni ad", ["email:read"])
    async with db_engine.connect() as conn:
        row = (
            await conn.execute(text("SELECT display_name, scopes FROM users WHERE id = 'u1'"))
        ).one()
    assert (row.display_name, row.scopes) == ("Yeni ad", ["email:read"])
