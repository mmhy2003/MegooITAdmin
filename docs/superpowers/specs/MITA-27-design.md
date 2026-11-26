# MITA-27 design: slow checks and container discovery

## Goal

A Linux server's page shows five facts the collector checks on their own intervals (failed services, pending updates, failed SSH sign-ins, certificate expiry, top processes) and the server's Docker containers grouped by Compose project. The numbers of these checks also land in `metrics`, ready for the alert rules and charts of the next tasks.

The approved screens are mockup **v2** (layout B).

## Decisions

| Decision | Chosen | Why, and what was rejected |
|---|---|---|
| Container runtimes (PRD §17.2) | **Docker only** (your answer) | `megoo-ctl` 1 already allows `docker ps`. `containers.runtime` exists so Podman can join without a schema change. Rejected: Podman now, which needs `megoo-ctl` 2 on every server. |
| Certificates | **What the server serves on its TLS ports** (your answer) | No sudo and no `megoo-ctl` change. Rejected: certificate files on disk (root only), both, and a check from outside. |
| How checks run | **Short scripts on a second channel of the stream's SSH connection** (your answer) | No extra sign-ins, and a slow check cannot delay samples or trip the 30-second rule. Rejected: inside the metrics loop, and a connection per check. |
| What is kept | **The latest result per server and check, plus its numbers as metrics** (your answer) | Rejected: latest only, and a history table. |
| Intervals | **Fixed in code** (your answer): containers 30 s, top processes 30 s, services 60 s, failed logins 5 min, pending updates 60 min, certificates 6 h | Like the 30-second unreachable rule. They are constructor parameters, so tests run them in seconds. |
| Package managers | **apt, and dnf from its cache only** (your answer) | dnf never downloads. When it cannot answer from its cache, the check is "not available". |
| Page layout | **B** (your answer): check cards on Overview, containers on a new Containers tab, a one-line summary on Overview | The PRD's Containers tab starts here, read-only. |
| Scope | **Everything in this task** (your answer) | Rejected: screens as a follow-up. |
| `megoo-ctl` | Stays version 1 | Only `docker ps` needs sudo, and that call exists. No server runs the setup script again. |
| A container Docker no longer lists | Its row is deleted at the next successful check | `last_seen_at` says how fresh a row is when the server is unreachable. Rejected: keeping removed containers, which fills the page with one-off containers. |
| Top processes and PRD §13 ("process snapshots are not stored") | Only the latest top five by CPU and by memory are kept, replaced every 30 seconds, **names only** | Command lines often hold secrets. Reading them needs the existing **View processes** right; the other checks and the containers are visible to everyone who sees the server. |
| Failed logins | A count for the last 24 hours and the five most frequent source addresses. **No user names** | The name in a failed sign-in is text an attacker chose, and people sometimes type a password there. |
| Top-process CPU | Measured over one second from `/proc` | `ps` reports the average over a process's whole life, which hides a process that just started spinning. |

## Architecture

**On the server**: six read-only POSIX `sh` scripts in `backend/app/collector/checks/`. Each is sent on stdin to `sh -s`, like the metrics loop: nothing is installed and no file is written. Each bounds its own commands with `timeout`, so nothing outlives a check, and prints one JSON status line (`ok` or `not_available`) followed by its result.

| Check | Every | What the script runs | Result |
|---|---|---|---|
| `containers` | 30 s | `sudo -n /usr/local/sbin/megoo-ctl docker ps` (the only sudo call) | Docker's JSON lines: id, name, image, state, status, and the labels `com.docker.compose.project` and `.service` |
| `processes` | 30 s | Two reads of `/proc/[pid]/stat` one second apart, and `ps` for user, memory and name | Top 5 by CPU, top 5 by memory: PID, name, user, CPU %, memory |
| `services` | 60 s | `systemctl list-units --type=service --all --plain --no-legend` | Counts (total, running, failed) and up to 50 failed units with their description |
| `logins` | 5 min | `journalctl` for `sshd` and `sshd-session`, last 24 hours, counted with `awk` on the server | Failed password attempts on existing accounts plus connections that named an unknown account; the top 5 source addresses |
| `updates` | 60 min | `apt-get -s upgrade` (no lock, no download), or `dnf -C check-update` | Pending and security updates, restart required, when the package lists were last refreshed |
| `certificates` | 6 h | `openssl s_client` to `127.0.0.1` on 443, 465, 636, 853, 993, 995, 5671, 6443, 8443, 8883 and 9443, 5 seconds each. The server's registered address is sent as the server name when it is a host name | Per answering port: subject, issuer, expiry, SHA-256 fingerprint |

**In the collector** (`backend/app/collector/`)

- `checks/__init__.py`: the registry: kind, interval, timeout (30 s; 60 s for `updates` and `certificates`), script.
- `checks/parse.py`: one Pydantic model per result, with size limits, in the style of `parse.py`. Output is capped at 1 MB; 500 containers, 50 units and 16 certificates are kept; names are limited to 255 characters and a name with a control character is dropped. The certificate date is parsed here. Text from the server is never logged.
- `checks/runner.py`: one task per connected server. It holds the timetable, runs the check that is due, one at a time, and hands the outcome to the store and the metrics. The timetable lives on the `Stream`, so a reconnect does not repeat a check before its interval passed. The first round starts after a random delay of up to 10 seconds, so a collector restart does not hit every server at once.
- `stream.py`: `_session` starts the runner beside the loop's channel and cancels it when the session ends. Check readings go straight to the `Publisher` and the `Writer`; they never count as a sample for the 30-second rule. A runner error never ends the stream.
- `app/ssh/client.py`: `run_script(conn, script, args, *, timeout, max_output)` returns the exit status and the capped output. Arguments are validated there (`[A-Za-z0-9.-]`, at most 253 characters). This stays the only module that uses asyncssh.

**Shared package `backend/app/checks/`** (like `app/metrics/`): `models.py` (`ServerCheck`, `Container`), `store.py` (write one check's row; replace a server's containers in one transaction), `schemas.py` and `router.py` (the two routes below).

**Frontend** (`frontend/src`)

- `lib/checks.ts`: the types, `groupContainers` (projects by name, "No Compose project" last), `isOld` (older than three intervals), and the texts of each state.
- `components/servers/checks/`: `check-card.tsx` (the frame: title, the state badge, the footer "Checked … ago · every …"), `services-card.tsx`, `updates-card.tsx`, `logins-card.tsx`, `certificates-card.tsx`, `top-processes-card.tsx`, `containers-summary-card.tsx`, `containers-tab.tsx`.
- `server-page.tsx`: real tabs, **Overview** and **Containers** (with the count), chosen with `?tab=containers`. A Linux server's page reads the checks and the containers on load and in the existing 15-second background refresh. A Windows server shows neither the cards nor the tab.
- Colours always come with a text: failed services pink; a certificate expired or under 7 days pink, under 30 days amber; security updates and "Restart required" amber; containers running green, restarting or paused amber, the rest muted.

**Docs**: `docs/server-setup.md` ("What the collector runs" lists the six checks and their commands, and says `megoo-ctl` stays at version 1) and the Servers section of `README.md`.

## Data and interfaces

**Migration `0010`**

`server_checks`, primary key (`server_id`, `kind`), deleted with its server:

| Column | Notes |
|---|---|
| `kind` | `containers`, `processes`, `services`, `logins`, `updates` or `certificates` (check constraint) |
| `status` | `ok`, `not_available` (the tool is not on the server), `denied` (sudo refused `megoo-ctl`), `timeout` or `failed` |
| `checked_at` | The last run, whatever its outcome |
| `data`, `data_at` | The last good result as JSONB, and its time. A failed run keeps both |

`containers`, primary key (`server_id`, `runtime`, `container_id`), deleted with its server: `runtime` (`docker`, check constraint), `container_id`, `name`, `image`, `compose_project` (null), `compose_service` (null), `state` (Docker's word, `unknown` for anything else), `status` (Docker's text, such as "Up 3 days (healthy)"), `first_seen_at`, `last_seen_at`.

Grants: `megooitadmin_collector` gets `SELECT, INSERT, UPDATE` on `server_checks` and `SELECT, INSERT, UPDATE, DELETE` on `containers`; `megooitadmin_api` gets `SELECT` on both. Both are declared in `tests/security/test_db_privileges.py`.

**Metrics** (written only when the check's status is `ok`)

| Metric | Instance |
|---|---|
| `services.failed` | empty |
| `updates.pending`, `updates.security`, `updates.reboot_required` (0 or 1) | empty |
| `logins.failed_24h` | empty |
| `cert.days_left` | empty for the nearest expiry, and one per port (`443`). Negative once expired |
| `containers.running`, `containers.not_running` | empty |

**API** (both need only that the person sees the server, `require_group_visible`; an invisible server answers 404)

- `GET /api/servers/{server_id}/checks` → `{can_view_processes, checks: [{kind, status, checked_at, every_seconds, data, data_at}]}`. Always six entries in a fixed order; a check that never ran has `status: "not_checked"`. The `processes` entry carries `data` only with the View processes right in the server's group.
- `GET /api/servers/{server_id}/containers` → a list of `{container_id, runtime, name, image, compose_project, compose_service, state, status, first_seen_at, last_seen_at}`, ordered by project, then name.

No new setting, no new Compose service, no change to `megoo-ctl` or `megoo-setup.sh`.

## Error handling and edge cases

- **A tool is missing** (no Docker, no systemd, no apt or dnf, no openssl, no journalctl): `not_available`, and the card says so.
- **sudo refuses `megoo-ctl`**: `denied`; the Containers tab points to the setup script.
- **A check times out or prints something that does not parse**: `timeout` or `failed`. The last good result stays, with its time. The server stays reachable.
- **sshd allows only one session per connection** (`MaxSessions 1`): the second channel is refused, so every check is `failed`. Metrics are unaffected.
- **The server becomes unreachable**: nothing is written. Results older than three intervals show "Last checked … ago" in amber.
- **The database is down**: a check's row is dropped with a throttled warning and written again at its next run. Its metrics wait in the writer's buffer as today.
- **`docker ps` fails**: the `containers` rows stay untouched. Only a successful listing adds, updates and deletes rows.
- **A spoofed source address**: the address is taken after the last " from " of a journal line, because the user name before it is the attacker's text, and it is kept only when it parses as an IP address.
- **A web server with many sites** shows only the certificate of its default site (or of the server's registered host name). The card's footer says what is checked.
- **dnf without a usable cache**, or without security information in it: `not_available`, or a count with "security" left out.
- **Package lists are only as fresh as the server's own refresh**: the card shows when that was.
- **More than 500 containers, 50 failed units or 16 certificates**: the rest is left out; the counts stay complete.
- **A person without View processes**: the card says which right is missing; no refusal is audited, as nothing was asked for.
- **A removed server**: its runner stops with its stream, and its rows go with it.

## Testing

Tests first. Intervals and timeouts are parameters.

- **Fake server** (`tools/fake-server`): `openssl` is installed, and `fake-tool` also stands in for `journalctl`, `apt-get` and `dnf` and prints a fixture file when one exists for the call. The image ships default fixtures for `docker ps` and `systemctl`, so a dev stack's page shows containers and services.
- **Scripts** (against the fake server, as `megoo`): each prints valid output from its fixture; `not_available` without its tool; `containers` calls exactly `megoo-ctl docker ps` (the tool log); `certificates` finds a self-signed certificate that the test serves on 8443 with `openssl s_server`, and nothing on a closed port; `processes` puts a busy loop the test starts on top; no process is left after a check.
- **Parsing** (unit): each result, its limits, a control character in a name, a line that is too long, the certificate date, Compose labels, the last " from ", an address that is not one, dnf's exit codes.
- **Runner**: a check runs when due and not before; one at a time; a timeout closes the channel and gives `timeout`; a reconnect keeps the timetable; a hung check does not stop samples; a failing store does not stop the stream.
- **Store**: the upsert keeps `data` on a failed run; a new listing adds, updates and deletes containers and keeps `first_seen_at`; a failed listing changes nothing.
- **Metrics**: the readings of each check; none when the status is not `ok`.
- **Migration and privileges**: `0010` goes down and up; the declared grants are the exact ones; the API role cannot write either table.
- **API**: the six entries; `not_checked`; `processes` with and without the right; 404 for a server the person does not see; the permission-coverage suite knows both routes.
- **Frontend** (Vitest): each card in each state (ok, nothing to report, not available, could not be checked, old, not checked yet); the colour rules; grouping and order of containers; the tab follows `?tab=`; the background refresh updates the cards and sends nothing while a dialog is open; a Windows server shows neither cards nor tab.
- **Stack** (the task's "done when"): after the Owner pins the fake server, `/checks` returns six checks with a result and `/containers` returns the fixture's containers with their Compose projects.
- The existing gates stay green: backend `pytest`, `pytest -m docker`, the frontend checks and image check, `pytest -m stack`, and `make test-security`.

## Out of scope

- Podman, and rootless containers.
- Container actions (start, stop, restart), container CPU and memory, and live logs: Phase 2 and the log viewer task.
- The full Processes and Services tabs, and command lines of processes.
- Alert rules and charts on the new metrics.
- Certificate files on disk, STARTTLS ports, and a per-server list of ports or site names.
- zypper, apk and other package managers; refreshing a server's package lists.
- Failed logins other than SSH, and the names that were tried.
- Changing intervals in a setting or per server, and a history of check results.
- Windows servers.
