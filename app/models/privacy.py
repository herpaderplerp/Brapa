import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class PrivacyZone(Base):
    """A circular area (center + radius) belonging to a user. Any ride track of
    theirs passing within the radius is clipped out for *other* viewers — the
    owner always sees their full track. Applied at read time, so zones added or
    edited later retroactively protect existing rides without mutating stored
    data. See app/services/privacy.py.
    """

    __tablename__ = "privacy_zone"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(80), default="Zone")
    center_lat: Mapped[float] = mapped_column(Float)
    center_lon: Mapped[float] = mapped_column(Float)
    radius_m: Mapped[float] = mapped_column(Float, default=250.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user = relationship("User", back_populates="privacy_zones")
