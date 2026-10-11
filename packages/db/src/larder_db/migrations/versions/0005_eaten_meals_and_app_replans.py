"""eaten meals (recipe, pantry taken) and plan-screen replans (client id)

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-11 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cravings", sa.Column("client_id", sa.UUID(), nullable=True))
    op.create_unique_constraint(
        op.f("uq_cravings_user_id_client_id_change_key"),
        "cravings",
        ["user_id", "client_id", "change_key"],
    )
    op.add_column("meal_logs", sa.Column("recipe_id", sa.Integer(), nullable=True))
    op.add_column(
        "meal_logs",
        sa.Column(
            "pantry_taken",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        op.f("fk_meal_logs_recipe_id_recipes"),
        "meal_logs",
        "recipes",
        ["recipe_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_meal_logs_recipe_id_recipes"), "meal_logs", type_="foreignkey")
    op.drop_column("meal_logs", "pantry_taken")
    op.drop_column("meal_logs", "recipe_id")
    op.drop_constraint(op.f("uq_cravings_user_id_client_id_change_key"), "cravings", type_="unique")
    op.drop_column("cravings", "client_id")
