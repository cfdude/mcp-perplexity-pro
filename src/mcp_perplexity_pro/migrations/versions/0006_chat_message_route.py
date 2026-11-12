"""Add chat_messages.tier and chat_messages.routed_model (the router's chat hold, design D12).

Revision ID: 0006
Revises: 0005

Both columns are nullable: a row written before this revision, a preset turn, an explicit
``model`` turn and every ``standard`` or ``custom`` turn leave them null.
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("tier", sa.String()))
    op.add_column("chat_messages", sa.Column("routed_model", sa.String()))


def downgrade() -> None:
    # ``ALTER TABLE ... DROP COLUMN`` (SQLite 3.35.0, the project minimum), deliberately NOT
    # Alembic's batch mode: batch mode rebuilds the table (create, copy, drop, rename), and
    # dropping ``chat_messages`` would cascade through the ON DELETE CASCADE key of
    # ``embedding_chunks`` and silently delete every stored vector of a chat.
    op.execute("ALTER TABLE chat_messages DROP COLUMN routed_model")
    op.execute("ALTER TABLE chat_messages DROP COLUMN tier")
