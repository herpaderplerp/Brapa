import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import LoggedInUser
from app.db import get_db
from app.models.user import User
from app.services import feed as feed_svc
from app.services import privacy as privacy_svc
from app.services import social
from app.templating import templates

router = APIRouter()
DB = Annotated[AsyncSession, Depends(get_db)]

ROAD_TAGS = ["Twisties", "Highway", "Mixed", "Gravel", "Track Day"]


@router.get("/feed", response_class=HTMLResponse)
async def feed_page(
    request: Request,
    user: LoggedInUser,
    db: DB,
    page: int = 1,
    friend: str = "",
    road: str = "",
):
    page = max(1, page)
    friend_id = None
    if friend:
        try:
            friend_id = uuid.UUID(friend)
        except ValueError:
            friend_id = None
    road_tag = road if road in ROAD_TAGS else None

    raw, has_next = await feed_svc.feed(
        db, user.id, page=page, friend_id=friend_id, road_tag=road_tag
    )

    author_ids = {a for (_, a, _, _, _) in raw}
    authors = {}
    if author_ids:
        rows = (await db.execute(select(User).where(User.id.in_(author_ids)))).scalars().all()
        authors = {u.id: u for u in rows}

    # Feed authors are always other users (friends), so clip every thumbnail
    # against that author's zones.
    zmap = await privacy_svc.zones_by_user(db, author_ids)
    cards = []
    for ride, author_id, lc, cc, liked in raw:
        thumb = await feed_svc.track_thumb(db, ride.id, zones=zmap.get(author_id, []))
        cards.append(
            {
                "ride": ride,
                "author": authors.get(author_id),
                "likes": lc,
                "comments": cc,
                "liked": liked,
                "thumb": thumb,
            }
        )

    friends = await social.list_friends(db, user.id)
    return templates.TemplateResponse(
        request,
        "feed.html",
        {
            "title": "Feed",
            "cards": cards,
            "friends": friends,
            "road_tags": ROAD_TAGS,
            "sel_friend": friend,
            "sel_road": road,
            "page": page,
            "has_next": has_next,
        },
    )
