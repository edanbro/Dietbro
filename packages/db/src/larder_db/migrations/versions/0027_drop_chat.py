"""drop the chat: chat_threads, chat_messages and the columns pointing at them; the chat turn
lock on users becomes the replan lock (one plan change per user at a time)

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-30 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_cravings_message_id_change_key", "cravings", type_="unique")
    op.drop_constraint("fk_cravings_message_id_chat_messages", "cravings", type_="foreignkey")
    op.drop_column("cravings", "message_id")
    op.drop_column("cravings", "raw_text")
    op.drop_index("ix_llm_calls_thread_id", table_name="llm_calls")
    op.drop_constraint("fk_llm_calls_thread_id_chat_threads", "llm_calls", type_="foreignkey")
    op.drop_column("llm_calls", "thread_id")
    op.drop_table("chat_messages")
    op.drop_table("chat_threads")
    op.drop_column("users", "chat_turn_message_id")
    op.alter_column("users", "chat_turn_token", new_column_name="replan_lock_token")
    op.alter_column("users", "chat_turn_started_at", new_column_name="replan_lock_at")


def downgrade() -> None:
    # The structure comes back empty: the conversations themselves are gone.
    op.alter_column("users", "replan_lock_at", new_column_name="chat_turn_started_at")
    op.alter_column("users", "replan_lock_token", new_column_name="chat_turn_token")
    op.add_column("users", sa.Column("chat_turn_message_id", sa.Integer(), nullable=True))
    op.create_table(
        "chat_threads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_chat_threads_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chat_threads"),
    )
    op.create_index("ix_chat_threads_user_updated", "chat_threads", ["user_id", "updated_at"])
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("thread_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("client_id", sa.UUID(), nullable=True),
        sa.Column("today", sa.Date(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("api_messages", sa.JSON(), nullable=False),
        sa.Column("api_epoch", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=True),
        sa.Column("offline_reason", sa.String(length=16), nullable=True),
        sa.Column("attachments", JSONB(), nullable=False),
        sa.Column("suggestions", JSONB(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["meal_plans.id"],
            name="fk_chat_messages_plan_id_meal_plans",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"],
            ["chat_threads.id"],
            name="fk_chat_messages_thread_id_chat_threads",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_chat_messages_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chat_messages"),
        sa.UniqueConstraint("user_id", "client_id", name="uq_chat_messages_user_id_client_id"),
    )
    op.create_index(
        "ix_chat_messages_plan_id",
        "chat_messages",
        ["plan_id"],
        postgresql_where=sa.text("plan_id IS NOT NULL"),
    )
    op.create_index("ix_chat_messages_thread_id_id", "chat_messages", ["thread_id", "id"])
    op.create_index(
        "ix_chat_messages_user_created_user_role",
        "chat_messages",
        ["user_id", "created_at"],
        postgresql_where=sa.text("role = 'user'"),
    )
    op.add_column("llm_calls", sa.Column("thread_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_llm_calls_thread_id_chat_threads",
        "llm_calls",
        "chat_threads",
        ["thread_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_llm_calls_thread_id",
        "llm_calls",
        ["thread_id"],
        postgresql_where=sa.text("thread_id IS NOT NULL"),
    )
    op.add_column("cravings", sa.Column("raw_text", sa.Text(), server_default="", nullable=False))
    op.add_column("cravings", sa.Column("message_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_cravings_message_id_chat_messages",
        "cravings",
        "chat_messages",
        ["message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_cravings_message_id_change_key", "cravings", ["message_id", "change_key"]
    )
