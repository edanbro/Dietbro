"""shared shopping list: share_links.kind 'list' (a week's shopping list, tickable by link)

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-26 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEFORE = (
    "(kind = 'recipe' AND recipe_id IS NOT NULL AND plan_start IS NULL)"
    " OR (kind = 'week' AND plan_start IS NOT NULL AND recipe_id IS NULL)"
)
_AFTER = (
    "(kind = 'recipe' AND recipe_id IS NOT NULL AND plan_start IS NULL)"
    " OR (kind IN ('week', 'list') AND plan_start IS NOT NULL AND recipe_id IS NULL)"
)


def upgrade() -> None:
    op.drop_constraint("ck_share_links_target", "share_links", type_="check")
    op.create_check_constraint("ck_share_links_target", "share_links", _AFTER)


def downgrade() -> None:
    op.execute("DELETE FROM share_links WHERE kind = 'list'")
    op.drop_constraint("ck_share_links_target", "share_links", type_="check")
    op.create_check_constraint("ck_share_links_target", "share_links", _BEFORE)
