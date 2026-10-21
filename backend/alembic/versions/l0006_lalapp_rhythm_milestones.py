"""Lalapp: weekly rhythm goals and informational milestones.

Revision ID: l0006_lalapp_rhythm_milestones
Revises: l0005_lalapp_scenario_runs
"""

import sqlalchemy as sa

from alembic import op

revision = "l0006_lalapp_rhythm_milestones"
down_revision = "l0005_lalapp_scenario_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lalapp_rhythm_goals",
        sa.Column("user_language_id", sa.Integer(), nullable=False),
        sa.Column("days_per_week", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_language_id"], ["user_languages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_language_id"),
    )
    op.create_table(
        "lalapp_milestones",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_language_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("seen_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_language_id"], ["user_languages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_language_id", "key", name="uq_lalapp_milestone_key"),
    )
    op.create_index(
        "ix_lalapp_milestones_user_language_id", "lalapp_milestones", ["user_language_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_lalapp_milestones_user_language_id", "lalapp_milestones")
    op.drop_table("lalapp_milestones")
    op.drop_table("lalapp_rhythm_goals")
