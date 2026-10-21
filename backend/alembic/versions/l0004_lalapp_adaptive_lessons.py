"""Lalapp: rationale for adaptively generated lessons.

Revision ID: l0004_lalapp_adaptive_lessons
Revises: l0003_lalapp_personas
"""

import sqlalchemy as sa

from alembic import op

revision = "l0004_lalapp_adaptive_lessons"
down_revision = "l0003_lalapp_personas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lalapp_adaptive_lessons",
        sa.Column("lesson_id", sa.Integer(), nullable=False),
        sa.Column("study_plan_id", sa.Integer(), nullable=False),
        sa.Column("skill", sa.String(20), nullable=False),
        sa.Column("cefr_level", sa.String(2), nullable=False),
        sa.Column("unit_id", sa.String(50), nullable=True),
        sa.Column("focus", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(20), nullable=False),
        sa.Column("predicted_success", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["study_plan_id"], ["study_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("lesson_id"),
    )
    op.create_index(
        "ix_lalapp_adaptive_lessons_study_plan_id",
        "lalapp_adaptive_lessons",
        ["study_plan_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_lalapp_adaptive_lessons_study_plan_id", "lalapp_adaptive_lessons")
    op.drop_table("lalapp_adaptive_lessons")
