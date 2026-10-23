"""weekly recap: users.weekly_recap (on by default), push_subscriptions.recap_sent_on

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-24 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("weekly_recap", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column("push_subscriptions", sa.Column("recap_sent_on", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("push_subscriptions", "recap_sent_on")
    op.drop_column("users", "weekly_recap")
