"""Aggregate ride stats for profile pages (lifetime + per-bike)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bike import Bike
from app.models.ride import STATUS_DONE, Ride


@dataclass
class LifetimeStats:
    rides: int
    distance_m: float
    elev_gain: float
    moving_time_s: float


@dataclass
class BikeStats:
    bike: Bike
    rides: int
    distance_m: float
    moving_time_s: float


def _published(user_id: uuid.UUID):
    return (Ride.user_id == user_id, Ride.published.is_(True), Ride.processing_status == STATUS_DONE)


async def lifetime_stats(db: AsyncSession, user_id: uuid.UUID) -> LifetimeStats:
    row = (
        await db.execute(
            select(
                func.count(Ride.id),
                func.coalesce(func.sum(Ride.distance_m), 0.0),
                func.coalesce(func.sum(Ride.elev_gain), 0.0),
                func.coalesce(func.sum(Ride.moving_time_s), 0.0),
            ).where(*_published(user_id))
        )
    ).one()
    return LifetimeStats(rides=row[0], distance_m=row[1], elev_gain=row[2], moving_time_s=row[3])


async def per_bike_stats(db: AsyncSession, user_id: uuid.UUID) -> list[BikeStats]:
    rows = (
        await db.execute(
            select(
                Bike,
                func.count(Ride.id),
                func.coalesce(func.sum(Ride.distance_m), 0.0),
                func.coalesce(func.sum(Ride.moving_time_s), 0.0),
            )
            .join(Ride, Ride.bike_id == Bike.id)
            .where(*_published(user_id))
            .group_by(Bike.id)
            .order_by(func.sum(Ride.distance_m).desc())
        )
    ).all()
    return [
        BikeStats(bike=r[0], rides=r[1], distance_m=r[2], moving_time_s=r[3]) for r in rows
    ]


async def recent_rides(
    db: AsyncSession, user_id: uuid.UUID, *, page: int = 1, per_page: int = 10
) -> tuple[list[Ride], bool]:
    """Published rides newest-first, paginated. Returns (rides, has_next)."""
    offset = (page - 1) * per_page
    rows = (
        await db.execute(
            select(Ride)
            .where(*_published(user_id))
            .order_by(Ride.start_time.desc().nullslast(), Ride.created_at.desc())
            .offset(offset)
            .limit(per_page + 1)
        )
    ).scalars().all()
    has_next = len(rows) > per_page
    return rows[:per_page], has_next
