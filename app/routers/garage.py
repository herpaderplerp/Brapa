import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import LoggedInUser
from app.db import get_db
from app.services import garage as svc
from app.templating import templates

router = APIRouter(prefix="/garage")

DB = Annotated[AsyncSession, Depends(get_db)]


async def _render_list(request: Request, db: AsyncSession, user_id: uuid.UUID) -> HTMLResponse:
    bikes = await svc.list_bikes(db, user_id)
    return templates.TemplateResponse(
        request, "partials/bike_list.html", {"bikes": bikes}
    )


@router.get("", response_class=HTMLResponse)
async def garage_page(request: Request, user: LoggedInUser, db: DB):
    bikes = await svc.list_bikes(db, user.id)
    return templates.TemplateResponse(
        request, "garage.html", {"title": "Garage", "bikes": bikes}
    )


@router.post("", response_class=HTMLResponse)
async def add_bike(
    request: Request,
    user: LoggedInUser,
    db: DB,
    make: Annotated[str, Form()],
    model: Annotated[str, Form()],
    year: Annotated[str, Form()] = "",
    nickname: Annotated[str, Form()] = "",
    photo_url: Annotated[str, Form()] = "",
):
    make = make.strip()
    model = model.strip()
    if not make or not model:
        raise HTTPException(status_code=422, detail="Make and model are required")
    year_int = int(year) if year.strip().isdigit() else None
    await svc.add_bike(
        db,
        user.id,
        make=make,
        model=model,
        year=year_int,
        nickname=nickname.strip() or None,
        photo_url=photo_url.strip() or None,
    )
    return await _render_list(request, db, user.id)


async def _require_bike(db: AsyncSession, user_id: uuid.UUID, bike_id: uuid.UUID):
    bike = await svc.get_bike(db, user_id, bike_id)
    if bike is None:
        raise HTTPException(status_code=404, detail="Bike not found")
    return bike


@router.get("/{bike_id}/edit", response_class=HTMLResponse)
async def edit_form(request: Request, user: LoggedInUser, db: DB, bike_id: uuid.UUID):
    bike = await _require_bike(db, user.id, bike_id)
    return templates.TemplateResponse(request, "partials/bike_form.html", {"bike": bike})


@router.post("/{bike_id}", response_class=HTMLResponse)
async def update_bike(
    request: Request,
    user: LoggedInUser,
    db: DB,
    bike_id: uuid.UUID,
    make: Annotated[str, Form()],
    model: Annotated[str, Form()],
    year: Annotated[str, Form()] = "",
    nickname: Annotated[str, Form()] = "",
    photo_url: Annotated[str, Form()] = "",
):
    bike = await _require_bike(db, user.id, bike_id)
    bike.make = make.strip() or bike.make
    bike.model = model.strip() or bike.model
    bike.year = int(year) if year.strip().isdigit() else None
    bike.nickname = nickname.strip() or None
    bike.photo_url = photo_url.strip() or None
    db.add(bike)
    return await _render_list(request, db, user.id)


@router.post("/{bike_id}/default", response_class=HTMLResponse)
async def make_default(request: Request, user: LoggedInUser, db: DB, bike_id: uuid.UUID):
    bike = await _require_bike(db, user.id, bike_id)
    await svc.set_default(db, user.id, bike)
    return await _render_list(request, db, user.id)


@router.post("/{bike_id}/active", response_class=HTMLResponse)
async def toggle_active(
    request: Request,
    user: LoggedInUser,
    db: DB,
    bike_id: uuid.UUID,
    active: Annotated[str, Form()] = "false",
):
    bike = await _require_bike(db, user.id, bike_id)
    await svc.set_active(db, user.id, bike, active == "true")
    return await _render_list(request, db, user.id)
