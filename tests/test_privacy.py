import uuid

import httpx
from sqlalchemy import delete

from app.auth.deps import require_login
from app.db import engine as global_engine
from app.main import app
from app.models.photo import Photo
from app.models.privacy import PrivacyZone
from app.models.ride import STATUS_DONE, VISIBILITY_PUBLIC, Ride, RidePoint
from app.models.user import User
from app.services import feed as feed_svc
from app.services import privacy as privacy_svc


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://x")


# A north–south line of 10 points ~111 m apart (Δlat 0.001), all at lon -122.0.
def _pts(rid):
    return [
        RidePoint(ride_id=rid, seq=i, lat=37.000 + i * 0.001, lon=-122.0, t=float(i))
        for i in range(10)
    ]


async def _ride(db, owner, *, visibility=VISIBILITY_PUBLIC):
    ride = Ride(
        user_id=owner.id, processing_status=STATUS_DONE, published=True, visibility=visibility,
        start_lat=37.000, start_lon=-122.0,
    )
    db.add(ride)
    await db.flush()
    for p in _pts(ride.id):
        db.add(p)
    await db.commit()
    return ride


async def _zone(db, owner, lat=37.005, lon=-122.0, radius=150.0):
    z = PrivacyZone(user_id=owner.id, label="Home", center_lat=lat, center_lon=lon, radius_m=radius)
    db.add(z)
    await db.commit()
    return z


async def _cleanup(db, ride_id=None, *user_ids):
    app.dependency_overrides.clear()
    if ride_id is not None:
        await db.execute(delete(Photo).where(Photo.ride_id == ride_id))
        await db.execute(delete(RidePoint).where(RidePoint.ride_id == ride_id))
        await db.execute(delete(Ride).where(Ride.id == ride_id))
    for uid in user_ids:
        await db.execute(delete(PrivacyZone).where(PrivacyZone.user_id == uid))
        await db.execute(delete(User).where(User.id == uid))
    await db.commit()
    await global_engine.dispose()


# --- service ---------------------------------------------------------------

def test_clip_segments_splits_around_zone():
    rid = uuid.uuid4()
    zone = privacy_svc.Zone(lat=37.005, lon=-122.0, radius_m=150.0)
    segs = privacy_svc.clip_segments(_pts(rid), [zone])
    # i=4,5,6 fall within 150 m of 37.005; the line splits into two runs.
    seqs = [[p.seq for p in seg] for seg in segs]
    assert seqs == [[0, 1, 2, 3], [7, 8, 9]]


def test_clip_segments_splits_outside_points_when_segment_crosses_zone():
    rid = uuid.uuid4()
    pts = [
        RidePoint(ride_id=rid, seq=0, lat=0.0, lon=-0.002),
        RidePoint(ride_id=rid, seq=1, lat=0.0, lon=0.002),
    ]
    zone = privacy_svc.Zone(lat=0.0, lon=0.0, radius_m=100.0)

    segs = privacy_svc.clip_segments(pts, [zone])

    assert [[p.seq for p in seg] for seg in segs] == [[0], [1]]


def test_clip_segments_no_zones_is_single_segment():
    rid = uuid.uuid4()
    segs = privacy_svc.clip_segments(_pts(rid), [])
    assert len(segs) == 1 and len(segs[0]) == 10


def test_in_any_zone():
    z = privacy_svc.Zone(lat=37.0, lon=-122.0, radius_m=150.0)
    assert privacy_svc.in_any_zone(37.0, -122.0, [z]) is True
    assert privacy_svc.in_any_zone(37.01, -122.0, [z]) is False  # ~1.1 km away


def test_clamp_radius():
    assert privacy_svc.clamp_radius(10) == privacy_svc.RADIUS_MIN_M
    assert privacy_svc.clamp_radius(99999) == privacy_svc.RADIUS_MAX_M
    assert privacy_svc.clamp_radius(300) == 300


def test_clip_gpx_drops_in_zone_points():
    gpx = (
        '<?xml version="1.0"?><gpx version="1.1"><trk><trkseg>'
        + "".join(
            f'<trkpt lat="{37.000 + i * 0.001}" lon="-122.0"></trkpt>' for i in range(10)
        )
        + "</trkseg></trk></gpx>"
    ).encode()
    zone = privacy_svc.Zone(lat=37.005, lon=-122.0, radius_m=150.0)
    out = privacy_svc.clip_gpx(gpx, [zone]).decode()
    assert "37.005" not in out and "37.004" not in out and "37.006" not in out
    assert "37.003" in out and "37.007" in out
    assert out.count("<trkseg>") == 2  # split into two segments


def test_clip_gpx_splits_outside_points_when_segment_crosses_zone():
    gpx = (
        '<?xml version="1.0"?><gpx version="1.1"><trk><trkseg>'
        '<trkpt lat="0.0" lon="-0.004"></trkpt>'
        '<trkpt lat="0.0" lon="-0.002"></trkpt>'
        '<trkpt lat="0.0" lon="0.002"></trkpt>'
        '<trkpt lat="0.0" lon="0.004"></trkpt>'
        '</trkseg></trk></gpx>'
    ).encode()
    zone = privacy_svc.Zone(lat=0.0, lon=0.0, radius_m=100.0)

    out = privacy_svc.clip_gpx(gpx, [zone]).decode()

    assert out.count("<trkseg>") == 2
    assert out.index('lon="-0.002"') < out.index("</trkseg>")
    second_seg = out.split("<trkseg>", 2)[2]
    assert 'lon="0.002"' in second_seg


async def test_effective_zones_owner_bypass(db, user):
    ride = await _ride(db, user)
    await _zone(db, user)
    stranger = User(email=f"{uuid.uuid4().hex}@t.dev", display_name="S")
    db.add(stranger)
    await db.flush()
    try:
        assert await privacy_svc.effective_zones(db, user.id, ride) == []  # owner: full
        assert len(await privacy_svc.effective_zones(db, stranger.id, ride)) == 1
    finally:
        await _cleanup(db, ride.id, user.id, stranger.id)


async def test_track_thumb_preserves_segment_crossing_gaps(db, user):
    ride = Ride(
        user_id=user.id,
        processing_status=STATUS_DONE,
        published=True,
        visibility=VISIBILITY_PUBLIC,
    )
    db.add(ride)
    await db.flush()
    for seq, lon in enumerate([-0.004, -0.002, 0.002, 0.004]):
        db.add(RidePoint(ride_id=ride.id, seq=seq, lat=0.0, lon=lon))
    await db.commit()
    zone = privacy_svc.Zone(lat=0.0, lon=0.0, radius_m=100.0)
    try:
        thumb = await feed_svc.track_thumb(db, ride.id, zones=[zone])

        assert thumb is not None
        assert len(thumb) == 2
    finally:
        await _cleanup(db, ride.id, user.id)


# --- routes ----------------------------------------------------------------

async def test_points_json_clipped_for_stranger_full_for_owner(db, user):
    owner = User(email=f"{uuid.uuid4().hex}@t.dev", display_name="Owner")
    db.add(owner)
    await db.flush()
    ride = await _ride(db, owner)
    await _zone(db, owner)
    try:
        # Owner sees the whole track in a single segment.
        app.dependency_overrides[require_login] = lambda: owner
        async with _client() as c:
            r = await c.get(f"/rides/{ride.id}/points.json")
        body = r.json()
        assert r.status_code == 200
        assert len(body["points"]) == 10 and len(body["segments"]) == 1

        # Stranger sees a clipped track: gap segments, no in-zone points.
        app.dependency_overrides[require_login] = lambda: user
        async with _client() as c:
            r = await c.get(f"/rides/{ride.id}/points.json")
        body = r.json()
        assert len(body["segments"]) == 2
        assert len(body["points"]) == 7
        for p in body["points"]:
            assert not privacy_svc.in_any_zone(
                p["lat"], p["lon"], [privacy_svc.Zone(37.005, -122.0, 150.0)]
            )
    finally:
        await _cleanup(db, ride.id, owner.id, user.id)


async def test_photos_json_hides_in_zone_photo(db, user):
    owner = User(email=f"{uuid.uuid4().hex}@t.dev", display_name="Owner")
    db.add(owner)
    await db.flush()
    ride = await _ride(db, owner)
    await _zone(db, owner)
    db.add(Photo(ride_id=ride.id, blob_key="a.jpg", lat=37.005, lon=-122.0, seq=0))  # in zone
    db.add(Photo(ride_id=ride.id, blob_key="b.jpg", lat=37.000, lon=-122.0, seq=1))  # outside
    await db.commit()
    try:
        app.dependency_overrides[require_login] = lambda: user  # stranger
        async with _client() as c:
            r = await c.get(f"/rides/{ride.id}/photos.json")
        photos = r.json()["photos"]
        assert len(photos) == 1 and photos[0]["lat"] == 37.000
    finally:
        await _cleanup(db, ride.id, owner.id, user.id)


async def test_create_and_delete_zone_route(db, user):
    await db.commit()  # persist the fixture user so the route's session sees it
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            r = await c.post(
                "/privacy-zones",
                data={"lat": "37.5", "lon": "-122.1", "radius_m": "300", "label": "Home"},
                follow_redirects=False,
            )
            assert r.status_code == 303
            page = await c.get("/privacy-zones")
        assert "Home" in page.text
        db.expunge_all()
        zones = (
            await db.execute(
                PrivacyZone.__table__.select().where(PrivacyZone.user_id == user.id)
            )
        ).all()
        assert len(zones) == 1
        zid = zones[0].id
        async with _client() as c:
            d = await c.post(f"/privacy-zones/{zid}/delete", follow_redirects=False)
        assert d.status_code == 303
        db.expunge_all()
        assert await db.get(PrivacyZone, zid) is None
    finally:
        await _cleanup(db, None, user.id)


async def test_zone_radius_is_clamped_on_create(db, user):
    await db.commit()  # persist the fixture user so the route's session sees it
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            await c.post(
                "/privacy-zones",
                data={"lat": "1.0", "lon": "2.0", "radius_m": "999999", "label": "Big"},
            )
        db.expunge_all()
        z = (
            await db.execute(
                PrivacyZone.__table__.select().where(PrivacyZone.user_id == user.id)
            )
        ).first()
        assert z.radius_m == privacy_svc.RADIUS_MAX_M
    finally:
        await _cleanup(db, None, user.id)
