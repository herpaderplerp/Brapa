"""Unit tests for the weather service.

All HTTP calls are mocked so these run without network access.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.weather import WeatherResult, _pick_hour, _sky_from_code, fetch_weather


# ---------------------------------------------------------------------------
# _sky_from_code — pure function, no I/O
# ---------------------------------------------------------------------------


def test_sky_code_0_is_clear():
    assert _sky_from_code(0) == "clear"


def test_sky_code_1_is_partly_cloudy():
    assert _sky_from_code(1) == "partly cloudy"


def test_sky_code_45_is_fog():
    assert _sky_from_code(45) == "fog"


def test_sky_code_61_is_rain():
    assert _sky_from_code(61) == "rain"


def test_sky_code_71_is_snow():
    assert _sky_from_code(71) == "snow"


def test_sky_unknown_code_defaults_to_partly_cloudy():
    assert _sky_from_code(9999) == "partly cloudy"


def test_sky_none_returns_none():
    assert _sky_from_code(None) is None


# ---------------------------------------------------------------------------
# _pick_hour — pure function, no I/O
# ---------------------------------------------------------------------------


def _make_hourly(temp: float = 20.0, code: int = 0) -> dict:
    """Build a minimal Open-Meteo-shaped hourly response for 2024-06-01."""
    return {
        "hourly": {
            "time": [f"2024-06-01T{h:02d}:00" for h in range(24)],
            "temperature_2m": [temp + h * 0.1 for h in range(24)],
            "weathercode": [code] * 24,
            "windspeed_10m": [15.0] * 24,
            "winddirection_10m": [180.0] * 24,
            "relativehumidity_2m": [60.0] * 24,
            "visibility": [10000.0] * 24,
        }
    }


def test_pick_hour_exact_match_returns_ok():
    when = datetime(2024, 6, 1, 10, 0, tzinfo=timezone.utc)
    result = _pick_hour(_make_hourly(temp=22.0, code=0), when)
    assert result.status == "ok"
    assert result.sky == "clear"
    assert result.temp_c == pytest.approx(22.0)
    assert result.wind_speed == 15.0
    assert result.humidity == 60.0


def test_pick_hour_mid_hour_timestamp_matches_correct_bucket():
    # 10:45 should still resolve to the 10:00 bucket.
    when = datetime(2024, 6, 1, 10, 45, tzinfo=timezone.utc)
    result = _pick_hour(_make_hourly(temp=22.0, code=0), when)
    assert result.status == "ok"
    assert result.temp_c == pytest.approx(22.0 + 10 * 0.1, abs=0.01)


def test_pick_hour_falls_back_to_nearest_when_no_exact_match():
    # Only two hours available; pick the closer one.
    data = {
        "hourly": {
            "time": ["2024-06-01T08:00", "2024-06-01T14:00"],
            "temperature_2m": [10.0, 25.0],
            "weathercode": [0, 61],
            "windspeed_10m": [5.0, 20.0],
            "winddirection_10m": [90.0, 270.0],
            "relativehumidity_2m": [80.0, 40.0],
            "visibility": [5000.0, 15000.0],
        }
    }
    # 09:00 is 1 hour from 08:00 and 5 hours from 14:00 → picks 08:00.
    when = datetime(2024, 6, 1, 9, 0, tzinfo=timezone.utc)
    result = _pick_hour(data, when)
    assert result.temp_c == pytest.approx(10.0)
    assert result.sky == "clear"


def test_pick_hour_empty_times_returns_unavailable():
    result = _pick_hour({"hourly": {"time": []}}, datetime(2024, 6, 1, 12, tzinfo=timezone.utc))
    assert result.status == "unavailable"


def test_pick_hour_missing_hourly_key_returns_unavailable():
    result = _pick_hour({}, datetime(2024, 6, 1, 12, tzinfo=timezone.utc))
    assert result.status == "unavailable"


def test_pick_hour_none_value_in_series_is_tolerated():
    data = {
        "hourly": {
            "time": ["2024-06-01T10:00"],
            "temperature_2m": [None],
            "weathercode": [0],
            "windspeed_10m": [None],
            "winddirection_10m": [None],
            "relativehumidity_2m": [None],
            "visibility": [None],
        }
    }
    result = _pick_hour(data, datetime(2024, 6, 1, 10, tzinfo=timezone.utc))
    assert result.status == "ok"
    assert result.temp_c is None
    assert result.wind_speed is None


# ---------------------------------------------------------------------------
# fetch_weather — requires HTTP mocking
# ---------------------------------------------------------------------------


def _mock_client(response_json=None, raise_error=False):
    """Return a patch context that stubs httpx.AsyncClient with a canned response."""
    mock_resp = MagicMock()
    if raise_error:
        mock_resp.raise_for_status.side_effect = Exception("HTTP error")
    else:
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = response_json

    mock_instance = AsyncMock()
    mock_instance.get = AsyncMock(return_value=mock_resp)

    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

    return patch("httpx.AsyncClient", mock_cls)


async def test_fetch_weather_none_coordinates_returns_unavailable():
    result = await fetch_weather(None, None, None)
    assert result.status == "unavailable"


async def test_fetch_weather_none_when_returns_unavailable():
    result = await fetch_weather(37.8, -122.4, None)
    assert result.status == "unavailable"


async def test_fetch_weather_http_error_returns_unavailable():
    when = datetime(2024, 6, 1, 12, tzinfo=timezone.utc)
    with _mock_client(raise_error=True):
        result = await fetch_weather(37.8, -122.4, when)
    assert result.status == "unavailable"


async def test_fetch_weather_parses_ok_response():
    when = datetime(2024, 6, 1, 10, tzinfo=timezone.utc)
    with _mock_client(response_json=_make_hourly(temp=18.5, code=1)):
        result = await fetch_weather(37.8, -122.4, when)
    assert result.status == "ok"
    assert result.sky == "partly cloudy"
    assert result.temp_c == pytest.approx(18.5 + 10 * 0.1, abs=0.01)
    assert result.wind_speed == 15.0
    assert result.humidity == 60.0


async def test_fetch_weather_rain_code_maps_correctly():
    when = datetime(2024, 6, 1, 6, tzinfo=timezone.utc)
    with _mock_client(response_json=_make_hourly(temp=12.0, code=63)):
        result = await fetch_weather(51.5, -0.1, when)
    assert result.status == "ok"
    assert result.sky == "rain"
