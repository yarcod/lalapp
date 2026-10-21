"""Lalapp: conversation characters and per-language partner preference.

Revision ID: l0003_lalapp_personas
Revises: l0002_lalapp_placement_sessions
"""

import sqlalchemy as sa

from alembic import op

revision = "l0003_lalapp_personas"
down_revision = "l0002_lalapp_placement_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lalapp_conversation_personas",
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("persona_id", sa.String(50), nullable=False),
        sa.Column("persona_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("conversation_id"),
    )
    op.create_table(
        "lalapp_language_preferences",
        sa.Column("user_language_id", sa.Integer(), nullable=False),
        sa.Column("peer_persona_id", sa.String(50), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_language_id"], ["user_languages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_language_id"),
    )


def downgrade() -> None:
    op.drop_table("lalapp_language_preferences")
    op.drop_table("lalapp_conversation_personas")
