"""Create the research_jobs table (project-scoped; one row per background research run).

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # ON DELETE CASCADE makes this an ordinary scoped table: delete_project removes it
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("depth", sa.String(), nullable=False),
        sa.Column("response_id", sa.String(), nullable=False),
        # verbatim (redacted, cut to 64) for a status this server has never seen
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("model", sa.String()),
        # OUR clock only (naive UTC): the API rewrites its own created_at/completed_at on
        # every fetch, so those are never stored (design D7)
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime()),
        sa.Column("finished_at", sa.DateTime()),
        sa.Column("cancel_requested_at", sa.DateTime()),
        sa.Column("missing_since", sa.DateTime()),
        sa.Column("result_text", sa.Text()),
        sa.Column("sources_json", sa.Text()),
        sa.Column("incomplete_reason", sa.String()),
        sa.Column("error_text", sa.Text()),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("total_tokens", sa.Integer()),
        sa.Column("cost_nano_usd", sa.Integer()),
        sa.Column("cost_source", sa.String()),
        sa.Column("usage_recorded", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.UniqueConstraint("response_id", name="uq_research_jobs_response_id"),
        # AUTOINCREMENT: the id of a deleted job is never handed out again (design D7)
        sqlite_autoincrement=True,
    )
    op.create_index("ix_research_jobs_project_id_id", "research_jobs", ["project_id", "id"])
    op.create_index("ix_research_jobs_status", "research_jobs", ["status"])


def downgrade() -> None:
    # Drops every stored job with its table; projects, chats and usage_events are untouched.
    op.drop_index("ix_research_jobs_status", table_name="research_jobs")
    op.drop_index("ix_research_jobs_project_id_id", table_name="research_jobs")
    op.drop_table("research_jobs")
