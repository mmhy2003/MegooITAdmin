"""The async Valkey client. Valkey carries live metric samples (app.metrics.fanout)."""

from valkey.asyncio import Valkey, from_url

from app.core.config import Settings, get_settings


def valkey_client(settings: Settings | None = None) -> Valkey:
    """A new client on VALKEY_URL. An asyncio client belongs to one event loop, so it is never shared: the caller
    closes it with `await client.aclose()`."""
    settings = settings or get_settings()
    if not settings.valkey_url:
        raise RuntimeError("VALKEY_URL is not set. The backend reaches Valkey through it (valkey://valkey:6379/0).")
    return from_url(settings.valkey_url)
