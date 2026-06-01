import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import LoggedInUser
from app.db import get_db
from app.models.ride import Ride
from app.models.social import FRIEND_ACCEPTED, Friendship
from app.models.user import User
from app.services import social
from app.templating import templates

router = APIRouter()
DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("/friends", response_class=HTMLResponse)
async def friends_page(request: Request, user: LoggedInUser, db: DB):
    friends = await social.list_friends(db, user.id)
    incoming = await social.pending_incoming(db, user.id)
    outgoing = await social.pending_outgoing(db, user.id)
    return templates.TemplateResponse(
        request,
        "friends.html",
        {"title": "Friends", "friends": friends, "incoming": incoming, "outgoing": outgoing},
    )


@router.post("/friends/request")
async def send_friend_request(
    user: LoggedInUser, db: DB, addressee_id: Annotated[str, Form()]
):
    try:
        aid = uuid.UUID(addressee_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Bad user id")
    if await db.get(User, aid) is None:
        raise HTTPException(status_code=404, detail="User not found")
    await social.send_request(db, user.id, aid)
    return RedirectResponse(f"/users/{aid}", status_code=303)


async def _my_friendship(db: AsyncSession, user_id: uuid.UUID, fid: uuid.UUID) -> Friendship:
    f = await db.get(Friendship, fid)
    if f is None or user_id not in (f.requester_id, f.addressee_id):
        raise HTTPException(status_code=404, detail="Not found")
    return f


@router.post("/friends/{fid}/accept")
async def accept_request(user: LoggedInUser, db: DB, fid: uuid.UUID):
    f = await _my_friendship(db, user.id, fid)
    # Only the addressee can accept.
    if f.addressee_id == user.id:
        await social.accept(db, f)
    return RedirectResponse("/friends", status_code=303)


@router.post("/friends/{fid}/decline")
async def decline_request(user: LoggedInUser, db: DB, fid: uuid.UUID):
    f = await _my_friendship(db, user.id, fid)
    await social.remove(db, f)
    return RedirectResponse("/friends", status_code=303)


@router.post("/friends/{fid}/remove")
async def remove_friend(user: LoggedInUser, db: DB, fid: uuid.UUID):
    f = await _my_friendship(db, user.id, fid)
    await social.remove(db, f)
    return RedirectResponse("/friends", status_code=303)


@router.get("/users", response_class=HTMLResponse)
async def search_users(request: Request, user: LoggedInUser, db: DB, q: str = ""):
    results = []
    if q.strip():
        like = f"%{q.strip()}%"
        candidates = (
            await db.execute(
                select(User)
                .where(User.id != user.id, or_(User.display_name.ilike(like), User.email.ilike(like)))
                .order_by(User.display_name)
                .limit(50)
            )
        ).scalars().all()
        # Respect each candidate's discoverability setting.
        for cand in candidates:
            if await social.can_discover(db, user.id, cand):
                results.append(cand)
            if len(results) >= 25:
                break
    fids = await social.friend_ids(db, user.id)
    return templates.TemplateResponse(
        request, "user_search.html", {"title": "Find riders", "q": q, "results": results, "friend_ids": fids}
    )


@router.get("/users/{uid}", response_class=HTMLResponse)
async def user_profile(request: Request, user: LoggedInUser, db: DB, uid: uuid.UUID):
    if uid == user.id:
        return RedirectResponse("/me", status_code=303)
    target = await db.get(User, uid)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    # Hidden profiles 404 for non-permitted viewers (no enumeration).
    if not await social.can_discover(db, user.id, target):
        raise HTTPException(status_code=404, detail="User not found")

    fids = await social.friend_ids(db, user.id)
    clause = social.visible_rides_clause(user.id, uid, fids)
    rides = (
        await db.execute(
            select(Ride).where(clause).order_by(Ride.start_time.desc().nullslast()).limit(20)
        )
    ).scalars().all()

    friendship = await social.friendship_between(db, user.id, uid)
    rel = "none"
    if friendship:
        if friendship.status == FRIEND_ACCEPTED:
            rel = "friends"
        elif friendship.requester_id == user.id:
            rel = "outgoing"
        else:
            rel = "incoming"
    return templates.TemplateResponse(
        request,
        "user_profile.html",
        {"title": target.display_name or "Rider", "target": target, "rides": rides,
         "rel": rel, "friendship": friendship},
    )
