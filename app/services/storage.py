"""Blob storage for original GPX files (and later, photos).

Local filesystem in dev behind a tiny interface so S3/GCS can swap in later
without touching routes. Keys are opaque strings.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from app.config import settings

_ROOT = Path(settings.storage_dir)


def _ensure_root() -> Path:
    _ROOT.mkdir(parents=True, exist_ok=True)
    return _ROOT


def save_gpx(data: bytes) -> str:
    _ensure_root()
    key = f"gpx/{uuid.uuid4().hex}.gpx"
    path = _ROOT / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return key


PHOTO_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "heic"}


def save_photo(data: bytes, ext: str) -> str:
    _ensure_root()
    safe_ext = ext.lower().lstrip(".")
    if safe_ext == "jpeg":
        safe_ext = "jpg"
    if safe_ext not in PHOTO_EXTENSIONS:
        safe_ext = "jpg"
    key = f"photos/{uuid.uuid4().hex}.{safe_ext}"
    path = _ROOT / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return key


def read(key: str) -> bytes:
    return (_ROOT / key).read_bytes()


def delete(key: str) -> None:
    try:
        (_ROOT / key).unlink()
    except FileNotFoundError:
        pass


def path_for(key: str) -> Path:
    return _ROOT / key
