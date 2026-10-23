"""household: goals.household, the number of people the user cooks for (1-8)

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-26 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "goals", sa.Column("household", sa.SmallInteger(), server_default="1", nullable=False)
    )
    op.create_check_constraint("ck_goals_household", "goals", "household BETWEEN 1 AND 8")


def downgrade() -> None:
    op.drop_constraint("ck_goals_household", "goals", type_="check")
    op.drop_column("goals", "household")
