"""recipe_notes: a user's private note and 1-5 star rating on a recipe

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-23 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recipe_notes",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "recipe_id",
            sa.Integer(),
            sa.ForeignKey("recipes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("rating", sa.SmallInteger(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_recipe_notes_rating"),
    )


def downgrade() -> None:
    op.drop_table("recipe_notes")
