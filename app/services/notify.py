"""In-app notifications + optional email fan-out (US-33/34)."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notify import Notification
from app.models.user import User
from app.services import email as email_svc

# Short human strings for the email body per type.
_SUBJECTS = {
    "friend_request": "New friend request on Brapa",
    "friend_accept": "Your friend request was accepted",
    "like": "Someone liked your ride",
    "comment": "New comment on your ride",
}


async def create(
    db: AsyncSession,
    *,
    recipient_id: uuid.UUID,
    type: str,
    actor_id: uuid.UUID | None = None,
    ride_id: uuid.UUID | None = None,
    comment_id: uuid.UUID | None = None,
) -> Notification | None:
    # No self-notifications.
    if actor_id is not None and actor_id == recipient_id:
        return None
    notif = Notification(
        user_id=recipient_id,
        type=type,
        actor_id=actor_id,
        ride_id=ride_id,
        comment_id=comment_id,
    )
    db.add(notif)
    await db.flush()

    # Best-effort email per recipient preference.
    recipient = await db.get(User, recipient_id)
    subject = _SUBJECTS.get(type, "Brapa notification")
    email_svc.maybe_send(recipient, type, subject, subject)
    return notif


async def unread_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count(Notification.id)).where(
                Notification.user_id == user_id, Notification.read.is_(False)
            )
        )
    ).scalar_one()


async def recent(db: AsyncSession, user_id: uuid.UUID, limit: int = 50) -> list[Notification]:
    return list(
        (
            await db.execute(
                select(Notification)
                .where(Notification.user_id == user_id)
                .order_by(Notification.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


async def mark_all_read(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read.is_(False))
        .values(read=True)
    )
