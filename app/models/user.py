import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# Profile discoverability (who can find you via search / open your profile cold).
DISCOVER_EVERYONE = "everyone"
DISCOVER_FOF = "fof"  # friends of friends (shared mutual friend)
DISCOVER_PRIVATE = "private"  # nobody; reachable only by existing friends/direct invite
DISCOVER_CHOICES = (DISCOVER_EVERYONE, DISCOVER_FOF, DISCOVER_PRIVATE)


class User(Base):
    __tablename__ = "user"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str | None] = mapped_column(String(320))
    display_name: Mapped[str | None] = mapped_column(String(80))
    home_region: Mapped[str | None] = mapped_column(String(120))
    avatar_url: Mapped[str | None] = mapped_column(String(512))
    # Unit preferences. distance: "km" | "mi"; temp: "C" | "F".
    unit_distance: Mapped[str] = mapped_column(String(2), default="km")
    unit_temp: Mapped[str] = mapped_column(String(1), default="C")
    discoverability: Mapped[str] = mapped_column(String(10), default=DISCOVER_EVERYONE)
    # Per-event email notification preferences (US-34).
    email_on_friend_request: Mapped[bool] = mapped_column(Boolean, default=True)
    email_on_friend_accept: Mapped[bool] = mapped_column(Boolean, default=True)
    email_on_like: Mapped[bool] = mapped_column(Boolean, default=False)
    email_on_comment: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    oauth_accounts: Mapped[list["OAuthAccount"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    privacy_zones = relationship(
        "PrivacyZone", back_populates="user", cascade="all, delete-orphan",
        order_by="PrivacyZone.created_at",
    )

    @property
    def is_onboarded(self) -> bool:
        """Profile setup is complete once a display name is set."""
        return bool(self.display_name)


class OAuthAccount(Base):
    __tablename__ = "oauth_account"
    __table_args__ = (
        UniqueConstraint("provider", "provider_account_id", name="uq_oauth_provider_account"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(40))
    provider_account_id: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="oauth_accounts")
