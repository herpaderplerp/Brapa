# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Brapa — GPX ride sharing for motorcyclists. FastAPI (async) + HTMX + Alpine,
server-rendered Jinja2 with one stateful client-JS "map island" (Leaflet + uPlot).
Postgres/PostGIS via SQLAlchemy 2.0 + GeoAlchemy2 + Alembic. Containerized with Podman.

Full spec: `brapa_spec.md`. Implementation plan: `~/.claude/plans/quizzical-brewing-parnas.md`.

## Commands

Everything runs inside the app container against the `db` service — there is no
host virtualenv. All via `make`:

```sh
make build          # podman compose build
make up             # app on :8000, db on :5432
make migrate        # alembic upgrade head (inside container)
make revision m="msg"   # autogenerate Alembic migration
make test           # installs .[dev] then pytest -q in container
make fmt            # ruff format app tests
make vendor         # download front-end libs to app/static/vendor (host, needs curl)
make logs           # follow app logs
make shell          # bash in app container
```

Tests require a live Postgres/PostGIS (conftest uses a real engine on
`settings.database_url`, rolls back per test) — run via `make test`, not bare `pytest`.
Single test: `podman compose run --rm app sh -c "pip install -q -e '.[dev]' && pytest tests/test_gpx.py::test_name -q"`.

On Apple/libkrun Podman machines `podman compose` may fail to reach the Docker API
socket — see README.md for the native-podman fallback (the `postgis:16-3.4` image is
amd64, runs emulated, ~15s first-boot; wait for the *second* "ready to accept connections").

## Architecture

**Auth is OAuth-only and config-driven.** No passwords. `Settings.oauth_providers`
(app/config.py) builds a provider registry from env vars; generic `/login/{provider}`
routes pick up any provider present — adding one needs env vars only, no route/schema
change. Google is wired at launch. Email allowlist via `ALLOWED_EMAILS` (empty =
open registration); gate logic in `Settings.email_allowed`.

**Session → user resolution happens in two layers.** `load_user` HTTP middleware
(app/main.py) populates `request.state.user` from the signed session cookie for
templates. Route handlers instead use DI: `LoggedInUser` / `CurrentUser` deps
(app/auth/deps.py). `require_login` raises `_NotAuthenticated`, caught by an exception
handler in main.py that redirects to `/login` — dependencies can't return responses,
hence the exception dance. Middleware ordering matters: SessionMiddleware is added
*last* so it's outermost and runs before `load_user`.

**Ride upload is a two-phase pipeline.** Upload stores the raw GPX blob (app/services/storage.py)
and enqueues `process_ride` as a FastAPI **BackgroundTask** (shares the web process —
not a real queue; see note in app/services/processing.py). Processing parses GPX,
computes stats, downsamples points into `RidePoint`, stores full-res track geometry as
PostGIS, reverse-geocodes the start, fetches historical weather, and runs per-user
duplicate detection via `dedup_hash`. Status field drives the UI:
`processing/done/duplicate/failed`. HTMX polls `ride_status` partial until terminal.

**Two DB session patterns, deliberately separate.** Request handlers use the `get_db`
dependency (app/db.py) — yields, commits on success, rolls back on exception.
Background tasks and middleware open their own `SessionLocal()` context directly
(they have no request scope). `expire_on_commit=False` throughout.

**External services are best-effort.** geocode (Nominatim), weather (Open-Meteo) failures
don't fail the ride — weather has a manual `retry_weather` path (spec US-05a). Bases
configurable via env.

## Layout

- `app/routers/` — auth, profile, garage (bikes), rides. Mounted in main.py.
- `app/services/` — gpx (parse/stats/dedup), processing (pipeline), storage (blobs),
  geocode, weather, garage. Pure-ish, called by routers + background tasks.
- `app/models/` — user, bike, ride (Ride/RidePoint/RideWeather + STATUS_*/VISIBILITY_* consts).
- `app/templates/partials/` — HTMX fragment responses (bike_card, ride_status, etc.).
- `app/static/vendor/` — pinned front-end libs, populated by `make vendor` (not committed).
- `migrations/versions/` — Alembic; 0001 enables PostGIS.

## Conventions

- Python 3.12, ruff line-length 100, `from __future__ import annotations` in newer modules.
- pytest `asyncio_mode = auto` (no `@pytest.mark.asyncio` needed).
- Status/visibility are module-level string constants in app/models/ride.py — import them, don't inline literals.
- Secrets/config via pydantic-settings `.env`; never hardcode. `.env` is gitignored, `.env.example` is the template.
