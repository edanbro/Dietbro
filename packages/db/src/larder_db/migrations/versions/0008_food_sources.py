"""food sources: USDA survey foods, UK CoFID and Open Food Facts products next to USDA

USDA rows keep `id` = FDC id (all below 1e9). Other sources take ids from `foods_local_id_seq`
(1e9 and up). `generic_food_id` links a regional or branded food to the generic USDA food it
"counts as" for planning (pantry matching, prices, shelf life); recipes only use generics.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-13 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOCAL_ID_START = 1_000_000_000


def upgrade() -> None:
    op.execute(
        f"CREATE SEQUENCE foods_local_id_seq START {LOCAL_ID_START} MINVALUE {LOCAL_ID_START} "
        "MAXVALUE 2147483647 OWNED BY foods.id"
    )
    op.add_column(
        "foods",
        sa.Column("source", sa.String(length=16), server_default="usda", nullable=False),
    )
    op.add_column("foods", sa.Column("source_id", sa.String(length=32), nullable=True))
    op.add_column("foods", sa.Column("source_category", sa.Text(), nullable=True))
    op.add_column("foods", sa.Column("brand", sa.Text(), nullable=True))
    op.add_column("foods", sa.Column("barcode", sa.String(length=14), nullable=True))
    op.add_column(
        "foods", sa.Column("countries", postgresql.ARRAY(sa.String(length=2)), nullable=True)
    )
    op.add_column("foods", sa.Column("generic_food_id", sa.Integer(), nullable=True))
    op.add_column("foods", sa.Column("generic_method", sa.String(length=16), nullable=True))
    op.add_column(
        "foods",
        sa.Column("allergens_declared", postgresql.ARRAY(sa.String(length=32)), nullable=True),
    )
    op.add_column(
        "foods",
        sa.Column("traces_declared", postgresql.ARRAY(sa.String(length=32)), nullable=True),
    )
    op.add_column("foods", sa.Column("ingredients_text", sa.Text(), nullable=True))
    op.add_column("foods", sa.Column("origin", sa.String(length=8), nullable=True))
    op.add_column("foods", sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "foods",
        sa.Column(
            "search_tsv",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('english'::regconfig, coalesce(brand, '') || ' ' || description)",
                persisted=True,
            ),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_foods_generic_food_id_foods",
        "foods",
        "foods",
        ["generic_food_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint("uq_foods_source_source_id", "foods", ["source", "source_id"])
    op.create_index(
        "uq_foods_barcode",
        "foods",
        ["barcode"],
        unique=True,
        postgresql_where=sa.text("barcode IS NOT NULL"),
    )
    op.create_index("ix_foods_generic_food_id", "foods", ["generic_food_id"])
    op.create_index("ix_foods_countries", "foods", ["countries"], postgresql_using="gin")
    op.create_index("ix_foods_search_tsv", "foods", ["search_tsv"], postgresql_using="gin")
    op.create_check_constraint(
        "ck_foods_usda_ids", "foods", f"(source = 'usda') = (id < {LOCAL_ID_START})"
    )
    op.create_check_constraint(
        "ck_foods_generic_not_self", "foods", "generic_food_id IS NULL OR generic_food_id <> id"
    )


def downgrade() -> None:
    # Only safe before any non-USDA food is in a pantry or on a receipt (those reference foods).
    op.execute(f"DELETE FROM foods WHERE id >= {LOCAL_ID_START}")
    op.drop_constraint("ck_foods_generic_not_self", "foods", type_="check")
    op.drop_constraint("ck_foods_usda_ids", "foods", type_="check")
    op.drop_index("ix_foods_search_tsv", table_name="foods")
    op.drop_index("ix_foods_countries", table_name="foods")
    op.drop_index("ix_foods_generic_food_id", table_name="foods")
    op.drop_index("uq_foods_barcode", table_name="foods")
    op.drop_constraint("uq_foods_source_source_id", "foods", type_="unique")
    op.drop_constraint("fk_foods_generic_food_id_foods", "foods", type_="foreignkey")
    for column in (
        "search_tsv",
        "retired_at",
        "origin",
        "ingredients_text",
        "traces_declared",
        "allergens_declared",
        "generic_method",
        "generic_food_id",
        "countries",
        "barcode",
        "brand",
        "source_category",
        "source_id",
        "source",
    ):
        op.drop_column("foods", column)
    op.execute("DROP SEQUENCE IF EXISTS foods_local_id_seq")
