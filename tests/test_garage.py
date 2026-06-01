import httpx
import pytest

from app.main import app
from app.services import garage as svc


@pytest.mark.asyncio
async def test_first_bike_becomes_default(db, user):
    bike = await svc.add_bike(
        db, user.id, make="Yamaha", model="MT-07", year=2022, nickname=None, photo_url=None
    )
    assert bike.is_default is True
    assert await svc.has_active_bike(db, user.id) is True


@pytest.mark.asyncio
async def test_second_bike_not_default_then_set_default(db, user):
    first = await svc.add_bike(
        db, user.id, make="Yamaha", model="MT-07", year=2022, nickname=None, photo_url=None
    )
    second = await svc.add_bike(
        db, user.id, make="Honda", model="CB500", year=2020, nickname=None, photo_url=None
    )
    assert second.is_default is False

    await svc.set_default(db, user.id, second)
    await db.refresh(first)
    assert second.is_default is True
    assert first.is_default is False


@pytest.mark.asyncio
async def test_deactivate_default_reassigns(db, user):
    first = await svc.add_bike(
        db, user.id, make="Yamaha", model="MT-07", year=2022, nickname=None, photo_url=None
    )
    second = await svc.add_bike(
        db, user.id, make="Honda", model="CB500", year=2020, nickname=None, photo_url=None
    )
    # Deactivate the default (first) -> default should move to the other active bike.
    await svc.set_active(db, user.id, first, False)
    await db.flush()
    await db.refresh(second)
    assert first.is_active is False
    assert first.is_default is False
    assert second.is_default is True


@pytest.mark.asyncio
async def test_deactivate_last_bike_blocks_upload_gate(db, user):
    only = await svc.add_bike(
        db, user.id, make="Yamaha", model="MT-07", year=2022, nickname=None, photo_url=None
    )
    await svc.set_active(db, user.id, only, False)
    assert await svc.has_active_bike(db, user.id) is False


@pytest.mark.asyncio
async def test_garage_requires_login():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8000") as c:
        resp = await c.get("/garage", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"
