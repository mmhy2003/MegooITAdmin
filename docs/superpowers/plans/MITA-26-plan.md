# MITA-26 — Metrics collector: one SSH stream per server — implementation plan

## Goal
A `collector` Compose service, running the backend image with `python -m app.collector`, keeps one SSH channel open to every pinned Linux server. Each channel runs a read-only shell loop that prints one JSON line per sample. Every sample is published on Valkey and written to `metrics`, and each server's reachable or unreachable state is kept in `server_status`.

## Architecture
The new package `backend/app/collector/` holds the server-side loop (`script.sh`), line parsing (`parse.py`), the arithmetic (`compute.py`), the state table writer (`state.py`), the buffered metrics writer (`writer.py`), one task per server (`stream.py`), the poller that starts and stops those tasks (`supervisor.py`), the start-up (`__main__.py`) and the healthcheck (`health.py`). SSH goes through `inventory.connection.open_connection` with `Actor.system("collector")`. A new helper, `app.ssh.client.script_output`, starts the loop on one channel, so `client.py` stays the only module that uses asyncssh's connection API. Migration `0009` adds the role `megooitadmin_collector`, `servers.metrics_interval_seconds` and `server_status`. The backend's entrypoint sets the collector role's password from `DATABASE_COLLECTOR_URL`. The server API returns the interval and the monitoring state.

## Facts checked (repo at `df3224e`)
- The last migration is `0008_metrics.py`. `test_migrations.py` requires `0009_<slug>.py` with `down_revision = "0008"`, and `test_the_models_match_the_migrations` runs `alembic check`, which compares types but not check constraints or server defaults.
- `Settings.auth_secret_key` is required today. It is used only by `auth_key()`, which `app/auth/service.py` calls at request time. `app/core/db.py` builds the engine from `DATABASE_URL` when it is imported, so a collector process that imports `app` needs `Settings` to work without the key.
- `open_connection(server, actor=, source=)` checks `server.os`, `host_key` and `host_key_changed_at` on the object it is given, and reads `connection_settings["username"]`. On `client.HostKeyChanged` it calls `_flag_changed`, which uses `app.inventory.connection.SessionLocal`. That function does `SELECT … FOR UPDATE` on the whole `servers` row (FOR UPDATE needs UPDATE on at least one column), updates `host_key_changed_at`, `host_key_offered` and `host_key_offered_at`, and calls `audit.record`. `record` locks `audit_chain_head` (SELECT and UPDATE), and every `audit_log` column is given, so the INSERT has no RETURNING.
- `client.HostKeyChanged` is a subclass of `client.SshFailure`, so it must be caught first.
- `tests/fake_server.py` gives `FakeServer(host, port, container)` with `exec`, `host_key()`, `swap_host_key()` and `sign_ins()`. The image has `procps` (`pgrep`/`pkill`) and Debian's `mawk`. Its entrypoint makes new host keys at every start today. Its `/` is `overlay`.
- `tests/conftest.py` sets the app's environment from `TEST_*` variables, and `upgrade_to_head()` migrates and then sets the API role's password. Test folders have no `__init__.py`, so test file names must be unique across `tests/`. Shared helper modules live at `tests/*.py` (`auth_helpers.py`, `fake_server.py`).
- `tests/security/test_db_privileges.py` compares `pg_class.relacl` with `API_GRANTS`, but not column grants (those live in `pg_attribute.attacl`).
- `test_stack.py` pins services in `NETWORKS`, checks that only the backend mounts `ssh_key`, and checks that the build overlay has exactly backend and frontend. `test_makefile.py` pins the exact `.env` lines.
- `megoo-setup.sh` writes `from="<addresses>" <key>` and no forced command, so `sh -s` runs. The fake server's `authorize-key` accepts the private ranges, which covers the collector's container.
- asyncssh: `conn.create_process(cmd, encoding=None, stderr=asyncssh.DEVNULL)` gives `process.stdin.write(bytes)`, `process.stdin.write_eof()`, `await process.stdout.read(n)` (returns `b""` at EOF), `process.close()` and `await process.wait_closed()`. Stderr has to be discarded: an unread stderr would fill the channel's window and stall stdout.

## Decisions made in this plan (within the design)
- **The tests' watchdog is 3 seconds, not 1.** The test servers sample every second, so a 1-second watchdog would fire between two samples. `FAST = Timings(no_sample_after=3.0, backoff_first=0.2, backoff_max=1.0, jitter=0.0)`.
- **When unreachable is written.** Each stream watches its own clock. When `no_sample_after` passes without a sample, it writes `unreachable` with the last failure's reason (`unreachable`, `key_refused`, `ssh_error`) or `no_samples`. A failed sign-in therefore does not flip the state before 30 seconds, which keeps "every server keeps its last state until a sample arrives or 30 seconds pass". `reachable` is written on the first sample.
- **Rates:** if any counter went down, or the uptime did not grow, the sample carries no rate at all.
- **Whole disks:** both the script and `compute.py` keep only names that match `^(sd[a-z]+|vd[a-z]+|xvd[a-z]+|hd[a-z]+|nvme[0-9]+n[0-9]+|mmcblk[0-9]+)$`. The script also leaves out `lo` and `veth*`, so its 64-entry caps are not used up by them.
- **Local filesystems:** `ext2|ext3|ext4|xfs|btrfs|f2fs|jfs|vfat|exfat`, plus `overlay` mounted on `/`. A mount point that holds a backslash (an escaped space or control character in `/proc/mounts`) is skipped.
- **Numbers are passed through as text** by awk, after a check against a digits-only pattern (`0` otherwise), so no awk ever prints a large counter in exponent form.
- **Without `DATABASE_COLLECTOR_URL`** the entrypoint leaves the collector role as it is and says so.
- **A throttle helper** (`app/collector/throttle.py`) gives every repeated warning "at most once a minute".
- **Build overlay:** the collector uses `megooitadmin-backend:${MEGOOITADMIN_VERSION:-dev}` with `pull_policy: never`, so it reuses the image the backend service builds and is never pulled.
- **Heartbeat file:** a new setting `COLLECTOR_HEARTBEAT_FILE` (default `/tmp/megooitadmin-collector.heartbeat`).

## File map

| File | Change | Responsibility |
|---|---|---|
| `backend/app/core/config.py` | modify | `auth_secret_key` optional; `database_collector_url`; `collector_heartbeat_file` |
| `backend/app/main.py` | modify | `create_app()` refuses to start without the key |
| `tools/fake-server/entrypoint.sh` | modify | Host keys made at the first start, kept across restarts |
| `backend/tests/fake_server.py` | modify | `restart`, `pause`, `unpause`, `kill_sessions`, `loops` |
| `backend/migrations/versions/0009_collector.py` | create | Role, interval column, `server_status`, grants |
| `backend/app/inventory/models.py` | modify | `metrics_interval_seconds`, `ServerStatus` |
| `backend/app/core/db_roles.py`, `backend/docker-entrypoint.sh` | modify | The collector role's password |
| `megoocolab.toml`, `tools/test-services/docker-compose.image.yml` | modify | Collector URLs of the test, image and stack sets |
| `backend/app/inventory/server_schemas.py`, `servers.py` | modify | Interval and `monitoring` in the API |
| `backend/app/ssh/client.py` | modify | `script_output()` |
| `backend/app/collector/__init__.py` | create | Docstring and `script()` (the bytes of `script.sh`) |
| `backend/app/collector/script.sh` | create | The server-side loop |
| `backend/app/collector/parse.py` | create | `Lines`, `Raw`, `parse` |
| `backend/app/collector/compute.py` | create | `readings(previous, current)` |
| `backend/app/collector/throttle.py` | create | `Throttle` |
| `backend/app/collector/state.py` | create | `StatusBook` |
| `backend/app/collector/writer.py` | create | `Writer` |
| `backend/app/collector/stream.py` | create | `Timings`, `Target`, `Publisher`, `Stream` |
| `backend/app/collector/supervisor.py` | create | `Supervisor`, `refusal_of` |
| `backend/app/collector/__main__.py`, `health.py` | create | Start, stop, healthcheck |
| `backend/tests/collector_helpers.py` | create | Shared helpers of the collector tests |
| `backend/tests/conftest.py` | modify | `DATABASE_COLLECTOR_URL`, collector password in `upgrade_to_head`, `collector_sessions` fixture |
| `backend/tests/collector/test_collector_*.py` | create | Behaviour tests |
| `docker-compose.yml`, `docker-compose.build.yml` | modify | The `collector` service; `DATABASE_COLLECTOR_URL` for the backend |
| `Makefile`, `.env.example`, `tools/stacks/dev.env`, `tools/stacks/e2e.env` | modify | `POSTGRES_COLLECTOR_PASSWORD` |
| `backend/tests/test_stack.py`, `test_makefile.py`, `test_container.py`, `test_settings.py`, `test_db_roles.py`, `test_migrations.py`, `security/test_db_privileges.py`, `ssh/test_fake_server.py`, `inventory/test_server_register.py`, `inventory/test_server_remove.py` | modify | Tests |
| `README.md`, `AGENTS.md`, `docs/server-setup.md` | modify | Docs |
| `workers/collector/.gitkeep` | delete | The part lives in `backend/app/collector` |

**Commands.** Everything runs from `backend/` unless stated otherwise:
- **BT** `<paths>` = `megoocolab-runner services run test -- uv run pytest <paths>`
- **IMG** = `megoocolab-runner services run image -- uv run pytest -m docker`
- **STK** = `megoocolab-runner services run stack -- uv run pytest -m stack`
- **MIG** = `megoocolab-runner services run migrate -- sh -c 'uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head'`

Every step ends with the full **BT** (no paths) green. Commit subjects are `type(area): sentence`, with a body that says why, ending in `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

## Step 1 — Settings: AUTH_SECRET_KEY optional, collector settings, the API still refuses to start without the key

**Files:** `backend/app/core/config.py`, `backend/app/main.py`, `backend/tests/test_settings.py`, `megoocolab.toml` (the `migrate` set).

Tests first, in `tests/test_settings.py`:
- Replace `test_auth_secret_key_is_required` with `test_auth_secret_key_is_optional_and_auth_key_names_it`: with `AUTH_SECRET_KEY` deleted, `Settings(database_url=URL).auth_secret_key is None`, and `.auth_key()` raises `RuntimeError` matching `AUTH_SECRET_KEY is not set`.
- `test_the_app_refuses_to_start_without_the_key`: `create_app(Settings(database_url=URL, auth_secret_key=None))` raises `RuntimeError` matching `AUTH_SECRET_KEY is not set`.
- `test_the_collector_settings_have_their_defaults`: with both variables deleted, `database_collector_url is None` and `collector_heartbeat_file == "/tmp/megooitadmin-collector.heartbeat"`.
- Keep `test_auth_secret_key_must_be_64_hex_characters`, `test_auth_key_is_32_bytes…` and `test_the_key_is_not_in_the_repr`.

Run **BT** `tests/test_settings.py`. **Expected:** the three new tests fail.

Implementation, in `config.py`:
```python
    # The collector role's URL, for the entrypoint's password step only (DATABASE_COLLECTOR_URL). The API never gets it.
    database_collector_url: str | None = None
    # Touched by the collector after each read of servers; its healthcheck reads its age.
    collector_heartbeat_file: str = "/tmp/megooitadmin-collector.heartbeat"
    # It encrypts the authenticator secrets. The API refuses to start without it (create_app and the entrypoint).
    # The collector never gets it.
    auth_secret_key: str | None = Field(default=None, repr=False)
```
The validator returns `None` unchanged. `auth_key()`:
```python
        if self.auth_secret_key is None:
            raise RuntimeError("AUTH_SECRET_KEY is not set. It encrypts the authenticator secrets: make up writes one into .env")
        return bytes.fromhex(self.auth_secret_key)
```
In `main.py`, as the first line of `create_app` after `settings = …`:
```python
    if settings.auth_secret_key is None:
        raise RuntimeError("AUTH_SECRET_KEY is not set: the API checks authenticator codes with it. Run make up, or see .env.example")
```
In `megoocolab.toml` `[services.migrate.env]`, remove the `AUTH_SECRET_KEY` line and its comment: Alembic no longer needs it.

Run **BT** `tests/test_settings.py` and **MIG**. **Expected:** both pass. Then the full **BT**.

**Commit:** `refactor(core): only the API needs AUTH_SECRET_KEY`. Body: the collector imports the app's settings and must not hold the key.

---

## Step 2 — The fake server keeps its host keys across restarts

**Files:** `tools/fake-server/entrypoint.sh`, `backend/tests/fake_server.py`, `backend/tests/ssh/test_fake_server.py`.

Add to `FakeServer` (all through `docker`, timeout 60):
```python
    def restart(self) -> None:          # docker restart <container>, then wait until ssh-keyscan inside succeeds (30 s)
    def pause(self) -> None:            # docker pause <container>
    def unpause(self) -> None:          # docker unpause <container>
    def kill_sessions(self, user: str = "megoo") -> None:   # exec("pkill", "-KILL", "-u", user); exit 0 or 1 accepted
    def loops(self, user: str = "megoo") -> int:            # int(exec("pgrep", "-c", "-u", user, "-f", "^sh -s [0-9]+$").stdout or 0)
```
`restart` waits with `exec("sh", "-c", "ssh-keyscan -T 2 -t ed25519 127.0.0.1 2>/dev/null | grep -q ssh-ed25519")` every 0.5 s until it returns 0, and fails the test after 30 s.

Test first, in `tests/ssh/test_fake_server.py`: `test_the_host_keys_survive_a_restart(fake_server)`: `before = fake_server.host_key()`, `fake_server.restart()`, then `fake_server.host_key() == before`, and a `client.connect(fake_server.host, fake_server.port, "megoo", before)` signs in (the authorized keys survive too). Run **BT** `tests/ssh/test_fake_server.py`. **Expected:** fails, because the key differs.

`entrypoint.sh`:
```sh
#!/bin/sh
# New host keys at the container's first start, kept when it restarts (swap-host-key still changes them on purpose),
# then sshd in the foreground as PID 1, logging to stderr (docker logs).
set -e
if [ ! -e /etc/ssh/.megoo-host-keys ]; then
  rm -f /etc/ssh/ssh_host_*
  ssh-keygen -A
  touch /etc/ssh/.megoo-host-keys
fi
mkdir -p /run/sshd
exec /usr/sbin/sshd -D -e
```
Run again. **Expected:** pass. Then the full **BT**.

**Commit:** `test(fake-server): host keys are made at the first start and kept across restarts`. Body: the collector's stack check restarts the fake server and expects it to stream again with the pinned key.

---

## Step 3 — Migration 0009: the collector role, the sample interval, server_status and their grants

**Files:** `backend/migrations/versions/0009_collector.py` (new, **Appendix B**), `backend/app/inventory/models.py`, `backend/tests/test_migrations.py`, `backend/tests/security/test_db_privileges.py`.

Models, in `inventory/models.py`. Add `SmallInteger` to the imports, and on `Server` add the check `CheckConstraint("metrics_interval_seconds BETWEEN 1 AND 10", name="servers_metrics_interval_seconds_check")` and:
```python
    # Seconds between two samples of the collector, 1 to 10.
    metrics_interval_seconds: Mapped[int] = mapped_column(SmallInteger, server_default=text("5"))
```
New model:
```python
UNREACHABLE_REASONS = ("unreachable", "key_refused", "ssh_error", "no_samples")
NOT_MONITORED_REASONS = ("not_an_ssh_server", "host_key_not_pinned", "host_key_changed")
STATE_CHECK = (
    "(state = 'reachable' AND reason IS NULL)"
    " OR (state = 'unreachable' AND reason IN ('unreachable', 'key_refused', 'ssh_error', 'no_samples'))"
    " OR (state = 'not_monitored' AND reason IN ('not_an_ssh_server', 'host_key_not_pinned', 'host_key_changed'))"
)

class ServerStatus(Base):
    """What the collector last saw of a server. Written only when the state or the reason changes."""
    __tablename__ = "server_status"
    __table_args__ = (
        PrimaryKeyConstraint("server_id", name="server_status_pkey"),
        ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE", name="server_status_server_id_fkey"),
        CheckConstraint(STATE_CHECK, name="server_status_state_check"),
    )
    server_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    state: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    since: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_sample_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

Tests first. In `test_migrations.py`, before `test_the_models_match_the_migrations`:
- `test_0009_goes_down_and_up_again`: downgrade to `"0008"`. Then `to_regclass('server_status')` is None, the column `metrics_interval_seconds` is absent from `information_schema.columns`, and `pg_roles` has no `megooitadmin_collector`. In `finally`, `upgrade_to_head()`. After that, all three are back.
- `test_the_database_refuses_an_interval_of_0_and_11_and_a_state_without_its_reason`: use a probe group and server named like the 0007 test's. An `UPDATE … SET metrics_interval_seconds = 0` and `= 11` each raise `IntegrityError` matching `servers_metrics_interval_seconds_check`. The default is 5. `INSERT INTO server_status (server_id, state) SELECT id, 'unreachable' …` raises `IntegrityError` matching `server_status_state_check`. Clean up in `finally`.

In `test_db_privileges.py`: generalise `_rows(sql, role=API_ROLE)`, and add `"server_status": frozenset({"SELECT"})` to `API_GRANTS`. Add:
```python
COLLECTOR_ROLE = "megooitadmin_collector"
# The collector writes samples and its state table, and flags a changed host key with its audit event.
COLLECTOR_GRANTS = {
    "metrics": frozenset({"INSERT"}),
    "servers": frozenset({"SELECT"}),
    "server_status": frozenset({"SELECT", "INSERT", "UPDATE"}),
    "audit_log": frozenset({"INSERT"}),
    "audit_chain_head": frozenset({"SELECT", "UPDATE"}),
}
COLLECTOR_COLUMN_GRANTS = {("servers", c, "UPDATE") for c in ("host_key_changed_at", "host_key_offered", "host_key_offered_at")}
COLUMN_GRANTS_SQL = ("SELECT c.relname, a.attname, x.privilege_type FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid"
    " JOIN pg_namespace n ON n.oid = c.relnamespace CROSS JOIN LATERAL aclexplode(a.attacl) x"
    f" WHERE n.nspname = 'public' AND x.grantee = {ROLE_OID}")
```
Tests:
- `test_the_collector_role_is_not_a_superuser_and_owns_nothing`
- `test_the_collector_roles_table_grants_are_the_declared_ones` (same query as the API one)
- `test_the_column_grants_are_the_declared_ones`: the collector's equal `COLLECTOR_COLUMN_GRANTS`, and the API role's are empty.
- `test_the_collector_role_can_insert_a_metric_and_cannot_read_users`: as owner, `SET LOCAL ROLE megooitadmin_collector`, insert a metric, then `SELECT 1 FROM users` raises 42501.
- `test_the_collector_role_may_flag_a_host_key_and_change_nothing_else_on_servers`: insert a probe server as owner and commit. Then, as the collector role, `SELECT … FOR UPDATE` and `UPDATE servers SET host_key_offered = NULL WHERE id = :id` succeed, and `UPDATE servers SET name = 'x'` raises 42501.
- `test_the_api_role_can_read_server_status`: `SET LOCAL ROLE megooitadmin_api; SELECT count(*) FROM server_status` works.

Run **BT** `tests/test_migrations.py tests/security/test_db_privileges.py`. **Expected:** the new tests fail.

Write `0009_collector.py` from **Appendix B**. Run **MIG**, then the same **BT** paths. **Expected:** pass, `test_the_models_match_the_migrations` included. If a grant test shows the mismatch path needs more (for example `SELECT` on `audit_log`), add only that grant to both the migration and `COLLECTOR_GRANTS`, and say why in the commit body. Then the full **BT**.

**Commit:** `feat(collector): migration 0009 adds the collector's role, the sample interval and server_status`.

---

## Step 4 — The entrypoint sets the collector role's password

**Files:** `backend/app/core/db_roles.py`, `backend/docker-entrypoint.sh`, `backend/tests/conftest.py`, `megoocolab.toml`, `tools/test-services/docker-compose.image.yml`, `backend/tests/test_db_roles.py`, `backend/tests/test_container.py`.

`db_roles.py`: add `COLLECTOR_ROLE = "megooitadmin_collector"`. Generalise `_api_password(url)` into `_password(url: str, role: str, variable: str) -> str`, with the messages `f"{variable} is not a database URL"`, `f"{variable} must connect as {role}"`, `f"{variable} has no password for {role}"` and `f"the password in {variable} must be printable ASCII"`. `_set_password(owner_url, role, verifier)` names the role in `ALTER ROLE` and in its "run the migrations" message. `sync_api_role_password(settings=None)` keeps its behaviour. Add:
```python
def sync_collector_role_password(settings: Settings | None = None) -> bool:
    """Gives the collector role LOGIN and the password of DATABASE_COLLECTOR_URL. False, and nothing changes, when the
    variable is not set."""
```
`main()` runs the API step, then the collector step. It prints `Set the password of megooitadmin_collector.`, or `DATABASE_COLLECTOR_URL is not set: megooitadmin_collector keeps no login, so the collector cannot sign in.` (exit 0). An `ApiRoleError` of either step prints `Could not set the password of <role>: <msg>` and exits 1.

`docker-entrypoint.sh`: the echo becomes `Setting the passwords of the API and collector roles...`, and the last lines are:
```sh
# The server never holds the owner's password or the collector's. docker compose exec still gets them (make migrate).
unset DATABASE_OWNER_URL DATABASE_COLLECTOR_URL
```
`megoocolab.toml`:
- `[services.test.env]`: `TEST_DATABASE_COLLECTOR_URL = "postgresql+asyncpg://megooitadmin_collector:megooitadmincollector@localhost:${DB_PORT}/megooitadmin_test"`
- `[services.image.env]`: `IMAGE_COLLECTOR_DATABASE_URL = "postgresql+asyncpg://megooitadmin_collector:megooitadmincollector@localhost:${DB_PORT}/megooitadmin"`

`docker-compose.image.yml`, backend environment: `DATABASE_COLLECTOR_URL: postgresql+asyncpg://megooitadmin_collector:megooitadmincollector@db:5432/${DB_NAME}`.

`conftest.py`: `pytest_configure` sets `os.environ["DATABASE_COLLECTOR_URL"] = _test_url("TEST_DATABASE_COLLECTOR_URL")`. `upgrade_to_head()` also calls `sync_collector_role_password()`. Update the module docstring.

Tests first. In `test_db_roles.py`:
- `test_after_the_step_the_collector_role_logs_in`: `sync_collector_role_password(Settings(database_url=…, database_owner_url=…, database_collector_url=<collector URL>))` returns True, and an asyncpg login as `megooitadmin_collector` returns that name.
- `test_a_collector_url_with_another_user_is_refused`: matches `DATABASE_COLLECTOR_URL must connect as megooitadmin_collector`.
- `test_without_the_collector_url_the_step_says_so_and_exits_0`: `python -m app.core.db_roles` with `DATABASE_COLLECTOR_URL` removed from the env exits 0, and its stdout holds `DATABASE_COLLECTOR_URL is not set`.
- Extend `restored_password` to restore the collector's password too.

In `test_container.py`:
- `test_the_collector_role_logs_in_and_is_not_a_superuser` (via `IMAGE_COLLECTOR_DATABASE_URL`).
- `test_the_server_holds_neither_the_owners_nor_the_collectors_url`: the names in `/proc/1/environ`, through `_exec("cat", "/proc/1/environ")`, include neither `DATABASE_OWNER_URL` nor `DATABASE_COLLECTOR_URL`.

Run **BT** `tests/test_db_roles.py`. **Expected:** fail (no function). Implement, then run **BT** `tests/test_db_roles.py`, the full **BT** and **IMG**. **Expected:** pass. `test_it_refuses_to_serve_without_the_auth_secret_key` still passes.

**Commit:** `feat(collector): the entrypoint gives the collector role its password`.

---

## Step 5 — The server API carries the sample interval and the monitoring state

**Files:** `backend/app/inventory/server_schemas.py`, `backend/app/inventory/servers.py`, `backend/tests/inventory/test_server_monitoring.py` (new), `test_server_register.py`, `test_server_remove.py`.

Schemas:
```python
MetricsInterval = Annotated[int, Field(ge=1, le=10)]
MonitoringState = Literal["reachable", "unreachable", "not_monitored"]

class Monitoring(BaseModel):
    state: MonitoringState
    reason: str | None
    since: datetime
    last_sample_at: datetime | None
```
`ServerIn.metrics_interval_seconds: MetricsInterval = 5`. `ServerPatch.metrics_interval_seconds: MetricsInterval | None = None`, added to `_not_null`'s fields. `ServerOut` gets `metrics_interval_seconds: int` and `monitoring: Monitoring | None` (None until the collector wrote a row).

`servers.py`:
- `FIELDS` gets `"metrics_interval_seconds"`, so create, change and delete events carry it.
- `create_server` passes `metrics_interval_seconds=body.metrics_interval_seconds`.
- `_out(server, group_name, tags, access, status: ServerStatus | None = None)` fills both fields.
- `list_servers` and `get_server` select `ServerStatus` with `.outerjoin(ServerStatus, ServerStatus.server_id == Server.id)`.
- `update_server` reads `await db.scalar(select(ServerStatus).where(ServerStatus.server_id == server.id))` for its answer.

Tests first:
- In `test_server_register.py`, `SERVER_KEYS` gets `"metrics_interval_seconds"` and `"monitoring"`. The created change gets `"metrics_interval_seconds": {"before": None, "after": 5}`, and the answer has `metrics_interval_seconds == 5` and `monitoring is None`.
- In `test_server_remove.py`, the deleted change gets `"metrics_interval_seconds": {"before": 5, "after": None}`. New: `test_removing_a_server_removes_its_monitoring_state`: the owner inserts a `server_status` row, the API delete works, and the row is gone (the cascade runs for the API role).
- In `test_server_monitoring.py`:
  - `test_a_registered_interval_is_stored_and_recorded` (2)
  - `test_an_interval_outside_1_to_10_answers_422` (parametrized: 0, 11, "x"; and `null` in a PATCH)
  - `test_changing_the_interval_records_server_changed`: the change equals `{"metrics_interval_seconds": {"before": 5, "after": 10}}`
  - `test_an_operator_cannot_change_the_interval` (403)
  - `test_monitoring_is_returned_once_the_collector_wrote_it`: the owner inserts `('reachable', NULL, now(), now())`. Both `GET /api/servers/{id}` and the list show `monitoring.state == "reachable"`, `reason is None` and `last_sample_at` set.

Use `api`, `clock`, `signed_in`, `make_group`, `make_server`, `add_grant` and `events` as `test_server_edit.py` does.

Run **BT** `tests/inventory`. **Expected:** fail. Implement, then run again. **Expected:** pass. Then the full **BT** (the audit- and permission-coverage suites included).

**Commit:** `feat(inventory): servers carry their sample interval and monitoring state`.

---

## Step 6 — Parsing the loop's lines

**Files:** `backend/app/collector/__init__.py`, `backend/app/collector/parse.py`, `backend/tests/collector/test_collector_parse.py`.

`__init__.py`:
```python
"""The metrics collector (python -m app.collector): one SSH stream per server, each sample published on Valkey and
written to metrics. Run one collector: a second one would publish every sample twice."""
from functools import cache
from pathlib import Path

SCRIPT = Path(__file__).with_name("script.sh")

@cache
def script() -> bytes:
    return SCRIPT.read_bytes()
```
(`script.sh` comes in step 8. `script()` is only called from then on.)

`parse.py` contract (the line format is in **Appendix A**):
```python
MAX_LINE = 256 * 1024
MAX_NAME = 255
MAX_CORES = 256          # cpu rows kept: the whole-server row and 256 cores
MAX_DEVICES = 64         # interfaces, disks and filesystems kept, each

class Lines:
    """Cuts a byte stream into lines. A line longer than max_line is skipped up to its newline and counted."""
    def __init__(self, max_line: int = MAX_LINE) -> None: ...
    too_long: int
    def feed(self, chunk: bytes) -> list[bytes]   # complete lines without b"\n"

Counter = NonNegativeInt
Load = Annotated[float, Field(ge=0, allow_inf_nan=False)]
class Memory(BaseModel): total: Counter; available: Counter; swap_total: Counter; swap_free: Counter
class Raw(BaseModel):     # frozen, extra="ignore"
    v: Literal[1]
    uptime: float = Field(ge=0, allow_inf_nan=False)
    load: tuple[Load, Load, Load]
    cpu: tuple[tuple[str, Counter, Counter, Counter, Counter, Counter, Counter, Counter, Counter], ...]
    mem: Memory
    net: tuple[tuple[str, Counter, Counter], ...]
    disk: tuple[tuple[str, Counter, Counter, Counter], ...]
    fs: tuple[tuple[str, Counter, Counter, Counter, Counter, Counter], ...]
    # model_validator(mode="before"): for each list, drop rows whose first item is a str longer than MAX_NAME, then keep
    # the first MAX_CORES + 1 cpu rows and MAX_DEVICES of the others.

def parse(line: bytes) -> Raw    # ValueError (pydantic's ValidationError is one) for anything that is not a sample
```
`Lines` keeps the partial tail between feeds. When the tail grows past `max_line` without a newline, it drops the tail, counts one, and drops bytes until the next newline.

Tests (`APPENDIX_A_LINE` is the example of Appendix A):
- `test_the_example_line_parses`
- `test_a_line_split_across_chunks_is_joined`
- `test_a_line_longer_than_256_kb_is_skipped_and_counted_and_the_next_one_arrives`
- `test_malformed_lines_are_refused` (parametrized: `b"not json"`, version 2, a negative counter, a missing `mem`, NaN load)
- `test_too_many_devices_are_cut_to_their_limits` (300 cpu rows, then 257 kept; 100 interfaces, then 64)
- `test_a_name_longer_than_255_characters_is_dropped`
- `test_odd_names_are_kept_as_given` (`'eth"0'`, `"/mnt/a\\b"`, `"/média"`)

Run **BT** `tests/collector/test_collector_parse.py`: fails, then passes after implementing.

**Commit:** `feat(collector): the collector parses the loop's JSON lines with size limits`.

---

## Step 7 — Computing the readings

**Files:** `backend/app/collector/compute.py`, `backend/tests/collector/test_collector_compute.py`.

Contract: `def readings(previous: Raw | None, current: Raw) -> tuple[Reading, ...]`. The rules and the worked example are in **Appendix C**: constants `WHOLE_DISK` (the regex of the Decisions) and `def counted_interface(name) -> bool` (not `lo`, not `veth*`).

Tests (Appendix C's `FIRST` and `SECOND` as `Raw.model_validate({...})`):
- `test_the_first_sample_carries_only_load_memory_and_filesystems`: exactly the 13 readings of the table.
- `test_two_samples_give_the_expected_rates`: the 24 readings, compared as a `{(metric, instance): value}` dict.
- `test_a_counter_that_went_down_skips_every_rate`
- `test_an_uptime_that_went_back_skips_every_rate` (a reboot)
- `test_loopback_veth_partitions_loop_and_device_mapper_are_left_out`
- `test_a_filesystem_without_inodes_has_no_inode_percentage` (btrfs reports 0)
- `test_memory_without_mem_available_has_no_available_or_used` (available 0)

Run **BT** `tests/collector/test_collector_compute.py`: fails, then passes after implementing.

**Commit:** `feat(collector): rates and percentages are computed from two raw samples`.

---

## Step 8 — The server-side loop and `script_output`

**Files:** `backend/app/collector/script.sh` (**Appendix A**), `backend/app/ssh/client.py`, `backend/tests/collector/test_collector_script.py`.

`client.py`:
```python
SCRIPT_CHUNK = 65536

@asynccontextmanager
async def script_output(conn: Connection, script: bytes, interval: int) -> AsyncIterator[AsyncIterator[bytes]]:
    """Runs `sh -s <interval>` with the script on stdin and its errors discarded, and yields its output as chunks of
    bytes. Leaving closes the channel. Raises SshError when the channel cannot start or breaks."""
```
It raises `ValueError` unless `interval` is an `int` from 1 to 10. Then it calls `conn.create_process(f"sh -s {interval}", encoding=None, stderr=asyncssh.DEVNULL)` (`asyncssh.Error`, raised as `SshError`), writes the script, then `write_eof()`, and yields `_chunks(process)`. That async generator reads `process.stdout.read(SCRIPT_CHUNK)` until `b""`, raising `SshError` from `asyncssh.Error`/`OSError`. In `finally`, `process.close()` and `await asyncio.wait_for(process.wait_closed(), 5)`, with `asyncssh.Error`, `OSError` and `TimeoutError` suppressed.

Tests (`fake_server` fixture; connect with `client.connect(fake_server.host, fake_server.port, "megoo", fake_server.host_key())`; read through `Lines` and `parse` with `asyncio.timeout(15)`):
- `test_the_loop_prints_a_valid_line_every_interval`: 3 lines at interval 1. Each parses, each uptime step is between 0.9 and 3.0, and `compute.readings(first, second)` has `cpu.used_percent`, `mem.total_bytes`, `load.1m` and `disk.used_percent` for `/`.
- `test_it_runs_without_sudo`: as `megoo-nosudo` it streams too. `b"sudo" not in script()`. While it runs, `fake_server.exec("ps", "-o", "user=", "-C", "sh")` lists `megoo-nosudo`.
- `test_the_loop_ends_after_its_channel_closes`: after leaving both contexts, `fake_server.loops()` reaches 0 within 6 s.
- `test_the_loop_refuses_an_interval_outside_1_to_10`: `fake_server.exec("sh", "-s", "11", input=script().decode(), user="megoo").returncode == 2`, and `script_output(conn, script(), 0)` raises `ValueError`.
- `test_the_loop_writes_no_file`: `find / -xdev -newer /tmp/marker -type f` as root, run before and after 2 lines, adds nothing under `/home/megoo` or `/tmp` (`touch /tmp/marker` first).

Run **BT** `tests/collector/test_collector_script.py tests/security/test_host_key_pinning.py`: fails, then passes after implementing.

**Commit:** `feat(collector): a read-only shell loop prints one JSON sample per interval`.

---

## Step 9 — Throttle and the state table

**Files:** `backend/app/collector/throttle.py`, `backend/app/collector/state.py`, `backend/tests/conftest.py`, `backend/tests/collector_helpers.py` (new), `backend/tests/collector/test_collector_state.py`.

`throttle.py`:
```python
class Throttle:
    """True at most once per `every` seconds: for warnings that would otherwise repeat on every sample."""
    def __init__(self, every: float = 60.0, clock: Callable[[], float] = time.monotonic) -> None
    def __call__(self) -> bool
```
`state.py`:
```python
State = Literal["reachable", "unreachable", "not_monitored"]
class StatusBook:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None
    async def load(self) -> None                         # reads every row into memory; raises on a DB error
    def known(self, server_id: UUID) -> tuple[str, str | None] | None
    def known_ids(self) -> set[UUID]
    async def set(self, server_id, state: State, reason: str | None = None, *, last_sample_at: datetime | None = None) -> None
    async def retry(self) -> None                        # writes what set() could not
    def forget(self, server_id: UUID) -> None
```
`set` returns at once when `(state, reason)` equals the known value or the pending one. Otherwise it upserts:
`insert(ServerStatus).values(server_id=…, state=…, reason=…, since=func.now(), last_sample_at=…).on_conflict_do_update(index_elements=["server_id"], set_={"state": ex.state, "reason": ex.reason, "since": func.now(), "last_sample_at": ex.last_sample_at}, where=or_(ServerStatus.state != ex.state, ServerStatus.reason.is_distinct_from(ex.reason)))`, then commits and records the value as known. On `IntegrityError` with sqlstate `23503` (the server is gone) it forgets the server. On any other `SQLAlchemyError`/`OSError` it keeps the value pending and warns through a `Throttle`. It never raises.

`conftest.py`, new fixture:
```python
@pytest.fixture
async def collector_sessions(database_at_head, monkeypatch):
    """Sessions as megooitadmin_collector, the collector's role. open_connection flags a changed host key through
    them too, as it does in the collector's process."""
    # engine on os.environ["DATABASE_COLLECTOR_URL"], NullPool; async_sessionmaker(expire_on_commit=False);
    # monkeypatch app.inventory.connection.SessionLocal; yield; dispose
```
`tests/collector_helpers.py`:
- `FAST = Timings(...)`: add it in step 11, when `Timings` exists.
- `async def pinned_server(fake_server, name, *, username="megoo", interval=1, os="linux", pinned=True) -> Server`: `make_group(f"{name}-group")` and `make_server(group.id, name, address=fake_server.host, port=fake_server.port, os=os)`. Then, as owner, set `host_key=fake_server.host_key()`, `host_key_pinned_at=now()` (when pinned), `connection_settings={"username": username}` and `metrics_interval_seconds=interval`, and return the row read again.
- `async def status_of(server_id) -> tuple[str, str | None] | None` (as owner)
- `async def metric_rows(server_id) -> int` (as owner)
- `async def eventually(check, timeout=15.0, every=0.1) -> None`: awaits or calls `check` until it returns truthy. Otherwise it raises `AssertionError("not within …")`.

Tests (`clean_auth`, `collector_sessions`):
- `test_a_change_is_written_once_with_its_time`: two identical `set`s give one row, and `since` stays the same.
- `test_since_moves_only_when_the_state_or_reason_changes`
- `test_a_server_that_was_removed_is_forgotten_without_error`
- `test_with_the_database_down_the_change_waits_and_is_written_by_retry`: a book on an engine at `postgresql+asyncpg://x:y@127.0.0.1:1/down_test` keeps the value pending. Point `book.sessions` at the real sessions and call `retry()`: the row is there.
- `test_load_reads_the_rows_so_a_restart_rewrites_nothing`
- `test_the_throttle_lets_one_through_per_period` (fake clock)

Run **BT** `tests/collector/test_collector_state.py`: fails, then passes.

**Commit:** `feat(collector): server_status is written only when a server's state changes`.

---

## Step 10 — The buffered writer

**Files:** `backend/app/collector/writer.py`, `backend/tests/collector/test_collector_writer.py`.

```python
MAX_SAMPLES = 10_000
class Writer:
    def __init__(self, sessions, *, max_samples: int = MAX_SAMPLES, every: float = 1.0) -> None
    pending: int (property)   dropped: int
    def add(self, sample: Sample) -> None    # never blocks; a full buffer drops the oldest and warns once a minute
    async def flush(self) -> int             # everything buffered, one write_samples() and one commit; samples written
    async def run(self) -> None              # sleep(every), flush(), forever
```
`flush` takes the whole buffer. On `SQLAlchemyError`/`OSError` it puts the batch back in front of what arrived meanwhile, as `deque(chain(batch, self._buffer), maxlen=max_samples)` (which keeps the newest), counts the overflow in `dropped`, warns through a `Throttle`, and returns 0.

Tests (`clean_auth`, `collector_sessions`; samples of a `pinned_server`-less random UUID are fine, because `metrics` has no foreign key):
- `test_a_batch_is_one_insert`: monkeypatch `app.collector.writer.write_samples` with a counting wrapper. Three samples give one call, and `metric_rows` is 3 × readings.
- `test_with_the_database_down_the_buffer_keeps_the_newest`: `max_samples=3` on the down engine, add 5, then `pending == 3`, `dropped == 2`, and `flush()` returns 0 and keeps 3. Switch to the real sessions and `flush() == 3`. The rows are those of samples 3 to 5.
- `test_flush_of_an_empty_buffer_does_nothing`

Run **BT** `tests/collector/test_collector_writer.py`: fails, then passes.

**Commit:** `feat(collector): samples are written in batches, and the newest 10,000 wait out a database outage`.

---

## Step 11 — One server's stream

**Files:** `backend/app/collector/stream.py` (**Appendix D**), `backend/tests/collector_helpers.py` (`FAST`, `parts`), `backend/tests/collector/test_collector_stream.py`.

In `collector_helpers.py`, add `FAST` (see Decisions) and `def parts(sessions, valkey=None) -> tuple[Publisher, Writer, StatusBook]`, plus `@asynccontextmanager async def streaming(stream, writer)`. That helper runs `stream.run()` and `writer.run()` as tasks, and on exit cancels both, awaits them and flushes the writer.

Tests (`clean_auth`, `collector_sessions`, `fake_server`; `Stream(Target.of(server), publisher=, writer=, status=, timings=FAST)`):
- `test_samples_reach_a_subscriber_and_the_metrics_table`: subscribe with `app.metrics.fanout.subscribe`. A sample arrives within 10 s, `metric_rows > 0` eventually, and the status is `("reachable", None)`.
- `test_a_killed_ssh_session_reconnects`: wait for a sample, note `fake_server.sign_ins()`, call `fake_server.kill_sessions()`, then a new sign-in and a new sample arrive.
- `test_a_paused_server_is_unreachable_with_no_samples_and_comes_back`: wait for reachable, then `fake_server.pause()` (`unpause()` in `finally`). The first observed state (poll every 0.05 s) is `("unreachable", "no_samples")`. After `unpause()`, it is `("reachable", None)` within 30 s.
- `test_a_wrong_account_is_key_refused`: username `megoo-unknown`, then `("unreachable", "key_refused")` within 10 s.
- `test_a_swapped_host_key_flags_the_server_once_and_stops`: `fake_server.swap_host_key()` before running. `run()` returns by itself within 15 s. `events("server.host_key_mismatch")` has exactly one event with `actor_type == "system"` and `actor_name == "collector"`. The row's `host_key_changed_at` is set, and the status is `("not_monitored", "host_key_changed")`.
- `test_samples_are_published_while_the_database_is_down`: the writer on the down engine, a sample still reaches the subscriber, and `writer.pending > 0`.
- `test_with_valkey_down_publish_returns_and_warns_once`: `Publisher(from_url("valkey://127.0.0.1:1/0"))`. Two publishes return within 3 s, and caplog shows one warning.
- `test_a_line_that_does_not_parse_is_counted_and_never_logged`: unit test with a fake `chunks` generator yielding `b"secret-text\n"` and then a valid line. `stream.bad_lines == 1`, and `"secret-text"` is not in `caplog.text`.

Run **BT** `tests/collector/test_collector_stream.py`: fails, then passes.

**Commit:** `feat(collector): each server streams samples on one channel and reconnects with backoff`.

---

## Step 12 — The supervisor

**Files:** `backend/app/collector/supervisor.py` (**Appendix E**), `backend/tests/collector/test_collector_supervisor.py`.

Tests (`clean_auth`, `collector_sessions`, `fake_server`; `Supervisor(sessions=collector_sessions, publisher=, writer=, status=, timings=FAST, heartbeat=tmp_path / "hb")`; call `await sup.poll()` directly; `await sup.stop()` in `finally`):
- `test_a_new_server_starts_streaming_and_a_removed_one_stops`: after `poll`, `targets` holds it and rows arrive. The owner deletes the server, `poll` runs, `targets == {}`, and `fake_server.loops()` reaches 0 within 6 s.
- `test_three_servers_give_three_sign_ins_and_three_loops`: three `pinned_server`s, then sign-ins grow by 3 and `loops() == 3`.
- `test_windows_unpinned_and_flagged_servers_are_not_monitored_without_a_sign_in`: their statuses are `not_an_ssh_server`, `host_key_not_pinned` and `host_key_changed`, `sign_ins()` is unchanged after 2 s, and `targets == {}`.
- `test_a_changed_interval_restarts_the_loop`: wait for a sample. The owner sets the interval to 2, then `poll`: one new sign-in, `targets[id].interval == 2`, and `loops()` settles back to 1.
- `test_poll_touches_the_heartbeat_and_retries_pending_states`
- `test_sign_ins_are_limited_to_20`: `Supervisor(...).sign_ins._value == 20`, and streams get that semaphore.

Run **BT** `tests/collector/test_collector_supervisor.py`: fails, then passes.

**Commit:** `feat(collector): the supervisor follows the servers table every 10 seconds`.

---

## Step 13 — Start-up, SIGTERM and the healthcheck

**Files:** `backend/app/collector/__main__.py`, `backend/app/collector/health.py`, `backend/tests/collector/test_collector_main.py`.

`health.py`:
```python
MAX_AGE = 30.0
def healthy(path: Path, now: float | None = None) -> bool   # the file exists and its mtime is under MAX_AGE old
def main() -> int                                           # 0 or 1 for Path(get_settings().collector_heartbeat_file)
if __name__ == "__main__": sys.exit(main())
```
`__main__.py`: as **Appendix E**'s `serve()`/`main()`.

Tests:
- `test_healthy_follows_the_age_of_the_heartbeat` (unit: missing file, 10 s old, 31 s old)
- `test_the_collector_starts_without_the_key_reports_healthy_and_stops_on_sigterm` (`clean_auth`): start `subprocess.Popen([sys.executable, "-m", "app.collector"], cwd=BACKEND)` with an env of `os.environ` minus `AUTH_SECRET_KEY` and `DATABASE_OWNER_URL`, plus `DATABASE_URL=os.environ["DATABASE_COLLECTOR_URL"]` and `COLLECTOR_HEARTBEAT_FILE=<tmp>`. The heartbeat appears within 20 s, and `python -m app.collector.health` with the same env exits 0. After `send_signal(SIGTERM)`, the process exits 0 within 10 s, and its stderr holds `The collector stopped.`

Run **BT** `tests/collector/test_collector_main.py`: fails, then passes.

**Commit:** `feat(collector): python -m app.collector runs the supervisor and stops cleanly on SIGTERM`.

---

## Step 14 — The `collector` Compose service, its password and the stack checks

**Files:** `docker-compose.yml`, `docker-compose.build.yml`, `Makefile`, `.env.example`, `tools/stacks/dev.env`, `tools/stacks/e2e.env`, `megoocolab.toml` (`stack`), `backend/tests/test_stack.py`, `backend/tests/test_makefile.py`.

Compose: **Appendix F**. `dev.env` and `e2e.env` get `POSTGRES_COLLECTOR_PASSWORD=megooitadmincollector`. In `megoocolab.toml` `[services.stack]`, the description names `collector`, and the env gets `POSTGRES_COLLECTOR_PASSWORD = "megooitadmincollector"`.

`.env.example`, after the API password:
```
# The password of megooitadmin_collector, the restricted role the collector writes samples as. Letters and digits
# only. The backend sets it at every start.
POSTGRES_COLLECTOR_PASSWORD=
```
`Makefile` `.env` rule:
- A new file gets a fourth random value `col` (16 bytes). The check becomes `grep -Eqx '[0-9a-f]{160}'` over pw+api+key+col, and the lines are written in the order `POSTGRES_PASSWORD`, `POSTGRES_API_PASSWORD`, `POSTGRES_COLLECTOR_PASSWORD`, `AUTH_SECRET_KEY`.
- An older file gets a third block, after the key block, that appends `POSTGRES_COLLECTOR_PASSWORD=<32 hex>` when it is missing, and prints `Added POSTGRES_COLLECTOR_PASSWORD to .env: the collector writes samples as the restricted role megooitadmin_collector.` Update the comment above the rule.

`test_makefile.py`:
- The created-file regex gets the collector line.
- The older-env tests expect `API, KEY, COLLECTOR` appended (and `KEY, COLLECTOR` for the one with both passwords).
- The complete env includes `POSTGRES_COLLECTOR_PASSWORD=ghi`.
- New: `test_the_env_rule_adds_only_the_collector_password_to_an_env_without_it`.

`test_stack.py` (tests first):
- `NETWORKS["collector"] = {"core", "servers"}`, and the service test is renamed `test_the_stack_has_exactly_its_six_services`.
- Replace the ssh_key test with `test_the_backend_mounts_the_ssh_key_volume_and_the_collector_reads_it`: backend `[("volume", "ssh_key", "/var/lib/megooitadmin/ssh")]` and not read-only, collector the same target with `read_only` True, and no other service mounts it.
- `test_docker_compose_yml_pulls…`: collector `image == f"{GHCR}backend:${{MEGOOITADMIN_VERSION:-latest}}"` and no build.
- The build overlay test: services `{"backend", "frontend", "collector"}`, and collector `== {"image": "megooitadmin-backend:${MEGOOITADMIN_VERSION:-dev}", "pull_policy": "never"}`.
- `test_the_stack_runs_the_images_it_built…`: the collector runs `megooitadmin-backend:{project}`.
- `test_the_collector_runs_the_backends_image_as_its_own_role`: entrypoint `["python", "-m", "app.collector"]`; `DATABASE_URL` starts with `postgresql+asyncpg://megooitadmin_collector:`; neither `AUTH_SECRET_KEY` nor `DATABASE_OWNER_URL` is in its environment; `depends_on` backend and valkey `service_healthy`; healthcheck `["CMD", "python", "-m", "app.collector.health"]`.
- `test_the_backend_sets_the_collector_password_and_does_not_hold_it`: `_psql_as_collector("SELECT current_user")` gives `megooitadmin_collector`, and the backend's `/proc/1/environ` has no `DATABASE_COLLECTOR_URL`.
- In `_resolves`, the collector uses the Python lookup. Add `("collector", "db", True)`, `("collector", "valkey", True)` and `("frontend", "collector", False)`.
- `test_the_collector_streams_the_fake_server_and_survives_restarts_and_a_network_drop(owner)`: **Appendix G**. Place it right before `test_after_sign_out_pages_redirect_to_login`.

Run **STK**. **Expected:** the new and changed tests fail. Implement, then run **STK**, **BT** `tests/test_makefile.py` and **IMG**. **Expected:** pass.

**Commit:** `feat(stack): a collector service streams every pinned server's metrics`.

---

## Step 15 — Docs, and workers/collector goes

**Files:** `README.md`, `AGENTS.md`, `docs/server-setup.md`, `workers/collector/.gitkeep` (deleted).

- `README.md`:
  - "Run it": the stack also starts the collector.
  - The `.env` bullet: a third password, `POSTGRES_COLLECTOR_PASSWORD`, added to an older `.env` by `make up` and `make upgrade`.
  - "Upgrade": `make upgrade` starts the collector too, so nobody has to act.
  - "Servers": a bullet. Once a Linux server's host key is pinned, the collector signs in as its account from the platform's address and keeps one channel open, sampling every 5 seconds by default (1 to 10, `metrics_interval_seconds` in the API). A server without a sample for 30 seconds is unreachable. Run one collector.
- `AGENTS.md`, "Migrations": a table the collector needs is granted to `megooitadmin_collector` in its migration and declared in `COLLECTOR_GRANTS`, column grants in `COLLECTOR_COLUMN_GRANTS`. "Checks": the `test` set also sets `TEST_DATABASE_COLLECTOR_URL`.
- `docs/server-setup.md`, a new section `## What the collector runs`, before "Run it again". It covers:
  - The command `sh -s <interval>`, with `app/collector/script.sh` sent on stdin, so nothing is installed.
  - What it reads: `/proc/uptime`, `/proc/stat`, `/proc/loadavg`, `/proc/meminfo`, `/proc/net/dev`, `/proc/diskstats` and `/proc/mounts`, and `df -kP`/`df -iP` on local filesystems only.
  - No sudo, no file written, and it ends by itself when the connection closes.
  - The collector signs in from the same address as the backend, so `--from` does not change.
  - How to see it: `ps -u megoo -o pid,args`.
  - Linux 3.14 or later (for `MemAvailable`).
- `git rm workers/collector/.gitkeep`.

Run **BT** `tests/test_workflows.py` and `uv run --project backend pytest tools/release` from the repository root. **Expected:** pass.

**Commit:** `docs(collector): what the collector runs on a server, and how it is set up`.

---

## Final verification
From `backend/`: **BT**, **MIG**, **IMG**, **STK**. From the repository root: `make test-security` and `make test`.

---

## Appendix A — `backend/app/collector/script.sh` and its line

```sh
# MegooITAdmin's metrics loop (backend/app/collector/script.sh). The collector sends it on stdin to `sh -s <interval>`
# as the server's account: it reads /proc and runs df on local filesystems only, needs no sudo and writes no file. It
# prints one JSON line every <interval> seconds and ends when its output closes.
set -f
interval=$1
case $interval in [1-9]|10) ;; *) echo 'usage: sh -s <1-10>' >&2; exit 2 ;; esac

# Local filesystems only, so a hung network mount cannot stall the loop. Escaped names (\040 …) are skipped.
MOUNTS='($3 ~ /^(ext2|ext3|ext4|xfs|btrfs|f2fs|jfs|vfat|exfat)$/ || ($3 == "overlay" && $2 == "/")) && $2 !~ /\\/ && !seen[$2]++ && n++ < 64 { print $2 }'

SAMPLE='
function s(x) { return x ~ /^[0-9]+$/ ? x : "0" }
function d(x) { return x ~ /^[0-9]+(\.[0-9]+)?$/ ? x : "0" }
function q(x,   i, c, o) { o = ""; for (i = 1; i <= length(x); i++) { c = substr(x, i, 1); if (c == "\\" || c == "\"") o = o "\\" c; else if (c >= " ") o = o c }; return "\"" o "\"" }
function add(list, item) { return list == "" ? item : list "," item }
FNR == 1 { f++ }
f == 1 { up = d($1) }
f == 2 && $1 ~ /^cpu[0-9]*$/ && ncpu++ < 257 { cpu = add(cpu, "[" q($1) "," s($2) "," s($3) "," s($4) "," s($5) "," s($6) "," s($7) "," s($8) "," s($9) "]") }
f == 3 { load = d($1) "," d($2) "," d($3) }
f == 4 { m[$1] = $2 }
f == 5 && FNR > 2 { i = index($0, ":"); name = substr($0, 1, i - 1); gsub(/ /, "", name); split(substr($0, i + 1), a, " ")
  if (name != "lo" && name !~ /^veth/ && length(name) <= 255 && nnet++ < 64) net = add(net, "[" q(name) "," s(a[1]) "," s(a[9]) "]") }
f == 6 && $3 ~ /^(sd[a-z]+|vd[a-z]+|xvd[a-z]+|hd[a-z]+|nvme[0-9]+n[0-9]+|mmcblk[0-9]+)$/ && ndisk++ < 64 { disk = add(disk, "[" q($3) "," s($6) "," s($10) "," s($13) "]") }
f == 7 && $1 == "#K" { part = "k"; next }
f == 7 && $1 == "#I" { part = "i"; next }
f == 7 && $1 != "Filesystem" && NF >= 6 && part == "k" { mt = $NF; if (!(mt in size)) order[++nfs] = mt; size[mt] = s($(NF-4)); used[mt] = s($(NF-3)); avail[mt] = s($(NF-2)) }
f == 7 && $1 != "Filesystem" && NF >= 6 && part == "i" { ino[$NF] = s($(NF-4)); iused[$NF] = s($(NF-3)) }
END {
  for (k = 1; k <= nfs; k++) { mt = order[k]; fs = add(fs, "[" q(mt) "," size[mt] "," used[mt] "," avail[mt] "," s(ino[mt]) "," s(iused[mt]) "]") }
  printf "{\"v\":1,\"uptime\":%s,\"load\":[%s],\"cpu\":[%s],\"mem\":{\"total\":%s,\"available\":%s,\"swap_total\":%s,\"swap_free\":%s},\"net\":[%s],\"disk\":[%s],\"fs\":[%s]}\n", up, load, cpu, s(m["MemTotal:"]), s(m["MemAvailable:"]), s(m["SwapTotal:"]), s(m["SwapFree:"]), net, disk, fs
}'

while :; do
  set -- $(awk "$MOUNTS" /proc/mounts)
  {
    if [ $# -gt 0 ]; then echo '#K'; df -kP -- "$@"; echo '#I'; df -iP -- "$@"; fi
  } 2>/dev/null </dev/null | awk "$SAMPLE" /proc/uptime /proc/stat /proc/loadavg /proc/meminfo /proc/net/dev /proc/diskstats - || exit 0
  sleep "$interval" || exit 0
done
```
If an awk on the fake server (mawk) refuses a construct, change only that construct, keep the output format, and name the change in the commit body.

The line (compact, one per interval). `APPENDIX_A_LINE` in the tests:
```json
{"v":1,"uptime":12345.67,"load":[0.5,0.25,0.125],"cpu":[["cpu",100,0,50,800,50,0,0,0],["cpu0",50,0,25,400,25,0,0,0]],"mem":{"total":8000000,"available":6000000,"swap_total":1000000,"swap_free":750000},"net":[["eth0",1000,2000]],"disk":[["sda",0,0,0]],"fs":[["/",100000,40000,60000,1000,250]]}
```
cpu rows hold user, nice, system, idle, iowait, irq, softirq and steal. net rows hold rx and tx bytes. disk rows hold sectors read, sectors written and ms doing I/O. fs rows hold size, used and available in kB, then inodes and used inodes.

## Appendix B — `backend/migrations/versions/0009_collector.py`
```python
"""collector: the collector's role, the sample interval of each server and the monitoring state

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLLECTOR = "megooitadmin_collector"
STATE_CHECK = (
    "(state = 'reachable' AND reason IS NULL)"
    " OR (state = 'unreachable' AND reason IN ('unreachable', 'key_refused', 'ssh_error', 'no_samples'))"
    " OR (state = 'not_monitored' AND reason IN ('not_an_ssh_server', 'host_key_not_pinned', 'host_key_changed'))"
)


def upgrade() -> None:
    # Like megooitadmin_api (0003): LOGIN and the password come from the entrypoint, from DATABASE_COLLECTOR_URL.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{COLLECTOR}') THEN
                CREATE ROLE {COLLECTOR} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
            END IF;
        END
        $$
        """
    )
    op.add_column(
        "servers", sa.Column("metrics_interval_seconds", sa.SmallInteger(), server_default=sa.text("5"), nullable=False)
    )
    op.create_check_constraint(
        "servers_metrics_interval_seconds_check", "servers", "metrics_interval_seconds BETWEEN 1 AND 10"
    )
    op.create_table(
        "server_status",
        sa.Column("server_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("since", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_sample_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(STATE_CHECK, name="server_status_state_check"),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE", name="server_status_server_id_fkey"),
        sa.PrimaryKeyConstraint("server_id", name="server_status_pkey"),
    )
    op.execute("GRANT SELECT ON server_status TO megooitadmin_api")

    op.execute(f"GRANT USAGE ON SCHEMA public TO {COLLECTOR}")
    op.execute(f"GRANT INSERT ON metrics TO {COLLECTOR}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON server_status TO {COLLECTOR}")
    # It reads the servers, and flags a changed host key (open_connection): FOR UPDATE needs UPDATE on one column.
    op.execute(f"GRANT SELECT ON servers TO {COLLECTOR}")
    op.execute(f"GRANT UPDATE (host_key_changed_at, host_key_offered, host_key_offered_at) ON servers TO {COLLECTOR}")
    # The audit writer, for server.host_key_mismatch.
    op.execute(f"GRANT INSERT ON audit_log TO {COLLECTOR}")
    op.execute(f"GRANT SELECT, UPDATE ON audit_chain_head TO {COLLECTOR}")


def downgrade() -> None:
    op.drop_table("server_status")
    op.drop_constraint("servers_metrics_interval_seconds_check", "servers", type_="check")
    op.drop_column("servers", "metrics_interval_seconds")
    op.execute(f"DROP OWNED BY {COLLECTOR}")
    op.execute(f"DROP ROLE {COLLECTOR}")
```

## Appendix C — `compute.readings` rules and the worked example
Always:
- `load.1m`, `load.5m` and `load.15m` from `load`.
- `mem.total_bytes = total*1024`. When `available > 0`: `mem.available_bytes = available*1024`, `mem.used_bytes` = total − available (in bytes), and `mem.used_percent = used/total*100` (only when total > 0).
- `swap.total_bytes = swap_total*1024` and `swap.used_bytes = (swap_total − swap_free)*1024`, clamped at 0.
- Per fs row (instance = mount): `disk.total_bytes = size*1024`, `disk.used_bytes = used*1024`, `disk.used_percent = used/(used+avail)*100` (when used+avail > 0) and `disk.inodes_used_percent = iused/inodes*100` (when inodes > 0).

Rates, only when `previous` is given, `current.uptime > previous.uptime` and no counter of a name present in both went down; `dt` is the uptime difference:
- CPU, per row present in both: the deltas u, n, sy, id, io, irq, sirq, st, and `total` = their sum (row skipped when 0). `cpu.used_percent = (total − id − io)/total*100`, with instance `""` for row `cpu` and the row name for `cpuN`. For row `cpu` only: `cpu.user_percent = (u+n)/total*100`, `cpu.system_percent = (sy+irq+sirq)/total*100`, `cpu.iowait_percent = io/total*100` and `cpu.steal_percent = st/total*100`. Percentages are clamped to 0 to 100.
- Net, interfaces with `counted_interface`: `net.rx_bytes_per_sec` and `net.tx_bytes_per_sec`, the deltas over dt.
- Disks matching `WHOLE_DISK`: `diskio.read_bytes_per_sec = Δsectors_read*512/dt`, `diskio.write_bytes_per_sec = Δsectors_written*512/dt` and `diskio.busy_percent = Δio_ms/(dt*1000)*100`, clamped to 0 to 100.

`FIRST` = Appendix A's line with uptime 100.0, plus `["lo",5,5]`, `["veth1",5,5]`, `["sda1",0,0,0]`, `["loop0",0,0,0]` and `["dm-0",0,0,0]`. `SECOND` = uptime 105.0, cpu `["cpu",200,0,100,1400,100,0,0,0]` and `["cpu0",100,0,50,700,50,0,0,0]`, eth0 `[6000,12000]`, sda `[10240,20480,2500]`, and everything else the same.

Expected for `readings(None, FIRST)` (13):

| metric | instance | value |
|---|---|---|
| load.1m / 5m / 15m | | 0.5 / 0.25 / 0.125 |
| mem.total_bytes | | 8192000000 |
| mem.available_bytes | | 6144000000 |
| mem.used_bytes | | 2048000000 |
| mem.used_percent | | 25.0 |
| swap.total_bytes | | 1024000000 |
| swap.used_bytes | | 256000000 |
| disk.total_bytes | / | 102400000 |
| disk.used_bytes | / | 40960000 |
| disk.used_percent | / | 40.0 |
| disk.inodes_used_percent | / | 25.0 |

`readings(FIRST, SECOND)` adds these 11 (24 in total):

| metric | instance | value |
|---|---|---|
| cpu.used_percent | | 18.75 |
| cpu.used_percent | cpu0 | 18.75 |
| cpu.user_percent | | 12.5 |
| cpu.system_percent | | 6.25 |
| cpu.iowait_percent | | 6.25 |
| cpu.steal_percent | | 0.0 |
| net.rx_bytes_per_sec | eth0 | 1000.0 |
| net.tx_bytes_per_sec | eth0 | 2000.0 |
| diskio.read_bytes_per_sec | sda | 1048576.0 |
| diskio.write_bytes_per_sec | sda | 2097152.0 |
| diskio.busy_percent | sda | 50.0 |

## Appendix D — `backend/app/collector/stream.py`
```python
"""One server's stream: sign in through open_connection, run the loop on one channel, turn each line into a Sample,
publish it and buffer it for the writer. A closed channel, or no sample for no_sample_after seconds, closes the
connection; the next try waits 1, 2, 4 ... up to 60 seconds with jitter, and a sample resets the wait."""

import asyncio
import logging
import random
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from valkey.asyncio import Valkey
from valkey.exceptions import ValkeyError

from app.audit import Actor
from app.collector import compute, script
from app.collector.parse import Lines, parse
from app.collector.state import StatusBook
from app.collector.throttle import Throttle
from app.collector.writer import Writer
from app.inventory.connection import ConnectionRefused, open_connection
from app.inventory.models import Server
from app.metrics.fanout import publish
from app.metrics.samples import Sample
from app.ssh import client
from app.ssh.keys import KeyFileError

logger = logging.getLogger(__name__)
ACTOR = Actor.system("collector")
MAX_SIGN_INS = 20


@dataclass(frozen=True)
class Timings:
    no_sample_after: float = 30.0
    backoff_first: float = 1.0
    backoff_max: float = 60.0
    jitter: float = 0.2

    def wait(self, delay: float) -> float:
        return delay * random.uniform(1 - self.jitter, 1 + self.jitter)


@dataclass(frozen=True)
class Target:
    """What a stream needs of its server. Any change restarts the stream."""

    server_id: UUID
    address: str
    port: int
    username: str
    host_key: str
    interval: int

    @classmethod
    def of(cls, server: Server) -> "Target":
        return cls(server.id, server.address, server.port, server.connection_settings["username"], server.host_key,
                   server.metrics_interval_seconds)

    def server(self) -> Server:
        """A transient Server for open_connection, which reads the row again only to flag a changed key."""
        return Server(id=self.server_id, os="linux", address=self.address, port=self.port, host_key=self.host_key,
                      host_key_changed_at=None, connection_settings={"username": self.username})


class Publisher:
    """Publishes on Valkey, never raises: with Valkey down the samples are still written."""

    def __init__(self, valkey: Valkey | None, timeout: float = 1.0) -> None:
        self.valkey, self.timeout, self._warned = valkey, timeout, Throttle()

    async def publish(self, sample: Sample) -> None:
        if self.valkey is None:
            return
        try:
            await asyncio.wait_for(publish(self.valkey, sample), self.timeout)
        except (ValkeyError, OSError) as error:  # TimeoutError is an OSError
            if self._warned():
                logger.warning("Could not publish samples on Valkey: %s", error)


class Stream:
    def __init__(self, target: Target, *, publisher: Publisher, writer: Writer, status: StatusBook,
                 timings: Timings = Timings(), sign_ins: asyncio.Semaphore | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.target, self.publisher, self.writer, self.status, self.timings = target, publisher, writer, status, timings
        self.sign_ins = sign_ins or asyncio.Semaphore(MAX_SIGN_INS)
        self.clock = clock
        self.failure: str | None = None       # the reason of the last failure, None after a sample
        self.last_sample = clock()            # monotonic; the task's start counts as one
        self.last_sample_at: datetime | None = None
        self.samples = 0
        self.bad_lines = 0
        self._bad, self._key = Throttle(), Throttle()

    async def run(self) -> None:
        """Streams until cancelled, or until the server cannot be tried any more (changed host key)."""
        watch = asyncio.create_task(self._watch())
        try:
            delay = self.timings.backoff_first
            while True:
                before = self.samples
                try:
                    await self._session()
                except client.HostKeyChanged:
                    await self.status.set(self.target.server_id, "not_monitored", "host_key_changed")
                    return
                except ConnectionRefused as refused:
                    await self.status.set(self.target.server_id, "not_monitored", refused.detail)
                    return
                if self.samples > before:
                    delay = self.timings.backoff_first
                await asyncio.sleep(self.timings.wait(delay))
                delay = min(delay * 2, self.timings.backoff_max)
        finally:
            watch.cancel()

    async def _session(self) -> None:
        try:
            async with AsyncExitStack() as stack:
                async with self.sign_ins:  # at most MAX_SIGN_INS sign-ins at once
                    conn = await stack.enter_async_context(
                        open_connection(self.target.server(), actor=ACTOR, source=None))
                    chunks = await stack.enter_async_context(
                        client.script_output(conn, script(), self.target.interval))
                await self._read(chunks)
        except client.HostKeyChanged:
            raise
        except client.SshFailure as failure:
            self.failure = failure.reason
        except KeyFileError as error:
            self.failure = "ssh_error"
            if self._key():
                logger.error("%s", error)

    async def _read(self, chunks: AsyncIterator[bytes]) -> None:
        lines, previous, got = Lines(), None, False
        loop = asyncio.get_running_loop()
        try:
            async with asyncio.timeout(self.timings.no_sample_after) as deadline:
                async for chunk in chunks:
                    skipped = lines.too_long
                    for line in lines.feed(chunk):
                        try:
                            raw = parse(line)
                        except ValueError:
                            self._bad_line()
                            continue
                        sample = Sample(time=datetime.now(UTC), server_id=self.target.server_id,
                                        readings=compute.readings(previous, raw))
                        previous = raw
                        deadline.reschedule(loop.time() + self.timings.no_sample_after)
                        await self._got(sample)
                        got = True
                    for _ in range(lines.too_long - skipped):
                        self._bad_line()
        except TimeoutError:
            self.failure = "no_samples"
            return
        # The channel ended. Without a single sample, the loop could not run there.
        self.failure = None if got else "ssh_error"

    def _bad_line(self) -> None:
        # The line's text is never logged: it comes from the server.
        self.bad_lines += 1
        if self._bad():
            logger.warning("Dropped %d lines from server %s that were not samples", self.bad_lines, self.target.server_id)

    async def _got(self, sample: Sample) -> None:
        self.samples += 1
        self.last_sample, self.last_sample_at, self.failure = self.clock(), sample.time, None
        await self.publisher.publish(sample)
        self.writer.add(sample)
        await self.status.set(self.target.server_id, "reachable", None, last_sample_at=sample.time)

    async def _watch(self) -> None:
        while True:
            await asyncio.sleep(self.timings.no_sample_after / 4)
            if self.clock() - self.last_sample >= self.timings.no_sample_after:
                await self.status.set(self.target.server_id, "unreachable", self.failure or "no_samples",
                                      last_sample_at=self.last_sample_at)
```

## Appendix E — `supervisor.py` and `__main__.py`
```python
# supervisor.py
"""Reads servers every 10 seconds and keeps one stream per server that can be tried. A server that cannot be tried
gets not_monitored and no connection attempt."""
POLL_EVERY = 10.0

def refusal_of(server: Server) -> str | None:
    if server.os != "linux":
        return "not_an_ssh_server"
    if server.host_key is None:
        return "host_key_not_pinned"
    if server.host_key_changed_at is not None:
        return "host_key_changed"
    return None

class Supervisor:
    def __init__(self, *, sessions, publisher, writer, status, timings=Timings(), poll_every=POLL_EVERY,
                 heartbeat: Path | None = None, max_sign_ins=MAX_SIGN_INS) -> None
        # self.sign_ins = asyncio.Semaphore(max_sign_ins); self._streams: dict[UUID, tuple[Target, asyncio.Task]] = {}
        # self._stopping: set[asyncio.Task] = set(); self._warned = Throttle()
    @property
    def targets(self) -> dict[UUID, Target]: ...   # streams whose task is not done
    async def poll(self) -> None:
        # rows = (await session.scalars(select(Server))).all() in `async with self.sessions() as session`
        # for each row: refusal -> self._stop(id); await status.set(id, "not_monitored", refusal); continue
        #   target = Target.of(row); current = self._streams.get(id)
        #   keep when current[0] == target and (task not done, or it returned normally: it stopped by itself);
        #   a task that ended with an exception is logged (logger.warning("The stream of %s stopped: %r", id, exc))
        #   and restarted; otherwise self._stop(id) and self._start(target)
        # ids in self._streams but not in rows -> self._stop(id); ids in status.known_ids() not in rows -> forget
        # await status.retry(); if heartbeat: heartbeat.touch()
    def _start(self, target) -> None   # Stream(..., sign_ins=self.sign_ins); asyncio.create_task(stream.run())
    def _stop(self, server_id) -> None # pop, cancel, add to _stopping with add_done_callback(_stopping.discard)
    async def run(self) -> None        # forever: poll (SQLAlchemyError/OSError -> throttled warning, no heartbeat); sleep
    async def stop(self) -> None       # stop every stream and gather _stopping (return_exceptions=True)
```
```python
# __main__.py
"""python -m app.collector: the collector's process. SIGTERM closes the channels, writes what is buffered and exits."""
SHUTDOWN_FLUSH = 5.0

async def serve(stop: asyncio.Event) -> None:
    settings = get_settings()
    status = StatusBook(SessionLocal)
    while not stop.is_set():          # wait for the database, without giving up
        try:
            await status.load()
            break
        except (SQLAlchemyError, OSError) as error:
            logger.warning("Waiting for the database: %s", error)
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), 5)
    if stop.is_set():
        return
    try:
        valkey = valkey_client(settings)
    except RuntimeError as error:
        logger.warning("%s Samples are not published.", error)
        valkey = None
    writer = Writer(SessionLocal)
    supervisor = Supervisor(sessions=SessionLocal, publisher=Publisher(valkey), writer=writer, status=status,
                            heartbeat=Path(settings.collector_heartbeat_file))
    tasks = [asyncio.create_task(writer.run()), asyncio.create_task(supervisor.run())]
    try:
        await stop.wait()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await supervisor.stop()
        with suppress(TimeoutError):
            await asyncio.wait_for(writer.flush(), SHUTDOWN_FLUSH)
        if valkey is not None:
            await valkey.aclose()

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    async def run() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        logger.info("The collector started.")
        await serve(stop)
        logger.info("The collector stopped.")

    asyncio.run(run())

if __name__ == "__main__":
    main()
```

## Appendix F — Compose
`docker-compose.yml`. Backend environment, after `DATABASE_OWNER_URL`:
```yaml
      # The entrypoint gives the collector's role this password, then unsets it before the server starts.
      DATABASE_COLLECTOR_URL: postgresql+asyncpg://megooitadmin_collector:${POSTGRES_COLLECTOR_PASSWORD:?POSTGRES_COLLECTOR_PASSWORD is not set. Run make up or see .env.example}@db:5432/megooitadmin
```
New service, after `backend`:
```yaml
  collector:
    # The backend's image with another command: one SSH stream per server, each sample published on Valkey and
    # written to metrics. Run one collector: a second one would publish every sample twice.
    image: ghcr.io/mmhy2003/megooitadmin-backend:${MEGOOITADMIN_VERSION:-latest}
    restart: unless-stopped
    entrypoint: ["python", "-m", "app.collector"]
    environment:
      DATABASE_URL: postgresql+asyncpg://megooitadmin_collector:${POSTGRES_COLLECTOR_PASSWORD:?POSTGRES_COLLECTOR_PASSWORD is not set. Run make up or see .env.example}@db:5432/megooitadmin
      VALKEY_URL: valkey://valkey:6379/0
    volumes:
      # The platform's SSH key, read-only: the backend makes it.
      - ssh_key:/var/lib/megooitadmin/ssh:ro
    networks: [core, servers]
    depends_on:
      # A healthy backend has run the migrations and set this role's password.
      backend:
        condition: service_healthy
      valkey:
        condition: service_healthy
    healthcheck:
      # Passes while the collector read the servers within the last 30 seconds.
      test: ["CMD", "python", "-m", "app.collector.health"]
      <<: *healthcheck-timing
```
`docker-compose.build.yml`:
```yaml
  collector:
    # The image the backend service builds: never pulled.
    image: megooitadmin-backend:${MEGOOITADMIN_VERSION:-dev}
    pull_policy: never
```

## Appendix G — the stack's streaming check
Helpers in `test_stack.py`:
- `_owner_sql(sql) -> str`: psql as `megooitadmin`, like `_audit_of_server`.
- `_psql_as_collector(sql)`: like `_psql_as_api_role`, with `POSTGRES_COLLECTOR_PASSWORD`.
- `_wait(check, timeout, every=2)`: `time.sleep` polling, failing with a message.
- `_newest(server_id) -> str`: `SELECT coalesce(max(time), '-infinity') FROM metrics WHERE server_id = '<uuid>'`.
- `_db_now() -> str`: `SELECT now()`.
- `_newer(server_id, t)`: `SELECT max(time) > '<t>' FROM metrics WHERE server_id = '<uuid>'` gives `t`.
- `_monitoring(owner, server_id)`: `owner.get(f"/api/servers/{id}").json()["monitoring"]`.

The test:
1. Authorize the backend's public key on the fake server, as the pin test does. Register `fake-server-metrics` (address `fake-server`, port 22) in a new group `metrics-lab`, then fetch and pin its key.
2. Wait up to 60 s until `metrics` has rows for it, and `monitoring.state == "reachable"`.
3. `SUBSCRIBE_PROBE` (python `-c` in the backend container, server id in `sys.argv[1]`) subscribes with `app.metrics.fanout.subscribe` and prints `received` once a sample arrives within 20 s. Expect `received`.
4. `t = _db_now()`, then `_compose_with_fake_server("restart", "fake-server")`. Within 90 s, `_newer(id, t)`.
5. `t = _db_now()`, then `_compose("restart", "collector")`. Within 90 s, `_newer(id, t)`.
6. Drop the network: the container is `_compose_with_fake_server("ps", "-q", "fake-server")`, the network `f"{project}_servers"`. Run `docker network disconnect <network> <container>`. Within 90 s, `monitoring.state == "unreachable"`. Then, in `finally` too, `docker network connect --alias fake-server <network> <container>`. Within 150 s, `monitoring.state == "reachable"` and `_newer(id, t_reconnect)`.
