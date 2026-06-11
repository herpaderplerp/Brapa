import uuid

import pytest

from app.models.user import DISCOVER_EVERYONE, DISCOVER_FOF, DISCOVER_PRIVATE, User
from app.services import social


async def _user(db, disc=DISCOVER_EVERYONE) -> User:
    u = User(email=f"{uuid.uuid4().hex}@t.dev", display_name="U", discoverability=disc)
    db.add(u)
    await db.flush()
    return u


async def _befriend(db, a, b):
    await social.send_request(db, a.id, b.id)
    await social.send_request(db, b.id, a.id)


@pytest.mark.asyncio
async def test_everyone_discoverable(db, user):
    t = await _user(db, DISCOVER_EVERYONE)
    assert await social.can_discover(db, user.id, t) is True


@pytest.mark.asyncio
async def test_private_hidden_except_friends(db, user):
    t = await _user(db, DISCOVER_PRIVATE)
    assert await social.can_discover(db, user.id, t) is False
    await _befriend(db, user, t)
    assert await social.can_discover(db, user.id, t) is True


@pytest.mark.asyncio
async def test_fof_requires_mutual_friend(db, user):
    t = await _user(db, DISCOVER_FOF)
    # No connection yet.
    assert await social.can_discover(db, user.id, t) is False
    # Add a shared mutual friend M (friend of both).
    m = await _user(db, DISCOVER_EVERYONE)
    await _befriend(db, user, m)
    await _befriend(db, t, m)
    assert await social.can_discover(db, user.id, t) is True


@pytest.mark.asyncio
async def test_self_always_discoverable(db, user):
    user.discoverability = DISCOVER_PRIVATE
    await db.flush()
    assert await social.can_discover(db, user.id, user) is True


@pytest.mark.asyncio
async def test_private_visible_for_pending_incoming_requests_only(db, user):
    requester = await _user(db, DISCOVER_PRIVATE)
    addressee = user
    addressee.discoverability = DISCOVER_PRIVATE
    await db.flush()
    await social.send_request(db, requester.id, addressee.id)

    assert await social.can_discover(db, addressee.id, requester) is True
    assert await social.can_discover(db, requester.id, addressee) is False
