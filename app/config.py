from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


INSECURE_SESSION_SECRETS = {"change-me-dev-only", "dev", "secret", "password"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://brapa:brapa@db:5432/brapa"
    session_secret: str
    session_https_only: bool = True
    base_url: str = "http://localhost:8000"

    google_client_id: str = ""
    google_client_secret: str = ""

    open_meteo_base: str = "https://archive-api.open-meteo.com/v1/archive"
    nominatim_base: str = "https://nominatim.openstreetmap.org"

    storage_dir: str = "/app/var/uploads"

    # Comma-separated email allowlist. Empty = open registration (anyone with a
    # working OAuth login). Non-empty = only these emails may sign in.
    allowed_emails: str = ""

    @field_validator("session_secret")
    @classmethod
    def validate_session_secret(cls, value: str) -> str:
        secret = value.strip()
        if not secret:
            raise ValueError("SESSION_SECRET must be set to a deployment-specific random value")
        if secret in INSECURE_SESSION_SECRETS:
            raise ValueError("SESSION_SECRET must not use a known development value")
        if len(secret) < 32:
            raise ValueError("SESSION_SECRET must be at least 32 characters long")
        return secret

    @property
    def email_allowlist(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_emails.split(",") if e.strip()}

    def email_allowed(self, email: str | None) -> bool:
        allow = self.email_allowlist
        if not allow:
            return True  # open registration
        return bool(email) and email.lower() in allow

    @property
    def oauth_providers(self) -> dict[str, dict[str, str]]:
        """Config-driven provider registry. Add a provider here (+ env vars) and
        the generic /login/{provider} routes pick it up — no schema/route change.
        Only providers with credentials present are enabled."""
        registry: dict[str, dict[str, str]] = {}
        if self.google_client_id and self.google_client_secret:
            registry["google"] = {
                "client_id": self.google_client_id,
                "client_secret": self.google_client_secret,
                "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
                "client_kwargs": {"scope": "openid email profile"},
            }
        return registry


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
