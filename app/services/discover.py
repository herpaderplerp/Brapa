"""Discovery: find public rides near a place/bbox (US-31) and rank popular
routes by engagement (US-32). Privacy enforced via social.discoverable_clause."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ride import Ride
from app.models.social import Comment, Like
from app.services import social

Bbox = tuple[float, float, float, float]  # (min_lon, min_lat, max_lon, max_lat)


def _envelope(bbox: Bbox):
    return func.ST_MakeEnvelope(bbox[0], bbox[1], bbox[2], bbox[3], 4326)


async def rides_in_bbox(
    db: AsyncSession, viewer_id: uuid.UUID, bbox: Bbox, *, limit: int = 50
) -> list[Ride]:
    fids = await social.friend_ids(db, viewer_id)
    stmt = (
        select(Ride)
        .where(
            social.discoverable_clause(viewer_id, fids),
            Ride.track.isnot(None),
            func.ST_Intersects(Ride.track, _envelope(bbox)),
        )
        .order_by(Ride.start_time.desc().nullslast())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


def _like_col():
    return (
        select(func.count(Like.id))
        .where(Like.ride_id == Ride.id)
        .correlate(Ride)
        .scalar_subquery()
    )


def _comment_col():
    return (
        select(func.count(Comment.id))
        .where(Comment.ride_id == Ride.id)
        .correlate(Ride)
        .scalar_subquery()
    )


async def popular_rides(
    db: AsyncSession,
    viewer_id: uuid.UUID,
    *,
    bbox: Bbox | None = None,
    page: int = 1,
    per_page: int = 15,
) -> tuple[list[tuple[Ride, int, int]], bool]:
    fids = await social.friend_ids(db, viewer_id)
    likes = _like_col()
    comments = _comment_col()
    stmt = select(Ride, likes.label("likes"), comments.label("comments")).where(
        social.discoverable_clause(viewer_id, fids)
    )
    if bbox is not None:
        stmt = stmt.where(Ride.track.isnot(None), func.ST_Intersects(Ride.track, _envelope(bbox)))
    offset = (page - 1) * per_page
    stmt = stmt.order_by((likes + comments).desc(), Ride.created_at.desc()).offset(offset).limit(
        per_page + 1
    )
    rows = (await db.execute(stmt)).all()
    has_next = len(rows) > per_page
    cards = [(r[0], r[1], r[2]) for r in rows[:per_page]]
    return cards, has_next
