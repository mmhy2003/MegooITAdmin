# MITA-26 — Metrics collector: one SSH stream per server

## Goal

A new `collector` service keeps one SSH channel open to every Linux server with a pinned host key. Each server runs a small read-only loop that prints one JSON line per sample. The collector turns each line into a `Sample`, publishes it on Valkey and writes it to `metrics`. It reconnects with backoff, and a server with no sample for 30 seconds is marked unreachable. Nothing changes on screen: the dashboard and server page tasks build on this.

## Decisions

| Decision | Chosen | Why, and what was rejected |
|---|---|---|
| Packaging | **Same image, other command** (your answer) | The code lives in `backend/app/collector/`, and the `collector` service runs the backend image with `python -m app.collector`. One image, one `uv.lock`, no change to the Release workflow. Rejected: an own image from `workers/collector` (a third release image, two lock files) and an image built FROM the backend image. `workers/collector/.gitkeep` is removed, because the part no longer lives there. |
| Reach into the UI | **API only** (your answer) | `metrics_interval_seconds` in the server API, and the monitoring state in `GET`. No screen changes, so no mockup. |
| Sample interval | **1 to 10 seconds, default 5** (your answer) | With 10 s, unreachable after 30 s still means at least two missed samples. |
| Reachable/unreachable changes | **Not audit events** (your answer) | They are monitoring data in a state table, and the alerts task builds on it. A changed host key met by the collector is still flagged and audited, as today. |
| Metrics | The PRD's list **plus inode use per filesystem** (your answer) | A disk can be full of files while bytes are free. Network errors and drops are left out. |
| Where the numbers are computed | The script prints raw counters, the collector computes rates and percentages | The loop stays small and cheap on the server, and the arithmetic is Python that unit tests cover. Rejected: computing percentages in awk on the server. |
| Time of a sample | The collector's clock when the line arrives | A server with a wrong clock cannot write into the wrong chunk or outside the retention window. Rates use the server's own uptime between two samples, so network delay does not distort them. |
| Finding servers | The collector reads `servers` every 10 seconds | A new, changed or removed server is picked up within 10 seconds with one small query. Rejected: a change notification through Valkey, which still needs the same poll as a fallback. |
| Database role | New role `megooitadmin_collector` with its own password | The collector can insert metrics and write its state table. It cannot read users, sessions or grants. The backend still cannot insert metrics. |
| The SSH key | The collector mounts the `ssh_key` volume read-only | It signs in with the platform's key, like the backend. Phase 3 moves the key into the vault. |
| `AUTH_SECRET_KEY` | The collector does not get it | `Settings` no longer requires the key. `auth_key()` fails with an error that names the variable, and the API still refuses to start without it (entrypoint guard and `create_app()`). |

## Architecture

**New package `backend/app/collector/`**

| File | Holds |
|---|---|
| `script.sh` | The loop the server runs. POSIX `sh` and `awk`, no sudo, no file written. It takes the interval as its argument. |
| `parse.py` | Validates one JSON line (Pydantic) into raw counters, with size limits. |
| `compute.py` | Two consecutive raw samples in, the `Reading`s of the table below out. A pure function. |
| `stream.py` | One server's task: connect, start the loop, read lines, hand samples on, reconnect with backoff, run the 30-second watchdog. |
| `writer.py` | A bounded buffer and one task that writes everything collected, at most once a second, with `metrics.store.write_samples`. |
| `state.py` | Reads and writes `server_status`. |
| `supervisor.py` | Reads `servers` every 10 seconds and starts, restarts or stops the stream tasks. Touches the heartbeat file. |
| `__main__.py`, `health.py` | Start-up, a clean stop on SIGTERM, and the container's healthcheck. |

**How one stream works**

1. The supervisor gives the task a server's address, port, account, pinned key and interval. A change to any of them restarts the task.
2. The task signs in through `inventory.connection.open_connection` with `Actor.system("collector")`. So the pinned host key is checked, and a changed key flags the server and records `server.host_key_mismatch`, exactly as for a person.
3. It starts `sh -s <interval>` on one channel and sends `script.sh` on stdin. Nothing is installed on the server.
4. Every line becomes a `Sample`. It is published at once with `metrics.fanout.publish` and put in the writer's buffer.
5. When the channel ends or 30 seconds pass without a sample, the task closes the connection and tries again after 1, 2, 4 … up to 60 seconds, with jitter. A sample resets the delay. The loop on the server ends by itself when its output closes.

At most 20 sign-ins run at the same time, so a restart with a few hundred servers does not open them all at once. Run one collector: a second one would publish every sample twice.

**Existing files touched**

- `app/core/config.py`, `app/main.py`: `auth_secret_key` optional as described.
- `app/core/db_roles.py`, `docker-entrypoint.sh`: the entrypoint also sets the collector role's password from `DATABASE_COLLECTOR_URL`, then unsets that variable before the server starts. Without the variable the role keeps no login and the entrypoint says so.
- `app/inventory/models.py`, `server_schemas.py`, `servers.py`: the interval field and the monitoring state.
- `docker-compose.yml`: service `collector` (below). `docker-compose.build.yml` gives it the locally built backend image.
- `Makefile`, `.env.example`, `tools/stacks/*.env`, `megoocolab.toml`: `POSTGRES_COLLECTOR_PASSWORD`. `make up` and `make upgrade` add it to an older `.env`, so nobody has to act.
- `tools/fake-server/entrypoint.sh`: host keys are made at the container's first start and kept when it restarts. `swap-host-key` still changes them on purpose.
- `README.md`, `AGENTS.md`, `docs/server-setup.md` (what the collector runs on a server).

## Data and interfaces

**Migration `0009`**

- Role `megooitadmin_collector`, created without login like `megooitadmin_api`.
- `servers.metrics_interval_seconds`: `smallint`, not null, default 5, check 1 to 10.
- Table `server_status`:

| Column | Type | Notes |
|---|---|---|
| `server_id` | `uuid`, primary key | Foreign key to `servers`, deleted with its server |
| `state` | `text` | `reachable`, `unreachable` or `not_monitored` |
| `reason` | `text`, null | Empty for `reachable`. For `unreachable`: `unreachable`, `key_refused`, `ssh_error` or `no_samples`. For `not_monitored`: `not_an_ssh_server`, `host_key_not_pinned` or `host_key_changed` |
| `since` | `timestamptz` | When the state or reason last changed |
| `last_sample_at` | `timestamptz`, null | The newest sample the collector had when it wrote the row |

The row is written only when the state or reason changes, not on every sample. A server without a row has not been looked at yet.

**Grants**

| Relation | `megooitadmin_collector` | `megooitadmin_api` |
|---|---|---|
| `metrics` | `INSERT` | unchanged (`SELECT`) |
| `server_status` | `SELECT`, `INSERT`, `UPDATE` | `SELECT` |
| `servers` | `SELECT`, and `UPDATE` only of the three columns a host key mismatch sets | unchanged |
| `audit_log`, `audit_chain_head` | What the audit writer needs to record the mismatch | unchanged |

The planner grants nothing beyond what the tests show these statements need.

**Server API**

- `ServerIn`, `ServerPatch`, `ServerOut` get `metrics_interval_seconds` (integer 1 to 10, default 5). A change is part of the `server.changed` event, like the other fields, and needs the same right as any edit.
- `ServerOut` gets `monitoring`: `{state, reason, since, last_sample_at}` or `null`.

**The line the server prints** (one per interval, compact JSON, at most 256 KB): version, uptime, CPU counters for the whole server and per core, the three load averages, memory and swap in kB, byte counters per network interface, sector counters and busy time per disk, and size, used, available, inodes and used inodes per filesystem. A line that does not parse or validate is dropped and counted. Its text is never logged.

**Metrics written**

| Metric | Instance | Meaning |
|---|---|---|
| `cpu.used_percent` | empty, and `cpu0`, `cpu1` … | Not idle and not waiting for I/O |
| `cpu.user_percent`, `cpu.system_percent`, `cpu.iowait_percent`, `cpu.steal_percent` | empty | Shares of the interval |
| `load.1m`, `load.5m`, `load.15m` | empty | |
| `mem.total_bytes`, `mem.available_bytes`, `mem.used_bytes`, `mem.used_percent` | empty | Used is total minus available |
| `swap.total_bytes`, `swap.used_bytes` | empty | |
| `net.rx_bytes_per_sec`, `net.tx_bytes_per_sec` | interface | Not `lo`, not `veth*` |
| `diskio.read_bytes_per_sec`, `diskio.write_bytes_per_sec`, `diskio.busy_percent` | disk | Whole disks only: no partitions, loop, ram or device-mapper entries |
| `disk.total_bytes`, `disk.used_bytes`, `disk.used_percent`, `disk.inodes_used_percent` | mount point | Local filesystems only |

A server with 4 cores, one interface, one disk and two filesystems gives about 30 rows per sample.

**Compose service `collector`**: the backend image, `entrypoint` replaced by `python -m app.collector`, `restart: unless-stopped`, networks `core` and `servers`, no port, `ssh_key` mounted read-only, `DATABASE_URL` as `megooitadmin_collector`, `VALKEY_URL`, waits for a healthy `backend` (so the migrations ran and the role has its password) and a healthy `valkey`. Healthcheck: `python -m app.collector.health`, which passes while the supervisor read `servers` within the last 30 seconds.

## Error handling and edge cases

- **Rates need two samples.** The first sample after a connect carries only load, memory and filesystems. A counter that went down or an uptime that went back (a reboot) skips the rates of that sample.
- **A server that cannot be tried** (Windows, no pinned key, flagged for a changed key) gets `not_monitored` at once and no connection attempt. It is tried again once that changes.
- **A changed host key** met by the collector flags the server once. The collector then stops trying until an admin accepts or keeps the key.
- **A refused key or an unreachable address** is retried with backoff, at most once a minute.
- **A stalled stream** (the connection is open but silent) is closed after 30 seconds and marked `unreachable` with `no_samples`.
- **The database is down**: samples are still published. The buffer keeps the newest 10,000 samples and drops the oldest beyond that, with one warning a minute. State changes are written when the database is back.
- **Valkey is down**: samples are still written. Publishing is skipped with a warning.
- **A hung network mount** cannot stall the loop: `df` is called only for the mount points of local filesystems, read from `/proc/mounts`.
- **Device names from the server** are untrusted: they are JSON-escaped by the script, limited to 255 characters, and at most 256 cores, 64 interfaces, 64 disks and 64 filesystems are kept per sample.
- **A server removed while it streams**: its task stops within 10 seconds. Samples written in between age out with the retention windows.
- **The collector restarts**: every server keeps its last state until a sample arrives or 30 seconds pass. Samples during the stop are lost, which leaves a gap in the charts.
- **The collector is stopped**: `server_status` keeps the last states. Compose restarts it, and its healthcheck shows the stop.
- **SIGTERM**: the collector closes its channels, writes what is in the buffer and exits within Compose's stop timeout.

## Testing

Tests are written first. Thresholds and delays are parameters, so the tests of the `test` set run with a 1-second watchdog and short backoff.

- **Script** (against the fake server): it prints valid lines at the asked interval, runs as `megoo` without sudo, and its process is gone after the channel closes.
- **Parse and compute** (unit): the readings of two known samples, a counter reset, a first sample, a malformed line, a line that is too long, too many devices, odd device names.
- **Stream** (fake server, real TimescaleDB and Valkey): samples reach a subscriber and `metrics`; three server rows give three sign-ins and three loops; a killed SSH session reconnects; a paused container is marked `unreachable` with `no_samples` and comes back as `reachable`; a wrong account gives `key_refused`; a swapped host key flags the server, records one `server.host_key_mismatch` by the system actor `collector` and stops the attempts; a changed interval restarts the loop.
- **Supervisor**: a new server starts streaming, a removed one stops, Windows and unpinned servers get `not_monitored`.
- **Writer**: one insert for a batch; with the database unreachable, publishing continues and the buffer drops the oldest.
- **Migration**: `0009` goes down and up; the check refuses an interval of 0 and 11.
- **Privileges** (`tests/security/test_db_privileges.py`): the collector role's grants, column grants included, are exactly the declared ones. It can insert a metric and cannot read `users`. The API role still cannot insert a metric and can read `server_status`.
- **Server API**: the interval is validated, stored and audited; `monitoring` is returned.
- **Settings and container**: the API still refuses to start without `AUTH_SECRET_KEY`; the entrypoint sets the collector's password and the server process does not hold it.
- **Stack** (`test_stack.py`), the task's "done when": six services; the collector is on `core` and `servers`, mounts `ssh_key` read-only, has no port and no `AUTH_SECRET_KEY`. After the owner pins the fake server, rows appear in `metrics` and a subscriber gets samples. After a restart of the fake server, and after a restart of the collector, streaming resumes. After the fake server is cut from the network for more than 30 seconds, it is `unreachable`, and after it is joined again it is `reachable` and streams.
- The existing checks (`make test`, `make test-security`) stay green.

## Out of scope

- Any screen: the interval field in the Edit dialog, a reachable badge, the live dashboard, the WebSocket route and the server detail page.
- The slower checks of PRD §5.1 (service status, pending updates, failed logins, certificate expiry, top processes, containers).
- Alert rules, and publishing state changes on Valkey.
- Audit events for reachable and unreachable.
- Windows servers, ZFS datasets and network filesystems.
- More than one collector, and a setting for the 30-second threshold.