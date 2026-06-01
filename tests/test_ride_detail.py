import httpx
import pytest

from app.auth.deps import require_login
from app.db import engine as global_engine
from app.main import app
from app.models.ride import STATUS_DONE, Ride, RidePoint


@pytest.mark.asyncio
async def test_points_json_returns_series(db, user):
    ride = Ride(user_id=user.id, processing_status=STATUS_DONE, published=True)
    db.add(ride)
    await db.flush()
    for i in range(5):
        db.add(
            RidePoint(
                ride_id=ride.id, seq=i, lat=37.0 + i * 0.001, lon=-122.0,
                elev=10.0 * i, speed=5.0 + i, t=float(i * 10),
            )
        )
    await db.commit()
    ride_id = ride.id

    app.dependency_overrides[require_login] = lambda: user
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8000") as c:
            resp = await c.get(f"/rides/{ride_id}/points.json")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["points"]) == 5
        p0 = body["points"][0]
        assert set(p0) == {"lat", "lon", "elev", "speed", "t"}
        assert body["points"][4]["speed"] == 9.0
    finally:
        app.dependency_overrides.clear()
        from sqlalchemy import delete

        await db.execute(delete(Ride).where(Ride.id == ride_id))
        await db.commit()
        await global_engine.dispose()


@pytest.mark.asyncio
async def test_points_json_owner_only(db, user):
    # A ride owned by someone else must 404 for this user.
    other = Ride(user_id=user.id, processing_status=STATUS_DONE)
    db.add(other)
    await db.flush()
    ride_id = other.id
    await db.commit()

    # Override with a *different* user id so ownership check fails.
    class Fake:
        id = __import__("uuid").uuid4()

    app.dependency_overrides[require_login] = lambda: Fake()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8000") as c:
            resp = await c.get(f"/rides/{ride_id}/points.json")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()
        from sqlalchemy import delete

        await db.execute(delete(Ride).where(Ride.id == ride_id))
        await db.commit()
        await global_engine.dispose()
