"""user and oauth_account tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-31
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("display_name", sa.String(80), nullable=True),
        sa.Column("home_region", sa.String(120), nullable=True),
        sa.Column("avatar_url", sa.String(512), nullable=True),
        sa.Column("unit_distance", sa.String(2), nullable=False, server_default="km"),
        sa.Column("unit_temp", sa.String(1), nullable=False, server_default="C"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "oauth_account",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("provider_account_id", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "provider", "provider_account_id", name="uq_oauth_provider_account"
        ),
    )
    op.create_index("ix_oauth_account_user_id", "oauth_account", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_oauth_account_user_id", table_name="oauth_account")
    op.drop_table("oauth_account")
    op.drop_table("user")
