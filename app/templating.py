from pathlib import Path

from starlette.requests import Request
from fastapi.templating import Jinja2Templates

from app import units

BASE_DIR = Path(__file__).resolve().parent


def _user_context(request: Request) -> dict:
    # request.state.user is populated by the load_user middleware (main.py).
    return {"user": getattr(request.state, "user", None)}


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
