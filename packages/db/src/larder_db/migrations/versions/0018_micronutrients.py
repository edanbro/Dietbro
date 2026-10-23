"""foods and recipes: iron, calcium, potassium, vitamins C and D, folate and B12

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-23 18:00:00.000000

Filled by the importers (`make seed` again: USDA and CoFID values; recipes add them up).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = (
    "iron_mg",
    "calcium_mg",
    "potassium_mg",
    "vitamin_c_mg",
    "vitamin_d_ug",
    "folate_ug",
    "vitamin_b12_ug",
)


def upgrade() -> None:
    for table in ("foods", "recipes"):
        for column in COLUMNS:
            op.add_column(table, sa.Column(column, sa.Float(), nullable=True))


def downgrade() -> None:
    for table in ("foods", "recipes"):
        for column in COLUMNS:
            op.drop_column(table, column)
