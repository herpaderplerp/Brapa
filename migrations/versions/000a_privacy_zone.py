"""add privacy_zone

Revision ID: 000a_privacy_zone
Revises: 9bfd60cfe250
Create Date: 2026-06-04
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "000a_privacy_zone"
down_revision: str | None = "9bfd60cfe250"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "privacy_zone",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("center_lat", sa.Float(), nullable=False),
        sa.Column("center_lon", sa.Float(), nullable=False),
        sa.Column("radius_m", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_privacy_zone_user_id"), "privacy_zone", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_privacy_zone_user_id"), table_name="privacy_zone")
    op.drop_table("privacy_zone")
