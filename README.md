# Brapa

GPX ride sharing for motorcyclists. FastAPI + HTMX + Alpine, Leaflet/uPlot map
island, Postgres/PostGIS. Containerized with Podman.

See the full spec in `brapa_spec.md` and the implementation plan in
`~/.claude/plans/quizzical-brewing-parnas.md`.

## Quick start

```sh
cp .env.example .env                  # then set SESSION_SECRET + Google OAuth keys
make vendor                           # download front-end libs into app/static/vendor
make build
make up                               # app on http://localhost:8000, db on :5432
make migrate                          # apply Alembic migrations
make test
```

## Stack

- **Backend:** FastAPI (async), Jinja2 + HTMX, Alpine.js
- **Map island:** Leaflet + uPlot (the one stateful client-JS area)
- **DB:** Postgres + PostGIS via SQLAlchemy 2.0 + GeoAlchemy2 + Alembic (async)
- **Auth:** OAuth-only, provider-agnostic (Authlib + signed session cookie).
  Google wired at launch; add providers via `.env` + `Settings.oauth_providers`.
- **GPX/geo:** gpxpy, shapely, pyproj; weather via Open-Meteo (httpx)

## Podman socket note (Apple / libkrun machines)

On some macOS Podman machines (libkrun backend), `podman compose` delegates to
`docker-compose`, which needs a Docker-compatible API socket that the machine
does not always forward — you'll see `failed to connect to the docker API ...
no such file or directory`. Two options:

1. **Native podman fallback** (works over the SSH connection):
   ```sh
   podman network create brapa
   podman run -d --name brapa-db --network brapa \
     -e POSTGRES_USER=brapa -e POSTGRES_PASSWORD=brapa -e POSTGRES_DB=brapa \
     -p 5432:5432 docker.io/postgis/postgis:16-3.4
   podman build -t brapa-app -f Containerfile .
   podman run --rm --network brapa \
     -e DATABASE_URL=postgresql+asyncpg://brapa:brapa@brapa-db:5432/brapa \
     brapa-app alembic upgrade head
   podman run -d --name brapa-app-run --network brapa -p 8000:8000 \
     -e DATABASE_URL=postgresql+asyncpg://brapa:brapa@brapa-db:5432/brapa \
     -e SESSION_SECRET=dev -v "$(pwd)/app:/app/app" brapa-app
   ```
   > The `postgis:16-3.4` image is amd64; under libkrun it runs emulated and its
   > first-boot init takes ~15s before the TCP listener is up. Wait for the
   > **second** "ready to accept connections" log line before connecting.

2. Enable a Docker-API socket for the machine and point `DOCKER_HOST` at it so
   `podman compose` works directly.
