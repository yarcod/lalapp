"""Lalapp: adaptive placement sessions.

Revision ID: l0002_lalapp_placement_sessions
Revises: l0001_lalapp_learner_model
"""

import sqlalchemy as sa

from alembic import op

revision = "l0002_lalapp_placement_sessions"
down_revision = "l0001_lalapp_learner_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lalapp_placement_sessions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("target_language", sa.String(10), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("pending_item_id", sa.String(50), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_lalapp_placement_sessions_user_id", "lalapp_placement_sessions", ["user_id"]
    )


def downgrade() -> None:
    op.drop_table("lalapp_placement_sessions")
