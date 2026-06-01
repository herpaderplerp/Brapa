import uuid

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.auth.deps import SESSION_USER_KEY, _NotAuthenticated
from app.config import settings
from app.db import SessionLocal
from app.models.user import User
from app.routers import auth, compare, feed, friends, garage, notifications, profile, rides
from app.services import notify as notify_svc
from app.templating import BASE_DIR, templates

app = FastAPI(title="Brapa")

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.middleware("http")
async def load_user(request: Request, call_next):
    """Populate request.state.user from the session so templates can read it.
    Added before SessionMiddleware so it runs *inside* it (session is parsed)."""
    request.state.user = None
    request.state.unread = 0
    raw = request.session.get(SESSION_USER_KEY)
    if raw:
        try:
            uid = uuid.UUID(raw)
            async with SessionLocal() as db:
                request.state.user = await db.get(User, uid)
                if request.state.user is not None:
                    request.state.unread = await notify_svc.unread_count(db, uid)
        except (ValueError, TypeError):
            request.state.user = None
    return await call_next(request)


# SessionMiddleware added last => outermost => runs first, so request.session is
# ready by the time load_user runs.
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, https_only=False)


@app.exception_handler(_NotAuthenticated)
async def _not_authenticated_handler(request: Request, exc: _NotAuthenticated):
    return RedirectResponse("/login", status_code=303)


app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(garage.router)
app.include_router(rides.router)
app.include_router(friends.router)
app.include_router(feed.router)
app.include_router(notifications.router)
app.include_router(compare.router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {"title": "Brapa"})
