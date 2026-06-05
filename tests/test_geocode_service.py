"""Unit tests for the geocode service.

All HTTP calls are mocked — no real Nominatim requests are made.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.geocode import reverse_region, search


def _mock_client(response_json, status_code=200, raise_error=False):
    """Patch httpx.AsyncClient to return a canned Nominatim response."""
    mock_resp = MagicMock()
    if raise_error:
        mock_resp.raise_for_status.side_effect = Exception("network error")
    else:
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = response_json

    mock_instance = AsyncMock()
    mock_instance.get = AsyncMock(return_value=mock_resp)

    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

    return patch("httpx.AsyncClient", mock_cls)


# ---------------------------------------------------------------------------
# reverse_region
# ---------------------------------------------------------------------------


async def test_reverse_region_returns_none_for_none_lat():
    assert await reverse_region(None, -122.4) is None


async def test_reverse_region_returns_none_for_none_lon():
    assert await reverse_region(37.8, None) is None


async def test_reverse_region_returns_none_for_both_none():
    assert await reverse_region(None, None) is None


async def test_reverse_region_formats_city_and_state():
    mock_resp = {
        "address": {
            "city": "San Francisco",
            "state": "California",
            "country": "United States",
        },
        "display_name": "San Francisco, California, United States",
    }
    with _mock_client(mock_resp):
        result = await reverse_region(37.77, -122.42)
    assert result == "San Francisco, California"


async def test_reverse_region_uses_town_when_no_city():
    mock_resp = {
        "address": {"town": "Half Moon Bay", "state": "California"},
        "display_name": "Half Moon Bay, CA",
    }
    with _mock_client(mock_resp):
        result = await reverse_region(37.46, -122.43)
    assert result == "Half Moon Bay, California"


async def test_reverse_region_uses_county_as_last_resort_locality():
    mock_resp = {
        "address": {"county": "San Mateo County", "state": "California"},
        "display_name": "San Mateo County, California",
    }
    with _mock_client(mock_resp):
        result = await reverse_region(37.46, -122.43)
    assert result == "San Mateo County, California"


async def test_reverse_region_falls_back_to_display_name_on_empty_address():
    mock_resp = {
        "address": {},
        "display_name": "Some Remote Location, Ocean",
    }
    with _mock_client(mock_resp):
        result = await reverse_region(0.0, 0.0)
    assert result == "Some Remote Location, Ocean"


async def test_reverse_region_returns_none_on_http_error():
    with _mock_client({}, raise_error=True):
        result = await reverse_region(37.8, -122.4)
    assert result is None


async def test_reverse_region_state_only_when_no_locality():
    mock_resp = {
        "address": {"country": "Germany", "state": "Bavaria"},
        "display_name": "Bavaria, Germany",
    }
    with _mock_client(mock_resp):
        result = await reverse_region(48.0, 11.0)
    assert result == "Bavaria"


# ---------------------------------------------------------------------------
# search (forward geocode)
# ---------------------------------------------------------------------------


async def test_search_empty_string_returns_none():
    result = await search("")
    assert result is None


async def test_search_whitespace_only_returns_none():
    result = await search("   ")
    assert result is None


async def test_search_parses_lat_lon_and_bbox():
    mock_resp = [
        {
            "lat": "37.7749",
            "lon": "-122.4194",
            # Nominatim boundingbox: [south, north, west, east]
            "boundingbox": ["37.6398", "37.9298", "-123.1737", "-122.2816"],
        }
    ]
    with _mock_client(mock_resp):
        result = await search("San Francisco")
    assert result is not None
    lat, lon, bbox = result
    assert lat == pytest.approx(37.7749)
    assert lon == pytest.approx(-122.4194)
    # bbox = (min_lon, min_lat, max_lon, max_lat)
    min_lon, min_lat, max_lon, max_lat = bbox
    assert min_lon == pytest.approx(-123.1737)
    assert min_lat == pytest.approx(37.6398)
    assert max_lon == pytest.approx(-122.2816)
    assert max_lat == pytest.approx(37.9298)


async def test_search_returns_none_for_empty_api_response():
    with _mock_client([]):
        result = await search("Atlantis")
    assert result is None


async def test_search_returns_none_on_http_error():
    with _mock_client({}, raise_error=True):
        result = await search("Tokyo")
    assert result is None


async def test_search_returns_none_on_malformed_response():
    # Missing required keys → KeyError/ValueError caught internally.
    with _mock_client([{"unexpected": "shape"}]):
        result = await search("Somewhere")
    assert result is None
