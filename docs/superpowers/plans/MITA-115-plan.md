# MITA-115 plan: the backend serves as a restricted database role

**Goal:** the backend serves as `megooitadmin_api`, a role that is not a superuser, owns no table and may only INSERT and SELECT on `audit_log`. The owner `megooitadmin` is used only by the entrypoint, before the server starts.

**Architecture:** migration 0003 creates `megooitadmin_api` without login and grants it what `audit_log` and `audit_chain_head` need. The entrypoint migrates with `DATABASE_OWNER_URL`. Then `python -m app.core.db_roles` gives the role LOGIN and the password of `DATABASE_URL`, sent as a SCRAM-SHA-256 verifier. The entrypoint then unsets the owner's URL and execs Uvicorn. `make up` adds a second random password, `POSTGRES_API_PASSWORD`, to `.env`. The tests also serve as the API role, and get an owner session from `conftest.py` for what only the owner may do.

## File map

| File | Change | Responsibility |
|---|---|---|
| `backend/app/core/config.py` | modify | `database_owner_url`; `alembic_url()` returns the owner's URL or raises |
| `backend/app/core/db_roles.py` | create | `API_ROLE`, `ApiRoleError`, `scram_verifier()`, `sync_api_role_password()`, `main()` |
| `backend/migrations/versions/0003_api_role.py` | create | The role and its grants; downgrade drops it |
| `backend/docker-entrypoint.sh`, `backend/Dockerfile` (comment) | modify | migrate, set the password, `unset DATABASE_OWNER_URL`, exec |
| `backend/tests/conftest.py` | modify | Both test URLs, `owner_session()`, `upgrade_to_head()`, `empty_audit_log` as the owner |
| `backend/tests/security/test_db_privileges.py` | create | `API_GRANTS`, role attributes, ownership, real grants = declared grants |
| `backend/tests/security/test_audit_tamper.py` | modify | Privilege refusals as the API role; trigger tests and `tamper()` as the owner |
| `backend/tests/test_db_roles.py` | create | The password step |
| `backend/tests/test_settings.py`, `test_migrations.py`, `test_db.py`, `audit/test_http.py` | modify | The owner's URL; owner queries; probe tables created by the owner |
| `backend/tests/test_makefile.py`, `test_container.py`, `test_stack.py` | modify | The `.env` rule, the image check, the stack check |
| `Makefile` | modify | `.env` rule: create the file with two passwords, or append the missing one |
| `docker-compose.yml`, `tools/test-services/docker-compose.image.yml` | modify | `DATABASE_URL` (the API role) and `DATABASE_OWNER_URL` (the owner) |
| `megoocolab.toml` | modify | The `test`, `migrate`, `image` and `stack` sets |
| `.env.example`, `tools/stacks/*.env`, `README.md`, `AGENTS.md` | modify | The second variable, the migration rule, the security suites line |

Throwaway values: owner `megooitadmin`/`megooitadmin`, API role `megooitadmin_api`/`megooitadminapi`. Run every runner command from `backend/`.

## Reference code

### A. `backend/app/core/db_roles.py` (step 2 creates the docstring and `API_ROLE`; step 3 adds the rest)

```python
"""The API role megooitadmin_api: the backend serves as it, and the entrypoint gives it its password.

Migration 0003 creates the role without login. `python -m app.core.db_roles` runs after `alembic upgrade head`, as
the owner, and gives the role LOGIN and the password of DATABASE_URL. The password is sent as a SCRAM-SHA-256
verifier, as psql's \\password does, so the plain password never reaches the database or its log."""

import asyncio, base64, hashlib, hmac, os, re, sys   # one import per line in the real file

from pydantic import ValidationError
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings

API_ROLE = "megooitadmin_api"
SCRAM_ITERATIONS = 4096
UNDEFINED_OBJECT = "42704"
# Only base64, digits, $ and :, so the verifier is safe between the quotes of ALTER ROLE.
_VERIFIER = re.compile(r"SCRAM-SHA-256\$[0-9]+:[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+:[A-Za-z0-9+/=]+")


class ApiRoleError(RuntimeError):
    """The API role's password cannot be set. The message names the variable and never holds a URL."""


def scram_verifier(password: str, salt: bytes | None = None, iterations: int = SCRAM_ITERATIONS) -> str:
    salt = os.urandom(16) if salt is None else salt
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    stored_key = hashlib.sha256(hmac.digest(salted, b"Client Key", "sha256")).digest()
    server_key = hmac.digest(salted, b"Server Key", "sha256")
    b64 = lambda data: base64.b64encode(data).decode()  # a def in the real file
    return f"SCRAM-SHA-256${iterations}:{b64(salt)}${b64(stored_key)}:{b64(server_key)}"


def _api_password(database_url: str) -> str:
    try:
        url = make_url(database_url)
    except ArgumentError:
        raise ApiRoleError("DATABASE_URL is not a database URL") from None
    if url.username != API_ROLE:
        raise ApiRoleError(f"DATABASE_URL must connect as {API_ROLE}: the backend never serves as another role")
    password = url.password or ""
    if not password:
        raise ApiRoleError(f"DATABASE_URL has no password for {API_ROLE}")
    if not (password.isascii() and password.isprintable()):
        raise ApiRoleError("the password in DATABASE_URL must be printable ASCII")
    return password


async def _set_password(owner_url: str, verifier: str) -> None:
    engine = create_async_engine(owner_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            # exec_driver_sql, not text(): text() would read ":<base64>" inside the verifier as a bind parameter.
            await connection.exec_driver_sql(f"ALTER ROLE {API_ROLE} WITH LOGIN PASSWORD '{verifier}'")
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == UNDEFINED_OBJECT:
            raise ApiRoleError(f"the role {API_ROLE} does not exist: run the migrations (alembic upgrade head) first") from None
        raise
    finally:
        await engine.dispose()


def _settings() -> Settings:
    try:
        return get_settings()
    except ValidationError:
        raise ApiRoleError("DATABASE_URL is not set") from None


def sync_api_role_password(settings: Settings | None = None) -> None:
    """Gives the API role LOGIN and the password of DATABASE_URL, connected with DATABASE_OWNER_URL. Sync, like
    Alembic's commands: it runs its own event loop."""
    settings = settings or _settings()
    password = _api_password(settings.database_url)
    if not settings.database_owner_url:
        raise ApiRoleError("DATABASE_OWNER_URL is not set: the API role's password is set as the owner")
    verifier = scram_verifier(password)
    if not _VERIFIER.fullmatch(verifier):
        raise ApiRoleError("the SCRAM verifier has an unexpected shape")
    asyncio.run(_set_password(settings.database_owner_url, verifier))


def main() -> int:
    try:
        sync_api_role_password()
    except ApiRoleError as exc:
        print(f"Could not set the password of {API_ROLE}: {exc}", file=sys.stderr)
        return 1
    print(f"Set the password of {API_ROLE}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### B. `backend/migrations/versions/0003_api_role.py`

Header in the style of 0002: docstring `api role: megooitadmin_api, the restricted role the backend serves as`, `revision = "0003"`, `down_revision = "0002"`.

```python
def upgrade() -> None:
    # Roles belong to the cluster, not the database, so another database of the cluster may have created it.
    # LOGIN and the password come from the entrypoint (app.core.db_roles), never from a migration.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'megooitadmin_api') THEN
                CREATE ROLE megooitadmin_api NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
            END IF;
        END
        $$
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO megooitadmin_api")
    # Append-only by privilege. A chunk takes the hypertable's grants.
    op.execute("GRANT SELECT, INSERT ON audit_log TO megooitadmin_api")
    # The writer locks the head (FOR UPDATE needs UPDATE) and moves it.
    op.execute("GRANT SELECT, UPDATE ON audit_chain_head TO megooitadmin_api")


def downgrade() -> None:
    op.execute("DROP OWNED BY megooitadmin_api")
    op.execute("DROP ROLE megooitadmin_api")
```

The role name is a literal: a migration never imports app code that may change.

### C. `backend/tests/conftest.py` additions

```python
def _test_url(name: str) -> str:
    url = os.environ.get(name)
    if not url:
        pytest.exit(f"{name} is not set. Run the suite as: {RUN_TESTS}", returncode=2)
    database = url.rsplit("/", 1)[-1].split("?", 1)[0]
    if not database.endswith("_test"):
        pytest.exit(f"Refusing to run against {database!r} ({name}): the test database name must end in _test.", returncode=2)
    return url


def pytest_configure(config):
    if _own_file(config):
        return
    os.environ["DATABASE_URL"] = _test_url("TEST_DATABASE_URL")
    os.environ["DATABASE_OWNER_URL"] = _test_url("TEST_DATABASE_OWNER_URL")
    os.environ["DB_NULL_POOL"] = "true"


@cache  # functools
def _owner_engine():
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool
    return create_async_engine(os.environ["DATABASE_OWNER_URL"], poolclass=NullPool)


def owner_session():
    """A session as megooitadmin, the owner of the tables, for what the API role may not do."""
    from sqlalchemy.ext.asyncio import AsyncSession
    return AsyncSession(_owner_engine(), expire_on_commit=False)


def upgrade_to_head() -> None:
    """Migrates as the owner, then sets the API role's password, as the entrypoint does. Sync: Alembic's env.py
    runs its own event loop. A downgrade below 0003 drops the role, so every way back to head goes through here."""
    from alembic import command
    from alembic.config import Config
    from app.core.db_roles import sync_api_role_password   # step 4 adds this line and the call
    command.upgrade(Config(str(ALEMBIC_INI)), "head")
    sync_api_role_password()                                # step 4


@pytest.fixture(scope="session")
def database_at_head():
    upgrade_to_head()
```

`empty_audit_log` (step 4) uses `async with owner_session() as session:`. Its comment says the owner switches the triggers off for this transaction only. Test modules import with `from conftest import owner_session, upgrade_to_head`, placed in the third-party import group as `from routes import …` is. Pytest's default prepend import mode puts `backend/tests` on `sys.path`.

### D. `backend/tests/security/test_db_privileges.py`

```python
"""The API role megooitadmin_api has only the grants declared here. A migration that creates a table grants the
role what the table needs, and adds the table to API_GRANTS (an empty set keeps a table closed on purpose)."""

import pytest
from conftest import owner_session
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.core.db import Base
from app.core.db_roles import API_ROLE

pytestmark = pytest.mark.usefixtures("database_at_head")

INSUFFICIENT_PRIVILEGE = "42501"
API_GRANTS: dict[str, frozenset[str]] = {
    "audit_log": frozenset({"SELECT", "INSERT"}),
    "audit_chain_head": frozenset({"SELECT", "UPDATE"}),
}
ROLE_OID = "(SELECT oid FROM pg_roles WHERE rolname = :role)"


async def _rows(sql: str) -> list:
    async with owner_session() as session:
        return (await session.execute(text(sql), {"role": API_ROLE})).all()


async def test_the_api_role_is_not_a_superuser_and_cannot_create_roles_or_databases():
    rows = await _rows("SELECT rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls FROM pg_roles WHERE rolname = :role")
    assert rows == [(False, False, False, False, False)]


async def test_the_api_role_owns_no_relation():
    assert await _rows(f"SELECT relname FROM pg_class WHERE relowner = {ROLE_OID}") == []


async def test_the_api_role_cannot_create_a_table_in_public():
    async with owner_session() as session:
        await session.execute(text(f"SET LOCAL ROLE {API_ROLE}"))
        with pytest.raises(DBAPIError) as exc:
            await session.execute(text("CREATE TABLE api_role_probe (id int)"))
        await session.rollback()
    assert exc.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE


async def test_the_api_roles_table_grants_are_the_declared_ones():
    rows = await _rows(
        "SELECT c.relname, a.privilege_type FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
        f" CROSS JOIN LATERAL aclexplode(c.relacl) a WHERE n.nspname = 'public' AND a.grantee = {ROLE_OID}"
    )
    actual: dict[str, set[str]] = {}
    for table, privilege in rows:
        actual.setdefault(table, set()).add(privilege)
    assert actual == {t: set(p) for t, p in API_GRANTS.items() if p}, (
        f"{API_ROLE}'s grants differ from API_GRANTS: grant what a table needs in the migration that creates it, "
        "and declare it in API_GRANTS"
    )


def test_every_table_of_the_models_is_declared():
    missing = sorted(set(Base.metadata.tables) - set(API_GRANTS))
    assert missing == [], (
        f"{', '.join(missing)}: add the grant for {API_ROLE} to the table's migration, "
        "and the table to API_GRANTS in tests/security/test_db_privileges.py"
    )
```

### E. `test_audit_tamper.py`: contracts for step 4

- `INSUFFICIENT_PRIVILEGE = "42501"`. `CHANGES` is three statements: `UPDATE audit_log SET reason = 'changed' WHERE seq = 3`, `DELETE FROM audit_log WHERE seq = 3` and `TRUNCATE audit_log`.
- `tamper(sql, params)` runs on `owner_session()`, after `SET LOCAL session_replication_role = replica`.
- `refused_for_the_owner(sql) -> str` returns `str(exc.value)`. `refused_for_the_api_role(sql) -> str` runs on `SessionLocal()` and returns `exc.value.orig.sqlstate`. Both use `pytest.raises(DBAPIError)` and then roll back.
- `audit_rows()` counts the rows as the owner. `a_chunk()` returns, as the owner, `SELECT chunk_schema || '.' || chunk_name FROM timescaledb_information.chunks WHERE hypertable_name = 'audit_log' LIMIT 1` (concatenation, not `format('%I…')`).
- The `triggers_off_for_the_api_role` fixture runs `ALTER ROLE megooitadmin_api SET session_replication_role = replica` as the owner and commits. After the yield it runs `ALTER ROLE megooitadmin_api RESET session_replication_role`.
- New tests:
  - `test_the_api_role_may_not_change_audit_log`: chain, parametrized over CHANGES, expects 42501.
  - `test_the_api_role_may_not_remove_or_add_a_chain_head`: `DELETE FROM audit_chain_head`, `TRUNCATE audit_chain_head`, `INSERT INTO audit_chain_head (id, seq, hash) VALUES (2, 0, decode(repeat('00', 32), 'hex'))`, expects 42501.
  - `test_the_api_role_may_not_change_audit_log_with_the_triggers_off`: chain and the fixture, over CHANGES. In one SessionLocal session, `SHOW session_replication_role` returns `replica`, then the statement raises 42501.
  - `test_the_api_role_cannot_switch_the_triggers_off`: chain. Each of `SET session_replication_role = replica`, `ALTER TABLE audit_log DISABLE TRIGGER USER`, `DROP TRIGGER audit_log_refuse_change ON audit_log`, `CREATE OR REPLACE FUNCTION audit_refuse_change() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN OLD; END $$` and `SELECT drop_chunks('audit_log', older_than => now() + INTERVAL '1 day')` gives 42501, and `audit_rows() == 5` afterwards.
  - `test_the_api_role_may_not_change_a_chunk_of_audit_log`: chain. `UPDATE {chunk} SET reason = 'changed'`, `DELETE FROM {chunk}` and `TRUNCATE {chunk}` each give 42501.
  - `test_a_chunk_takes_only_the_hypertables_grants`: chain. As the owner, `has_table_privilege(:role, :chunk, p)` for SELECT, INSERT, UPDATE, DELETE and TRUNCATE gives `(True, True, False, False, False)`.
- The five existing trigger tests become `test_the_trigger_refuses_the_owner_an_update_on_audit_log`, `…_a_delete_on_audit_log`, `…_a_truncate_on_audit_log`, `…_a_delete_on_the_chain_head` and `…_a_truncate_on_the_chain_head`, using `refused_for_the_owner` with `"append-only" in`. Remove `refused()`. The module docstring becomes: "The API role may not change the audit log, by privilege; the triggers refuse even the owner; and the chain check finds what the owner changed or removed anyway."

### F. `backend/tests/test_db_roles.py`: contracts for step 3

- `PASSWORD = "megooitadminapi"`, with the comment "the API role's password in the test set of megooitadmin.toml". `_url(user, password)` is `make_url(os.environ["DATABASE_OWNER_URL"]).set(username=user, password=password).render_as_string(hide_password=False)`. `_settings(database_url)` is `Settings(database_url=database_url, database_owner_url=os.environ["DATABASE_OWNER_URL"])`.
- The autouse `restored_password(database_at_head)` fixture: after the yield, `sync_api_role_password(_settings(_url(API_ROLE, PASSWORD)))`.
- `_login(password) -> str`: `asyncio.run`, `asyncpg.connect` to the plain `postgresql://` form of `_url(API_ROLE, password)`, returns `SELECT current_user` and closes the connection.
- Tests:
  - `test_after_the_step_the_api_role_logs_in_with_the_password_of_database_url`.
  - `test_a_changed_password_works_and_the_old_one_is_refused`: sync with PASSWORD, then with `changedpassword2`. The new password logs in, and the old one raises `asyncpg.InvalidPasswordError`.
  - `test_a_database_url_with_another_user_is_refused`: `_settings(DATABASE_OWNER_URL)` raises `ApiRoleError`, matching `DATABASE_URL must connect as megooitadmin_api`.
  - `test_a_password_that_is_missing_or_not_printable_ascii_is_refused`, parametrized over `""`, `"pässword"` and `"tab\tbed"`: `ApiRoleError` matching `DATABASE_URL`.
  - `test_the_stored_password_is_a_scram_verifier`: as the owner, `SELECT rolpassword FROM pg_authid WHERE rolname = :role` starts with `SCRAM-SHA-256$4096:`.
  - `test_without_the_role_the_step_says_to_run_the_migrations`: `command.downgrade(Config(str(ALEMBIC_INI)), "0002")`, then `ApiRoleError` matching `alembic upgrade head`. In a `finally`, `upgrade_to_head()`.
  - `test_the_module_exits_1_and_never_prints_the_url`: `subprocess.run([sys.executable, "-m", "app.core.db_roles"], cwd=backend, env={**os.environ, "DATABASE_URL": owner_url}, timeout=60)`. The return code is 1 and stderr contains `DATABASE_URL must connect as megooitadmin_api`. Neither the owner URL nor `@localhost` appears in stdout or stderr.

### G. `Makefile` `.env` rule

Add `.env` to `.PHONY`, so the rule runs on every `make up` of the real instance. With `STACK=`, `ENV_FILE` is empty. The `up` help line becomes "(creates or completes .env first)".

```make
# Only the real instance reads .env. A missing file is created with both passwords. A file without
# POSTGRES_API_PASSWORD gets one appended. No line is ever changed or removed.
.env:
	@if [ ! -e .env ]; then \
		pw=$$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n'); api=$$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n'); \
		if ! printf '%s%s' "$$pw" "$$api" | grep -Eqx '[0-9a-f]{64}'; then \
			echo "Could not read a random password from /dev/urandom: .env was not written." >&2; exit 1; \
		fi; \
		(umask 077; printf 'POSTGRES_PASSWORD=%s\nPOSTGRES_API_PASSWORD=%s\n' "$$pw" "$$api" > .env); \
		echo "Created .env with new database passwords. Keep this file: the database keeps the owner's password it was first started with."; \
	elif ! grep -q '^POSTGRES_API_PASSWORD=' .env; then \
		api=$$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n'); \
		if ! printf '%s' "$$api" | grep -Eqx '[0-9a-f]{32}'; then \
			echo "Could not read a random password from /dev/urandom: .env was not changed." >&2; exit 1; \
		fi; \
		if [ -s .env ] && [ -n "$$(tail -c 1 .env)" ]; then echo >> .env; fi; \
		printf 'POSTGRES_API_PASSWORD=%s\n' "$$api" >> .env; \
		echo "Added POSTGRES_API_PASSWORD to .env: the backend now serves as the restricted role megooitadmin_api."; \
	fi
```

### H. `.env.example` (the port block stays unchanged)

```
# The real instance reads .env. `make up` creates it with random passwords when it is missing, and adds
# POSTGRES_API_PASSWORD to a file that lacks it. It never changes or removes a line.

# The database owner's password. The owner holds the tables and runs the migrations; only the backend's
# entrypoint uses it. Letters and digits only: it is also part of a database URL.
# The database keeps the password it was first started with, so keep .env once the stack has run.
POSTGRES_PASSWORD=

# The password of megooitadmin_api, the restricted role the backend serves as. Letters and digits only.
# The backend sets it at every start, so a changed value takes effect at the next start.
POSTGRES_API_PASSWORD=
```

## Steps

1. Alembic connects with DATABASE_OWNER_URL
2. Migration 0003 creates megooitadmin_api with its grants
3. The password step: python -m app.core.db_roles
4. The backend's tests serve as the API role
5. make up gives .env the second password, and the stacks get it
6. The container sets the password and serves as the API role

Each step's full detail is the matching entry of the `steps` list.

## Final verification

From the repository root, `make test` and `make test-security` must pass. `make test` runs the backend suite, the frontend checks, `-m docker`, the web image check and `-m stack`. `make test-security` includes `test_db_privileges.py` and the privilege tests of `test_audit_tamper.py`. From `backend/`, `megoocolab-runner services run migrate -- sh -c 'uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head'` must pass too.

## Requirement coverage

- The role and its grants, the declared list and the AGENTS.md rule: step 2.
- The password set at every start as a SCRAM verifier, and other roles refused: steps 3 and 6.
- The owner used only by the entrypoint: steps 1 and 6.
- The second password in every file the task names: steps 1, 4, 5 and 6.
- `make up` appending the missing line: step 5.
- Privilege refusals, also with the triggers off, the triggers that cannot be switched off, and chunks: step 4.
- The whole suite and the stack check on the restricted role: steps 4 and 6, and the final verification.
