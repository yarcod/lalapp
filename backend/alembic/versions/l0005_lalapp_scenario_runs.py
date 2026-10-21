"""Lalapp: role-play scenario runs and mission evidence.

Revision ID: l0005_lalapp_scenario_runs
Revises: l0004_lalapp_adaptive_lessons
"""

import sqlalchemy as sa

from alembic import op

revision = "l0005_lalapp_scenario_runs"
down_revision = "l0004_lalapp_adaptive_lessons"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lalapp_scenario_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_language_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("scenario_id", sa.String(50), nullable=False),
        sa.Column("scenario_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("missions", sa.JSON(), nullable=False),
        sa.Column("last_checked_message_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_language_id"], ["user_languages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id"),
    )
    op.create_index(
        "ix_lalapp_scenario_runs_user_language_id",
        "lalapp_scenario_runs",
        ["user_language_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_lalapp_scenario_runs_user_language_id", "lalapp_scenario_runs")
    op.drop_table("lalapp_scenario_runs")
