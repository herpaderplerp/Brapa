from authlib.integrations.starlette_client import OAuth

from app.config import settings

# Provider-agnostic registry. Every provider with credentials in config is
# registered here; adding a provider = config + env vars, no code change.
oauth = OAuth()
for _name, _conf in settings.oauth_providers.items():
    oauth.register(name=_name, **_conf)


def enabled_providers() -> list[str]:
    return list(settings.oauth_providers.keys())


def is_enabled(provider: str) -> bool:
    return provider in settings.oauth_providers
