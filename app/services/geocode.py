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
