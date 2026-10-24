"""units: users.units, metric or US (pounds, ounces, feet); NULL follows the region

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-24 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("units", sa.String(6), nullable=True))
    op.create_check_constraint("ck_users_units", "users", "units IN ('metric', 'us')")


def downgrade() -> None:
    op.drop_constraint("ck_users_units", "users", type_="check")
    op.drop_column("users", "units")
