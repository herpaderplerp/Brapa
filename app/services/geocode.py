"""Reverse geocoding of a ride's start coordinate to a city/region label.

Uses OSM Nominatim. Best-effort: returns None on any failure (the ride still
saves). Nominatim asks for a descriptive User-Agent and <=1 req/sec; uploads are
infrequent so we just set the header.
"""
from __future__ import annotations

import httpx

from app.config import settings


async def reverse_region(lat: float, lon: float) -> str | None:
    if lat is None or lon is None:
        return None
    params = {"lat": f"{lat:.5f}", "lon": f"{lon:.5f}", "format": "json", "zoom": "10"}
    headers = {"User-Agent": "Brapa/0.1 (ride geocoding)"}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                f"{settings.nominatim_base}/reverse", params=params, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return None

    addr = data.get("address") or {}
    city = (
        addr.get("city")
        or addr.get("town")
        or addr.get("village")
        or addr.get("county")
    )
    region = addr.get("state") or addr.get("region") or addr.get("country")
    parts = [p for p in (city, region) if p]
    if parts:
        return ", ".join(parts)
    return data.get("display_name")


async def search(query: str) -> tuple[float, float, tuple[float, float, float, float]] | None:
    """Forward geocode a place name. Returns (lat, lon, bbox) where
    bbox = (min_lon, min_lat, max_lon, max_lat), or None on failure."""
    query = (query or "").strip()
    if not query:
        return None
    params = {"q": query, "format": "json", "limit": "1"}
    headers = {"User-Agent": "Brapa/0.1 (ride discovery)"}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                f"{settings.nominatim_base}/search", params=params, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return None
    if not data:
        return None
    top = data[0]
    try:
        lat = float(top["lat"])
        lon = float(top["lon"])
        # Nominatim boundingbox = [south, north, west, east] (strings).
        south, north, west, east = (float(x) for x in top["boundingbox"])
        return lat, lon, (west, south, east, north)
    except (KeyError, ValueError, TypeError):
        return None
