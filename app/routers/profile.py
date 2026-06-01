from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import LoggedInUser
from app.db import get_db
from app.services import garage as garage_svc
from app.services import stats as stats_svc
from app.templating import templates

router = APIRouter()


@router.get("/onboarding", response_class=HTMLResponse)
async def onboarding_page(request: Request, user: LoggedInUser):
    return templates.TemplateResponse(
        request, "profile_setup.html", {"title": "Set up your profile", "u": user}
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
):
    user.display_name = display_name.strip()
    user.home_region = home_region.strip() or None
    if avatar_url.strip():
        user.avatar_url = avatar_url.strip()
    user.unit_distance = "mi" if unit_distance == "mi" else "km"
    user.unit_temp = "F" if unit_temp == "F" else "C"
    db.add(user)
    return RedirectResponse("/me", status_code=303)


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
