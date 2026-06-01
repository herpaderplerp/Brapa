import uuid

import httpx
import pytest

from app.auth.deps import require_login
from app.db import engine as global_engine
from app.main import app
from app.models.ride import STATUS_DONE, VISIBILITY_PRIVATE, VISIBILITY_PUBLIC, Ride
from app.models.user import User


async def _user(db, name="U") -> User:
    u = User(email=f"{uuid.uuid4().hex}@t.dev", display_name=name)
    db.add(u)
    await db.flush()
    return u


async def _ride(db, owner, vis=VISIBILITY_PUBLIC) -> Ride:
    r = Ride(user_id=owner.id, visibility=vis, published=True,
             processing_status=STATUS_DONE, title="r", distance_m=1000)
    db.add(r)
    await db.flush()
    return r


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://x")


@pytest.mark.asyncio
async def test_compare_two_viewable(db, user):
    a = await _ride(db, user)
    b = await _ride(db, user)
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            r = await c.get(f"/compare?a={a.id}&b={b.id}")
        assert r.status_code == 200
        assert 'id="map"' in r.text  # both viewable -> overlay rendered
    finally:
        app.dependency_overrides.clear()
        from sqlalchemy import delete

        await db.execute(delete(Ride).where(Ride.user_id == user.id))
        await db.commit()
        await global_engine.dispose()


@pytest.mark.asyncio
async def test_compare_hides_unviewable_b(db, user):
    a = await _ride(db, user)
    stranger = await _user(db, "Stranger")
    b = await _ride(db, stranger, VISIBILITY_PRIVATE)  # not viewable by user
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            r = await c.get(f"/compare?a={a.id}&b={b.id}")
        assert r.status_code == 200
        # b not viewable -> no overlay, no leak of b's track endpoint
        assert 'id="map"' not in r.text
        assert f"/rides/{b.id}/points.json" not in r.text
    finally:
        app.dependency_overrides.clear()
        from sqlalchemy import delete

        await db.execute(delete(Ride).where(Ride.id.in_([a.id, b.id])))
        await db.execute(delete(User).where(User.id == stranger.id))
        await db.commit()
        await global_engine.dispose()
