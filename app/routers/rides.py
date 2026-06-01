import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import LoggedInUser
from app.db import get_db
from app.models.ride import (
    STATUS_DONE,
    STATUS_DUPLICATE,
    STATUS_FAILED,
    STATUS_PROCESSING,
    VISIBILITY_PRIVATE,
    Ride,
    RidePoint,
)
from app.services import garage as garage_svc
from app.services import storage
from app.services.processing import process_ride, retry_weather
from app.templating import templates

router = APIRouter(prefix="/rides")

DB = Annotated[AsyncSession, Depends(get_db)]

MAX_BYTES = 50 * 1024 * 1024  # 50 MB (spec US-04)
ROAD_TAGS = ["Twisties", "Highway", "Mixed", "Gravel", "Track Day"]
MOOD_TAGS = ["Casual", "Spirited", "Touring", "Commute"]


async def _owned_ride(db: AsyncSession, user_id: uuid.UUID, ride_id: uuid.UUID) -> Ride:
    ride = await db.get(Ride, ride_id)
    if ride is None or ride.user_id != user_id:
        raise HTTPException(status_code=404, detail="Ride not found")
    return ride


@router.get("", response_class=HTMLResponse)
async def my_rides(request: Request, user: LoggedInUser, db: DB):
    rows = (
        await db.execute(
            select(Ride)
            .where(Ride.user_id == user.id)
            .order_by(Ride.created_at.desc())
        )
    ).scalars().all()
    return templates.TemplateResponse(
        request, "rides_list.html", {"title": "My rides", "rides": rows}
    )


@router.get("/upload", response_class=HTMLResponse)
async def upload_page(request: Request, user: LoggedInUser, db: DB):
    # Spec US-03: at least one active bike required before the first upload.
    if not await garage_svc.has_active_bike(db, user.id):
        return templates.TemplateResponse(
            request, "upload.html", {"title": "Upload", "needs_bike": True}
        )
    return templates.TemplateResponse(
        request, "upload.html", {"title": "Upload", "needs_bike": False}
    )


@router.post("/upload")
async def upload_submit(
    request: Request,
    user: LoggedInUser,
    db: DB,
    background: BackgroundTasks,
    file: Annotated[UploadFile, File()],
):
    if not await garage_svc.has_active_bike(db, user.id):
        raise HTTPException(status_code=400, detail="Add an active bike first")

    name = (file.filename or "").lower()
    if not name.endswith(".gpx"):
        raise HTTPException(status_code=422, detail="File must be a .gpx")

    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 50 MB")
    if b"<gpx" not in data[:4096].lower():
        raise HTTPException(status_code=422, detail="Not a valid GPX file")

    key = storage.save_gpx(data)
    ride = Ride(
        user_id=user.id,
        gpx_blob_key=key,
        processing_status=STATUS_PROCESSING,
        visibility=VISIBILITY_PRIVATE,
    )
    db.add(ride)
    await db.flush()
    ride_id = ride.id
    await db.commit()

    # Process after the response is sent (keeps upload fast; 10s budget in worker).
    background.add_task(process_ride, ride_id)
    return RedirectResponse(f"/rides/{ride_id}/processing", status_code=303)


@router.get("/{ride_id}/processing", response_class=HTMLResponse)
async def processing_page(request: Request, user: LoggedInUser, db: DB, ride_id: uuid.UUID):
    ride = await _owned_ride(db, user.id, ride_id)
    return templates.TemplateResponse(
        request, "processing.html", {"title": "Processing ride", "ride": ride}
    )


@router.get("/{ride_id}/status")
async def status_partial(request: Request, user: LoggedInUser, db: DB, ride_id: uuid.UUID):
    ride = await _owned_ride(db, user.id, ride_id)
    if ride.processing_status == STATUS_DONE:
        # Tell htmx to navigate the whole page to the review screen.
        return Response(status_code=200, headers={"HX-Redirect": f"/rides/{ride_id}/review"})
    return templates.TemplateResponse(
        request, "partials/ride_status.html", {"ride": ride}
    )


@router.post("/{ride_id}/import-anyway")
async def import_anyway(request: Request, user: LoggedInUser, db: DB, ride_id: uuid.UUID):
    ride = await _owned_ride(db, user.id, ride_id)
    if ride.processing_status == STATUS_DUPLICATE:
        ride.processing_status = STATUS_DONE
        db.add(ride)
    return Response(status_code=200, headers={"HX-Redirect": f"/rides/{ride_id}/review"})


@router.get("/{ride_id}/review", response_class=HTMLResponse)
async def review_page(request: Request, user: LoggedInUser, db: DB, ride_id: uuid.UUID):
    ride = await _owned_ride(db, user.id, ride_id)
    if ride.processing_status == STATUS_FAILED:
        return templates.TemplateResponse(
            request, "processing.html", {"title": "Processing failed", "ride": ride}
        )
    bikes = await garage_svc.list_bikes(db, user.id, active_only=True)
    default_title = _auto_title(ride)
    return templates.TemplateResponse(
        request,
        "ride_review.html",
        {
            "title": "Review ride",
            "ride": ride,
            "bikes": bikes,
            "road_tags": ROAD_TAGS,
            "mood_tags": MOOD_TAGS,
            "default_title": default_title,
        },
    )


@router.post("/{ride_id}/review")
async def review_submit(
    request: Request,
    user: LoggedInUser,
    db: DB,
    ride_id: uuid.UUID,
    title: Annotated[str, Form()] = "",
    description_md: Annotated[str, Form()] = "",
    bike_id: Annotated[str, Form()] = "",
    visibility: Annotated[str, Form()] = VISIBILITY_PRIVATE,
    road_tags: Annotated[list[str], Form()] = (),
    mood_tags: Annotated[list[str], Form()] = (),
):
    ride = await _owned_ride(db, user.id, ride_id)
    ride.title = title.strip() or _auto_title(ride)
    ride.description_md = description_md.strip() or None
    ride.visibility = visibility if visibility in ("public", "friends", "private") else "private"
    ride.road_tags = [t for t in road_tags if t in ROAD_TAGS]
    ride.mood_tags = [t for t in mood_tags if t in MOOD_TAGS]
    if bike_id:
        try:
            bike = await garage_svc.get_bike(db, user.id, uuid.UUID(bike_id))
            ride.bike_id = bike.id if bike else None
        except ValueError:
            ride.bike_id = None
    ride.published = True
    db.add(ride)
    return RedirectResponse(f"/rides/{ride_id}", status_code=303)


@router.post("/{ride_id}/weather/retry")
async def weather_retry(
    request: Request,
    user: LoggedInUser,
    db: DB,
    background: BackgroundTasks,
    ride_id: uuid.UUID,
):
    await _owned_ride(db, user.id, ride_id)
    background.add_task(retry_weather, ride_id)
    return RedirectResponse(f"/rides/{ride_id}", status_code=303)


@router.get("/{ride_id}/points.json")
async def ride_points(user: LoggedInUser, db: DB, ride_id: uuid.UUID):
    ride = await _owned_ride(db, user.id, ride_id)
    rows = (
        await db.execute(
            select(RidePoint).where(RidePoint.ride_id == ride.id).order_by(RidePoint.seq)
        )
    ).scalars().all()
    points = [
        {"lat": p.lat, "lon": p.lon, "elev": p.elev, "speed": p.speed, "t": p.t}
        for p in rows
    ]
    return JSONResponse({"points": points})


@router.get("/{ride_id}/gpx")
async def download_gpx(user: LoggedInUser, db: DB, ride_id: uuid.UUID):
    # Data export, no lock-in (NFR). Owner only for now.
    ride = await _owned_ride(db, user.id, ride_id)
    if not ride.gpx_blob_key:
        raise HTTPException(status_code=404, detail="No file")
    data = storage.read(ride.gpx_blob_key)
    return Response(
        content=data,
        media_type="application/gpx+xml",
        headers={"Content-Disposition": f'attachment; filename="ride-{ride_id}.gpx"'},
    )


@router.get("/{ride_id}", response_class=HTMLResponse)
async def ride_detail(request: Request, user: LoggedInUser, db: DB, ride_id: uuid.UUID):
    # Minimal stub; full map + stats + elevation land in Phase 4.
    ride = await _owned_ride(db, user.id, ride_id)
    return templates.TemplateResponse(
        request, "ride_detail.html", {"title": ride.title or "Ride", "ride": ride}
    )


def _auto_title(ride: Ride) -> str:
    region = ride.start_region or "the unknown"
    date = ride.start_time.strftime("%b %-d, %Y") if ride.start_time else "undated"
    return f"Ride in {region}, {date}"
