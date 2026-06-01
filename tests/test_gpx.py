from pathlib import Path

import pytest

from app.services.gpx import (
    GPXParseError,
    DOWNSAMPLE_TARGET,
    compute_dedup_hash,
    parse_gpx,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample.gpx"


def test_parse_sample_stats():
    stats = parse_gpx(FIXTURE.read_bytes())
    assert stats.distance_m > 1000  # ~1.3 km of track
    assert stats.elapsed_time_s == 210  # 09:00:00 -> 09:03:30
    assert stats.moving_time_s > 0
    assert stats.max_speed > 0
    assert stats.elev_gain > 0
    assert stats.max_elev == 60
    assert stats.start_lat == pytest.approx(37.8000)
    assert stats.start_lon == pytest.approx(-122.4000)
    assert stats.start_time is not None


def test_points_have_speed_and_sequence():
    stats = parse_gpx(FIXTURE.read_bytes())
    assert len(stats.points) >= 2
    assert [p.seq for p in stats.points] == list(range(len(stats.points)))
    # First point has no speed (no predecessor); a later one does.
    assert stats.points[0].speed is None
    assert any(p.speed and p.speed > 0 for p in stats.points)


def test_track_wkt_is_linestring_z():
    stats = parse_gpx(FIXTURE.read_bytes())
    assert stats.track_wkt.startswith("LINESTRING Z (")
    assert stats.track_wkt.count(",") == 6  # 7 points -> 6 commas


def test_downsample_caps_points():
    # Synthesize a long track and confirm it caps near the target.
    head = (
        '<?xml version="1.0"?><gpx version="1.1" creator="t" '
        'xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
    )
    pts = []
    for i in range(DOWNSAMPLE_TARGET * 3):
        lat = 37.0 + i * 0.0001
        pts.append(f'<trkpt lat="{lat:.5f}" lon="-122.0"><ele>{i}</ele></trkpt>')
    gpx = head + "".join(pts) + "</trkseg></trk></gpx>"
    stats = parse_gpx(gpx.encode())
    assert len(stats.points) <= DOWNSAMPLE_TARGET + 1


def test_dedup_hash_stable_and_distinct():
    from datetime import datetime, timezone

    t = datetime(2024, 6, 1, 9, 0, tzinfo=timezone.utc)
    h1 = compute_dedup_hash(t, 37.8, -122.4)
    h2 = compute_dedup_hash(t, 37.8, -122.4)
    h3 = compute_dedup_hash(t, 37.9, -122.4)
    assert h1 == h2
    assert h1 != h3


def test_empty_gpx_raises():
    bad = (
        '<?xml version="1.0"?><gpx version="1.1" creator="t" '
        'xmlns="http://www.topografix.com/GPX/1/1"></gpx>'
    )
    with pytest.raises(GPXParseError):
        parse_gpx(bad.encode())
