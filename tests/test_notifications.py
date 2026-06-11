import re
import uuid

import httpx
import pytest

from app.auth.deps import require_login
from app.db import engine as global_engine
from app.main import app
from app.models.notify import Notification
from app.models.ride import STATUS_DONE, VISIBILITY_PUBLIC, Ride
from app.models.user import User
from app.services import email as email_svc
from app.services import feed as feed_svc
from app.services import notify as notify_svc
from app.services import social


async def _user(db, name="U", **kw) -> User:
    u = User(email=f"{uuid.uuid4().hex}@t.dev", display_name=name, **kw)
    db.add(u)
    await db.flush()
    return u


async def _ride(db, owner) -> Ride:
    r = Ride(user_id=owner.id, visibility=VISIBILITY_PUBLIC, published=True,
             processing_status=STATUS_DONE, title="r")
    db.add(r)
    await db.flush()
    return r


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://x")


async def _notifications_csrf_token(client):
    r = await client.get("/notifications")
    assert r.status_code == 200
    match = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
    assert match is not None
    return match.group(1)


@pytest.mark.asyncio
async def test_no_self_notification(db, user):
    n = await notify_svc.create(db, recipient_id=user.id, type="like", actor_id=user.id)
    assert n is None
    assert await notify_svc.unread_count(db, user.id) == 0


@pytest.mark.asyncio
async def test_unread_and_mark_read(db, user):
    actor = await _user(db, "Actor")
    await notify_svc.create(db, recipient_id=user.id, type="friend_request", actor_id=actor.id)
    await notify_svc.create(db, recipient_id=user.id, type="friend_accept", actor_id=actor.id)
    await db.flush()
    assert await notify_svc.unread_count(db, user.id) == 2
    await notify_svc.mark_all_read(db, user.id)
    assert await notify_svc.unread_count(db, user.id) == 0


@pytest.mark.asyncio
async def test_like_and_comment_emit_to_owner(db, user):
    owner = await _user(db, "Owner")
    ride = await _ride(db, owner)
    # user likes owner's ride
    await feed_svc.toggle_like(db, ride.id, user.id)
    await db.flush()
    assert await notify_svc.unread_count(db, owner.id) == 1
    # user comments
    await feed_svc.add_comment(db, ride.id, user.id, "nice")
    await db.flush()
    assert await notify_svc.unread_count(db, owner.id) == 2
    # owner liking own ride → no self-notify
    await feed_svc.toggle_like(db, ride.id, owner.id)
    await db.flush()
    assert await notify_svc.unread_count(db, owner.id) == 2


@pytest.mark.asyncio
async def test_friend_request_and_accept_notify(db, user):
    other = await _user(db, "Other")
    await social.send_request(db, user.id, other.id)
    await db.flush()
    assert await notify_svc.unread_count(db, other.id) == 1  # friend_request
    # other accepts (reverse request auto-accepts) → notify original requester
    await social.send_request(db, other.id, user.id)
    await db.flush()
    assert await notify_svc.unread_count(db, user.id) == 1  # friend_accept


def test_email_pref_gating(monkeypatch):
    sent = []
    monkeypatch.setattr(email_svc, "send", lambda to, subject, body: sent.append((to, subject)))

    class Rec:
        email = "x@y.com"
        email_on_like = False
        email_on_comment = True

    assert email_svc.maybe_send(Rec(), "like", "s", "b") is False
    assert email_svc.maybe_send(Rec(), "comment", "s", "b") is True
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_notifications_page_get_does_not_mark_read(db, user):
    actor = await _user(db, "Actor")
    await notify_svc.create(db, recipient_id=user.id, type="friend_request", actor_id=actor.id)
    await db.commit()

    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            r = await c.get("/notifications")
        assert r.status_code == 200
        assert await notify_svc.unread_count(db, user.id) == 1
    finally:
        app.dependency_overrides.clear()
        from sqlalchemy import delete

        await db.execute(delete(Notification).where(Notification.user_id == user.id))
        await db.execute(delete(User).where(User.id.in_([user.id, actor.id])))
        await db.commit()
        await global_engine.dispose()


@pytest.mark.asyncio
async def test_mark_notifications_read_requires_csrf(db, user):
    actor = await _user(db, "Actor")
    await notify_svc.create(db, recipient_id=user.id, type="friend_request", actor_id=actor.id)
    await db.commit()

    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            r = await c.post("/notifications/read", follow_redirects=False)
        assert r.status_code == 403
        assert await notify_svc.unread_count(db, user.id) == 1
    finally:
        app.dependency_overrides.clear()
        from sqlalchemy import delete

        await db.execute(delete(Notification).where(Notification.user_id == user.id))
        await db.execute(delete(User).where(User.id.in_([user.id, actor.id])))
        await db.commit()
        await global_engine.dispose()


@pytest.mark.asyncio
async def test_mark_notifications_read_with_csrf(db, user):
    actor = await _user(db, "Actor")
    await notify_svc.create(db, recipient_id=user.id, type="friend_request", actor_id=actor.id)
    await db.commit()

    app.dependency_overrides[require_login] = lambda: user
    try:
        async with _client() as c:
            csrf_token = await _notifications_csrf_token(c)
            r = await c.post(
                "/notifications/read",
                data={"csrf_token": csrf_token},
                follow_redirects=False,
            )
        assert r.status_code == 303
        assert r.headers["location"] == "/notifications"
        assert await notify_svc.unread_count(db, user.id) == 0
    finally:
        app.dependency_overrides.clear()
        from sqlalchemy import delete

        await db.execute(delete(Notification).where(Notification.user_id == user.id))
        await db.execute(delete(User).where(User.id.in_([user.id, actor.id])))
        await db.commit()
        await global_engine.dispose()
