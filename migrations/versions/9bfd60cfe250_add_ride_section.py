"""add ride_section

Revision ID: 9bfd60cfe250
Revises: 0008
Create Date: 2026-06-02 16:43:46.325787

Hand-trimmed: autogenerate also surfaced the PostGIS tiger/topology system
tables (as drops) plus a spurious spatial-index rename on ride.track and the
partial notification index — none of which are real schema changes. Only the
ride_section table is kept.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9bfd60cfe250"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ride_section",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ride_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=140), nullable=False),
        sa.Column("start_seq", sa.Integer(), nullable=False),
        sa.Column("end_seq", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["ride_id"], ["ride.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ride_section_ride_id"), "ride_section", ["ride_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ride_section_ride_id"), table_name="ride_section")
    op.drop_table("ride_section")
