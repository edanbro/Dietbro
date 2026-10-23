"""user region: country, time zone and locale (currency, prices, dates)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-13 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("country", sa.String(length=2), nullable=True))
    op.add_column("users", sa.Column("timezone", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("locale", sa.String(length=35), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "locale")
    op.drop_column("users", "timezone")
    op.drop_column("users", "country")
