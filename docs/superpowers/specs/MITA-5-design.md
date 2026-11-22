# MITA-5 design: backend skeleton (FastAPI, numbered Alembic migrations, auto-migrate entrypoint)

## Goal

After this task, `backend/` holds a FastAPI app that answers `GET /api/health`, and an image that applies all Alembic migrations when its container starts and refuses to serve if one fails. Coding agents get a throwaway PostgreSQL (TimescaleDB and pgvector) for every check through `megoocolab.toml`.

## What the repository looks like today

- `backend/` holds only `.gitkeep`. There is no Python code, no Compose file, no Makefile and no `megoocolab.toml`.
- `VERSION` is `0.1.0`. `AGENTS.md` already fixes the numbered-revision rule and the name of the scratch database (`megooitadmin_migrate`), and MITA-2 left the exact command lines to this task.
- `AGENTS.md` allows only the `megooitadmin-dev` and `megooitadmin-e2e` Compose projects. Neither exists yet (MITA-4).

## Decisions

Answers from the owner:

1. **The checks get their database from `megoocolab.toml` service sets, as in MegooColab.** Each worktree gets its own container on a free port, and the runner removes it when the check ends. Rejected: a database-only Compose file in the `megooitadmin-dev` project (parallel tasks would share one container, and MITA-4 would have to take the file over), and both together.
2. **`GET /api/health` is liveness only:** always `200 {"status": "ok"}`, with no database query. The entrypoint migrates before Uvicorn starts, so an answer already means "migrated and serving". Rejected: a `SELECT 1` with a 503 (a database outage would show as an unhealthy backend), and adding the version to the body.

Decisions I made (say so if you want them changed):

3. **Async SQLAlchemy with `asyncpg`, and Alembic's async `env.py`**, the same as MegooColab. The backend will hold WebSockets and SSH streams, so the database layer should not block. Rejected: sync SQLAlchemy with psycopg.
4. **The layout, Dockerfile and settings follow MegooColab's backend** (answer MC-Q7): `python:3.12-slim`, uv with a committed `uv.lock`, `app/core/config.py` and `app/core/db.py`, a non-root user in the image. The differences come from the PRD: migrations run in `docker-entrypoint.sh`, not in the app's lifespan, and revisions are numbered.
5. **Settings come from environment variables only.** No `.env` file is read, so a stray file can never change a test or a container. `DATABASE_URL` is required and has no default: there is no dev database to default to, and a missing value should stop the container.
6. **`0001_initial` goes down as well as up.** `upgrade` creates the two extensions with `IF NOT EXISTS` (the database image may have created TimescaleDB already). `downgrade` drops both with `IF EXISTS`. This keeps the rule "every migration goes down and up again" true from the first revision.
7. **The "done when" is proved by automated container tests**, not by hand: a third service set builds the image and starts it, and three tests check that it migrated, that it serves, and that it exits when a migration fails. Rejected: a manual check, which nobody repeats.
8. **A failing migration is simulated by mounting one extra revision** (`9999_fails.py`, whose `upgrade` raises) into a one-off container of the same image. Rejected: pointing the image at a plain PostgreSQL so `CREATE EXTENSION` fails (needs a second database image), and building a second image.
9. **The database image is `timescale/timescaledb-ha:pg18`** in the test services. MITA-4 uses the same image for the real stack. Changing the major version is free until `v0.1.0` is released.
10. **A test guards the numbering rule for every later migration:** file name `NNNN_slug.py`, `revision` equal to `NNNN`, numbers consecutive from `0001`, each `down_revision` the number before, and one head.
11. **Nothing guards against two replicas migrating at once.** The PRD says to run one replica and to move migrations to a one-off job if that ever changes. A comment in the entrypoint says so.
12. **No lint tool is added.** `AGENTS.md` lists only `uv run pytest` for the backend.

## Architecture

```text
megoocolab.toml                          new: service sets test, migrate, image
tools/test-services/
  docker-compose.yml                     new: db (TimescaleDB + pgvector), healthcheck, port from DB_PORT
  docker-compose.image.yml               new: backend built from ../../backend, port from API_PORT
.gitignore                               new: .venv/, __pycache__/, .pytest_cache/, .env
.gitattributes                           new: *.sh text eol=lf
AGENTS.md                                changed: Checks, Migrations, Safety
backend/
  .gitkeep                               deleted
  pyproject.toml, uv.lock, .python-version, .dockerignore
  Dockerfile
  docker-entrypoint.sh
  alembic.ini
  migrations/env.py, script.py.mako
  migrations/versions/0001_initial.py
  app/__init__.py
  app/main.py                            create_app(), app, the /api router, GET /api/health
  app/core/__init__.py
  app/core/config.py                     Settings, get_settings(), alembic_url()
  app/core/db.py                         Base, engine, SessionLocal, get_session, DbSession
  app/models.py                          imports every model module, so Alembic sees all tables (empty for now)
  tests/conftest.py
  tests/test_health.py, test_settings.py, test_db.py, test_migrations.py
  tests/test_container.py                marked "docker"
  tests/fixtures/9999_fails.py
```

How the pieces connect:

- **`app/main.py`** builds the app in `create_app()`. One `APIRouter(prefix="/api")` is the parent of every route, so a later feature cannot forget the prefix. Caddy (MITA-4) forwards `/api/*` unchanged. OpenAPI is at `/api/openapi.json` and the docs at `/api/docs`, as in MegooColab.
- **`app/core/config.py`** holds a pydantic-settings class, cached by `get_settings()`.
- **`app/core/db.py`** creates the async engine and `SessionLocal` from the settings. `get_session` yields a session, commits after the handler and rolls back on an error. No route uses it yet. MITA-7 adds the first model.
- **`migrations/env.py`** is Alembic's async template. It takes the URL from `get_settings().database_url`, uses `Base.metadata` as the target, sets `compare_type=True`, and connects with `NullPool`.
- **`docker-entrypoint.sh`** runs `alembic upgrade head`, then hands over to the image's command.
- **`megoocolab.toml`** declares three sets on the same Compose file. Each gives the command a URL to its own database.

## Data and interfaces

### HTTP

| Request | Response |
|---|---|
| `GET /api/health` | `200 {"status": "ok"}`. No login, no database query |
| `GET /health` | `404`. Nothing is served outside `/api` |

### Settings (environment variables)

| Variable | Type | Default | Use |
|---|---|---|---|
| `DATABASE_URL` | string | none, required | `postgresql+asyncpg://user:password@host:port/database`. Read by the app and by Alembic |
| `APP_VERSION` | string | `dev` | The FastAPI app's version. The image sets it from the build argument `APP_VERSION` |
| `DB_NULL_POOL` | bool | `false` | The tests set it, so connections are not shared between event loops |

### `backend/pyproject.toml`

- `name = "megooitadmin-backend"`, `version = "0.1.0"`, `requires-python = ">=3.12"`, not installed as a package (`[tool.uv] package = false`).
- Dependencies: `fastapi`, `uvicorn[standard]`, `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `pydantic-settings`. Dev group: `pytest`, `pytest-asyncio`, `httpx`.
- pytest: `asyncio_mode = "auto"`, a `docker` marker, and `addopts = "-m 'not docker'"`, so a plain `uv run pytest` leaves the container tests out.
- `uv.lock` is committed. Its own entry for the package carries `0.1.0`, which the release rules in `AGENTS.md` expect.

### Alembic

- `alembic.ini`: `script_location = %(here)s/migrations`, `prepend_sys_path = .`, `file_template = %%(rev)s_%%(slug)s`. No `sqlalchemy.url`: `env.py` sets it.
- `migrations/versions/0001_initial.py`: `revision = "0001"`, `down_revision = None`.

  ```python
  def upgrade() -> None:
      op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
      op.execute("CREATE EXTENSION IF NOT EXISTS vector")


  def downgrade() -> None:
      op.execute("DROP EXTENSION IF EXISTS vector")
      op.execute("DROP EXTENSION IF EXISTS timescaledb")
  ```

### `backend/docker-entrypoint.sh`

```sh
#!/bin/sh
# Applies every pending migration, then starts the server. Run one backend replica: two that start
# together would migrate at the same time.
set -e

echo "Applying database migrations..."
alembic upgrade head

exec "$@"
```

### `backend/Dockerfile`

MegooColab's Dockerfile with the entrypoint added:

- `FROM python:3.12-slim`, uv copied from `ghcr.io/astral-sh/uv`, `uv sync --frozen --no-dev --no-install-project` into `/opt/venv`, which is on `PATH`.
- Copies `alembic.ini`, `migrations/` and `app/` into `/app`.
- `ARG APP_VERSION=dev`, then `ENV APP_VERSION=$APP_VERSION`.
- Copies `docker-entrypoint.sh` to `/usr/local/bin/` and makes it executable.
- Runs as a system user `megooitadmin` (uid 10001). `EXPOSE 8000`.
- `ENTRYPOINT ["docker-entrypoint.sh"]`
- `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]`

### `megoocolab.toml` and the test services

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

- `docker-compose.yml` has one service, `db`: `timescale/timescaledb-ha:pg18`, user and password `megooitadmin` (a throwaway test credential, not a secret), `POSTGRES_DB: ${DB_NAME}`, port `127.0.0.1:${DB_PORT}:5432`, and a `pg_isready` healthcheck over TCP. No named volume.
- `docker-compose.image.yml` adds `backend`: `build: ../../backend`, `image: ${BACKEND_IMAGE}`, `DATABASE_URL` pointing at `db:5432/${DB_NAME}`, `depends_on: db: condition: service_healthy`, port `127.0.0.1:${API_PORT}:8000`, and a healthcheck that calls `/api/health` with Python (the image has no curl).

### `AGENTS.md` changes

**Checks**, the Backend line becomes:

```markdown
- **Backend** (`backend/`): `megoocolab-runner services run test -- uv run pytest`, then the container start-up
  tests: `megoocolab-runner services run image -- uv run pytest -m docker`.
```

**Migrations** becomes:

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

**Safety**, the Docker line becomes:

```markdown
- Docker: start containers for checks only with `megoocolab-runner services run`. It gives this worktree its own
  `megoo-…` containers and removes them when the command ends. Apart from those, use only the `megooitadmin-dev`
  and `megooitadmin-e2e` Compose projects. Never stop, remove or change any other container. A `megooitadmin`
  project and its `megooitadmin-*` containers are the owner's real instance.
```

`docs/releasing.md` and `README.md` do not change.

## Error handling and edge cases

- **A migration fails.** Alembic runs each migration in a transaction, so PostgreSQL rolls it back. `set -e` ends the script with Alembic's exit code, and Uvicorn never starts.
- **`DATABASE_URL` is missing or wrong, or the database is not reachable.** `alembic upgrade head` fails in the same way, and the container exits. Waiting for the database (`depends_on` with `service_healthy`) and the restart policy belong to MITA-4.
- **The database is already at head.** `upgrade head` does nothing and the server starts.
- **The extension already exists**, because the image created it: `IF NOT EXISTS` makes the migration pass.
- **The database role may not create extensions.** The migration fails and the container refuses to serve. The image's own user may create them. MITA-4 must give the backend a role that can.
- **TimescaleDB and sessions.** TimescaleDB wants its extension created or dropped in a fresh session. `env.py` uses `NullPool`, so every Alembic command has its own connection. The first migration step of the build proves `downgrade -1` and `upgrade head` on the `migrate` set. If the image refuses to drop the extension, the implementer stops and asks, and does not weaken the downgrade silently.
- **Stop signals.** `exec "$@"` makes Uvicorn process 1, so `docker stop` reaches it.
- **A Windows checkout.** `.gitattributes` keeps `*.sh` with LF line endings. With CRLF the entrypoint would not run in the container.
- **Two replicas.** Not guarded (decision 11).
- **pytest without its database.** `conftest.py` stops with a message that names the `services run test` command. It also refuses a database whose name does not end in `_test`, as MegooColab does, so the suite can never run against a real database.
- **The healthcheck of `db`** uses TCP (`pg_isready -h 127.0.0.1`), because the image's first-start server listens only on its socket and would report "ready" too early.
- **Behind the upstream proxy.** `--proxy-headers --forwarded-allow-ips=*` makes Uvicorn trust `X-Forwarded-Proto` and `X-Forwarded-For` from any address. This is safe only because Caddy is the only service that can reach the backend (MITA-4).

## Testing

Tests are written first. Names read as sentences.

**`megoocolab-runner services run test -- uv run pytest`** (from `backend/`):

- `test_health.py`: `GET /api/health` gives 200 and `{"status": "ok"}`. `GET /health` gives 404. `/api/openapi.json` lists `/api/health`.
- `test_settings.py`: `DATABASE_URL` is required. `APP_VERSION` defaults to `dev`. `alembic_url()` doubles `%`.
- `test_db.py`: a session from `SessionLocal` runs `SELECT 1` on the test database.
- `test_migrations.py`:
  - after `upgrade head` (run once per session by a fixture, through Alembic, not `create_all`), `alembic_version` holds the head and `pg_extension` lists `timescaledb` and `vector`;
  - `downgrade -1` removes both extensions and `upgrade head` brings them back;
  - `file_template` in `alembic.ini` is `%%(rev)s_%%(slug)s`;
  - the numbering rule of decision 10 holds for every file in `migrations/versions/`.

**`megoocolab-runner services run image -- uv run pytest -m docker`** (`test_container.py`; it does not import the app or run Alembic itself):

- **The container migrates on start:** the database behind `IMAGE_DATABASE_URL` is at head and has both extensions, although no test migrated it.
- **`/api/health` responds:** `GET ${BACKEND_URL}/api/health` gives 200.
- **The proxy headers are honoured:** `GET /api/health/` with `X-Forwarded-Proto: https` is redirected to a URL that starts with `https://`.
- **It refuses to serve when a migration fails:** `docker run --rm` of `${BACKEND_IMAGE}` on `${BACKEND_NETWORK}`, with `tests/fixtures/9999_fails.py` mounted into `/app/migrations/versions/`, exits with a non-zero code. Its output has "Applying database migrations..." and no Uvicorn start-up line. The database is still at `0001`.

**By hand in the build:** the two `migrate` commands of the new Migrations section, run exactly as `AGENTS.md` gives them.

The frontend, security and release checks are skipped in this task, because their parts are not in the repository yet. The implementer says so in the finish report.

## Out of scope

- `docker-compose.yml`, `caddy/Caddyfile`, the `Makefile` (with `make migrate` and `make migration`), the dev database in `megooitadmin-dev`, and the check behind Caddy: MITA-4.
- `ci.yml` (MITA-12), `tools/release/versions.py` (MITA-3), `release.yml` (MITA-13). CI will set `TEST_DATABASE_URL` from its own service container.
- Models, tables and mixins, hypertables and retention policies, the separate database roles, the audit writer (MITA-7), login (MITA-8).
- Valkey and Meilisearch clients, the workers, the gateway and the executor.
- CORS, rate limiting, logging configuration, a `.env` loader, a lint tool.
- One database per pytest-xdist worker. The suite is small and runs in one process.
- Any change to `README.md` or `docs/releasing.md`.
