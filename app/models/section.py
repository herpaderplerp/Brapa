import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class RideSection(Base):
    """A named highlight stretch of a ride.

    Bounds are stored as RidePoint.seq indices into the *downsampled* point
    series (the same series the map polyline renders and that two map clicks
    resolve to), so the slice is start_seq <= seq <= end_seq. Name only — no
    per-section stats are stored; the section page derives its display from the
    point slice.
    """

    __tablename__ = "ride_section"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ride_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ride.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(140))
    start_seq: Mapped[int] = mapped_column(Integer)
    end_seq: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    ride = relationship("Ride", back_populates="sections")
