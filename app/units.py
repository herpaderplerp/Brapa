"""Display formatters honouring user unit preferences (km/mi, C/F, km/h/mph)."""
from __future__ import annotations


def fmt_distance(meters: float | None, unit: str = "km") -> str:
    if meters is None:
        return "—"
    if unit == "mi":
        return f"{meters / 1609.344:.1f} mi"
    return f"{meters / 1000:.1f} km"


def fmt_speed(mps: float | None, unit: str = "km") -> str:
    if mps is None:
        return "—"
    if unit == "mi":
        return f"{mps * 2.236936:.0f} mph"
    return f"{mps * 3.6:.0f} km/h"


def fmt_temp(celsius: float | None, unit: str = "C") -> str:
    if celsius is None:
        return "—"
    if unit == "F":
        return f"{celsius * 9 / 5 + 32:.0f}°F"
    return f"{celsius:.0f}°C"


def fmt_elev(meters: float | None, unit: str = "km") -> str:
    if meters is None:
        return "—"
    if unit == "mi":
        return f"{meters * 3.28084:.0f} ft"
    return f"{meters:.0f} m"


def fmt_duration(seconds: float | None) -> str:
    if not seconds:
        return "—"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, _ = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m"


def fmt_wind(speed: float | None, direction: float | None, unit: str = "km") -> str:
    if speed is None:
        return "—"
    # Open-Meteo returns km/h.
    val = f"{speed * 0.621371:.0f} mph" if unit == "mi" else f"{speed:.0f} km/h"
    if direction is None:
        return val
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    idx = int((direction % 360) / 45 + 0.5) % 8
    return f"{val} {dirs[idx]}"
