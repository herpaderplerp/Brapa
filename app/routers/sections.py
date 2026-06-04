"""Cross-ride section management: one page listing every section the user owns,
with inline rename + delete. Per-ride create/view/delete still live on the ride
detail page (app/routers/rides.py); these routes are keyed by section id alone
and verify ownership via the parent ride, so no ride id is needed in the path.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import LoggedInUser
from app.db import get_db
from app.services import sections as svc
from app.templating import templates

router = APIRouter(prefix="/sections")

DB = Annotated[AsyncSession, Depends(get_db)]


async def _render_list(request: Request, db: AsyncSession, user_id: uuid.UUID) -> HTMLResponse:
    sections = await svc.list_for_user(db, user_id)
    return templates.TemplateResponse(
        request, "partials/section_manage_list.html", {"sections": sections}
    )


async def _owned(db: AsyncSession, user_id: uuid.UUID, section_id: uuid.UUID):
    section = await svc.get_owned(db, user_id, section_id)
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found")
    return section


@router.get("", response_class=HTMLResponse)
async def manage_page(request: Request, user: LoggedInUser, db: DB):
    sections = await svc.list_for_user(db, user.id)
    return templates.TemplateResponse(
        request, "sections_manage.html", {"title": "Your sections", "sections": sections}
    )


@router.post("/{section_id}/rename", response_class=HTMLResponse)
async def rename_section(
    request: Request,
    user: LoggedInUser,
    db: DB,
    section_id: uuid.UUID,
    name: Annotated[str, Form()],
):
    section = await _owned(db, user.id, section_id)
    try:
        await svc.rename(db, section, name)
    except svc.SectionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await _render_list(request, db, user.id)


@router.post("/{section_id}/delete", response_class=HTMLResponse)
async def delete_section(request: Request, user: LoggedInUser, db: DB, section_id: uuid.UUID):
    section = await _owned(db, user.id, section_id)
    await db.delete(section)
    await db.flush()
    return await _render_list(request, db, user.id)
