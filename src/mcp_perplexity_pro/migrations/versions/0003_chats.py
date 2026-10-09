"""Create the chats and chat_messages tables (project-scoped; messages cascade with the chat).

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chats",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # ON DELETE CASCADE makes this an ordinary scoped table: delete_project removes it
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(), nullable=False),
        # naive UTC with microseconds
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        # AUTOINCREMENT: the id of a deleted chat is never handed out again (design D6)
        sqlite_autoincrement=True,
    )
    op.create_index("ix_chats_project_id_updated_at", "chats", ["project_id", "updated_at"])
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "chat_id",
            sa.Integer(),
            sa.ForeignKey("chats.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(), nullable=False),  # user | assistant
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("response_id", sa.String()),
        sa.Column("model", sa.String()),
        sa.Column("preset", sa.String()),
        sa.Column("sources_json", sa.Text()),
    )
    op.create_index("ix_chat_messages_chat_id_id", "chat_messages", ["chat_id", "id"])


def downgrade() -> None:
    # Drops every stored chat with its tables; projects and usage_events are untouched.
    op.drop_index("ix_chat_messages_chat_id_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chats_project_id_updated_at", table_name="chats")
    op.drop_table("chats")
