# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Brapa — GPX ride sharing for motorcyclists. FastAPI (async) + HTMX + Alpine,
server-rendered Jinja2 with one stateful client-JS "map island" (Leaflet + uPlot).
Postgres/PostGIS via SQLAlchemy 2.0 + GeoAlchemy2 + Alembic. Containerized with Podman.

Full spec: `brapa_spec.md`. Implementation plan: `~/.claude/plans/quizzical-brewing-parnas.md`.

## Where to develop

**Develop directly on `devbuntu` (`~/brapa`).** This is the native-amd64 build
box: podman + podman-compose, a `.venv`, and git push/pull wired to GitHub —
builds, the postgis container, and tests are all fast here. Edit in place, run
`make test` / `make up` / `make logs`, and commit + `git push` straight from
this repo with an ordinary git workflow (no rsync, no HEAD reconcile dance).
`make test` is self-contained (bind-mounts the repo, installs dev extras, skips
the node test if node is absent).

(Historical note: this repo used to be driven from a macOS host that ran Podman
under libkrun — emulated amd64 postgis, slow first boot, `podman compose`
couldn't reach the Docker API socket — via an `edit-on-Mac → make sync → run-on-
remote` loop. That loop is retired; the `make sync` target has been dropped.)

**Testing Google login against the app:** from the laptop with the browser, SSH
local port-forward, then browse `http://localhost:8000`:

```sh
ssh -L 8000:localhost:8000 devbuntu.local -l user
```

Works with zero config because the app's `BASE_URL=http://localhost:8000`
builds a `localhost` `redirect_uri` that's already authorized in Google Console,
and Google permits `localhost` over plain HTTP. Browsing `devbuntu.local:8000`
directly fails — the callback lands on the client's localhost and the URI isn't
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

## Frontend / map gotchas

The Leaflet "map island" has bitten us more than once with the same two symptoms.
If a map renders wrong, it's almost always one of these — check them before
re-debugging from scratch.

**Symptom A — map paints full-width at the top of the page, overlapping the
header (instead of inside its card).** Cause: Leaflet's panes are
`position:absolute`, and the vendored `leaflet.css` only sets `overflow:hidden`
on `.leaflet-container` — no `position`. With no positioning context the panes
anchor to the viewport. Fix: `#map { position: relative }` (in app.css). It's
most visible when `#map` sits *below* other content (e.g. the privacy-zones page,
where the map is under the "Your zones" list); on pages where `#map` is near the
top the panes happen to line up and the bug hides.

**Symptom B — map is the right place but oversized / mis-scaled until a manual
refresh.** Cause: the container's real size (vh-based height, or laid out *after*
init under `hx-boost`'s body-swap navigation) isn't known when `L.map()` runs, so
Leaflet caches a stale/zero size. Fixes in use: `map.js` `_fixSize()`
(invalidateSize via rAF + setTimeout + window load) for the fetch-driven ride/
section maps; `zones.js` uses a **ResizeObserver** on `#map` calling
`invalidateSize()` (more robust for a synchronously-initialised map below dynamic
content). Any new synchronously-built map should do likewise.

**Symptom C — a CSS/JS change "doesn't take" until a hard refresh (or looks fixed
for you but not the user).** Cause: browsers cache `/static/*` across windows;
`hx-boost` navigation won't re-fetch a cached script. This wasted real debugging
time. Fix: reference static assets through the `static_url()` template global
(app/templating.py), which appends the file's mtime as `?v=` so the URL changes
whenever the file does. **Always use `{{ static_url('js/foo.js') }}`, never a bare
`/static/...` path**, in templates — otherwise stale-cache bugs masquerade as code
bugs. Static files and templates are bind-mounted (`./app`), so they serve live
with no rebuild; only `.py` (uvicorn `--reload`) and migrations/Containerfile
changes need anything more.
