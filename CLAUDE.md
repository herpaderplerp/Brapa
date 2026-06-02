# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Brapa — GPX ride sharing for motorcyclists. FastAPI (async) + HTMX + Alpine,
server-rendered Jinja2 with one stateful client-JS "map island" (Leaflet + uPlot).
Postgres/PostGIS via SQLAlchemy 2.0 + GeoAlchemy2 + Alembic. Containerized with Podman.

Full spec: `brapa_spec.md`. Implementation plan: `~/.claude/plans/quizzical-brewing-parnas.md`.

## Where to develop

**Do dev on the remote box whenever possible:** `ssh devbuntu.local -l user`,
project at `~/brapa`. It's native amd64 (no libkrun emulation), has podman +
podman-compose, a `.venv`, and git push/pull wired to GitHub — builds, the
postgis container, and tests are all fast there. The macOS host runs Podman
under libkrun (emulated amd64 postgis, slow first boot, `podman compose` can't
reach the Docker API socket — native `podman` fallback only). Prefer the remote
for build/run/test; use the Mac mainly for editing + committing.

Iteration loop (preferred): **edit on Mac → `make sync` → run on remote.**
`make sync` rsyncs the working tree (incl. uncommitted changes) to
`user@devbuntu.local:brapa/`, mirroring files but never touching the remote
`.git` or `.venv`. Then on the remote: `make test` / `make up` / `make logs`.
Commit + `git push` to GitHub only at checkpoints — not every tweak. (GitHub
`git pull` on remote also works but `make sync` avoids the commit churn.)
`make test` there is self-contained (bind-mounts the repo, installs dev extras,
skips the node test if node is absent).

**Testing Google login against the remote app:** SSH local port-forward, then
browse `http://localhost:8000` on the Mac:

```sh
ssh -L 8000:localhost:8000 devbuntu.local -l user
```

Works with zero config because the app's `BASE_URL=http://localhost:8000`
builds a `localhost` `redirect_uri` that's already authorized in Google Console,
and Google permits `localhost` over plain HTTP. Browsing `devbuntu.local:8000`
directly fails — the callback lands on the Mac's localhost and the URI isn't
registered. (Confirmed working.)

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
