# MITA-5 implementation plan: backend skeleton (FastAPI, numbered Alembic migrations, auto-migrate entrypoint)

## Goal

`backend/` holds a FastAPI app that answers `GET /api/health` and an image that applies every Alembic migration when its container starts. If a migration fails, the container does not serve. Every check gets its own throwaway TimescaleDB and pgvector database through `megoocolab.toml`.

## Architecture

`app/main.py` builds the app in `create_app()`. Every route hangs from one `APIRouter(prefix="/api")`. Settings come from environment variables only (`app/core/config.py`). The async SQLAlchemy engine and sessions are in `app/core/db.py`. Alembic's async `env.py` takes the URL from those settings. The image's `docker-entrypoint.sh` runs `alembic upgrade head` under `set -e` and then `exec`s Uvicorn. `megoocolab.toml` declares three service sets on `tools/test-services/`: `test` for pytest, `migrate` for the scratch database, and `image` for the built image with its own database.

## Facts this plan relies on

- The repository today: `backend/`, `caddy/`, `executor/`, `frontend/`, `gateway/`, `tools/release/` and `workers/*/` each hold only `.gitkeep`. There is no `.gitignore`, no `.gitattributes`, no `megoocolab.toml`, no Compose file and no Makefile. `VERSION` is `0.1.0`. `AGENTS.md` has the sections Checks, Migrations and Safety, which this task rewrites.
- The runner's `services run` uses `docker compose … up -d --build --wait`. So when the command starts, every container with a healthcheck is already healthy, and the image set has already built the backend image under `${BACKEND_IMAGE}`. Afterwards the runner removes the containers, the network and the built images. It never reads a `.env` file.
- **Step 1 is there because the runner asked for it, not because the design did.** The runner asks every repository whose checks need a container to make "Add megoocolab.toml" its first step.
- Commands run from `backend/` unless a step says otherwise. `megoocolab-runner` finds `megoocolab.toml` in a parent folder.
- Commit subjects follow `AGENTS.md`: `type(area): plain sentence`. The body says why. Every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never write anything under `docs/`.
- Test names read as sentences.

## File map

| Path | Step | Responsibility |
|---|---|---|
| `megoocolab.toml` | 1, 6 | The `test` and `migrate` sets (step 1) and the `image` set (step 6) |
| `tools/test-services/docker-compose.yml` | 1 | `db`: `timescale/timescaledb-ha:pg18`, port `DB_PORT`, TCP healthcheck, no volume |
| `tools/test-services/docker-compose.image.yml` | 6 | `backend` built from `../../backend`, port `API_PORT`, healthcheck on `/api/health` |
| `AGENTS.md` | 1, 5, 6 | Safety and the first half of the Backend check (1), Migrations (5), the container tests on the Backend line (6) |
| `.gitignore` | 2 | `.venv/`, `__pycache__/`, `.pytest_cache/`, `.env` |
| `.gitattributes` | 2 | `*.sh text eol=lf` |
| `backend/.gitkeep` | 2 | deleted |
| `backend/pyproject.toml`, `backend/uv.lock`, `backend/.python-version` | 2 | The project at version 0.1.0, its dependencies and pytest settings |
| `backend/app/__init__.py`, `backend/app/core/__init__.py` | 2 | Empty package markers |
| `backend/app/core/config.py` | 2 | `Settings`, `Settings.alembic_url()`, `get_settings()` |
| `backend/tests/conftest.py` | 2 | Points the app at the test database. A `-m docker` run collects only the container tests |
| `backend/tests/test_settings.py` | 2 | Settings tests |
| `backend/app/main.py` | 3 | `create_app()`, `app`, the `/api` router, `GET /api/health` |
| `backend/tests/test_health.py` | 3 | HTTP tests |
| `backend/app/core/db.py` | 4 | `Base`, `engine`, `SessionLocal`, `get_session`, `DbSession` |
| `backend/tests/test_db.py` | 4 | Session tests against the test database |
| `backend/alembic.ini`, `backend/migrations/env.py`, `backend/migrations/script.py.mako` | 5 | Alembic setup: numbered file template, async env |
| `backend/migrations/versions/0001_initial.py` | 5 | Enables `timescaledb` and `vector`, and goes down again |
| `backend/app/models.py` | 5 | Imports every model module, so that Alembic sees all tables. Empty for now |
| `backend/tests/test_migrations.py` | 5 | Upgrade, downgrade, the file template and the numbering rule |
| `backend/.dockerignore`, `backend/Dockerfile`, `backend/docker-entrypoint.sh` | 6 | The image and its migrate-then-serve entrypoint |
| `backend/tests/test_container.py` | 6, 7 | Container start-up tests, marked `docker` |
| `backend/tests/fixtures/9999_fails.py` | 7 | A revision whose `upgrade` raises, mounted into a one-off container |

---

## Code listings

The steps refer to these listings by name.

### L1 `megoocolab.toml` (step 1: only `test` and `migrate`)

```toml
[services.test]
description = "PostgreSQL with TimescaleDB and pgvector for backend pytest"
compose = ["tools/test-services/docker-compose.yml"]
ports = ["DB_PORT"]

[services.test.env]
DB_NAME = "megooitadmin_test"
TEST_DATABASE_URL = "postgresql+asyncpg://megooitadmin:megooitadmin@localhost:${DB_PORT}/megooitadmin_test"

[services.migrate]
description = "The empty scratch database megooitadmin_migrate, for generating and trying migrations"
compose = ["tools/test-services/docker-compose.yml"]
ports = ["DB_PORT"]

[services.migrate.env]
DB_NAME = "megooitadmin_migrate"
DATABASE_URL = "postgresql+asyncpg://megooitadmin:megooitadmin@localhost:${DB_PORT}/megooitadmin_migrate"
```

Step 6 appends:

```toml

[services.image]
description = "The backend image built from this checkout, started with its own database, for pytest -m docker"
compose = ["tools/test-services/docker-compose.yml", "tools/test-services/docker-compose.image.yml"]
ports = ["DB_PORT", "API_PORT"]

[services.image.env]
DB_NAME = "megooitadmin"
BACKEND_IMAGE = "megooitadmin-backend:${MEGOO_SERVICES_PROJECT}"
BACKEND_NETWORK = "${MEGOO_SERVICES_PROJECT}_default"
BACKEND_URL = "http://localhost:${API_PORT}"
IMAGE_DATABASE_URL = "postgresql+asyncpg://megooitadmin:megooitadmin@localhost:${DB_PORT}/megooitadmin"
```

### L2 `tools/test-services/docker-compose.yml`

```yaml
# Test services for megoocolab-runner (see megoocolab.toml). The credentials are throwaway test values.
services:
  db:
    image: timescale/timescaledb-ha:pg18
    environment:
      POSTGRES_USER: megooitadmin
      POSTGRES_PASSWORD: megooitadmin
      POSTGRES_DB: ${DB_NAME}
    ports:
      - "127.0.0.1:${DB_PORT}:5432"
    healthcheck:
      # TCP, not the socket: on first start the image's temporary server listens only on its socket.
      test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U megooitadmin -d ${DB_NAME}"]
      interval: 2s
      timeout: 5s
      retries: 60
```

### L3 `AGENTS.md` texts

Step 1 replaces the Safety Docker bullet with:

```markdown
- Docker: start containers for checks only with `megoocolab-runner services run`. It gives this worktree its own
  `megoo-…` containers and removes them when the command ends. Apart from those, use only the `megooitadmin-dev`
  and `megooitadmin-e2e` Compose projects. Never stop, remove or change any other container. A `megooitadmin`
  project and its `megooitadmin-*` containers are the owner's real instance.
```

Step 1 replaces the Backend check bullet with:

```markdown
- **Backend** (`backend/`): `megoocolab-runner services run test -- uv run pytest`.
```

Step 6 replaces it with the final text:

```markdown
- **Backend** (`backend/`): `megoocolab-runner services run test -- uv run pytest`, then the container start-up
  tests: `megoocolab-runner services run image -- uv run pytest -m docker`.
```

Step 5 replaces the whole body of `## Migrations` with:

```markdown
- Alembic revisions are numbered, not hashed: `0001_initial.py`, `0002_add_users.py`.
- Generate and try migrations only on the scratch database `megooitadmin_migrate`, never on the dev database and
  never inside a running container. The `migrate` service set starts that database, empty, in this worktree's own
  container, and removes it when the command ends. Run these from `backend/`.
- Create each migration with the next number:
  `megoocolab-runner services run migrate -- sh -c 'uv run alembic upgrade head && uv run alembic revision --autogenerate --rev-id 0002 -m "add users"'`
- Before committing, check that the migration goes down and up again:
  `megoocolab-runner services run migrate -- sh -c 'uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head'`
```

### L4 `backend/pyproject.toml` (the parts written by hand; `uv add` fills in the dependency lists)

```toml
[project]
name = "megooitadmin-backend"
version = "0.1.0"
description = "MegooITAdmin backend API"
requires-python = ">=3.12"
dependencies = []

[dependency-groups]
dev = []

[tool.uv]
package = false

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]
# The app is not installed as a package, so tests import it from here.
pythonpath = ["."]
markers = ["docker: checks the built backend image; run with megoocolab-runner services run image -- uv run pytest -m docker"]
addopts = "-m 'not docker'"
```

Then run `uv add fastapi 'uvicorn[standard]' 'sqlalchemy[asyncio]' asyncpg alembic pydantic-settings` and `uv add --dev pytest pytest-asyncio httpx`. `backend/.python-version` contains `3.12`.

### L5 `backend/app/core/config.py`

```python
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
```

### L6 `backend/tests/conftest.py`

```python
"""Points the app at the test database before any app module is imported.

`megoocolab-runner services run test -- uv run pytest` starts that database and sets TEST_DATABASE_URL.
"""

import os
from pathlib import Path

import pytest

RUN_TESTS = "megoocolab-runner services run test -- uv run pytest"


def _docker_only(config: pytest.Config) -> bool:
    return config.getoption("markexpr") == "docker"


def pytest_configure(config: pytest.Config) -> None:
    if _docker_only(config):
        return
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.exit(f"TEST_DATABASE_URL is not set. Run the suite as: {RUN_TESTS}", returncode=2)
    database = url.rsplit("/", 1)[-1].split("?", 1)[0]
    if not database.endswith("_test"):
        pytest.exit(f"Refusing to run against {database!r}: the test database name must end in _test.", returncode=2)
    os.environ["DATABASE_URL"] = url
    os.environ["DB_NULL_POOL"] = "true"


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    # The image set has no test database, so a `-m docker` run collects only the container tests.
    if _docker_only(config) and collection_path.is_file() and collection_path.name != "test_container.py":
        return True
    return None
```

### L7 `backend/tests/test_settings.py`

```python
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
```

### L8 `backend/app/main.py`

```python
from fastapi import APIRouter, FastAPI

from app.core.config import get_settings


def create_app() -> FastAPI:
    # Caddy forwards /api/* unchanged, and nothing is served outside /api, the docs included.
    app = FastAPI(
        title="MegooITAdmin",
        version=get_settings().app_version,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        swagger_ui_oauth2_redirect_url="/api/docs/oauth2-redirect",
        redoc_url=None,
    )
    # The parent of every route, so a feature cannot forget the prefix: include feature routers into it.
    api = APIRouter(prefix="/api")

    @api.get("/health")
    async def health() -> dict[str, str]:
        # Liveness only: the entrypoint migrated before Uvicorn started, so an answer means "migrated and serving".
        return {"status": "ok"}

    app.include_router(api)
    return app


app = create_app()
```

### L9 `backend/tests/test_health.py`

```python
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        yield client


async def test_api_health_answers_ok(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("path", ["/health", "/docs", "/openapi.json", "/redoc"])
async def test_nothing_is_served_outside_api(client, path):
    assert (await client.get(path)).status_code == 404


async def test_the_openapi_document_lists_api_health(client):
    response = await client.get("/api/openapi.json")
    assert response.status_code == 200
    assert "/api/health" in response.json()["paths"]
```

### L10 `backend/app/core/db.py`

```python
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def _engine_options() -> dict[str, Any]:
    if get_settings().db_null_pool:
        return {"poolclass": NullPool}
    return {"pool_pre_ping": True}


engine = create_async_engine(get_settings().database_url, **_engine_options())
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """One session per request: committed after the handler, rolled back if it raises."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


DbSession = Annotated[AsyncSession, Depends(get_session)]
```

### L11 `backend/tests/test_db.py`

```python
import pytest
from sqlalchemy import text

from app.core.db import SessionLocal, get_session

PROBE = "get_session_probe"


async def _probe_exists() -> bool:
    async with SessionLocal() as session:
        return (await session.execute(text(f"SELECT to_regclass('{PROBE}') IS NOT NULL"))).scalar_one()


@pytest.fixture(autouse=True)
async def no_probe_table():
    yield
    async with SessionLocal() as session:
        await session.execute(text(f"DROP TABLE IF EXISTS {PROBE}"))
        await session.commit()


async def test_a_session_runs_a_query_on_the_test_database():
    async with SessionLocal() as session:
        assert (await session.execute(text("SELECT 1"))).scalar_one() == 1


async def test_get_session_commits_after_the_handler():
    sessions = get_session()
    session = await anext(sessions)
    await session.execute(text(f"CREATE TABLE {PROBE} (id int)"))
    with pytest.raises(StopAsyncIteration):
        await anext(sessions)
    assert await _probe_exists()


async def test_get_session_rolls_back_when_the_handler_raises():
    sessions = get_session()
    session = await anext(sessions)
    await session.execute(text(f"CREATE TABLE {PROBE} (id int)"))
    with pytest.raises(RuntimeError):
        await sessions.athrow(RuntimeError("handler failed"))
    assert not await _probe_exists()
```

### L12 `backend/migrations/env.py`

```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.core.config import get_settings
from app.core.db import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

config.set_main_option("sqlalchemy.url", get_settings().alembic_url())
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    # NullPool: every Alembic command gets a fresh connection, which TimescaleDB wants for CREATE/DROP EXTENSION.
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

### L13 `backend/migrations/versions/0001_initial.py`

```python
"""initial: enable the timescaledb and vector extensions

Revision ID: 0001
Revises:
Create Date: (keep the date Alembic wrote)
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # IF NOT EXISTS: the database image may have created TimescaleDB already.
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")
    op.execute("DROP EXTENSION IF EXISTS timescaledb")
```

### L14 `backend/tests/test_migrations.py`

```python
import asyncio
import configparser
import re
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.core.db import SessionLocal

BACKEND = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND / "alembic.ini"
VERSIONS = BACKEND / "migrations" / "versions"
EXTENSIONS = {"timescaledb", "vector"}


def _config() -> Config:
    return Config(str(ALEMBIC_INI))


def _fetch(sql: str) -> list:
    # Alembic's env.py runs its own event loop, so these tests are sync and query through a short-lived one.
    async def run():
        async with SessionLocal() as session:
            return (await session.execute(text(sql))).all()

    return asyncio.run(run())


def _head() -> str:
    return ScriptDirectory.from_config(_config()).get_current_head()


def _extensions() -> set[str]:
    return {row[0] for row in _fetch("SELECT extname FROM pg_extension")}


@pytest.fixture(scope="session", autouse=True)
def migrated():
    command.upgrade(_config(), "head")


def test_upgrade_head_records_the_head_and_enables_the_extensions():
    assert [row[0] for row in _fetch("SELECT version_num FROM alembic_version")] == [_head()]
    assert EXTENSIONS <= _extensions()


def test_the_first_revision_goes_down_and_up_again():
    # Walk down to 0001, check its downgrade, and come back to head.
    command.downgrade(_config(), "0001")
    command.downgrade(_config(), "-1")
    assert not EXTENSIONS & _extensions()
    command.upgrade(_config(), "head")
    assert EXTENSIONS <= _extensions()
    assert [row[0] for row in _fetch("SELECT version_num FROM alembic_version")] == [_head()]


def test_revision_files_are_named_by_number_and_slug():
    parser = configparser.RawConfigParser()
    parser.read(ALEMBIC_INI)
    assert parser.get("alembic", "file_template") == "%%(rev)s_%%(slug)s"


def test_revisions_are_numbered_consecutively_from_0001():
    script = ScriptDirectory.from_config(_config())
    files = sorted(VERSIONS.glob("*.py"))
    assert files, "migrations/versions holds no revision"
    for position, path in enumerate(files, start=1):
        number = f"{position:04d}"
        assert re.fullmatch(rf"{number}_[a-z0-9_]+\.py", path.name), f"{path.name} should be {number}_<slug>.py"
        revision = script.get_revision(number)
        assert revision is not None, f"{path.name}: revision should be {number!r}"
        assert Path(revision.path).name == path.name
        expected_down = None if position == 1 else f"{position - 1:04d}"
        assert revision.down_revision == expected_down, f"{path.name}: down_revision should be {expected_down!r}"
    assert script.get_heads() == [f"{len(files):04d}"]
```

### L15 `backend/docker-entrypoint.sh` (mode 0755)

```sh
#!/bin/sh
# Applies every pending migration, then starts the server. Run one backend replica: two that start
# together would migrate at the same time.
set -e

echo "Applying database migrations..."
alembic upgrade head

exec "$@"
```

### L16 `backend/Dockerfile`

```dockerfile
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app

# The release build passes the version; a local build stays "dev".
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh && useradd --system --uid 10001 megooitadmin
USER megooitadmin
EXPOSE 8000
# The entrypoint migrates first; if a migration fails, Uvicorn never starts.
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
```

`backend/.dockerignore`:

```
.venv
**/__pycache__
.pytest_cache
tests
.env
```

### L17 `tools/test-services/docker-compose.image.yml`

```yaml
# The backend image built from this checkout, on the db of docker-compose.yml (the image set in megoocolab.toml).
services:
  backend:
    build: ../../backend
    image: ${BACKEND_IMAGE}
    environment:
      DATABASE_URL: postgresql+asyncpg://megooitadmin:megooitadmin@db:5432/${DB_NAME}
    depends_on:
      db:
        condition: service_healthy
    ports:
      - "127.0.0.1:${API_PORT}:8000"
    healthcheck:
      # The image has no curl.
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"]
      interval: 2s
      timeout: 5s
      retries: 60
```

### L18 `backend/tests/test_container.py` (step 6: the first three tests; step 7 adds the last)

```python
"""Start-up tests of the built image. They start nothing themselves: the image service set has built the image and
started it with its own database. They do not import the app or run Alembic."""

import asyncio
import os
import subprocess
from pathlib import Path

import asyncpg
import httpx
import pytest

pytestmark = pytest.mark.docker

TESTS = Path(__file__).resolve().parent
VERSIONS = TESTS.parent / "migrations" / "versions"
FAILING_REVISION = TESTS / "fixtures" / "9999_fails.py"


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"{name} is not set. Run: megoocolab-runner services run image -- uv run pytest -m docker")
    return value


def _head() -> str:
    return max(path.name[:4] for path in VERSIONS.glob("[0-9][0-9][0-9][0-9]_*.py"))


async def _fetch(sql: str) -> list[asyncpg.Record]:
    url = _env("IMAGE_DATABASE_URL").replace("postgresql+asyncpg://", "postgresql://", 1)
    connection = await asyncpg.connect(url)
    try:
        return await connection.fetch(sql)
    finally:
        await connection.close()


async def test_the_container_migrates_on_start():
    versions = [row["version_num"] for row in await _fetch("SELECT version_num FROM alembic_version")]
    assert versions == [_head()]
    extensions = {row["extname"] for row in await _fetch("SELECT extname FROM pg_extension")}
    assert {"timescaledb", "vector"} <= extensions


async def test_api_health_responds():
    async with httpx.AsyncClient(base_url=_env("BACKEND_URL")) as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_the_proxy_headers_are_honoured():
    async with httpx.AsyncClient(base_url=_env("BACKEND_URL")) as client:
        response = await client.get("/api/health/", headers={"X-Forwarded-Proto": "https"})
    assert response.status_code == 307
    assert response.headers["location"].startswith("https://")
```

Step 7 appends:

```python


def test_it_refuses_to_serve_when_a_migration_fails():
    result = subprocess.run(
        [
            "docker", "run", "--rm",
            "--network", _env("BACKEND_NETWORK"),
            "-e", f"DATABASE_URL=postgresql+asyncpg://megooitadmin:megooitadmin@db:5432/{_env('DB_NAME')}",
            "-v", f"{FAILING_REVISION}:/app/migrations/versions/9999_fails.py:ro",
            _env("BACKEND_IMAGE"),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "Applying database migrations..." in output
    assert "9999_fails: this migration fails on purpose" in output
    assert "Uvicorn running" not in output
    versions = [row["version_num"] for row in asyncio.run(_fetch("SELECT version_num FROM alembic_version"))]
    assert versions == [_head()]
```

### L19 `backend/tests/fixtures/9999_fails.py`

```python
"""A revision that always fails. tests/test_container.py mounts it into migrations/versions/ of a one-off container,
to prove that the container refuses to serve when a migration fails. Never copy it into migrations/versions/."""

from pathlib import Path

from alembic import op  # noqa: F401

revision = "9999"
# The real head: the highest-numbered revision beside this file once it is mounted.
down_revision = max(
    path.name[:4] for path in Path(__file__).parent.glob("[0-9][0-9][0-9][0-9]_*.py") if path.name != "9999_fails.py"
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    raise RuntimeError("9999_fails: this migration fails on purpose")


def downgrade() -> None:
    pass
```

---

## Steps

### 1. Add megoocolab.toml with the test and migrate service sets (asked for by the runner)

The runner asked for this step, not the design. It gives every check its own database container.

- Create `megoocolab.toml` at the repository root with only the `test` and `migrate` sets from **L1**. The `image` set comes in step 6, together with the Compose file it needs.
- Create `tools/test-services/docker-compose.yml` exactly as **L2**.
- In `AGENTS.md`, replace the Safety Docker bullet and the Backend line under Checks with the step-1 texts of **L3**. Leave Migrations as it is (step 5 rewrites it).
- Nothing to unit-test yet. Prove each set from the repository root. Each command must print the two lines `timescaledb` and `vector`, in either order, and exit 0:
  - `megoocolab-runner services run test -- sh -c 'docker compose -p "$MEGOO_SERVICES_PROJECT" -f tools/test-services/docker-compose.yml exec -T -e PGPASSWORD=megooitadmin db psql -h 127.0.0.1 -U megooitadmin -d "$DB_NAME" -Atc "select name from pg_available_extensions" | grep -Ex "timescaledb|vector"'`
  - The same command with `migrate` in place of `test`.
- Afterwards, `docker ps -a --filter name=megoo-` shows no container of this worktree.
- If `timescale/timescaledb-ha:pg18` cannot be pulled, stop and ask. Do not pick another image.
- Commit: `chore(checks): every check gets its own TimescaleDB database through megoocolab.toml`.

### 2. Create the backend project with environment-only settings

- Delete `backend/.gitkeep`. Create the root `.gitignore` (`.venv/`, `__pycache__/`, `.pytest_cache/`, `.env`) and `.gitattributes` (`*.sh text eol=lf`).
- Write `backend/pyproject.toml` as **L4** and `backend/.python-version`, then run the two `uv add` commands from **L4** in `backend/`. This creates `uv.lock`, which gets committed.
- Create the empty files `backend/app/__init__.py` and `backend/app/core/__init__.py`.
- Test first: write `backend/tests/conftest.py` (**L6**) and `backend/tests/test_settings.py` (**L7**). Run `megoocolab-runner services run test -- uv run pytest` from `backend/`. Expected failure: `ModuleNotFoundError: No module named 'app.core.config'`.
- Implement `backend/app/core/config.py` as **L5**. Run the same command again. Expected: 4 passed.
- Also check the following:
  - `uv run pytest` without the runner exits with code 2, and its message names `megoocolab-runner services run test -- uv run pytest`.
  - `TEST_DATABASE_URL=postgresql+asyncpg://u:p@localhost/megooitadmin uv run pytest` exits with the "must end in _test" message.
  - `grep -A1 'name = "megooitadmin-backend"' uv.lock` shows `version = "0.1.0"`.
  - `git check-attr eol -- backend/docker-entrypoint.sh` prints `eol: lf`.
- Commit: `feat(backend): the backend project reads its settings from the environment only`.

### 3. Serve GET /api/health from a FastAPI app under /api

- Test first: write `backend/tests/test_health.py` as **L9**. Run `megoocolab-runner services run test -- uv run pytest tests/test_health.py`. Expected failure: `ModuleNotFoundError: No module named 'app.main'`.
- Implement `backend/app/main.py` as **L8**. It has `create_app()`, a module-level `app`, and one `APIRouter(prefix="/api")` that later features include their routers into. `/api/health` is liveness only and makes no database query. The OpenAPI document is at `/api/openapi.json` and the docs are at `/api/docs`. ReDoc is off, so nothing is served outside `/api`.
- Run `megoocolab-runner services run test -- uv run pytest`. Expected: every test passes, 6 of them new.
- Commit: `feat(backend): GET /api/health answers ok, and nothing is served outside /api`.

### 4. Add the async SQLAlchemy engine and request sessions

- Test first: write `backend/tests/test_db.py` as **L11**. Run `megoocolab-runner services run test -- uv run pytest tests/test_db.py`. Expected failure: `ModuleNotFoundError: No module named 'app.core.db'`.
- Implement `backend/app/core/db.py` as **L10**:
  - `Base` (a `DeclarativeBase`), `engine` and `SessionLocal`, built from `get_settings()`. With `DB_NULL_POOL=true` the engine uses `NullPool`.
  - `get_session` commits after the handler and rolls back if it raises. `DbSession` is its `Annotated` dependency.
  - No route uses it yet.
- Run `megoocolab-runner services run test -- uv run pytest`. Expected: every test passes, 3 of them new.
- Commit: `feat(backend): the backend has an async database engine and request sessions`.

### 5. Add numbered Alembic migrations with 0001_initial

- In `backend/`, run `uv run alembic init -t async migrations`, then:
  - Delete `migrations/README`.
  - In `alembic.ini`: `script_location = %(here)s/migrations` and `prepend_sys_path = .`. Uncomment the line and set `file_template = %%(rev)s_%%(slug)s`. Delete the `sqlalchemy.url` line and put the comment `# env.py sets sqlalchemy.url from DATABASE_URL` in its place.
  - Keep the generated `script.py.mako`.
  - Replace `migrations/env.py` with **L12**.
  - Create `backend/app/models.py`. Its docstring says that every model module is imported here, so that Alembic sees all tables, and that there are none yet (MITA-7 adds the first).
- Test first: write `backend/tests/test_migrations.py` as **L14**. Run `megoocolab-runner services run test -- uv run pytest tests/test_migrations.py`. Expected failure: the numbering test reports that `migrations/versions` holds no revision. The upgrade tests fail with "Can't locate revision 0001" or find no extensions.
- Run `uv run alembic revision --rev-id 0001 -m initial`. It creates `migrations/versions/0001_initial.py`. Fill it in as **L13**.
- Run `megoocolab-runner services run test -- uv run pytest`. Expected: everything passes.
- In `AGENTS.md`, replace the body of `## Migrations` with **L3**'s Migrations text.
- Run both `migrate` commands from the new Migrations section by hand, exactly as written. Use the down-and-up check: `megoocolab-runner services run migrate -- sh -c 'uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head'`. Expected: exit 0. Do not commit any revision that the autogenerate example would create. Run it with `--rev-id 0002 -m "probe"`, check that it writes `0002_probe.py`, then delete that file.
- If TimescaleDB refuses `DROP EXTENSION` inside Alembic's connection, stop and ask. Do not weaken the downgrade.
- Commit: `feat(backend): numbered Alembic migrations, and 0001_initial enables timescaledb and vector`.

### 6. Build the backend image that migrates on start, with container tests

- Create `backend/docker-entrypoint.sh` (**L15**, then `chmod 0755`; `git ls-files -s` should show mode 100755), `backend/Dockerfile` and `backend/.dockerignore` (**L16**), and `tools/test-services/docker-compose.image.yml` (**L17**).
- Append the `image` set from **L1** to `megoocolab.toml`.
- Test first: write `backend/tests/test_container.py` with the three tests of **L18**. The image and test files can be written in either order. Before the Dockerfile exists, `megoocolab-runner services run image -- uv run pytest -m docker` fails to start (exit 125: there is no Dockerfile to build).
- Run `megoocolab-runner services run image -- uv run pytest -m docker` from `backend/`. Expected: 3 passed. The container migrated on start, `/api/health` answered 200, and the `X-Forwarded-Proto: https` request was redirected to an `https://` URL.
- Run `megoocolab-runner services run test -- uv run pytest`. Expected: it still passes, and the container tests are deselected.
- In `AGENTS.md`, set the Backend check line to **L3**'s final text.
- Commit: `feat(backend): the backend image applies its migrations before it serves`.

### 7. Prove that the container refuses to serve when a migration fails

- Create `backend/tests/fixtures/9999_fails.py` as **L19**.
- Test first: append the fourth test of **L18** to `backend/tests/test_container.py`, before the fixture exists. Run `megoocolab-runner services run image -- uv run pytest -m docker`. Expected failure: the new test fails, because Docker mounts a missing path as a directory and the output lacks the "fails on purpose" message.
- With the fixture in place, run the same command. Expected: 4 passed. The one-off container exits non-zero, its output has "Applying database migrations..." and the fixture's error but no "Uvicorn running", and the database is still at the head.
- `megoocolab-runner services run test -- uv run pytest` still passes. The numbering test ignores `tests/fixtures/`.
- Commit: `test(backend): the backend container exits instead of serving when a migration fails`.

## Final verification

From `backend/`:

1. `megoocolab-runner services run test -- uv run pytest`: all tests pass.
2. `megoocolab-runner services run image -- uv run pytest -m docker`: 4 passed.
3. `megoocolab-runner services run migrate -- sh -c 'uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head'`: exit 0.
4. `git ls-files backend` no longer lists `.gitkeep`. `grep -A1 'name = "megooitadmin-backend"' uv.lock` shows `0.1.0`. `git check-attr eol -- backend/docker-entrypoint.sh` prints `lf`.
5. `docker ps -a --filter name=megoo-` lists none of this worktree's containers.

Checks skipped, and said so in the finish report: Frontend (`frontend/` holds only `.gitkeep`), Security suites and Release tools (there is no Makefile and no `tools/release/versions.py` yet).
