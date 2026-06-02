.PHONY: build up down logs migrate revision test shell fmt vendor sync

# Push the working tree to the remote dev box (run on the Mac). Mirrors files but
# never touches the remote .git or .venv. Commit to GitHub only at checkpoints.
REMOTE ?= user@devbuntu.local:brapa/
sync:
	rsync -az --delete-after \
	  --exclude '.git/' --exclude '.venv' --exclude 'var/' --exclude '__pycache__/' \
	  --exclude '.pytest_cache/' --exclude '.ruff_cache/' --exclude '.mypy_cache/' \
	  --exclude '*.pyc' --exclude '*.egg-info/' --exclude 'dist/' --exclude 'build/' \
	  ./ $(REMOTE)
	@echo "synced -> $(REMOTE)"

build:
	podman compose build

up:
	podman compose up -d

down:
	podman compose down

logs:
	podman compose logs -f app

# Run Alembic inside the app container against the db service.
migrate:
	podman compose run --rm app alembic upgrade head

revision:
	podman compose run --rm app alembic revision --autogenerate -m "$(m)"

# Bind-mount the repo so tests/ (excluded from the image) is visible; the script
# avoids nested-quote mangling across compose providers. Requires `make up` first
# (uses the running db service). Pass args via A="...": make test A="-k gpx".
test:
	podman compose run --rm -v "$(PWD):/app" app sh scripts/test.sh $(A)

shell:
	podman compose run --rm app bash

fmt:
	podman compose run --rm app ruff format app tests

# Download front-end libs into app/static/vendor (run on host, needs curl).
vendor:
	mkdir -p app/static/vendor
	curl -fsSL https://unpkg.com/htmx.org@2/dist/htmx.min.js          -o app/static/vendor/htmx.min.js
	curl -fsSL https://unpkg.com/alpinejs@3/dist/cdn.min.js            -o app/static/vendor/alpine.min.js
	curl -fsSL https://unpkg.com/leaflet@1.9.4/dist/leaflet.js         -o app/static/vendor/leaflet.js
	curl -fsSL https://unpkg.com/leaflet@1.9.4/dist/leaflet.css        -o app/static/vendor/leaflet.css
	curl -fsSL https://unpkg.com/uplot@1.6.31/dist/uPlot.iife.min.js   -o app/static/vendor/uplot.iife.min.js
	curl -fsSL https://unpkg.com/uplot@1.6.31/dist/uPlot.min.css       -o app/static/vendor/uplot.min.css
