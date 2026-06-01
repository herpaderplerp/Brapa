"""notification table + user email prefs

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-01
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user", sa.Column("email_on_friend_request", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("user", sa.Column("email_on_friend_accept", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("user", sa.Column("email_on_like", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("user", sa.Column("email_on_comment", sa.Boolean(), nullable=False, server_default=sa.true()))

    op.create_table(
        "notification",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("actor_id", UUID(as_uuid=True), nullable=True),
        sa.Column("ride_id", UUID(as_uuid=True), nullable=True),
        sa.Column("comment_id", UUID(as_uuid=True), nullable=True),
        sa.Column("read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ride_id"], ["ride.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["comment_id"], ["comment.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_notification_user_id", "notification", ["user_id"])
    op.create_index("ix_notification_read", "notification", ["read"])
    op.create_index("ix_notification_user_unread", "notification", ["user_id", "read"])


def downgrade() -> None:
    op.drop_table("notification")
    op.drop_column("user", "email_on_comment")
    op.drop_column("user", "email_on_like")
    op.drop_column("user", "email_on_friend_accept")
    op.drop_column("user", "email_on_friend_request")
