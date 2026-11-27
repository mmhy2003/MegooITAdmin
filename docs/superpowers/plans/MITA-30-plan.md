# MITA-30 plan: live log streaming backend (journal, files, containers)

## Goal

People with View logs in a server's group follow its journal, its allowlisted files and its Docker containers live over `/api/ws/logs`. A new `logs` worker holds one SSH channel per source, however many people watch it, and sends each new viewer the last 200 lines first.

## Architecture

The shared package `backend/app/logs/` holds the pure rules (sources, allowlist patterns, line parsing, the cap, the Valkey protocol), the `log_file_allowlist` table with its API, and the socket `/api/ws/logs`. The worker `backend/app/logs/worker/` (`python -m app.logs.worker`, the backend image) listens on `logs:requests`, checks each request again in the database as `megooitadmin_logs`, and runs one `RunningSource` per source key on one shared SSH connection per server. It counts subscribers with `PUBSUB NUMSUB` and publishes lines on `logs:source:<key>`. Valkey carries pub/sub only. The last 200 lines live in the worker's memory.

## Conventions every step follows

- Work on the branch `megoo/MITA-30-p1-07-live-log-streaming-backend-journal`. Do not create another branch, and do not push.
- Write the test first and run it to watch it fail for the reason given. Then implement and run it again.
- Run backend commands from `backend/`: **BT `<paths>`** means `megoocolab-runner services run test -- uv run pytest <paths>`.
- Commits: `type(area): sentence`, a body that says why, and the last line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Commit only the files of the step. Never commit `.megoocolab/`, a plan or a design. No `docs/` files except `docs/server-setup.md` in the last step.
- `backend/tests/` has no `__init__.py`, so every test file basename must be unique. New log tests go in `backend/tests/logs/` and are named `test_log_*.py`. Shared helpers go in the new `backend/tests/logs_helpers.py`.
- Hand-format to 120 columns. Match the docstring and comment style of the files next to yours, such as `app/metrics/socket.py` and `app/collector/__main__.py`.
- A route that returns normally must `record()` one of its `audited(...)` actions. Call `record()` last in a transaction. A socket has no request transaction, so it uses `record_alone`.
- `client.py` stays the only module that imports asyncssh.
- Times and limits are parameters or module constants that tests patch, so every test runs in seconds.

## Clarifications of the design (no change of scope)

1. A source's `id` towards the browser is its key (`source_key`, 32 hex characters).
2. `subscribed` waits up to `OPEN_TIMEOUT` (5 s) for the worker's answers to the new sources, so that worker refusals appear in `denied`. A source without an answer is listed in `sources` and then gets `ended` with `worker_unavailable`.
3. When the 30-second recheck (in the socket or the worker) finds that a file's pattern was removed, the source ends with `not_allowed`, the same word as the denied reason.
4. Every `logs.stream_opened` gets a matching `logs.stream_closed`. A source the worker refuses closes at once, with the refusal as the reason and duration 0.
5. When `logs.stream_opened` cannot be recorded, nothing is asked of the worker and the socket closes with `1011`, as an audit failure answers 500 elsewhere.
6. `ended` with reason `exited` carries `"status": <exit status>`.
7. A file source runs `tail` behind a read check (`FILE_SCRIPT` below), so a missing or unreadable file ends with `not_readable` and does not wait for ever.

## File map

### Backend (`backend/`)

| File | New or changed | Responsibility |
|---|---|---|
| `app/logs/__init__.py` | new | empty |
| `app/logs/sources.py` | new | C1: source models, rules, `describe`, `source_key`, `command` |
| `app/logs/allowlist.py` | new | C2: pattern rules, `matches`, `STARTER_PATTERNS`, `patterns_of`, list, add and remove with events |
| `app/logs/lines.py` | new | C3: `Line`, `Splitter`, `parse`, `line_message` |
| `app/logs/cap.py` | new | C4: `Cap`, `Batcher` |
| `app/logs/protocol.py` | new | C5: channel names and messages |
| `app/logs/models.py` | new | `LogFileAllowlist` |
| `app/logs/schemas.py` | new | `PatternIn`, `PatternOut`, `AllowlistOut` |
| `app/logs/actions.py` | new | audit action names |
| `app/logs/router.py` | new | the three allowlist routes |
| `app/logs/socket.py` | new | C10: `WS /api/ws/logs` |
| `app/logs/worker/__init__.py` | new | empty |
| `app/logs/worker/links.py` | new | C7: `Links`, one shared connection per server |
| `app/logs/worker/source.py` | new | C8: `Limits`, `ended_by`, `RunningSource` |
| `app/logs/worker/hub.py` | new | C9: `Timings`, `Hub` |
| `app/logs/worker/__main__.py`, `health.py` | new | the process and its healthcheck |
| `app/ssh/client.py` | changed | C6: `FOLLOW_WRAPPER`, `Exit`, `Follower`, `follow()` |
| `app/core/config.py` | changed | C11: four settings |
| `app/core/db_roles.py` | changed | `LOGS_ROLE`, `sync_logs_role_password`, `main()` |
| `app/inventory/service.py` | changed | starter patterns on create; patterns in the created and deleted events |
| `app/models.py`, `app/main.py` | changed | register the model; include the two routers |
| `migrations/versions/0012_log_streams.py` | new | the role, the table, the starter rows, the grants |
| `docker-entrypoint.sh` | changed | step text; unset `DATABASE_LOGS_URL` |
| `tests/logs_helpers.py` | new | C12: `FakeWorker`, `viewers`, `text_line`, `add_pattern`, `log_file`, socket helpers |
| `tests/conftest.py` | changed | `DATABASE_LOGS_URL`, `upgrade_to_head`, the `logs_sessions` fixture |
| `tests/fake_server.py` | changed | `feed`, `append`, `followers` |
| `tests/logs/test_log_*.py` | new | the tests of every step |
| `tests/ssh/test_follow.py` | new | `follow()` against the fake server |
| `tests/security/test_db_privileges.py`, `test_socket_coverage.py`, `test_permission_coverage.py` | changed | the logs role, the socket, the routes |
| `tests/test_migrations.py`, `test_db_roles.py`, `test_settings.py`, `test_container.py`, `test_stack.py`, `test_makefile.py` | changed | as each step says |
| `tests/inventory/test_server_groups.py`, `test_group_delete.py` | changed | the group events now carry `log_file_allowlist` |

### Repository root

| File | Change |
|---|---|
| `tools/fake-server/fake-tool`, `Dockerfile` | the stubs follow with `-f` or `--follow` |
| `docker-compose.yml`, `docker-compose.build.yml` | the `logs` service, plus the backend's new variables |
| `tools/test-services/docker-compose.image.yml` | `DATABASE_LOGS_URL` |
| `megoocolab.toml` | `TEST_DATABASE_LOGS_URL`, `IMAGE_LOGS_DATABASE_URL`, `POSTGRES_LOGS_PASSWORD` |
| `Makefile`, `.env.example`, `tools/stacks/dev.env`, `tools/stacks/e2e.env` | `POSTGRES_LOGS_PASSWORD` |
| `README.md`, `docs/server-setup.md`, `AGENTS.md` | live logs, the service, the settings, what the worker runs |

## Contracts

### C1. `app/logs/sources.py`

```python
BACKLOG = 200
PRIORITIES = ("emerg", "alert", "crit", "err", "warning", "notice", "info", "debug")  # index = syslog number
Priority = Literal["emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"]
UNIT = re.compile(r"[A-Za-z0-9][A-Za-z0-9:_.@-]{0,254}")
PATH_CHARS = "A-Za-z0-9._/@%+=:,-"
PATH = re.compile(rf"/[{PATH_CHARS}]{{0,254}}")
CONTAINER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")        # megoo-ctl's own rule
JOURNAL_FIELDS = "MESSAGE,PRIORITY,_SYSTEMD_UNIT,SYSLOG_IDENTIFIER"
NOT_READABLE = 66
FILE_SCRIPT = 'test -f "$1" && test -r "$1" || exit 66; exec tail -n 200 -F -- "$1"'

def check_path(value: str) -> str:
    """ValueError unless PATH.fullmatch(value) and every segment after the first "/" is non-empty and not "." or ".."."""

class _Source(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    server_id: UUID

class JournalSource(_Source):
    kind: Literal["journal"]
    unit: str | None = None          # validator: UNIT.fullmatch
    priority: Priority | None = None
    this_boot: bool = False

class FileSource(_Source):
    kind: Literal["file"]
    path: str                        # validator: check_path

class ContainerSource(_Source):
    kind: Literal["container"]
    container_id: str                # validator: CONTAINER.fullmatch

Source = Annotated[JournalSource | FileSource | ContainerSource, Field(discriminator="kind")]
SOURCES: TypeAdapter[Source] = TypeAdapter(Source)

def describe(source) -> dict:   # source.model_dump(mode="json"): every field, defaults included
def source_key(source) -> str:  # sha256(json.dumps(describe(s), sort_keys=True, separators=(",", ":"))).hexdigest()[:32]
def command(source) -> list[str]:
    # journal:   ["journalctl", "--no-pager", "-f", "-o", "json", f"--output-fields={JOURNAL_FIELDS}", "-n", "200"]
    #            + ["-u", unit] if unit + ["-p", str(PRIORITIES.index(priority))] if priority + ["-b"] if this_boot
    # file:      ["sh", "-c", FILE_SCRIPT, "megoo-file", path]
    # container: ["sudo", "-n", CTL, "docker", "logs", container_id, "--follow", "--tail", "200"]  (CTL from app.ssh.client)
```

### C2. `app/logs/allowlist.py`

```python
MAX_PATTERNS = 50
STARTER_PATTERNS = ("/var/log/syslog", "/var/log/messages", "/var/log/nginx/*.log", "/var/log/apache2/*.log")
PATTERN = re.compile(rf"/[{PATH_CHARS}*?]{{0,254}}")

def check_pattern(value: str) -> str:
    """ValueError unless PATTERN matches, every segment is non-empty and not "." or "..", and the first segment
    holds no wildcard ("/*", "/v*r/log" are refused)."""

def matches(path: str, patterns: Iterable[str]) -> bool:
    """Whether the path matches one pattern. "*" is "[^/]*" and "?" is "[^/]"; every other character is itself
    (re.escape). The whole path must match."""

async def patterns_of(db: AsyncSession, group_ids: Iterable[UUID]) -> dict[UUID, list[str]]:
    """The patterns of each asked group, sorted; a group without any is absent."""

def starter_rows(group_id: UUID) -> list[LogFileAllowlist]

async def list_patterns(db, access: Access, group_id: UUID) -> AllowlistOut          # 404 not_found: no such group
async def add_pattern(db, request, user, group_id, body: PatternIn) -> PatternOut    # lock the group row FOR UPDATE, then count
async def remove_pattern(db, request, user, group_id, pattern_id) -> None            # 404 not_found: none in this group
```

Events: `auth_event(request, action, actor_of(user), mfa=True, target=Target(type="server_group", id=str(group.id), name=group.name), change={"pattern": {"before": None, "after": p}}, detail={"pattern_id": str(row.id)})` for added. Removed swaps before and after. `409 pattern_exists` comes from `flush_unique(db, "log_file_allowlist_server_group_id_pattern_key", "pattern_exists")`. `409 too_many_patterns` applies when the group already holds `MAX_PATTERNS`.

### C3. `app/logs/lines.py`

```python
MAX_LINE_BYTES = 8192
MAX_JOURNAL_BYTES = 65536   # a journal entry is JSON: its MESSAGE is cut to MAX_LINE_BYTES after parsing

@dataclass(frozen=True)
class Line:
    seq: int
    time: datetime
    text: str
    truncated: bool = False
    level: str | None = None   # journal: PRIORITIES[PRIORITY]
    unit: str | None = None    # journal: _SYSTEMD_UNIT

def line_message(line: Line) -> dict:
    # {"seq", "time": iso(time) (app.metrics.overview.iso), "text"}, + "level" and "unit" when not None,
    # + "truncated": True only when truncated

class Splitter:
    def __init__(self, max_bytes: int)
    def feed(self, chunk: bytes) -> list[tuple[bytes, bool]]
        # complete lines without b"\n" (one trailing b"\r" removed), each with "was cut": a line over max_bytes keeps
        # its first max_bytes and the rest up to its b"\n" is discarded. Never holds more than max_bytes.
    def rest(self) -> list[tuple[bytes, bool]]   # the unterminated last line, at the end of the output

def parse(kind: str, raw: bytes, *, seq: int, read_at: datetime, cut: bool = False) -> Line
    # text: the first MAX_LINE_BYTES bytes decoded with errors="replace"; truncated = cut or it was longer.
    # file: text = raw, time = read_at.
    # container: re.match(rb"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?(Z|[+-]\d\d:\d\d) ", raw): time from it (the
    #   fraction cut or padded to 6 digits, Z as +00:00), text = what follows. No match or a bad date: read_at, whole raw.
    # journal: json.loads; not a dict: as a file line. MESSAGE str, or a list of ints 0..255 (binary) taken as bytes, or
    #   missing/None as "". __REALTIME_TIMESTAMP (microseconds, a digit string) as UTC, else read_at. PRIORITY "0".."7"
    #   gives level. _SYSTEMD_UNIT when a str gives unit.
```

### C4. `app/logs/cap.py`

```python
class Cap:
    def __init__(self, per_second: int, clock: Callable[[], float] = time.monotonic)
    def admit(self) -> bool    # int(clock()) is the second; a new second resets the count. True while under per_second.

class Batcher:
    """A source's outgoing messages in order: batches of kept lines, and a skipped count at the place of each gap."""
    def __init__(self, max_lines: int = 500)
    def keep(self, message: dict) -> None   # a line_message; remembers its seq as the last kept seq
    def drop(self) -> None
    @property
    def full(self) -> bool                  # max_lines lines wait
    def take(self) -> list[dict]
        # In order: {"type":"lines","lines":[…]} and {"type":"skipped","count":n,"after_seq":s}, where s is the seq of
        # the last line kept before the gap (0 when none). A kept line after drops closes the batch, adds the skipped
        # message, then starts a new batch. take() also emits drops still pending. [] when nothing waits.
```

### C5. `app/logs/protocol.py`

```python
REQUESTS = "logs:requests"
WORKER = "logs:worker"
def viewer_channel(socket_id: str) -> str:   # f"logs:viewer:{socket_id}"
def source_channel(key: str) -> str:          # f"logs:source:{key}"
HEX32 = r"^[0-9a-f]{32}$"

class OpenRequest(BaseModel):  type: Literal["open"]; socket_id: str (pattern HEX32); request_id: str (HEX32); source: Source
class Opened(BaseModel):       type: Literal["opened"]; request_id: str; key: str; run_id: str; lines: list[dict]; last_seq: int
class Refused(BaseModel):      type: Literal["refused"]; request_id: str; key: str; reason: str
class Lines(BaseModel):        type: Literal["lines"]; lines: list[dict]
class Skipped(BaseModel):      type: Literal["skipped"]; count: int; after_seq: int
class Ended(BaseModel):        type: Literal["ended"]; reason: str; status: int | None = None
class Alive(BaseModel):        type: Literal["alive"]; run_id: str
TO_VIEWER = TypeAdapter(Annotated[Opened | Refused, Field(discriminator="type")])
ON_SOURCE = TypeAdapter(Annotated[Lines | Skipped | Ended, Field(discriminator="type")])
def encode(message: BaseModel) -> str:   # message.model_dump_json()
REFUSALS = frozenset({"not_found", "not_allowed", "not_an_ssh_server", "host_key_not_pinned", "host_key_changed",
                      "too_many_sources"})
```

### C6. `app/ssh/client.py` additions

```python
FOLLOW_ERRORS = 4096   # bytes of error output kept for the reason of an end
# $0 is megoo-follow, "$@" the command. The command gets no stdin. A background cat reads the channel's stdin: when the
# channel closes it gets EOF and ends the command, so nothing stays on the server, also for a quiet tail -F.
FOLLOW_WRAPPER = (
    'exec 3<&0; "$@" 3<&- < /dev/null & c=$!; '
    '{ cat <&3 > /dev/null 2>&1; kill -TERM "$c" 2> /dev/null; } > /dev/null 2>&1 & w=$!; '
    'wait "$c"; s=$?; kill "$w" 2> /dev/null; exit "$s"'
)

@dataclass(frozen=True)
class Exit:
    status: int | None   # None: no exit status (a signal, or a broken channel)
    errors: bytes        # the first FOLLOW_ERRORS bytes of its error output

class Follower:
    def __aiter__(self) -> AsyncIterator[tuple[Literal["out", "err"], bytes]]   # chunks of both streams until both end
    exit: Exit | None    # set when the iteration ended

@asynccontextmanager
async def follow(conn: Connection, argv: Sequence[str]) -> AsyncIterator[Follower]:
    """Runs argv under FOLLOW_WRAPPER on a channel of its own: `sh -c <wrapper> megoo-follow <argv…>`, each part
    shlex.quote'd. ValueError for an empty argv, more than 32 arguments, or an argument that is longer than 4096 or not
    printable. Leaving closes the channel. Raises SshError when the channel cannot start or breaks."""
```

The implementation reads `process.stdout` and `process.stderr` (`encoding=None`) in two tasks into one queue. Iteration ends when both reach EOF. Then it awaits `process.wait()` (bounded by `CLOSE_TIMEOUT`) and sets `exit`. On leaving, it calls `process.close()`, then `wait_closed()` within `CLOSE_TIMEOUT`, as `script_output` does.

### C7. `app/logs/worker/links.py`

```python
ACTOR = Actor.system("logs")
MAX_SIGN_INS = 20

class Links:
    def __init__(self, *, max_sign_ins: int = MAX_SIGN_INS)
    @asynccontextmanager
    async def use(self, server: Server) -> AsyncIterator[Connection]:
        """The server's one connection, opened by its first user through open_connection(server, actor=ACTOR,
        source=None), with at most max_sign_ins sign-ins at once, and closed when its last user leaves. A failed
        sign-in raises ConnectionRefused or an SshFailure to every waiting user, and the next use tries again."""
    def open_count(self) -> int   # connections open now
```

A holder task per server keeps `open_connection` entered (`AsyncExitStack`), sets a future with the connection and waits for an `asyncio.Event` that the last user sets. Users await `asyncio.shield(link.ready)`.

### C8. `app/logs/worker/source.py`

```python
@dataclass(frozen=True)
class Limits:
    max_lines_per_second: int = 2000
    backlog: int = BACKLOG
    sources_per_server: int = 8
    batch_every: float = 0.1
    batch_lines: int = 500

DIAGNOSTICS = (b"sudo: ", b"megoo-ctl: ")   # container error lines that are not the container's

def ended_by(kind: str, exit: client.Exit) -> tuple[str, int | None]:
    # status 127: ("not_available", None); file and status NOT_READABLE: ("not_readable", None);
    # container and a line of exit.errors starting with b"sudo: ": ("denied", None); else ("exited", exit.status)

class RunningSource:
    def __init__(self, key: str, source: Source, server: Server, *, links: Links, valkey: Valkey, limits: Limits,
                 clock: Callable[[], float] = time.monotonic)
    key: str; source: Source; server_id: UUID; zero_since: float | None = None
    def snapshot(self) -> tuple[list[dict], int]   # the last limits.backlog kept line messages, and the last seq (0)
    def start(self, on_end: Callable[["RunningSource"], None]) -> None
    async def stop(self) -> None                  # cancels and waits; publishes nothing
    async def end(self, reason: str) -> None      # publishes Ended(reason), then stop()
```

The task does `async with links.use(server) as conn, client.follow(conn, command(source)) as followed`. A reader feeds `Splitter(MAX_JOURNAL_BYTES if journal else MAX_LINE_BYTES)` per stream. Journal and file sources ignore `err` chunks. A container reads both streams and drops lines that start with `DIAGNOSTICS`. Each line goes `parse` → `Cap.admit()` → kept: seq += 1, `Batcher.keep`, append to `deque(maxlen=backlog)`; dropped: `Batcher.drop`. A flusher publishes `Batcher.take()` every `batch_every`, or at once when `full`, on `source_channel(key)` as `Lines`/`Skipped`. When the output ends: last flush, then `Ended(*ended_by(...))`. `ConnectionRefused` → `Ended(refused.detail)`. `SshFailure` → `Ended(failure.reason)`. Then `on_end(self)`.

### C9. `app/logs/worker/hub.py`

```python
@dataclass(frozen=True)
class Timings:
    count_every: float = 1.0
    close_after: float = 5.0
    alive_every: float = 5.0
    recheck_every: float = 30.0

class Hub:
    def __init__(self, sessions: async_sessionmaker, valkey: Valkey, *, limits: Limits = Limits(),
                 timings: Timings = Timings(), links: Links | None = None, run_id: str | None = None)
    run_id: str                         # uuid4().hex when not given
    running: dict[str, RunningSource]
    async def run(self, heartbeat: Path | None = None) -> None
        # one TaskGroup until cancelled: listener (logs:requests, one request at a time, in order), counter (every
        # count_every: PUBSUB NUMSUB of every running source's channel; touches heartbeat), alive (publishes
        # Alive(run_id) on WORKER at once and every alive_every), recheck (every recheck_every). ValkeyError propagates.
    async def handle(self, request: OpenRequest) -> Opened | Refused   # and publishes it on viewer_channel(socket_id)
    async def stop(self) -> None        # stops every running source
```

`handle` checks, in order: no server → `not_found`; `os != "linux"` → `not_an_ssh_server`; `host_key is None` → `host_key_not_pinned`; `host_key_changed_at` set → `host_key_changed`; file not `matches` the group's patterns → `not_allowed`; container without a `containers` row `(server_id, "docker", container_id)` → `not_found`. Then the key: if it is running, answer `Opened` with its snapshot. Otherwise, if the server already runs `sources_per_server` sources → `too_many_sources`; else start a new `RunningSource`, register it, and answer `Opened([], 0)`. Requests are handled one at a time, so two requests for one new source start one channel. Counter: 0 subscribers sets `zero_since`, and one held for `close_after` → `stop()` and remove; a subscriber clears it. Recheck: a server gone → `end("not_found")`; a file whose pattern is gone (also after a move to another group) → `end("not_allowed")`.

### C10. `app/logs/socket.py`

```python
router = APIRouter()
ROUTE = "WS /api/ws/logs"
MAX_SOURCES = 16
MAX_MESSAGE_BYTES = 16_384
QUEUE_LIMIT = 1000
RECHECK_EVERY = 30.0
OPEN_TIMEOUT = 5.0
ALIVE_TIMEOUT = 15.0
WATCH_EVERY = 0.5
SLOW_CLOSE = 1013
VALKEY_CLOSE = 1011
INVALID = {"type": "error", "detail": "invalid_message"}

def idle_after() -> float:   # get_settings().log_stream_idle_minutes * 60.0; tests patch it
class SubscribeIn(BaseModel): extra forbid; type: Literal["subscribe"]; sources: list[Source] = Field(max_length=MAX_SOURCES)
class ActiveIn(BaseModel):    extra forbid; type: Literal["active"]
CLIENT = TypeAdapter(Annotated[SubscribeIn | ActiveIn, Field(discriminator="type")])

@router.websocket("/ws/logs")
@signed_in_socket
async def logs_socket(websocket: WebSocket, signed: SocketSession) -> None: ...
```

Per socket: `socket_id = uuid4().hex`, `client = valkey_client()`, one pubsub subscribed at once to `viewer_channel(socket_id)` and `WORKER`, a bounded queue of `QUEUE_LIMIT`, an `asyncio.Lock`, `last_active`, `last_alive` (both now at open), `run_id = None`, `recorded: set[UUID]` (servers already given an `access.denied`), and `opens: dict[key, _Open]`. `_Open` holds key, source, server_id, server_name, group_id, opened_at (monotonic), request_id, state `"waiting"`/`"live"`, held messages, a reply future, and last_seq. Tasks in one TaskGroup, as in `metrics/socket.py`: reader, pump, sender, recheck, watch.

**Subscribe** (under the lock; also sets `last_active`):
1. `wanted = {source_key(s): s}`. Open keys not wanted are closed quietly: unsubscribe, `stream_closed` reason `left`, no `ended`.
2. New keys: one query for their servers (`id, server_group_id, name`), one `patterns_of` for the groups of file sources. Per source: no server or `not access.sees(group)` → denied `not_found` (`record_hidden` for an existing hidden server); `not access.allows(VIEW_LOGS, group)` → `forbidden`; file not `matches` → `not_allowed`. Each `access.denied` is recorded once per socket and server. Forbidden and not_allowed are recorded with `record_alone(Event(ACCESS_DENIED, actor_of(user), FAILURE, target=Target("server", id, name), context={"server_group_id"}, result_detail={"required": "view_logs" | "log_file_allowlist", "route": ROUTE} (+ "path"), source=source_of(websocket, auth_method="password", mfa=True)))`.
3. The accepted sources, grouped by server: one `logs.stream_opened` each with `record_alone`. Detail `{"sources": [describe…] sorted by key}`, target the server, context its group. A failure raises `_Closed(1011)`.
4. Each accepted source: `_Open` waiting; subscribe `source_channel(key)` and wait for Valkey's confirmation (`_Channels.subscribe`, which the pump confirms); publish `OpenRequest`. 0 receivers → unanswered at once.
5. `asyncio.wait(replies, timeout=OPEN_TIMEOUT)`. `Refused` → removed, unsubscribed, put in denied with its reason, and `stream_closed` with that reason and duration 0.
6. Enqueue `{"type":"subscribed","sources":[{"id":key,"source":describe(s)} for every open source, sorted by key],"denied":[{"source":describe(s),"reason":r}, in asked order]}`.
7. With no await in between, for each new `Opened` (by key): enqueue `{"type":"lines","source":key,"lines":opened.lines,"backlog":true}`, then the held messages translated with `last_seq = opened.last_seq`, then state `live`. `run_id` is set from the first `Opened`.
8. Unanswered sources: `_end(key, "worker_unavailable")`.

**Pump**: `get_message(ignore_subscribe_messages=False, timeout=1.0)`. A subscribe confirmation goes to `_Channels`. A viewer message (`TO_VIEWER`) resolves the `_Open` with that request_id. A worker message (`Alive`) sets `last_alive`; a known `run_id` that differs → `_end_all("worker_restarted")`; an unknown one is adopted. A source message (`ON_SOURCE`) for a waiting open is held: more than `QUEUE_LIMIT` held → `_Closed(1013)`. For a live open it is translated: `Lines` keeps the lines with `seq > last_seq`, raises `last_seq`, and enqueues `{"type":"lines","source":key,"lines":[…]}` when any is left. `Skipped` with `after_seq >= last_seq` → `{"type":"skipped","source":key,"count":n}`. `Ended` → `_end(key, reason, status)`. Bad JSON is skipped with a warning.

**`_end(key, reason, status=None)`**: remove, unsubscribe, enqueue `{"type":"ended","source":key,"reason":reason}` (+ `"status"` when not None), and record `stream_closed`.

**`stream_closed`**: one `record_alone` per server for the sources closing together. Target, context and source are as for opened. Detail `{"sources": [...], "duration_seconds": round(now - min(opened_at), 1), "reason": reason}`.

**Reader**: a message over 16 kB, or one `CLIENT` refuses → enqueue `INVALID`. `active` → `last_active = now`.

**Recheck**: every `RECHECK_EVERY`, `recheck(signed)`. None → `_Closed(4401)`, and the remaining sources close with `signed_out`. Otherwise, under the lock, reload the servers and patterns of the open sources. A source whose server is gone or hidden → `_end(key, "not_found")`; no View logs → `forbidden`; the file no longer matches → `not_allowed`.

**Watch**: every `WATCH_EVERY`, with sources open: `now - last_active >= idle_after()` → `_end_all("idle")`; `now - last_alive >= ALIVE_TIMEOUT` → `_end_all("worker_unavailable")`.

**Closing**: the remaining sources close with `signed_out` after 4401, and with `left` otherwise. `ValkeyError`/`OSError` → 1011, a full queue → 1013, as in `metrics/socket.py`.

### C11. Settings (`app/core/config.py`)

```python
database_logs_url: str | None = None                       # the entrypoint's password step only (DATABASE_LOGS_URL)
logs_heartbeat_file: str = "/tmp/megooitadmin-logs.heartbeat"
log_stream_max_lines_per_second: int = Field(default=2000, ge=1)   # the logs worker
log_stream_idle_minutes: int = Field(default=30, ge=1)              # the backend's socket
```

### C12. `tests/logs_helpers.py`

```python
NOW_TEXT = "2026-11-27T10:00:00Z"
def text_line(seq: int, text: str) -> dict:   # {"seq": seq, "time": NOW_TEXT, "text": text}
async def add_pattern(group_id: UUID, pattern: str) -> None   # inserts a log_file_allowlist row as the owner
def log_file(name: str) -> str:   # f"/var/log/nginx/{name}-{uuid4().hex[:8]}.log", a path the starter patterns cover
async def viewers(client: Valkey, key: str) -> int   # PUBSUB NUMSUB of source_channel(key)
async def receive(ws, timeout: float = 5) -> dict
async def receive_type(ws, kind: str, timeout: float = 5) -> dict   # skips other types
async def subscribe(ws, sources: list[dict]) -> dict   # sends a subscribe, returns the "subscribed" answer

class FakeWorker:
    """Stands in for the logs worker on Valkey: answers each open request, and publishes what a test tells it to."""
    def __init__(self, client: Valkey, *, run_id: str = "f" * 32, answer: bool = True)
    requests: list[OpenRequest]
    refusals: dict[str, str]                       # key -> reason
    backlogs: dict[str, tuple[list[dict], int]]    # key -> (lines, last_seq)
    async def __aenter__(self) -> "FakeWorker"     # subscribes REQUESTS, waits for the confirmation, starts its task
    async def __aexit__(self, *exc) -> None
    async def publish(self, key: str, message: BaseModel) -> None   # on source_channel(key)
    async def alive(self, run_id: str | None = None) -> None
```

## Steps

### 1. Log sources: models, rules, key and command

**Files:** create `backend/app/logs/__init__.py` (empty), `backend/app/logs/sources.py` (contract C1), `backend/tests/logs/test_log_sources.py`.

**Test first** (`tests/logs/test_log_sources.py`), with no database (plain functions):
- `test_a_journal_source_runs_journalctl_with_its_filters`: `command(JournalSource(kind="journal", server_id=S, unit="nginx.service", priority="warning", this_boot=True))` equals `["journalctl","--no-pager","-f","-o","json","--output-fields=MESSAGE,PRIORITY,_SYSTEMD_UNIT,SYSLOG_IDENTIFIER","-n","200","-u","nginx.service","-p","4","-b"]`. Without filters it stops after `"200"`.
- `test_a_file_source_runs_tail_behind_a_read_check`: `["sh","-c",FILE_SCRIPT,"megoo-file","/var/log/syslog"]`.
- `test_a_container_source_runs_megoo_ctl`: `["sudo","-n","/usr/local/sbin/megoo-ctl","docker","logs","web-1","--follow","--tail","200"]`.
- `test_refused_units` (parametrized): `""`, `"-x"`, `".hidden"`, `"a b"`, `"a;b"`, `"x"*256` → `ValidationError` through `SOURCES.validate_python`. `"getty@tty1.service"` and `"a:b_c.d-e"` are accepted.
- `test_refused_paths`: `"var/log/x"`, `"/var/../etc/shadow"`, `"/var/log/./x"`, `"/var//log"`, `"/var/log/"`, `"/var/log/*.log"`, `"/var/log/a b"`, `"/var/log/$(x)"`, `"/" + "a"*255`.
- `test_refused_containers`: `"-rm"`, `"a/b"`, `"a b"`, `"x"*129`.
- `test_an_unknown_kind_or_field_is_refused`: `{"kind":"podman",…}` and an extra field.
- `test_the_key_is_the_same_for_equal_sources_and_differs_with_a_filter`: the defaults given or omitted give the same key; `priority="warning"` gives another; the key is 32 lowercase hex characters.
- `test_describe_holds_every_field`.

**Run:** `BT tests/logs/test_log_sources.py`. It fails with `ModuleNotFoundError: app.logs`.

**Implement** C1 exactly. The validators raise `ValueError` with the field's name, for example `"not a unit"`.

**Run again:** same command. It passes.

**Commit:** `feat(logs): the three log sources, their rules and the command each one runs`.

### 2. Allowlist patterns: rules and matching

**Files:** create `backend/app/logs/allowlist.py` with only the pure part of C2 for now (`MAX_PATTERNS`, `STARTER_PATTERNS`, `PATTERN`, `check_pattern`, `matches`), and `backend/tests/logs/test_log_allowlist_rules.py`.

**Test first:**
- `test_a_wildcard_never_crosses_a_slash`: `matches("/var/log/nginx/access.log", ["/var/log/*.log"])` is False. With `["/var/log/nginx/*.log"]` it is True.
- `test_a_question_mark_matches_one_character`: `/var/log/app?.log` matches `/var/log/app1.log`, not `/var/log/app12.log` and not `/var/log/app/.log`.
- `test_other_characters_match_only_themselves`: `/var/log/a.log` does not match `/var/log/aXlog`; the pattern `/var/log/+x` matches only `/var/log/+x`.
- `test_the_whole_path_must_match`: `/var/log/syslog` does not match `/var/log/syslog.1`.
- `test_no_pattern_matches_nothing`: `matches(p, [])` is False.
- `test_refused_patterns` (parametrized): `"/*"`, `"/v*r/log"`, `"var/log"`, `"/var/../etc"`, `"/var//x"`, `"/var/log/"`, `"/var/log/[ab]"`, `"/"` + 255 characters. Each raises `ValueError`.
- `test_the_starter_patterns_are_valid`: `check_pattern` accepts all four.

**Run:** `BT tests/logs/test_log_allowlist_rules.py`. It fails on import.

**Implement:** build the regex as described in C2, with `re.escape` for every character except `*` and `?`. `check_pattern` reuses the segment rule of `check_path` (import it from `app.logs.sources`). Leave the database functions for step 5.

**Run again:** it passes.

**Commit:** `feat(logs): allowlist patterns whose wildcards stay inside one path segment`.

### 3. Log lines, the cap, the batcher and the Valkey protocol

**Files:** create `backend/app/logs/lines.py` (C3), `backend/app/logs/cap.py` (C4), `backend/app/logs/protocol.py` (C5), and the tests `backend/tests/logs/test_log_lines.py`, `test_log_cap.py`, `test_log_protocol.py`.

**Tests first:**
- lines: `test_the_splitter_keeps_lines_across_chunks` (b"a\nb" then b"c\n" gives a, bc); `test_a_crlf_ending_loses_its_cr`; `test_a_long_line_is_cut_and_its_rest_discarded` (Splitter(10) fed 25 bytes in 3 chunks, then b"\nnext\n": the first line is 10 bytes, cut=True, then "next"); `test_rest_gives_the_unterminated_line`; `test_a_journal_entry_gives_time_level_unit_and_text`; `test_a_binary_journal_message_becomes_text` (MESSAGE `[104,105,255]` gives "hi\ufffd"); `test_a_journal_entry_without_a_valid_time_uses_the_read_time`; `test_a_journal_line_that_is_not_json_is_kept_as_text`; `test_a_docker_timestamp_with_nanoseconds_gives_the_time` (`2026-11-27T10:00:00.123456789Z hello` gives 10:00:00.123456 UTC, text "hello"); `test_a_bad_docker_timestamp_keeps_the_whole_line_and_the_read_time`; `test_bad_utf8_is_replaced`; `test_a_text_over_8_kb_is_cut_and_marked`; `test_line_message_omits_empty_fields` (a file line has exactly seq, time, text).
- cap: a fake clock (`lambda: t[0]`). `test_the_cap_admits_per_second_and_resets_the_next_second`. `test_the_batcher_puts_skipped_at_the_place_of_the_gap`: keep 1, 2, drop, drop, keep 3, then take gives `[lines(1,2), skipped(count 2, after_seq 2), lines(3)]`. `test_take_emits_pending_drops`. `test_full_after_max_lines`. `test_take_is_empty_when_nothing_waits`.
- protocol: channel names; a round trip of each message through `encode` and its adapter; `OpenRequest` refuses a socket_id that is not 32 hex characters; `ON_SOURCE` refuses an unknown type.

**Run:** `BT tests/logs/test_log_lines.py tests/logs/test_log_cap.py tests/logs/test_log_protocol.py`. It fails on import.

**Implement** C3 to C5. `parse` takes `read_at` from its caller: no clock inside.

**Run again:** they pass.

**Commit:** `feat(logs): parsing log lines, the per-second cap and the Valkey messages`.

### 4. Migration 0012: the allowlist table, the logs role and its password

**Files:** `backend/migrations/versions/0012_log_streams.py`, `backend/app/logs/models.py`, `backend/app/models.py`, `backend/app/core/config.py` (`database_logs_url`), `backend/app/core/db_roles.py`, `backend/tests/conftest.py`, `megoocolab.toml`, `AGENTS.md` (Checks: the test set also sets `TEST_DATABASE_LOGS_URL`), and the tests `tests/test_migrations.py`, `tests/test_db_roles.py`, `tests/security/test_db_privileges.py`.

**Model** `LogFileAllowlist`, `__tablename__ = "log_file_allowlist"`: `id` Uuid (default uuid4), `server_group_id` Uuid, `pattern` Text, `created_at` timestamptz (server default now()). Constraints: `log_file_allowlist_pkey`; FK `log_file_allowlist_server_group_id_fkey` to `server_groups.id` ON DELETE CASCADE; `UniqueConstraint("server_group_id","pattern", name="log_file_allowlist_server_group_id_pattern_key")`; `CheckConstraint("char_length(pattern) BETWEEN 2 AND 255", name="log_file_allowlist_pattern_check")`.

**Migration** (hand-written like 0009 and 0011): create `megooitadmin_logs` NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS if missing, and the table. Insert the four starter patterns for every group: `INSERT … SELECT gen_random_uuid(), g.id, p.pattern FROM server_groups g CROSS JOIN (VALUES …) AS p(pattern)`. Grants: `GRANT SELECT, INSERT, DELETE ON log_file_allowlist TO megooitadmin_api`; for logs: `USAGE ON SCHEMA public`, `SELECT ON servers, containers, log_file_allowlist`, `UPDATE (host_key_changed_at, host_key_offered, host_key_offered_at) ON servers`, `INSERT ON audit_log`, `SELECT, UPDATE ON audit_chain_head`. Downgrade: drop the table, `DROP OWNED BY megooitadmin_logs`, `DROP ROLE megooitadmin_logs`.

**db_roles**: `LOGS_ROLE = "megooitadmin_logs"` and `sync_logs_role_password(settings=None) -> bool`, like the collector's. `main()` sets the API, then the collector, then logs. Unset: print `DATABASE_LOGS_URL is not set: megooitadmin_logs keeps no login, so the logs worker cannot sign in.` Update the module docstring.

**conftest**: `os.environ["DATABASE_LOGS_URL"] = _test_url("TEST_DATABASE_LOGS_URL")`; `upgrade_to_head` also calls `sync_logs_role_password()`. Add a `logs_sessions` fixture copied from `collector_sessions` on `DATABASE_LOGS_URL`; it also patches `app.inventory.connection.SessionLocal`.

**megoocolab.toml** `[services.test.env]`: `TEST_DATABASE_LOGS_URL = "postgresql+asyncpg://megooitadmin_logs:megooitadminlogs@localhost:${DB_PORT}/megooitadmin_test"`.

**Tests first:**
- privileges: `LOGS_ROLE`, `LOGS_GRANTS = {"servers": {SELECT}, "containers": {SELECT}, "log_file_allowlist": {SELECT}, "audit_log": {INSERT}, "audit_chain_head": {SELECT, UPDATE}}`, `LOGS_COLUMN_GRANTS` (the three columns, UPDATE), and `API_GRANTS["log_file_allowlist"] = {SELECT, INSERT, DELETE}`. Tests: the role is not a superuser and owns nothing; its table grants and column grants are the declared ones; `test_the_logs_role_cannot_write_metrics_or_read_users`.
- migrations: `test_0012_goes_down_and_up_again` (the role and the table are gone at 0011 and back at head; finish with `upgrade_to_head()`); `test_0012_gives_every_existing_group_the_starter_patterns` (at 0011 insert a group as the owner, upgrade, and find its four rows); `test_the_database_refuses_a_second_equal_pattern_in_a_group`. `test_the_models_match_the_migrations` must stay green.
- db_roles: `test_the_logs_role_gets_login_and_its_password`; the wrong user names the variable; `main` without the variable says so. Restore it in `restored_password`.

**Run:** `BT tests/test_migrations.py tests/test_db_roles.py tests/security/test_db_privileges.py`. It fails (no 0012, no role). Try the migration with `megoocolab-runner services run migrate -- sh -c 'uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head'`.

**Run again:** they pass. Then run the whole `BT` to check that nothing else broke.

**Commit:** `feat(logs): the per-group log file allowlist and the logs worker's database role`.

### 5. The allowlist API

**Files:** `backend/app/logs/schemas.py`, `backend/app/logs/actions.py`, the database part of `backend/app/logs/allowlist.py` (C2), `backend/app/logs/router.py`, `backend/app/main.py`, `backend/tests/logs_helpers.py` (`add_pattern` only for now), `backend/tests/logs/test_log_allowlist_api.py`, `backend/tests/security/test_permission_coverage.py`.

**Contracts:** `actions.py` holds `LOG_ALLOWLIST_PATTERN_ADDED = "log_allowlist.pattern_added"`, `LOG_ALLOWLIST_PATTERN_REMOVED = "log_allowlist.pattern_removed"`, `ALLOWLIST_ACTIONS`, `LOGS_STREAM_OPENED = "logs.stream_opened"`, `LOGS_STREAM_CLOSED = "logs.stream_closed"` and `STREAM_ACTIONS`. `schemas.py` holds `PatternIn(pattern: str)` (extra forbid; a validator calls `check_pattern`, so a bad pattern answers 422), `PatternOut(id, pattern, created_at)` and `AllowlistOut(can_manage: bool, patterns: list[PatternOut])`, sorted by pattern. `router = APIRouter(prefix="/server-groups/{group_id}/log-allowlist")`:
- `GET ""` with `dependencies=[Depends(require_group_visible())]`
- `POST ""` with `[Depends(require_group_admin()), audited(LOG_ALLOWLIST_PATTERN_ADDED)]` → `PatternOut`
- `DELETE "/{pattern_id}"` with status 204 and `[Depends(require_group_admin()), audited(LOG_ALLOWLIST_PATTERN_REMOVED)]`

The service locks the group row `FOR UPDATE`; no group → 404 `not_found`. Events follow C2.

**Tests first** (`api`, `clock`, `signed_in`, `make_group`, `add_grant`, `events` from `auth_helpers`):
- `test_a_member_lists_the_patterns_and_learns_they_cannot_manage` (an operator: `can_manage` False); the Owner: True.
- `test_an_admin_adds_a_pattern_and_it_is_recorded`: 200, the row exists, and one `log_allowlist.pattern_added` with target server_group, change and detail as in C2.
- `test_an_admin_removes_a_pattern_and_it_is_recorded`: 204, then 404 a second time.
- `test_a_pattern_of_another_group_is_not_found`.
- `test_an_invalid_pattern_is_422` (`/*`, `/var/log/../x`).
- `test_a_duplicate_is_409_pattern_exists`; `test_the_51st_pattern_is_409_too_many_patterns`.
- `test_an_unseen_group_is_404_and_a_non_admin_is_403`, with their `access.denied` events.
- permission coverage: `test_the_log_allowlist_routes_need_a_visible_group_or_an_admin` (GET: group, POST and DELETE: admin, through `access_requirement`).

**Run:** `BT tests/logs/test_log_allowlist_api.py tests/security`. It fails (404 routes).

**Implement**, and include the router in `create_app` after `inventory_router`.

**Run again:** it passes, and `tests/security` stays green (audit coverage sees `audited`).

**Commit:** `feat(logs): admins manage the log file allowlist of their groups`.

### 6. A new group gets the starter patterns, and its events carry them

**Files:** `backend/app/inventory/service.py`, `backend/tests/inventory/test_group_log_patterns.py`, and the existing `backend/tests/inventory/test_server_groups.py` and `test_group_delete.py`.

**Behaviour:** `create_group` adds `starter_rows(group.id)` after the group's flush. Its event's change becomes `changes({}, _fields(group) | {"log_file_allowlist": list(STARTER_PATTERNS)})`. `delete_group` reads the group's patterns (sorted) before deleting. Its event's change becomes `changes(_fields(group) | {"log_file_allowlist": patterns}, {})`. The key is always there, `[]` included. The rows go with the group (ON DELETE CASCADE). `update_group` is unchanged.

**Tests first** (`test_group_log_patterns.py`):
- `test_a_new_group_gets_the_four_starter_patterns` (via `POST /api/server-groups` as the Owner, then GET the allowlist).
- `test_the_created_event_carries_the_starter_patterns`.
- `test_the_deleted_event_carries_the_groups_patterns_and_the_rows_go` (add one with `add_pattern`, then delete).

Update `test_server_groups.py:125` and `test_group_delete.py:69` to expect the new `log_file_allowlist` field.

**Run:** `BT tests/inventory`. The new tests fail.

**Implement**, importing `STARTER_PATTERNS`, `starter_rows` and the patterns read from `app.logs.allowlist`. There is no cycle: allowlist imports only inventory models.

**Run again:** `BT tests/inventory tests/security` passes.

**Commit:** `feat(inventory): a new group starts with four log file patterns, and its events carry them`.

### 7. The fake server follows, and the SSH client follows a command

**Files:** `tools/fake-server/fake-tool`, `tools/fake-server/Dockerfile`, `backend/tests/fake_server.py`, `backend/app/ssh/client.py` (C6), `backend/tests/ssh/test_follow.py`.

**Stub:** after the fixture name is chosen, add a follow mode: `case " $* " in *' -f '*|*' --follow '*) follow=1;; esac`. With follow and no `<fixture>.exit`: `feed=/var/lib/fake-tools/follow/$name`; `size=$(stat -c %s "$feed")`; print the fixture; `exec tail -c +$((size + 1)) -F "$feed" 2> /dev/null`. With an `.exit` it prints and exits as now. The Dockerfile makes `/var/lib/fake-tools/follow` (0755) holding `journalctl` and `docker_logs`, mode 0666. Update the stub's header comment.

**FakeServer:** `feed(name, text)` appends to the follow file as root. `append(path, text)` creates the parent directories and appends, mode 0644, as root. `followers() -> int` is `pgrep -c -f 'megoo-follow|^tail .*-F'` in the container (exit 1 means 0).

**Tests first** (`test_follow.py`, with `client.connect(fake_server.host, fake_server.port, "megoo", fake_server.host_key())`):
- `test_follow_prints_the_fixture_then_what_is_fed`: fixture `journalctl` "a\n", `follow(conn, ["journalctl","-f"])`, read "a", `feed("journalctl","b\n")`, read "b".
- `test_leaving_ends_the_command_on_the_server`: a quiet `tail -F` of an empty file. After leaving, `followers()` reaches 0 within 5 s.
- `test_the_exit_status_and_the_error_output`: `["sh","-c","echo out; echo err >&2; exit 3"]` gives out chunks, err chunks, `exit == Exit(3, b"err\n")`.
- `test_a_missing_command_exits_127`.
- `test_arguments_reach_the_command_unchanged`: `["printf","%s\\n","a b'c\"$(x)"]`.
- `test_bad_arguments_are_refused`: `[]`, 33 arguments, `"a\nb"`.
- `test_a_container_follow_stops_through_sudo`: `["sudo","-n",CTL,"docker","logs","web-1","--follow","--tail","200"]` with fixture `docker_logs`, then leave and check `followers()` returns to 0 (TERM reaches the root process through sudo).

**Run:** `BT tests/ssh/test_follow.py tests/ssh/test_fake_server.py`. It fails (no `follow`). The runner rebuilds the fake server image from the changed Dockerfile.

**Implement** C6.

**Run again:** they pass, and `BT tests/collector` stays green (the stubs without follow are unchanged).

**Commit:** `feat(ssh): follow a command on a channel that ends it when the channel closes`.

### 8. Worker: one shared connection per server and a running source

**Files:** `backend/app/logs/worker/__init__.py`, `backend/app/logs/worker/links.py` (C7), `backend/app/logs/worker/source.py` (C8 without the end reasons beyond `exited`), `backend/tests/logs_helpers.py` (add `log_file`), `backend/tests/logs/test_log_running.py`.

**Test setup:** `pinned_server(fake_server, name)` from `collector_helpers`, `logs_sessions`, a Valkey client, and a pubsub on `source_channel(key)` that collects messages. Tests use `Limits(batch_every=0.05)`.

**Tests first:**
- `test_a_file_source_holds_the_last_200_lines_then_streams_new_ones`: append 250 lines to `log_file("run")`, start, eventually the snapshot is 200 lines ending in "line 250" with last seq 200. Append 3: a `Lines` message with seq 201 to 203.
- `test_a_journal_source_parses_the_stub_entries`: fixture `journalctl` with two JSON entries, then `feed`: the level, unit and time come from the entries.
- `test_a_container_source_takes_dockers_time`: fixture `docker_logs` `2026-11-27T10:00:00.5Z hi\n`.
- `test_two_sources_of_a_server_share_one_sign_in`: `sign_ins()` grows by 1, `links.open_count() == 1`; after both stop it is 0.
- `test_stopping_a_quiet_source_leaves_no_process`: `followers()` returns to 0 within 5 s.
- `test_a_container_that_stops_ends_with_exited`: fixture `docker_logs` with `exit=3` publishes `Ended(reason="exited", status=3)`, and `on_end` is called.

**Run:** `BT tests/logs/test_log_running.py`. It fails on import.

**Implement** C7 and C8: `Links`; `RunningSource` with the reader, the cap, the batcher, the ring, the flusher and the final `Ended`; and `ended_by` for `exited`.

**Run again:** they pass.

**Commit:** `feat(logs): the worker follows a source on a server connection it shares`.

### 9. Worker: every end reason, the cap and a changed host key

**Files:** `backend/app/logs/worker/source.py` (all of `ended_by`, and the refusals and failures in the task), `backend/tests/logs/test_log_running_ends.py`.

**Tests first:**
- `test_ended_by` (pure, parametrized): 127 gives not_available; file with 66 gives not_readable; container with `b"sudo: a password is required\n"` gives denied; otherwise exited with the status.
- `test_a_missing_journalctl_ends_with_not_available` (`fake_server.hidden("/usr/local/bin/journalctl")`).
- `test_a_file_megoo_cannot_read_ends_with_not_readable` (append, then `chmod 600`) and `test_a_missing_file_ends_with_not_readable`.
- `test_a_container_without_the_sudo_rule_ends_with_denied`: the server's username is `megoo-nosudo`, and the "sudo:" line is not published as a line.
- `test_an_unreachable_server_ends_with_unreachable`: port 1.
- `test_a_refused_key_ends_with_key_refused`: an account sshd refuses, such as `nobody`.
- `test_a_changed_host_key_flags_the_server_and_ends_the_source`: pin another key (from `ssh-keygen` in a temporary directory). The source ends `host_key_changed`, `host_key_changed_at` is set, and `server.host_key_mismatch` comes from the system actor `logs`. Use `logs_sessions`.
- `test_a_broken_channel_ends_with_ssh_error`: monkeypatch `client.follow` to raise `client.SshError`.
- `test_a_burst_over_the_cap_is_counted`: `Limits(max_lines_per_second=50)`, an empty file, 500 lines appended at once. Collect until `Lines` stops for 1 s: the kept lines plus the `Skipped` counts equal 500, the first `Skipped` comes right after the first 50 lines, and the seqs have no gap.
- `test_a_line_over_8_kb_is_cut`.

**Run:** `BT tests/logs/test_log_running_ends.py`. The new cases fail.

**Implement** the rest of `ended_by` and the `except` branches of C8.

**Run again:** they pass.

**Commit:** `feat(logs): a source tells why it ended, and a burst over the cap is counted`.

### 10. Worker: the hub

**Files:** `backend/app/logs/worker/hub.py` (C9), `backend/tests/logs/test_log_hub.py`.

**Test setup:** `Hub(logs_sessions, client, timings=Timings(count_every=0.1, close_after=0.5, alive_every=0.2, recheck_every=0.3))` run as a task. A test "viewer" subscribes to `viewer_channel(id)` and `source_channel(key)` before publishing an `OpenRequest` on `REQUESTS`. Groups come from `make_group` plus `add_pattern(group, "/var/log/nginx/*.log")`.

**Tests first:**
- `test_an_open_request_is_answered_opened`, then lines arrive on the source channel.
- `test_a_second_viewer_gets_the_held_lines_and_no_second_channel`: after lines were written, a second request (another socket id) gets `Opened` with those lines and their last seq; `len(hub.running) == 1`, `followers() == 1`, one more sign-in in all.
- `test_two_requests_at_once_start_one_source`: publish both, then wait for both answers.
- refusals (parametrized): missing server `not_found`; windows `not_an_ssh_server`; unpinned `host_key_not_pinned`; flagged `host_key_changed`; a path outside the allowlist `not_allowed`; an unknown container `not_found`.
- `test_the_ninth_source_of_a_server_is_refused` (`too_many_sources`; eight files of the pattern).
- `test_a_source_without_subscribers_closes_after_close_after` (unsubscribe: within 2 s `hub.running` is empty and `followers()` is 0).
- `test_alive_is_published_with_the_run_id`.
- `test_a_removed_pattern_ends_the_source_with_not_allowed` and `test_a_removed_server_ends_with_not_found` (by the recheck).
- `test_the_heartbeat_is_touched` (`tmp_path`).

**Run:** `BT tests/logs/test_log_hub.py`. It fails on import.

**Implement** C9. The listener uses `client.pubsub()`, subscribes to `REQUESTS`, and loops `get_message(ignore_subscribe_messages=True, timeout=1.0)`. A request that fails `OpenRequest` is skipped with a warning. `on_end` removes the source from `running`.

**Run again:** they pass.

**Commit:** `feat(logs): the worker's hub checks each request and shares a source between its viewers`.

### 11. The worker process, its healthcheck and its settings

**Files:** `backend/app/core/config.py` (`logs_heartbeat_file`, `log_stream_max_lines_per_second`), `backend/app/logs/worker/__main__.py`, `backend/app/logs/worker/health.py`, `backend/tests/logs/test_log_worker_main.py`, `backend/tests/test_settings.py`.

**`__main__.py`**: `async def serve(stop: asyncio.Event) -> None`. It does `valkey = valkey_client(settings)`; a missing `VALKEY_URL` raises `RuntimeError` and the process exits 1. Then `Hub(SessionLocal, valkey, limits=Limits(max_lines_per_second=settings.log_stream_max_lines_per_second))`, and `hub.run(Path(settings.logs_heartbeat_file))` as a task next to `stop.wait()`. On stop, or when the hub ends, it runs `hub.stop()` and `valkey.aclose()`, and re-raises what the hub raised, so `main()` exits 1 and Compose restarts it. `main()` mirrors `app/collector/__main__.py` (SIGTERM and SIGINT set stop; it logs "The logs worker started/stopped."). `health.py` mirrors `app/collector/health.py`, on `logs_heartbeat_file` with `MAX_AGE = 30.0`.

**Tests first:**
- `test_serve_publishes_alive_and_stops_on_the_event` (with `VALKEY_URL` from the test set and monkeypatched `SessionLocal` → `logs_sessions`).
- `test_serve_stops_every_source_on_stop`: open one file source through a request; after stop, `followers()` is 0.
- `test_a_valkey_failure_ends_serve_with_the_error`: `valkey_client` patched to an unreachable URL; `serve` raises `ValkeyError` or `OSError`.
- `test_health_is_healthy_only_with_a_fresh_heartbeat`.
- settings: `test_the_log_stream_settings_have_their_defaults` (2000, 30, the heartbeat path) and `test_the_cap_must_be_positive`.

**Run:** `BT tests/logs/test_log_worker_main.py tests/test_settings.py`. It fails.

**Implement.** Add `log_stream_idle_minutes` and `database_logs_url` now too if they are missing (C11).

**Run again:** it passes.

**Commit:** `feat(logs): the logs worker runs as its own process with a healthcheck`.

### 12. Socket: handshake, subscribe, rights, audit and the backlog

**Files:** `backend/app/logs/socket.py` (C10: reader, pump, sender, subscribe), `backend/app/main.py`, `backend/tests/logs_helpers.py` (`FakeWorker`, `text_line`, `viewers`, `receive`, `receive_type`, `subscribe`), `backend/tests/logs/test_log_socket.py`, `backend/tests/security/test_socket_coverage.py`.

**Test setup:** as `tests/metrics/test_socket.py`: `serving(create_app())`, `connect(base, "/api/ws/logs", cookie)`, `signed_in`. Sources are dicts like `{"kind":"file","server_id":…,"path":…}`.

**Tests first:**
- `test_no_cookie_closes_4401`; `test_a_foreign_origin_gets_403`.
- `test_subscribe_opens_a_source_and_sends_the_backlog_first`: the FakeWorker backlog has `[text_line(1,"a"), text_line(2,"b")]` with last seq 2. The answer is `subscribed` with the source's id, then `lines` with `backlog: true`. A published `Lines([line 3])` arrives without `backlog`.
- `test_lines_held_before_opened_are_sent_once_without_a_gap`: the FakeWorker publishes lines 2 to 4 before answering `Opened(lines 1..3, last_seq 3)`; the browser gets 1 to 3, then only 4.
- `test_skipped_is_forwarded`.
- denied: `test_a_server_the_person_does_not_see_is_not_found_and_recorded_once`; `test_without_view_logs_is_forbidden` (an operator with `view_logs=False`, and an Auditor); `test_a_path_outside_the_allowlist_is_not_allowed`. Each comes with `access.denied`, once per socket and server.
- `test_a_worker_refusal_is_denied_and_closed`: `refusals[key] = "too_many_sources"`. It is in `denied`, with a `logs.stream_closed` reason `too_many_sources`.
- `test_stream_opened_names_the_person_server_and_sources`.
- `test_an_invalid_message_gets_an_error_and_the_socket_stays_open`: bad JSON, 17 sources, over 16 kB, a bad unit.
- socket coverage: `SOCKETS["/api/ws/logs"] = "live log lines of the sources the person may read"`.

**Run:** `BT tests/logs/test_log_socket.py tests/security`. It fails (no route).

**Implement** C10's per-socket state, `_Channels`, reader, pump (for viewer and source messages), sender and subscribe steps 1 to 7, plus `_end` and `stream_closed`. Include `logs_socket_router` in `create_app`.

**Run again:** they pass.

**Commit:** `feat(logs): the logs socket opens sources a person may read, backlog first`.

### 13. Socket: replacing, ending, idle, the recheck and failures

**Files:** `backend/app/logs/socket.py` (recheck, watch for idle, closing), `backend/app/core/config.py` (`log_stream_idle_minutes` if step 11 did not add it), `backend/tests/logs/test_log_socket_close.py`.

**Tests first** (FakeWorker; patch `RECHECK_EVERY` to 0.2, `WATCH_EVERY` to 0.05, and `idle_after` to `lambda: 0.5`):
- `test_a_subscribe_replaces_the_set`: A open; subscribe A and B keeps A (no second backlog) and opens B; subscribe B closes A (`viewers(client, A)` reaches 0, closed reason `left`).
- `test_an_ended_source_is_told_and_closed`: `Ended("exited", 3)` → `{"type":"ended","source":key,"reason":"exited","status":3}`.
- `test_closing_the_socket_records_closed_with_duration_and_left`.
- `test_idle_ends_every_source_and_the_socket_stays_open`: then a new subscribe works.
- `test_active_resets_the_idle_timer`.
- `test_the_recheck_ends_a_source_after_a_lost_right` (`set_switch(grant, "view_logs", False)` → `forbidden`) and after a removed pattern (`not_allowed`).
- `test_an_ended_session_closes_4401_with_signed_out`.
- `test_a_browser_that_reads_too_slowly_is_closed_1013` and `test_valkey_unreachable_closes_1011` (as in the metrics tests).
- `test_the_idle_setting_defaults_to_30_minutes` in `tests/test_settings.py` if step 11 did not add it.

**Run:** `BT tests/logs/test_log_socket_close.py`. The new tests fail.

**Implement** the recheck, watch (idle part) and closing parts of C10.

**Run again:** they pass, and `BT tests/logs` stays green.

**Commit:** `feat(logs): a log stream ends when its viewer is idle, loses the right or leaves`.

### 14. Socket: a missing or restarted worker, and two admins on one channel

**Files:** `backend/app/logs/socket.py` (watch for alive, run id, unanswered opens), `backend/tests/logs/test_log_socket_worker.py`.

**Tests first:**
- `test_no_worker_ends_the_source_with_worker_unavailable` (no FakeWorker: 0 receivers).
- `test_a_worker_that_does_not_answer_ends_with_worker_unavailable` (`FakeWorker(answer=False)`, `OPEN_TIMEOUT` 0.3).
- `test_another_run_id_ends_every_source_with_worker_restarted`.
- `test_no_alive_ends_every_source_with_worker_unavailable` (`ALIVE_TIMEOUT` 0.5).
- **Done when**, `test_two_admins_watch_one_file_over_one_channel`: the real `Hub(logs_sessions, client, timings=fast)` as a task, `pinned_server`, two people with the admin role in its group (`signed_in` + `add_grant`), and `log_file("two")` with 5 lines. Both subscribe and get a backlog of 5. Append 3 lines: both receive the same 3 lines (equal seq and text). `len(hub.running) == 1`, `followers() == 1`, `sign_ins()` grew by 1. When both close, `hub.running` becomes empty within 2 s and `followers()` is 0.
- `test_the_cap_reaches_the_browser_as_skipped`: Hub with `Limits(max_lines_per_second=20)`; 200 lines appended; kept lines plus skipped counts equal 200.

**Run:** `BT tests/logs/test_log_socket_worker.py`. The new cases fail.

**Implement** the alive and run-id handling and the unanswered-open path of C10.

**Run again:** they pass. Run the whole `BT`.

**Commit:** `feat(logs): viewers learn when the logs worker is down or restarted`.

### 15. The logs service in Compose, the entrypoint and the password

**Files:** `docker-compose.yml`, `docker-compose.build.yml`, `backend/docker-entrypoint.sh`, `Makefile`, `.env.example`, `tools/stacks/dev.env`, `tools/stacks/e2e.env`, `tools/test-services/docker-compose.image.yml`, `megoocolab.toml`, `backend/tests/test_makefile.py`, `backend/tests/test_container.py`, `backend/tests/test_stack.py`.

**Compose:** the `logs` service, after `collector`. It uses the backend image, `entrypoint: ["python", "-m", "app.logs.worker"]`, `DATABASE_URL: postgresql+asyncpg://megooitadmin_logs:${POSTGRES_LOGS_PASSWORD:?POSTGRES_LOGS_PASSWORD is not set. Run make up or see .env.example}@db:5432/megooitadmin`, `VALKEY_URL`, and `LOG_STREAM_MAX_LINES_PER_SECOND: ${LOG_STREAM_MAX_LINES_PER_SECOND:-2000}`. It mounts `ssh_key` read-only, sits on networks `[core, servers]`, depends on a healthy backend and valkey, and its healthcheck is `["CMD","python","-m","app.logs.worker.health"]`. A comment says: run one, a second one would open every source twice. The backend gets `DATABASE_LOGS_URL` (with the same `:?` message) and `LOG_STREAM_IDLE_MINUTES: ${LOG_STREAM_IDLE_MINUTES:-30}`. The build overlay adds `logs` like `collector` (`pull_policy: never`). The entrypoint says "Setting the passwords of the API, collector and logs roles..." and unsets `DATABASE_LOGS_URL` too.

**Password:** in the Makefile `.env` rule, a fifth random value. A new file is written `POSTGRES_PASSWORD, POSTGRES_API_PASSWORD, POSTGRES_COLLECTOR_PASSWORD, POSTGRES_LOGS_PASSWORD, AUTH_SECRET_KEY`, and the hex check covers 192 characters. An older file gets `POSTGRES_LOGS_PASSWORD` appended after the collector's step, with `Added POSTGRES_LOGS_PASSWORD to .env: the logs worker reads servers as the restricted role megooitadmin_logs.` Update the rule's comment, `.env.example` (the password, and the commented `#LOG_STREAM_MAX_LINES_PER_SECOND=2000` and `#LOG_STREAM_IDLE_MINUTES=30`), and both stack env files (`POSTGRES_LOGS_PASSWORD=megooitadminlogs`). In `megoocolab.toml`: `[services.stack.env] POSTGRES_LOGS_PASSWORD = "megooitadminlogs"`, `[services.image.env] IMAGE_LOGS_DATABASE_URL = "postgresql+asyncpg://megooitadmin_logs:megooitadminlogs@localhost:${DB_PORT}/megooitadmin"`, and `DATABASE_LOGS_URL` in `docker-compose.image.yml`.

**Tests first:**
- makefile: add `LOGS_LINE`; every existing expectation gains it; `test_the_env_rule_adds_only_the_logs_password_to_an_env_without_it`; the complete env includes it; four distinct passwords.
- container: `test_the_logs_role_logs_in_and_is_not_a_superuser`; the backend holds neither `DATABASE_COLLECTOR_URL` nor `DATABASE_LOGS_URL`; `test_the_image_runs_the_logs_worker`: `_run_once({"DATABASE_URL": _url("megooitadmin_logs:megooitadminlogs")}, "--entrypoint", "python", …)` with `-m app.logs.worker` and no `VALKEY_URL` exits non-zero with "VALKEY_URL is not set".
- stack: add `"logs": {"core","servers"}` to `NETWORKS`; `test_the_stack_has_exactly_its_seven_services`; the ssh key mount includes logs read-only; the overlay builds `{"backend","frontend","collector","logs"}`; `test_the_logs_worker_runs_the_backends_image_as_its_own_role`; `test_the_backend_sets_the_logs_password_and_does_not_hold_it`; `_resolves` knows `logs`, with cases `("logs","db",True)`, `("logs","valkey",True)` and `("frontend","logs",False)`; the backend's environment has `LOG_STREAM_IDLE_MINUTES`.

**Run:** `BT tests/test_makefile.py`, `megoocolab-runner services run image -- uv run pytest -m docker`, and `megoocolab-runner services run stack -- uv run pytest -m stack`. The new tests fail.

**Implement**, then run the three commands again. They pass.

**Commit:** `feat(compose): the logs worker runs as its own service and database role`.

### 16. Stack: two sockets through Caddy share one follower

**Files:** `backend/tests/test_stack.py`.

**Test first**, `test_two_sockets_through_caddy_share_one_follower_of_a_file(owner)`, modelled on `test_ten_servers_stream_live_through_caddy`. Authorize the key on the fake server, create a group through the API (it gets the starter patterns), and register and pin `fake-server`. Write `/var/log/nginx/stack-<hex>.log` with 3 lines through `_compose_with_fake_server("exec","-T","fake-server","sh","-c",…)`. Open two sockets to `/api/ws/logs` with the owner's cookie and the stack's Origin, and subscribe both to the file source. Each gets `subscribed` (no denied) and a `lines` backlog of 3. Append 2 lines: both sockets receive them, with the same seqs. `pgrep -c -f '^tail .*-F'` in the fake server is 1 while both are open. After both close it is 0 within 30 s (the 5-second grace, then the channel closes).

**Run:** `megoocolab-runner services run stack -- uv run pytest -m stack -k two_sockets`. It fails only if something of steps 12 to 15 is wrong in the real stack. Fix the cause, not the test.

**Run again:** the whole `megoocolab-runner services run stack -- uv run pytest -m stack` passes.

**Commit:** `test(stack): two viewers through Caddy share one log follower on the fake server`.

### 17. Docs and the full check run

**Files:** `README.md`, `docs/server-setup.md`, `AGENTS.md`.

- `README.md`: a `### Live logs` section after `### Alerts`. It covers who may watch (View logs; Auditors never), the three sources and their filters, the allowlist (four starter patterns, Admins change it, wildcards stay inside one segment), the last 200 lines first, the cap with skipped counts, the 30-minute idle rule, that nothing is stored, and the audit events. The settings `LOG_STREAM_MAX_LINES_PER_SECOND` and `LOG_STREAM_IDLE_MINUTES`. Under Upgrade: `make upgrade` adds `POSTGRES_LOGS_PASSWORD` and starts the `logs` service, so nobody has to act. Run one `logs` service.
- `docs/server-setup.md`: `## What the logs worker runs`, after "What the collector runs". It lists the three commands exactly as in C1 under the `sh -c` wrapper named `megoo-follow`, which ends each command when its channel closes. The journal needs `systemd-journal` and systemd 236 or later (`--output-fields`), files need `adm` or a readable file, and containers use `megoo-ctl docker logs`, which stays at version 1. At most 8 sources per server on one connection (sshd's `MaxSessions` 10). With `MaxSessions 1`, a second source ends with "ssh_error". To see them: `ps -u megoo -o pid,args`.
- `AGENTS.md`: the test set sets `TEST_DATABASE_LOGS_URL` too, if step 4 did not already say it.

**Run** every check of Final verification.

**Commit:** `docs: live logs, the logs worker and what it runs on a server`.

## Final verification

From `backend/`:

- `megoocolab-runner services run test -- uv run pytest` (includes `test_two_admins_watch_one_file_over_one_channel`, the cap and idle tests)
- `megoocolab-runner services run image -- uv run pytest -m docker`
- `megoocolab-runner services run stack -- uv run pytest -m stack` (includes `test_two_sockets_through_caddy_share_one_follower_of_a_file`)
- `megoocolab-runner services run migrate -- sh -c 'uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head'`

From the repository root:

- `make test-security`

The frontend does not change, so its checks are not needed.
