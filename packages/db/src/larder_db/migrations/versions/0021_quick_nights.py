"""busy nights: preferences.quick_days (weekdays whose dinner is quick) and quick_minutes

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-25 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "preferences",
        sa.Column(
            "quick_days",
            postgresql.ARRAY(sa.SmallInteger()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.add_column(
        "preferences",
        sa.Column("quick_minutes", sa.SmallInteger(), server_default="30", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("preferences", "quick_minutes")
    op.drop_column("preferences", "quick_days")
