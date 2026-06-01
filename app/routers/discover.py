from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import LoggedInUser
from app.db import get_db
from app.services import discover as discover_svc
from app.services import geocode
from app.templating import templates

router = APIRouter()
DB = Annotated[AsyncSession, Depends(get_db)]


def _parse_bbox(s: str):
    parts = (s or "").split(",")
    if len(parts) != 4:
        return None
    try:
        min_lon, min_lat, max_lon, max_lat = (float(p) for p in parts)
    except ValueError:
        return None
    return (min_lon, min_lat, max_lon, max_lat)


def _markers(rides):
    return [
        {
            "lat": r.start_lat,
            "lon": r.start_lon,
            "title": r.title or "Ride",
            "url": f"/rides/{r.id}",
        }
        for r in rides
        if r.start_lat is not None and r.start_lon is not None
    ]


@router.get("/discover", response_class=HTMLResponse)
async def discover(request: Request, user: LoggedInUser, db: DB, q: str = "", bbox: str = ""):
    search_bbox = _parse_bbox(bbox)
    center = None
    if search_bbox is None and q.strip():
        hit = await geocode.search(q)
        if hit:
            lat, lon, gbbox = hit
            search_bbox = gbbox
            center = [lat, lon]

    rides = []
    if search_bbox is not None:
        rides = await discover_svc.rides_in_bbox(db, user.id, search_bbox)

    return templates.TemplateResponse(
        request,
        "discover.html",
        {
            "title": "Discover",
            "q": q,
            "rides": rides,
            "markers": _markers(rides),
            "bbox": search_bbox,
            "center": center,
            "searched": search_bbox is not None,
        },
    )


@router.get("/popular", response_class=HTMLResponse)
async def popular(request: Request, user: LoggedInUser, db: DB, q: str = "", page: int = 1):
    page = max(1, page)
    bbox = None
    if q.strip():
        hit = await geocode.search(q)
        if hit:
            bbox = hit[2]
    cards, has_next = await discover_svc.popular_rides(db, user.id, bbox=bbox, page=page)
    return templates.TemplateResponse(
        request,
        "popular.html",
        {"title": "Popular routes", "q": q, "cards": cards, "page": page, "has_next": has_next},
    )
