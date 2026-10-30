"""preferences.meal_style: how far from everyday meals the planner goes

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-30 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "preferences",
        sa.Column("meal_style", sa.String(16), nullable=False, server_default="everyday"),
    )


def downgrade() -> None:
    op.drop_column("preferences", "meal_style")
