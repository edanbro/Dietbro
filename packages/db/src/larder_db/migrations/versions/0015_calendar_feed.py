"""users.calendar_token and calendar_times: a private calendar feed of planned meals

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-20 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("calendar_token", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("calendar_times", postgresql.JSONB(), nullable=True))
    op.create_unique_constraint("uq_users_calendar_token", "users", ["calendar_token"])


def downgrade() -> None:
    op.drop_constraint("uq_users_calendar_token", "users", type_="unique")
    op.drop_column("users", "calendar_times")
    op.drop_column("users", "calendar_token")
