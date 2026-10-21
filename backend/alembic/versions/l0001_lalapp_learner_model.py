"""Lalapp: learner skill estimates, item difficulty ratings and response log.

Revision ID: l0001_lalapp_learner_model
Revises: (base of the lalapp branch)
"""

import sqlalchemy as sa

from alembic import op

revision = "l0001_lalapp_learner_model"
down_revision = None
branch_labels = ("lalapp",)
depends_on = "0057_flashcard_review_receipts"


def upgrade() -> None:
    op.create_table(
        "lalapp_learner_skills",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_language_id", sa.Integer(), nullable=False),
        sa.Column("skill", sa.String(20), nullable=False),
        sa.Column("theta", sa.Float(), nullable=False),
        sa.Column("theta_sd", sa.Float(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_language_id"], ["user_languages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_language_id", "skill", name="uq_lalapp_learner_skill"),
    )
    op.create_index(
        "ix_lalapp_learner_skills_user_language_id",
        "lalapp_learner_skills",
        ["user_language_id"],
    )
    op.create_table(
        "lalapp_item_ratings",
        sa.Column("item_key", sa.String(200), nullable=False),
        sa.Column("difficulty", sa.Float(), nullable=False),
        sa.Column("difficulty_sd", sa.Float(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("item_key"),
    )
    op.create_table(
        "lalapp_learner_responses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_language_id", sa.Integer(), nullable=False),
        sa.Column("item_key", sa.String(200), nullable=False),
        sa.Column("skill", sa.String(20), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("expected", sa.Float(), nullable=False),
        sa.Column("theta_before", sa.Float(), nullable=False),
        sa.Column("difficulty_before", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_language_id"], ["user_languages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_lalapp_learner_responses_user_language_id",
        "lalapp_learner_responses",
        ["user_language_id"],
    )
    op.create_index(
        "ix_lalapp_learner_responses_item_key", "lalapp_learner_responses", ["item_key"]
    )


def downgrade() -> None:
    op.drop_table("lalapp_learner_responses")
    op.drop_table("lalapp_item_ratings")
    op.drop_table("lalapp_learner_skills")
