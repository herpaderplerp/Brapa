from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://brapa:brapa@db:5432/brapa"
    session_secret: str = "change-me-dev-only"
    base_url: str = "http://localhost:8000"

    google_client_id: str = ""
    google_client_secret: str = ""

    open_meteo_base: str = "https://archive-api.open-meteo.com/v1/archive"
    nominatim_base: str = "https://nominatim.openstreetmap.org"

    storage_dir: str = "/app/var/uploads"

    # Comma-separated email allowlist. Empty = open registration (anyone with a
    # working OAuth login). Non-empty = only these emails may sign in.
    allowed_emails: str = ""

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
