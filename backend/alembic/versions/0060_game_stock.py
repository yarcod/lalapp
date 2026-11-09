"""Add the pre-generated game stock.

Revision ID: 0060_game_stock
Revises: 0059_game_session_is_child
"""

import sqlalchemy as sa

from alembic import op

revision = "0060_game_stock"
down_revision = "0059_game_session_is_child"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "game_stock",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "study_plan_id",
            sa.Integer(),
            sa.ForeignKey("study_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("game_type", sa.String(24), nullable=False),
        sa.Column("target_language", sa.String(10), nullable=False),
        sa.Column("native_language", sa.String(10), nullable=False),
        sa.Column("level", sa.String(10), nullable=False),
        sa.Column("is_child", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("is_stale", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("replaced", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("counts_toward_cap", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("taken_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_game_stock_study_plan_id", "game_stock", ["study_plan_id"])
    op.create_index("ix_game_stock_bucket", "game_stock", ["study_plan_id", "mode", "game_type"])


def downgrade() -> None:
    op.drop_index("ix_game_stock_bucket", table_name="game_stock")
    op.drop_index("ix_game_stock_study_plan_id", table_name="game_stock")
    op.drop_table("game_stock")
