import hmac
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.auth.deps import SESSION_USER_KEY, LoggedInUser
from app.db import get_db
from app.models.ride import Ride
from app.models.user import DISCOVER_CHOICES, DISCOVER_EVERYONE, User
from app.services import storage
from app.services import garage as garage_svc
from app.services import stats as stats_svc
from app.templating import templates

router = APIRouter()

ACCOUNT_DELETE_CSRF_KEY = "account_delete_csrf_token"


def _account_delete_csrf_token(request: Request) -> str:
    token = request.session.get(ACCOUNT_DELETE_CSRF_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[ACCOUNT_DELETE_CSRF_KEY] = token
    return token


def _valid_account_delete_csrf(request: Request, submitted: str) -> bool:
    token = request.session.get(ACCOUNT_DELETE_CSRF_KEY)
    return bool(
        token
        and submitted
        and hmac.compare_digest(str(token), submitted)
    )


@router.get("/onboarding", response_class=HTMLResponse)
async def onboarding_page(request: Request, user: LoggedInUser):
    return templates.TemplateResponse(
        request,
        "profile_setup.html",
        {
            "title": "Set up your profile",
            "u": user,
            "account_delete_csrf_token": _account_delete_csrf_token(request),
        },
    )


@router.post("/onboarding")
async def onboarding_submit(
    request: Request,
    user: LoggedInUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    display_name: Annotated[str, Form()],
    home_region: Annotated[str, Form()] = "",
    avatar_url: Annotated[str, Form()] = "",
    unit_distance: Annotated[str, Form()] = "km",
    unit_temp: Annotated[str, Form()] = "C",
    discoverability: Annotated[str, Form()] = "everyone",
    email_on_friend_request: Annotated[bool, Form()] = False,
    email_on_friend_accept: Annotated[bool, Form()] = False,
    email_on_like: Annotated[bool, Form()] = False,
    email_on_comment: Annotated[bool, Form()] = False,
):
    user.display_name = display_name.strip()
    user.home_region = home_region.strip() or None
    if avatar_url.strip():
        user.avatar_url = avatar_url.strip()
    user.unit_distance = "mi" if unit_distance == "mi" else "km"
    user.unit_temp = "F" if unit_temp == "F" else "C"
    user.discoverability = (
        discoverability if discoverability in DISCOVER_CHOICES else DISCOVER_EVERYONE
    )
    user.email_on_friend_request = email_on_friend_request
    user.email_on_friend_accept = email_on_friend_accept
    user.email_on_like = email_on_like
    user.email_on_comment = email_on_comment
    db.add(user)
    return RedirectResponse("/me", status_code=303)


@router.post("/account/delete")
async def delete_account(
    request: Request,
    user: LoggedInUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    confirm: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    if not _valid_account_delete_csrf(request, csrf_token):
        return RedirectResponse("/onboarding?confirm=bad", status_code=303)

    # Require the literal word "confirm" (server-side guard, not just the UI).
    if confirm.strip().lower() != "confirm":
        return RedirectResponse("/onboarding?confirm=bad", status_code=303)

    # Collect blob keys before the DB cascade so we can purge files too.
    keys: list[str] = []
    rides = (await db.execute(select(Ride).where(Ride.user_id == user.id))).scalars().all()
    for r in rides:
        if r.gpx_blob_key:
            keys.append(r.gpx_blob_key)
        for p in r.photos:
            keys.append(p.blob_key)

    # Re-fetch in this session so delete works regardless of where `user` came from.
    target = await db.get(User, user.id)
    await db.delete(target)  # FK ondelete=CASCADE removes bikes/rides/social/etc.
    await db.flush()
    for k in keys:
        storage.delete(k)

    request.session.pop(SESSION_USER_KEY, None)
    request.session.pop(ACCOUNT_DELETE_CSRF_KEY, None)
    return RedirectResponse("/", status_code=303)


@router.get("/me", response_class=HTMLResponse)
async def my_profile(
    request: Request,
    user: LoggedInUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = 1,
):
    page = max(1, page)
    lifetime = await stats_svc.lifetime_stats(db, user.id)
    per_bike = await stats_svc.per_bike_stats(db, user.id)
    bikes = await garage_svc.list_bikes(db, user.id)
    rides, has_next = await stats_svc.recent_rides(db, user.id, page=page)
    return templates.TemplateResponse(
        request,
        "profile.html",
        {
            "title": user.display_name or "Profile",
            "u": user,
            "lifetime": lifetime,
            "per_bike": per_bike,
            "bikes": bikes,
            "rides": rides,
            "page": page,
            "has_next": has_next,
        },
    )
