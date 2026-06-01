"""user discoverability setting

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-01
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("discoverability", sa.String(10), nullable=False, server_default="everyone"),
    )


def downgrade() -> None:
    op.drop_column("user", "discoverability")
