# MITA-27 plan: slow checks and container discovery

## Goal

A Linux server's page shows the five slow checks (failed services, pending updates, failed SSH sign-ins, certificate expiry, top processes) and its Docker containers grouped by Compose project. The collector runs the checks on their own intervals, and their numbers also go to `metrics`.

## Architecture

Six read-only POSIX `sh` scripts in `backend/app/collector/checks/` run as `sh -s [name]` on a **second channel** of each stream's SSH connection (`client.run_script`). Each prints one JSON status line and then its body. `checks/parse.py` turns that into a Pydantic result. `checks/runner.py` holds the timetable (kept on the `Stream`), runs one due check at a time, and hands the outcome to a `Recorder`. The `Recorder` writes `server_checks` and `containers` (shared package `app/checks/`) and sends the numbers as a `Sample` to the existing `Publisher` and `Writer`. Two read-only API routes serve the rows. The frontend shows check cards on Overview and a new Containers tab (`?tab=containers`).

## File map

**Backend: create**
- `backend/app/checks/__init__.py`: package docstring.
- `backend/app/checks/models.py`: `Kind`, `KINDS`, `Status`, `STATUSES`, `CONTAINER_STATES`, the `SeenContainer` dataclass, and the ORM models `ServerCheck` and `Container`.
- `backend/app/checks/store.py`: `write_check`, `replace_containers`, `read_checks`, `read_containers`.
- `backend/app/checks/schemas.py`: `CheckOut`, `ChecksOut`, `ContainerOut`.
- `backend/app/checks/router.py`: `GET /servers/{server_id}/checks` and `GET /servers/{server_id}/containers`.
- `backend/migrations/versions/0010_checks.py`.
- `backend/app/collector/checks/__init__.py`: the `Check` dataclass, `script_of`, `CHECKS`.
- `backend/app/collector/checks/parse.py`: `MAX_OUTPUT`, `MAX_LINE`, `NotAvailable`, `CheckResult`, `Outcome`, `read`, and one result model and parser per kind.
- `backend/app/collector/checks/runner.py`: `Timetable`, `server_name`, `run_check`, `run_checks`, `Recorder`.
- `backend/app/collector/checks/{containers,processes,services,logins,updates,certificates}.sh`.
- Tests: `backend/tests/collector/test_check_parse.py`, `test_check_scripts.py`, `test_check_runner.py`, `test_collector_checks.py`; `backend/tests/checks/test_check_store.py`, `test_check_routes.py`.
- `tools/fake-server/fixtures/docker_ps`, `tools/fake-server/fixtures/systemctl_list-units`.

**Backend: modify**
- `backend/app/ssh/client.py`: `ScriptResult`, `ScriptTimeout`, `run_script`.
- `backend/app/collector/stream.py`, `supervisor.py`, `__main__.py`: start the check loop beside the metrics loop.
- `backend/app/models.py`: import `app.checks.models`.
- `backend/app/main.py`: include the checks router.
- `tools/fake-server/Dockerfile`, `tools/fake-server/fake-tool`; `backend/tests/fake_server.py` (`fixture`, `hidden`).
- `backend/tests/security/test_db_privileges.py`, `test_permission_coverage.py`, `backend/tests/test_migrations.py`, `backend/tests/test_stack.py`, `backend/tests/ssh/test_ssh_client.py`, `backend/tests/ssh/test_fake_server.py`.
- `docs/server-setup.md`, `README.md`.

**Frontend: create**
- `frontend/src/lib/checks.ts` and `frontend/src/lib/__tests__/checks.test.ts`.
- `frontend/src/components/servers/checks/`: `check-card.tsx`, `services-card.tsx`, `updates-card.tsx`, `logins-card.tsx`, `certificates-card.tsx`, `top-processes-card.tsx`, `containers-summary-card.tsx`, `containers-tab.tsx`, and tests in `checks/__tests__/`.

**Frontend: modify**
- `frontend/src/components/servers/server-page.tsx` and its test; `frontend/src/app/(app)/servers/[serverId]/page.tsx` (adds a `Suspense` wrapper).

## Shared contracts (every step uses these names)

**`app/checks/models.py`**
```python
Kind = Literal["containers", "processes", "services", "logins", "updates", "certificates"]
KINDS: tuple[Kind, ...] = get_args(Kind)          # this order is the API's order
Status = Literal["ok", "not_available", "denied", "timeout", "failed"]
STATUSES: tuple[Status, ...] = get_args(Status)
CONTAINER_STATES = ("created", "running", "paused", "restarting", "removing", "exited", "dead", "unknown")

@dataclass(frozen=True)
class SeenContainer:
    container_id: str; name: str; image: str
    compose_project: str | None; compose_service: str | None
    state: str; status: str
```

**`app/ssh/client.py`**
```python
@dataclass(frozen=True)
class ScriptResult:
    exit_status: int | None
    output: bytes
    truncated: bool          # output reached max_output, and the rest was not read

class ScriptTimeout(SshFailure):
    reason = "timeout"

async def run_script(conn: Connection, script: bytes, args: Sequence[str] = (), *, timeout: float, max_output: int) -> ScriptResult
```

**`app/collector/checks/parse.py`**
```python
MAX_OUTPUT = 1024 * 1024
MAX_LINE = 64 * 1024
class NotAvailable(Exception): ...      # a parser raises it: the tool cannot answer here
class CheckResult(BaseModel):           # frozen; extra="forbid"
    def data(self) -> dict[str, Any]: return self.model_dump(mode="json")
    def readings(self, now: datetime) -> tuple[Reading, ...]: return ()
@dataclass(frozen=True)
class Outcome:
    status: Status
    result: CheckResult | None = None   # set only when status == "ok"
def read(parser: Callable[[list[bytes]], CheckResult], result: ScriptResult) -> Outcome
```

**`app/collector/checks/__init__.py`**
```python
@dataclass(frozen=True)
class Check:
    kind: Kind
    every: float                                   # seconds between two runs
    timeout: float                                 # seconds one run may take
    script: bytes
    parse: Callable[[list[bytes]], CheckResult]
    server_name: bool = False                      # sends the server's host name as $1

def script_of(kind: str) -> bytes  # reads checks/<kind>.sh next to this file
CHECKS: tuple[Check, ...]  # final order and values:
# containers 30/30, processes 30/30, services 60/30, logins 300/30, updates 3600/60, certificates 21600/60 (server_name=True)
```

**`app/collector/checks/runner.py`**
```python
FIRST_DELAY = 10.0
class Timetable:
    def __init__(self, checks: Sequence[Check], *, first_delay: float = FIRST_DELAY, clock=time.monotonic) -> None
    def next(self) -> tuple[Check, float]           # the earliest due check (ties: registry order) and its due time
    def ran(self, kind: Kind, started: float) -> None  # due again at started + every
def server_name(address: str) -> str | None
async def run_check(conn: Connection, check: Check, address: str) -> Outcome   # never raises, except CancelledError
async def run_checks(conn: Connection, target: Target, timetable: Timetable, recorder: Recorder) -> None  # loops forever
class Recorder:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], publisher: Publisher, writer: Writer) -> None
    async def record(self, server_id: UUID, kind: Kind, outcome: Outcome, at: datetime) -> None   # never raises
```

### Check output protocol (R3)

- Line 1 is exactly one of `{"status":"ok"}`, `{"status":"not_available"}` or `{"status":"denied"}`. The body follows only after `ok`.
- `read()` gives: `truncated` → `failed`; `exit_status != 0` (or `None`) → `failed`; any line longer than `MAX_LINE` → `failed`; a first line that is not one of the three → `failed`; `not_available` / `denied` → that status; `ok` → `parser(body_lines)` (body lines without `b"\n"`, a trailing empty line removed). `NotAvailable` gives `not_available`, and `ValueError` (Pydantic's `ValidationError` included) gives `failed`. Nothing from the output is ever logged.
- Every script: `PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin; export PATH`, `LC_ALL=C; export LC_ALL`, and every external command that can wait is bounded by `timeout N`. A missing tool prints `{"status":"not_available"}` and then exits 0.

### Result models (parse.py)

Strings from the server: at most 255 characters (`MAX_NAME`), no control character (`CONTROL` from `app/collector/parse.py`). An entry with a bad name is dropped. Counts are always computed over every entry.

| Kind | Model | Fields | `readings(now)` |
|---|---|---|---|
| containers | `ContainersResult` | `containers: tuple[SeenContainer, ...]` (≤500), `total`, `running`, `not_running` | `containers.running`, `containers.not_running`; `data()` excludes `containers` |
| processes | `ProcessesResult` | `by_cpu`, `by_memory`: `tuple[Proc, ...]` (≤5 each); `Proc(pid:int, name:str, user:str, cpu_percent:float, memory_bytes:int)` | none |
| services | `ServicesResult` | `total`, `running`, `failed`, `failed_units: tuple[Unit, ...]` (≤50, sorted by unit); `Unit(unit, description)` | `services.failed` |
| logins | `LoginsResult` | `failed_24h`, `top_sources: tuple[Source, ...]` (≤5); `Source(address, count)` | `logins.failed_24h` |
| updates | `UpdatesResult` | `manager: Literal["apt","dnf"]`, `pending`, `security: int \| None`, `reboot_required: bool \| None`, `lists_refreshed_at: AwareDatetime \| None` | `updates.pending`; `updates.security` and `updates.reboot_required` (0/1) when not None |
| certificates | `CertificatesResult` | `certificates: tuple[Cert, ...]` (≤16); `Cert(port, subject, issuer, not_after: AwareDatetime, fingerprint_sha256)` | `cert.days_left` with instance `str(port)` for each, and instance `""` for the smallest; value `(not_after - now).total_seconds() / 86400`, rounded down; negative once expired |

### Fake server fixtures (R1)

`tools/fake-server/fixtures/docker_ps` (four lines, exactly):
```
{"Command":"\"/docker-entrypoint.sh nginx\"","CreatedAt":"2026-11-22 10:00:00 +0000 UTC","ID":"1111111111111111111111111111111111111111111111111111111111111111","Image":"nginx:1.27","Labels":"com.docker.compose.project=shop,com.docker.compose.service=web,com.docker.compose.project.config_files=/srv/shop/compose.yml,/srv/shop/compose.prod.yml","LocalVolumes":"0","Mounts":"","Names":"shop-web-1","Networks":"shop_default","Ports":"0.0.0.0:80->80/tcp","RunningFor":"3 days ago","Size":"0B","State":"running","Status":"Up 3 days (healthy)"}
{"Command":"\"docker-entrypoint.sh postgres\"","CreatedAt":"2026-11-22 10:00:00 +0000 UTC","ID":"2222222222222222222222222222222222222222222222222222222222222222","Image":"postgres:17","Labels":"com.docker.compose.project=shop,com.docker.compose.service=db","LocalVolumes":"1","Mounts":"shop_db","Names":"shop-db-1","Networks":"shop_default","Ports":"5432/tcp","RunningFor":"3 days ago","Size":"0B","State":"running","Status":"Up 3 days"}
{"Command":"\"/run.sh\"","CreatedAt":"2026-11-20 08:00:00 +0000 UTC","ID":"3333333333333333333333333333333333333333333333333333333333333333","Image":"grafana/grafana:11.3.0","Labels":"com.docker.compose.project=monitoring,com.docker.compose.service=grafana","LocalVolumes":"1","Mounts":"grafana","Names":"monitoring-grafana-1","Networks":"monitoring_default","Ports":"","RunningFor":"5 days ago","Size":"0B","State":"exited","Status":"Exited (0) 2 hours ago"}
{"Command":"\"sh -c 'exit 1'\"","CreatedAt":"2026-11-25 07:00:00 +0000 UTC","ID":"4444444444444444444444444444444444444444444444444444444444444444","Image":"busybox:1.37","Labels":"","LocalVolumes":"0","Mounts":"","Names":"hello-adhoc","Networks":"bridge","Ports":"","RunningFor":"1 hour ago","Size":"0B","State":"restarting","Status":"Restarting (1) 5 seconds ago"}
```
`tools/fake-server/fixtures/systemctl_list-units`:
```
cron.service loaded active running Regular background program processing daemon
ssh.service loaded active running OpenBSD Secure Shell server
nginx.service loaded failed failed A high performance web server and a reverse proxy server
systemd-tmpfiles-clean.service loaded inactive dead Cleanup of Temporary Directories
```

### fake-tool (R2), the whole new file
```sh
#!/bin/sh
# Stands in for docker, systemctl, journalctl, apt-get and dnf: logs its name and each argument in brackets to
# /var/log/fake-tools.log, then prints the fixture of the call and exits with its status. The fixture of a call is
# /etc/fake-tools/<tool>_<first argument> when that file exists, else /etc/fake-tools/<tool>; <fixture>.exit holds the
# exit status (0 without one). No fixture: nothing printed, status 0.
{ printf '%s' "${0##*/}"; printf ' [%s]' "$@"; printf '\n'; } >> /var/log/fake-tools.log
dir=/etc/fake-tools
tool=${0##*/}
name=$tool
case ${1-} in [A-Za-z0-9]*) case $1 in *[!A-Za-z0-9-]*) ;; *) [ -f "$dir/${tool}_$1" ] && name=${tool}_$1 ;; esac ;; esac
[ -f "$dir/$name" ] && cat "$dir/$name"
[ -f "$dir/$name.exit" ] && exit "$(cat "$dir/$name.exit")"
exit 0
```
The names the scripts use: `docker_ps`, `systemctl_list-units`, `journalctl`, `apt-get`, `dnf_check-update`, `dnf_updateinfo`.

### processes.sh (R4), the whole file
```sh
# MegooITAdmin's top-processes check (backend/app/collector/checks/processes.sh), sent on stdin to `sh -s`. It reads
# /proc/<pid>/stat twice, one second apart, and runs ps for the user, the resident memory and the name. Read-only.
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
LC_ALL=C
export PATH LC_ALL
command -v ps > /dev/null 2>&1 || { echo '{"status":"not_available"}'; exit 0; }
# pid and utime + stime: the name in parentheses may hold spaces, so the fields are counted after the last ") ".
TICKS='{ s = $0; sub(/^.*\) /, "", s); split(s, f, " "); print $1, f[12] + f[13] }'
first=$(cat /proc/[0-9]*/stat 2> /dev/null | awk "$TICKS")
sleep 1
hz=$(getconf CLK_TCK 2> /dev/null) || hz=100
echo '{"status":"ok"}'
printf '{"hz":%s}\n' "$hz"
{
  printf '%s\n' "$first" | sed 's/^/A /'
  cat /proc/[0-9]*/stat 2> /dev/null | awk "$TICKS" | sed 's/^/B /'
  timeout 10 ps -e -o pid=,user:32=,rss=,comm= | sed 's/^ */P /'
} | awk '
$1 == "A" { a[$2] = $3; next }
$1 == "B" { b[$2] = $3; next }
$1 == "P" && ($2 in b) { name = $0; sub(/^P +[0-9]+ +[^ ]+ +[0-9]+ /, "", name)
  printf "%s\t%s\t%d\t%s\t%s\n", $2, $3, b[$2] - (($2 in a) ? a[$2] : 0), $4, name }'
```
Body: `{"hz":N}`, then one line per process: `pid<TAB>user<TAB>ticks<TAB>rss_kB<TAB>name`. Parser: `cpu_percent = ticks / hz * 100`, `memory_bytes = rss_kB * 1024`. A bad row is skipped. Top 5 by CPU (ties: lower pid), top 5 by memory.

### logins.sh (R5), the core
```sh
command -v journalctl > /dev/null 2>&1 || { echo '{"status":"not_available"}'; exit 0; }
# The address is the word after the LAST " from ": the user name before it is the attacker's text.
COUNT='
function source(line,   rest, j) { rest = ""; while ((j = index(line, " from ")) > 0) { line = substr(line, j + 6); rest = line }; split(rest, w, " "); return w[1] }
/^Failed password for invalid user / { next }
/^Failed password for / || /^Invalid user / { n++; a = source($0); if (a != "") c[a]++ }
END { printf "total %d\n", n; for (a in c) printf "%d %s\n", c[a], a }'
counts=$(timeout 30 journalctl -q --no-pager -o cat --since=-24h -t sshd -t sshd-session 2> /dev/null | awk "$COUNT")
echo '{"status":"ok"}'
printf '%s\n' "$counts" | grep '^total '
printf '%s\n' "$counts" | grep -v '^total ' | sort -rn | head -n 20
```
Body: `total N`, then up to 20 lines `count address`. Parser: `failed_24h = N`; keeps the first 5 lines whose address passes `ipaddress.ip_address` (kept as `str(ip_address(...))`); the others are skipped. A missing `total` line raises `ValueError`.

### updates.sh (R6), the whole logic
```sh
if command -v apt-get > /dev/null 2>&1; then
  out=$(timeout 50 apt-get -s -o Debug::NoLocking=1 upgrade 2> /dev/null) || exit 1
  echo '{"status":"ok"}'
  echo 'manager apt'
  printf '%s\n' "$out" | awk '/^Inst / { n++; if (tolower($0) ~ /security/) s++ } END { printf "pending %d\nsecurity %d\n", n, s }'
  if [ -e /var/run/reboot-required ]; then echo 'reboot 1'; else echo 'reboot 0'; fi
  t=$(stat -c %Y /var/lib/apt/lists 2> /dev/null) && echo "refreshed $t"
elif command -v dnf > /dev/null 2>&1; then
  # -C: only what is cached. dnf never downloads here.
  out=$(timeout 50 dnf check-update -C -q 2> /dev/null); code=$?
  echo '{"status":"ok"}'
  echo 'manager dnf'
  echo "exit $code"
  printf '%s\n' "$out" | awk 'NF == 3 && $1 ~ /\./ { n++ } END { printf "pending %d\n", n }'
  sec=$(timeout 5 dnf updateinfo -C -q list --security 2> /dev/null) && printf '%s\n' "$sec" | awk 'NF >= 3 { n++ } END { printf "security %d\n", n }'
  t=$(stat -c %Y /var/cache/dnf 2> /dev/null) && echo "refreshed $t"
else
  echo '{"status":"not_available"}'
fi
```
Parser: `key value` lines. apt: `pending`, `security` and `reboot` are required. dnf: `exit 0` → pending 0; `exit 100` → the `pending` line; any other exit → `NotAvailable`; no `security` line → `security=None`; no `reboot` line → `None`. `refreshed` (epoch seconds) → `lists_refreshed_at` (UTC); a missing or non-integer value → None.

### certificates.sh (R7), the whole logic
```sh
set -f
command -v openssl > /dev/null 2>&1 || { echo '{"status":"not_available"}'; exit 0; }
name=${1-}
if [ -n "$name" ]; then sni="-servername $name"; else sni=-noservername; fi
echo '{"status":"ok"}'
for port in 443 465 636 853 993 995 5671 6443 8443 8883 9443; do
  cert=$(timeout 5 openssl s_client -connect "127.0.0.1:$port" $sni < /dev/null 2> /dev/null \
    | openssl x509 -noout -subject -issuer -enddate -fingerprint -sha256 -nameopt RFC2253 2> /dev/null) || continue
  [ -n "$cert" ] || continue
  echo "port $port"
  printf '%s\n' "$cert"
done
```
Body: blocks that start with `port N`, followed by `subject=…`, `issuer=…`, `notAfter=Nov 25 12:00:00 2027 GMT` and `sha256 Fingerprint=AB:…`. The keys are matched without regard to case; OpenSSL 1.1 prints `SHA256 Fingerprint=`. The date is read after `" ".join(v.split())` with `%b %d %H:%M:%S %Y GMT` as UTC. A block without one of the four fields, or with a bad subject or issuer, is dropped. The fingerprint is kept upper-case.

### Frontend texts (R8)

- Card titles: `Services`, `Updates`, `Failed sign-ins`, `Certificates`, `Top processes`, `Containers`. Tab labels: `Overview`, `Containers (N)` (just `Containers` before the list is read).
- State badges and texts (`STATE_TEXTS`):
  - `not_checked`: badge `Not checked yet`, text "The collector has not run this check yet."
  - `not_available`: badge `Not available`, with the text per kind (`NOT_AVAILABLE`):
    - containers: "Docker is not installed on this server."
    - processes: "ps is not installed on this server."
    - services: "systemd is not running on this server."
    - logins: "journalctl is not available on this server."
    - updates: "Neither apt nor dnf could answer from what this server has cached."
    - certificates: "openssl is not installed on this server."
  - `denied`: badge `Not allowed`, text "sudo refused megoo-ctl on this server. Run megoo-setup.sh on it again (Platform access card)."
  - `timeout`: badge `Could not be checked`, text "The check took too long."
  - `failed`: badge `Could not be checked`, text "The check failed or printed something unexpected."
- A failed run that has an older result: that result, then "Showing the result from {ago}."
- Footer: `Checked {ago} · {every}`. When the result is old (`isOld`), `Last checked {ago} · {every}` in `text-amber-ink`.
- `agoText`: under 60 s "just now"; then "1 minute ago" / "N minutes ago", "1 hour ago" / "N hours ago", "1 day ago" / "N days ago".
- `everyText`: 30 → "every 30 seconds", 60 → "every minute", 300 → "every 5 minutes", 3600 → "every hour", 21600 → "every 6 hours". The rule: whole hours → hours, whole minutes → minutes, else seconds; 1 gives the singular without a number.
- Services, when ok: "{running} running · {failed} failed · {total} in all". Failed units: unit name in `font-mono`, description, and a pink `Failed` badge. With none failed: "No failed services."
- Updates, when ok: "{pending} pending updates" ("Up to date" when 0); "{security} security updates" in amber when > 0; a `Restart required` amber badge when `reboot_required`; "Package lists refreshed {ago}" when `lists_refreshed_at` is set; a `dnf` result without security information leaves the security line out.
- Failed sign-ins, when ok: "{n} failed SSH sign-ins in the last 24 hours" ("No failed SSH sign-ins in the last 24 hours" when 0), then the top sources: address in `font-mono`, and "{count} attempts". Footnote: "Counts failed passwords and unknown accounts. Names that were tried are not kept."
- Certificates, when ok: one row per certificate: "Port {port}", subject, issuer, "Expires {formatTime(not_after)}", and a badge: `Expired` pink / `Expires in N days` pink (< 7 days) / amber (< 30 days) / `Valid` green. With none: "No certificate is served on the usual TLS ports." Footnote: "Checks what the server serves on ports 443, 465, 636, 853, 993, 995, 5671, 6443, 8443, 8883 and 9443, for its own host name. Only the default site of each port is seen."
- Top processes, when ok: two lists, "By CPU" and "By memory": name, user, PID (mono), "{cpu}% CPU" (one decimal), memory in MiB (one decimal). Without the right: "You need the View processes right in {group} to see processes."
- Containers summary: "{running} running · {not_running} not running", and a link `Show containers` to `?tab=containers`.
- Containers tab: one section per project (`h3` with the project name; the last one is "No Compose project"), each with a table: Name (mono), Service, Image (mono), State badge, Status, Last seen (`formatTime`). Empty after an ok run: "No containers on this server." The `denied` and `not_available` texts come from `STATE_TEXTS`.
- Tones (`TONE_CLASSES`): `pink: "border-pink text-pink-ink"`, `amber: "border-amber text-amber-ink"`, `green: "border-green text-green-ink"`, `muted: "text-muted-foreground"`. They go on `<Badge variant="outline">` and always come with a text.

## Steps

### 1. Fake server: fixtures for its stub tools, openssl, and a way to hide a tool
(see step detail)

### 2. SSH client: run_script runs a short script on a channel of its own
(see step detail)

### 3. Database: migration 0010 with server_checks and containers, their models and grants
(see step detail)

### 4. Collector: the check registry and reading a check's output
(see step detail)

### 5. Containers check: script and parser
### 6. Top processes check: script and parser
### 7. Services check: script and parser
### 8. Failed logins check: script and parser
### 9. Pending updates check: script and parser (apt, and dnf from its cache)
### 10. Certificates check: script and parser
### 11. Store: write a check's row and replace a server's containers
### 12. Collector: the Recorder writes an outcome and its metrics
### 13. Collector: the timetable and the check loop
### 14. Collector: every stream runs its checks beside the metrics loop
### 15. API: the checks and containers routes
### 16. Stack: the fake server's checks and containers through Caddy
### 17. Frontend: types and helpers for checks and containers
### 18. Frontend: the check card frame, and the Services and Updates cards
### 19. Frontend: the Failed sign-ins, Certificates and Top processes cards
### 20. Frontend: the Containers summary card and the Containers tab
### 21. Frontend: the server page gets real tabs and reads the checks
### 22. Docs: what the collector checks, and where it shows

Each step's full detail is in the `steps` list submitted with this plan (one subtask each). The shared contracts and references R1 to R8 above are the source for every name, format and text.

## Final verification

From `backend/`:
- `megoocolab-runner services run test -- uv run pytest`
- `megoocolab-runner services run image -- uv run pytest -m docker`
- `megoocolab-runner services run migrate -- sh -c 'uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head'`
- `megoocolab-runner services run stack -- uv run pytest -m stack` (it includes `test_the_collector_checks_the_fake_server_and_lists_its_containers`)

From the root: `make test-security`.

From `frontend/`: `npx tsc --noEmit`, `npx eslint src`, `npm test`, `megoocolab-runner services run web -- npm run test:image`.

Done when: after the Owner pins the fake server, `/api/servers/{id}/checks` returns six `ok` checks and `/api/servers/{id}/containers` returns `shop-db-1`, `shop-web-1`, `monitoring-grafana-1` and `hello-adhoc`, with projects `shop`, `monitoring` and none. The page shows the cards on Overview and the containers grouped under `monitoring`, `shop` and "No Compose project" on the Containers tab.
