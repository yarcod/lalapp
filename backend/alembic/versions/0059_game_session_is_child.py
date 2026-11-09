"""Record whether a game was requested for a child profile.

Revision ID: 0059_game_session_is_child
Revises: 0058_user_is_child
"""

import sqlalchemy as sa

from alembic import op

revision = "0059_game_session_is_child"
down_revision = "0058_user_is_child"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "game_sessions",
        sa.Column("is_child", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("game_sessions", "is_child")
