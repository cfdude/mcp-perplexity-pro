"""Create the embedding_chunks table (project-scoped vector store for perplexity_embed).

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "embedding_chunks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # ON DELETE CASCADE makes this an ordinary scoped table: delete_project removes it
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(), nullable=False),  # chat | job | text
        # a deleted chat message or research job takes its chunks with it
        sa.Column(
            "chat_message_id",
            sa.Integer(),
            sa.ForeignKey("chat_messages.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "research_job_id",
            sa.Integer(),
            sa.ForeignKey("research_jobs.id", ondelete="CASCADE"),
        ),
        sa.Column("ref", sa.String(), nullable=False),  # c:<id> | j:<id> | t:<key>
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("encoding", sa.String(), nullable=False),  # int8 | binary
        sa.Column("vector", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "(source = 'chat' AND chat_message_id IS NOT NULL AND research_job_id IS NULL)"
            " OR (source = 'job' AND research_job_id IS NOT NULL AND chat_message_id IS NULL)"
            " OR (source = 'text' AND chat_message_id IS NULL AND research_job_id IS NULL)",
            name="ck_embedding_chunks_source_keys",
        ),
        sa.UniqueConstraint(
            "project_id",
            "ref",
            "chunk_index",
            "model",
            "dimensions",
            "encoding",
            name="uq_embedding_chunks_item",
        ),
        sqlite_autoincrement=True,
    )
    op.create_index(
        "ix_embedding_chunks_project_triple",
        "embedding_chunks",
        ["project_id", "model", "dimensions", "encoding"],
    )
    op.create_index(
        "ix_embedding_chunks_project_source", "embedding_chunks", ["project_id", "source"]
    )
    # the cascade from a deleted message or job runs DELETE ... WHERE <key> = ? once per parent
    # row inside one write unit; without these it would scan the whole table each time
    op.create_index(
        "ix_embedding_chunks_chat_message_id",
        "embedding_chunks",
        ["chat_message_id"],
        sqlite_where=sa.text("chat_message_id IS NOT NULL"),
    )
    op.create_index(
        "ix_embedding_chunks_research_job_id",
        "embedding_chunks",
        ["research_job_id"],
        sqlite_where=sa.text("research_job_id IS NOT NULL"),
    )


def downgrade() -> None:
    # Drops every stored vector with its table; the chats, jobs and projects are untouched
    # (backup-0004.db has none of the vectors, the source texts are still there to re-index).
    op.drop_index("ix_embedding_chunks_research_job_id", table_name="embedding_chunks")
    op.drop_index("ix_embedding_chunks_chat_message_id", table_name="embedding_chunks")
    op.drop_index("ix_embedding_chunks_project_source", table_name="embedding_chunks")
    op.drop_index("ix_embedding_chunks_project_triple", table_name="embedding_chunks")
    op.drop_table("embedding_chunks")
