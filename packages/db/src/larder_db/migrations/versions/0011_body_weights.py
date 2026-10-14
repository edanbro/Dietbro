"""body_weights: the user's weigh-ins, one per day (progress chart; the newest is the body
profile's weight)

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-14 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "body_weights",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("measured_on", sa.Date(), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "measured_on"),
    )


def downgrade() -> None:
    op.drop_table("body_weights")
