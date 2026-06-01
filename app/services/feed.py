"""Feed, likes, and comments."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ride import (
    STATUS_DONE,
    STATUS_DUPLICATE,
    VISIBILITY_FRIENDS,
    VISIBILITY_PUBLIC,
    Ride,
)
from app.models.social import Comment, Like
from app.services import social


@dataclass
class CommentNode:
    comment: Comment
    replies: list = field(default_factory=list)


async def like_count(db: AsyncSession, ride_id: uuid.UUID) -> int:
    return (
        await db.execute(select(func.count(Like.id)).where(Like.ride_id == ride_id))
    ).scalar_one()


async def has_liked(db: AsyncSession, ride_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return (
        await db.execute(
            select(Like.id).where(Like.ride_id == ride_id, Like.user_id == user_id)
        )
    ).first() is not None


async def toggle_like(db: AsyncSession, ride_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    existing = (
        await db.execute(
            select(Like).where(Like.ride_id == ride_id, Like.user_id == user_id)
        )
    ).scalar_one_or_none()
    if existing:
        await db.delete(existing)
        return False
    db.add(Like(ride_id=ride_id, user_id=user_id))
    return True


async def comments_tree(db: AsyncSession, ride_id: uuid.UUID) -> list[CommentNode]:
    rows = (
        await db.execute(
            select(Comment).where(Comment.ride_id == ride_id).order_by(Comment.created_at)
        )
    ).scalars().all()
    nodes: dict[uuid.UUID, CommentNode] = {c.id: CommentNode(comment=c) for c in rows}
    roots: list[CommentNode] = []
    for c in rows:
        if c.parent_id and c.parent_id in nodes:
            nodes[c.parent_id].replies.append(nodes[c.id])
        else:
            roots.append(nodes[c.id])
    return roots


async def add_comment(
    db: AsyncSession,
    ride_id: uuid.UUID,
    user_id: uuid.UUID,
    body: str,
    parent_id: uuid.UUID | None = None,
) -> Comment | None:
    body = body.strip()
    if not body:
        return None
    # Only allow replies to a top-level comment on the same ride (one level deep).
    if parent_id:
        parent = await db.get(Comment, parent_id)
        if parent is None or parent.ride_id != ride_id or parent.parent_id is not None:
            parent_id = None
    c = Comment(ride_id=ride_id, user_id=user_id, body=body[:2000], parent_id=parent_id)
    db.add(c)
    await db.flush()
    return c


async def ride_social(db: AsyncSession, ride_id: uuid.UUID, user_id: uuid.UUID):
    return (
        await like_count(db, ride_id),
        await has_liked(db, ride_id, user_id),
        await comments_tree(db, ride_id),
    )


async def track_thumb(
    db: AsyncSession, ride_id: uuid.UUID, w: int = 260, h: int = 120, pad: int = 8
) -> str | None:
    """Normalized SVG polyline points for a mini route thumbnail (keyless)."""
    from app.models.ride import RidePoint

    rows = (
        await db.execute(
            select(RidePoint.lat, RidePoint.lon)
            .where(RidePoint.ride_id == ride_id)
            .order_by(RidePoint.seq)
        )
    ).all()
    if len(rows) < 2:
        return None
    # Sub-sample to at most ~120 points for a light SVG.
    step = max(1, len(rows) // 120)
    pts = rows[::step]
    lats = [r[0] for r in pts]
    lons = [r[1] for r in pts]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    span_lat = (max_lat - min_lat) or 1e-6
    span_lon = (max_lon - min_lon) or 1e-6
    iw, ih = w - 2 * pad, h - 2 * pad
    coords = []
    for lat, lon in zip(lats, lons):
        x = pad + (lon - min_lon) / span_lon * iw
        y = pad + (1 - (lat - min_lat) / span_lat) * ih  # invert y (north up)
        coords.append(f"{x:.1f},{y:.1f}")
    return " ".join(coords)


async def feed(
    db: AsyncSession,
    viewer_id: uuid.UUID,
    *,
    page: int = 1,
    per_page: int = 15,
    friend_id: uuid.UUID | None = None,
    road_tag: str | None = None,
):
    """Friends' published rides newest-first. Returns (cards, has_next) where each
    card is (ride, author_id, like_count, comment_count, liked)."""
    fids = await social.friend_ids(db, viewer_id)
    if not fids:
        return [], False
    authors = {friend_id} if (friend_id and friend_id in fids) else fids

    clause = and_(
        Ride.user_id.in_(authors),
        Ride.published.is_(True),
        Ride.processing_status.in_([STATUS_DONE, STATUS_DUPLICATE]),
        or_(Ride.visibility == VISIBILITY_PUBLIC, Ride.visibility == VISIBILITY_FRIENDS),
    )
    if road_tag:
        clause = and_(clause, Ride.road_tags.any(road_tag))

    offset = (page - 1) * per_page
    rides = (
        await db.execute(
            select(Ride)
            .where(clause)
            .order_by(Ride.start_time.desc().nullslast(), Ride.created_at.desc())
            .offset(offset)
            .limit(per_page + 1)
        )
    ).scalars().all()
    has_next = len(rides) > per_page
    rides = rides[:per_page]

    cards = []
    for r in rides:
        lc = await like_count(db, r.id)
        cc = (
            await db.execute(select(func.count(Comment.id)).where(Comment.ride_id == r.id))
        ).scalar_one()
        liked = await has_liked(db, r.id, viewer_id)
        cards.append((r, r.user_id, lc, cc, liked))
    return cards, has_next
