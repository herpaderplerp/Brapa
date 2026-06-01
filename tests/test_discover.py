import uuid

import pytest
from geoalchemy2.elements import WKTElement

from app.models.ride import STATUS_DONE, VISIBILITY_FRIENDS, VISIBILITY_PRIVATE, VISIBILITY_PUBLIC, Ride
from app.models.social import Like
from app.models.user import User
from app.services import discover as discover_svc
from app.services import geocode, social


async def _user(db, name="U") -> User:
    u = User(email=f"{uuid.uuid4().hex}@t.dev", display_name=name)
    db.add(u)
    await db.flush()
    return u


async def _ride(db, owner, *, vis=VISIBILITY_PUBLIC, lon=10.0, lat=10.0) -> Ride:
    # tiny 2-point track near (lon, lat)
    wkt = f"LINESTRING Z ({lon} {lat} 0, {lon + 0.001} {lat + 0.001} 0)"
    r = Ride(
        user_id=owner.id, visibility=vis, published=True, processing_status=STATUS_DONE,
        title="r", distance_m=1000, start_lat=lat, start_lon=lon,
        track=WKTElement(wkt, srid=4326),
    )
    db.add(r)
    await db.flush()
    return r


# Use a tiny unique-ish coordinate window per test to avoid cross-test bleed in
# the shared dev DB.
def _box(lon, lat, d=0.01):
    return (lon - d, lat - d, lon + d, lat + d)


@pytest.mark.asyncio
async def test_geocode_search_parses(monkeypatch):
    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"lat": "45.4", "lon": "-75.7",
                     "boundingbox": ["45.0", "45.8", "-76.0", "-75.0"]}]

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, *a, **k):
            return Resp()

    monkeypatch.setattr(geocode.httpx, "AsyncClient", Client)
    out = await geocode.search("Ottawa")
    assert out is not None
    lat, lon, bbox = out
    assert (lat, lon) == (45.4, -75.7)
    assert bbox == (-76.0, 45.0, -75.0, 45.8)  # (min_lon,min_lat,max_lon,max_lat)


@pytest.mark.asyncio
async def test_bbox_search_respects_visibility(db, user):
    owner = await _user(db, "Owner")
    friend = await _user(db, "Friend")
    await social.send_request(db, user.id, friend.id)
    await social.send_request(db, friend.id, user.id)

    lon, lat = 30.0, 30.0
    pub = await _ride(db, owner, vis=VISIBILITY_PUBLIC, lon=lon, lat=lat)
    await _ride(db, owner, vis=VISIBILITY_PRIVATE, lon=lon, lat=lat)
    await _ride(db, owner, vis=VISIBILITY_FRIENDS, lon=lon, lat=lat)  # owner not friend
    fr_ride = await _ride(db, friend, vis=VISIBILITY_FRIENDS, lon=lon, lat=lat)
    await _ride(db, owner, vis=VISIBILITY_PUBLIC, lon=80.0, lat=80.0)  # outside box
    await db.flush()

    found = await discover_svc.rides_in_bbox(db, user.id, _box(lon, lat))
    ids = {r.id for r in found}
    assert pub.id in ids          # public in box
    assert fr_ride.id in ids      # friend's friends-only visible
    # private + non-friend friends-only + out-of-box excluded
    assert len(ids) == 2


@pytest.mark.asyncio
async def test_popular_orders_by_engagement(db, user):
    owner = await _user(db, "Owner")
    lon, lat = 50.0, 50.0
    low = await _ride(db, owner, lon=lon, lat=lat)
    high = await _ride(db, owner, lon=lon, lat=lat)
    # 2 likes on `high`, 0 on `low`
    liker = await _user(db, "L")
    db.add(Like(user_id=user.id, ride_id=high.id))
    db.add(Like(user_id=liker.id, ride_id=high.id))
    await db.flush()

    cards, _ = await discover_svc.popular_rides(db, user.id, bbox=_box(lon, lat))
    ordered = [c[0].id for c in cards]
    assert ordered.index(high.id) < ordered.index(low.id)
    high_card = next(c for c in cards if c[0].id == high.id)
    assert high_card[1] == 2  # like count
