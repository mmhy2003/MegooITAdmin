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


def test_alembic_url_is_the_owners_url_with_percent_signs_doubled():
    settings = Settings(
        database_url=URL, database_owner_url="postgresql+asyncpg://owner:p%40ss@localhost/example_test"
    )
    assert settings.alembic_url() == "postgresql+asyncpg://owner:p%%40ss@localhost/example_test"


def test_alembic_url_without_the_owners_url_names_the_variable(monkeypatch):
    monkeypatch.delenv("DATABASE_OWNER_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_OWNER_URL"):
        Settings(database_url=URL).alembic_url()


TEST_KEY = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"


def test_auth_secret_key_is_required(monkeypatch):
    monkeypatch.delenv("AUTH_SECRET_KEY", raising=False)
    with pytest.raises(ValidationError, match="auth_secret_key"):
        Settings(database_url=URL)


@pytest.mark.parametrize("key", ["abc", "zz" * 32, "00" * 33])
def test_auth_secret_key_must_be_64_hex_characters(key):
    with pytest.raises(ValidationError, match="AUTH_SECRET_KEY must be 64 hexadecimal characters"):
        Settings(database_url=URL, auth_secret_key=key)


def test_auth_key_is_32_bytes_and_upper_case_is_accepted():
    settings = Settings(database_url=URL, auth_secret_key=TEST_KEY.upper())
    assert settings.auth_key() == bytes(range(32))


def test_session_and_docs_settings_have_their_defaults(monkeypatch):
    for name in ("SESSION_IDLE_MINUTES", "SESSION_ABSOLUTE_MINUTES", "API_DOCS"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(database_url=URL)
    assert (settings.session_idle_minutes, settings.session_absolute_minutes, settings.api_docs) == (60, 720, False)


def test_session_settings_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("SESSION_IDLE_MINUTES", "15")
    monkeypatch.setenv("SESSION_ABSOLUTE_MINUTES", "480")
    monkeypatch.setenv("API_DOCS", "true")
    settings = Settings(database_url=URL)
    assert (settings.session_idle_minutes, settings.session_absolute_minutes, settings.api_docs) == (15, 480, True)


def test_the_key_is_not_in_the_repr():
    settings = Settings(database_url=URL, auth_secret_key=TEST_KEY)
    assert TEST_KEY not in repr(settings)
    assert "auth_secret_key" not in repr(settings)


def test_ssh_key_file_has_its_default(monkeypatch):
    monkeypatch.delenv("SSH_KEY_FILE", raising=False)
    settings = Settings(database_url=URL)
    assert settings.ssh_key_file == "/var/lib/megooitadmin/ssh/id_ed25519"
