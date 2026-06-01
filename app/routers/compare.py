import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import LoggedInUser
from app.db import get_db
from app.models.ride import STATUS_DONE, STATUS_DUPLICATE, VISIBILITY_FRIENDS, VISIBILITY_PUBLIC, Ride
from app.routers.rides import _viewable_ride
from app.services import social
from app.templating import templates

router = APIRouter()
DB = Annotated[AsyncSession, Depends(get_db)]


def _parse(v: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(v)
    except (ValueError, TypeError):
        return None


@router.get("/compare", response_class=HTMLResponse)
async def compare(request: Request, user: LoggedInUser, db: DB, a: str = "", b: str = ""):
    # Picker options: viewer's own done rides + friends' visible done rides.
    fids = await social.friend_ids(db, user.id)
    done = (STATUS_DONE, STATUS_DUPLICATE)
    cond = [Ride.user_id == user.id]
    if fids:
        cond.append(
            and_(
                Ride.user_id.in_(fids),
                Ride.published.is_(True),
                or_(Ride.visibility == VISIBILITY_PUBLIC, Ride.visibility == VISIBILITY_FRIENDS),
            )
        )
    options = (
        await db.execute(
            select(Ride)
            .where(or_(*cond), Ride.processing_status.in_(done))
            .order_by(Ride.start_time.desc().nullslast())
            .limit(100)
        )
    ).scalars().all()

    ride_a = ride_b = None
    aid, bid = _parse(a), _parse(b)
    if aid:
        try:
            ride_a = await _viewable_ride(db, user.id, aid)
        except Exception:
            ride_a = None
    if bid:
        try:
            ride_b = await _viewable_ride(db, user.id, bid)
        except Exception:
            ride_b = None

    return templates.TemplateResponse(
        request,
        "compare.html",
        {"title": "Compare rides", "options": options, "ride_a": ride_a, "ride_b": ride_b},
    )
