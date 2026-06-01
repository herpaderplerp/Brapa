import uuid

import httpx
import pytest

from app.auth.deps import require_login
from app.db import engine as global_engine
from app.main import app
from app.models.bike import Bike
from app.models.photo import Photo
from app.models.ride import STATUS_DONE, Ride
from app.models.social import Comment, Like
from app.models.user import User
from app.services import storage


async def _seed(db):
    u = User(email=f"{uuid.uuid4().hex}@t.dev", display_name="Doomed")
    db.add(u)
    await db.flush()
    bike = Bike(user_id=u.id, make="Yamaha", model="MT-07")
    db.add(bike)
    gpx_key = storage.save_gpx(b"<gpx></gpx>")
    photo_key = storage.save_photo(b"\xff\xd8\xff", "jpg")
    ride = Ride(user_id=u.id, processing_status=STATUS_DONE, published=True, gpx_blob_key=gpx_key)
    db.add(ride)
    await db.flush()
    db.add(Photo(ride_id=ride.id, blob_key=photo_key))
    db.add(Like(user_id=u.id, ride_id=ride.id))
    db.add(Comment(ride_id=ride.id, user_id=u.id, body="hi"))
    await db.commit()
    return u, ride.id, gpx_key, photo_key


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://x")


@pytest.mark.asyncio
async def test_delete_requires_confirm_word(db, user):
    u, ride_id, gpx_key, photo_key = await _seed(db)
    app.dependency_overrides[require_login] = lambda: u
    try:
        async with _client() as c:
            r = await c.post("/account/delete", data={"confirm": "nope"}, follow_redirects=False)
        assert r.status_code == 303
        # user still present
        assert await db.get(User, u.id) is not None
    finally:
        app.dependency_overrides.clear()
        from sqlalchemy import delete

        await db.execute(delete(Ride).where(Ride.id == ride_id))
        await db.execute(delete(User).where(User.id == u.id))
        await db.commit()
        storage.delete(gpx_key)
        storage.delete(photo_key)
        await global_engine.dispose()


@pytest.mark.asyncio
async def test_delete_cascades_and_purges_blobs(db, user):
    u, ride_id, gpx_key, photo_key = await _seed(db)
    assert storage.path_for(gpx_key).exists()

    app.dependency_overrides[require_login] = lambda: u
    try:
        async with _client() as c:
            r = await c.post("/account/delete", data={"confirm": "Confirm"}, follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/"
        # Drop stale identity-map copies so gets hit the DB.
        db.expunge_all()
        # User + all dependents gone.
        assert await db.get(User, u.id) is None
        assert await db.get(Ride, ride_id) is None
        # Blob files purged from storage.
        assert not storage.path_for(gpx_key).exists()
        assert not storage.path_for(photo_key).exists()
    finally:
        app.dependency_overrides.clear()
        await global_engine.dispose()
