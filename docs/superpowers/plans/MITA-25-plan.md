# MITA-25 — Metrics storage: hypertable, rollups, retention, Valkey service — implementation plan

## Goal
Metric samples written to a `metrics` hypertable can be read back as real-time 1-minute and 1-hour rollups. Retention and compression jobs are scheduled. A `valkey` Compose service and a small pub/sub helper carry each sample live, one channel per server.

## Architecture
Migration `0008_metrics.py` creates the `metrics` hypertable, the `metrics_1m` continuous aggregate (over `metrics`) and the `metrics_1h` continuous aggregate (over `metrics_1m`, weighted average), their refresh, compression and retention policies, and `SELECT` grants for `megooitadmin_api`. The new package `backend/app/metrics/` holds the ORM model, the Pydantic `Sample`/`Reading`, the store functions (`write_samples`, `read_rollup`) and the Valkey fan-out (`channel`, `encode`, `decode`, `publish`, `subscribe`). `backend/app/core/valkey.py` builds the async client from the optional `VALKEY_URL` setting. Compose gets a `valkey` service on `core` only. The `test` service set gets its own Valkey through a new Compose file.

## Facts checked (repo at `1a0a174`, web on 2026-11-25)
- The last migration is `0007_host_key_pinning.py`. `test_migrations.py` requires `0008_<slug>.py` with `down_revision = "0007"`. Hand-written TimescaleDB SQL goes through `op.execute` (see `0002_audit_log.py`, which uses `create_hypertable(..., by_range('time', ...), create_default_indexes => false)`).
- `test_migrations.py` runs sync and queries through `_fetch(sql)` / `_execute(sql)` as the owner. `test_the_models_match_the_migrations` runs `alembic check`. Alembic does not reflect views, and continuous aggregates are views, so they stay out of `Base.metadata`.
- `tests/security/test_db_privileges.py`: `API_GRANTS` must equal the API role's grants on every relation in `public`, views included (it reads `pg_class.relacl`). Every table in `Base.metadata` must be in it.
- `tests/conftest.py` sets the app's environment in `pytest_configure` from `TEST_*` variables. It provides `owner_session()`, `_owner_engine()` and the session fixture `database_at_head`. Test folders have no `__init__.py`, so new test file names must be unique across `tests/`, and shared helpers live in the root `conftest.py` (as `clean_auth` does). No second `conftest.py`.
- `Settings` (`app/core/config.py`) reads only the environment. Optional URLs follow the `database_owner_url: str | None = None` pattern, and a missing one raises `RuntimeError` naming the variable (`alembic_url`).
- The app has no logger yet. Use `logging.getLogger(__name__)`.
- `docker-compose.yml` has an `x-healthcheck-timing` anchor and networks `edge`, `core` (internal), `servers`, `exec`, `sandbox`. `test_stack.py` pins services and networks in `NETWORKS`, and `test_the_stack_has_exactly_the_four_phase_0_services` checks the service list.
- The backend image installs from `uv.lock` (`uv sync --frozen --no-dev`), so the new dependency must be in the lock.
- **Valkey image:** `valkey/valkey:9` is the current major version (9.2). Its Dockerfile turns protected mode off at build time (`sed` on `protected-mode` in `config.c`), so another container on the network connects without a password. The image ships `valkey-cli`, and its working directory is `/data`, where `--appendonly yes` writes.
- **valkey-py (asyncio):** `valkey.asyncio.from_url("valkey://host:6379/0")`. `await client.publish(channel, data)` returns the number of receivers. `async with client.pubsub() as pubsub:` closes the pub/sub connection on exit. `await pubsub.subscribe(*channels)`, `await pubsub.get_message(timeout=...)` (returns `None` on timeout), `pubsub.listen()` is an async generator of dicts `{"type": "message", "channel": b"…", "data": b"…"}`. `await client.pubsub_numsub(ch)` returns `[(b"ch", n)]`. Close a client with `await client.aclose()`.
- **TimescaleDB:** `CREATE MATERIALIZED VIEW … WITH (timescaledb.continuous) … WITH NO DATA` may run inside Alembic's transaction (`WITH DATA` may not). `CALL refresh_continuous_aggregate(...)` and `CALL run_job(...)` may **not** run in a transaction block, so tests call them on an AUTOCOMMIT connection. For a continuous aggregate's policy, `timescaledb_information.jobs.hypertable_name` is the *materialization* hypertable, so tests map it back through `timescaledb_information.continuous_aggregates.materialization_hypertable_name`.

## Decisions made in this plan (within the design)
- **Refresh end offsets:** `metrics_1m` refreshes `start_offset => 24 hours, end_offset => 1 minute`, and `metrics_1h` refreshes `start_offset => 7 days, end_offset => 1 hour`. The bucket still in progress is served by the real-time part.
- **Chunk interval of a rollup** is set on its materialization hypertable, which is looked up in `timescaledb_information.continuous_aggregates`.
- **Value check:** `value > '-Infinity'::float8 AND value < 'Infinity'::float8`. PostgreSQL sorts NaN above Infinity, so this one check refuses NaN and both infinities.
- **`subscribe` waits for Valkey's confirmation** of every channel before it yields. A publish made after entering the context is therefore never lost to a race.
- **The client is built per call** (`valkey_client()`), not cached: an asyncio client belongs to one event loop. The caller closes it.
- **Tests that read rollups of "now"** use sample times in the next hour. They stay above any refresh watermark, so the test proves real-time reads whatever the background jobs did. Tests that run jobs pause the metrics jobs first (fixture `metrics_jobs_paused`) and restore them afterwards.

## File map

| File | Change | Responsibility |
|---|---|---|
| `backend/pyproject.toml`, `backend/uv.lock` | modify | Add `valkey` |
| `backend/app/core/config.py` | modify | `valkey_url: str \| None = None` |
| `backend/app/core/valkey.py` | create | `valkey_client()` |
| `tools/test-services/docker-compose.valkey.yml` | create | Valkey of the `test` set |
| `megoocolab.toml` | modify | `test` set: Valkey file, `VALKEY_PORT`, `TEST_VALKEY_URL`, description. `stack` description names valkey |
| `backend/tests/conftest.py` | modify | `VALKEY_URL` from `TEST_VALKEY_URL`; `owner_call()`; `metrics_jobs_paused` fixture |
| `backend/migrations/versions/0008_metrics.py` | create | Table, hypertable, rollups, policies, grants |
| `backend/app/metrics/__init__.py` | create | Package docstring |
| `backend/app/metrics/models.py` | create | `Metric` ORM model; `metrics_1m`, `metrics_1h` `Table`s on their own `MetaData` |
| `backend/app/models.py` | modify | `import app.metrics.models` |
| `backend/app/metrics/samples.py` | create | `Reading`, `Sample` |
| `backend/app/metrics/store.py` | create | `Bucket`, `write_samples`, `read_rollup` |
| `backend/app/metrics/fanout.py` | create | `channel`, `encode`, `decode`, `publish`, `subscribe` |
| `backend/tests/test_settings.py`, `backend/tests/test_valkey.py` | modify / create | Settings and client tests |
| `backend/tests/test_migrations.py` | modify | `0008` tests |
| `backend/tests/security/test_db_privileges.py` | modify | `API_GRANTS`, insert refused |
| `backend/tests/metrics/test_samples.py`, `test_store.py`, `test_policies.py`, `test_fanout.py` | create | Behaviour tests |
| `docker-compose.yml` | modify | `valkey` service, `valkey_data` volume, backend `VALKEY_URL` and `depends_on` |
| `backend/tests/test_stack.py` | modify | Five services, valkey checks, fan-out in the backend container, API role reads `metrics_1m` |
| `README.md`, `AGENTS.md` | modify | Valkey in `make up`; the `test` set includes Valkey |

All commands run from `backend/` unless stated otherwise. Commits use `type(area): sentence`, a body that says why, and end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

## Step 1 — Valkey client, `VALKEY_URL` setting and a Valkey in the test set

**Files:** `backend/pyproject.toml`, `backend/uv.lock`, `backend/app/core/config.py`, `backend/app/core/valkey.py` (new), `tools/test-services/docker-compose.valkey.yml` (new), `megoocolab.toml`, `backend/tests/conftest.py`, `backend/tests/test_settings.py`, `backend/tests/test_valkey.py` (new), `AGENTS.md`.

1. Add the dependency: `uv add valkey` (from `backend/`; it updates `pyproject.toml` and `uv.lock`).
2. Write the tests first.

`backend/tests/test_settings.py` (append):
```python
def test_valkey_url_is_optional(monkeypatch):
    monkeypatch.delenv("VALKEY_URL", raising=False)
    assert Settings(database_url=URL).valkey_url is None


def test_the_valkey_client_without_valkey_url_names_the_variable(monkeypatch):
    from app.core.valkey import valkey_client

    monkeypatch.delenv("VALKEY_URL", raising=False)
    with pytest.raises(RuntimeError, match="VALKEY_URL"):
        valkey_client(Settings(database_url=URL))
```
`backend/tests/test_valkey.py` (new):
```python
from app.core.valkey import valkey_client


async def test_the_client_reaches_the_test_sets_valkey():
    client = valkey_client()
    try:
        assert await client.ping() is True
    finally:
        await client.aclose()
```
Run `megoocolab-runner services run test -- uv run pytest tests/test_settings.py tests/test_valkey.py`. **Expected failure:** `ModuleNotFoundError: app.core.valkey` (and `valkey_url` missing).

3. Implement.

`app/core/config.py`, after `database_owner_url`:
```python
    # Valkey, for live metric fan-out. Optional: nothing at start-up needs it, and the image check runs without one.
    valkey_url: str | None = None
```
`app/core/valkey.py`:
```python
"""The async Valkey client. Valkey carries live metric samples (app.metrics.fanout)."""

from valkey.asyncio import Valkey, from_url

from app.core.config import Settings, get_settings


def valkey_client(settings: Settings | None = None) -> Valkey:
    """A new client on VALKEY_URL. An asyncio client belongs to one event loop, so it is never shared: the caller
    closes it with `await client.aclose()`."""
    settings = settings or get_settings()
    if not settings.valkey_url:
        raise RuntimeError("VALKEY_URL is not set. The backend reaches Valkey through it (valkey://valkey:6379/0).")
    return from_url(settings.valkey_url)
```
`tools/test-services/docker-compose.valkey.yml`:
```yaml
# Valkey for backend pytest (the test set in megoocolab.toml), on 127.0.0.1:${VALKEY_PORT}. No password, as in the stack.
services:
  valkey:
    image: valkey/valkey:9
    ports:
      - "127.0.0.1:${VALKEY_PORT}:6379"
    healthcheck:
      test: ["CMD", "valkey-cli", "ping"]
      interval: 2s
      timeout: 5s
      retries: 60
```
`megoocolab.toml`, `[services.test]`:
```toml
description = "PostgreSQL with TimescaleDB and pgvector, Valkey, and the fake sshd server, for backend pytest"
compose = ["tools/test-services/docker-compose.yml", "tools/test-services/docker-compose.valkey.yml", "tools/fake-server/docker-compose.test.yml"]
ports = ["DB_PORT", "SSH_PORT", "VALKEY_PORT"]
```
and in `[services.test.env]`: `TEST_VALKEY_URL = "valkey://localhost:${VALKEY_PORT}/0"`. The fake-server file's comment says its paths are relative to `tools/test-services`, the first file, which stays true.

`tests/conftest.py`: add
```python
def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.exit(f"{name} is not set. Run the suite as: {RUN_TESTS}", returncode=2)
    return value
```
Make `_test_url` use `_required(name)` for its first lines, and in `pytest_configure` add `os.environ["VALKEY_URL"] = _required("TEST_VALKEY_URL")`. Update the module docstring: the set also starts Valkey and sets `TEST_VALKEY_URL`, passed on as `VALKEY_URL`.

`AGENTS.md`, "Checks", Backend bullet: add "The `test` set starts PostgreSQL with TimescaleDB and pgvector, Valkey and the fake server."

4. Run `megoocolab-runner services run test -- uv run pytest tests/test_settings.py tests/test_valkey.py tests/test_workflows.py`. **Expected:** pass. Then run the full suite `megoocolab-runner services run test -- uv run pytest`. **Expected:** green.

**Commit:** `feat(core): the backend can reach Valkey through VALKEY_URL`. Body: the metrics fan-out needs a Valkey client, and the test set needs its own Valkey.

---

## Step 2 — Migration 0008: the `metrics` hypertable, the rollups, their policies and grants

**Files:** `backend/migrations/versions/0008_metrics.py` (new), `backend/app/metrics/__init__.py` (new), `backend/app/metrics/models.py` (new), `backend/app/models.py`, `backend/tests/test_migrations.py`, `backend/tests/security/test_db_privileges.py`.

### Tests first

`tests/test_migrations.py`, appended before `test_the_models_match_the_migrations`:
```python
METRICS_RELATIONS = ("metrics", "metrics_1m", "metrics_1h")
# Policy jobs of the three relations. For a rollup, jobs.hypertable_name is its materialization hypertable.
METRICS_JOBS_SQL = (
    "SELECT j.job_id, j.proc_name, coalesce(c.view_name, j.hypertable_name) AS relation, j.schedule_interval, j.config"
    " FROM timescaledb_information.jobs j LEFT JOIN timescaledb_information.continuous_aggregates c"
    " ON c.materialization_hypertable_name = j.hypertable_name"
    " WHERE coalesce(c.view_name, j.hypertable_name) IN ('metrics', 'metrics_1m', 'metrics_1h')"
)
# (job, relation, config key, value, runs every or None when the default is fine)
METRICS_JOBS = [
    ("policy_retention", "metrics", "drop_after", "48 hours", "1 hour"),
    ("policy_compression", "metrics", "compress_after", "1 hour", None),
    ("policy_refresh_continuous_aggregate", "metrics_1m", "start_offset", "24 hours", "1 minute"),
    ("policy_compression", "metrics_1m", "compress_after", "2 days", None),
    ("policy_retention", "metrics_1m", "drop_after", "30 days", None),
    ("policy_refresh_continuous_aggregate", "metrics_1h", "start_offset", "7 days", "1 hour"),
    ("policy_compression", "metrics_1h", "compress_after", "30 days", None),
    ("policy_retention", "metrics_1h", "drop_after", "13 months", None),
]


def _metrics_relations() -> list:
    return _fetch(f"SELECT {', '.join(f'to_regclass({r!r})' for r in METRICS_RELATIONS)}")


def test_0008_goes_down_and_up_again():
    command.downgrade(_config(), "0007")
    try:
        assert _metrics_relations() == [(None, None, None)]
        assert _fetch(f"SELECT count(*) FROM ({METRICS_JOBS_SQL}) j") == [(0,)]
    finally:
        upgrade_to_head()
    assert _metrics_relations() == [METRICS_RELATIONS]


def test_metrics_is_a_hypertable_on_time_with_6_hour_chunks():
    assert _fetch(
        "SELECT column_name, time_interval = INTERVAL '6 hours' FROM timescaledb_information.dimensions"
        " WHERE hypertable_name = 'metrics'"
    ) == [("time", True)]


def test_both_rollups_are_real_time_with_their_chunk_intervals():
    rows = _fetch(
        "SELECT c.view_name, c.materialized_only, d.time_interval FROM timescaledb_information.continuous_aggregates c"
        " JOIN timescaledb_information.dimensions d ON d.hypertable_name = c.materialization_hypertable_name"
        " WHERE c.view_name IN ('metrics_1m', 'metrics_1h') ORDER BY c.view_name"
    )
    assert [(r[0], r[1]) for r in rows] == [("metrics_1h", False), ("metrics_1m", False)]
    assert _fetch(
        "SELECT d.time_interval = INTERVAL '30 days' FROM timescaledb_information.continuous_aggregates c"
        " JOIN timescaledb_information.dimensions d ON d.hypertable_name = c.materialization_hypertable_name"
        " WHERE c.view_name = 'metrics_1h'"
    ) == [(True,)]
    assert _fetch(
        "SELECT d.time_interval = INTERVAL '1 day' FROM timescaledb_information.continuous_aggregates c"
        " JOIN timescaledb_information.dimensions d ON d.hypertable_name = c.materialization_hypertable_name"
        " WHERE c.view_name = 'metrics_1m'"
    ) == [(True,)]


def test_the_metrics_jobs_are_scheduled():
    actual = sorted((row[1], row[2]) for row in _fetch(METRICS_JOBS_SQL))
    assert actual == sorted((job, relation) for job, relation, *_ in METRICS_JOBS)
    for job, relation, key, value, every in METRICS_JOBS:
        every_check = f", j.schedule_interval = INTERVAL '{every}'" if every else ""
        rows = _fetch(
            f"SELECT (j.config->>'{key}')::interval = INTERVAL '{value}'{every_check} FROM ({METRICS_JOBS_SQL}) j"
            f" WHERE j.proc_name = '{job}' AND j.relation = '{relation}'"
        )
        assert rows == [(True, True) if every else (True,)], (job, relation)


def _insert_metric(metric: str, value: str) -> None:
    _execute(
        "INSERT INTO metrics (time, server_id, metric, instance, value)"
        f" VALUES (now(), gen_random_uuid(), '{metric}', '', {value})"
    )


def test_the_database_refuses_a_bad_metric_name_and_a_value_that_is_not_finite():
    with pytest.raises(IntegrityError, match="metrics_metric_check"):
        _insert_metric("CPU.used", "1")
    with pytest.raises(IntegrityError, match="metrics_metric_check"):
        _insert_metric("a" * 65, "1")
    for bad in ("'NaN'::float8", "'Infinity'::float8", "'-Infinity'::float8"):
        with pytest.raises(IntegrityError, match="metrics_value_check"):
            _insert_metric("cpu.used_percent", bad)
```

`tests/security/test_db_privileges.py`: add to `API_GRANTS`
```python
    # The backend only reads metrics. The collector's role writes them (MITA-26).
    "metrics": frozenset({"SELECT"}),
    "metrics_1m": frozenset({"SELECT"}),
    "metrics_1h": frozenset({"SELECT"}),
```
and a test:
```python
async def test_the_api_role_cannot_insert_a_metric():
    async with owner_session() as session:
        await session.execute(text(f"SET LOCAL ROLE {API_ROLE}"))
        with pytest.raises(DBAPIError) as exc:
            await session.execute(
                text("INSERT INTO metrics (time, server_id, metric, value) VALUES (now(), gen_random_uuid(), 'cpu.used_percent', 1)")
            )
        await session.rollback()
    assert exc.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE
```
Run `megoocolab-runner services run test -- uv run pytest tests/test_migrations.py tests/security/test_db_privileges.py`. **Expected failures:** the new tests fail (`to_regclass` is None, no jobs, no `metrics` table), `test_every_table_of_the_models_is_declared` passes, and `test_the_api_roles_table_grants_are_the_declared_ones` fails (declared grants missing).

### Implementation

`app/metrics/__init__.py`: `"""Metric samples: storage in the metrics hypertable, rollups, and live fan-out through Valkey."""`

`app/metrics/models.py`:
```python
"""The metrics hypertable, one row per value, and its two rollups.

metrics has no foreign key to servers: a cascade could not reach the rollups, and deletes across compressed chunks
are slow. A removed server's samples age out with the retention windows (migration 0008).
The rollups are continuous aggregates, that is views, so they are plain Tables outside Base.metadata: Alembic
neither creates nor compares them.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, Double, MetaData, PrimaryKeyConstraint, Table, Text, Uuid, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

METRIC_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$"
METRIC_MAX_LENGTH = 64
INSTANCE_MAX_LENGTH = 255


class Metric(Base):
    __tablename__ = "metrics"
    __table_args__ = (
        # Every read filters on server, metric and instance, then a time range. A repeated sample hits this key.
        PrimaryKeyConstraint("server_id", "metric", "instance", "time", name="metrics_pkey"),
        CheckConstraint(
            f"metric ~ '{METRIC_PATTERN}' AND char_length(metric) <= {METRIC_MAX_LENGTH}", name="metrics_metric_check"
        ),
        CheckConstraint(f"char_length(instance) <= {INSTANCE_MAX_LENGTH}", name="metrics_instance_check"),
        # PostgreSQL sorts NaN above Infinity, so this refuses NaN and both infinities.
        CheckConstraint("value > '-Infinity'::float8 AND value < 'Infinity'::float8", name="metrics_value_check"),
    )

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    server_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    metric: Mapped[str] = mapped_column(Text)
    # The device ("cpu3", "/var", "eth0"), empty for a whole-server value.
    instance: Mapped[str] = mapped_column(Text, server_default=text("''"))
    value: Mapped[float] = mapped_column(Double)


_rollups = MetaData()


def _rollup(name: str) -> Table:
    return Table(
        name,
        _rollups,
        Column("bucket", DateTime(timezone=True)),
        Column("server_id", Uuid),
        Column("metric", Text),
        Column("instance", Text),
        Column("avg_value", Double),
        Column("min_value", Double),
        Column("max_value", Double),
        Column("samples", BigInteger),
    )


metrics_1m = _rollup("metrics_1m")
metrics_1h = _rollup("metrics_1h")
```
`app/models.py`: add `import app.metrics.models  # noqa: F401`, in alphabetical order.

`migrations/versions/0008_metrics.py`: the full text is in **Appendix A**. Write it as given. If the TimescaleDB of `timescale/timescaledb-ha:pg18` refuses a statement, read the error and change only that statement. The behaviour stays the design's: chunk sizes, real-time, weighted hourly average, offsets, intervals. Name the change in the commit body.

Check that it goes down and up on the scratch database: `megoocolab-runner services run migrate -- sh -c 'uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head'`. **Expected:** no error.

Run `megoocolab-runner services run test -- uv run pytest tests/test_migrations.py tests/security/test_db_privileges.py`. **Expected:** all pass, `test_the_models_match_the_migrations` and `test_revisions_are_numbered_consecutively_from_0001` included. Then run the full suite. **Expected:** green.

**Commit:** `feat(metrics): the metrics hypertable with 1-minute and 1-hour rollups, retention and compression`. Body: the collector and the dashboard need a place for samples, and the PRD fixes the retention windows (48 h, 30 days, 13 months).

---

## Step 3 — `Sample` and `Reading`

**Files:** `backend/app/metrics/samples.py` (new), `backend/tests/metrics/test_samples.py` (new).

Tests first, `tests/metrics/test_samples.py`:
```python
import math
import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.metrics.samples import Reading, Sample

NOW = datetime(2026, 11, 25, 10, 0, 5, tzinfo=UTC)


@pytest.mark.parametrize("metric", ["cpu.used_percent", "load1", "disk.used_percent", "net.rx_bytes"])
def test_a_lowercase_dotted_name_is_accepted(metric):
    assert Reading(metric=metric, value=1.0).instance == ""


@pytest.mark.parametrize("metric", ["", "CPU", "1cpu", "cpu..used", "cpu.", ".cpu", "cpu-used", "a" * 65])
def test_a_metric_name_outside_the_pattern_is_refused(metric):
    with pytest.raises(ValidationError):
        Reading(metric=metric, value=1.0)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_a_value_that_is_not_finite_is_refused(value):
    with pytest.raises(ValidationError):
        Reading(metric="cpu.used_percent", value=value)


def test_an_instance_longer_than_255_characters_is_refused():
    assert Reading(metric="disk.used_percent", instance="/" * 255, value=1.0)
    with pytest.raises(ValidationError):
        Reading(metric="disk.used_percent", instance="/" * 256, value=1.0)


def test_a_sample_needs_an_aware_time():
    with pytest.raises(ValidationError):
        Sample(time=datetime(2026, 11, 25, 10, 0), server_id=uuid.uuid4(), readings=())
    sample = Sample(time=NOW, server_id=uuid.uuid4(), readings=[Reading(metric="load1", value=0.5)])
    assert sample.readings == (Reading(metric="load1", value=0.5),)
```
Run `megoocolab-runner services run test -- uv run pytest tests/metrics/test_samples.py`. **Expected failure:** `ModuleNotFoundError: app.metrics.samples`.

Implementation, `app/metrics/samples.py`:
```python
"""One Sample is everything one server reported at one moment: a Reading per value."""

import uuid

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.metrics.models import INSTANCE_MAX_LENGTH, METRIC_MAX_LENGTH, METRIC_PATTERN


class Reading(BaseModel):
    """One value: a metric such as cpu.used_percent, of the whole server (instance "") or of one device."""

    model_config = ConfigDict(frozen=True)

    metric: str = Field(max_length=METRIC_MAX_LENGTH, pattern=METRIC_PATTERN)
    instance: str = Field(default="", max_length=INSTANCE_MAX_LENGTH)
    # Refused like the table's check: one NaN would spoil every average it falls into.
    value: float = Field(allow_inf_nan=False)


class Sample(BaseModel):
    model_config = ConfigDict(frozen=True)

    time: AwareDatetime
    server_id: uuid.UUID
    readings: tuple[Reading, ...]
```
Run the test again. **Expected:** pass.

**Commit:** `feat(metrics): a Sample validates its metric names, devices and values`.

---

## Step 4 — `write_samples` and `read_rollup`

**Files:** `backend/app/metrics/store.py` (new), `backend/tests/metrics/test_store.py` (new).

Contract:
```python
Resolution = Literal["1m", "1h"]

@dataclass(frozen=True)
class Bucket:
    bucket: datetime
    avg_value: float
    min_value: float
    max_value: float
    samples: int

async def write_samples(session: AsyncSession, samples: Iterable[Sample]) -> None
async def read_rollup(session: AsyncSession, resolution: Resolution, server_id: uuid.UUID, metric: str,
                      instance: str, start: datetime, end: datetime) -> list[Bucket]
```
`write_samples` makes one row per reading and runs one `postgresql.insert(Metric).on_conflict_do_nothing(constraint="metrics_pkey")` with the list of rows (`await session.execute(stmt, rows)`). It does nothing when there are no rows. It does not commit: the caller owns the transaction. `read_rollup` selects from `metrics_1m` or `metrics_1h` (from a `_ROLLUPS` dict; any other resolution raises `ValueError`), filtered by `server_id`, `metric`, `instance` and `start <= bucket < end`, ordered by `bucket`, and maps the rows to `Bucket`.

Tests first, `tests/metrics/test_store.py`. The full text is in **Appendix B**. It writes as the owner (`owner_session()`, then commit), because the API role may only read. It reads through `app.core.db.SessionLocal`, the API role, which also proves its `SELECT` grant on the rollups. Sample times are in the next hour, above any refresh watermark, so the rows prove the rollups are real-time (visible before any refresh). Tests:
- `test_samples_are_read_back_as_1_minute_rollups`
- `test_the_hourly_rollup_weights_each_minute_by_its_sample_count`: minute 0 holds 10 and 20, minute 1 holds 60. The hourly average is 30, not 37.5.
- `test_a_repeated_sample_changes_nothing`: write the same samples twice, then `SELECT count(*) FROM metrics WHERE server_id = :id` is 3 and the rollups are unchanged.
- `test_readings_of_other_instances_and_metrics_stay_apart`
- `test_an_unknown_resolution_is_refused`

Run `megoocolab-runner services run test -- uv run pytest tests/metrics/test_store.py`. **Expected failure:** `ModuleNotFoundError: app.metrics.store`.

Implement `app/metrics/store.py` per the contract, then run the test again. **Expected:** pass.

**Commit:** `feat(metrics): samples are written in one insert and read back as rollups`.

---

## Step 5 — Retention and compression jobs, proved on real chunks

**Files:** `backend/tests/conftest.py`, `backend/tests/metrics/test_policies.py` (new). These tests exercise the migration of step 2. If one fails, fix `0008_metrics.py` (the database is fresh on every run), never the test's expectations of the design.

Add to `tests/conftest.py`:
```python
async def owner_call(sql: str) -> None:
    """Runs, as the owner, a statement that refuses a transaction block: CALL run_job, CALL refresh_continuous_aggregate."""
    async with _owner_engine().connect() as connection:
        connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await connection.exec_driver_sql(sql)


METRICS_JOBS_WHERE = (
    "hypertable_name = 'metrics' OR hypertable_name IN (SELECT materialization_hypertable_name"
    " FROM timescaledb_information.continuous_aggregates WHERE view_name IN ('metrics_1m', 'metrics_1h'))"
)


@pytest.fixture
async def metrics_jobs_paused(database_at_head):
    """Stops the metrics jobs from running on their own, so a test runs them when it wants. Restored afterwards."""
    from sqlalchemy import text

    async with owner_session() as session:
        await session.execute(text(f"SELECT alter_job(job_id, scheduled => false) FROM timescaledb_information.jobs WHERE {METRICS_JOBS_WHERE}"))
        await session.commit()
    yield
    async with owner_session() as session:
        await session.execute(text(f"SELECT alter_job(job_id, scheduled => true) FROM timescaledb_information.jobs WHERE {METRICS_JOBS_WHERE}"))
        await session.commit()
```
`tests/metrics/test_policies.py`: the full text is in **Appendix C**. Tests:
- `test_retention_drops_raw_samples_older_than_48_hours_and_keeps_their_minutes`: two values (1 and 3) four days ago. Refresh `metrics_1m` over that hour, run the `metrics` retention job, then no raw row of the server is left, and `read_rollup("1m", …)` still gives one bucket `(avg 2, min 1, max 3, samples 2)`.
- `test_compression_keeps_the_rollups_and_accepts_a_late_sample`: value 5 thirteen hours ago. Refresh, read `(5, 5, 5, 1)`, run the `metrics` compression job, then the chunk holding it has `is_compressed = true` and the rollup reads the same. A late value 7 in that chunk is accepted. After a refresh the rollup reads `(6, 5, 7, 2)`.

Run `megoocolab-runner services run test -- uv run pytest tests/metrics/test_policies.py`. **Expected:** pass. Then the full suite. **Expected:** green.

**Commit:** `test(metrics): retention drops old raw samples and compression keeps the rollups`.

---

## Step 6 — Fan-out through Valkey

**Files:** `backend/app/metrics/fanout.py` (new), `backend/tests/metrics/test_fanout.py` (new).

Contract:
```python
def channel(server_id: uuid.UUID) -> str                 # "metrics:<server_id>"
def encode(sample: Sample) -> str                         # the JSON payload below
def decode(data: bytes | str) -> Sample                   # raises ValueError (pydantic's ValidationError is one)
async def publish(client: Valkey, sample: Sample) -> int  # subscribers that got it
@asynccontextmanager
async def subscribe(client: Valkey, server_ids: Iterable[uuid.UUID]) -> AsyncIterator[AsyncIterator[Sample]]
```
Payload: `{"v": 1, "server_id": "<uuid>", "time": "2026-11-25T10:00:05Z", "readings": [["cpu.used_percent", "", 12.5], ["disk.used_percent", "/var", 81.0]]}`. It is compact JSON (`separators=(",", ":")`), and the time is UTC with `Z` (`sample.time.astimezone(UTC).isoformat().replace("+00:00", "Z")`).

Tests first, `tests/metrics/test_fanout.py`: the full text is in **Appendix D**. Tests:
- `test_the_payload_is_the_designs_json`
- `test_a_published_sample_reaches_a_subscriber_of_its_server`: `publish` returns 1, and the subscriber receives an equal `Sample`.
- `test_a_subscriber_of_another_server_does_not_get_it`: publishing for A returns 0. Then a sample for B arrives first.
- `test_a_malformed_message_is_skipped_and_the_next_one_arrives`: publishes `b"not json"`, a version-2 payload and a payload with metric `CPU`, then a good sample. Only the good one arrives, and `caplog` holds a warning for each skipped message.
- `test_leaving_the_subscription_closes_its_connection`: `pubsub_numsub(channel(a))` is `[(channel_bytes, 1)]` inside and `0` after leaving.
- `test_subscribe_needs_a_server`: an empty list raises `ValueError`.

Run `megoocolab-runner services run test -- uv run pytest tests/metrics/test_fanout.py`. **Expected failure:** `ModuleNotFoundError: app.metrics.fanout`.

Implement `app/metrics/fanout.py` (full text in **Appendix E**). `subscribe` deduplicates the channels, raises `ValueError` when there are none, opens `async with client.pubsub() as pubsub`, subscribes, then reads `get_message(timeout=5.0)` until every channel's `subscribe` confirmation has arrived (`TimeoutError` otherwise), and yields an async generator over `pubsub.listen()`. That generator keeps only `type == "message"`, decodes it, and on `ValueError` logs `logger.warning("Skipped a message on %s: %s", channel, error)` and goes on. Leaving the context closes the pub/sub connection. Reconnecting is valkey-py's own: delivery is at most once (module docstring).

Run the test again. **Expected:** pass.

**Commit:** `feat(metrics): samples fan out through Valkey, one channel per server`.

---

## Step 7 — The `valkey` Compose service, stack checks and docs

**Files:** `docker-compose.yml`, `backend/tests/test_stack.py`, `megoocolab.toml` (stack description), `README.md`.

Tests first, in `tests/test_stack.py`:
- `NETWORKS` gains `"valkey": {"core"}`. Rename `test_the_stack_has_exactly_the_four_phase_0_services` to `test_the_stack_has_exactly_its_five_services` (the body is unchanged: it compares with `NETWORKS`). The existing `test_only_caddy_publishes_a_port`, `test_each_service_is_only_on_its_own_networks` and `test_every_service_restarts_has_a_healthcheck_and_no_fixed_container_name` then cover valkey.
- `_resolves` and the parametrized lookup test: add `("backend", "valkey", True)`, `("caddy", "valkey", False)` and `("frontend", "valkey", False)`. Rename the test to `test_only_the_backend_can_find_the_database_and_valkey`.
- New tests (full text in **Appendix F**):
  - `test_the_backend_waits_for_a_healthy_valkey_and_has_its_url`
  - `test_valkey_keeps_an_append_only_file_in_valkey_data`: the model's `command` is `["valkey-server", "--appendonly", "yes"]`, the volume is `valkey_data` on `/data`, and `valkey-cli CONFIG GET appendonly` in the container prints `appendonly` and `yes`.
  - `test_a_sample_published_in_the_backend_reaches_a_subscriber_there`: runs `FANOUT_PROBE` with `python -c` in the backend container and expects `received`.
  - `test_the_api_role_can_read_metrics_1m`: `_psql_as_api_role("SELECT count(*) FROM metrics_1m")` succeeds.

Run `megoocolab-runner services run stack -- uv run pytest -m stack`. **Expected failure:** the five-services, networks, lookup and new valkey tests fail.

Implement, in `docker-compose.yml`:
```yaml
  backend:
    environment:
      ...
      VALKEY_URL: valkey://valkey:6379/0
    depends_on:
      db:
        condition: service_healthy
      valkey:
        condition: service_healthy

  valkey:
    image: valkey/valkey:9
    restart: unless-stopped
    # Append-only file in /data, so the job queue finds it ready. No password: valkey is only on core (internal) and
    # publishes no port, and the image turns protected mode off.
    command: ["valkey-server", "--appendonly", "yes"]
    volumes:
      - valkey_data:/data
    networks: [core]
    healthcheck:
      test: ["CMD", "valkey-cli", "ping"]
      <<: *healthcheck-timing
```
Place the `valkey` service after `db`, and add `valkey_data: {}` under `volumes:`. Update the `[services.stack]` description in `megoocolab.toml` to `(docker-compose.build.yml: caddy, frontend, backend, db, valkey)`. In `README.md` ("Run it"), say it "starts Caddy, the frontend, the backend, the database and Valkey". Under "Upgrade", add a sentence: `make upgrade` also pulls the Valkey image and creates its `valkey_data` volume, so nobody has to act.

Run `megoocolab-runner services run stack -- uv run pytest -m stack`. **Expected:** pass. Then `megoocolab-runner services run image -- uv run pytest -m docker`. **Expected:** pass, unchanged, because the image check runs without Valkey.

**Commit:** `feat(stack): a valkey service on the core network carries live metrics`.

---

## Final verification
From `backend/`:
- `megoocolab-runner services run test -- uv run pytest`
- `megoocolab-runner services run migrate -- sh -c 'uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head'`
- `megoocolab-runner services run image -- uv run pytest -m docker`
- `megoocolab-runner services run stack -- uv run pytest -m stack`

From the repository root: `make test-security` and `make test` (it runs the frontend checks too).

---

## Appendix A — `backend/migrations/versions/0008_metrics.py`
```python
"""metrics: the metrics hypertable, one row per value, its 1-minute and 1-hour rollups, and their policies

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEGMENT_BY = "server_id, metric, instance"


def _set_rollup_chunk_interval(view: str, interval: str) -> None:
    # A rollup keeps its rows in a materialization hypertable of its own: the chunk interval is set there.
    op.execute(
        "SELECT set_chunk_time_interval("
        "(quote_ident(materialization_hypertable_schema) || '.' || quote_ident(materialization_hypertable_name))::regclass,"
        f" INTERVAL '{interval}') FROM timescaledb_information.continuous_aggregates WHERE view_name = '{view}'"
    )


def upgrade() -> None:
    op.create_table(
        "metrics",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("server_id", sa.Uuid(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("instance", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("value", sa.Double(), nullable=False),
        sa.CheckConstraint(
            r"metric ~ '^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$' AND char_length(metric) <= 64", name="metrics_metric_check"
        ),
        sa.CheckConstraint("char_length(instance) <= 255", name="metrics_instance_check"),
        sa.CheckConstraint("value > '-Infinity'::float8 AND value < 'Infinity'::float8", name="metrics_value_check"),
        sa.PrimaryKeyConstraint("server_id", "metric", "instance", "time", name="metrics_pkey"),
    )
    # create_default_indexes => false: the primary key is the index every read uses.
    op.execute(
        "SELECT create_hypertable('metrics', by_range('time', INTERVAL '6 hours'), create_default_indexes => false)"
    )
    op.execute(
        "ALTER TABLE metrics SET (timescaledb.compress, "
        f"timescaledb.compress_segmentby = '{SEGMENT_BY}', timescaledb.compress_orderby = 'time DESC')"
    )

    # Real-time (materialized_only = false): a query sees the current minute without waiting for a refresh.
    op.execute(
        """
        CREATE MATERIALIZED VIEW metrics_1m
        WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
        SELECT time_bucket(INTERVAL '1 minute', time) AS bucket, server_id, metric, instance,
               avg(value) AS avg_value, min(value) AS min_value, max(value) AS max_value, count(*) AS samples
        FROM metrics
        GROUP BY time_bucket(INTERVAL '1 minute', time), server_id, metric, instance
        WITH NO DATA
        """
    )
    _set_rollup_chunk_interval("metrics_1m", "1 day")

    # Built on metrics_1m, kept 30 days, so it can catch up after a long stop; raw samples are gone after 48 hours.
    # The average is weighted by each minute's sample count, so it equals the average of the raw values.
    op.execute(
        """
        CREATE MATERIALIZED VIEW metrics_1h
        WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
        SELECT time_bucket(INTERVAL '1 hour', bucket) AS bucket, server_id, metric, instance,
               sum(avg_value * samples) / sum(samples) AS avg_value, min(min_value) AS min_value,
               max(max_value) AS max_value, sum(samples)::bigint AS samples
        FROM metrics_1m
        GROUP BY time_bucket(INTERVAL '1 hour', bucket), server_id, metric, instance
        WITH NO DATA
        """
    )
    _set_rollup_chunk_interval("metrics_1h", "30 days")

    for view in ("metrics_1m", "metrics_1h"):
        op.execute(
            f"ALTER MATERIALIZED VIEW {view} SET (timescaledb.compress = true, "
            f"timescaledb.compress_segmentby = '{SEGMENT_BY}', timescaledb.compress_orderby = 'bucket DESC')"
        )

    # Each refresh window is shorter than its source's retention and ends before its own compression starts.
    op.execute(
        "SELECT add_continuous_aggregate_policy('metrics_1m', start_offset => INTERVAL '24 hours',"
        " end_offset => INTERVAL '1 minute', schedule_interval => INTERVAL '1 minute')"
    )
    op.execute(
        "SELECT add_continuous_aggregate_policy('metrics_1h', start_offset => INTERVAL '7 days',"
        " end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '1 hour')"
    )
    op.execute("SELECT add_compression_policy('metrics', compress_after => INTERVAL '1 hour')")
    op.execute("SELECT add_compression_policy('metrics_1m', compress_after => INTERVAL '2 days')")
    op.execute("SELECT add_compression_policy('metrics_1h', compress_after => INTERVAL '30 days')")
    # Retention drops whole chunks: data is kept at least the stated time and at most one chunk longer.
    op.execute(
        "SELECT add_retention_policy('metrics', drop_after => INTERVAL '48 hours', schedule_interval => INTERVAL '1 hour')"
    )
    op.execute("SELECT add_retention_policy('metrics_1m', drop_after => INTERVAL '30 days')")
    op.execute("SELECT add_retention_policy('metrics_1h', drop_after => INTERVAL '13 months')")

    # The backend only reads. The collector's role and its INSERT grant come with the collector (MITA-26).
    op.execute("GRANT SELECT ON metrics, metrics_1m, metrics_1h TO megooitadmin_api")


def downgrade() -> None:
    # Policies and grants go with their relations.
    op.execute("DROP MATERIALIZED VIEW metrics_1h")
    op.execute("DROP MATERIALIZED VIEW metrics_1m")
    op.drop_table("metrics")
```

## Appendix B — `backend/tests/metrics/test_store.py`
```python
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from conftest import owner_session
from sqlalchemy import text

from app.core.db import SessionLocal
from app.metrics.samples import Reading, Sample
from app.metrics.store import Bucket, read_rollup, write_samples

pytestmark = pytest.mark.usefixtures("database_at_head")


def _next_hour() -> datetime:
    # Above any refresh watermark: these rows can only be seen through the rollups' real-time part.
    return datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


def _samples(server_id: uuid.UUID, hour: datetime) -> list[Sample]:
    def sample(offset: timedelta, value: float) -> Sample:
        return Sample(
            time=hour + offset,
            server_id=server_id,
            readings=(
                Reading(metric="cpu.used_percent", value=value),
                Reading(metric="disk.used_percent", instance="/var", value=value + 1),
            ),
        )

    return [sample(timedelta(seconds=0), 10.0), sample(timedelta(seconds=30), 20.0), sample(timedelta(minutes=1), 60.0)]


async def _write(samples: list[Sample]) -> None:
    async with owner_session() as session:
        await write_samples(session, samples)
        await session.commit()


async def _read(resolution, server_id, hour, metric="cpu.used_percent", instance="") -> list[Bucket]:
    async with SessionLocal() as session:
        return await read_rollup(session, resolution, server_id, metric, instance, hour, hour + timedelta(hours=1))


async def test_samples_are_read_back_as_1_minute_rollups():
    server_id, hour = uuid.uuid4(), _next_hour()
    await _write(_samples(server_id, hour))
    assert await _read("1m", server_id, hour) == [
        Bucket(hour, 15.0, 10.0, 20.0, 2),
        Bucket(hour + timedelta(minutes=1), 60.0, 60.0, 60.0, 1),
    ]


async def test_the_hourly_rollup_weights_each_minute_by_its_sample_count():
    server_id, hour = uuid.uuid4(), _next_hour()
    await _write(_samples(server_id, hour))
    # (10 + 20 + 60) / 3, not the average of the minutes (15 + 60) / 2.
    assert await _read("1h", server_id, hour) == [Bucket(hour, 30.0, 10.0, 60.0, 3)]


async def test_a_repeated_sample_changes_nothing():
    server_id, hour = uuid.uuid4(), _next_hour()
    await _write(_samples(server_id, hour))
    await _write(_samples(server_id, hour))
    async with owner_session() as session:
        count = await session.scalar(
            text("SELECT count(*) FROM metrics WHERE server_id = :id AND metric = 'cpu.used_percent'"), {"id": server_id}
        )
    assert count == 3
    assert await _read("1h", server_id, hour) == [Bucket(hour, 30.0, 10.0, 60.0, 3)]


async def test_readings_of_other_instances_and_metrics_stay_apart():
    server_id, hour = uuid.uuid4(), _next_hour()
    await _write(_samples(server_id, hour))
    assert await _read("1h", server_id, hour, "disk.used_percent", "/var") == [Bucket(hour, 31.0, 11.0, 61.0, 3)]
    assert await _read("1h", server_id, hour, "disk.used_percent", "") == []
    assert await _read("1h", uuid.uuid4(), hour) == []


async def test_an_unknown_resolution_is_refused():
    with pytest.raises(ValueError):
        await _read("5m", uuid.uuid4(), _next_hour())
```

## Appendix C — `backend/tests/metrics/test_policies.py`
```python
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from conftest import owner_call, owner_session
from sqlalchemy import text

from app.core.db import SessionLocal
from app.metrics.samples import Reading, Sample
from app.metrics.store import Bucket, read_rollup, write_samples

pytestmark = pytest.mark.usefixtures("metrics_jobs_paused")


def _minute_ago(delta: timedelta) -> datetime:
    return (datetime.now(UTC) - delta).replace(second=0, microsecond=0)


async def _write(server_id: uuid.UUID, *points: tuple[datetime, float]) -> None:
    async with owner_session() as session:
        await write_samples(
            session,
            [Sample(time=t, server_id=server_id, readings=(Reading(metric="load1", value=v),)) for t, v in points],
        )
        await session.commit()


async def _refresh_1m(around: datetime) -> None:
    start, end = (around - timedelta(hours=1)).isoformat(), (around + timedelta(hours=1)).isoformat()
    await owner_call(f"CALL refresh_continuous_aggregate('metrics_1m', '{start}', '{end}')")


async def _run_job(proc_name: str) -> None:
    async with owner_session() as session:
        job_id = await session.scalar(
            text("SELECT job_id FROM timescaledb_information.jobs WHERE proc_name = :p AND hypertable_name = 'metrics'"),
            {"p": proc_name},
        )
    assert job_id is not None, proc_name
    await owner_call(f"CALL run_job({int(job_id)})")


async def _minute(server_id: uuid.UUID, minute: datetime) -> list[Bucket]:
    async with SessionLocal() as session:
        return await read_rollup(session, "1m", server_id, "load1", "", minute, minute + timedelta(minutes=1))


async def _raw_count(server_id: uuid.UUID) -> int:
    async with owner_session() as session:
        return await session.scalar(text("SELECT count(*) FROM metrics WHERE server_id = :id"), {"id": server_id})


async def test_retention_drops_raw_samples_older_than_48_hours_and_keeps_their_minutes():
    server_id, minute = uuid.uuid4(), _minute_ago(timedelta(days=4))
    await _write(server_id, (minute + timedelta(seconds=10), 1.0), (minute + timedelta(seconds=30), 3.0))
    await _refresh_1m(minute)
    await _run_job("policy_retention")
    assert await _raw_count(server_id) == 0
    assert await _minute(server_id, minute) == [Bucket(minute, 2.0, 1.0, 3.0, 2)]


async def test_compression_keeps_the_rollups_and_accepts_a_late_sample():
    server_id, minute = uuid.uuid4(), _minute_ago(timedelta(hours=13))
    await _write(server_id, (minute + timedelta(seconds=5), 5.0))
    await _refresh_1m(minute)
    assert await _minute(server_id, minute) == [Bucket(minute, 5.0, 5.0, 5.0, 1)]

    await _run_job("policy_compression")
    async with owner_session() as session:
        compressed = await session.scalar(
            text(
                "SELECT is_compressed FROM timescaledb_information.chunks WHERE hypertable_name = 'metrics'"
                " AND range_start <= :t AND range_end > :t"
            ),
            {"t": minute},
        )
    assert compressed is True
    assert await _minute(server_id, minute) == [Bucket(minute, 5.0, 5.0, 5.0, 1)]

    await _write(server_id, (minute + timedelta(seconds=25), 7.0))
    await _refresh_1m(minute)
    assert await _raw_count(server_id) == 2
    assert await _minute(server_id, minute) == [Bucket(minute, 6.0, 5.0, 7.0, 2)]
```

## Appendix D — `backend/tests/metrics/test_fanout.py`
```python
import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

import pytest

from app.core.valkey import valkey_client
from app.metrics.fanout import channel, encode, publish, subscribe
from app.metrics.samples import Reading, Sample

NOW = datetime(2026, 11, 25, 10, 0, 5, tzinfo=UTC)


def _sample(server_id: uuid.UUID, value: float = 12.5) -> Sample:
    return Sample(
        time=NOW,
        server_id=server_id,
        readings=(
            Reading(metric="cpu.used_percent", value=value),
            Reading(metric="disk.used_percent", instance="/var", value=81.0),
        ),
    )


@pytest.fixture
async def client():
    client = valkey_client()
    yield client
    await client.aclose()


async def _next(samples) -> Sample:
    return await asyncio.wait_for(anext(samples), 5)


def test_the_payload_is_the_designs_json():
    server_id = uuid.UUID("0b6c5f7e-2a51-4c1e-9d43-7a8f9e1c2b3d")
    assert json.loads(encode(_sample(server_id))) == {
        "v": 1,
        "server_id": str(server_id),
        "time": "2026-11-25T10:00:05Z",
        "readings": [["cpu.used_percent", "", 12.5], ["disk.used_percent", "/var", 81.0]],
    }
    assert channel(server_id) == f"metrics:{server_id}"


async def test_a_published_sample_reaches_a_subscriber_of_its_server(client):
    sample = _sample(uuid.uuid4())
    async with subscribe(client, [sample.server_id]) as samples:
        assert await publish(client, sample) == 1
        assert await _next(samples) == sample


async def test_a_subscriber_of_another_server_does_not_get_it(client):
    a, b = _sample(uuid.uuid4(), 1.0), _sample(uuid.uuid4(), 2.0)
    async with subscribe(client, [b.server_id]) as samples:
        assert await publish(client, a) == 0
        assert await publish(client, b) == 1
        assert await _next(samples) == b


async def test_a_malformed_message_is_skipped_and_the_next_one_arrives(client, caplog):
    sample = _sample(uuid.uuid4())
    bad_version = json.loads(encode(sample)) | {"v": 2}
    bad_metric = json.loads(encode(sample)) | {"readings": [["CPU", "", 1.0]]}
    with caplog.at_level(logging.WARNING, logger="app.metrics.fanout"):
        async with subscribe(client, [sample.server_id]) as samples:
            for bad in (b"not json", json.dumps(bad_version), json.dumps(bad_metric)):
                await client.publish(channel(sample.server_id), bad)
            await publish(client, sample)
            assert await _next(samples) == sample
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 3


async def test_leaving_the_subscription_closes_its_connection(client):
    server_id = uuid.uuid4()
    name = channel(server_id).encode()
    async with subscribe(client, [server_id]):
        assert await client.pubsub_numsub(name) == [(name, 1)]
    assert await client.pubsub_numsub(name) == [(name, 0)]


async def test_subscribe_needs_a_server(client):
    with pytest.raises(ValueError):
        async with subscribe(client, []):
            pass
```

## Appendix E — `backend/app/metrics/fanout.py`
```python
"""Live metric fan-out through Valkey: one channel per server, metrics:<server_id>, one JSON message per Sample.

Delivery is at most once. A subscriber that was disconnected misses what was published meanwhile (valkey-py
subscribes again on reconnect). The database is the source of truth, and a dashboard fills its gaps from it.
Anything on the core network can publish, so a message that does not parse or validate is skipped with a warning.
"""

import json
import logging
import uuid
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from datetime import UTC
from typing import Literal

from pydantic import AwareDatetime, BaseModel
from valkey.asyncio import Valkey
from valkey.asyncio.client import PubSub

from app.metrics.samples import Reading, Sample

logger = logging.getLogger(__name__)
SUBSCRIBE_TIMEOUT = 5.0


class _Message(BaseModel):
    v: Literal[1]
    server_id: uuid.UUID
    time: AwareDatetime
    readings: list[tuple[str, str, float]]


def channel(server_id: uuid.UUID) -> str:
    return f"metrics:{server_id}"


def encode(sample: Sample) -> str:
    return json.dumps(
        {
            "v": 1,
            "server_id": str(sample.server_id),
            "time": sample.time.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "readings": [[r.metric, r.instance, r.value] for r in sample.readings],
        },
        separators=(",", ":"),
    )


def decode(data: bytes | str) -> Sample:
    """The Sample of a message. Raises ValueError (pydantic's ValidationError is one) when it is not one."""
    message = _Message.model_validate_json(data)
    return Sample(
        time=message.time,
        server_id=message.server_id,
        readings=tuple(Reading(metric=m, instance=i, value=v) for m, i, v in message.readings),
    )


async def publish(client: Valkey, sample: Sample) -> int:
    """Sends the sample to the subscribers of its server. Returns how many got it."""
    return await client.publish(channel(sample.server_id), encode(sample))


async def _samples(pubsub: PubSub) -> AsyncIterator[Sample]:
    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        try:
            yield decode(message["data"])
        except ValueError as error:
            logger.warning("Skipped a message on %s: %s", message["channel"], error)


@asynccontextmanager
async def subscribe(client: Valkey, server_ids: Iterable[uuid.UUID]) -> AsyncIterator[AsyncIterator[Sample]]:
    """The samples of these servers, from the moment Valkey confirmed the subscription. Leaving closes its connection."""
    channels = sorted({channel(server_id) for server_id in server_ids})
    if not channels:
        raise ValueError("subscribe needs at least one server")
    async with client.pubsub() as pubsub:
        await pubsub.subscribe(*channels)
        confirmed = 0
        while confirmed < len(channels):
            message = await pubsub.get_message(timeout=SUBSCRIBE_TIMEOUT)
            if message is None:
                raise TimeoutError("Valkey did not confirm the subscription")
            if message["type"] == "subscribe":
                confirmed += 1
        yield _samples(pubsub)
```

## Appendix F — new tests in `backend/tests/test_stack.py`
```python
def test_the_backend_waits_for_a_healthy_valkey_and_has_its_url():
    backend = _model()["services"]["backend"]
    assert backend["depends_on"]["valkey"]["condition"] == "service_healthy"
    assert backend["environment"]["VALKEY_URL"] == "valkey://valkey:6379/0"


def test_valkey_keeps_an_append_only_file_in_valkey_data():
    valkey = _model()["services"]["valkey"]
    assert valkey["command"] == ["valkey-server", "--appendonly", "yes"]
    assert [(v["type"], v["source"], v["target"]) for v in valkey["volumes"]] == [("volume", "valkey_data", "/data")]
    assert "valkey_data" in _model()["volumes"]
    result = _compose("exec", "-T", "valkey", "valkey-cli", "CONFIG", "GET", "appendonly")
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["appendonly", "yes"]


FANOUT_PROBE = """
import asyncio, uuid
from datetime import UTC, datetime
from app.core.valkey import valkey_client
from app.metrics.fanout import publish, subscribe
from app.metrics.samples import Reading, Sample

async def main():
    client = valkey_client()
    sample = Sample(time=datetime.now(UTC), server_id=uuid.uuid4(), readings=(Reading(metric="cpu.used_percent", value=12.5),))
    async with subscribe(client, [sample.server_id]) as samples:
        await publish(client, sample)
        received = await asyncio.wait_for(anext(samples), 5)
    await client.aclose()
    print("received" if received == sample else "different")

asyncio.run(main())
"""


def test_a_sample_published_in_the_backend_reaches_a_subscriber_there():
    result = _compose("exec", "-T", "backend", "python", "-c", FANOUT_PROBE)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "received"


def test_the_api_role_can_read_metrics_1m():
    result = _psql_as_api_role("SELECT count(*) FROM metrics_1m")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "0"
```
