"""Privacy zones: read-time, viewer-aware clipping of ride tracks.

A user defines circular zones (center + radius) at the account level. When a ride
is viewed by *anyone other than its owner*, every track point falling inside one
of the owner's zones is removed, splitting the polyline into gap-separated
segments so the rendered course visibly stops at the zone boundary. The owner
always sees the full track (effective_zones returns [] for them).

Nothing is mutated on disk: the full RidePoint series, PostGIS track geometry,
and raw GPX blob stay intact. Redaction is applied on each read — points.json,
section slices, photos.json, the GPX export, feed thumbnails, and discover
markers. So zones added or edited later retroactively protect old rides.

Distance uses an equirectangular approximation, which is well within tolerance
at the sub-2 km scale of a zone and avoids per-point trig beyond two cosines.
"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Callable, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.privacy import PrivacyZone

# Radius bounds (metres) and per-user cap, enforced on create.
RADIUS_MIN_M = 100.0
RADIUS_MAX_M = 2000.0
RADIUS_DEFAULT_M = 250.0
MAX_ZONES = 10

_EARTH_M = 6371000.0


@dataclass(frozen=True)
class Zone:
    lat: float
    lon: float
    radius_m: float


def clamp_radius(r: float) -> float:
    return max(RADIUS_MIN_M, min(RADIUS_MAX_M, r))


def _to_zone(z: PrivacyZone) -> Zone:
    return Zone(z.center_lat, z.center_lon, z.radius_m)


async def zones_for(db: AsyncSession, user_id: uuid.UUID) -> list[Zone]:
    rows = (
        await db.execute(select(PrivacyZone).where(PrivacyZone.user_id == user_id))
    ).scalars().all()
    return [_to_zone(z) for z in rows]


async def zones_by_user(
    db: AsyncSession, user_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[Zone]]:
    """Zones for many owners in one query (avoids N+1 in feed/discover)."""
    ids = list({i for i in user_ids})
    out: dict[uuid.UUID, list[Zone]] = {i: [] for i in ids}
    if not ids:
        return out
    rows = (
        await db.execute(select(PrivacyZone).where(PrivacyZone.user_id.in_(ids)))
    ).scalars().all()
    for z in rows:
        out.setdefault(z.user_id, []).append(_to_zone(z))
    return out


async def effective_zones(db: AsyncSession, viewer_id: uuid.UUID, ride) -> list[Zone]:
    """Zones that apply when `viewer_id` looks at `ride`: none for the owner,
    the owner's zones for anyone else. This single gate enforces the
    owner-sees-full / others-see-clipped policy across every leak surface."""
    if viewer_id == ride.user_id:
        return []
    return await zones_for(db, ride.user_id)


def _dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    mean_lat = math.radians((lat1 + lat2) / 2.0)
    x = math.radians(lon2 - lon1) * math.cos(mean_lat)
    y = math.radians(lat2 - lat1)
    return _EARTH_M * math.hypot(x, y)


def in_any_zone(lat: float, lon: float, zones: list[Zone]) -> bool:
    return any(_dist_m(lat, lon, z.lat, z.lon) <= z.radius_m for z in zones)


def _offset_m(lat: float, lon: float, zone: Zone) -> tuple[float, float]:
    """Return equirectangular x/y metre offsets from `zone` to `lat`/`lon`."""
    mean_lat = math.radians((lat + zone.lat) / 2.0)
    x = math.radians(lon - zone.lon) * math.cos(mean_lat) * _EARTH_M
    y = math.radians(lat - zone.lat) * _EARTH_M
    return x, y


def _segment_intersects_zone(
    lat1: float, lon1: float, lat2: float, lon2: float, zone: Zone
) -> bool:
    """True when the straight segment between two points enters `zone`.

    Track rendering and GPX re-import connect adjacent retained points with a
    straight line. Two endpoints can both sit outside a privacy zone while that
    connecting line passes through it, especially after downsampling. Projecting
    onto a local metre plane around the zone is accurate enough for the maximum
    2 km radius used here.
    """
    x1, y1 = _offset_m(lat1, lon1, zone)
    x2, y2 = _offset_m(lat2, lon2, zone)
    dx = x2 - x1
    dy = y2 - y1
    denom = dx * dx + dy * dy
    if denom == 0:
        return math.hypot(x1, y1) <= zone.radius_m
    t = max(0.0, min(1.0, -(x1 * dx + y1 * dy) / denom))
    closest_x = x1 + t * dx
    closest_y = y1 + t * dy
    return math.hypot(closest_x, closest_y) <= zone.radius_m


def _segment_intersects_any_zone(
    lat1: float, lon1: float, lat2: float, lon2: float, zones: list[Zone]
) -> bool:
    return any(_segment_intersects_zone(lat1, lon1, lat2, lon2, z) for z in zones)


def clip_segments(
    items: Iterable,
    zones: list[Zone],
    getlat: Callable = lambda p: p.lat,
    getlon: Callable = lambda p: p.lon,
) -> list[list]:
    """Split `items` into visible runs, preserving privacy-zone gaps.

    Points inside a zone are dropped. Adjacent outside points are also split into
    separate runs when their connecting segment crosses a zone, preventing maps
    and charts from drawing a straight line through a protected area. With no
    zones, returns a single segment with everything. An all-redacted track
    returns [].
    """
    seq = list(items)
    if not zones:
        return [seq] if seq else []
    segments: list[list] = []
    current: list = []
    prev = None

    def flush() -> None:
        nonlocal current
        if current:
            segments.append(current)
            current = []

    for it in seq:
        lat = getlat(it)
        lon = getlon(it)
        if in_any_zone(lat, lon, zones):
            flush()
            prev = it
            continue
        if current and prev is not None and _segment_intersects_any_zone(
            getlat(prev), getlon(prev), lat, lon, zones
        ):
            flush()
        current.append(it)
        prev = it
    flush()
    return segments


def clip_gpx(data: bytes, zones: list[Zone]) -> bytes:
    """Return GPX with privacy-zone trackpoints and crossing segments removed.

    Surviving runs become separate <trkseg>s so gaps are preserved on re-import.
    Used for the non-owner download path.
    """
    if not zones:
        return data
    import gpxpy
    import gpxpy.gpx

    try:
        src = gpxpy.parse(data.decode("utf-8", errors="replace"))
    except Exception:
        # Unparseable: safest is to withhold rather than leak the raw blob.
        return gpxpy.gpx.GPX().to_xml().encode("utf-8")

    out = gpxpy.gpx.GPX()
    out.name = src.name
    trk = gpxpy.gpx.GPXTrack()
    out.tracks.append(trk)

    def flush(run: list) -> None:
        if len(run) >= 2:
            seg = gpxpy.gpx.GPXTrackSegment()
            seg.points = run
            trk.segments.append(seg)

    sources = [seg.points for t in src.tracks for seg in t.segments]
    if not sources:  # files that used <rte> instead of <trk>
        sources = [r.points for r in src.routes]

    for pts in sources:
        run: list = []
        prev = None
        for pt in pts:
            lat = pt.latitude
            lon = pt.longitude
            if in_any_zone(lat, lon, zones):
                if run:
                    flush(run)
                    run = []
                prev = pt
                continue
            if run and prev is not None and _segment_intersects_any_zone(
                prev.latitude, prev.longitude, lat, lon, zones
            ):
                flush(run)
                run = []
            run.append(pt)
            prev = pt
        if run:
            flush(run)

    return out.to_xml().encode("utf-8")
