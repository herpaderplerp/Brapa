import pytest
from pydantic import ValidationError

from app.config import Settings


def test_session_secret_rejects_known_development_value():
    with pytest.raises(ValidationError, match="known development value"):
        Settings(session_secret="change-me-dev-only", _env_file=None)


def test_session_secret_is_required_when_env_is_missing(monkeypatch):
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    with pytest.raises(ValidationError, match="session_secret"):
        Settings(_env_file=None)


def test_session_cookies_are_secure_by_default(monkeypatch):
    monkeypatch.delenv("SESSION_HTTPS_ONLY", raising=False)
    settings = Settings(session_secret="x" * 32, _env_file=None)
    assert settings.session_https_only is True
