"""Friendship graph + ride-visibility rules.

Privacy is enforced here (NFR): private rides never leak, friends-only rides are
gated server-side, not just hidden in templates.
"""
from __future__ import annotations

import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ride import VISIBILITY_FRIENDS, VISIBILITY_PUBLIC, Ride
from app.models.social import FRIEND_ACCEPTED, FRIEND_PENDING, Friendship


async def friendship_between(
    db: AsyncSession, a: uuid.UUID, b: uuid.UUID
) -> Friendship | None:
    return (
        await db.execute(
            select(Friendship).where(
                or_(
                    and_(Friendship.requester_id == a, Friendship.addressee_id == b),
                    and_(Friendship.requester_id == b, Friendship.addressee_id == a),
                )
            )
        )
    ).scalar_one_or_none()


async def friend_ids(db: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    rows = (
        await db.execute(
            select(Friendship).where(
                Friendship.status == FRIEND_ACCEPTED,
                or_(
                    Friendship.requester_id == user_id,
                    Friendship.addressee_id == user_id,
                ),
            )
        )
    ).scalars().all()
    out: set[uuid.UUID] = set()
    for f in rows:
        out.add(f.addressee_id if f.requester_id == user_id else f.requester_id)
    return out


async def are_friends(db: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> bool:
    f = await friendship_between(db, a, b)
    return f is not None and f.status == FRIEND_ACCEPTED


async def send_request(
    db: AsyncSession, requester_id: uuid.UUID, addressee_id: uuid.UUID
) -> Friendship | None:
    if requester_id == addressee_id:
        return None
    existing = await friendship_between(db, requester_id, addressee_id)
    if existing:
        # If the other side already requested, accept it (mutual).
        if existing.status == FRIEND_PENDING and existing.requester_id == addressee_id:
            existing.status = FRIEND_ACCEPTED
            db.add(existing)
            await _notify(db, recipient_id=addressee_id, type="friend_accept", actor_id=requester_id)
        return existing
    f = Friendship(requester_id=requester_id, addressee_id=addressee_id, status=FRIEND_PENDING)
    db.add(f)
    await db.flush()
    await _notify(db, recipient_id=addressee_id, type="friend_request", actor_id=requester_id)
    return f


async def accept(db: AsyncSession, friendship: Friendship) -> None:
    friendship.status = FRIEND_ACCEPTED
    db.add(friendship)
    await _notify(
        db,
        recipient_id=friendship.requester_id,
        type="friend_accept",
        actor_id=friendship.addressee_id,
    )


async def _notify(db: AsyncSession, **kwargs) -> None:
    # Local import avoids a module-load cycle (notify imports models only).
    from app.services import notify

    await notify.create(db, **kwargs)


async def remove(db: AsyncSession, friendship: Friendship) -> None:
    await db.delete(friendship)


async def list_friends(db: AsyncSession, user_id: uuid.UUID) -> list:
    ids = await friend_ids(db, user_id)
    if not ids:
        return []
    from app.models.user import User

    return list(
        (await db.execute(select(User).where(User.id.in_(ids)).order_by(User.display_name)))
        .scalars()
        .all()
    )


async def pending_incoming(db: AsyncSession, user_id: uuid.UUID) -> list[Friendship]:
    return list(
        (
            await db.execute(
                select(Friendship).where(
                    Friendship.addressee_id == user_id, Friendship.status == FRIEND_PENDING
                )
            )
        )
        .scalars()
        .all()
    )


async def pending_outgoing(db: AsyncSession, user_id: uuid.UUID) -> list[Friendship]:
    return list(
        (
            await db.execute(
                select(Friendship).where(
                    Friendship.requester_id == user_id, Friendship.status == FRIEND_PENDING
                )
            )
        )
        .scalars()
        .all()
    )


async def can_discover(db: AsyncSession, viewer_id: uuid.UUID, target) -> bool:
    """Whether viewer may find/open target's profile, per target.discoverability.
    Existing friends and pending direct invites always can; 'fof' needs a shared mutual friend;
    'private' nobody else."""
    from app.models.user import DISCOVER_EVERYONE, DISCOVER_FOF

    if viewer_id == target.id:
        return True
    if target.discoverability == DISCOVER_EVERYONE:
        return True
    friendship = await friendship_between(db, viewer_id, target.id)
    if friendship is not None and friendship.status in (FRIEND_ACCEPTED, FRIEND_PENDING):
        return True
    if target.discoverability == DISCOVER_FOF:
        mine = await friend_ids(db, viewer_id)
        theirs = await friend_ids(db, target.id)
        return bool(mine & theirs)  # at least one mutual friend
    return False  # private


async def can_view_ride(db: AsyncSession, viewer_id: uuid.UUID | None, ride: Ride) -> bool:
    if viewer_id is not None and ride.user_id == viewer_id:
        return True
    if not ride.published:
        return False
    if ride.visibility == VISIBILITY_PUBLIC:
        return True
    if ride.visibility == VISIBILITY_FRIENDS and viewer_id is not None:
        return await are_friends(db, viewer_id, ride.user_id)
    return False


def visible_rides_clause(viewer_id: uuid.UUID | None, owner_id: uuid.UUID, friend_id_set: set):
    """WHERE clause for owner_id's rides that viewer may see (for profile/feed)."""
    if viewer_id == owner_id:
        return Ride.user_id == owner_id
    allowed = [Ride.visibility == VISIBILITY_PUBLIC]
    if viewer_id is not None and owner_id in friend_id_set:
        allowed.append(Ride.visibility == VISIBILITY_FRIENDS)
    return and_(Ride.user_id == owner_id, Ride.published.is_(True), or_(*allowed))


def discoverable_clause(viewer_id: uuid.UUID | None, friend_id_set: set):
    """Global visibility clause (across all owners) for discovery queries:
    published rides that are public, the viewer's own, or a friend's friends-only."""
    from app.models.ride import STATUS_DONE, STATUS_DUPLICATE

    allowed = [Ride.visibility == VISIBILITY_PUBLIC]
    if viewer_id is not None:
        allowed.append(Ride.user_id == viewer_id)
        if friend_id_set:
            allowed.append(
                and_(Ride.visibility == VISIBILITY_FRIENDS, Ride.user_id.in_(friend_id_set))
            )
    return and_(
        Ride.published.is_(True),
        Ride.processing_status.in_([STATUS_DONE, STATUS_DUPLICATE]),
        or_(*allowed),
    )
