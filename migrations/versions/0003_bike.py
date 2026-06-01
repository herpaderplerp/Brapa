"""bike table

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-31
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bike",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("make", sa.String(60), nullable=False),
        sa.Column("model", sa.String(60), nullable=False),
        sa.Column("nickname", sa.String(60), nullable=True),
        sa.Column("photo_url", sa.String(512), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_bike_user_id", "bike", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_bike_user_id", table_name="bike")
    op.drop_table("bike")
