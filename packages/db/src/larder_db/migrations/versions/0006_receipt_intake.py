"""receipt intake: uploads (photo or text) and the item lines read from them

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-11 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "receipt_uploads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("purchased_on", sa.Date(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("image", sa.LargeBinary(), nullable=True),
        sa.Column("image_type", sa.String(length=32), nullable=True),
        sa.Column("image_bytes", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("read_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_receipt_uploads_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_receipt_uploads")),
    )
    op.create_index("ix_receipt_uploads_user_created", "receipt_uploads", ["user_id", "created_at"])
    op.create_table(
        "receipt_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("upload_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("food_id", sa.Integer(), nullable=True),
        sa.Column("match_method", sa.String(length=16), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("grams", sa.Float(), nullable=True),
        sa.Column("approx", sa.Boolean(), nullable=False),
        sa.Column("price_minor", sa.Integer(), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("pantry_item_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["food_id"], ["foods.id"], name=op.f("fk_receipt_lines_food_id_foods")
        ),
        sa.ForeignKeyConstraint(
            ["pantry_item_id"],
            ["pantry_items.id"],
            name=op.f("fk_receipt_lines_pantry_item_id_pantry_items"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["upload_id"],
            ["receipt_uploads.id"],
            name=op.f("fk_receipt_lines_upload_id_receipt_uploads"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_receipt_lines")),
    )
    op.create_index(
        op.f("ix_receipt_lines_upload_id"), "receipt_lines", ["upload_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_receipt_lines_upload_id"), table_name="receipt_lines")
    op.drop_table("receipt_lines")
    op.drop_index("ix_receipt_uploads_user_created", table_name="receipt_uploads")
    op.drop_table("receipt_uploads")
