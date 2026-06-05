"""Tests for the bike management HTTP routes in /garage."""
from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import delete

from sqlalchemy import delete, select

from app.auth.deps import require_login
from app.db import engine as global_engine
from app.main import app
from app.models.bike import Bike
from app.models.user import User
from app.services import garage as svc


def _client():
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:8000"
    )


async def _cleanup(db, user):
    app.dependency_overrides.clear()
    # Deleting the user cascades to bikes at the DB level (ondelete=CASCADE).
    await db.execute(delete(User).where(User.id == user.id))
    await db.commit()
    await global_engine.dispose()


def _select_bikes(user_id):
    return select(Bike).where(Bike.user_id == user_id)


# ---------------------------------------------------------------------------
# POST /garage – add bike
# ---------------------------------------------------------------------------


async def test_add_bike_route_creates_bike(db, user):
    """POST /garage with valid fields creates a bike and returns the list partial."""
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            resp = await c.post(
                "/garage",
                data={"make": "Kawasaki", "model": "Z900", "year": "2021"},
            )
        assert resp.status_code == 200
        assert "Kawasaki" in resp.text
        assert "Z900" in resp.text
        db.expire_all()
        bikes = (await db.execute(_select_bikes(user.id))).scalars().all()
        assert len(bikes) == 1
        assert bikes[0].make == "Kawasaki"
    finally:
        await _cleanup(db, user)


async def test_add_bike_first_bike_becomes_default(db, user):
    """The very first bike added for a user automatically becomes the default."""
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            await c.post("/garage", data={"make": "Honda", "model": "CB500", "year": "2020"})
        db.expire_all()
        bikes = (await db.execute(_select_bikes(user.id))).scalars().all()
        assert bikes[0].is_default is True
    finally:
        await _cleanup(db, user)


async def test_add_bike_rejects_empty_make(db, user):
    """POST /garage with a blank make field returns 422."""
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            resp = await c.post("/garage", data={"make": "  ", "model": "Z900"})
        assert resp.status_code == 422
    finally:
        await _cleanup(db, user)


async def test_add_bike_rejects_empty_model(db, user):
    """POST /garage with a blank model field returns 422."""
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            resp = await c.post("/garage", data={"make": "Kawasaki", "model": ""})
        assert resp.status_code == 422
    finally:
        await _cleanup(db, user)


# ---------------------------------------------------------------------------
# GET /garage/{id}/edit – edit form
# ---------------------------------------------------------------------------


async def test_edit_form_returns_bike_data(db, user):
    """GET /garage/{id}/edit returns an HTML form pre-populated with bike fields."""
    bike = await svc.add_bike(
        db, user.id, make="Ducati", model="Monster", year=2019, nickname=None, photo_url=None
    )
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            resp = await c.get(f"/garage/{bike.id}/edit")
        assert resp.status_code == 200
        assert "Ducati" in resp.text
        assert "Monster" in resp.text
    finally:
        await _cleanup(db, user)


async def test_edit_form_unknown_bike_returns_404(db, user):
    """Requesting the edit form for a non-existent bike returns 404."""
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            resp = await c.get(f"/garage/{uuid.uuid4()}/edit")
        assert resp.status_code == 404
    finally:
        await _cleanup(db, user)


# ---------------------------------------------------------------------------
# POST /garage/{id} – update bike
# ---------------------------------------------------------------------------


async def test_update_bike_changes_model_and_year(db, user):
    """POST /garage/{id} updates the bike's model and year fields."""
    bike = await svc.add_bike(
        db, user.id, make="Honda", model="CB500", year=2020, nickname=None, photo_url=None
    )
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            resp = await c.post(
                f"/garage/{bike.id}",
                data={"make": "Honda", "model": "CB650R", "year": "2023"},
            )
        assert resp.status_code == 200
        assert "CB650R" in resp.text
        db.expire_all()
        updated = await db.get(Bike, bike.id)
        assert updated.model == "CB650R"
        assert updated.year == 2023
    finally:
        await _cleanup(db, user)


async def test_update_bike_non_digit_year_stored_as_none(db, user):
    """A non-numeric year value in the update form is stored as None."""
    bike = await svc.add_bike(
        db, user.id, make="BMW", model="R1250GS", year=2021, nickname=None, photo_url=None
    )
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            await c.post(
                f"/garage/{bike.id}",
                data={"make": "BMW", "model": "R1250GS", "year": "not-a-year"},
            )
        db.expire_all()
        updated = await db.get(Bike, bike.id)
        assert updated.year is None
    finally:
        await _cleanup(db, user)


async def test_update_bike_other_users_bike_returns_404(db, user):
    """Updating a bike belonging to another user returns 404."""
    other = User(email=f"{uuid.uuid4().hex}@t.dev", display_name="Other")
    db.add(other)
    bike = await svc.add_bike(
        db, other.id, make="KTM", model="Duke", year=2022, nickname=None, photo_url=None
    )
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            resp = await c.post(
                f"/garage/{bike.id}",
                data={"make": "KTM", "model": "Adventure", "year": "2023"},
            )
        assert resp.status_code == 404
    finally:
        await db.execute(delete(User).where(User.id.in_([user.id, other.id])))
        await db.commit()
        app.dependency_overrides.clear()
        await global_engine.dispose()


# ---------------------------------------------------------------------------
# POST /garage/{id}/default – set default bike
# ---------------------------------------------------------------------------


async def test_set_default_bike_route(db, user):
    """POST /garage/{id}/default promotes a bike to default and demotes the old one."""
    first = await svc.add_bike(
        db, user.id, make="Yamaha", model="MT-07", year=2022, nickname=None, photo_url=None
    )
    second = await svc.add_bike(
        db, user.id, make="Honda", model="CB500", year=2020, nickname=None, photo_url=None
    )
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            resp = await c.post(f"/garage/{second.id}/default")
        assert resp.status_code == 200
        db.expire_all()
        await db.refresh(first)
        await db.refresh(second)
        assert second.is_default is True
        assert first.is_default is False
    finally:
        await _cleanup(db, user)


# ---------------------------------------------------------------------------
# POST /garage/{id}/active – toggle active state
# ---------------------------------------------------------------------------


async def test_toggle_bike_to_inactive(db, user):
    """POST /garage/{id}/active with active=false deactivates the bike."""
    bike = await svc.add_bike(
        db, user.id, make="Yamaha", model="MT-07", year=2022, nickname=None, photo_url=None
    )
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            resp = await c.post(f"/garage/{bike.id}/active", data={"active": "false"})
        assert resp.status_code == 200
        db.expire_all()
        updated = await db.get(Bike, bike.id)
        assert updated.is_active is False
    finally:
        await _cleanup(db, user)


async def test_toggle_bike_back_to_active(db, user):
    """POST /garage/{id}/active with active=true reactivates a deactivated bike."""
    bike = await svc.add_bike(
        db, user.id, make="Yamaha", model="MT-07", year=2022, nickname=None, photo_url=None
    )
    await svc.set_active(db, user.id, bike, False)
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            resp = await c.post(f"/garage/{bike.id}/active", data={"active": "true"})
        assert resp.status_code == 200
        db.expire_all()
        updated = await db.get(Bike, bike.id)
        assert updated.is_active is True
    finally:
        await _cleanup(db, user)
