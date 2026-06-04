"""Named highlight sections of a ride.

A section is a contiguous slice of a ride's downsampled point series, picked by
clicking two points on the map. Bounds are stored as RidePoint.seq indices and
ordered/clamped here so click order and out-of-range values can't produce a bad
range. Name only — no per-section stats are persisted.
"""
from __future__ import annotations

import math
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ride import Ride, RidePoint
from app.models.section import RideSection

NAME_MAX = 140

_EARTH_M = 6371000.0


def _clean_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise SectionError("Section needs a name")
    return name[:NAME_MAX]


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_M * math.asin(math.sqrt(h))


class SectionError(ValueError):
    """Invalid section input (bad name or zero-length range)."""


async def _max_seq(db: AsyncSession, ride_id: uuid.UUID) -> int | None:
    return (
        await db.execute(select(func.max(RidePoint.seq)).where(RidePoint.ride_id == ride_id))
    ).scalar_one()


async def create(
    db: AsyncSession, ride_id: uuid.UUID, name: str, start_seq: int, end_seq: int
) -> RideSection:
    name = _clean_name(name)

    top = await _max_seq(db, ride_id)
    if top is None:
        raise SectionError("Ride has no points to section")

    lo, hi = sorted((start_seq, end_seq))
    lo = max(0, min(lo, top))
    hi = max(0, min(hi, top))
    if hi <= lo:
        raise SectionError("Section must span at least two points")

    section = RideSection(ride_id=ride_id, name=name, start_seq=lo, end_seq=hi)
    db.add(section)
    await db.flush()
    return section


async def list_for_ride(db: AsyncSession, ride_id: uuid.UUID) -> list[RideSection]:
    return list(
        (
            await db.execute(
                select(RideSection)
                .where(RideSection.ride_id == ride_id)
                .order_by(RideSection.start_seq)
            )
        )
        .scalars()
        .all()
    )


async def get(
    db: AsyncSession, ride_id: uuid.UUID, section_id: uuid.UUID
) -> RideSection | None:
    section = await db.get(RideSection, section_id)
    if section is None or section.ride_id != ride_id:
        return None
    return section


async def list_for_user(db: AsyncSession, user_id: uuid.UUID) -> list[RideSection]:
    """Every section across the user's rides, newest ride first. The parent Ride
    is eager-loaded (.ride) so the manage page can show ride title/region."""
    return list(
        (
            await db.execute(
                select(RideSection)
                .join(Ride, RideSection.ride_id == Ride.id)
                .where(Ride.user_id == user_id)
                .order_by(Ride.created_at.desc(), RideSection.start_seq)
                .options(selectinload(RideSection.ride))
            )
        )
        .scalars()
        .all()
    )


async def get_owned(
    db: AsyncSession, user_id: uuid.UUID, section_id: uuid.UUID
) -> RideSection | None:
    """A section whose parent ride belongs to user_id (None otherwise), for
    ride-less management routes. Verifies ownership via the join, not a path id."""
    return (
        (
            await db.execute(
                select(RideSection)
                .join(Ride, RideSection.ride_id == Ride.id)
                .where(RideSection.id == section_id, Ride.user_id == user_id)
                .options(selectinload(RideSection.ride))
            )
        )
        .scalars()
        .one_or_none()
    )


async def rename(db: AsyncSession, section: RideSection, name: str) -> RideSection:
    section.name = _clean_name(name)
    db.add(section)
    await db.flush()
    return section


def section_stats(points: list[RidePoint]) -> dict:
    """Derive display stats for a section from its point slice (units match the
    Ride stat-bar: distance/elev in metres, speeds in m/s, duration in seconds).

    Distance is haversine-summed over the *downsampled* slice, so it trends a
    touch short of the full-res ride distance — fine for a highlight readout.
    """
    distance_m = 0.0
    elev_gain = 0.0
    for prev, cur in zip(points, points[1:]):
        distance_m += _haversine(prev.lat, prev.lon, cur.lat, cur.lon)
        if prev.elev is not None and cur.elev is not None and cur.elev > prev.elev:
            elev_gain += cur.elev - prev.elev

    times = [p.t for p in points if p.t is not None]
    duration_s = (times[-1] - times[0]) if len(times) >= 2 else 0.0
    speeds = [p.speed for p in points if p.speed is not None]
    return {
        "distance_m": distance_m,
        "elev_gain": elev_gain,
        "duration_s": duration_s,
        "avg_speed": (distance_m / duration_s) if duration_s else 0.0,
        "max_speed": max(speeds) if speeds else None,
    }


async def slice_points(db: AsyncSession, section: RideSection) -> list[RidePoint]:
    return list(
        (
            await db.execute(
                select(RidePoint)
                .where(
                    RidePoint.ride_id == section.ride_id,
                    RidePoint.seq >= section.start_seq,
                    RidePoint.seq <= section.end_seq,
                )
                .order_by(RidePoint.seq)
            )
        )
        .scalars()
        .all()
    )
