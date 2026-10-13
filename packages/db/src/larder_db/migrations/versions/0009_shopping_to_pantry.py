"""shopping to pantry: when a bought line was moved into the pantry, and the user's own items

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-14 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "shopping_items", sa.Column("stocked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "shopping_extras",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("checked", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_shopping_extras_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shopping_extras")),
    )
    op.create_index(
        op.f("ix_shopping_extras_user_id"), "shopping_extras", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_shopping_extras_user_id"), table_name="shopping_extras")
    op.drop_table("shopping_extras")
    op.drop_column("shopping_items", "stocked_at")
