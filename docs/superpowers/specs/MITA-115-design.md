# MITA-115 design: the backend serves as a restricted database role

## Goal

After this task the backend serves as `megooitadmin_api`, a PostgreSQL role that is not a superuser and owns no table. On `audit_log` it can only INSERT and SELECT, so it cannot change audit rows or switch the triggers off. The owner `megooitadmin` is used only by the entrypoint, before the server starts.

## Decisions

Answers from the owner:

1. **The entrypoint sets the role's password at every start.** Migration 0003 creates the role without login. After `alembic upgrade head`, the entrypoint (as the owner) gives it LOGIN and the password from the environment. Changing the password is: edit `.env`, restart. Rejected: a migration that reads the password from the environment (fixed when it runs), and a database init script (an existing volume never gets the role).
2. **`make up` adds the missing line to an existing `.env`.** It appends a random `POSTGRES_API_PASSWORD` when the file lacks it, and never changes or removes a line. Rejected: stopping with a message and a manual step.
3. **Each migration grants what its table needs.** A new table is closed to the API role until its migration grants something, and a security test compares the real grants with one declared list. Rejected: default privileges, where a forgotten revoke is an open table.

Decided in this design:

4. **Two URLs.** `DATABASE_URL` is the API role's and `DATABASE_OWNER_URL` is the owner's. Alembic and the password step use the owner's URL, and there is no fallback to `DATABASE_URL`: a missing owner URL stops Alembic with a message that names the variable.
5. **The server never holds the owner's password.** The entrypoint runs `unset DATABASE_OWNER_URL` before `exec "$@"`, so Uvicorn's environment does not contain it. `make migrate` still works: `docker compose exec` gets the container's configured environment. Rejected for now: a separate one-off migration service (the stack is pinned to four services; the PRD names it as the step when the backend is scaled out).
6. **The password is sent as a SCRAM-SHA-256 verifier**, computed in Python with the standard library, as `psql`'s `\password` does. The plain password is never part of an SQL statement, so it cannot reach the database log.
7. **The container refuses to serve as any other role.** The password step stops the start when `DATABASE_URL` does not name `megooitadmin_api`.

## Architecture

- **`backend/migrations/versions/0003_api_role.py`** (new). Upgrade: creates `megooitadmin_api` if it does not exist (roles belong to the cluster, not the database) with `NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`, grants USAGE on schema `public`, and the table grants below. Downgrade: `DROP OWNED BY megooitadmin_api`, then `DROP ROLE megooitadmin_api`.
- **`backend/app/core/db_roles.py`** (new). `API_ROLE = "megooitadmin_api"` and `sync_api_role_password()`, also runnable as `python -m app.core.db_roles`. It reads the user and password from `DATABASE_URL`, connects with `DATABASE_OWNER_URL`, and runs `ALTER ROLE megooitadmin_api WITH LOGIN PASSWORD '<verifier>'`. The app keeps no owner engine: this module opens one and disposes of it.
- **`backend/app/core/config.py`**. New `database_owner_url: str | None = None`. `alembic_url()` returns the owner's URL, and raises when it is not set.
- **`backend/docker-entrypoint.sh`**. `alembic upgrade head`, `python -m app.core.db_roles`, `unset DATABASE_OWNER_URL`, `exec "$@"`.
- **`docker-compose.yml`**. The backend gets `DATABASE_URL` (user `megooitadmin_api`, `${POSTGRES_API_PASSWORD:?…}`) and `DATABASE_OWNER_URL` (user `megooitadmin`, `${POSTGRES_PASSWORD:?…}`). The `db` service does not change, apart from its comment.
- **`Makefile`**. The `.env` rule runs on every `make up` of the real instance. A missing file is created with both passwords, mode 600. A file without a `POSTGRES_API_PASSWORD=` line gets one appended, and make says so. A file that has both is not touched. The rule only looks for the variable's name.
- **`.env.example`, `tools/stacks/dev.env`, `tools/stacks/e2e.env`, `README.md`**. The second variable. The throwaway value is `megooitadminapi`, different from the owner's `megooitadmin`, so a mixed-up password fails.
- **`megoocolab.toml` and `tools/test-services/docker-compose.image.yml`**. See the table below.
- **`AGENTS.md`**, Migrations: a migration that creates a table grants `megooitadmin_api` what it needs and adds the table to the declared list.

## Data and interfaces

Grants for `megooitadmin_api`:

| Table | Privileges | Why |
|---|---|---|
| `audit_log` | SELECT, INSERT | The writer inserts, the chain check and the Audit page read |
| `audit_chain_head` | SELECT, UPDATE | The writer locks the head (`FOR UPDATE` needs UPDATE) and moves it |
| `alembic_version` | none | Only the owner migrates |

Environment variables:

| Variable | Where | Value |
|---|---|---|
| `POSTGRES_API_PASSWORD` | `.env`, `tools/stacks/*.env`, the `stack` set | The API role's password. Letters and digits only, like `POSTGRES_PASSWORD` |
| `DATABASE_URL` | backend | The API role's URL. The app serves with it |
| `DATABASE_OWNER_URL` | backend, entrypoint only | The owner's URL, for Alembic and the password step |
| `TEST_DATABASE_URL`, `TEST_DATABASE_OWNER_URL` | the `test` set | The API role's and the owner's URL of `megooitadmin_test`. `conftest.py` copies them to `DATABASE_URL` and `DATABASE_OWNER_URL`, and checks the `_test` suffix on both |
| `DATABASE_URL`, `DATABASE_OWNER_URL` | the `migrate` set | Both, so `make migration` keeps working |
| `IMAGE_API_DATABASE_URL` | the `image` set | The API role's URL, beside the owner's `IMAGE_DATABASE_URL` |

## Error handling and edge cases

- **An instance that already runs.** `make up` appends the new password, the entrypoint applies 0003 as the owner, sets the password, and the server connects as the API role. No manual step.
- **`.env` lacks the variable and Compose is run without make.** Compose stops and names `POSTGRES_API_PASSWORD`.
- **`DATABASE_URL` names another role, has no password, or a password outside printable ASCII.** The password step exits with a message that names the variable and never prints the URL. Uvicorn does not start.
- **The role is missing when the password step runs.** It fails and says to run the migrations.
- **A changed API password.** The next start sets it. Sessions that are open stay open.
- **Downgrade below 0003.** The role is dropped, so the next upgrade creates it without login. The tests set the password again after each such cycle.
- **TimescaleDB chunks.** A chunk takes the hypertable's grants, so the API role has SELECT and INSERT on a chunk and nothing else. A test proves it on a real chunk, and the existing writer tests prove that the API role's insert creates a chunk.

## Testing

Tests are written first. Sessions of the app (`SessionLocal`) are now the API role's. The tests get an owner session from `conftest.py` for what only the owner can do: `empty_audit_log`, `tamper()` and the migration tests. One helper, upgrade to head and then set the password, serves `database_at_head` and the down-and-up cycles in `test_migrations.py`.

- **`tests/security/test_audit_tamper.py`**
  - As the API role: UPDATE, DELETE and TRUNCATE on `audit_log` are refused with SQLSTATE 42501 (permission denied), and so are DELETE, TRUNCATE and INSERT on `audit_chain_head`.
  - The same three statements with the triggers off. The owner sets `ALTER ROLE megooitadmin_api SET session_replication_role = replica`, the test checks with `SHOW` that the API session runs with it, expects 42501, and the fixture resets the setting.
  - The API role cannot disable the triggers: `SET session_replication_role = replica`, `ALTER TABLE audit_log DISABLE TRIGGER USER`, `DROP TRIGGER`, `CREATE OR REPLACE FUNCTION audit_refuse_change()` and `drop_chunks('audit_log', …)` are all refused.
  - UPDATE, DELETE and TRUNCATE directly on a chunk of `audit_log` are refused.
  - The existing trigger tests move to the owner session: the trigger still refuses the owner.
- **`tests/security/test_db_privileges.py`** (new, part of `make test-security`)
  - The role is not a superuser, cannot create roles or databases, owns no relation and cannot create a table in `public`.
  - Its real table grants equal the declared `API_GRANTS`, and every table of `Base.metadata` is in that list. The failure message says to add the grant to the table's migration.
- **`tests/test_db_roles.py`** (new). After the step the role logs in with the password of `DATABASE_URL`. A changed password works and the old one is refused. A `DATABASE_URL` with another user is refused. The stored password is a SCRAM verifier.
- **`tests/test_migrations.py`**. 0003 goes down and up again: the role and its grants are gone, then back. Queries run as the owner.
- **`tests/test_db.py`**. The probe table is created by the owner with grants for the API role, because the API role cannot create tables.
- **`tests/test_settings.py`**. `alembic_url()` uses the owner's URL and raises without it.
- **`tests/test_makefile.py`**. A new `.env` holds both passwords, different, with mode 600. An `.env` with only `POSTGRES_PASSWORD` gets the second line and keeps the first unchanged. A complete file is not touched.
- **`tests/test_container.py`** (`-m docker`). The API role logs in with `IMAGE_API_DATABASE_URL` and is not a superuser. A one-off container whose `DATABASE_URL` names the owner refuses to serve.
- **`tests/test_stack.py`** (`-m stack`). The backend's process 1 has no `DATABASE_OWNER_URL` and its `DATABASE_URL` names `megooitadmin_api`. Through `psql` in the `db` container, the API role logs in with `POSTGRES_API_PASSWORD` and is refused an UPDATE on `audit_log`.

Done when `make test` and `make test-security` pass.

## Out of scope

- The roles for the agent runtime and the executor: they join when those services exist.
- A separate one-off migration service, and rotating the owner's password.
- A database check in `/api/health`.
- Grants for tables that do not exist yet.
