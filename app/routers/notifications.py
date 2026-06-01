from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import LoggedInUser
from app.db import get_db
from app.services import notify as notify_svc
from app.templating import templates

router = APIRouter()
DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("/notifications", response_class=HTMLResponse)
async def notifications_page(request: Request, user: LoggedInUser, db: DB):
    items = await notify_svc.recent(db, user.id)
    # Mark read on view so the nav badge clears.
    await notify_svc.mark_all_read(db, user.id)
    return templates.TemplateResponse(
        request, "notifications.html", {"title": "Notifications", "items": items}
    )


@router.post("/notifications/read")
async def mark_read(user: LoggedInUser, db: DB):
    await notify_svc.mark_all_read(db, user.id)
    return RedirectResponse("/notifications", status_code=303)
