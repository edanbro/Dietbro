"""prep ahead: pantry_items.storage (where the user keeps it), users.prep_reminders, and
push_subscriptions.ahead_sent_on (one evening heads-up a day)

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-25 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("pantry_items", sa.Column("storage", sa.String(8), nullable=True))
    op.create_check_constraint(
        "ck_pantry_items_storage",
        "pantry_items",
        "storage IS NULL OR storage IN ('fridge', 'freezer', 'cupboard')",
    )
    op.add_column(
        "users",
        sa.Column("prep_reminders", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column("push_subscriptions", sa.Column("ahead_sent_on", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("push_subscriptions", "ahead_sent_on")
    op.drop_column("users", "prep_reminders")
    op.drop_constraint("ck_pantry_items_storage", "pantry_items", type_="check")
    op.drop_column("pantry_items", "storage")
