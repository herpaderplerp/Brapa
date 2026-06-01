"""Background processing pipeline for an uploaded ride.

Parses the stored GPX, computes stats, downsamples the point series, stores the
full-resolution track geometry, reverse-geocodes the start, and fetches historical
weather. Runs as a FastAPI BackgroundTask in its own DB session.

Note: BackgroundTasks share the web process. If large-file throughput strains the
10s budget, lift this to a real queue (Celery/RQ/arq) — the call sites won't change.
"""
from __future__ import annotations

import uuid

from geoalchemy2.elements import WKTElement
from sqlalchemy import select

from app.db import SessionLocal
from app.models.ride import (
    STATUS_DONE,
    STATUS_DUPLICATE,
    STATUS_FAILED,
    Ride,
    RidePoint,
    RideWeather,
)
from app.services import geocode, storage, weather
from app.services.gpx import GPXParseError, compute_dedup_hash, parse_gpx


async def process_ride(ride_id: uuid.UUID) -> None:
    async with SessionLocal() as db:
        ride = await db.get(Ride, ride_id)
        if ride is None or not ride.gpx_blob_key:
            return
        try:
            data = storage.read(ride.gpx_blob_key)
            stats = parse_gpx(data)
        except (GPXParseError, FileNotFoundError) as exc:
            ride.processing_status = STATUS_FAILED
            ride.processing_error = str(exc)[:255]
            db.add(ride)
            await db.commit()
            return

        ride.start_time = stats.start_time
        ride.start_lat = stats.start_lat
        ride.start_lon = stats.start_lon
        ride.distance_m = stats.distance_m
        ride.moving_time_s = stats.moving_time_s
        ride.elapsed_time_s = stats.elapsed_time_s
        ride.max_speed = stats.max_speed
        ride.avg_moving_speed = stats.avg_moving_speed
        ride.elev_gain = stats.elev_gain
        ride.elev_loss = stats.elev_loss
        ride.max_elev = stats.max_elev
        if stats.track_wkt:
            ride.track = WKTElement(stats.track_wkt, srid=4326)

        ride.dedup_hash = compute_dedup_hash(
            stats.start_time, stats.start_lat, stats.start_lon
        )

        # Persist downsampled point series for rendering.
        for tp in stats.points:
            db.add(
                RidePoint(
                    ride_id=ride.id,
                    seq=tp.seq,
                    lat=tp.lat,
                    lon=tp.lon,
                    elev=tp.elev,
                    speed=tp.speed,
                    t=tp.t,
                )
            )

        # Reverse geocode + historical weather (best-effort).
        if stats.start_lat is not None and stats.start_lon is not None:
            ride.start_region = await geocode.reverse_region(stats.start_lat, stats.start_lon)
            wx = await weather.fetch_weather(
                stats.start_lat, stats.start_lon, stats.start_time
            )
        else:
            wx = weather.WeatherResult(status="unavailable")

        db.add(
            RideWeather(
                ride_id=ride.id,
                status=wx.status,
                sky=wx.sky,
                temp_c=wx.temp_c,
                wind_speed=wx.wind_speed,
                wind_dir=wx.wind_dir,
                humidity=wx.humidity,
                visibility=wx.visibility,
            )
        )

        # Duplicate detection against this user's already-processed rides.
        dup = (
            await db.execute(
                select(Ride.id).where(
                    Ride.user_id == ride.user_id,
                    Ride.dedup_hash == ride.dedup_hash,
                    Ride.id != ride.id,
                    Ride.processing_status == STATUS_DONE,
                )
            )
        ).first()
        ride.processing_status = STATUS_DUPLICATE if dup else STATUS_DONE

        db.add(ride)
        await db.commit()


async def retry_weather(ride_id: uuid.UUID) -> None:
    """Manual weather retry (spec US-05a) when the first fetch failed."""
    async with SessionLocal() as db:
        ride = await db.get(Ride, ride_id)
        if ride is None or ride.start_lat is None or ride.start_lon is None:
            return
        wx = await weather.fetch_weather(ride.start_lat, ride.start_lon, ride.start_time)
        rw = await db.get(RideWeather, ride_id)
        if rw is None:
            rw = RideWeather(ride_id=ride_id)
        rw.status = wx.status
        rw.sky = wx.sky
        rw.temp_c = wx.temp_c
        rw.wind_speed = wx.wind_speed
        rw.wind_dir = wx.wind_dir
        rw.humidity = wx.humidity
        rw.visibility = wx.visibility
        db.add(rw)
        await db.commit()
