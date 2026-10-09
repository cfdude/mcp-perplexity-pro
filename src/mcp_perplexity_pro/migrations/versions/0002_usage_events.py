"""Create the usage_events table (retained: spend history outlives its project).

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # naive UTC with microseconds, written by the recorder
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("tool", sa.String(), nullable=False),
        sa.Column("api", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("model", sa.String()),
        sa.Column("preset", sa.String()),
        sa.Column("request_id", sa.String()),
        # ON DELETE SET NULL makes this a retained table; project_name outlives the project row
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("project_name", sa.String()),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("total_tokens", sa.Integer()),
        sa.Column("cached_tokens", sa.Integer()),
        sa.Column("cache_creation_tokens", sa.Integer()),
        sa.Column("cache_read_tokens", sa.Integer()),
        sa.Column("reasoning_tokens", sa.Integer()),
        # money: integer nano-USD (10^-9 USD); cost_source is reported | computed | none
        sa.Column("cost_nano_usd", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("cost_source", sa.String(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False, server_default=sa.text("'USD'")),
        sa.Column("input_cost_nano", sa.Integer()),
        sa.Column("output_cost_nano", sa.Integer()),
        sa.Column("cache_read_cost_nano", sa.Integer()),
        sa.Column("cache_creation_cost_nano", sa.Integer()),
        sa.Column("tool_calls_cost_nano", sa.Integer()),
        sa.Column("price_table", sa.String()),
        sa.Column("tool_calls_json", sa.Text()),
        sa.Column("usage_json", sa.Text()),
    )
    op.create_index("ix_usage_events_created_at", "usage_events", ["created_at"])
    op.create_index("ix_usage_events_project_name", "usage_events", ["project_name"])
    # one stored event per successful upstream response (design D8)
    op.create_index(
        "uq_usage_events_api_request_id",
        "usage_events",
        ["api", "request_id"],
        unique=True,
        sqlite_where=sa.text("request_id IS NOT NULL AND status = 'ok'"),
    )


def downgrade() -> None:
    # Drops the spend history with the table; the automatic pre-upgrade backup holds the
    # revision-0001 database, not these rows.
    op.drop_index("uq_usage_events_api_request_id", table_name="usage_events")
    op.drop_index("ix_usage_events_project_name", table_name="usage_events")
    op.drop_index("ix_usage_events_created_at", table_name="usage_events")
    op.drop_table("usage_events")
