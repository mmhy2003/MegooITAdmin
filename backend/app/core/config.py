import re
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings from environment variables only. No .env file is read, so a stray file can never change a test
    or a container."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    # Required: a container without a database must stop, not fall back to one.
    database_url: str
    # The owner's URL, for Alembic and the entrypoint's password step only. The server never gets it.
    database_owner_url: str | None = None
    # Valkey, for live metric fan-out. Optional: nothing at start-up needs it, and the image check runs without one.
    valkey_url: str | None = None
    app_version: str = "dev"
    # The tests set it, so connections are not shared between event loops.
    db_null_pool: bool = False
    # The collector role's URL, for the entrypoint's password step only (DATABASE_COLLECTOR_URL). The API never gets it.
    database_collector_url: str | None = None
    # Touched by the collector after each read of servers; its healthcheck reads its age.
    collector_heartbeat_file: str = "/tmp/megooitadmin-collector.heartbeat"
    # It encrypts the authenticator secrets, so a lost key locks every account out of its second factor. The API
    # refuses to start without it (create_app and the entrypoint). The collector never gets it.
    auth_secret_key: str | None = Field(default=None, repr=False)
    session_idle_minutes: int = 60
    session_absolute_minutes: int = 720
    # /api/docs and /api/openapi.json are served only when this is on.
    api_docs: bool = False
    # The platform's SSH private key: one Ed25519 key, made by the entrypoint at the first start (Phase 3 moves it
    # into the vault).
    ssh_key_file: str = "/var/lib/megooitadmin/ssh/id_ed25519"
    # The backend's sender task, which delivers alert messages by email, to webhooks and to Telegram. The tests turn
    # it off.
    notification_sender: bool = True
    # Lets a webhook use http://. On in the dev, e2e and stack stacks only, whose sinks have no TLS.
    webhook_allow_http: bool = False

    @field_validator("auth_secret_key")
    @classmethod
    def _hex_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            raise ValueError(
                "AUTH_SECRET_KEY must be 64 hexadecimal characters (32 bytes). make up writes one into .env"
            )
        return value.lower()

    def auth_key(self) -> bytes:
        if self.auth_secret_key is None:
            raise RuntimeError(
                "AUTH_SECRET_KEY is not set. It encrypts the authenticator secrets: make up writes one into .env"
            )
        return bytes.fromhex(self.auth_secret_key)

    def alembic_url(self) -> str:
        """The owner's URL for Alembic's config, where % starts an interpolation. Never DATABASE_URL: the API role
        cannot migrate."""
        if not self.database_owner_url:
            raise RuntimeError("DATABASE_OWNER_URL is not set. Alembic connects as the owner of the tables.")
        return self.database_owner_url.replace("%", "%%")


@lru_cache
def get_settings() -> Settings:
    return Settings()
