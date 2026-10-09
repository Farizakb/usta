"""initial schema: users, runs, checkpoints, append-only audit tables, DB roles

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

STATUSES = (
    "queued",
    "running",
    "awaiting_approval",
    "awaiting_user",
    "unknown_outcome",
    "finished",
)
STOP_REASONS = (
    "done",
    "verification_failed",
    "max_turns",
    "budget_declined",
    "timeout",
    "provider_quota",
    "cancelled",
    "interrupted",
    "error",
)
RUN_TABLES = "users, runs, run_checkpoints"
AUDIT_TABLES = "model_calls, tool_calls, run_events"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _ts(name: str, default: str = "now()") -> sa.Column:
    return sa.Column(
        name, sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text(default)
    )


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column("scopes", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        _ts("created_at"),
        sa.CheckConstraint("id ~ '^[a-z0-9][a-z0-9_-]{0,63}$'", name="ck_users_id_format"),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("task", sa.Text, nullable=False),
        sa.Column("engine", sa.Text, nullable=False),
        sa.Column("profile", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("stop_reason", sa.Text, nullable=True),
        sa.Column("cancel_requested", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("turns", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("cost_usd", sa.Float, nullable=False, server_default=sa.text("0")),
        _ts("created_at"),
        _ts("updated_at"),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(_in("status", STATUSES), name="ck_runs_status"),
        sa.CheckConstraint(
            "stop_reason IS NULL OR " + _in("stop_reason", STOP_REASONS), name="ck_runs_stop_reason"
        ),
        sa.CheckConstraint(
            "(status = 'finished') = (stop_reason IS NOT NULL)", name="ck_runs_finished_has_reason"
        ),
    )
    op.create_index(
        "ix_runs_status", "runs", ["status"], postgresql_where=sa.text("status <> 'finished'")
    )
    op.create_index("ix_runs_user_created", "runs", ["user_id", "created_at"])
    op.create_table(
        "run_checkpoints",
        sa.Column(
            "run_id", sa.Uuid, sa.ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("seq", sa.Integer, primary_key=True),
        sa.Column("state", JSONB, nullable=False),
        _ts("created_at"),
    )
    op.create_table(
        "model_calls",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("run_id", sa.Uuid, nullable=True),
        sa.Column("user_id", sa.Text, nullable=True),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("prompt_version", sa.Text, nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("request", JSONB, nullable=False),
        sa.Column("response", JSONB, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("input_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=False),
        sa.Column("cache_read_tokens", sa.Integer, nullable=False),
        sa.Column("cache_write_tokens", sa.Integer, nullable=False),
        sa.Column("cost_usd", sa.Float, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        _ts("created_at", "clock_timestamp()"),
    )
    op.create_index("ix_model_calls_run", "model_calls", ["run_id"])
    op.create_index("ix_model_calls_user_created", "model_calls", ["user_id", "created_at"])
    op.create_table(
        "tool_calls",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("run_id", sa.Uuid, nullable=False),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("call_id", sa.Text, nullable=False),
        sa.Column("tool", sa.Text, nullable=False),
        sa.Column("phase", sa.Text, nullable=False),
        sa.Column("input", JSONB, nullable=False),
        sa.Column("output", sa.Text, nullable=True),
        sa.Column("is_error", sa.Boolean, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        _ts("created_at", "clock_timestamp()"),
        sa.CheckConstraint("phase IN ('intent', 'done')", name="ck_tool_calls_phase"),
    )
    op.create_index("ix_tool_calls_run_call", "tool_calls", ["run_id", "call_id"])
    op.create_table(
        "run_events",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("run_id", sa.Uuid, nullable=False),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("data", JSONB, nullable=False),
        _ts("created_at", "clock_timestamp()"),
    )
    op.create_index("ix_run_events_run_created", "run_events", ["run_id", "created_at"])

    # Append-only audit, enforced by the database (ADR-029).
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'usta_app') THEN
            CREATE ROLE usta_app NOLOGIN;
          END IF;
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'usta_purge') THEN
            CREATE ROLE usta_purge NOLOGIN;
          END IF;
        END $$;
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO usta_app, usta_purge")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {RUN_TABLES} TO usta_app")
    op.execute(f"GRANT SELECT, INSERT ON {AUDIT_TABLES} TO usta_app")
    op.execute(f"GRANT SELECT, DELETE ON {AUDIT_TABLES}, runs TO usta_purge")


def downgrade() -> None:
    # Roles are cluster-wide and may serve other databases, so they stay.
    for table in ("run_events", "tool_calls", "model_calls", "run_checkpoints", "runs", "users"):
        op.drop_table(table)
