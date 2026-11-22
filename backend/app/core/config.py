from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings from environment variables only. No .env file is read, so a stray file can never change a test
    or a container."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    # Required: a container without a database must stop, not fall back to one.
    database_url: str
    app_version: str = "dev"
    # The tests set it, so connections are not shared between event loops.
    db_null_pool: bool = False

    def alembic_url(self) -> str:
        """The URL for Alembic's config, where % starts an interpolation."""
        return self.database_url.replace("%", "%%")


@lru_cache
def get_settings() -> Settings:
    return Settings()
