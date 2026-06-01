"""photo table

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-01
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "photo",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("ride_id", UUID(as_uuid=True), nullable=False),
        sa.Column("blob_key", sa.String(255), nullable=False),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["ride_id"], ["ride.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_photo_ride_id", "photo", ["ride_id"])


def downgrade() -> None:
    op.drop_index("ix_photo_ride_id", table_name="photo")
    op.drop_table("photo")
