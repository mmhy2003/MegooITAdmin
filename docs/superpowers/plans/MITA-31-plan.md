# MITA-31 plan: live log viewer, saved views and the allowlist editor

## Goal

People with View logs follow journals, allowlisted files and containers in the browser, on the Logs page and on a server's Logs tab. They filter, pause, merge and download what they follow, and save it as a private or shared view. The Owner and a group's Admins edit the group's log file patterns in a dialog.

## Architecture

Pure logic lives in `frontend/src/lib/logs/`: the address codec, ANSI, levels, the filter, merge, download, the allowlist port, the views API, the `LogSocket` client of `/api/ws/logs` and the `LogStore`, which holds rows outside React and notifies at most once a frame. React components in `frontend/src/components/logs/` draw it with `@tanstack/react-virtual`: `LogViewer` owns one socket and one store and is used by the Logs page and by the server's Logs tab. The backend adds `can_view_logs` to servers, plus a `log_views` table with four audited routes. The socket protocol does not change.

## Conventions every step follows

- Work on the branch `megoo/MITA-31-p1-08-live-log-viewer-ui-and-saved-views`. Do not create another branch, and do not push.
- Test first: write the test, run it, and watch it fail for the reason given. Then implement and run it again.
- **BT `<paths>`** means, from `backend/`: `megoocolab-runner services run test -- uv run pytest <paths>`.
- **FT `<paths>`** means, from `frontend/`: `npx vitest run <paths>`. Every frontend step also runs `npx tsc --noEmit` and `npx eslint <changed files>`.
- Commits: `type(area): sentence`, then a body that says why, then the last line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Commit only the step's files. Never commit `.megoocolab/`, the plan or the design, and add no `docs/` files.
- Backend: hand-format to 120 columns. Match the docstring style of `app/logs/allowlist.py` and `app/alerts/service.py`. Call `record()` last in a route's transaction. `backend/tests/` has no `__init__.py`, so new test basenames must be unique: name them `test_log_view*.py`.
- Frontend: client components start with `"use client"`. Mock the API with `vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }))` and `vi.mock("@/lib/auth/navigate")`, as `components/settings/__tests__/groups-page.test.tsx` does. Unit tests go in `src/lib/logs/__tests__/`, component tests in `src/components/logs/__tests__/`.
- Colours exist only in `src/app/globals.css`, as theme tokens. Components use classes. Nothing touches `localStorage`, `sessionStorage` or `document.cookie` (`src/__tests__/storage.test.ts`).
- User-facing text follows the house style: plain sentences, sentence case.

## Contracts

### C1. Backend: the saved-view shapes (`backend/app/logs/schemas.py`)

```python
LevelGroup = Literal["error", "warning", "info", "debug", "none"]
LEVEL_GROUPS: tuple[str, ...] = ("error", "warning", "info", "debug", "none")
MAX_VIEW_SOURCES = 16
MAX_VIEW_NAME = 80
MAX_FILTER = 200

class ContainerViewSource(ContainerSource):          # app.logs.sources.ContainerSource
    name: str | None = None                           # the container's name; CONTAINER.fullmatch or 422
class ViewSettings(BaseModel):                         # extra="forbid"
    q: str = Field("", max_length=MAX_FILTER)
    regex: bool = False                                # the regex is not compiled here: the browser's engine differs
    levels: list[LevelGroup] = list(LEVEL_GROUPS)      # deduplicated and put in LEVEL_GROUPS order by a validator
    layout: Literal["side_by_side", "merged"] = "side_by_side"
    wrap: bool = False
    utc: bool = False
ViewSource = Annotated[JournalSource | FileSource | ContainerViewSource, Field(discriminator="kind")]
class LogViewIn(BaseModel):                            # extra="forbid"
    name: str          # stripped; 1..80 characters after the strip, else 422
    shared: bool = False
    sources: list[ViewSource] = Field(min_length=1, max_length=MAX_VIEW_SOURCES)
    settings: ViewSettings = ViewSettings()
class LogViewOut(BaseModel):
    id: UUID; name: str; shared: bool; owner_name: str; is_mine: bool; can_edit: bool
    sources: list[ViewSource]; settings: ViewSettings; updated_at: datetime
```

Stored JSON: `sources` is `[s.model_dump(mode="json") for s in body.sources]`, so a journal source keeps every field and a container source keeps `name`. `settings` is `body.settings.model_dump(mode="json")`.

### C2. Backend: the rules (`backend/app/logs/views.py`)

- `MAX_VIEWS = 100`.
- A person **reads a server for views** when the server exists, `server.os == "linux"`, and `access.allows(Permission.VIEW_LOGS, server.server_group_id)`.
- **Saving** (POST and PUT): every `server_id` of the sources must exist and be seen (`access.sees(group)`), else `404 not_found`. It must also be read for views, else `403 forbidden`. A file path is not checked against the allowlist.
- **Listing** returns the person's own views, plus the shared views of others: all of them for the Owner, otherwise only those whose every server is read for views. They are ordered by `lower(name)`, then `id`. `owner_name` is `users.name`, `is_mine = owner_id == user.id`, and `can_edit = is_mine or access.is_owner`.
- **PUT/DELETE**: the view is loaded `FOR UPDATE`. It is visible when it is the person's own, or when it is shared and (the person is the Owner or they read every server). Not visible: `404 not_found`. Visible but not `can_edit`: `403 forbidden`. The PUT then saves with the checks above. A PUT that changes nothing answers `409 no_change` (the message exists already).
- **Limits**: lock the person's `users` row (`select(User).where(User.id == user.id).with_for_update()`) and count. 100 already: `409 too_many_views` (POST only). A name clash on the same owner, without regard to case: `409 view_name_taken`. Pre-check with `func.lower(LogView.name) == name.lower()`, then `flush_unique(db, "log_views_owner_id_name_key", "view_name_taken")`.
- **Events**: `log_view.created`, `log_view.updated` and `log_view.deleted` (in `app/logs/actions.py`, as `VIEW_ACTIONS`), built with `auth_event(request, action, actor_of(user), mfa=True, target=Target(type="log_view", id=str(view.id), name=view.name), change=changes(before, after))`. The fields are `{"name", "shared", "sources", "settings"}` as stored JSON. Created: `changes({}, fields)`. Deleted: `changes(fields, {})`.

### C3. Frontend: types (`frontend/src/lib/logs/`)

```ts
// levels.ts
export type LevelGroup = "error" | "warning" | "info" | "debug" | "none";
export const LEVEL_GROUPS: readonly LevelGroup[] = ["error", "warning", "info", "debug", "none"];
export const LEVEL_LABELS: Record<LevelGroup, string> = { error: "Error", warning: "Warning", info: "Info", debug: "Debug", none: "No level" };
export const LEVEL_TAGS: Record<LevelGroup, string> = { error: "ERR", warning: "WRN", info: "INF", debug: "DBG", none: "" };
export function groupOfPriority(priority: string): LevelGroup;  // emerg|alert|crit|err→error, warning, notice|info→info, debug; unknown→none
export function levelOf(priority: string | null | undefined, plain: string): LevelGroup;

// sources.ts
export const PRIORITIES = ["emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"] as const;
export type Priority = (typeof PRIORITIES)[number];
export type JournalSource = { kind: "journal"; server_id: string; unit: string | null; priority: Priority | null; this_boot: boolean };
export type FileSource = { kind: "file"; server_id: string; path: string };
export type ContainerSource = { kind: "container"; server_id: string; container_id: string; name: string | null };
export type LogSource = JournalSource | FileSource | ContainerSource;
export type ViewSettings = { q: string; regex: boolean; levels: LevelGroup[]; layout: "side_by_side" | "merged"; wrap: boolean; utc: boolean };
export type ViewState = { sources: LogSource[]; settings: ViewSettings };
export const DEFAULT_SETTINGS: ViewSettings;  // "", false, all five, "side_by_side", false, false
export const MAX_SOURCES = 16, MAX_PER_SERVER = 8, MAX_FILTER = 200;
export function checkUnit(v: string): boolean; checkPath(v: string): boolean; checkContainer(v: string): boolean;
export function encodeSource(s: LogSource): string;      // also the source's local id
export function decodeSource(text: string): LogSource | null;
export function stateFrom(params: URLSearchParams): ViewState & { view: string | null };
export function queryOf(state: ViewState, view?: string | null): string;  // no leading "?"; "" when all default
export function wire(s: LogSource): Record<string, unknown>;  // what subscribe sends: container without name
export function sameSource(s: LogSource, described: Record<string, unknown>): boolean;
export function sourceLabel(s: LogSource): string;
export function swapContainers(sources: LogSource[], containers: Map<string, Container[]>): { sources: LogSource[]; changed: boolean };
export function normalizeSource(raw: Record<string, unknown>): LogSource | null;  // from the API; the field rules
```

Ported rules from `backend/app/logs/sources.py`:
- `UNIT = /^[A-Za-z0-9][A-Za-z0-9:_.@-]{0,254}$/`
- `PATH = /^\/[A-Za-z0-9._\/@%+=:,-]{0,254}$/`, with every segment after the first `/` non-empty and not `.` or `..`
- `CONTAINER = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/`
- the server ID matches the UUID form `/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i`

**Address codec.** The fields are joined with `~`, and trailing empty fields are left out:
- `j~S`, `j~S~nginx.service`, `j~S~~warning`, `j~S~nginx.service~err~1`
- `f~S~/var/log/syslog`
- `c~S~3f2a…~web`, or `c~S~3f2a…` with no name

`decodeSource` pads the missing fields. It returns null on an unknown kind, a broken rule, an unknown priority, a fifth journal field other than `1` or empty, or too many fields.

`stateFrom`:
- `src` entries in order: invalid ones and duplicates (same `encodeSource`) are dropped, and only the first 16 are kept.
- `q`: cut to 200 characters. `re=1`.
- `lv`: absent means all five. Present means comma-separated, with unknown words dropped, so `lv=` is none.
- `layout=merged`, `wrap=1`, `tz=utc`, and `view`.

`queryOf` writes the parameters in that order and leaves every default out.

`sameSource` compares the socket's `describe()` (`{server_id, kind, unit, priority, this_boot}`, `{server_id, kind, path}`, `{server_id, kind, container_id}`) field by field.

`swapContainers`: for a container source whose `container_id` is missing from its server's list (the server must be in the map) and whose `name` is set, if exactly one listed container has that `name`, its ID replaces the old one.

`sourceLabel`:
- `Journal`, then ` · nginx.service`, then ` · warning and worse`, then ` · this boot`
- `File · /var/log/syslog`
- `Container · web`, or the first 12 characters of the ID when there is no name

```ts
// store.ts
export type LineRow = { kind: "line"; key: string; source: string; run: number; seq: number; time: string; ms: number;
  text: string; plain: string; level: LevelGroup; unit: string | null; truncated: boolean };
export type MarkerRow = { kind: "marker"; key: string; source: string; ms: number; marker: "skipped" | "reconnected"; count: number };
export type Row = LineRow | MarkerRow;
export type PaneState =
  | { state: "opening" } | { state: "live" }
  | { state: "retrying"; reason: string; attempt: number; at: number }   // at: epoch ms of the next try
  | { state: "ended"; reason: string; status: number | null }           // waits: "Reconnect"
  | { state: "denied"; reason: string }                                 // waits
  | { state: "idle" };
export type SourceEntry = { id: string; source: LogSource; rows: Row[]; trimmed: number; state: PaneState;
  skipped: number; retries: number; wireId: string | null; run: number };
export type SocketState = "connecting" | "live" | "reconnecting";
export type StoreSnapshot = { version: number; entries: SourceEntry[]; socket: SocketState; idle: boolean };
export const MAX_ROWS = 10_000, TRIM_BLOCK = 1_000;
export const RETRY_MS = [2000, 5000, 15000, 30000, 30000];
export const RETRY_REASONS: ReadonlySet<string>;   // worker_unavailable, worker_restarted, unreachable, ssh_error
export class LogStore {
  constructor(options: { onWanted: (sources: LogSource[]) => void; frame?: (cb: () => void) => void; now?: () => number });
  setSources(sources: LogSource[]): void;
  wanted(): LogSource[];
  handle(message: ServerMessage): void;
  socketStatus(status: LogSocketStatus): void;
  socketOpened(): void;
  retryNow(id: string): void;   // retrying → opening
  reconnect(id: string): void;  // ended|denied → opening, retries = 0
  resume(): void;               // idle → opening for every idle entry
  subscribe(listener: () => void): () => void;
  snapshot(): StoreSnapshot;    // same object until the next notify (useSyncExternalStore)
  dispose(): void;              // clears timers and the pending frame
}

// socket.ts
export type WireLine = { seq: number; time: string; text: string; level?: string; unit?: string; truncated?: boolean };
export type ServerMessage =
  | { type: "subscribed"; sources: { id: string; source: Record<string, unknown> }[]; denied: { source: Record<string, unknown>; reason: string }[] }
  | { type: "lines"; source: string; lines: WireLine[]; backlog?: boolean }
  | { type: "skipped"; source: string; count: number }
  | { type: "ended"; source: string; reason: string; status?: number }
  | { type: "error"; detail: string };
export type LogSocketStatus = "connecting" | "live" | "reconnecting" | "closed";
export const ACTIVE_EVERY_MS = 60_000;
export function logsSocketUrl(location: Pick<Location, "protocol" | "host">): string;  // ws(s)://host/api/ws/logs
export class LogSocket {
  constructor(options: { onMessage: (m: ServerMessage) => void; onStatus: (s: LogSocketStatus) => void; onOpen: () => void; now?: () => number });
  subscribe(sources: Record<string, unknown>[]): void;  // remembers; connects on the first non-empty call; sends when open
  active(): void;   // {"type":"active"} at most once per ACTIVE_EVERY_MS, only while open
  close(): void;    // final
}
```

**Store rules.**
- **Wanted** means the entries in `opening`, `live` or `idle`→no. Exactly: `opening` or `live`. After any change, `onWanted(wanted())` is called only when the list of `encodeSource` of the wanted sources differs from the last list reported.
- **`subscribed`**: each wanted entry that `sameSource`-matches a `sources[i].source` gets `wireId = sources[i].id` and stays `opening` until its backlog. A match in `denied` becomes `denied` with that reason.
- **`lines` with `backlog: true`**:
  - When the entry has no line rows, all the lines are added.
  - Otherwise find the entry's last line row (same `seq`, `time` and `text`) in the backlog. When it is there, only the backlog lines after it are added. When it is not, a `reconnected` marker goes in, `run += 1`, and the whole backlog is added.
  - Then `state = live` and `retries = 0`.
- **`lines` without backlog**: the lines are appended.
- **A line row**:
  - `key = ${id}:${run}:${seq}`
  - `ms = Date.parse(time)`
  - `plain = stripAnsi(text)`
  - `level = levelOf(line.level, plain)`
- **A marker row**: `key = ${id}:m${n}` (`n` is a store-wide counter), and `ms` is the `ms` of the entry's last row, or `now()`.
- **`skipped`**: a `skipped` marker with `count`, and `skipped += count`.
- **The cap**: when `rows.length > MAX_ROWS`, the oldest `TRIM_BLOCK` rows (or more, to get back to `MAX_ROWS`) are dropped, and `trimmed` grows by that number.
- **`ended`**:
  - `idle` makes the entry `idle`.
  - A reason in `RETRY_REASONS` while `retries < 5`: the entry becomes `retrying` with `attempt = retries + 1` and a delay of `RETRY_MS[retries]` (0 for the first `worker_restarted`). Then `retries += 1`, and a timer moves it to `opening`.
  - Otherwise the entry becomes `ended`, with `status` from the message or null.
  - Each time, `wireId = null`.
- **Messages for an unknown `wireId`** are ignored.
- **`snapshot().idle`** is true when there is at least one entry and every entry is `idle`.
- **`socketStatus`** sets `socket` (`closed` counts as `reconnecting` for the badge).
- **`socketOpened()`** moves `live` to `opening` and clears every `wireId`.
- **`setSources`** keeps the entries whose id is kept (in the new order), adds new ones as `opening`, and drops the others along with their timers.
- **Notify**: changes set a dirty flag and ask `frame` (by default `requestAnimationFrame`) once. The frame bumps `version`, rebuilds the snapshot and calls the listeners.

### C4. Pane texts (`components/logs/log-pane.tsx`, `REASONS`)

| reason | text |
|---|---|
| not_found | This server does not exist any more, or you cannot see it. |
| forbidden | You do not hold View logs on this server. |
| not_allowed | This file matches none of the group's log file patterns. |
| not_an_ssh_server | Only Linux servers stream logs. |
| host_key_not_pinned | The server's host key is not pinned yet. |
| host_key_changed | The server's host key has changed. An Admin must review it. |
| too_many_sources | This server already streams 8 sources, the most allowed. Remove one first. |
| worker_unavailable | The logs worker is not answering. |
| worker_restarted | The logs worker restarted. |
| unreachable | The server is not answering. |
| ssh_error | The SSH connection failed. |
| exited | The command ended with status {status}. |
| not_readable | The file does not exist, or cannot be read. |
| not_available | This source is not available on this server. |
| denied | sudo refused megoo-ctl on this server. Run megoo-setup.sh on it again. |
| key_refused | The server refused the platform's key. |
| (other) | The stream ended ({reason}). |

Badges: `opening` "Connecting", `live` "Live" (or "Paused" while the list is scrolled up), the socket `reconnecting` "Reconnecting", `retrying` "Retrying", `ended` "Ended", `denied` "Refused", `idle` "Paused".
- A `retrying` pane says `{text} Trying again in {s} s ({attempt} of 5).` and has a "Try now" button.
- An `ended` pane says the text, keeps its lines and has a "Reconnect" button.
- A `denied` pane says the text. For `not_allowed` it also has "Manage patterns", for those who may.

### C5. Levels from text (`levels.ts`)

For a line without a journal priority, `levelOf` looks at `plain.slice(0, 200)`. It takes the match with the **lowest index** among these four:
1. `/\b(FATAL|CRITICAL|ERROR|ERR|WARNING|WARN|INFO|NOTICE|DEBUG|TRACE)\b/` (case-sensitive)
2. `/\[(fatal|critical|panic|emerg|alert|error|err|warning|warn|info|notice|debug|trace)\]/i`
3. `/\b(?:level|lvl)=["']?(fatal|critical|panic|emerg|alert|error|err|warning|warn|info|notice|debug|trace)\b/i`
4. `/"level"\s*:\s*"(fatal|critical|panic|emerg|alert|error|err|warning|warn|info|notice|debug|trace)"/i`

The word then maps to a group:
- fatal, critical, panic, emerg, alert, error and err → error
- warning and warn → warning
- info and notice → info
- debug and trace → debug

No match gives `none`.

### C6. ANSI (`ansi.ts`)

```ts
export type Segment = { text: string; fg: number | null; bold: boolean; dim: boolean; italic: boolean; underline: boolean };
export function parseAnsi(text: string): Segment[];   // adjacent equal styles merge
export function stripAnsi(text: string): string;
export function nearest16(r: number, g: number, b: number): number;
export function segmentClass(s: Segment): string;      // "ansi-fg-9 ansi-bold" …
```

**Escape sequences.** Three kinds are recognised:
- CSI: `/\x1b\[[0-?]*[ -\/]*[@-~]/`. Only those that end in `m` are read, as SGR.
- OSC: `/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/`
- Two-byte escapes: `/\x1b[@-Z\\-_]/`

All of them are removed. So are the C0 controls other than tab (`\x00-\x08\x0b-\x1f\x7f`).

**SGR codes.**

| Code | Effect |
|---|---|
| 0 | Reset |
| 1 | Bold |
| 2 | Dim |
| 3 | Italic |
| 4 | Underline |
| 22 | Bold and dim off |
| 23 | Italic off |
| 24 | Underline off |
| 30–37 | fg 0–7 |
| 90–97 | fg 8–15 |
| 39 | fg null |
| 38;5;n | n < 16 is n itself; 16–231 is the 6×6×6 cube (levels 0, 95, 135, 175, 215, 255); 232–255 is grey 8 + 10·(n − 232); the result is `nearest16` |
| 38;2;r;g;b | `nearest16` |
| 40–49, 100–107, 48;5;n and 48;2;r;g;b | Consumed and ignored |
| Unknown | Ignored |

`nearest16` uses the xterm palette (0 `#000000`, 1 `#cd0000`, 2 `#00cd00`, 3 `#cdcd00`, 4 `#0000ee`, 5 `#cd00cd`, 6 `#00cdcd`, 7 `#e5e5e5`, 8 `#7f7f7f`, 9 `#ff0000`, 10 `#00ff00`, 11 `#ffff00`, 12 `#5c5cff`, 13 `#ff00ff`, 14 `#00ffff`, 15 `#ffffff`) and the squared RGB distance.

CSS in `globals.css`, a new `@layer components { … }` after `@layer base`:
- `.ansi-fg-0`, `.ansi-fg-8` → `color: var(--muted-foreground)`
- `1`, `9` → `var(--pink-ink)`
- `2`, `10` → `var(--green-ink)`
- `3`, `11` → `var(--amber-ink)`
- `4`, `12`, `6`, `14` → `var(--cyan-ink)`
- `5`, `13` → `var(--violet)`
- `7`, `15` → `var(--fg)`
- `.ansi-bold { font-weight: 600 }`, `.ansi-dim { opacity: .7 }`, `.ansi-italic { font-style: italic }`, `.ansi-underline { text-decoration: underline }`
- `.log-match { background: color-mix(in srgb, var(--amber) 30%, transparent); color: inherit; border-radius: 2px }`
- `.log-tag-0` to `.log-tag-5`: `color` cyan-ink, pink-ink, green-ink, amber-ink, violet, fg
- `.log-level-error` pink-ink, `.log-level-warning` amber-ink, `.log-level-info` cyan-ink, `.log-level-debug` muted-foreground

### C7. Filter, merge, download

```ts
// filter.ts
export type CompiledFilter = { test: (plain: string) => boolean; ranges: (plain: string) => [number, number][] };
export function compileFilter(q: string, regex: boolean): CompiledFilter | null | { error: "invalid_regex" };
//   "" → null. Text: case-insensitive, matched literally (escaped). Regex: new RegExp(q, "giu") ("gi" if "u" throws), else the error.
//   ranges: every non-empty match, non-overlapping; a zero-width match advances by 1. test resets lastIndex.
export const SLICE = 5_000;
export class FilterCache {
  constructor(filter: CompiledFilter | null);
  apply(rows: Row[], levels: ReadonlySet<LevelGroup>, budget: number): { rows: Row[]; matched: number; total: number; pending: boolean; used: number };
  // markers always pass; a line passes when its level is on and the filter (cached per row key) matches. At most
  // `budget` uncached lines are tested, newest first; untested lines are left out and pending is true.
  // matched/total count line rows only (total = all line rows held, matched = those passing).
}
// merge.ts
export class Merger {
  update(entries: { id: string; rows: Row[]; trimmed: number }[]): Row[];
  // Merged by ms, then by the entry's index, then by seq (markers after lines of the same ms). New rows are inserted by
  // binary search from the end. Rows dropped by a trim (trimmed grew by n: the n oldest of that source) and entries no
  // longer given are removed. Returns the same array when nothing changed, a new one otherwise.
}
// download.ts
export function clock(ms: number, utc: boolean): string;     // "HH:MM:SS.mmm"
export function stamp(ms: number, utc: boolean): string;     // "2026-11-28T09:05:01.123+01:00" or "…Z" in UTC
export function downloadText(rows: Row[], options: { utc: boolean; labels: Map<string, string> | null }): string;
//   line: `${stamp} ${label + " "}${plain}${truncated ? "…" : ""}`, label only in a merged pane;
//   skipped marker: `# ${count} lines skipped`; reconnected: `# Reconnected`. Lines joined by "\n", final "\n".
export function downloadName(parts: string[], at: Date): string;
//   `logs-${parts.map(slug).join("-")}-${YYYYMMDD}-${HHMMSS}.log`; slug: lower case, runs of [^a-z0-9.]+ → "-", trimmed
//   of "-", at most 40 characters; local time. Merged: parts = ["merged"].
```

### C8. Views client (`views.ts`)

```ts
export type LogView = { id: string; name: string; shared: boolean; owner_name: string; is_mine: boolean; can_edit: boolean;
  sources: LogSource[]; settings: ViewSettings; updated_at: string };
export type ViewBody = { name: string; shared: boolean; sources: Record<string, unknown>[]; settings: ViewSettings };
export const MAX_VIEW_NAME = 80;
export async function listViews(): Promise<LogView[]>;      // GET /log-views, sources through normalizeSource (invalid dropped)
export function createView(body: ViewBody): Promise<LogView>;           // POST /log-views
export function updateView(id: string, body: ViewBody): Promise<LogView>; // PUT /log-views/{id}
export function deleteView(id: string): Promise<void>;                  // DELETE /log-views/{id}
export function bodyOf(state: ViewState, name: string, shared: boolean): ViewBody;
//   sources: wire(s) plus, for a container, name; settings: state.settings with levels in LEVEL_GROUPS order.
export function stateOf(view: LogView): ViewState;
export function differs(state: ViewState, view: LogView): boolean;   // queryOf(state) !== queryOf(stateOf(view))
```

New `MESSAGES` in `lib/auth/messages.ts`:
- `view_name_taken`: "You have a view with this name already."
- `too_many_views`: "You have 100 saved views, the most allowed. Delete one first."
- `pattern_exists`: "This pattern is in the list already."
- `too_many_patterns`: "This group has 50 patterns, the most allowed. Remove one first."

### C9. Component props

```ts
LogLine({ row, utc, wrap, filter, tag }: { row: Row; utc: boolean; wrap: boolean; filter: CompiledFilter | null;
  tag: { text: string; tone: number } | null })
LogList({ rows, utc, wrap, filter, tags, label }: { rows: Row[]; utc: boolean; wrap: boolean; filter: CompiledFilter | null;
  tags: Map<string, { text: string; tone: number }> | null; label: string })
LogPane({ title, entry, entries, rows, socket, utc, wrap, filter, merged, onRemove, onRetryNow, onReconnect,
  onManagePatterns, downloadParts })  // entry null in a merged pane; entries = those merged
LogToolbar({ settings, onSettings, matched, total, onAddSource, extra })
LogViewer({ state, onChange, servers, serverId, extra }: { state: ViewState; onChange: (next: ViewState) => void;
  servers: Server[]; serverId?: string; extra?: ReactNode })
SourceDialog({ open, onOpenChange, servers, serverId, current, onAdd })
AllowlistDialog({ group, open, onOpenChange }: { group: { id: string; name: string } | null; ... })
ViewsMenu({ views, current, changed, onOpen, onSave, onSaveAs, onEdit, onDelete })
SaveViewDialog({ view, state, open, onOpenChange, onSaved })  // view null: a new view; else rename or share
DeleteViewDialog({ view, open, onOpenChange, onDeleted })
LogsPage()   ServerLogsTab({ server }: { server: Server })   // default export too, for next/dynamic
```

## File map

**Backend**

| File | Change |
|---|---|
| `backend/app/inventory/server_schemas.py`, `servers.py` | `can_view_logs` |
| `backend/app/logs/models.py` | `LogView` |
| `backend/migrations/versions/0013_log_views.py` | The table and its grant |
| `backend/app/logs/schemas.py` | C1 |
| `backend/app/logs/actions.py` | `VIEW_ACTIONS` |
| `backend/app/logs/views.py` | C2 |
| `backend/app/logs/views_router.py` | `/api/log-views` |
| `backend/app/main.py` | Includes the router |
| `backend/tests/inventory/test_server_list.py` | `can_view_logs` |
| `backend/tests/test_migrations.py` | 0013 |
| `backend/tests/security/test_db_privileges.py` | `API_GRANTS` |
| `backend/tests/security/test_permission_coverage.py` | `ANY_SIGNED_IN` |
| `backend/tests/logs/test_log_views_api.py`, `test_log_views_change.py` | New |
| `backend/tests/test_stack.py` | The stack check |
| `README.md` | "Live logs" |

**Frontend**

| File | Change |
|---|---|
| `src/lib/logs/{levels,ansi,sources,filter,merge,download,allowlist,views,socket,store}.ts` and their tests | New |
| `src/components/logs/{log-line,log-list,log-pane,log-toolbar,use-filtered,log-viewer,source-dialog,views-menu,save-view-dialog,delete-view-dialog,logs-page,server-logs-tab}.tsx` and their tests | New |
| `src/__tests__/helpers/element-size.ts` | New |
| `src/components/settings/allowlist-dialog.tsx` | New |
| `src/components/settings/groups-page.tsx` | The "Log files" button |
| `src/app/(app)/logs/page.tsx` | `LogsPage` |
| `src/components/servers/server-page.tsx` | The `logs` tab |
| `src/components/servers/checks/containers-tab.tsx` | The "Logs" link |
| `src/lib/servers.ts`, `src/lib/auth/messages.ts`, `src/app/globals.css`, `package.json`, `package-lock.json` | Changed |

## Steps

### 1. Backend and frontend: servers answer can_view_logs
**Test first** in `backend/tests/inventory/test_server_list.py`: `test_can_view_logs_follows_view_logs_and_the_os`.
- Set-up: groups `staging` and `production`; Linux `web-01` and Windows `win-02` in staging; Linux `app-03` in production.
- Ada is an operator of staging with `view_logs=True`, and an operator of production through `add_grant(..., "operator", view_logs=False)`.
- `GET /api/servers` gives `{"app-03": False, "web-01": True, "win-02": False}`.
- `GET /api/servers/{web-01}` gives True.
- The Owner gets True for both Linux servers. An Auditor gets False everywhere.

Run BT `tests/inventory/test_server_list.py`: it fails with a `KeyError`.

**Implement:**
- `ServerOut.can_view_logs: bool`, commented "Whether the person may follow its logs: a Linux server and View logs in its group."
- In `_out`: `can_view_logs=server.os == "linux" and access.allows(Permission.VIEW_LOGS, server.server_group_id)`.
- In `tests/inventory/test_server_register.py`, add `"can_view_logs"` to the expected key list beside `"can_connect"` (line 36).
- Frontend `src/lib/servers.ts`: `can_view_logs: boolean` after `can_connect`. Add `can_view_logs: false` next to every `can_connect:` in the fixtures (`grep -rln 'can_connect:' frontend/src`).

Run BT `tests/inventory`, then `npx tsc --noEmit` and `npm test` in `frontend/`.

Commit `feat(inventory): servers say whether the person may follow their logs`.

### 2. Backend: the log_views table
**Test first:**
- `tests/test_migrations.py`: `test_0013_goes_down_and_up_again`. Downgrade to `0012`, then `to_regclass('log_views')` is NULL. Upgrade to head, then it is not NULL and `has_table_privilege('megooitadmin_api','log_views','DELETE')` is true.
- `tests/security/test_db_privileges.py`: `API_GRANTS["log_views"] = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"})`, with the comment "A person saves, replaces and deletes their own views; the Owner any shared one."

Run BT `tests/test_migrations.py tests/security/test_db_privileges.py`: the migration test fails, and so does `test_every_table_of_the_models_is_declared`.

**Implement:**
- `LogView` in `app/logs/models.py`, in the style of `LogFileAllowlist`:
  - `log_views_pkey`
  - FK `owner_id` → `users.id`, `ondelete="CASCADE"`, `log_views_owner_id_fkey`
  - `CheckConstraint("char_length(name) BETWEEN 1 AND 80", name="log_views_name_check")`
  - `Index("log_views_owner_id_name_key", "owner_id", text("lower(name)"), unique=True)`
  - The columns: `id` Uuid default uuid4, `owner_id`, `name` Text, `shared` Boolean `server_default=false()`, `sources` JSONB, `settings` JSONB, `created_at` and `updated_at` `DateTime(timezone=True)` `server_default=func.now()`
- `migrations/versions/0013_log_views.py` (revision `"0013"`, down `"0012"`): `create_table` with the same names, the index, and `GRANT SELECT, INSERT, UPDATE, DELETE ON log_views TO megooitadmin_api`. `downgrade` drops the table.

Run the tests again, then `megoocolab-runner services run migrate -- sh -c 'uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head'`.

Commit `feat(logs): a table for saved log views`.

### 3. Backend: save and list views
**Test first** in `tests/logs/test_log_views_api.py` (fixtures `api`, `clock`; helpers from `auth_helpers`). The `view(server_id, **kw)` helper builds a POST body with one journal source. Tests:
- `test_a_person_saves_a_view_and_lists_it`: the answer has every field of `LogViewOut`, `is_mine` and `can_edit` true, the stored defaults (`unit: None`, `priority: None`, `this_boot: False`), and `settings` defaults.
- `test_a_container_source_keeps_its_name`
- `test_a_shared_view_is_listed_for_who_reads_every_server`:
  - An operator of g1 with View logs saves a shared view of a g1 server and a g2 server, after the Owner gives them g2 too.
  - It is listed for an admin of g1 and g2, and for the Owner.
  - It is not listed for an operator of g1 only, for an operator of g1+g2 without View logs on g2, or for an Auditor.
  - A view naming a Windows server is listed for nobody else.
- `test_a_private_view_is_nobody_elses` (the Owner included)
- `test_saving_refuses_a_server_out_of_sight_404_and_without_view_logs_403`, and a Windows server answers 403
- `test_the_name_is_unique_per_owner_without_regard_to_case`: 409 `view_name_taken`. Another person may use the same name.
- `test_the_101st_view_is_refused`: insert 100 rows through `SessionLocal`, then POST gives 409 `too_many_views`.
- `test_invalid_bodies_answer_422` (parametrize): no source, 17 sources, a bad unit, `..` in a path, a 201-character `q`, a level `fatal`, an unknown field, an 81-character name, a blank name.
- `test_saving_records_log_view_created` with `target_type == "log_view"` and `change` `{name, shared, sources, settings}` with before None.

In `tests/security/test_permission_coverage.py`, pin `"GET /api/log-views"` and `"POST /api/log-views"` in `ANY_SIGNED_IN` with "the list and the save filter and check by the person itself".

Run BT `tests/logs/test_log_views_api.py tests/security`: it fails with 404.

**Implement** C1 and C2 (create and list) in `schemas.py`, `actions.py` (`LOG_VIEW_CREATED`, `LOG_VIEW_UPDATED`, `LOG_VIEW_DELETED`, `VIEW_ACTIONS`) and `views.py`: `list_views(db, access, user)` and `create_view(db, request, user, access, body)`.

`views_router.py` is `APIRouter(prefix="/log-views")`:
- `GET ""` with `user: CurrentUser` and `access: CurrentAccess`
- `POST ""` with `dependencies=[audited(actions.LOG_VIEW_CREATED)]`

Include it in `app/main.py` after `logs_allowlist_router`.

Run BT `tests/logs tests/security` and `make test-security`.

Commit `feat(logs): people save log views and list their own and the shared ones`.

### 4. Backend: replace and delete views
**Test first** in `tests/logs/test_log_views_change.py`:
- `test_the_owner_of_a_view_replaces_it`: the four fields change, `updated_at` moves, and the event `log_view.updated` holds the before and after of the changed fields only.
- `test_the_platform_owner_replaces_and_deletes_a_shared_view`
- `test_another_reader_of_a_shared_view_gets_403`
- `test_a_private_view_of_another_and_a_shared_one_out_of_reach_answer_404`, for both PUT and DELETE
- `test_a_put_that_changes_nothing_answers_409_no_change`
- `test_put_applies_the_save_checks`: 404, 403, and the name clash
- `test_deleting_records_log_view_deleted` (after None)
- `test_a_disabled_owners_shared_views_stay` (disable through the API as the Owner, then still listed for a reader)
- `test_a_view_naming_a_lost_server_stays_in_its_owners_list` (delete the server as the owner session)

Pin `PUT` and `DELETE /api/log-views/{view_id}` in `ANY_SIGNED_IN` with the same reason.

Run BT: 405 or 404.

**Implement** `update_view` and `delete_view` in `views.py` (C2), with the routes `PUT /{view_id}` (`audited(LOG_VIEW_UPDATED)`) and `DELETE /{view_id}` (status 204, `audited(LOG_VIEW_DELETED)`).

Run BT `tests/logs tests/security`, then `make test-security`.

Commit `feat(logs): the owner of a view and the Owner replace and delete it`.

### 5. Frontend: levels and ANSI
**Test first:**
- `src/lib/logs/__tests__/levels.test.ts`:
  - every priority maps to its group
  - `levelOf("err", "INFO x")` is `error` (the priority wins)
  - C5 cases: `"2026 ERROR boom"`, `"[warn] x"`, `"level=debug"`, `"lvl=\"info\""`, `'{"level":"fatal"}'`, `"TRACE"` → debug, `"error in lower case"` → none, a word after 200 characters → none, the earliest of two
- `ansi.test.ts`:
  - the 16 colours, bold, dim, italic and underline, resets 0/22/23/24/39
  - `38;5;196` → 9, `38;5;244` → 8, `38;2;0;205;0` → 2
  - backgrounds are ignored
  - OSC, cursor moves and `\x1b(B` are stripped
  - `stripAnsi` and merging of equal segments
  - `segmentClass`

Run FT `src/lib/logs`: the modules are missing.

**Implement** `levels.ts` (C3, C5) and `ansi.ts` (C6).

Run FT again.

Commit `feat(logs): read a line's level and its ANSI colours`.

### 6. Frontend: sources and the address
**Test first** in `src/lib/logs/__tests__/sources.test.ts`:
- each kind encodes and decodes both ways, with trailing fields left out
- `decodeSource` refuses a bad server ID, unit, path (`/a/../b`, `relative`, `/a//b`), container, priority, an extra field, and an unknown kind
- `stateFrom` drops invalid and duplicate entries, keeps 16, cuts `q` at 200, and reads `lv` absent, empty and listed, plus `layout`, `wrap`, `tz` and `view`
- `queryOf` leaves out defaults, and `stateFrom(new URLSearchParams(queryOf(s)))` round-trips
- `wire` drops `name`
- `sameSource` against `describe()`-shaped objects
- `sourceLabel`
- `swapContainers`: one name match swaps; none, two, a server not in the map, or a present ID do not
- `normalizeSource`

Run FT: missing.

**Implement** `sources.ts` per C3. `Container` comes from `@/lib/checks`.

Run FT.

Commit `feat(logs): log sources and the viewer's address`.

### 7. Frontend: the filter
**Test first** in `filter.test.ts`:
- text matching ignores case and treats `.*` literally
- regex matching
- an invalid regex gives `{error}`
- `""` gives null
- `ranges` for several matches and for a zero-width regex (`^`)
- `FilterCache.apply`:
  - markers pass
  - levels filter
  - the budget tests the newest first and reports `pending`
  - a second call with the same rows tests nothing new (`used` 0)
  - `matched` and `total`

Run FT: missing.

**Implement** C7 `filter.ts`.

Run FT.

Commit `feat(logs): text and regex filters with highlight ranges`.

### 8. Frontend: merge and download
**Test first:**
- `merge.test.ts`:
  - two sources interleave by time
  - equal times order by entry index and then seq
  - a late line is inserted at its time
  - a trim removes the oldest of its source
  - a removed entry disappears
  - an unchanged update returns the same array
- `download.test.ts` (set `TZ` with `vi.stubEnv("TZ", …)` only if needed; prefer checking `stamp(ms, true)` exactly and matching `stamp(ms, false)` with `/[+-]\d\d:\d\d$/`):
  - the lines with and without labels, markers as `#` lines, `…` for truncated
  - `downloadName` slugs

Run FT: missing.

**Implement** C7 `merge.ts` and `download.ts`.

Run FT.

Commit `feat(logs): merge sources by time and write a pane as a text file`.

### 9. Frontend: the allowlist port and the views client
**Test first:**
- `allowlist.test.ts` ports the cases of `backend/tests/logs/test_log_allowlist_rules.py`, the `check_pattern` and `matches` tables, one to one.
- `views.test.ts` mocks `apiFetch`:
  - `listViews` calls `/log-views` and drops an invalid source
  - `createView`, `updateView` and `deleteView` use the right method and path
  - `bodyOf` keeps a container's name and orders levels
  - `differs` is false for the same state and true after a changed filter or source order
- `src/lib/auth/__tests__/messages.test.ts`: the four new reasons have texts.

Run FT: missing.

**Implement** `allowlist.ts`:
- `checkPattern(v): boolean` ports the PATTERN regex `/^\/[*?A-Za-z0-9._\/@%+=:,-]{0,254}$/`, the segment rule with wildcards as letters, and no wildcard in the first segment.
- `matches(path, patterns): boolean` ports `_glob` without a regex.

Then `views.ts` (C8), and the C8 messages in `messages.ts`.

Run FT.

Commit `feat(logs): the allowlist rules and the saved views client in the browser`.

### 10. Frontend: LogSocket
**Test first** in `socket.test.ts`, with `installFakeWebSocket()` and fake timers:
- No socket opens before the first non-empty `subscribe`.
- The URL ends in `/api/ws/logs`.
- After `open()`, `{"type":"subscribe","sources":[…]}` is sent. Each later `subscribe` sends again, and so does an empty one.
- A drop with 1006 reports `reconnecting`, waits `BACKOFF_MS` (1000, then 2000), and sends the remembered set after the new open. Then `onOpen` is called.
- 4401 closes for good, calls `goTo("/login?next=…")` (mock `@/lib/auth/navigate`) and never reconnects.
- `active()` sends at most once per 60 s, measured with an injected `now`, and not while connecting.
- `document.visibilityState = "hidden"` with a `visibilitychange` event does not close it.
- `close()` stops the reconnects.
- Messages that are not JSON are ignored.

Run FT: missing.

**Implement** C3 `socket.ts`, reusing `BACKOFF_MS` and `NOT_SIGNED_IN_CLOSE` from `@/lib/live-socket`.

Run FT.

Commit `feat(logs): the browser's client of the log socket`.

### 11. Frontend: LogStore rows
**Test first** in `store.test.ts` (the parts about rows). Construct with `frame: (cb) => queue.push(cb)` and a fake `now`.
- `setSources` and `wanted` order, and `onWanted` only when the list changes.
- `subscribed` maps a `wireId` through `sameSource`.
- The backlog adds the lines with `plain`, `level` and `key`.
- Live lines append.
- A second backlog that holds the last row adds only the newer lines. One that does not adds a `reconnected` marker, bumps `run` and adds all.
- `skipped` adds a marker and a total.
- The cap: 10,001 rows trim to 9,001 with `trimmed` 1000.
- Messages for an unknown id are ignored.
- The listeners run once per frame however many messages arrive, and `snapshot()` keeps its identity between frames.

Run FT: missing.

**Implement** the row half of C3 `store.ts`: the constructor, `setSources`, `wanted`, `handle` for `subscribed`, `lines` and `skipped`, `subscribe`, `snapshot` and `dispose`.

Run FT.

Commit `feat(logs): a store holds each source's last 10,000 rows`.

### 12. Frontend: LogStore states
**Test first** in `store-states.test.ts`, with fake timers:
- `denied` → `denied` and out of `wanted`
- each retry reason → `retrying` with the delays 2, 5, 15, 30 and 30 s, then `opening` and back in `wanted`
- `worker_restarted` first retries at 0 s
- the 6th end → `ended`
- a backlog resets `retries`
- `retryNow` skips the wait
- `exited` with status 1 → `ended` with status 1, and its rows are kept
- `reconnect` moves it back to `opening`
- `idle` on every entry → `snapshot().idle`, and `resume()` reopens them
- `socketStatus("reconnecting")`
- `socketOpened()` moves `live` to `opening` and clears the ids
- `dispose` clears the timers

Run FT: they fail.

**Implement** `ended` handling, the timers, `retryNow`, `reconnect`, `resume`, `socketStatus` and `socketOpened` per C3.

Run FT `src/lib/logs`.

Commit `feat(logs): the store retries passing ends and waits on the others`.

### 13. Frontend: the virtualised list
1. In `frontend/`, run `npm install @tanstack/react-virtual`.
2. Check that `grep -n 'anchorTo\|followOnAppend\|scrollEndThreshold' node_modules/@tanstack/virtual-core/dist/esm/index.d.ts` finds all three. If one is missing, stop and report it.

**Test first:**
- Add `src/__tests__/helpers/element-size.ts`: `mockElementSize(width = 800, height = 400, row = 20)` stubs `HTMLElement.prototype.getBoundingClientRect`, `offsetWidth`, `offsetHeight` and `clientHeight` with `vi.spyOn(…, "get")` or `defineProperty`. Scroll containers (`data-log-scroll`) get the given size and rows get `row`. It returns a restore function.
- `src/components/logs/__tests__/log-list.test.tsx`:
  - 1,000 rows render only the rows in sight
  - a row shows `clock` time, a level tag (`ERR`), its ANSI classes and `.log-match` marks
  - markers read "1,240 lines skipped" and "Reconnected"
  - wrap off uses `whitespace-pre`, on uses `whitespace-pre-wrap`
  - a scroll more than 24 px from the end (set `scrollTop` and fire `scroll`) shows "Jump to latest · 3 new" after 3 rows arrive
  - clicking it hides it
  - the list is `role="log"` with `aria-live="off"`

Run FT: missing.

**Implement** `log-line.tsx` and `log-list.tsx` with C9 props.
- `useVirtualizer({ count, getScrollElement, estimateSize: () => 20, getItemKey: (i) => rows[i].key, anchorTo: "end", followOnAppend: true, scrollEndThreshold: 24, overscan: 20 })`.
- With wrap on, rows are measured (`ref={virtualizer.measureElement}`, `data-index`).
- Paused means `scrollHeight - scrollTop - clientHeight > 24`, held in state. The "new" count is the rows after the last key seen at the pause. Jump calls `scrollToIndex(rows.length - 1, { align: "end" })`.
- Add the C6 CSS to `globals.css`.

Run FT `src/components/logs src/app src/__tests__`.

Commit `feat(logs): a virtualised list that follows new lines and pauses on scroll-up`.

### 14. Frontend: the pane
**Test first** in `log-pane.test.tsx`:
- the header shows the server name and `sourceLabel`, the badge per C4, and the skipped total ("1,240 skipped")
- each C4 reason text
- "Try now" calls `onRetryNow` and "Reconnect" calls `onReconnect`
- "Manage patterns" shows only for `not_allowed` with `onManagePatterns`
- "Remove" calls `onRemove`
- Download: stub `URL.createObjectURL` and `HTMLAnchorElement.prototype.click`. The Blob holds `downloadText`, and the `download` attribute is `downloadName`.
- a merged pane titles itself "Merged · 2 sources", and its download uses the labels

Run FT: missing.

**Implement** `log-pane.tsx` (C4, C9) with `Card`, `Badge` and `Button`. The countdown re-renders each second while `retrying`.

Run FT.

Commit `feat(logs): a pane says its state and downloads its lines`.

### 15. Frontend: the toolbar and the filtered rows
**Test first:**
- `log-toolbar.test.tsx`:
  - typing calls `onSettings` once, 200 ms after the last key (fake timers)
  - an invalid regex turns the field `aria-invalid` and shows "Not a valid regular expression" without calling `onSettings`
  - the regex switch, the five level switches (`aria-pressed`), Side by side or Merged, Wrap and Local or UTC
  - "212 of 4,203 lines match" when a filter or level is active
  - "Add source" only with `onAddSource`
  - `extra` renders
- `use-filtered.test.tsx` (`renderHook`): the hook applies `FilterCache` with a shared budget of `SLICE` per frame across panes, schedules another frame while `pending`, and a new filter starts a new cache.

Run FT: missing.

**Implement:**
- `log-toolbar.tsx`: an `Input` with the max length 200, and pressed buttons for the switches.
- `use-filtered.ts`: `useFiltered(lists: Row[][], settings): { lists: Row[][]; matched: number; total: number; filter: CompiledFilter | null }`.

Run FT.

Commit `feat(logs): the viewer's toolbar and its filter`.

### 16. Frontend: LogViewer
**Test first** in `log-viewer.test.tsx`, with `installFakeWebSocket`, a mocked `apiFetch` for `/servers/{id}/containers`, fake timers, `mockElementSize` and a `requestAnimationFrame` stub:
- the address's two sources (a container and a journal unit) open one socket and subscribe with their `wire` forms
- `subscribed`, then the backlogs show both panes side by side with lines
- the filter and the levels hide lines and highlight matches
- `layout: "merged"` shows one pane ordered by time, with `log-tag-*` tags
- the Local or UTC switch changes the shown times
- a container ID no longer listed but with one name match is swapped, and `onChange` gets the new state before the subscribe
- an `ended idle` on every source shows "Paused after 30 minutes without activity" with "Resume", which subscribes again
- a key press inside sends `active` once
- removing a pane calls `onChange` without it
- unmount closes the socket
- a source of an unknown server titles "Unknown server"

Run FT: missing.

**Implement** `log-viewer.tsx` (C9):
- One `LogSocket` and one `LogStore` per mount (refs). `store.onWanted` → `socket.subscribe(sources.map(wire))`.
- `useSyncExternalStore(store.subscribe, store.snapshot)`.
- `setSources` on a state change, after `swapContainers` with the containers read for each server that has a container source.
- Side by side: `grid gap-4 md:grid-cols-2 xl:grid-cols-3`. Merged: one `Merger`.
- Activity: `onPointerDown`, `onKeyDown`, `onWheel` and `onScrollCapture` call `socket.active()`.

Run FT.

Commit `feat(logs): the viewer follows its sources side by side or merged`.

### 17. Frontend: the allowlist dialog and its Settings door
**Test first:**
- `src/components/settings/__tests__/allowlist-dialog.test.tsx`:
  - lists `GET /server-groups/g1/log-allowlist`
  - Remove → `DELETE …/{pattern_id}` and reload
  - Add refuses `/*` locally ("Not a valid pattern") and posts a valid one
  - 409 `pattern_exists` and `too_many_patterns` show their messages
  - `can_manage: false` hides Add and Remove
- `groups-page.test.tsx`: each row has "Log files of {name}", which opens the dialog.

Run FT: they fail.

**Implement** `allowlist-dialog.tsx` (shadcn `Dialog`, `checkPattern`, `messageFor`), and the `FileText` icon button in `groups-page.tsx`.

Run FT `src/components/settings`.

Commit `feat(settings): the Owner edits a group's log file patterns`.

### 18. Frontend: the source dialog
**Test first** in `source-dialog.test.tsx`:
- the server list holds only `can_view_logs` Linux servers, grouped by `group_name`, and is fixed with `serverId`
- **Journal**: an invalid unit is refused, and priority and "This boot only" give the right source
- **File**: the group's patterns show. A pattern without a wildcard is offered as the person types. A path that matches none disables Add, with "This path matches none of the group's patterns". "Manage patterns" shows when `can_manage`, opens `AllowlistDialog`, and the patterns reload after it closes.
- **Containers**: grouped by Compose project with a state badge. Several can be ticked, and a source carries the name.
- **Limits**: the text "A view holds at most 16 sources, 8 per server." Adding past either limit is disabled. Sources already in `current` are not added twice.
- in `log-viewer.test.tsx`: "Add source" opens it, and a `not_allowed` pane offers "Manage patterns" when the group's allowlist says `can_manage`

Run FT: they fail.

**Implement** `source-dialog.tsx` (C9), and wire it in `LogViewer`. `onAddSource` opens it, and `onAdd` → `onChange`. A pane's `onManagePatterns` is set when `GET /server-groups/{group}/log-allowlist` says `can_manage`, read once per group when a pane is `not_allowed`.

Run FT.

Commit `feat(logs): add a journal, a file or containers to the viewer`.

### 19. Frontend: the Logs page
**Test first** in `logs-page.test.tsx` (mock `useSearchParams` and `useRouter`):
- With no server `can_view_logs`, it says "You do not hold View logs on any server. The Owner grants it in Settings → Users." and opens no socket. An Auditor's answer has every flag false.
- With servers and no `src`, it shows "Add source".
- With `src`, the viewer gets the state, and a change calls `router.replace("/logs?…")` with `queryOf`.

Run FT: missing.

**Implement:**
- `logs-page.tsx`: reads `GET /servers` and `stateFrom(useSearchParams())`, and renders `LogViewer` in the page.
- `src/app/(app)/logs/page.tsx`: `metadata` as now, and `<Suspense><LogsPage /></Suspense>` instead of the placeholder.
- If `src/components/__tests__/placeholder-page.test.tsx` lists `/logs`, update it.

Run FT `src/components src/app`.

Commit `feat(logs): the Logs page`.

### 20. Frontend: saved views on the Logs page
**Test first:**
- `views-menu.test.tsx`: "My views" and "Shared with me" (with the owner's name). Opening one calls `onOpen`. "Save" shows only with `current`, `can_edit` and `changed`. "Save as a new view" always shows. "Rename or share" and "Delete" show only when `can_edit`.
- `save-view-dialog.test.tsx`: a new view POSTs `bodyOf`. Rename or share PUTs the name and `shared`. A name over 80 characters is refused locally. `view_name_taken` and `too_many_views` show their messages. The shared hint is "People who hold View logs on every server of this view see it."
- `delete-view-dialog.test.tsx`: DELETE, then `onDeleted`.
- `logs-page.test.tsx`:
  - opening a view writes `queryOf(stateOf(view), id)`
  - the title shows the view's name, with "Changed" while `differs`
  - "Save" PUTs the current state
  - after the reload, a view no longer listed drops `view` from the address
  - the Owner sees Delete on another person's shared view, and a reader does not

Run FT: they fail.

**Implement** the three components (C9: `DropdownMenu`, `Dialog`, `Checkbox`) and their wiring in `LogsPage` through the viewer's `extra`.

Run FT.

Commit `feat(logs): save, share, open and delete log views`.

### 21. Frontend: the server's Logs tab and the Containers link
**Test first:**
- `server-logs-tab.test.tsx`: sources of other servers in the address are dropped. A change replaces `/servers/{id}?tab=logs&…`. "Open in Logs" links to `/logs?{queryOf(state)}`. The source dialog is fixed to the server.
- `server-page.test.tsx`: a Logs tab only when `can_view_logs`, and `?tab=logs` without it falls back to Overview.
- `containers-tab.test.tsx`: with `canViewLogs`, each row has a "Logs" link to `/servers/{id}?tab=logs&src=` + the encoded container source with its name. Without it, there is none.

Run FT: they fail.

**Implement:**
- `server-logs-tab.tsx`, with a named export and a default export.
- In `server-page.tsx`:
  - `type Tab` gains `"logs"`
  - the tabs are `LINUX_TABS` plus `"logs"` when `server.can_view_logs`, with the button after Containers
  - `const LogsTab = dynamic(() => import("@/components/logs/server-logs-tab"), { ssr: false, loading: () => <Skeleton className="h-64" /> })`
- `ContainersTab` gains `serverId` and `canViewLogs` props, and a link column.

Run FT `src/components`, then `npx tsc --noEmit` and `npm test`.

Commit `feat(servers): a Logs tab and a Logs link per container`.

### 22. Stack: the page and a shared view through Caddy
**Test first** in `backend/tests/test_stack.py`: `test_the_logs_page_answers_and_a_shared_view_reaches_another_reader(owner)`.
1. `owner.get("/logs")` is 200.
2. Create the group `logs-views`, then the Linux server `stack-logs-01` in it.
3. POST `/api/log-views`: `{"name": "Stack view", "shared": true, "sources": [{"kind": "journal", "server_id": …}]}`.
4. Invite Olga as an operator of the group with `view_logs: true`, through the invite, enrol and confirm steps of `test_a_staging_only_admin_sees_only_staging_is_refused_settings_and_is_disabled`. Factor them into `_invited_client(owner, name, email, grants) -> httpx.Client` and use it in both tests.
5. Her `GET /api/log-views` lists "Stack view" with `is_mine` and `can_edit` False.

Run `megoocolab-runner services run stack -- uv run pytest -m stack -k "logs_page or staging_only"`.

Commit `test(stack): the Logs page answers and a shared view reaches another reader`.

### 23. Docs: the Live logs part of the README
Rewrite `README.md` → "### Live logs":
- the Logs page and the server's Logs tab, which replace "its page comes later"
- follow and pause, filters, levels read from the text, merged or side by side, Local or UTC, and per-pane downloads
- the address holds the view
- saved views: private or shared, who sees a shared one (View logs on every server), who changes it (its owner and the Owner), 100 per person, and the events `log_view.created`, `log_view.updated` and `log_view.deleted`
- the allowlist dialog's two doors (Settings → Server groups → Log files; Manage patterns in the file picker)
- a stream ending for a passing reason is retried 5 times

Check with `uv run pytest tests/test_stack.py -k columns` if a column check applies. Otherwise keep it to 120 columns by hand.

Commit `docs: the log viewer and saved views`.

## Final verification

From `backend/`:
- `megoocolab-runner services run test -- uv run pytest`
- `megoocolab-runner services run image -- uv run pytest -m docker`
- `megoocolab-runner services run stack -- uv run pytest -m stack`
- the migrate down and up check
- `make test-security`

From `frontend/`:
- `npx tsc --noEmit`
- `npx eslint src`
- `npm test`
- `npm run build`
- `megoocolab-runner services run web -- npm run test:image`

From the root: `uv run --project backend pytest tools/release` and `uv run --project backend python tools/release/versions.py check`.

Manual check of the Phase 1 exit: with `make up STACK=dev` and the fake server registered, pin its key. Then, on `/servers/{id}?tab=logs`, add a container and the journal unit `ssh.service`. Both panes follow side by side, scrolling up pauses one, and "Jump to latest" brings it back.
