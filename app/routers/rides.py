import io
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
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import LoggedInUser
from app.db import get_db
from app.models.photo import Photo
from app.models.ride import (
    STATUS_DONE,
    STATUS_DUPLICATE,
    STATUS_FAILED,
    STATUS_PROCESSING,
    VISIBILITY_PRIVATE,
    Ride,
    RidePoint,
)
from app.models.user import User
from app.services import exif
from app.services import feed as feed_svc
from app.services import garage as garage_svc
from app.services import privacy as privacy_svc
from app.csrf import csrf_token, require_csrf_token
from app.services import sections as sections_svc
from app.services import social
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


async def _viewable_ride(db: AsyncSession, viewer_id: uuid.UUID, ride_id: uuid.UUID) -> Ride:
    """Ride the viewer is allowed to see (owner / public / friends-only). 404 otherwise
    so private rides never leak existence."""
    ride = await db.get(Ride, ride_id)
    if ride is None or not await social.can_view_ride(db, viewer_id, ride):
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


@router.get("/{ride_id}/edit", response_class=HTMLResponse)
async def edit_page(request: Request, user: LoggedInUser, db: DB, ride_id: uuid.UUID):
    ride = await _owned_ride(db, user.id, ride_id)
    bikes = await garage_svc.list_bikes(db, user.id, active_only=True)
    return templates.TemplateResponse(
        request,
        "ride_edit.html",
        {
            "title": "Edit ride",
            "ride": ride,
            "bikes": bikes,
            "road_tags": ROAD_TAGS,
            "mood_tags": MOOD_TAGS,
        },
    )


@router.post("/{ride_id}/edit")
async def edit_submit(
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
    db.add(ride)
    return RedirectResponse(f"/rides/{ride_id}", status_code=303)


@router.post("/{ride_id}/delete")
async def delete_ride(user: LoggedInUser, db: DB, ride_id: uuid.UUID):
    ride = await _owned_ride(db, user.id, ride_id)
    key = ride.gpx_blob_key
    await db.delete(ride)  # cascades to points + weather
    await db.flush()
    if key:
        storage.delete(key)
    return RedirectResponse("/rides", status_code=303)


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
    ride = await _viewable_ride(db, user.id, ride_id)
    rows = (
        await db.execute(
            select(RidePoint).where(RidePoint.ride_id == ride.id).order_by(RidePoint.seq)
        )
    ).scalars().all()
    zones = await privacy_svc.effective_zones(db, user.id, ride)
    return JSONResponse(_points_payload(rows, zones))


def _point_dict(p) -> dict:
    return {"lat": p.lat, "lon": p.lon, "elev": p.elev, "speed": p.speed, "t": p.t}


def _points_payload(rows, zones=()) -> dict:
    """Gap-aware track payload. `segments` is the authoritative gap-split form
    (privacy-clipped for non-owners); `points` is their flat concatenation, kept
    for the elevation chart and marker indexing. With no zones it's one segment."""
    segs = privacy_svc.clip_segments(rows, list(zones))
    seg_json = [[_point_dict(p) for p in seg] for seg in segs]
    flat = [pt for seg in seg_json for pt in seg]
    return {"points": flat, "segments": seg_json}


@router.post("/{ride_id}/sections", response_class=HTMLResponse)
async def create_section(
    request: Request,
    user: LoggedInUser,
    db: DB,
    _: Annotated[None, Depends(require_csrf_token)],
    ride_id: uuid.UUID,
    name: Annotated[str, Form()],
    start_seq: Annotated[int, Form()],
    end_seq: Annotated[int, Form()],
):
    ride = await _owned_ride(db, user.id, ride_id)
    try:
        await sections_svc.create(db, ride.id, name, start_seq, end_seq)
    except sections_svc.SectionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await db.flush()
    rows = await sections_svc.list_for_ride(db, ride.id)
    return templates.TemplateResponse(
        request,
        "partials/section_list.html",
        {"ride": ride, "sections": rows, "is_owner": True, "csrf_token": csrf_token(request)},
    )


@router.post("/{ride_id}/sections/{section_id}/delete")
async def delete_section(
    user: LoggedInUser,
    db: DB,
    _: Annotated[None, Depends(require_csrf_token)],
    ride_id: uuid.UUID,
    section_id: uuid.UUID,
):
    await _owned_ride(db, user.id, ride_id)
    section = await sections_svc.get(db, ride_id, section_id)
    if section is not None:
        await db.delete(section)
    return RedirectResponse(f"/rides/{ride_id}", status_code=303)


@router.get("/{ride_id}/sections/{section_id}", response_class=HTMLResponse)
async def section_detail(
    request: Request, user: LoggedInUser, db: DB, ride_id: uuid.UUID, section_id: uuid.UUID
):
    ride = await _viewable_ride(db, user.id, ride_id)
    section = await sections_svc.get(db, ride.id, section_id)
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found")
    rows = await sections_svc.slice_points(db, section)
    zones = await privacy_svc.effective_zones(db, user.id, ride)
    # Stats reflect only the visible (un-redacted) portion for non-owners.
    visible = [p for seg in privacy_svc.clip_segments(rows, zones) for p in seg]
    stats = sections_svc.section_stats(visible)
    return templates.TemplateResponse(
        request,
        "section_detail.html",
        {"title": section.name, "ride": ride, "section": section, "stats": stats},
    )


@router.get("/{ride_id}/sections/{section_id}/points.json")
async def section_points(user: LoggedInUser, db: DB, ride_id: uuid.UUID, section_id: uuid.UUID):
    ride = await _viewable_ride(db, user.id, ride_id)
    section = await sections_svc.get(db, ride.id, section_id)
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found")
    rows = await sections_svc.slice_points(db, section)
    zones = await privacy_svc.effective_zones(db, user.id, ride)
    return JSONResponse(_points_payload(rows, zones))


MAX_PHOTOS = 50
PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic"}
PHOTO_FORMATS = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
    "HEIF": ("image/heic", "heic"),
}
PHOTO_MEDIA_TYPES = {ext: media_type for media_type, ext in PHOTO_FORMATS.values()}


def _validated_photo_extension(data: bytes, content_type: str | None) -> str:
    if content_type not in PHOTO_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported photo type")

    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
            image_format = image.format
    except (UnidentifiedImageError, OSError):
        raise HTTPException(status_code=400, detail="Invalid photo image") from None

    media_type_and_ext = PHOTO_FORMATS.get(image_format or "")
    if media_type_and_ext is None or media_type_and_ext[0] != content_type:
        raise HTTPException(status_code=400, detail="Unsupported photo type")
    return media_type_and_ext[1]


def _photo_media_type(blob_key: str) -> str:
    ext = blob_key.rsplit(".", 1)[-1].lower()
    return PHOTO_MEDIA_TYPES.get(ext, "application/octet-stream")


@router.post("/{ride_id}/photos")
async def upload_photos(
    user: LoggedInUser,
    db: DB,
    ride_id: uuid.UUID,
    files: Annotated[list[UploadFile], File()] = (),
):
    ride = await _owned_ride(db, user.id, ride_id)
    existing = (
        await db.execute(select(func.count(Photo.id)).where(Photo.ride_id == ride.id))
    ).scalar_one()
    seq = existing
    for f in files:
        if existing >= MAX_PHOTOS:
            break
        data = await f.read()
        if not data:
            continue
        ext = _validated_photo_extension(data, f.content_type)
        lat, lon, taken = exif.extract(data)
        key = storage.save_photo(data, ext)
        db.add(
            Photo(ride_id=ride.id, blob_key=key, lat=lat, lon=lon, taken_at=taken, seq=seq)
        )
        seq += 1
        existing += 1
    return RedirectResponse(f"/rides/{ride_id}", status_code=303)


@router.get("/{ride_id}/photos/{photo_id}/file")
async def photo_file(user: LoggedInUser, db: DB, ride_id: uuid.UUID, photo_id: uuid.UUID):
    await _viewable_ride(db, user.id, ride_id)
    photo = await db.get(Photo, photo_id)
    if photo is None or photo.ride_id != ride_id:
        raise HTTPException(status_code=404, detail="Photo not found")
    return FileResponse(
        storage.path_for(photo.blob_key),
        media_type=_photo_media_type(photo.blob_key),
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.post("/{ride_id}/photos/{photo_id}/delete")
async def delete_photo(user: LoggedInUser, db: DB, ride_id: uuid.UUID, photo_id: uuid.UUID):
    await _owned_ride(db, user.id, ride_id)
    photo = await db.get(Photo, photo_id)
    if photo and photo.ride_id == ride_id:
        key = photo.blob_key
        await db.delete(photo)
        await db.flush()
        storage.delete(key)
    return RedirectResponse(f"/rides/{ride_id}", status_code=303)


@router.post("/{ride_id}/photos/{photo_id}/place")
async def place_photo(
    user: LoggedInUser,
    db: DB,
    ride_id: uuid.UUID,
    photo_id: uuid.UUID,
    lat: Annotated[float, Form()],
    lon: Annotated[float, Form()],
):
    # Manual geotag placement (US-14) for photos without EXIF GPS. Owner only.
    await _owned_ride(db, user.id, ride_id)
    photo = await db.get(Photo, photo_id)
    if photo is None or photo.ride_id != ride_id:
        raise HTTPException(status_code=404, detail="Photo not found")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(status_code=422, detail="Bad coordinates")
    photo.lat = lat
    photo.lon = lon
    db.add(photo)
    return RedirectResponse(f"/rides/{ride_id}", status_code=303)


@router.get("/{ride_id}/photos.json")
async def photos_json(user: LoggedInUser, db: DB, ride_id: uuid.UUID):
    ride = await _viewable_ride(db, user.id, ride_id)
    rows = (
        await db.execute(
            select(Photo).where(Photo.ride_id == ride.id, Photo.lat.isnot(None)).order_by(Photo.seq)
        )
    ).scalars().all()
    # Hide geotagged photos that fall inside the owner's privacy zones.
    zones = await privacy_svc.effective_zones(db, user.id, ride)
    rows = [p for p in rows if not privacy_svc.in_any_zone(p.lat, p.lon, zones)]
    return JSONResponse(
        {
            "photos": [
                {"id": str(p.id), "lat": p.lat, "lon": p.lon,
                 "url": f"/rides/{ride_id}/photos/{p.id}/file"}
                for p in rows
            ]
        }
    )


@router.get("/{ride_id}/gpx")
async def download_gpx(user: LoggedInUser, db: DB, ride_id: uuid.UUID):
    # Data export, no lock-in (NFR). Owner only for now.
    ride = await _viewable_ride(db, user.id, ride_id)
    if not ride.gpx_blob_key:
        raise HTTPException(status_code=404, detail="No file")
    data = storage.read(ride.gpx_blob_key)
    # Non-owners get a copy with in-zone trackpoints stripped; owner gets original.
    zones = await privacy_svc.effective_zones(db, user.id, ride)
    if zones:
        data = privacy_svc.clip_gpx(data, zones)
    return Response(
        content=data,
        media_type="application/gpx+xml",
        headers={"Content-Disposition": f'attachment; filename="ride-{ride_id}.gpx"'},
    )


@router.post("/{ride_id}/like", response_class=HTMLResponse)
async def toggle_like(request: Request, user: LoggedInUser, db: DB, ride_id: uuid.UUID):
    ride = await _viewable_ride(db, user.id, ride_id)
    await feed_svc.toggle_like(db, ride.id, user.id)
    await db.flush()
    count = await feed_svc.like_count(db, ride.id)
    liked = await feed_svc.has_liked(db, ride.id, user.id)
    return templates.TemplateResponse(
        request, "partials/like_button.html",
        {"ride": ride, "like_count": count, "liked": liked},
    )


@router.post("/{ride_id}/comments")
async def post_comment(
    user: LoggedInUser,
    db: DB,
    ride_id: uuid.UUID,
    body: Annotated[str, Form()],
    parent_id: Annotated[str, Form()] = "",
):
    ride = await _viewable_ride(db, user.id, ride_id)
    pid = None
    if parent_id:
        try:
            pid = uuid.UUID(parent_id)
        except ValueError:
            pid = None
    await feed_svc.add_comment(db, ride.id, user.id, body, pid)
    return RedirectResponse(f"/rides/{ride_id}#comments", status_code=303)


@router.get("/{ride_id}", response_class=HTMLResponse)
async def ride_detail(request: Request, user: LoggedInUser, db: DB, ride_id: uuid.UUID):
    ride = await _viewable_ride(db, user.id, ride_id)
    is_owner = ride.user_id == user.id
    author = await db.get(User, ride.user_id)
    likes, liked, comments = await feed_svc.ride_social(db, ride.id, user.id)
    return templates.TemplateResponse(
        request,
        "ride_detail.html",
        {
            "title": ride.title or "Ride",
            "ride": ride,
            "is_owner": is_owner,
            "author": author,
            "like_count": likes,
            "liked": liked,
            "comments": comments,
            "csrf_token": csrf_token(request),
        },
    )


def _auto_title(ride: Ride) -> str:
    region = ride.start_region or "the unknown"
    date = ride.start_time.strftime("%b %-d, %Y") if ride.start_time else "undated"
    return f"Ride in {region}, {date}"
