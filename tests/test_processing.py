from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.db import engine as global_engine
from app.models.ride import STATUS_DONE, STATUS_DUPLICATE, Ride, RidePoint, RideWeather
from app.services import storage
from app.services.processing import process_ride

FIXTURE = Path(__file__).parent / "fixtures" / "sample.gpx"


@pytest.mark.asyncio
async def test_process_ride_end_to_end(db, user):
    # Arrange: store the GPX blob and a processing ride row, committed so the
    # processing pipeline (its own session) can see them.
    key = storage.save_gpx(FIXTURE.read_bytes())
    ride = Ride(user_id=user.id, gpx_blob_key=key)
    db.add(ride)
    await db.commit()
    ride_id = ride.id

    try:
        # Act
        await process_ride(ride_id)

        # Assert: stats populated, points stored, weather row present.
        db.expire_all()
        refreshed = await db.get(Ride, ride_id)
        assert refreshed.processing_status in (STATUS_DONE, STATUS_DUPLICATE)
        assert refreshed.distance_m and refreshed.distance_m > 1000
        assert refreshed.dedup_hash
        assert refreshed.start_lat == pytest.approx(37.8, abs=0.01)

        n_points = (
            await db.execute(select(RidePoint).where(RidePoint.ride_id == ride_id))
        ).scalars().all()
        assert len(n_points) >= 2

        weather = await db.get(RideWeather, ride_id)
        assert weather is not None
        assert weather.status in ("ok", "unavailable")

        # Regression: templates read ride.weather / ride.bike AFTER the request's
        # session has closed. With lazy="selectin" these are preloaded, so no
        # lazy IO (which would raise MissingGreenlet on an async session).
        from app.db import SessionLocal

        async with SessionLocal() as s:
            r = await s.get(Ride, ride_id)
        # session now closed; attribute access must not trigger IO
        assert r.weather is None or r.weather.status in ("ok", "unavailable")
        assert r.bike is None
    finally:
        # Cleanup committed rows (cascades to points/weather), and dispose the
        # global engine so its pool doesn't outlive this test's event loop.
        await db.execute(delete(Ride).where(Ride.id == ride_id))
        await db.commit()
        storage.delete(key)
        await global_engine.dispose()
