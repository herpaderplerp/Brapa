"""Tests for OAuth callback logic and user/session lifecycle."""
from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import select

from app.auth.deps import require_login
from app.db import engine as global_engine
from app.main import app
from app.models.user import OAuthAccount, User
from app.routers.auth import _find_or_create_user


def _client():
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:8000"
    )


# ---------------------------------------------------------------------------
# _find_or_create_user — service-level unit tests (no HTTP)
# ---------------------------------------------------------------------------


async def test_creates_new_user_and_oauth_account(db):
    """A brand-new OAuth identity creates both a User and an OAuthAccount row."""
    sub = uuid.uuid4().hex
    user = await _find_or_create_user(
        db, "google", sub, email="new@example.com", name="New Rider", picture=None
    )
    await db.flush()

    assert user.id is not None
    assert user.email == "new@example.com"

    acct = (
        await db.execute(
            select(OAuthAccount).where(
                OAuthAccount.provider == "google",
                OAuthAccount.provider_account_id == sub,
            )
        )
    ).scalar_one_or_none()
    assert acct is not None
    assert acct.user_id == user.id


async def test_repeated_login_returns_same_user(db):
    """Logging in with the same provider + sub returns the existing user without duplication."""
    sub = uuid.uuid4().hex
    first = await _find_or_create_user(
        db, "google", sub, email="u@example.com", name=None, picture=None
    )
    await db.flush()

    second = await _find_or_create_user(
        db, "google", sub, email="u@example.com", name=None, picture=None
    )
    assert first.id == second.id

    # Only one OAuthAccount row should exist.
    accounts = (
        await db.execute(
            select(OAuthAccount).where(OAuthAccount.provider_account_id == sub)
        )
    ).scalars().all()
    assert len(accounts) == 1


async def test_links_new_oauth_to_existing_email_user(db):
    """A first-time OAuth login whose email matches an existing user links to that user."""
    existing = User(email="preexisting@example.com", display_name="Pre-existing")
    db.add(existing)
    await db.flush()

    sub = uuid.uuid4().hex
    linked = await _find_or_create_user(
        db, "google", sub, email="preexisting@example.com", name="Pre-existing", picture=None
    )
    await db.flush()

    assert linked.id == existing.id


async def test_creates_user_with_no_email(db):
    """An OAuth account that provides no email still creates a valid user."""
    sub = uuid.uuid4().hex
    user = await _find_or_create_user(
        db, "google", sub, email=None, name=None, picture=None
    )
    await db.flush()

    assert user.id is not None
    assert user.email is None


async def test_different_providers_same_email_creates_separate_accounts(db):
    """Two different providers with the same email both link to the same user."""
    email = f"{uuid.uuid4().hex}@example.com"
    sub_a = uuid.uuid4().hex
    sub_b = uuid.uuid4().hex

    user_a = await _find_or_create_user(db, "google", sub_a, email=email, name=None, picture=None)
    await db.flush()
    user_b = await _find_or_create_user(db, "github", sub_b, email=email, name=None, picture=None)
    await db.flush()

    assert user_a.id == user_b.id


# ---------------------------------------------------------------------------
# User.is_onboarded property
# ---------------------------------------------------------------------------


async def test_is_onboarded_false_without_display_name(db):
    """A user without a display_name has not completed onboarding."""
    user = User(email="fresh@example.com")
    db.add(user)
    await db.flush()
    assert user.is_onboarded is False


async def test_is_onboarded_true_with_display_name(db):
    """A user with a display_name is considered onboarded."""
    user = User(email="ready@example.com", display_name="Ready Rider")
    db.add(user)
    await db.flush()
    assert user.is_onboarded is True


# ---------------------------------------------------------------------------
# Logout route
# ---------------------------------------------------------------------------


async def test_logout_redirects_to_root():
    """GET /logout redirects to / regardless of session state."""
    async with _client() as c:
        resp = await c.get("/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


async def test_unknown_provider_in_callback_returns_404():
    """Accessing the callback for a provider that isn't configured returns 404."""
    async with _client() as c:
        resp = await c.get("/auth/notarealid/callback", follow_redirects=False)
    assert resp.status_code == 404
