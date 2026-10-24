"""meal modes: preferences.meal_modes, which meals the planner plans ({"lunch": "own"})

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-24 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "preferences",
        sa.Column("meal_modes", JSONB(), server_default=sa.text("'{}'"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("preferences", "meal_modes")
