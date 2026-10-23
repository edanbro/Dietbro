"""recipes.minutes: about how long a recipe takes, estimated from its method

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-25 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BATCH = 500


def upgrade() -> None:
    op.add_column("recipes", sa.Column("minutes", sa.SmallInteger(), nullable=True))
    # Backfill with the estimator as it is today (a later change to it re-runs its own
    # backfill). Imported here, not at the top: only this data step needs it.
    from larder_core.cook_time import cook_minutes

    recipes = sa.table(
        "recipes",
        sa.column("id", sa.Integer()),
        sa.column("instructions", sa.Text()),
        sa.column("minutes", sa.SmallInteger()),
    )
    conn = op.get_bind()
    rows = conn.execute(sa.select(recipes.c.id, recipes.c.instructions)).all()
    estimates = ((rid, cook_minutes(text or "")) for rid, text in rows)
    values = [{"rid": rid, "m": m} for rid, m in estimates if m is not None]
    update = (
        sa.update(recipes)
        .where(recipes.c.id == sa.bindparam("rid"))
        .values(minutes=sa.bindparam("m"))
    )
    for start in range(0, len(values), BATCH):
        conn.execute(update, values[start : start + BATCH])


def downgrade() -> None:
    op.drop_column("recipes", "minutes")
