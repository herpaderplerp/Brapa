import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

NOTIFY_FRIEND_REQUEST = "friend_request"
NOTIFY_FRIEND_ACCEPT = "friend_accept"
NOTIFY_LIKE = "like"
NOTIFY_COMMENT = "comment"

# Maps a notification type to the User email-pref column gating its email.
EMAIL_PREF_COLUMN = {
    NOTIFY_FRIEND_REQUEST: "email_on_friend_request",
    NOTIFY_FRIEND_ACCEPT: "email_on_friend_accept",
    NOTIFY_LIKE: "email_on_like",
    NOTIFY_COMMENT: "email_on_comment",
}


class Notification(Base):
    __tablename__ = "notification"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=True
    )
    ride_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ride.id", ondelete="CASCADE"), nullable=True
    )
    comment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("comment.id", ondelete="CASCADE"), nullable=True
    )
    read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    actor = relationship("User", foreign_keys=[actor_id], lazy="selectin")
