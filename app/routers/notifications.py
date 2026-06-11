import hmac
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import LoggedInUser
from app.db import get_db
from app.services import notify as notify_svc
from app.templating import templates

router = APIRouter()
DB = Annotated[AsyncSession, Depends(get_db)]
NOTIFICATIONS_READ_CSRF_KEY = "notifications_read_csrf_token"


def _notifications_read_csrf_token(request: Request) -> str:
    token = request.session.get(NOTIFICATIONS_READ_CSRF_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[NOTIFICATIONS_READ_CSRF_KEY] = token
    return token


def _valid_notifications_read_csrf(request: Request, submitted: str) -> bool:
    token = request.session.get(NOTIFICATIONS_READ_CSRF_KEY)
    return bool(token and submitted and hmac.compare_digest(str(token), submitted))


@router.get("/notifications", response_class=HTMLResponse)
async def notifications_page(request: Request, user: LoggedInUser, db: DB):
    items = await notify_svc.recent(db, user.id)
    return templates.TemplateResponse(
        request,
        "notifications.html",
        {
            "title": "Notifications",
            "items": items,
            "notifications_read_csrf_token": _notifications_read_csrf_token(request),
        },
    )


@router.post("/notifications/read")
async def mark_read(
    request: Request,
    user: LoggedInUser,
    db: DB,
    csrf_token: Annotated[str, Form()] = "",
):
    if not _valid_notifications_read_csrf(request, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    await notify_svc.mark_all_read(db, user.id)
    return RedirectResponse("/notifications", status_code=303)
