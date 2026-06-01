"""ride, ride_point, ride_weather tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-31
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, UUID

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ride",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("bike_id", UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(140), nullable=True),
        sa.Column("description_md", sa.Text(), nullable=True),
        sa.Column("visibility", sa.String(10), nullable=False, server_default="private"),
        sa.Column("road_tags", ARRAY(sa.String()), nullable=False, server_default="{}"),
        sa.Column("mood_tags", ARRAY(sa.String()), nullable=False, server_default="{}"),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_lat", sa.Float(), nullable=True),
        sa.Column("start_lon", sa.Float(), nullable=True),
        sa.Column("start_region", sa.String(160), nullable=True),
        sa.Column("distance_m", sa.Float(), nullable=True),
        sa.Column("moving_time_s", sa.Float(), nullable=True),
        sa.Column("elapsed_time_s", sa.Float(), nullable=True),
        sa.Column("max_speed", sa.Float(), nullable=True),
        sa.Column("avg_moving_speed", sa.Float(), nullable=True),
        sa.Column("elev_gain", sa.Float(), nullable=True),
        sa.Column("elev_loss", sa.Float(), nullable=True),
        sa.Column("max_elev", sa.Float(), nullable=True),
        sa.Column("gpx_blob_key", sa.String(255), nullable=True),
        sa.Column("dedup_hash", sa.String(64), nullable=True),
        sa.Column("processing_status", sa.String(16), nullable=False, server_default="processing"),
        sa.Column("processing_error", sa.String(255), nullable=True),
        sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["bike_id"], ["bike.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_ride_user_id", "ride", ["user_id"])
    op.create_index("ix_ride_dedup_hash", "ride", ["dedup_hash"])
    # PostGIS geometry column + spatial index (raw SQL avoids ORM-event quirks).
    op.execute("ALTER TABLE ride ADD COLUMN track geometry(LineStringZ, 4326)")
    op.execute("CREATE INDEX ix_ride_track ON ride USING GIST (track)")

    op.create_table(
        "ride_point",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ride_id", UUID(as_uuid=True), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("elev", sa.Float(), nullable=True),
        sa.Column("speed", sa.Float(), nullable=True),
        sa.Column("t", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["ride_id"], ["ride.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_ride_point_ride_id", "ride_point", ["ride_id"])

    op.create_table(
        "ride_weather",
        sa.Column("ride_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="ok"),
        sa.Column("sky", sa.String(20), nullable=True),
        sa.Column("temp_c", sa.Float(), nullable=True),
        sa.Column("wind_speed", sa.Float(), nullable=True),
        sa.Column("wind_dir", sa.Float(), nullable=True),
        sa.Column("humidity", sa.Float(), nullable=True),
        sa.Column("visibility", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["ride_id"], ["ride.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("ride_weather")
    op.drop_index("ix_ride_point_ride_id", table_name="ride_point")
    op.drop_table("ride_point")
    op.drop_index("ix_ride_track", table_name="ride")
    op.drop_index("ix_ride_dedup_hash", table_name="ride")
    op.drop_index("ix_ride_user_id", table_name="ride")
    op.drop_table("ride")
