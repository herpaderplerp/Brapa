import httpx
import pytest

from app.main import app


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://localhost:8000")


@pytest.mark.asyncio
async def test_login_page_lists_google():
    async with _client() as c:
        resp = await c.get("/login")
    assert resp.status_code == 200
    assert "Continue with Google" in resp.text


@pytest.mark.asyncio
async def test_me_requires_login():
    async with _client() as c:
        resp = await c.get("/me", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


@pytest.mark.asyncio
async def test_login_google_redirects_to_provider():
    async with _client() as c:
        resp = await c.get("/login/google", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("https://accounts.google.com/")


@pytest.mark.asyncio
async def test_unknown_provider_404():
    async with _client() as c:
        resp = await c.get("/login/facebook", follow_redirects=False)
    assert resp.status_code == 404
