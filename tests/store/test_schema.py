import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import CheckConstraint, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from usta.store.tables import metadata

pytestmark = pytest.mark.pg

INSERT_EVENT = (
    "INSERT INTO run_events (id, run_id, user_id, type, data) "
    "VALUES (gen_random_uuid(), gen_random_uuid(), 'u1', 'finished', '{}')"
)


@pytest.mark.parametrize("table", ["model_calls", "tool_calls", "run_events"])
async def test_app_role_cannot_update_delete_or_truncate_audit_rows(
    app_role_engine, table: str
) -> None:
    for statement in (
        f"UPDATE {table} SET created_at = now()",
        f"DELETE FROM {table}",
        f"TRUNCATE {table}",
    ):
        async with app_role_engine.connect() as conn:
            with pytest.raises(DBAPIError, match="permission denied"):
                await conn.execute(text(statement))


async def test_app_role_can_insert_and_select_audit_rows(app_role_engine) -> None:
    async with app_role_engine.begin() as conn:
        await conn.execute(text(INSERT_EVENT))
        assert (await conn.execute(text("SELECT count(*) FROM run_events"))).scalar_one() == 1


async def test_purge_role_can_delete_audit_rows(db_engine) -> None:
    async with db_engine.begin() as conn:
        await conn.execute(text(INSERT_EVENT))
        await conn.execute(text("SET LOCAL ROLE usta_purge"))
        assert (await conn.execute(text("DELETE FROM run_events"))).rowcount == 1


async def test_finished_run_needs_a_stop_reason(db_engine) -> None:
    async with db_engine.begin() as conn:
        await conn.execute(text("INSERT INTO users (id, display_name) VALUES ('u1', 'U')"))
    with pytest.raises(IntegrityError, match="ck_runs_finished_has_reason"):
        async with db_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO runs (id, user_id, task, engine, profile, status) "
                    "VALUES (gen_random_uuid(), 'u1', 't', 'own', 'test', 'finished')"
                )
            )


def test_table_definitions_match_migrations(migrated_db: str) -> None:
    command.check(Config("alembic.ini"))  # raises if tables.py and migrations disagree


RUN_ID = "11111111-1111-1111-1111-111111111111"
INSERT_USER = "INSERT INTO users (id, display_name) VALUES ('u1', 'U')"
INSERT_RUN = (
    "INSERT INTO runs (id, user_id, task, engine, profile, status) "
    f"VALUES ('{RUN_ID}', 'u1', 't', 'own', 'test', 'running')"
)
INSERT_CHECKPOINT = (
    f"INSERT INTO run_checkpoints (run_id, seq, state) VALUES ('{RUN_ID}', 1, '{{}}')"
)


@pytest.mark.parametrize("bad_id", ["../x", "A b", "", "-a", "a" * 65])
async def test_user_id_check_rejects_bad_ids(db_engine, bad_id: str) -> None:
    with pytest.raises(IntegrityError, match="ck_users_id_format"):
        async with db_engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO users (id, display_name) VALUES (:id, 'X')"), {"id": bad_id}
            )


@pytest.mark.parametrize("good_id", ["fariz", "user_1-a", "a" * 64])
async def test_user_id_check_accepts_good_ids(db_engine, good_id: str) -> None:
    async with db_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO users (id, display_name) VALUES (:id, 'X')"), {"id": good_id}
        )


async def test_runs_status_index_is_partial(db_engine) -> None:
    async with db_engine.connect() as conn:
        definition = (
            await conn.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_runs_status'")
            )
        ).scalar_one()
    assert "WHERE (status <> 'finished'::text)" in definition


async def test_runs_status_accepts_all_six_values_and_rejects_others(db_engine) -> None:
    async with db_engine.begin() as conn:
        await conn.execute(text(INSERT_USER))
        for status in (
            "queued",
            "running",
            "awaiting_approval",
            "awaiting_user",
            "unknown_outcome",
        ):
            await conn.execute(
                text(
                    "INSERT INTO runs (id, user_id, task, engine, profile, status) "
                    f"VALUES (gen_random_uuid(), 'u1', 't', 'own', 'p', '{status}')"
                )
            )
        await conn.execute(
            text(
                "INSERT INTO runs (id, user_id, task, engine, profile, status, stop_reason) "
                "VALUES (gen_random_uuid(), 'u1', 't', 'own', 'p', 'finished', 'done')"
            )
        )
    with pytest.raises(IntegrityError, match="ck_runs_status"):
        async with db_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO runs (id, user_id, task, engine, profile, status) "
                    "VALUES (gen_random_uuid(), 'u1', 't', 'own', 'p', 'bogus')"
                )
            )


async def test_app_role_can_write_run_tables_but_not_delete_runs(app_role_engine) -> None:
    async with app_role_engine.begin() as conn:
        await conn.execute(text(INSERT_USER))
        await conn.execute(text(INSERT_RUN))
        await conn.execute(text(INSERT_CHECKPOINT))
        await conn.execute(text("UPDATE runs SET turns = 1"))
        await conn.execute(text("UPDATE run_checkpoints SET seq = 2"))
        await conn.execute(text("UPDATE users SET display_name = 'V'"))
    for statement in ("DELETE FROM runs", "DELETE FROM run_checkpoints", "DELETE FROM users"):
        async with app_role_engine.connect() as conn:
            with pytest.raises(DBAPIError, match="permission denied"):
                await conn.execute(text(statement))


async def test_purge_role_deletes_run_and_cascades_checkpoints(db_engine) -> None:
    async with db_engine.begin() as conn:
        await conn.execute(text(INSERT_USER))
        await conn.execute(text(INSERT_RUN))
        await conn.execute(text(INSERT_CHECKPOINT))
    async with db_engine.begin() as conn:
        await conn.execute(text("SET LOCAL ROLE usta_purge"))
        assert (await conn.execute(text("DELETE FROM runs"))).rowcount == 1
    async with db_engine.connect() as conn:
        count = (await conn.execute(text("SELECT count(*) FROM run_checkpoints"))).scalar_one()
    assert count == 0


async def test_checks_and_indexes_match_metadata(db_engine) -> None:
    """`alembic check` ignores CHECK constraints and index predicates, so compare them here."""
    async with db_engine.connect() as conn:
        db_checks = {
            (r[0], r[1])
            for r in await conn.execute(
                text(
                    "SELECT conrelid::regclass::text, conname FROM pg_constraint "
                    "WHERE contype = 'c' AND connamespace = 'public'::regnamespace"
                )
            )
        }
        db_indexes = dict(
            (await conn.execute(text("SELECT indexname, indexdef FROM pg_indexes"))).all()
        )
    expected_checks = {
        (table.name, c.name)
        for table in metadata.tables.values()
        for c in table.constraints
        if isinstance(c, CheckConstraint)
    }
    assert db_checks == expected_checks
    for table in metadata.tables.values():
        for index in table.indexes:
            assert index.name in db_indexes, index.name
            assert ("WHERE" in db_indexes[index.name]) == bool(
                index.dialect_options["postgresql"]["where"] is not None
            ), index.name
