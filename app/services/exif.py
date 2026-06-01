"""Extract GPS coords + capture time from image EXIF (best-effort)."""
from __future__ import annotations

import io
from datetime import datetime, timezone

from PIL import ExifTags, Image

_GPS_TAG = next((k for k, v in ExifTags.TAGS.items() if v == "GPSInfo"), None)
_DT_TAG = next((k for k, v in ExifTags.TAGS.items() if v == "DateTimeOriginal"), None)


def _ratio(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _dms_to_deg(dms, ref) -> float | None:
    try:
        d = _ratio(dms[0]) + _ratio(dms[1]) / 60 + _ratio(dms[2]) / 3600
    except (TypeError, IndexError):
        return None
    if ref in ("S", "W"):
        d = -d
    return d


def extract(data: bytes) -> tuple[float | None, float | None, datetime | None]:
    """Return (lat, lon, taken_at). Any field may be None."""
    try:
        img = Image.open(io.BytesIO(data))
        exif = img._getexif() or {}
    except Exception:
        return None, None, None

    lat = lon = None
    if _GPS_TAG and _GPS_TAG in exif:
        gps = exif[_GPS_TAG]
        # GPS sub-IDs: 1=LatRef 2=Lat 3=LonRef 4=Lon
        lat = _dms_to_deg(gps.get(2), gps.get(1))
        lon = _dms_to_deg(gps.get(4), gps.get(3))

    taken = None
    if _DT_TAG and _DT_TAG in exif:
        try:
            taken = datetime.strptime(exif[_DT_TAG], "%Y:%m:%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
        except (ValueError, TypeError):
            taken = None

    return lat, lon, taken
