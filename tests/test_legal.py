import httpx
import pytest

from app.main import app


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://x")


@pytest.mark.asyncio
@pytest.mark.parametrize("path,needle", [("/privacy", "Privacy Policy"), ("/terms", "Terms of Service")])
async def test_legal_pages_public(path, needle):
    # Must be reachable WITHOUT a session (Google consent screen + users).
    async with _client() as c:
        resp = await c.get(path, follow_redirects=False)
    assert resp.status_code == 200
    assert needle in resp.text
