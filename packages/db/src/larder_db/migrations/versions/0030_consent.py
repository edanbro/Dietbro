"""users.terms_accepted_at, users.health_consent_at: when the terms and the health-data consent
were agreed to (NULL for accounts made before they were asked for)

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-03 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("terms_accepted_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("health_consent_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("users", "health_consent_at")
    op.drop_column("users", "terms_accepted_at")
