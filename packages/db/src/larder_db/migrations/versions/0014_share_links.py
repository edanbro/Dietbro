"""share_links: read-only public links to a recipe or a week's plan

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-20 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "share_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token", sa.String(length=32), nullable=False, unique=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column(
            "recipe_id",
            sa.Integer(),
            sa.ForeignKey("recipes.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("plan_start", sa.Date(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(kind = 'recipe' AND recipe_id IS NOT NULL AND plan_start IS NULL)"
            " OR (kind = 'week' AND plan_start IS NOT NULL AND recipe_id IS NULL)",
            name="ck_share_links_target",
        ),
    )
    op.create_index("ix_share_links_user_id", "share_links", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_share_links_user_id", table_name="share_links")
    op.drop_table("share_links")
