import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Bike(Base):
    __tablename__ = "bike"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    year: Mapped[int | None] = mapped_column(Integer)
    make: Mapped[str] = mapped_column(String(60))
    model: Mapped[str] = mapped_column(String(60))
    nickname: Mapped[str | None] = mapped_column(String(60))
    photo_url: Mapped[str | None] = mapped_column(String(512))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    # Inactive bikes are hidden from pickers but preserved so historical rides
    # keep their bike reference (spec US-03).
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user = relationship("User")

    @property
    def label(self) -> str:
        if self.nickname:
            return self.nickname
        parts = [str(self.year) if self.year else "", self.make, self.model]
        return " ".join(p for p in parts if p).strip() or "Bike"
