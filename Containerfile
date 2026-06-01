# syntax=docker/dockerfile:1
# Multi-stage build: install deps with uv, then ship a slim runtime.

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv
# Build deps for asyncpg / shapely / pyproj wheels are prebuilt, but keep gcc
# available in case a sdist needs compiling.
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
RUN uv venv /opt/venv && uv pip install --python /opt/venv .

FROM python:3.12-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
# libproj / libgeos runtime libs for shapely & pyproj.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgeos-c1v5 libproj25 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /opt/venv /opt/venv
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
