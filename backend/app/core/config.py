from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings from environment variables only. No .env file is read, so a stray file can never change a test
    or a container."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    # Required: a container without a database must stop, not fall back to one.
    database_url: str
    # The owner's URL, for Alembic and the entrypoint's password step only. The server never gets it.
    database_owner_url: str | None = None
    app_version: str = "dev"
    # The tests set it, so connections are not shared between event loops.
    db_null_pool: bool = False

    def alembic_url(self) -> str:
        """The owner's URL for Alembic's config, where % starts an interpolation. Never DATABASE_URL: the API role
        cannot migrate."""
        if not self.database_owner_url:
            raise RuntimeError("DATABASE_OWNER_URL is not set. Alembic connects as the owner of the tables.")
        return self.database_owner_url.replace("%", "%%")


@lru_cache
def get_settings() -> Settings:
    return Settings()
