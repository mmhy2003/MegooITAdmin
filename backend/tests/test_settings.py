import pytest
from pydantic import ValidationError

from app.core.config import Settings

URL = "postgresql+asyncpg://user:secret@localhost:5432/example_test"


def test_database_url_is_required(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings()


def test_a_dotenv_file_is_never_read(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    (tmp_path / ".env").write_text(f"DATABASE_URL={URL}\n")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValidationError):
        Settings()


def test_app_version_defaults_to_dev(monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)
    assert Settings(database_url=URL).app_version == "dev"


def test_alembic_url_doubles_percent_signs():
    settings = Settings(database_url="postgresql+asyncpg://user:p%40ss@localhost/example_test")
    assert settings.alembic_url() == "postgresql+asyncpg://user:p%%40ss@localhost/example_test"
