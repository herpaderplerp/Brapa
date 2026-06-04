import uuid

import httpx
import pytest
from sqlalchemy import delete

from app.auth.deps import require_login
from app.db import engine as global_engine
from app.main import app
from app.models.ride import VISIBILITY_PRIVATE, VISIBILITY_PUBLIC, STATUS_DONE, Ride, RidePoint
from app.models.section import RideSection
from app.models.user import User
from app.services import sections as sections_svc


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://x")


async def _ride_with_points(db, owner, n=10, visibility=VISIBILITY_PUBLIC):
    ride = Ride(
        user_id=owner.id, processing_status=STATUS_DONE, published=True, visibility=visibility
    )
    db.add(ride)
    await db.flush()
    for i in range(n):
        db.add(RidePoint(ride_id=ride.id, seq=i, lat=37.0 + i * 0.001, lon=-122.0, t=float(i)))
    await db.commit()
    return ride


async def _cleanup(db, ride_id, *user_ids):
    app.dependency_overrides.clear()
    await db.execute(delete(RideSection).where(RideSection.ride_id == ride_id))
    await db.execute(delete(RidePoint).where(RidePoint.ride_id == ride_id))
    await db.execute(delete(Ride).where(Ride.id == ride_id))
    for uid in user_ids:
        await db.execute(delete(User).where(User.id == uid))
    await db.commit()
    await global_engine.dispose()


# --- service ---------------------------------------------------------------

async def test_create_orders_and_clamps(db, user):
    ride = await _ride_with_points(db, user, n=10)
    try:
        # end before start, end out of range -> ordered + clamped to [0, 9].
        s = await sections_svc.create(db, ride.id, "  Twisties  ", start_seq=8, end_seq=99)
        assert (s.start_seq, s.end_seq) == (8, 9)
        assert s.name == "Twisties"  # trimmed

        s2 = await sections_svc.create(db, ride.id, "Reverse", start_seq=6, end_seq=2)
        assert (s2.start_seq, s2.end_seq) == (2, 6)
    finally:
        await _cleanup(db, ride.id, user.id)


async def test_create_rejects_blank_name_and_zero_length(db, user):
    ride = await _ride_with_points(db, user, n=5)
    try:
        with pytest.raises(sections_svc.SectionError):
            await sections_svc.create(db, ride.id, "   ", start_seq=0, end_seq=3)
        with pytest.raises(sections_svc.SectionError):
            await sections_svc.create(db, ride.id, "Point", start_seq=2, end_seq=2)
    finally:
        await _cleanup(db, ride.id, user.id)


async def test_slice_points_returns_inclusive_range(db, user):
    ride = await _ride_with_points(db, user, n=10)
    try:
        s = await sections_svc.create(db, ride.id, "Mid", start_seq=3, end_seq=6)
        rows = await sections_svc.slice_points(db, s)
        assert [p.seq for p in rows] == [3, 4, 5, 6]
    finally:
        await _cleanup(db, ride.id, user.id)


def test_section_stats_derives_from_slice():
    rid = uuid.uuid4()
    pts = [
        RidePoint(ride_id=rid, seq=0, lat=37.000, lon=-122.0, elev=100.0, speed=10.0, t=0.0),
        RidePoint(ride_id=rid, seq=1, lat=37.001, lon=-122.0, elev=110.0, speed=20.0, t=10.0),
        RidePoint(ride_id=rid, seq=2, lat=37.002, lon=-122.0, elev=105.0, speed=30.0, t=20.0),
    ]
    s = sections_svc.section_stats(pts)
    assert s["elev_gain"] == pytest.approx(10.0)  # +10 then -5 (descents ignored)
    assert s["duration_s"] == pytest.approx(20.0)
    assert s["max_speed"] == 30.0
    assert s["distance_m"] > 0
    assert s["avg_speed"] == pytest.approx(s["distance_m"] / 20.0)


def test_section_stats_handles_empty_slice():
    s = sections_svc.section_stats([])
    assert s == {
        "distance_m": 0.0, "elev_gain": 0.0, "duration_s": 0.0,
        "avg_speed": 0.0, "max_speed": None,
    }


# --- routes ----------------------------------------------------------------

async def test_owner_creates_section_via_route(db, user):
    ride = await _ride_with_points(db, user, n=10)
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            r = await c.post(
                f"/rides/{ride.id}/sections",
                data={"name": "Canyon run", "start_seq": "2", "end_seq": "7"},
            )
        assert r.status_code == 200
        assert "Canyon run" in r.text
        db.expunge_all()
        rows = await sections_svc.list_for_ride(db, ride.id)
        assert len(rows) == 1 and rows[0].name == "Canyon run"
    finally:
        await _cleanup(db, ride.id, user.id)


async def test_create_bad_range_is_422(db, user):
    ride = await _ride_with_points(db, user, n=5)
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            r = await c.post(
                f"/rides/{ride.id}/sections",
                data={"name": "x", "start_seq": "2", "end_seq": "2"},
            )
        assert r.status_code == 422
    finally:
        await _cleanup(db, ride.id, user.id)


async def test_non_owner_cannot_create(db, user):
    owner = User(email=f"{uuid.uuid4().hex}@t.dev", display_name="Owner")
    db.add(owner)
    await db.flush()
    ride = await _ride_with_points(db, owner, n=10)
    app.dependency_overrides[require_login] = lambda: user  # not the owner
    try:
        async with _client() as c:
            r = await c.post(
                f"/rides/{ride.id}/sections",
                data={"name": "nope", "start_seq": "1", "end_seq": "3"},
            )
        assert r.status_code == 404
    finally:
        await _cleanup(db, ride.id, owner.id)


async def test_section_points_gated_on_private_ride(db, user):
    owner = User(email=f"{uuid.uuid4().hex}@t.dev", display_name="Owner")
    db.add(owner)
    await db.flush()
    ride = await _ride_with_points(db, owner, n=10, visibility=VISIBILITY_PRIVATE)
    section = await sections_svc.create(db, ride.id, "Secret", start_seq=1, end_seq=4)
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user  # stranger
    try:
        async with _client() as c:
            page = await c.get(f"/rides/{ride.id}/sections/{section.id}")
            pts = await c.get(f"/rides/{ride.id}/sections/{section.id}/points.json")
        assert page.status_code == 404  # private ride never leaks
        assert pts.status_code == 404
    finally:
        await _cleanup(db, ride.id, owner.id)


async def test_public_section_points_visible_to_stranger(db, user):
    owner = User(email=f"{uuid.uuid4().hex}@t.dev", display_name="Owner")
    db.add(owner)
    await db.flush()
    ride = await _ride_with_points(db, owner, n=10, visibility=VISIBILITY_PUBLIC)
    section = await sections_svc.create(db, ride.id, "Open", start_seq=2, end_seq=5)
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            pts = await c.get(f"/rides/{ride.id}/sections/{section.id}/points.json")
        assert pts.status_code == 200
        assert len(pts.json()["points"]) == 4  # seq 2..5 inclusive
    finally:
        await _cleanup(db, ride.id, owner.id)


async def test_section_detail_page_shows_stats(db, user):
    ride = await _ride_with_points(db, user, n=10)
    section = await sections_svc.create(db, ride.id, "Stats run", start_seq=1, end_seq=6)
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            page = await c.get(f"/rides/{ride.id}/sections/{section.id}")
        assert page.status_code == 200
        assert "Stats run" in page.text
        assert "Distance" in page.text and "Elev gain" in page.text
    finally:
        await _cleanup(db, ride.id, user.id)


async def test_owner_deletes_section(db, user):
    ride = await _ride_with_points(db, user, n=10)
    section = await sections_svc.create(db, ride.id, "Bye", start_seq=1, end_seq=4)
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            r = await c.post(
                f"/rides/{ride.id}/sections/{section.id}/delete", follow_redirects=False
            )
        assert r.status_code == 303
        db.expunge_all()
        assert await db.get(RideSection, section.id) is None
    finally:
        await _cleanup(db, ride.id, user.id)


# --- cross-ride manage page ------------------------------------------------

async def test_manage_page_lists_only_own_sections(db, user):
    other = User(email=f"{uuid.uuid4().hex}@t.dev", display_name="Other")
    db.add(other)
    await db.flush()
    mine = await _ride_with_points(db, user, n=10)
    theirs = await _ride_with_points(db, other, n=10)
    await sections_svc.create(db, mine.id, "Mine A", start_seq=1, end_seq=4)
    await sections_svc.create(db, theirs.id, "Theirs B", start_seq=1, end_seq=4)
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            page = await c.get("/sections")
        assert page.status_code == 200
        assert "Mine A" in page.text
        assert "Theirs B" not in page.text  # other user's section never appears
    finally:
        await _cleanup(db, mine.id)
        await _cleanup(db, theirs.id, user.id, other.id)


async def test_rename_and_delete_via_manage_routes(db, user):
    ride = await _ride_with_points(db, user, n=10)
    section = await sections_svc.create(db, ride.id, "Old name", start_seq=1, end_seq=4)
    await db.commit()
    sid = section.id
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            r = await c.post(f"/sections/{sid}/rename", data={"name": "New name"})
            assert r.status_code == 200
            assert "New name" in r.text and "Old name" not in r.text
            d = await c.post(f"/sections/{sid}/delete")
            assert d.status_code == 200
        db.expunge_all()
        assert await db.get(RideSection, sid) is None
    finally:
        await _cleanup(db, ride.id, user.id)


async def test_rename_blank_is_422(db, user):
    ride = await _ride_with_points(db, user, n=10)
    section = await sections_svc.create(db, ride.id, "Keep", start_seq=1, end_seq=4)
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            r = await c.post(f"/sections/{section.id}/rename", data={"name": "   "})
        assert r.status_code == 422
    finally:
        await _cleanup(db, ride.id, user.id)


async def test_manage_routes_reject_non_owner(db, user):
    owner = User(email=f"{uuid.uuid4().hex}@t.dev", display_name="Owner")
    db.add(owner)
    await db.flush()
    ride = await _ride_with_points(db, owner, n=10)
    section = await sections_svc.create(db, ride.id, "Owned", start_seq=1, end_seq=4)
    await db.commit()
    app.dependency_overrides[require_login] = lambda: user  # stranger
    try:
        async with _client() as c:
            r = await c.post(f"/sections/{section.id}/rename", data={"name": "Hijack"})
            d = await c.post(f"/sections/{section.id}/delete")
        assert r.status_code == 404 and d.status_code == 404
    finally:
        await _cleanup(db, ride.id, owner.id)


async def test_sections_cascade_on_ride_delete(db, user):
    ride = await _ride_with_points(db, user, n=10)
    section = await sections_svc.create(db, ride.id, "Doomed", start_seq=1, end_seq=4)
    await db.commit()
    section_id = section.id
    try:
        ride_obj = await db.get(Ride, ride.id)
        await db.delete(ride_obj)
        await db.commit()
        db.expunge_all()
        assert await db.get(RideSection, section_id) is None
    finally:
        await db.execute(delete(User).where(User.id == user.id))
        await db.commit()
        await global_engine.dispose()
