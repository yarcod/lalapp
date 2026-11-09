"""Add the per-profile child setting used to adapt prompts.

Revision ID: 0058_user_is_child
Revises: 0057_flashcard_review_receipts
"""

import sqlalchemy as sa

from alembic import op

revision = "0058_user_is_child"
down_revision = "0057_flashcard_review_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_child", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("users", "is_child")
