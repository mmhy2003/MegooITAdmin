# MITA-28 plan: live dashboard and server performance charts

**Goal.** The Dashboard shows every server the person sees with live CPU, memory, disk, load and network over one WebSocket, as cards or a table. A Linux server's page gets a live strip on Overview and a Performance tab with live and historical charts, from 15 minutes back to 1 year.

**Architecture.** The backend gets a pure range table and an overview summarizer (`app/metrics/ranges.py`, `overview.py`), two history reads in `app/metrics/store.py`, two REST routes (`app/metrics/router.py`) and one WebSocket route `/api/ws/metrics` (`app/metrics/socket.py`). The socket's handshake lives in `app/auth/socket.py` and its live feed comes from a new `Subscription` in `app/metrics/fanout.py`, which can change its servers while it is read. The frontend keeps all pure logic in `src/lib/metrics.ts`, the socket client in `src/lib/live-socket.ts`, and the React side in two hooks. Charts use Recharts through shadcn's `chart` component and load only with the Performance tab.

Conventions this plan follows: tests come first. Backend tests run with `megoocolab-runner services run test -- uv run pytest …` from `backend/`. Frontend checks are `npx tsc --noEmit`, `npx eslint <changed files>` and `npx vitest run <file>` from `frontend/`. Lines are hand-formatted to 120 columns, with no Prettier and no linter on the backend. Commit subjects are `type(area): sentence` and end with the attribution line. There is no migration: the API role already reads `metrics`, `metrics_1m` and `metrics_1h`.

## File map

### Backend (`backend/`)

| File | New/Changed | Responsibility |
|---|---|---|
| `app/metrics/ranges.py` | new | `Range`, `RANGES`, `RangeName`, `METRIC_NAMES`, `MAX_METRICS = 16` |
| `app/metrics/overview.py` | new | `Disk`, `Overview`, `OVERVIEW_METRICS`, `summarize(sample)`, `overview_message(o)`, `iso(dt)` |
| `app/metrics/store.py` | changed | `Series`, `read_series(...)`, `Trend`, `ServerOverview`, `read_overview(...)` |
| `app/access/servers.py` | new | `split_visible(db, access, ids)`, `record_hidden(connection, user, route, hidden)` |
| `app/metrics/schemas.py` | new | Pydantic answers of the two REST routes |
| `app/metrics/router.py` | new | `GET /api/servers/{server_id}/metrics`, `GET /api/metrics/overview` |
| `app/metrics/fanout.py` | changed | `Subscription` |
| `app/auth/socket.py` | new | `SocketSession`, `same_origin`, `open_socket`, `recheck`, `signed_in_socket`, `NOT_SIGNED_IN_CLOSE = 4401` |
| `app/audit/http.py` | changed | `source_of` takes a Starlette `HTTPConnection`, so a `WebSocket` works too |
| `app/metrics/socket.py` | new | the `/ws/metrics` route and its tasks |
| `app/main.py` | changed | includes `metrics.router.router` and `metrics.socket.router` |
| `pyproject.toml`, `uv.lock` | changed | `websockets` in the dev group (`uv add --dev websockets`) |
| `tests/metrics/test_ranges.py`, `test_overview.py`, `test_series.py`, `test_overview_read.py`, `test_metric_routes.py`, `test_subscription.py`, `test_socket.py` | new | tests |
| `tests/access/test_split_visible.py` | new | tests |
| `tests/socket_helpers.py` | new | `serving(app)` runs Uvicorn in-process on a free port; `connect(...)`, `close_code(ws)` |
| `tests/security/test_socket_coverage.py` | new | `SOCKETS` pin list, every socket uses the shared handshake |
| `tests/security/routes.py` | changed | `unknown_routes(app, sockets={})` and `socket_routes(app)` |
| `tests/security/test_audit_coverage.py`, `test_permission_coverage.py` | changed | pass `SOCKETS`; pin the overview route |
| `tests/test_stack.py` | changed | the placeholder socket test becomes the ten-server live check |

### Repository root

| File | Change |
|---|---|
| `tools/fake-server/sshd_config` | `MaxStartups 50:30:100`, so ten-plus servers on one fake sshd can sign in at once |
| `AGENTS.md`, `Makefile` (help text of `test-security`) | name the socket-coverage suite |
| `README.md` | Dashboard, Performance tab, the idle rule, proxy requirements |

### Frontend (`frontend/src/`)

| File | New/Changed | Responsibility |
|---|---|---|
| `lib/metrics.ts` | new | types, ranges, formatters, `toneOf`, `fleetOrder`, `fleetCounts`, trend buffer, `mergeOverview`, `appendSample`, `sumSeries`, `chartRows`, `lastValue` |
| `lib/live-socket.ts` | new | `LiveSocket` class |
| `hooks/use-live-metrics.ts`, `hooks/use-on-screen.ts` | new | React side of the socket; IntersectionObserver |
| `hooks/use-refresh.ts` | changed | optional third argument `everyMs` |
| `__tests__/helpers/fake-websocket.ts`, `__tests__/helpers/intersection-observer.ts` | new | test doubles |
| `components/metrics/{sparkline,meter,percent-value,live-badge,server-vitals}.tsx` | new | small SVG pieces |
| `components/dashboard/{dashboard-page,fleet-summary,server-card,server-rows,view-switch}.tsx` | new | the Dashboard |
| `app/(app)/page.tsx` | changed | renders `DashboardPage` inside `Suspense` |
| `lib/servers.ts` | changed | `addressOf(page, filters, params?)` |
| `components/ui/chart.tsx` | new | `npx shadcn add chart` (adds `recharts` to package.json) |
| `app/globals.css`, `app/__tests__/themeTokens.test.ts` | changed | `--chart-3` |
| `components/servers/performance/{metric-chart,metric-card,use-series,range-picker,cpu-card,memory-card,load-card,network-card,disk-io-card,filesystems-card,performance-tab,live-strip}.tsx/.ts` | new | the Performance tab and the strip |
| `components/servers/server-page.tsx` | changed | the Performance tab, `?tab=performance&range=…`, the live strip |

## Contracts (shared by several steps)

### B1. `app/metrics/ranges.py`

```python
RangeName = Literal["live", "1h", "6h", "24h", "7d", "30d", "1y"]
Source = Literal["raw", "1m", "1h"]

@dataclass(frozen=True)
class Range:
    name: RangeName
    window: timedelta
    source: Source
    step: timedelta | None  # None: every sample (live)

RANGES: dict[str, Range] = {
    "live": Range("live", timedelta(minutes=15), "raw", None),
    "1h": Range("1h", timedelta(hours=1), "raw", timedelta(seconds=10)),
    "6h": Range("6h", timedelta(hours=6), "1m", timedelta(minutes=1)),
    "24h": Range("24h", timedelta(hours=24), "1m", timedelta(minutes=5)),
    "7d": Range("7d", timedelta(days=7), "1m", timedelta(minutes=30)),
    "30d": Range("30d", timedelta(days=30), "1h", timedelta(hours=2)),
    "1y": Range("1y", timedelta(days=365), "1h", timedelta(days=1)),
}
MAX_METRICS = 16
# Every metric the collector writes (app/collector/compute.py).
METRIC_NAMES = frozenset({
    "load.1m", "load.5m", "load.15m", "mem.total_bytes", "mem.available_bytes", "mem.used_bytes", "mem.used_percent",
    "swap.total_bytes", "swap.used_bytes", "disk.total_bytes", "disk.used_bytes", "disk.used_percent",
    "disk.inodes_used_percent", "cpu.used_percent", "cpu.user_percent", "cpu.system_percent", "cpu.iowait_percent",
    "cpu.steal_percent", "net.rx_bytes_per_sec", "net.tx_bytes_per_sec", "diskio.read_bytes_per_sec",
    "diskio.write_bytes_per_sec", "diskio.busy_percent",
})
MetricName = Literal[...same 23 names...]  # for the Query parameter; a test asserts set(get_args(MetricName)) == METRIC_NAMES
```

### B2. `app/metrics/overview.py`

```python
OVERVIEW_METRICS = ("cpu.used_percent", "mem.used_percent", "load.1m", "disk.used_percent",
                    "net.rx_bytes_per_sec", "net.tx_bytes_per_sec")

@dataclass(frozen=True)
class Disk:
    mount: str
    percent: float

@dataclass(frozen=True)
class Overview:
    server_id: uuid.UUID
    time: datetime | None
    cpu: float | None    # cpu.used_percent, instance ""
    mem: float | None    # mem.used_percent
    load: float | None   # load.1m
    disk: Disk | None    # highest disk.used_percent; a tie goes to the mount that sorts first
    rx: float | None     # sum of net.rx_bytes_per_sec over instances; None when the sample has none
    tx: float | None

def summarize(sample: Sample) -> Overview: ...
def iso(value: datetime) -> str:  # UTC, "Z", as fanout.encode writes it
def overview_message(o: Overview) -> dict:
    # {"type": "overview", "server_id": str, "time": iso|None, "cpu", "mem", "load",
    #  "disk": {"mount", "percent"} | None, "rx", "tx"}
```

### B3. `app/metrics/store.py` additions

```python
@dataclass(frozen=True)
class Series:
    metric: str
    instance: str
    time: list[datetime]
    avg: list[float]
    min: list[float | None]
    max: list[float | None]

async def read_series(session, server_id, metrics: Sequence[str], range_: Range, *, now: datetime) -> list[Series]:
    """Every instance of each metric with now - window <= time < now, sorted by (metric, instance), oldest first.
    A step without samples is left out."""

TREND_SLOTS = 60
TREND_STEP = timedelta(seconds=5)
OVERVIEW_WINDOW = timedelta(minutes=5)

@dataclass(frozen=True)
class Trend:
    start: datetime               # the first slot: time_bucket(5 s, now) - 59 * 5 s
    cpu: list[float | None]       # 60 averages of cpu.used_percent ""
    mem: list[float | None]       # 60 averages of mem.used_percent

@dataclass(frozen=True)
class ServerOverview:
    overview: Overview            # time None when no sample in the last 5 minutes
    trend: Trend

async def read_overview(session, server_ids: Sequence[uuid.UUID], *, now: datetime) -> dict[uuid.UUID, ServerOverview]:
    """One entry per asked id, also for one without samples."""
```

SQL shapes (SQLAlchemy Core, `func.time_bucket(<timedelta>, column)`; asyncpg sends a timedelta as an interval):

- `live`: `SELECT metric, instance, time, value FROM metrics WHERE server_id=:id AND metric IN :m AND time >= :start AND time < :now ORDER BY metric, instance, time`. Here avg is value and min/max are None.
- `raw` with a step: `time_bucket(step, time) AS t, avg(value), min(value), max(value) … GROUP BY metric, instance, t ORDER BY metric, instance, t`.
- `1m` and `1h`: on the rollup table `c = metrics_1m.c` / `metrics_1h.c`: `time_bucket(step, c.bucket) AS t, sum(c.avg_value * c.samples) / sum(c.samples), min(c.min_value), max(c.max_value) … WHERE c.bucket >= :start AND c.bucket < :now`. The average is weighted by sample counts. 1-day and 2-hour buckets use time_bucket's default origin, so they are cut at midnight UTC.
- Overview newest values: `SELECT DISTINCT ON (server_id, metric, instance) server_id, metric, instance, time, value FROM metrics WHERE server_id IN :ids AND metric IN OVERVIEW_METRICS AND time >= now - 5 min AND time < now ORDER BY server_id, metric, instance, time DESC`. Per server, build `Sample(time=max(time), server_id, readings=…)` and `summarize` it.
- Trend: `SELECT server_id, metric, time_bucket(5 s, time) AS slot, avg(value) … WHERE instance = '' AND metric IN ('cpu.used_percent','mem.used_percent') AND time >= start AND time < start + 300 s GROUP BY 1,2,3`. Slot index = `(slot - start) // 5 s`.

### B4. `app/access/servers.py`

```python
async def split_visible(db, access: Access, server_ids: Iterable[UUID]) -> tuple[frozenset[UUID], dict[UUID, UUID]]:
    """(the asked servers the person sees, {existing asked server they do not see: its group}). One query.
    An id that is in neither does not exist."""

async def record_hidden(connection: HTTPConnection, user: User, route: str, hidden: Iterable[UUID]) -> None:
    """One access.denied event (record_alone) for these servers:
    actor_of(user), Result.FAILURE, target None,
    result_detail {"required": "group", "route": route, "server_ids": sorted(str(id))},
    source source_of(connection, auth_method="password", mfa=True)."""
```

### B5. REST answers (`app/metrics/schemas.py`)

```python
class SeriesOut(BaseModel): metric: str; instance: str; time: list[datetime]; avg: list[float]; min: list[float | None]; max: list[float | None]
class SeriesAnswer(BaseModel): range: RangeName; step_seconds: int | None; start: datetime; end: datetime; series: list[SeriesOut]
class DiskOut(BaseModel): mount: str; percent: float
class TrendOut(BaseModel): start: datetime; cpu: list[float | None]; mem: list[float | None]
class ServerOverviewOut(BaseModel):
    server_id: UUID; time: datetime | None; cpu: float | None; mem: float | None; load: float | None
    disk: DiskOut | None; rx: float | None; tx: float | None; trend: TrendOut
class OverviewAnswer(BaseModel): servers: list[ServerOverviewOut]; denied: list[UUID]
```

Routes:

- `GET /servers/{server_id}/metrics`, with `dependencies=[Depends(require_group_visible(group=group_of_server))]`. Parameters: `range_: Annotated[RangeName, Query(alias="range")]` and `metric: Annotated[list[MetricName], Query(min_length=1, max_length=MAX_METRICS)]`. `now = datetime.now(UTC)`, `start = now - window`, and `step_seconds = None` for live.
- `GET /metrics/overview`, with `server_id: Annotated[list[UUID], Query(min_length=1, max_length=200)]`, `user: CurrentUser`, `access: CurrentAccess`. It calls `split_visible` and records hidden servers with `record_hidden(request, user, "GET /api/metrics/overview", hidden)` when there are any. `denied` is the sorted list of hidden plus missing servers. `servers` follows the asked order, visible ones only.

### B6. `Subscription` (`app/metrics/fanout.py`)

```python
class Subscription:
    """Samples of a set of servers that can change while it is read. One pubsub connection; leaving closes it."""
    def __init__(self, client: Valkey) -> None
    async def __aenter__(self) -> "Subscription"   # opens client.pubsub(); pings Valkey so an unreachable one raises here
    async def __aexit__(self, *exc) -> None        # aclose the pubsub
    @property
    def servers(self) -> frozenset[uuid.UUID]
    async def replace(self, server_ids: Iterable[uuid.UUID]) -> None   # subscribe the new channels, unsubscribe the gone ones
    def __aiter__(self) -> AsyncIterator[Sample]
        # loop: message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0); None -> continue
        # (also when nothing is subscribed yet); decode like _samples (skip with a warning);
        # drop a sample whose server is no longer in self.servers (in flight before an unsubscribe)
```

### B7. `app/auth/socket.py`

```python
NOT_SIGNED_IN_CLOSE = 4401

@dataclass(frozen=True)
class SocketSession:
    token: str
    session_id: UUID
    user: User
    access: Access

def same_origin(websocket: WebSocket) -> bool:
    """No Origin (not a browser): True. Otherwise urlsplit(origin).netloc.lower() == Host header lower. "null" is foreign."""

async def open_socket(websocket: WebSocket) -> SocketSession | None:
    # foreign Origin: await websocket.close(code=1008) before accept -> Uvicorn answers HTTP 403; return None
    # async with SessionLocal() as db: lookup_session(db, cookie, touch=False); await db.commit()  (an expired row is deleted)
    #   none, expired or stage != "active": accept, close(4401), return None
    #   access = await load_access(db, session.user)
    # accept; return SocketSession(...)
    # The socket never touches last_seen_at.

async def recheck(signed: SocketSession) -> SocketSession | None:
    """A fresh SessionLocal: lookup_session(touch=False), commit; None when the session ended or is no longer active,
    else a SocketSession with freshly loaded user and access."""

def signed_in_socket(handler: Callable[[WebSocket, SocketSession], Awaitable[None]]):
    async def endpoint(websocket: WebSocket) -> None:
        signed = await open_socket(websocket)
        if signed is not None:
            await handler(websocket, signed)
    endpoint.__name__ = handler.__name__
    endpoint.__doc__ = handler.__doc__
    endpoint.socket_handshake = open_socket   # read by tests/security/test_socket_coverage.py
    return endpoint
```

Do not use `functools.wraps`, because FastAPI would read the handler's two-parameter signature through `__wrapped__`.

### B8. `app/metrics/socket.py`

```python
router = APIRouter()
ROUTE = "WS /api/ws/metrics"
MAX_SERVERS = 200
MAX_MESSAGE_BYTES = 16_384
QUEUE_LIMIT = 1000
RECHECK_EVERY = 30.0
SLOW_CLOSE = 1013
VALKEY_CLOSE = 1011

class SubscribeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["subscribe"]
    view: Literal["overview", "full"]
    server_ids: list[uuid.UUID] = Field(max_length=MAX_SERVERS)

async def _send(websocket: WebSocket, message: dict) -> None:   # tests patch it
    await websocket.send_json(message)

@router.websocket("/ws/metrics")
@signed_in_socket
async def metrics_socket(websocket: WebSocket, signed: SocketSession) -> None: ...
```

Per socket: `client = valkey_client()`, `async with Subscription(client)` (a `ValkeyError`/`OSError` on enter closes with 1011), and `queue = asyncio.Queue(QUEUE_LIMIT)` read from the module variable at open time. The work runs in one `asyncio.TaskGroup`; when any task ends, the others are cancelled, then the socket closes and `client.aclose()` runs.

1. **reader**: `receive_text()`. A message over `MAX_MESSAGE_BYTES` bytes (UTF-8) or one that fails `SubscribeIn.model_validate_json` sends `{"type":"error","detail":"invalid_message"}` and the socket stays open. On a valid message: open a short `SessionLocal` session and call `split_visible`. The first time hidden servers appear on this socket, call `record_hidden(websocket, signed.user, ROUTE, hidden)`, and never again on this socket. Then `await subscription.replace(visible)`, set the current view, and enqueue `{"type":"subscribed","server_ids":sorted visible str,"denied":sorted(hidden ∪ missing) str}`. `WebSocketDisconnect` ends the task.
2. **pump** (Valkey → queue): `async for sample in subscription`. Build `overview_message(summarize(sample))` or `{"type":"sample","server_id","time":iso,"readings":[[m,i,v],…]}` for the current view, then `queue.put_nowait`. `asyncio.QueueFull` closes with 1013. A `ValkeyError` closes with 1011.
3. **sender** (queue → browser): `await _send(websocket, await queue.get())`.
4. **recheck**: `await asyncio.sleep(RECHECK_EVERY)`, then `recheck(signed)`. None closes with 4401. Otherwise `split_visible(new access, subscription.servers)`. When servers dropped out, call `replace(remaining)` and enqueue `{"type":"subscribed","server_ids":remaining,"denied":dropped}`.

The "three tasks" of the design are reader, Valkey-to-browser (pump plus sender, joined by the bounded queue) and recheck.

### F1. `src/lib/metrics.ts` (types and functions)

```ts
export const RANGES = ["live", "1h", "6h", "24h", "7d", "30d", "1y"] as const;
export type RangeName = (typeof RANGES)[number];
export const RANGE_LABELS: Record<RangeName, string> = { live: "Live", "1h": "1 hour", "6h": "6 hours", "24h": "24 hours", "7d": "7 days", "30d": "30 days", "1y": "1 year" };
export const AMBER_FROM = 80; export const PINK_FROM = 90;
export const LIVE_WINDOW_MS = 15 * 60_000; export const HISTORY_REFRESH_MS = 60_000;
export const TREND_SLOTS = 60; export const TREND_STEP_MS = 5_000; export const STALE_AFTER_MS = 5 * 60_000;
export type Tone = "normal" | "amber" | "pink";
export type Disk = { mount: string; percent: number };
export type Overview = { server_id: string; time: string | null; cpu: number | null; mem: number | null; load: number | null; disk: Disk | null; rx: number | null; tx: number | null };
export type Trend = { start: number; cpu: (number | null)[]; mem: (number | null)[] };   // start: ms of slot 0
export type ServerOverviewRead = Overview & { trend: { start: string; cpu: (number | null)[]; mem: (number | null)[] } };
export type OverviewRead = { servers: ServerOverviewRead[]; denied: string[] };
export type Vitals = { overview: Overview; trend: Trend };
export type Reading = [metric: string, instance: string, value: number];
export type OverviewMessage = Overview & { type: "overview"; time: string };
export type SampleMessage = { type: "sample"; server_id: string; time: string; readings: Reading[] };
export type SubscribedMessage = { type: "subscribed"; server_ids: string[]; denied: string[] };
export type ErrorMessage = { type: "error"; detail: string };
export type LiveMessage = OverviewMessage | SampleMessage | SubscribedMessage | ErrorMessage;
export type Series = { metric: string; instance: string; time: string[]; avg: number[]; min: (number | null)[]; max: (number | null)[] };
export type SeriesAnswer = { range: RangeName; step_seconds: number | null; start: string; end: string; series: Series[] };
export type ChartLine = { key: string; label: string; color: string; series: Series; band: boolean };
export type ChartRow = { t: number } & Record<string, number | null | [number, number] >;

export function rangeFrom(params: URLSearchParams): RangeName           // unknown or missing -> "live"
export function formatPercent(v: number | null): string                  // null "—"; Math.round -> "42%"
export function formatBytes(v: number | null): string                    // binary: "0 B", "512 B", "1.5 KiB", "16 GiB"; one decimal under 10, none from 10
export function formatRate(v: number | null): string                     // formatBytes + "/s"
export function formatLoad(v: number | null): string                     // two decimals, "—"
export function toneOf(percent: number | null): Tone                     // >= 90 pink, >= 80 amber
export function fleetOrder<T extends { name: string; monitoring: Monitoring | null }>(servers: T[]): T[]  // unreachable, reachable, other; localeCompare by name
export function fleetCounts(servers: Server[]): { total: number; reachable: number; unreachable: number; notMonitored: number; notChecked: number }
export function emptyTrend(endMs: number): Trend
export function trendOf(read: ServerOverviewRead["trend"]): Trend
export function pushTrend(trend: Trend, timeMs: number, cpu: number | null, mem: number | null): Trend  // moves the window so timeMs's slot is the last; a null keeps the slot's value
export function vitalsOf(read: ServerOverviewRead): Vitals
export function mergeOverview(previous: Overview | null, next: Overview): Overview  // each null field of next keeps previous; time = next.time ?? previous.time
export function applyMessage(previous: Vitals | undefined, message: OverviewMessage): Vitals
export function isStale(time: string | null, nowMs: number): boolean   // null or older than STALE_AFTER_MS
export function appendSample(series: Series[], sample: SampleMessage, metrics: string[], windowMs: number): Series[]  // live: append avg, min/max null; new instances start a series; drop points older than sample time - windowMs; keep (metric, instance) order
export function sumSeries(series: Series[], metric: string, instance: string): Series  // sum avg per timestamp present in any; min/max null
export function chartRows(lines: ChartLine[], stepMs: number): ChartRow[]  // union of times, sorted; row[key] = avg, row[`${key}_band`] = [min,max] when band and both non-null; when two consecutive times are more than 3 * stepMs apart, a row with every key null is inserted between them (the break)
export function lastValue(series: Series | undefined): number | null
export function seriesOf(answer: SeriesAnswer | null, metric: string, instance = ""): Series | undefined
export function instancesOf(answer: SeriesAnswer | null, metric: string): string[]  // sorted, "" left out
```

### F2. `LiveSocket` (`src/lib/live-socket.ts`)

```ts
export type LiveView = "overview" | "full";
export type LiveStatus = "connecting" | "live" | "reconnecting" | "paused";
export const BACKOFF_MS = [1000, 2000, 4000, 8000, 16000, 30000];
export const NOT_SIGNED_IN_CLOSE = 4401;
export type LiveSocketOptions = { onMessage: (m: LiveMessage) => void; onStatus: (s: LiveStatus) => void; onOpen: () => void };
export function socketUrl(location: Pick<Location, "protocol" | "host">): string  // "wss://host/api/ws/metrics" under https, else ws://
export class LiveSocket {
  constructor(options: LiveSocketOptions)
  subscribe(view: LiveView, serverIds: string[]): void   // remembered; sent now when open, and after every (re)open; sorted ids; identical repeat not sent
  close(): void                                          // final: no reconnect, listeners removed
}
```

- `connect()` runs on construction when `document.visibilityState === "visible"`, otherwise the status is `paused`. On open the attempt counter resets, the status becomes `live`, the socket sends the remembered subscription and calls `onOpen()` (the caller refills from REST).
- On close with 4401 the status becomes `paused` with no reconnect, and `goTo("/login?next=" + encodeURIComponent(pathname + search))` from `@/lib/auth/navigate`.
- On any other close that was not asked for: the status becomes `reconnecting` and it retries after `BACKOFF_MS[min(attempt, 5)]`.
- When the tab turns hidden: close the socket on purpose, clear the timer and set `paused`. When it turns visible: connect again.
- Messages are parsed with JSON.parse. A message that does not parse is ignored.

### F3. Hooks

```ts
// hooks/use-live-metrics.ts
export function useLiveMetrics(options: { view: LiveView; serverIds: string[]; onMessage: (m: LiveMessage) => void; onOpen: () => void; enabled?: boolean }): LiveStatus
// hooks/use-on-screen.ts — one IntersectionObserver, rootMargin "200px"
export function useOnScreen(): { track: (id: string) => (element: Element | null) => void; onScreen: string[] }  // sorted ids; without IntersectionObserver every tracked id counts
// hooks/use-refresh.ts
export function useRefresh(refresh: () => void, active: boolean, everyMs: number = REFRESH_EVERY_MS): void
```

### F4. Chart colours

`--chart-3` is the theme's violet: light `#6d28d9`, dark `#c084fc`. It is added to both blocks and to `@theme inline` as `--color-chart-3: var(--chart-3)`. Chart lines use `var(--chart-1)`, `var(--chart-2)` and `var(--chart-3)` in this fixed order. Text never takes a series colour.

## Steps

### 1. Backend: the range table, the metric names and the overview summary

See the step detail.

### 2. Backend: read_series reads every range from raw samples and rollups

### 3. Backend: read_overview gives the newest values and a 60-slot trend

### 4. Backend: split_visible and record_hidden

### 5. Backend: the two REST routes

### 6. Backend: Subscription changes its servers while it is read

### 7. Backend: the shared socket handshake and the socket-coverage suite

### 8. Backend: /api/ws/metrics subscribes, streams and denies

### 9. Backend: the recheck, the slow-browser limit and an unreachable Valkey

### 10. Stack: ten servers stream live through Caddy

### 11. Frontend: metrics library (formatters, tones, order, counts, ranges)

### 12. Frontend: metrics library (trend buffer, merging, live append, sums, chart rows)

### 13. Frontend: the LiveSocket client

### 14. Frontend: useLiveMetrics, useOnScreen and the refresh interval

### 15. Frontend: Sparkline, Meter, PercentValue, LiveBadge and ServerVitals

### 16. Frontend: the Dashboard's pieces (address, summary, switch, card, table rows)

### 17. Frontend: the live Dashboard page

### 18. Frontend: shadcn chart, --chart-3 and MetricChart

### 19. Frontend: useSeries, MetricCard and the CPU, Memory and Load cards

### 20. Frontend: the Network, Disk I/O and Filesystems cards

### 21. Frontend: the Performance tab on the server page

### 22. Frontend: the live strip on Overview

### 23. Docs and the full check run

(Each step's full text is in its `detail`: files, failing tests, commands, implementation and commit.)

## Final verification

From `backend/`:

- `megoocolab-runner services run test -- uv run pytest`
- `megoocolab-runner services run image -- uv run pytest -m docker`
- `megoocolab-runner services run stack -- uv run pytest -m stack` (includes `test_ten_servers_stream_live_through_caddy`)

From the repository root:

- `make test-security` (now with the socket-coverage suite)

From `frontend/`:

- `npx tsc --noEmit`
- `npx eslint src`
- `npm test` (includes `dashboard-page.test.tsx` "updates each of ten servers from socket messages without a reload")
- `megoocolab-runner services run web -- npm run test:image`

Manually on `make up STACK=dev` (optional): open `/` with the fake server registered and watch the values move. On a server page, open Performance, try every range, switch the theme, hide the tab and come back.
