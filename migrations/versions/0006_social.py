"""friendship, ride_like, comment tables

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-01
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "friendship",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("requester_id", UUID(as_uuid=True), nullable=False),
        sa.Column("addressee_id", UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["requester_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["addressee_id"], ["user.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("requester_id", "addressee_id", name="uq_friend_pair"),
    )
    op.create_index("ix_friendship_requester_id", "friendship", ["requester_id"])
    op.create_index("ix_friendship_addressee_id", "friendship", ["addressee_id"])

    op.create_table(
        "ride_like",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("ride_id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ride_id"], ["ride.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "ride_id", name="uq_like_user_ride"),
    )
    op.create_index("ix_ride_like_user_id", "ride_like", ["user_id"])
    op.create_index("ix_ride_like_ride_id", "ride_like", ["ride_id"])

    op.create_table(
        "comment",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("ride_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", UUID(as_uuid=True), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["ride_id"], ["ride.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["comment.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_comment_ride_id", "comment", ["ride_id"])
    op.create_index("ix_comment_user_id", "comment", ["user_id"])


def downgrade() -> None:
    op.drop_table("comment")
    op.drop_table("ride_like")
    op.drop_table("friendship")
