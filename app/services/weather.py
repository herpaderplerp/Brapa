"""Historical weather lookup via Open-Meteo's archive API.

Fetches conditions at the ride's start coordinate and time. Fully historical:
rides uploaded weeks later still resolve the original date/time (spec US-05a).
On any failure the caller saves the ride with weather status 'unavailable'.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import httpx

from app.config import settings

# WMO weather codes -> our coarse sky buckets.
# https://open-meteo.com/en/docs (weathercode table)
_WMO_SKY = {
    0: "clear",
    1: "partly cloudy",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "fog",
    51: "rain", 53: "rain", 55: "rain",
    56: "rain", 57: "rain",
    61: "rain", 63: "rain", 65: "rain",
    66: "rain", 67: "rain",
    71: "snow", 73: "snow", 75: "snow", 77: "snow",
    80: "rain", 81: "rain", 82: "rain",
    85: "snow", 86: "snow",
    95: "rain", 96: "rain", 99: "rain",
}


@dataclass
class WeatherResult:
    status: str  # "ok" | "unavailable"
    sky: str | None = None
    temp_c: float | None = None
    wind_speed: float | None = None  # km/h
    wind_dir: float | None = None
    humidity: float | None = None  # %
    visibility: float | None = None  # meters


def _sky_from_code(code: int | None) -> str | None:
    if code is None:
        return None
    return _WMO_SKY.get(int(code), "partly cloudy")


async def fetch_weather(lat: float, lon: float, when: datetime) -> WeatherResult:
    if lat is None or lon is None or when is None:
        return WeatherResult(status="unavailable")

    date = when.strftime("%Y-%m-%d")
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "start_date": date,
        "end_date": date,
        "hourly": "temperature_2m,relativehumidity_2m,windspeed_10m,winddirection_10m,weathercode,visibility",
        "timezone": "UTC",
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(settings.open_meteo_base, params=params)
            resp.raise_for_status()
            data = resp.json()
        return _pick_hour(data, when)
    except Exception:
        return WeatherResult(status="unavailable")


def _pick_hour(data: dict, when: datetime) -> WeatherResult:
    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return WeatherResult(status="unavailable")

    # Match the hour bucket "YYYY-MM-DDTHH:00".
    target = when.strftime("%Y-%m-%dT%H:00")
    try:
        idx = times.index(target)
    except ValueError:
        idx = min(range(len(times)), key=lambda i: abs(_hour_of(times[i]) - when.hour))

    def at(name: str):
        seq = hourly.get(name)
        return seq[idx] if seq and idx < len(seq) else None

    return WeatherResult(
        status="ok",
        sky=_sky_from_code(at("weathercode")),
        temp_c=at("temperature_2m"),
        wind_speed=at("windspeed_10m"),
        wind_dir=at("winddirection_10m"),
        humidity=at("relativehumidity_2m"),
        visibility=at("visibility"),
    )


def _hour_of(ts: str) -> int:
    try:
        return int(ts[11:13])
    except (ValueError, IndexError):
        return 0
