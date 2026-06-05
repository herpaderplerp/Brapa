"""Manage privacy zones (US: hide route near home). Account-level circular
zones that clip the owner's tracks for other viewers — see app/services/privacy.py."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import LoggedInUser
from app.db import get_db
from app.models.privacy import PrivacyZone
from app.services import privacy as privacy_svc
from app.templating import templates

router = APIRouter(prefix="/privacy-zones")
DB = Annotated[AsyncSession, Depends(get_db)]


async def _zones(db: AsyncSession, user_id) -> list[PrivacyZone]:
    return list(
        (
            await db.execute(
                select(PrivacyZone)
                .where(PrivacyZone.user_id == user_id)
                .order_by(PrivacyZone.created_at)
            )
        )
        .scalars()
        .all()
    )


@router.get("", response_class=HTMLResponse)
async def zones_page(request: Request, user: LoggedInUser, db: DB):
    zones = await _zones(db, user.id)
    return templates.TemplateResponse(
        request,
        "privacy_zones.html",
        {
            "title": "Privacy zones",
            "zones": zones,
            "radius_default": int(privacy_svc.RADIUS_DEFAULT_M),
            "radius_min": int(privacy_svc.RADIUS_MIN_M),
            "radius_max": int(privacy_svc.RADIUS_MAX_M),
            "max_zones": privacy_svc.MAX_ZONES,
            "at_limit": len(zones) >= privacy_svc.MAX_ZONES,
        },
    )


@router.post("")
async def create_zone(
    user: LoggedInUser,
    db: DB,
    lat: Annotated[float, Form()],
    lon: Annotated[float, Form()],
    radius_m: Annotated[float, Form()] = privacy_svc.RADIUS_DEFAULT_M,
    label: Annotated[str, Form()] = "Zone",
):
    count = (
        await db.execute(
            select(func.count(PrivacyZone.id)).where(PrivacyZone.user_id == user.id)
        )
    ).scalar_one()
    if count >= privacy_svc.MAX_ZONES:
        raise HTTPException(status_code=400, detail="Zone limit reached")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(status_code=422, detail="Bad coordinates")

    db.add(
        PrivacyZone(
            user_id=user.id,
            label=(label.strip() or "Zone")[:80],
            center_lat=lat,
            center_lon=lon,
            radius_m=privacy_svc.clamp_radius(radius_m),
        )
    )
    return RedirectResponse("/privacy-zones", status_code=303)


@router.post("/{zone_id}/delete")
async def delete_zone(user: LoggedInUser, db: DB, zone_id: uuid.UUID):
    zone = await db.get(PrivacyZone, zone_id)
    if zone is not None and zone.user_id == user.id:
        await db.delete(zone)
    return RedirectResponse("/privacy-zones", status_code=303)
