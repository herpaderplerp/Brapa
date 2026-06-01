"""GPX parsing and stat extraction.

Uses gpxpy for robust GPX 1.0/1.1 parsing and most stat math, pyproj for
geodesic per-point speed, and a stride downsample to keep the client-rendered
point series small. The full-resolution track is returned separately as WKT for
PostGIS storage.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import datetime

import gpxpy
from pyproj import Geod

_GEOD = Geod(ellps="WGS84")

# Target number of points sent to the browser. 50k-point tracks downsample to
# this for 60fps pan/zoom; full resolution is preserved in the PostGIS geometry.
DOWNSAMPLE_TARGET = 2500


@dataclass
class TrackPoint:
    seq: int
    lat: float
    lon: float
    elev: float | None
    speed: float | None  # m/s
    t: float | None  # seconds from start


@dataclass
class RideStats:
    start_time: datetime | None
    start_lat: float | None
    start_lon: float | None
    distance_m: float
    moving_time_s: float
    elapsed_time_s: float
    max_speed: float  # m/s
    avg_moving_speed: float  # m/s
    elev_gain: float
    elev_loss: float
    max_elev: float | None
    points: list[TrackPoint] = field(default_factory=list)
    track_wkt: str | None = None  # LINESTRING Z in lon lat elev order


class GPXParseError(Exception):
    pass


def compute_dedup_hash(start_time: datetime | None, lat: float | None, lon: float | None) -> str:
    """Hash of start time + start coords rounded to ~11m, for duplicate
    detection (spec US-04)."""
    parts = [
        start_time.isoformat() if start_time else "no-time",
        f"{lat:.4f}" if lat is not None else "no-lat",
        f"{lon:.4f}" if lon is not None else "no-lon",
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _flatten_points(gpx) -> list:
    pts = []
    for track in gpx.tracks:
        for seg in track.segments:
            pts.extend(seg.points)
    # Routes as a fallback for files that use <rte> instead of <trk>.
    if not pts:
        for route in gpx.routes:
            pts.extend(route.points)
    return pts


def _downsample(points: list[TrackPoint], target: int) -> list[TrackPoint]:
    n = len(points)
    if n <= target:
        return points
    stride = math.ceil(n / target)
    kept = points[::stride]
    if kept[-1].seq != points[-1].seq:
        kept.append(points[-1])  # always keep the final point
    return kept


def parse_gpx(data: bytes) -> RideStats:
    try:
        gpx = gpxpy.parse(data.decode("utf-8", errors="replace"))
    except Exception as exc:  # gpxpy raises various parse errors
        raise GPXParseError(f"Could not parse GPX: {exc}") from exc

    raw = _flatten_points(gpx)
    if len(raw) < 2:
        raise GPXParseError("GPX contains no usable track points")

    # Stats via gpxpy built-ins (handles moving/stopped thresholds, 3d length).
    moving = gpx.get_moving_data()
    up_down = gpx.get_uphill_downhill()
    elev_ext = gpx.get_elevation_extremes()
    time_bounds = gpx.get_time_bounds()

    distance_m = gpx.length_3d() or gpx.length_2d() or 0.0
    moving_time_s = moving.moving_time if moving else 0.0
    moving_distance = moving.moving_distance if moving else 0.0
    max_speed = moving.max_speed if moving and moving.max_speed else 0.0
    avg_moving_speed = (moving_distance / moving_time_s) if moving_time_s else 0.0

    start_time = time_bounds.start_time if time_bounds else None
    end_time = time_bounds.end_time if time_bounds else None
    elapsed_time_s = (
        (end_time - start_time).total_seconds() if start_time and end_time else 0.0
    )

    start_lat = raw[0].latitude
    start_lon = raw[0].longitude

    # Build per-point series with geodesic speed.
    series: list[TrackPoint] = []
    t0 = raw[0].time
    prev = None
    for i, p in enumerate(raw):
        t_off = (p.time - t0).total_seconds() if (p.time and t0) else None
        speed = None
        if prev is not None and p.time and prev.time:
            dt = (p.time - prev.time).total_seconds()
            if dt > 0:
                _, _, dist = _GEOD.inv(prev.longitude, prev.latitude, p.longitude, p.latitude)
                speed = dist / dt
        series.append(
            TrackPoint(
                seq=i,
                lat=p.latitude,
                lon=p.longitude,
                elev=p.elevation,
                speed=speed,
                t=t_off,
            )
        )
        prev = p

    points = _downsample(series, DOWNSAMPLE_TARGET)
    # Re-sequence downsampled points 0..k for stable client indexing.
    for new_seq, tp in enumerate(points):
        tp.seq = new_seq

    track_wkt = _to_linestring_z(raw)

    return RideStats(
        start_time=start_time,
        start_lat=start_lat,
        start_lon=start_lon,
        distance_m=float(distance_m),
        moving_time_s=float(moving_time_s),
        elapsed_time_s=float(elapsed_time_s),
        max_speed=float(max_speed),
        avg_moving_speed=float(avg_moving_speed),
        elev_gain=float(up_down.uphill or 0.0) if up_down else 0.0,
        elev_loss=float(up_down.downhill or 0.0) if up_down else 0.0,
        max_elev=float(elev_ext.maximum) if elev_ext and elev_ext.maximum is not None else None,
        points=points,
        track_wkt=track_wkt,
    )


def _to_linestring_z(raw: list) -> str:
    coords = []
    for p in raw:
        z = p.elevation if p.elevation is not None else 0.0
        coords.append(f"{p.longitude} {p.latitude} {z}")
    return "LINESTRING Z (" + ", ".join(coords) + ")"
