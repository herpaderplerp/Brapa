import uuid

import httpx
import pytest

from app.auth.deps import require_login
from app.db import engine as global_engine
from app.main import app
from app.models.photo import Photo
from app.models.ride import STATUS_DONE, Ride
from app.models.user import User


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://x")


async def _ride_with_photo(db, owner):
    ride = Ride(user_id=owner.id, processing_status=STATUS_DONE, published=True)
    db.add(ride)
    await db.flush()
    photo = Photo(ride_id=ride.id, blob_key="photos/x.jpg")  # no lat/lon
    db.add(photo)
    await db.commit()
    return ride.id, photo.id


@pytest.mark.asyncio
async def test_owner_places_photo(db, user):
    ride_id, photo_id = await _ride_with_photo(db, user)
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            r = await c.post(
                f"/rides/{ride_id}/photos/{photo_id}/place",
                data={"lat": "45.42", "lon": "-75.7"},
                follow_redirects=False,
            )
        assert r.status_code == 303
        db.expunge_all()
        p = await db.get(Photo, photo_id)
        assert p.lat == pytest.approx(45.42)
        assert p.lon == pytest.approx(-75.7)
    finally:
        app.dependency_overrides.clear()
        from sqlalchemy import delete

        await db.execute(delete(Photo).where(Photo.ride_id == ride_id))
        await db.execute(delete(Ride).where(Ride.id == ride_id))
        await db.commit()
        await global_engine.dispose()


@pytest.mark.asyncio
async def test_place_rejects_bad_coords(db, user):
    ride_id, photo_id = await _ride_with_photo(db, user)
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            r = await c.post(
                f"/rides/{ride_id}/photos/{photo_id}/place",
                data={"lat": "999", "lon": "0"},
                follow_redirects=False,
            )
        assert r.status_code == 422
    finally:
        app.dependency_overrides.clear()
        from sqlalchemy import delete

        await db.execute(delete(Photo).where(Photo.ride_id == ride_id))
        await db.execute(delete(Ride).where(Ride.id == ride_id))
        await db.commit()
        await global_engine.dispose()


@pytest.mark.asyncio
async def test_non_owner_cannot_place(db, user):
    owner = User(email=f"{uuid.uuid4().hex}@t.dev", display_name="Owner")
    db.add(owner)
    await db.flush()
    ride_id, photo_id = await _ride_with_photo(db, owner)
    app.dependency_overrides[require_login] = lambda: user  # not the owner
    try:
        async with _client() as c:
            r = await c.post(
                f"/rides/{ride_id}/photos/{photo_id}/place",
                data={"lat": "10", "lon": "10"},
                follow_redirects=False,
            )
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()
        from sqlalchemy import delete

        await db.execute(delete(Photo).where(Photo.ride_id == ride_id))
        await db.execute(delete(Ride).where(Ride.id == ride_id))
        await db.execute(delete(User).where(User.id == owner.id))
        await db.commit()
        await global_engine.dispose()
