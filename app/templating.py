from pathlib import Path

from starlette.requests import Request
from fastapi.templating import Jinja2Templates

from app import units

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


def static_url(path: str) -> str:
    """Cache-busted URL for a file under /static. Appends the file's mtime as
    `?v=`, so the URL changes whenever the file changes and browsers can never
    serve a stale CSS/JS after a deploy. `path` is relative to /static, e.g.
    static_url("js/zones.js") -> "/static/js/zones.js?v=1717533123"."""
    rel = path.lstrip("/")
    try:
        v = int((STATIC_DIR / rel).stat().st_mtime)
    except OSError:
        v = 0
    return f"/static/{rel}?v={v}"


def _user_context(request: Request) -> dict:
    # request.state.user / .unread are populated by the load_user middleware.
    return {
        "user": getattr(request.state, "user", None),
        "unread": getattr(request.state, "unread", 0),
    }


templates = Jinja2Templates(
    directory=BASE_DIR / "templates",
    context_processors=[_user_context],
)

# Unit-aware display helpers available in all templates.
templates.env.filters["distance"] = units.fmt_distance
templates.env.filters["speed"] = units.fmt_speed
templates.env.filters["temp"] = units.fmt_temp
templates.env.filters["elev"] = units.fmt_elev
templates.env.filters["duration"] = units.fmt_duration
templates.env.globals["fmt_wind"] = units.fmt_wind
templates.env.globals["static_url"] = static_url
