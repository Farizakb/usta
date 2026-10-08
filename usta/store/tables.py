"""SQLAlchemy Core tables. Must match the migrations (`alembic check` in the test suite)."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

metadata = MetaData()


def _ts(name: str, default: str | None = "now()", nullable: bool = False) -> Column:
    return Column(
        name,
        TIMESTAMP(timezone=True),
        nullable=nullable,
        server_default=text(default) if default else None,
    )


def _uuid(name: str, *args, **kw) -> Column:
    return Column(name, Uuid(as_uuid=False), *args, **kw)


users = Table(
    "users",
    metadata,
    Column("id", Text, primary_key=True),
    Column("display_name", Text, nullable=False),
    Column("scopes", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    _ts("created_at"),
    CheckConstraint("id ~ '^[a-z0-9][a-z0-9_-]{0,63}$'", name="ck_users_id_format"),
)

runs = Table(
    "runs",
    metadata,
    _uuid("id", primary_key=True),
    Column("user_id", Text, ForeignKey("users.id"), nullable=False),
    Column("task", Text, nullable=False),
    Column("engine", Text, nullable=False),
    Column("profile", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("stop_reason", Text, nullable=True),
    Column("cancel_requested", Boolean, nullable=False, server_default=text("false")),
    Column("turns", Integer, nullable=False, server_default=text("0")),
    Column("cost_usd", Float, nullable=False, server_default=text("0")),
    _ts("created_at"),
    _ts("updated_at"),
    _ts("finished_at", default=None, nullable=True),
    Index("ix_runs_status", "status", postgresql_where=text("status <> 'finished'")),
    Index("ix_runs_user_created", "user_id", "created_at"),
)

run_checkpoints = Table(
    "run_checkpoints",
    metadata,
    _uuid("run_id", ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True),
    Column("seq", Integer, primary_key=True),
    Column("state", JSONB, nullable=False),
    _ts("created_at"),
)

model_calls = Table(
    "model_calls",
    metadata,
    _uuid("id", primary_key=True),
    _uuid("run_id", nullable=True),
    Column("user_id", Text, nullable=True),
    Column("role", Text, nullable=False),
    Column("provider", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("prompt_version", Text, nullable=False),
    Column("attempt", Integer, nullable=False),
    Column("request", JSONB, nullable=False),
    Column("response", JSONB(none_as_null=True), nullable=True),
    Column("error", Text, nullable=True),
    Column("input_tokens", Integer, nullable=False),
    Column("output_tokens", Integer, nullable=False),
    Column("cache_read_tokens", Integer, nullable=False),
    Column("cache_write_tokens", Integer, nullable=False),
    Column("cost_usd", Float, nullable=False),
    Column("latency_ms", Integer, nullable=False),
    _ts("created_at", default="clock_timestamp()"),
    Index("ix_model_calls_run", "run_id"),
    Index("ix_model_calls_user_created", "user_id", "created_at"),
)

tool_calls = Table(
    "tool_calls",
    metadata,
    _uuid("id", primary_key=True),
    _uuid("run_id", nullable=False),
    Column("user_id", Text, nullable=False),
    Column("call_id", Text, nullable=False),
    Column("tool", Text, nullable=False),
    Column("phase", Text, nullable=False),
    Column("input", JSONB, nullable=False),
    Column("output", Text, nullable=True),
    Column("is_error", Boolean, nullable=True),
    Column("latency_ms", Integer, nullable=True),
    _ts("created_at", default="clock_timestamp()"),
    Index("ix_tool_calls_run_call", "run_id", "call_id"),
)

run_events = Table(
    "run_events",
    metadata,
    _uuid("id", primary_key=True),
    _uuid("run_id", nullable=False),
    Column("user_id", Text, nullable=False),
    Column("type", Text, nullable=False),
    Column("data", JSONB, nullable=False),
    _ts("created_at", default="clock_timestamp()"),
    Index("ix_run_events_run_created", "run_id", "created_at"),
)
