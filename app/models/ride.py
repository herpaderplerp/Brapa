import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# Processing lifecycle for an uploaded GPX.
STATUS_PROCESSING = "processing"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_DUPLICATE = "duplicate"

VISIBILITY_PUBLIC = "public"
VISIBILITY_FRIENDS = "friends"
VISIBILITY_PRIVATE = "private"


class Ride(Base):
    __tablename__ = "ride"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    bike_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bike.id", ondelete="SET NULL"), nullable=True
    )

    title: Mapped[str | None] = mapped_column(String(140))
    description_md: Mapped[str | None] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(String(10), default=VISIBILITY_PRIVATE)
    road_tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    mood_tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)

    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    start_lat: Mapped[float | None] = mapped_column(Float)
    start_lon: Mapped[float | None] = mapped_column(Float)
    start_region: Mapped[str | None] = mapped_column(String(160))

    # Full-resolution track for future segment matching / spatial search.
    track = mapped_column(Geometry("LINESTRINGZ", srid=4326), nullable=True)

    distance_m: Mapped[float | None] = mapped_column(Float)
    moving_time_s: Mapped[float | None] = mapped_column(Float)
    elapsed_time_s: Mapped[float | None] = mapped_column(Float)
    max_speed: Mapped[float | None] = mapped_column(Float)  # m/s
    avg_moving_speed: Mapped[float | None] = mapped_column(Float)  # m/s
    elev_gain: Mapped[float | None] = mapped_column(Float)
    elev_loss: Mapped[float | None] = mapped_column(Float)
    max_elev: Mapped[float | None] = mapped_column(Float)

    gpx_blob_key: Mapped[str | None] = mapped_column(String(255))
    dedup_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    processing_status: Mapped[str] = mapped_column(String(16), default=STATUS_PROCESSING)
    processing_error: Mapped[str | None] = mapped_column(String(255))
    published: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # selectin so templates can read these on an async session without lazy IO.
    bike = relationship("Bike", lazy="selectin")
    points: Mapped[list["RidePoint"]] = relationship(
        back_populates="ride", cascade="all, delete-orphan", order_by="RidePoint.seq"
    )
    weather: Mapped["RideWeather | None"] = relationship(
        back_populates="ride", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )


class RidePoint(Base):
    __tablename__ = "ride_point"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ride_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ride.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    elev: Mapped[float | None] = mapped_column(Float)
    speed: Mapped[float | None] = mapped_column(Float)  # m/s
    t: Mapped[float | None] = mapped_column(Float)  # seconds from start

    ride = relationship("Ride", back_populates="points")


class RideWeather(Base):
    __tablename__ = "ride_weather"

    ride_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ride.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(12), default="ok")  # ok | unavailable
    sky: Mapped[str | None] = mapped_column(String(20))
    temp_c: Mapped[float | None] = mapped_column(Float)
    wind_speed: Mapped[float | None] = mapped_column(Float)  # km/h
    wind_dir: Mapped[float | None] = mapped_column(Float)  # degrees
    humidity: Mapped[float | None] = mapped_column(Float)  # %
    visibility: Mapped[float | None] = mapped_column(Float)  # meters

    ride = relationship("Ride", back_populates="weather")
