# MITA-25 — Metrics storage: hypertable, rollups, retention, Valkey service

## Goal

The platform gets a place to keep metric samples and a channel to pass them on live. Samples written to `metrics` can be read back as 1-minute and 1-hour rollups, old data is dropped and compressed by scheduled jobs, and a `valkey` service with a small publish/subscribe helper carries each sample to whoever is watching. Nothing changes on screen: the collector (MITA-26) and the dashboard build on this.

## Decisions

| Decision | Chosen | Why, and what was rejected |
|---|---|---|
| Shape of `metrics` | **One row per value** (your answer) | One table covers whole-server and per-device series, and a new metric needs no migration. Rejected: a column per metric (a migration and a rollup rebuild for each new metric, extra hypertables for per-device values) and a JSONB column (rollups can only aggregate keys named in their definition). |
| Where the shared code lives | **The backend's `app` package** (your answer) | No new package and no change to the release tooling. The collector task decides how its image gets `app`. Rejected: a new top-level shared package. |
| Valkey password | **None** (your answer) | Valkey is only on the internal `core` network and publishes no port. No new line in `.env`. |
| Valkey persistence | **On now** (your answer) | Append-only file and a `valkey_data` volume, so the job queue finds it ready. |
| Compression | **Now, on raw samples and both rollups** (your answer) | About a tenth of the disk space at a few hundred servers. |
| `metrics_1h` source | Built on `metrics_1m`, not on raw samples | The 1-minute rollup is kept 30 days, so the hourly one can catch up after a long stop. Raw samples are gone after 48 hours. The hourly average is weighted by the sample count, so it equals the average of the raw values. |
| Rollups show the newest data | Both rollups are real-time (`materialized_only = false`) | A query sees the current minute and hour without waiting for the refresh job. |
| Link to `servers` | `server_id` without a foreign key | A cascade cannot reach the rollups, and deleting across compressed chunks is slow. Samples of a removed server become unreachable (the server is gone, its id is never reused) and age out with the retention windows. |
| Database rights | `megooitadmin_api` gets `SELECT` only on the three relations | The backend only reads metrics. The collector task adds the role the collector writes as and its `INSERT` grant. |
| `VALKEY_URL` in the backend | Optional setting; using Valkey without it fails with an error that names the variable | Nothing in the server uses Valkey until the dashboard, and the backend image check runs without a Valkey. Same pattern as `DATABASE_OWNER_URL`. |

## Architecture

**Migration `0008_metrics.py`** (hand-written SQL where Alembic has no operation, like `0002`):

- `metrics` table, made a hypertable on `time` with 6-hour chunks.
- `metrics_1m`: continuous aggregate over `metrics`, 1-minute buckets.
- `metrics_1h`: continuous aggregate over `metrics_1m`, 1-hour buckets.
- Refresh, compression and retention policies (table below).
- `GRANT SELECT ON metrics, metrics_1m, metrics_1h TO megooitadmin_api`.
- Downgrade drops `metrics_1h`, `metrics_1m`, then `metrics`. Their policies go with them.

**New module `backend/app/metrics/`**

| File | Holds |
|---|---|
| `models.py` | `Metric`, the ORM model of `metrics`, imported in `app/models.py` so Alembic's check sees it. The two rollups are views, so they are plain `Table` objects outside `Base.metadata`. |
| `samples.py` | `Reading(metric, instance, value)` and `Sample(time, server_id, readings)`: Pydantic models that validate the metric name, the instance length and a finite value. One `Sample` is everything one server reported at one moment. |
| `store.py` | `write_samples(session, samples)`: one bulk insert, a repeated row is ignored. `read_rollup(session, resolution, server_id, metric, instance, start, end)` with resolution `1m` or `1h`: the buckets in time order. |
| `fanout.py` | `channel(server_id)`, `publish(client, sample)`, `subscribe(client, server_ids)`. |

**New `backend/app/core/valkey.py`**: builds the async client from `VALKEY_URL` (`valkey.asyncio.from_url`). New dependency: `valkey` (valkey-py) in `backend/pyproject.toml` and `uv.lock`.

**Compose (`docker-compose.yml`)**

- New service `valkey`: image `valkey/valkey` pinned to its current major version, `restart: unless-stopped`, append-only file on, volume `valkey_data:/data`, network `core` only, no published port, healthcheck with `valkey-cli ping`.
- `backend` gets `VALKEY_URL: valkey://valkey:6379/0` and waits for a healthy `valkey`.
- The planner checks that the image accepts connections from another container without a password (protected mode).

**Test services**: a Valkey joins the `test` set in `megoocolab.toml` through its own Compose file (`tools/test-services/docker-compose.valkey.yml`), so the `migrate` and `image` sets stay as they are. It sets `TEST_VALKEY_URL`, which `conftest.py` passes on as `VALKEY_URL`. CI needs no change: it runs the sets of `megoocolab.toml`.

**Docs**: `README.md` names Valkey among the services `make up` starts. `AGENTS.md` and `megoocolab.toml` describe the `test` set with Valkey.

## Data and interfaces

**`metrics`**

| Column | Type | Notes |
|---|---|---|
| `time` | `timestamptz`, not null | When the values were read |
| `server_id` | `uuid`, not null | No foreign key (see Decisions) |
| `metric` | `text`, not null | Lowercase dotted name, for example `cpu.used_percent`, `disk.used_percent`. Check: `^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$`, at most 64 characters |
| `instance` | `text`, not null, default `''` | The device: `cpu3`, `/var`, `eth0`. Empty for a whole-server value. At most 255 characters |
| `value` | `double precision`, not null | Check: not NaN and not infinite, so one bad value cannot spoil an average |

Primary key `(server_id, metric, instance, time)`. It is also the index every read uses, and it lets a repeated sample be ignored.

**`metrics_1m` and `metrics_1h`**: `bucket`, `server_id`, `metric`, `instance`, `avg_value`, `min_value`, `max_value`, `samples`.

**Policies**

| Relation | Chunk | Refreshed | Compressed after | Dropped after |
|---|---|---|---|---|
| `metrics` | 6 hours | — | 1 hour | **48 hours**, checked hourly |
| `metrics_1m` | 1 day | every minute, over the last 24 hours | 2 days | **30 days** |
| `metrics_1h` | 30 days | every hour, over the last 7 days | 30 days | **13 months** |

- Compression segments by `server_id, metric, instance` and orders by time, newest first.
- Each refresh window is shorter than the retention of its source and ends before its own compression starts, which TimescaleDB requires.
- Retention drops whole chunks, so data is kept at least the stated time and at most one chunk longer.

**Valkey messages**

- Channel: `metrics:<server_id>`, one per server, so a dashboard subscribes only to the servers on screen (PRD §5.2).
- Payload: JSON, one message per `Sample`: `{"v": 1, "server_id": "…", "time": "2026-11-25T10:00:05Z", "readings": [["cpu.used_percent", "", 12.5], ["disk.used_percent", "/var", 81.0]]}`.
- `publish` returns how many subscribers got it. `subscribe` is an async context manager that yields an async iterator of `Sample` and closes its connection on exit.

**Config**: `VALKEY_URL` (optional, see Decisions). No new line in `.env` or `.env.example`.

## Error handling and edge cases

- **Delivery is at most once.** A subscriber that was disconnected misses what was published meanwhile; valkey-py subscribes again by itself on reconnect. The database is the source of truth, and a dashboard fills gaps from it.
- **A message that does not parse or validate** is skipped with a warning and never ends the subscription: anything on `core` can publish.
- **A repeated sample** (same server, metric, instance and time) is ignored by `write_samples`.
- **A late sample** in an already compressed chunk is still accepted, and the next refresh corrects its rollup while it is inside the refresh window.
- **A value that is NaN or infinite**, or a metric name outside the pattern, is refused by `Sample` and, behind it, by the table's checks.
- **After a stop** of more than 24 hours, nothing was collected, so no rollup is lost. The hourly rollup catches up over 7 days from `metrics_1m`.
- **Upgrade of a running instance**: `make upgrade` pulls the Valkey image and creates the `valkey_data` volume. Nobody has to act. `valkey_data` holds nothing worth a backup yet.
- **`VALKEY_URL` missing** when the client is first asked for: a `RuntimeError` that names the variable.

## Testing

Tests are written first, against the real TimescaleDB and Valkey of the `test` set.

- **Migration** (`test_migrations.py`): `0008` goes down and up again; `metrics` is a hypertable on `time`; both rollups exist and are real-time; `timescaledb_information.jobs` holds the three retention jobs with 48 hours, 30 days and 13 months, the two refresh jobs and the three compression jobs; the table refuses a bad metric name and a NaN; the models match the migrations.
- **Store** (`tests/metrics/`): samples written are read back as 1-minute and 1-hour rollups with the right `avg_value`, `min_value`, `max_value` and `samples`, including an hour whose minutes hold different sample counts (the weighted average); they are visible before any refresh; a repeated sample changes nothing.
- **Retention**: after a refresh, running the retention job drops raw samples older than 48 hours while their 1-minute buckets stay readable.
- **Compression**: running the job compresses an old chunk, the rollups read the same, and a late sample is still accepted.
- **Privileges** (`test_db_privileges.py`): `API_GRANTS` lists the three relations with `SELECT`, and the API role cannot insert into `metrics`.
- **Fan-out**: a published sample reaches a subscriber of that server and not a subscriber of another server; a malformed message is skipped and the next one still arrives; leaving the subscription closes its connection.
- **Settings**: without `VALKEY_URL`, asking for the client names the variable.
- **Stack** (`test_stack.py`): the stack has five services; `valkey` is on `core` only, publishes no port, restarts, has a healthcheck, mounts `valkey_data` and has the append-only file on; the backend finds `valkey` and Caddy and the frontend do not; a sample published from the backend container reaches a subscriber there; the API role can read `metrics_1m`.
- The existing checks (`make test`, `make test-security`) stay green.

## Out of scope

- The collector, its database role and `INSERT` grant, the list of metric names, the sample interval and marking a server unreachable (MITA-26).
- The WebSocket route, the live dashboard, the server detail page, alert rules and `query_metrics`.
- Live log fan-out and the job queue on Valkey.
- A Valkey password or ACLs.
- Settings to change the retention windows: they are the PRD's fixed values.
- Deleting a removed server's samples before they age out.
