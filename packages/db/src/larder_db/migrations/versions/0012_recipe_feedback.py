"""preferences: favourite recipes (planned more often) and recipes never to plan again

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-14 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name in ("favourite_recipe_ids", "blocked_recipe_ids"):
        op.add_column(
            "preferences",
            sa.Column(
                name,
                postgresql.ARRAY(sa.Integer()),
                server_default=sa.text("'{}'"),
                nullable=False,
            ),
        )


def downgrade() -> None:
    op.drop_column("preferences", "blocked_recipe_ids")
    op.drop_column("preferences", "favourite_recipe_ids")
