# MITA-30 design: live log streaming backend (journal, files, containers)

## Goal

People with View logs in a server's group follow its systemd journal, its allowlisted log files and its Docker containers live over one WebSocket, `/api/ws/logs`. A new `logs` worker service holds one SSH channel per source however many people watch it, and each viewer first gets the last 200 lines. This task builds no screen: the viewer is a later task.

Mockup **v1** is the picture of the parts and the messages between them.

## Decisions

| Decision | Chosen | Why, and what was rejected |
|---|---|---|
| Who holds the SSH channels | **A separate `logs` worker service** (your answer) | The backend opens no SSH connection for logs. Rejected: a hub inside the backend process, and all shared state in Valkey. |
| Scope | **The stream plus the allowlist API** (your answer) | No screen. Listing a server's units and files stays with the log viewer task. Rejected: a discovery read, the allowlist screen, and the stream alone. |
| The worker's database role | **A role of its own, `megooitadmin_logs`** (your answer) | It reads servers, containers and the allowlist, and may flag a changed host key. Rejected: the collector's role, which may also write metrics and alerts. |
| "30 minutes idle" | **The viewer did nothing in the log view for 30 minutes** (your answer) | The browser tells the socket about activity. Rejected: a source that printed nothing for 30 minutes. |
| Audit | **Opened and closed** (your answer) | Closed carries the duration and the reason. It is missing when the backend is killed. |
| A group's allowlist at the start | **Four starter patterns in every group** (your answer) | `/var/log/syslog`, `/var/log/messages`, `/var/log/nginx/*.log`, `/var/log/apache2/*.log`. An Admin can remove them. |
| The cap and the idle time | **Two settings with the PRD's defaults** (your answer) | `LOG_STREAM_MAX_LINES_PER_SECOND=2000` and `LOG_STREAM_IDLE_MINUTES=30`. |

Decisions I made (say so if you want one changed):

1. **Valkey carries pub/sub only.** Valkey runs with an append-only file, and a Valkey list or key would put log lines on disk. The last 200 lines of a running source live in the worker's memory.
2. **The worker counts viewers by asking Valkey** how many subscribers a source's channel has (`PUBSUB NUMSUB`, every second). A source without a subscriber for 5 seconds closes. A closed browser or a killed backend loses its subscription by itself, so there is no viewer bookkeeping to go wrong. The 5 seconds keep a page reload from closing and reopening the channel.
3. **The worker checks every request again in the database**: the server, the file path against the group's allowlist, the container. Anything on the `core` network can publish on Valkey, so the backend's check alone is not enough. The person's right is checked by the backend, which knows the person.
4. **One SSH connection per server, one channel per source on it**, at most 8 sources per server at once (OpenSSH allows 10 channels per connection by default). The connection closes with its last source.
5. **A filter is part of the source.** Two viewers share a channel when they ask for the same server, kind and filters. `nginx.service` at priority warning is another source than `nginx.service` without a priority.
6. **A file source is one file.** A viewer names a path, and the path must match one of the group's patterns. A pattern never streams several files into one source.
7. **"Boot" is a switch, "this boot only".** A followed journal grows only in the current boot, so the filter decides only what the first 200 lines may hold.
8. **`megoo-ctl` stays at version 1.** `docker logs --follow --tail` is already there, and the journal and files need no sudo (`systemd-journal` and `adm`). No server runs the setup script again.
9. **Nothing stays behind on the server.** Each command runs under a fixed `sh` wrapper that ends it when the channel closes. Without it a quiet `tail -F` would stay until its next line.
10. **A source that ends is not restarted by the worker.** Viewers get `ended` with the reason and may ask again. Reconnecting is the viewer's job.
11. **A slow browser** loses its socket with close code `1013`, as on the metrics socket, and gets the last 200 lines again when it reconnects.
12. **The worker ships as the backend image** run with `python -m app.logs.worker`, like the collector: one image, one `uv.lock`.

## Architecture

**Shared package `backend/app/logs/`** (used by the backend and the worker)

| File | Holds |
|---|---|
| `sources.py` | The three sources as Pydantic models, their rules, the key of a source (a hash of server, kind and filters) and the command each one runs, as a list of arguments. |
| `allowlist.py` | The rules of a pattern, `matches(path, patterns)`, the four starter patterns, and list, add and remove with their events. |
| `lines.py` | Turns a raw line into `{seq, time, text, …}` per kind, and cuts a line over 8 kB. |
| `protocol.py` | The Valkey channel names and the messages on them. |
| `models.py`, `schemas.py`, `actions.py` | The `log_file_allowlist` table, the API's shapes, the audit action names. |
| `router.py` | The allowlist routes. |
| `socket.py` | `/api/ws/logs`, built like `metrics/socket.py`: one Valkey subscription and a bounded queue per socket, and a task group. |

**The worker `backend/app/logs/worker/`**

| File | Holds |
|---|---|
| `__main__.py`, `health.py` | The process (SIGTERM closes every channel) and its healthcheck, a heartbeat file like the collector's. |
| `hub.py` | Listens on `logs:requests`, checks each request, keeps the running sources by key, counts subscribers every second, publishes `alive` every 5 seconds. |
| `source.py` | One running source: the channel, the reader, the cap, the last 200 lines, and the publisher (a batch every 100 ms or 500 lines). |
| `links.py` | One SSH connection per server through `open_connection`, shared by the server's sources. At most 20 sign-ins at once. |
| `cap.py` | The cap: per second, lines over the limit are dropped and counted. |

**Other changes**

- `app/ssh/client.py`: `follow(conn, argv, …)` starts a command under the wrapper and yields its output. It stays the only module that uses asyncssh.
- `app/inventory/service.py`: a new group gets the starter patterns; the group's created and deleted events carry its patterns.
- `app/core/config.py`, `app/core/db_roles.py`, `docker-entrypoint.sh`: the two settings, `DATABASE_LOGS_URL`, and the password step for `megooitadmin_logs`.
- `app/main.py`: includes the two routers.
- `docker-compose.yml`, `docker-compose.build.yml`: the `logs` service (networks `core` and `servers`, the SSH key read-only, its own database URL, a healthcheck). Run one: a second one would open every source twice.
- `Makefile`, `.env.example`, `tools/stacks/*.env`, `megoocolab.toml`, CI: `POSTGRES_LOGS_PASSWORD`. `make up` and `make upgrade` add the line to an older `.env`, as they did for the collector.
- `tools/fake-server/`: see Testing.
- Docs: `README.md` (live logs, the new service and settings), `docs/server-setup.md` ("What the logs worker runs"), `AGENTS.md`.

## Data and interfaces

### Sources

| Kind | Fields | Runs on the server |
|---|---|---|
| `journal` | `server_id`, optional `unit`, optional `priority` (`emerg` to `debug`: that level and worse), optional `this_boot` | `journalctl --no-pager -f -o json -n 200 [-u unit] [-p n] [-b]`, with only the fields the viewer needs |
| `file` | `server_id`, `path` | `tail -n 200 -F -- <path>` |
| `container` | `server_id`, `container_id` | `sudo -n /usr/local/sbin/megoo-ctl docker logs <id> --follow --tail 200` (`megoo-ctl` adds `--timestamps`); the container's error output is merged in |

Rules: a unit is letters, digits and `:_.@-`, at most 255 characters, starting with a letter or digit. A path is absolute, at most 255 characters of `A-Za-z0-9._/@%+=:,-`, without `..` and without wildcards. A container must be a row of `containers` for that server. Nothing a person types reaches a shell unchecked.

A line is `{seq, time, text}`. Journal lines add `level` (from the priority) and `unit`. A container line takes its time from Docker's timestamp; a file line gets the time the worker read it. `truncated: true` marks a cut line.

### Migration `0012`

- The role `megooitadmin_logs`, without login until the entrypoint sets its password.
- `log_file_allowlist`: `id`, `server_group_id` (deleted with its group), `pattern`, `created_at`. Unique per group and pattern.
- The four starter patterns for every existing group.
- Grants: `megooitadmin_api` gets `SELECT, INSERT, DELETE` on the table. `megooitadmin_logs` gets `SELECT` on `servers`, `containers` and `log_file_allowlist`, plus what `open_connection` needs to flag a changed host key (the three host key columns of `servers`, `INSERT` on `audit_log`, `SELECT, UPDATE` on `audit_chain_head`). Both are declared in `tests/security/test_db_privileges.py`.

**A pattern** is an absolute path with the same characters as a path, plus `*` and `?`. A wildcard never matches `/`, so `/var/log/*.log` does not cover `/var/log/nginx/access.log`. The first path segment holds no wildcard (`/*` is refused). At most 50 patterns per group.

### Allowlist API

| Route | Who | Does | Audit |
|---|---|---|---|
| `GET /api/server-groups/{group_id}/log-allowlist` | Sees the group | `{can_manage, patterns: [{id, pattern, created_at}]}` | none |
| `POST /api/server-groups/{group_id}/log-allowlist` | Owner, the group's Admins | Adds `{pattern}`. `422` invalid, `409 pattern_exists`, `409 too_many_patterns` | `log_allowlist.pattern_added` |
| `DELETE /api/server-groups/{group_id}/log-allowlist/{pattern_id}` | Owner, the group's Admins | Removes it | `log_allowlist.pattern_removed` |

### `WS /api/ws/logs`

The handshake is the shared one (`auth/socket.py`).

| Direction | Message |
|---|---|
| Browser → backend | `{"type":"subscribe","sources":[…]}`. Replaces the socket's set: sources already open stay open, new ones open, the others close. At most 16 sources and 16 kB. |
| | `{"type":"active"}`: the person did something in the view. The browser sends it at most once a minute. |
| Backend → browser | `{"type":"subscribed","sources":[{"id","source"}],"denied":[{"source","reason"}]}` after each subscribe. |
| | `{"type":"lines","source":id,"lines":[…],"backlog":true}` once per source, then the same without `backlog` for new lines. |
| | `{"type":"skipped","source":id,"count":n}` when the cap dropped lines. |
| | `{"type":"ended","source":id,"reason":…}`: the source is closed for this viewer. |
| | `{"type":"error","detail":"invalid_message"}`. The socket stays open. |

Denied reasons: `not_found` (no such server, or one the person does not see), `forbidden` (no View logs), `not_allowed` (a path outside the allowlist), and what the worker refuses: `not_an_ssh_server`, `host_key_not_pinned`, `host_key_changed`, `too_many_sources`.

Ended reasons: `idle`, `forbidden` or `not_found` (found by the 30-second recheck), `exited` with the command's status (a container stopped), `not_available` (no `journalctl` or `docker`), `denied` (sudo refused `megoo-ctl`), `not_readable` (the file is missing or `megoo` cannot read it), `unreachable`, `key_refused`, `ssh_error`, `host_key_changed`, `worker_unavailable`, `worker_restarted`.

Close codes: `4401` not signed in, `1013` the browser reads too slowly, `1011` Valkey cannot be reached. A foreign `Origin` gets 403.

### Valkey (pub/sub only)

| Channel | From → to | Carries |
|---|---|---|
| `logs:requests` | socket → worker | `open` with the socket's id and the source. No receiver means the worker is down. |
| `logs:viewer:<socket id>` | worker → one socket | `opened` with the lines the worker holds and the last `seq` among them, or `refused` with the reason. |
| `logs:source:<key>` | worker → the source's viewers | `lines`, `skipped`, `ended`. |
| `logs:worker` | worker → every socket | `alive` every 5 seconds with the worker's run id. |

A socket subscribes to the source's channel before it asks, holds the live lines until `opened` arrives, then sends the backlog and only the held lines with a higher `seq`. So a second viewer sees no gap and no line twice.

### Audit

- `logs.stream_opened`: the person, the server as target, the sources that opened, the group as context. Recorded before the request goes to the worker. If it cannot be recorded, nothing opens.
- `logs.stream_closed`: the same, with `duration_seconds` and the reason (`left`, `idle`, `signed_out`, or the ended reason).
- `access.denied` for a server the person does not see, a missing View logs right, or a path outside the allowlist: once per socket and server.
- `server.host_key_mismatch` by the system actor `logs` when a server presents another key.

### Settings

| Variable | Service | Default |
|---|---|---|
| `LOG_STREAM_MAX_LINES_PER_SECOND` | `logs` | 2000 |
| `LOG_STREAM_IDLE_MINUTES` | `backend` | 30 |
| `POSTGRES_LOGS_PASSWORD` | `.env` | made by `make up` |

## Error handling and edge cases

- **The worker is down**: the `open` request has no receiver, or no `opened` arrives within 5 seconds: `ended` with `worker_unavailable`.
- **The worker restarts or hangs**: sockets see another run id, or no `alive` for 15 seconds, and end their sources. The browser asks again.
- **Valkey is down**: the worker closes every source, and sockets close with `1011`.
- **The backend is killed**: its subscriptions go, so the worker closes the channels after 5 seconds. No closed event is written.
- **A noisy source**: over the cap, lines of that second are dropped and counted. `skipped` follows in the stream at the place of the gap.
- **A line over 8 kB** is cut. Bytes that are not UTF-8 are replaced. A journal message that is binary becomes text the same way.
- **Session ended or idle**: the 30-second recheck closes the socket with `4401`. A socket never counts as session activity, as in MITA-28.
- **A lost right, a moved or removed server, a removed pattern**: the recheck ends that source for that viewer. The worker also rechecks a file source's pattern every 30 seconds.
- **30 minutes without `active` or `subscribe`**: every source of that socket ends with `idle`. The socket stays open, and a new subscribe starts again.
- **A container that stops**: `docker logs` exits, and viewers get `exited`.
- **A rotated file**: `tail -F` follows the new file.
- **A symbolic link inside an allowed directory** is followed. What `megoo` may read on the server is the limit.
- **sshd with `MaxSessions 1`**: a second source on that server ends with `ssh_error`.
- **Two requests for a new source at the same moment**: the hub starts one channel and answers both.
- **An Auditor** sees servers but never holds View logs: `forbidden`.

## Testing

Tests first. Times and limits are parameters, so tests run in seconds.

- **Fake server**: the `journalctl` and `docker` stubs learn to follow. With `-f` or `--follow` they print their fixture, then follow a file a test appends to. Files use the real `tail`. `tests/fake_server.py` gains helpers to append lines and to count follower processes.
- **Unit**: each source's rules and exact command; refused units, paths and containers; pattern rules and matching; the key of a source; line parsing per kind (a binary journal message, a bad timestamp, a long line, bad UTF-8); the cap with a fake clock; the protocol messages.
- **Worker** (real Valkey, fake server): a file's last 200 lines, then new ones; the journal and a container through the stubs; a second viewer gets the held lines and no second channel or sign-in; the source closes after its last subscriber and **no process stays on the server**, also for a quiet source; a burst over the cap, where kept plus skipped equals written; every refusal and every ended reason; the ninth source of a server; `alive`; a changed host key flags the server.
- **Socket**: the handshake; two admins on the same source both receive the lines while the worker holds one source (the task's "done when"); the backlog rule without gaps or repeats; every denied reason with its `access.denied`; opened and closed events with person, server, sources, duration and reason; a subscribe that replaces the set; idle ends the sources and the channel closes; `active` resets the timer; the recheck after a lost right; a missing and a restarted worker; the full queue; an invalid message.
- **Allowlist API**: list, add, remove; the guards (404 for an unseen group, 403 for a non-Admin); duplicate, invalid and the 51st pattern; the events; a new group gets the starter patterns; the created and deleted events carry them.
- **Migration and privileges**: `0012` goes down and up; existing groups get the starter rows; the declared grants are the exact ones; `megooitadmin_logs` cannot write `metrics` or read `users`; the entrypoint sets its password.
- **Security suites**: socket-coverage pins `/api/ws/logs`; permission-coverage and audit-coverage know the three routes.
- **Image and stack**: the image starts `python -m app.logs.worker`; in the stack, the `logs` service becomes healthy, and two sockets through Caddy receive the same lines of a file on the fake server while it runs one follower.
- The existing gates stay green: backend `pytest`, `pytest -m docker`, `pytest -m stack`, `make test-security`. The frontend does not change.

## Out of scope

- Every screen: the Logs page, a server's Logs tab and the allowlist editor.
- Listing a server's units and the files that match a pattern.
- Text, regex and level filters, merged views, saved views (`log_views`), download and "Send to assistant".
- Storing or searching log history.
- Podman and the Windows Event Log.
- Restarting an ended source from the worker.
- More than one logs worker, and a limit of sockets per person.
- The agents' `read_logs` tool (Phase 4).
