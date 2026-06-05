"""Tests for ride upload, review, edit, and delete routes."""
from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import delete, select

from app.auth.deps import require_login
from app.db import engine as global_engine
from app.main import app
from app.models.bike import Bike
from app.models.ride import (
    STATUS_DONE,
    STATUS_PROCESSING,
    VISIBILITY_PRIVATE,
    Ride,
)
from app.models.user import User
from app.services import garage as garage_svc
from app.services import storage

FIXTURE_GPX = Path(__file__).parent / "fixtures" / "sample.gpx"


def _client():
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:8000"
    )


async def _add_bike(db, user):
    return await garage_svc.add_bike(
        db, user.id, make="Yamaha", model="MT-07", year=2022, nickname=None, photo_url=None
    )


async def _cleanup(db, user):
    """Delete user and all cascaded data (bikes, rides, blobs) after a route test."""
    app.dependency_overrides.clear()
    rides = (
        await db.execute(select(Ride).where(Ride.user_id == user.id))
    ).scalars().all()
    for ride in rides:
        if ride.gpx_blob_key:
            storage.delete(ride.gpx_blob_key)
    await db.execute(delete(User).where(User.id == user.id))
    await db.commit()
    await global_engine.dispose()


# ---------------------------------------------------------------------------
# Upload page (GET)
# ---------------------------------------------------------------------------


async def test_upload_page_shows_needs_bike_warning(db, user):
    """Upload page shows a 'needs_bike' state when the user has no active bikes."""
    # No commit needed: user.id is a UUID that exists in the override; the route
    # queries bikes (finds none) and renders with needs_bike=True.
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            resp = await c.get("/rides/upload")
        assert resp.status_code == 200
        # The template uses {% if needs_bike %} to show an alternative prompt.
        assert "bike" in resp.text.lower()
    finally:
        app.dependency_overrides.clear()
        await global_engine.dispose()


async def test_upload_page_shows_form_with_active_bike(db, user):
    """Upload page renders the upload form when the user has an active bike."""
    await _add_bike(db, user)
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            resp = await c.get("/rides/upload")
        assert resp.status_code == 200
    finally:
        await _cleanup(db, user)


# ---------------------------------------------------------------------------
# Upload submission (POST) – validation
# ---------------------------------------------------------------------------


async def test_upload_rejects_non_gpx_extension(db, user):
    """A file with a non-.gpx extension is rejected with 422."""
    await _add_bike(db, user)
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            resp = await c.post(
                "/rides/upload",
                files={"file": ("track.txt", b"content", "text/plain")},
            )
        assert resp.status_code == 422
    finally:
        await _cleanup(db, user)


async def test_upload_rejects_oversized_file(db, user):
    """A file exceeding 50 MB is rejected with 413."""
    await _add_bike(db, user)
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    # Build a minimal-but-over-limit payload.
    over_limit = b"<gpx>" + b"x" * (51 * 1024 * 1024)
    try:
        async with _client() as c:
            resp = await c.post(
                "/rides/upload",
                files={"file": ("track.gpx", over_limit, "application/gpx+xml")},
            )
        assert resp.status_code == 413
    finally:
        await _cleanup(db, user)


async def test_upload_rejects_file_without_gpx_magic_bytes(db, user):
    """A .gpx file whose content has no <gpx element is rejected with 422."""
    await _add_bike(db, user)
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            resp = await c.post(
                "/rides/upload",
                files={"file": ("track.gpx", b"this is not xml at all", "application/gpx+xml")},
            )
        assert resp.status_code == 422
    finally:
        await _cleanup(db, user)


async def test_upload_rejects_when_no_active_bike(db, user):
    """Upload is blocked with 400 when the user has no active bikes."""
    # User is injected via override; bike query returns nothing → 400.
    app.dependency_overrides[require_login] = lambda: user
    try:
        gpx = FIXTURE_GPX.read_bytes()
        async with _client() as c:
            resp = await c.post(
                "/rides/upload",
                files={"file": ("track.gpx", gpx, "application/gpx+xml")},
            )
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.clear()
        await global_engine.dispose()


async def test_upload_requires_login():
    """Upload page redirects unauthenticated users to /login."""
    async with _client() as c:
        resp = await c.get("/rides/upload", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


# ---------------------------------------------------------------------------
# Upload submission (POST) – happy path
# ---------------------------------------------------------------------------


async def test_upload_valid_gpx_creates_ride_and_redirects(db, user):
    """A valid GPX upload creates a Ride row and redirects to the processing page."""
    await _add_bike(db, user)
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    gpx = FIXTURE_GPX.read_bytes()
    try:
        # Patch process_ride so it's a no-op; the upload route test only cares
        # about ride creation and the redirect, not the full processing pipeline.
        with patch("app.routers.rides.process_ride", new=AsyncMock()):
            async with _client() as c:
                resp = await c.post(
                    "/rides/upload",
                    files={"file": ("track.gpx", gpx, "application/gpx+xml")},
                    follow_redirects=False,
                )
        assert resp.status_code == 303
        loc = resp.headers["location"]
        assert "/processing" in loc

        ride_id = uuid.UUID(loc.split("/rides/")[1].split("/")[0])
        db.expire_all()
        ride = await db.get(Ride, ride_id)
        assert ride is not None
        assert ride.user_id == user.id
        assert ride.processing_status == STATUS_PROCESSING
        assert ride.visibility == VISIBILITY_PRIVATE
    finally:
        await _cleanup(db, user)


# ---------------------------------------------------------------------------
# Review submission
# ---------------------------------------------------------------------------


async def test_review_submit_publishes_ride(db, user):
    """POSTing the review form marks the ride published and sets metadata."""
    ride = Ride(user_id=user.id, processing_status=STATUS_DONE, visibility=VISIBILITY_PRIVATE)
    db.add(ride)
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            resp = await c.post(
                f"/rides/{ride.id}/review",
                data={
                    "title": "Epic twisty run",
                    "description_md": "Best roads ever",
                    "visibility": "public",
                    "road_tags": "Twisties",
                    "mood_tags": "Spirited",
                },
                follow_redirects=False,
            )
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/rides/{ride.id}"
        db.expire_all()
        updated = await db.get(Ride, ride.id)
        assert updated.published is True
        assert updated.title == "Epic twisty run"
        assert updated.visibility == "public"
        assert "Twisties" in updated.road_tags
        assert "Spirited" in updated.mood_tags
    finally:
        await _cleanup(db, user)


async def test_review_rejects_invalid_visibility_falls_back_to_private(db, user):
    """An invalid visibility value in the review form is silently coerced to private."""
    ride = Ride(user_id=user.id, processing_status=STATUS_DONE, visibility=VISIBILITY_PRIVATE)
    db.add(ride)
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            await c.post(
                f"/rides/{ride.id}/review",
                data={"title": "Test", "visibility": "injected_value"},
                follow_redirects=False,
            )
        db.expire_all()
        updated = await db.get(Ride, ride.id)
        assert updated.visibility == VISIBILITY_PRIVATE
    finally:
        await _cleanup(db, user)


async def test_review_non_owner_gets_404(db, user):
    """A user cannot review another user's ride."""
    other = User(email=f"{uuid.uuid4().hex}@t.dev", display_name="Other")
    db.add(other)
    ride = Ride(user_id=other.id, processing_status=STATUS_DONE)
    db.add(ride)
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            resp = await c.post(
                f"/rides/{ride.id}/review",
                data={"title": "Hack"},
                follow_redirects=False,
            )
        assert resp.status_code == 404
    finally:
        # Clean up both users (cascade deletes their rides).
        await db.execute(delete(User).where(User.id.in_([user.id, other.id])))
        await db.commit()
        app.dependency_overrides.clear()
        await global_engine.dispose()


# ---------------------------------------------------------------------------
# Edit submission
# ---------------------------------------------------------------------------


async def test_edit_submit_updates_title_and_visibility(db, user):
    """POSTing the edit form updates the ride's title, description, and visibility."""
    ride = Ride(
        user_id=user.id,
        processing_status=STATUS_DONE,
        published=True,
        title="Old title",
        visibility=VISIBILITY_PRIVATE,
    )
    db.add(ride)
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            resp = await c.post(
                f"/rides/{ride.id}/edit",
                data={
                    "title": "Updated title",
                    "description_md": "Now with description",
                    "visibility": "friends",
                },
                follow_redirects=False,
            )
        assert resp.status_code == 303
        db.expire_all()
        updated = await db.get(Ride, ride.id)
        assert updated.title == "Updated title"
        assert updated.description_md == "Now with description"
        assert updated.visibility == "friends"
    finally:
        await _cleanup(db, user)


async def test_edit_invalid_road_tag_is_ignored(db, user):
    """Unknown road tags submitted via edit form are silently dropped."""
    ride = Ride(user_id=user.id, processing_status=STATUS_DONE, published=True)
    db.add(ride)
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            await c.post(
                f"/rides/{ride.id}/edit",
                data={"title": "Test", "road_tags": "InvalidTagXYZ"},
                follow_redirects=False,
            )
        db.expire_all()
        updated = await db.get(Ride, ride.id)
        assert updated.road_tags == []
    finally:
        await _cleanup(db, user)


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


async def test_delete_ride_removes_row_and_redirects(db, user):
    """DELETE removes the ride and redirects to /rides."""
    ride = Ride(user_id=user.id, processing_status=STATUS_DONE)
    db.add(ride)
    await db.commit()
    ride_id = ride.id
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            resp = await c.post(f"/rides/{ride_id}/delete", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/rides"
        db.expire_all()
        assert await db.get(Ride, ride_id) is None
    finally:
        await _cleanup(db, user)


async def test_delete_ride_enforces_ownership(db, user):
    """A user cannot delete another user's ride (returns 404)."""
    other = User(email=f"{uuid.uuid4().hex}@t.dev", display_name="Other")
    db.add(other)
    ride = Ride(user_id=other.id, processing_status=STATUS_DONE)
    db.add(ride)
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            resp = await c.post(f"/rides/{ride.id}/delete", follow_redirects=False)
        assert resp.status_code == 404
        db.expire_all()
        # Ride must still exist.
        assert await db.get(Ride, ride.id) is not None
    finally:
        await db.execute(delete(User).where(User.id.in_([user.id, other.id])))
        await db.commit()
        app.dependency_overrides.clear()
        await global_engine.dispose()
