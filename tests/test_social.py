import uuid

import pytest

from app.models.ride import (
    STATUS_DONE,
    VISIBILITY_FRIENDS,
    VISIBILITY_PRIVATE,
    VISIBILITY_PUBLIC,
    Ride,
)
from app.models.user import User
from app.services import feed as feed_svc
from app.services import social


async def _user(db, name="U") -> User:
    u = User(email=f"{uuid.uuid4().hex}@t.dev", display_name=name)
    db.add(u)
    await db.flush()
    return u


async def _ride(db, owner, vis, *, published=True, road=None) -> Ride:
    r = Ride(
        user_id=owner.id, visibility=vis, published=published,
        processing_status=STATUS_DONE, title="r", distance_m=1000,
        road_tags=([road] if road else []),
    )
    db.add(r)
    await db.flush()
    return r


@pytest.mark.asyncio
async def test_mutual_request_accept(db, user):
    other = await _user(db, "Other")
    await social.send_request(db, user.id, other.id)
    assert await social.are_friends(db, user.id, other.id) is False
    # reverse request → auto-accept
    await social.send_request(db, other.id, user.id)
    assert await social.are_friends(db, user.id, other.id) is True
    assert other.id in await social.friend_ids(db, user.id)


@pytest.mark.asyncio
async def test_can_view_ride_visibility(db, user):
    owner = await _user(db, "Owner")
    pub = await _ride(db, owner, VISIBILITY_PUBLIC)
    fr = await _ride(db, owner, VISIBILITY_FRIENDS)
    priv = await _ride(db, owner, VISIBILITY_PRIVATE)

    # stranger
    assert await social.can_view_ride(db, user.id, pub) is True
    assert await social.can_view_ride(db, user.id, fr) is False
    assert await social.can_view_ride(db, user.id, priv) is False
    # owner sees own private
    assert await social.can_view_ride(db, owner.id, priv) is True
    # become friends → friends-only visible
    await social.send_request(db, user.id, owner.id)
    await social.send_request(db, owner.id, user.id)
    assert await social.can_view_ride(db, user.id, fr) is True
    assert await social.can_view_ride(db, user.id, priv) is False


@pytest.mark.asyncio
async def test_feed_shows_friend_rides_with_filter(db, user):
    friend = await _user(db, "Friend")
    stranger = await _user(db, "Stranger")
    await social.send_request(db, user.id, friend.id)
    await social.send_request(db, friend.id, user.id)

    await _ride(db, friend, VISIBILITY_PUBLIC, road="Twisties")
    await _ride(db, friend, VISIBILITY_FRIENDS, road="Highway")
    await _ride(db, stranger, VISIBILITY_PUBLIC)  # not a friend
    await db.flush()

    cards, _ = await feed_svc.feed(db, user.id)
    assert len(cards) == 2  # both friend rides, none from stranger

    only_tw, _ = await feed_svc.feed(db, user.id, road_tag="Twisties")
    assert len(only_tw) == 1


@pytest.mark.asyncio
async def test_like_toggle_and_count(db, user):
    owner = await _user(db, "O")
    r = await _ride(db, owner, VISIBILITY_PUBLIC)
    assert await feed_svc.toggle_like(db, r.id, user.id) is True
    await db.flush()
    assert await feed_svc.like_count(db, r.id) == 1
    assert await feed_svc.toggle_like(db, r.id, user.id) is False
    await db.flush()
    assert await feed_svc.like_count(db, r.id) == 0


@pytest.mark.asyncio
async def test_comments_one_level_deep(db, user):
    owner = await _user(db, "O")
    r = await _ride(db, owner, VISIBILITY_PUBLIC)
    top = await feed_svc.add_comment(db, r.id, user.id, "top")
    reply = await feed_svc.add_comment(db, r.id, user.id, "reply", parent_id=top.id)
    # reply-to-reply must collapse to top-level (parent_id dropped)
    deep = await feed_svc.add_comment(db, r.id, user.id, "deep", parent_id=reply.id)
    await db.flush()

    tree = await feed_svc.comments_tree(db, r.id)
    assert len(tree) == 2  # 'top' (with a reply) and 'deep' (collapsed to root)
    top_node = next(n for n in tree if n.comment.body == "top")
    assert len(top_node.replies) == 1
    assert deep.parent_id is None
