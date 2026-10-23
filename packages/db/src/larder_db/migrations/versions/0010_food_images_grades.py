"""foods: product photo links and Open Food Facts' own Nutri-Score grade

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-14 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("foods", sa.Column("image_url", sa.Text(), nullable=True))
    op.add_column("foods", sa.Column("off_grade", sa.String(length=1), nullable=True))


def downgrade() -> None:
    op.drop_column("foods", "off_grade")
    op.drop_column("foods", "image_url")
