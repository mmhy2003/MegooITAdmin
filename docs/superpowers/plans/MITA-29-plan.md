# MITA-29 — Alert rules and notifications — implementation plan

## Goal
The Owner sets alert rules in Settings. The collector checks every sample against them, and writes firing, resolved and ended alerts with their events and audit events. The pages show alerts on the Dashboard, on a server's page and under a bell. A sender task in the backend delivers one message per event by email, to webhooks and to Telegram.

## Architecture
- **Collector.** `app/collector/alerts/engine.py` is pure: it takes rules, servers, samples and the clock, and gives transitions. `app/collector/alerts/book.py` loads the firing alerts and the rules at each 10-second poll. It writes each transition (an `alerts` row, an `alert_events` row and the audit event) in one transaction, and keeps refused writes until the next poll.
- **Backend, alerts.** `app/alerts/` holds the models (`alert_rules`, `alerts`, `alert_events`), the metric catalog, the Owner's rule CRUD and the read routes.
- **Backend, notifications.** `app/notify/` holds the channel tables, the encrypted secrets, the message texts, the transports, the sender loop (started by a FastAPI lifespan) and the Owner's routes.
- **Frontend.** `lib/alerts.ts` holds types and sentences. `components/alerts/` holds the shared pieces. On top of them come the Dashboard card, tile and marks, the header bell, the server banner and Alerts tab, and two new Settings tabs.

## Facts checked (repo at `f609668`)
- The last migration is `0010_checks.py`. `test_migrations.py` requires `0011_<slug>.py` with `down_revision = "0010"`, and `test_the_models_match_the_migrations` runs `alembic check`.
- `tests/security/test_db_privileges.py` compares table grants with `API_GRANTS` and `COLLECTOR_GRANTS`. It asserts that the API role has **no** column grants (`assert await _rows(COLUMN_GRANTS_SQL) == []`): this test changes to a declared `API_COLUMN_GRANTS`.
- `SELECT … FOR UPDATE` needs `UPDATE` on at least one column, so a column grant on `alert_events.dispatched_at` is enough for the sender's claim.
- The collector has `SELECT` on `servers`, and audit grants (`INSERT` on `audit_log`, `SELECT, UPDATE` on `audit_chain_head`). `app.audit.record(session, event)` must be called last in a transaction, and raises `AuditChainBusy` (a `RuntimeError`) after 5 s.
- Foreign-key cascades run as the table owner, so a server deletion by the API role also removes `alerts`, `alert_events` and `notification_deliveries` rows.
- `app/main.py` has no lifespan. `create_app()` refuses to start without `AUTH_SECRET_KEY`. The tests build the app with `create_app()` inside `httpx.ASGITransport`.
- `Stream._read` has the parsed `Raw` (with `raw.cpu` rows `cpu`, `cpu0`, `cpu1`…) and builds `Sample`. `Stream._got(sample)` publishes, buffers and sets `reachable`. `Stream._watch` writes `unreachable`.
- `StatusBook` keeps `(state, reason)` per server, but not `since`.
- `Supervisor.poll()` reads every `Server` row, then calls `status.retry()` and touches the heartbeat.
- Readings: `cpu.used_percent` (instance `""` for the whole server, `cpuN` per core; missing in the first sample after a connect), `mem.used_percent` (missing when `MemAvailable` is 0), `disk.used_percent` and `disk.inodes_used_percent` (instance = mount point), and `load.1m|5m|15m`.
- Security suites: `ANY_SIGNED_IN` in `test_permission_coverage.py`, `EXEMPT` in `test_audit_coverage.py`. Guards: `require_owner`, `require_group_visible(group=group_of_server)` (`app/inventory/deps.py`).
- `conftest.py`: `clean_auth` deletes users, servers and groups as the owner. `api` builds `create_app()` with a fake clock (`app.auth.clock.now`). `collector_sessions` gives collector-role sessions. `owner_session()` gives owner sessions.
- `httpx` is in the dev group only. `smtplib` is in the standard library.
- Frontend: `apiFetch` (`src/lib/api.ts`), `useRefresh` (15 s), `messageFor` (`src/lib/auth/messages.ts`), and `SettingsTabs` (`src/components/settings/settings-tabs.tsx`, two tabs). The Dashboard keeps a slot at `{/* The firing alerts go here with MITA-29. */}`. `FleetSummary` has five tiles. `withQuery` in `src/lib/servers.ts` is not exported. `components/ui` has no `switch` or `popover`. Tests mock `@/lib/api` and `@/hooks/use-refresh` with `vi.mock`.
- The stack set's fake server runs from `tools/fake-server/docker-compose.stack.yml` (also used by `make up STACK=dev|e2e`). `test_stack.py` reaches containers through `_compose_with_fake_server("exec", "-T", …)`. The fake server's `/` is `overlay`, which the collector counts.

## Decisions made in this plan (within the design)
- **Engine identity.** A firing alert is keyed `(rule_id, server_id, instance)`. The engine creates the alert's UUID when it fires, so a resolve can follow a fire that is still waiting to be written.
- **Rule changes.** An alert ends with `rule_changed` when the rule's snapshot (metric, comparison, threshold, duration, severity) differs from the alert's copy, or when the rule no longer applies to the server. It ends with `rule_disabled` when `enabled` is false, and with `rule_deleted` when the rule is gone (also at load, for an alert whose `rule_id` is null). Counting conditions are keyed by the rule's `revision`, so a new revision starts them again.
- **Interrupted samples.** When two samples of a server are more than 30 s apart (`GAP = 30.0`), that server's counting conditions start again.
- **Unreachable.** `StatusBook` also keeps `since`: from the row at load, and `datetime.now(UTC)` after a successful write. At each poll the book calls `engine.unreachable(server_id, since, now)` for each server whose known state is `unreachable`. The first sample resolves the alert.
- **Values.** For `unreachable` alerts, `value`, `last_value` and `peak_value` stay null. For `above` the peak is the maximum, for `below` the minimum.
- **Writes.** The collector writes with core `insert()` and `update()`, gives every value, and uses no `RETURNING`.
- **Email row.** `notification_email` has `id smallint` with `CHECK (id = 1)`, inserted by the migration with `enabled = false`.
- **Secrets.** `notify/crypto.py` derives the key with HKDF-SHA256 from `Settings.auth_key()`, with info `b"megooitadmin notification secrets"`. It seals with AES-256-GCM: a 12-byte nonce, then the ciphertext, with the row as associated data (`channel.id.bytes`, or `b"notification_email"`). A channel's secret is JSON text: `{"url": …}` or `{"bot_token": …, "chat_id": …}`.
- **Sinks.** `backend/tests/sinks.py` (standard library, asyncio) is an HTTP sink and a minimal SMTP sink. The sender tests use it in process. The stack and dev stacks run it as a `sink` service in `tools/fake-server/docker-compose.stack.yml` (`python:3.13-slim`, the file mounted read-only).
- **Telegram base URL.** `app.notify.transports.TELEGRAM_API = "https://api.telegram.org"`. Tests monkeypatch it.
- **Retry timetable.** `RETRY_DELAYS = (30, 120, 300, 900, 2400)` seconds after tries 1 to 5. `MAX_ATTEMPTS = 6`.
- **Error codes** (the `detail` of 4xx answers, and the `error` of a test result):
  - Rules: `rule_name_taken` (409), `unknown_group` (422), `unknown_server` (422), `bad_threshold` (422), `bad_scope` (422), `no_change` (409).
  - Channels: `channel_name_taken` (409), `too_many_channels` (409), `webhook_url_https` (422), `bad_url` (422), `bad_telegram_token` (422), `bad_chat_id` (422).
  - Email: `email_not_set_up` (409).
  - Transports: `connection_failed`, `timeout`, `tls_failed`, `auth_failed`, `recipients_refused`, `http_status`, `redirect_refused`, `undecryptable`.

## Shared contracts

### A. Migration `0011_alerts` (`backend/migrations/versions/0011_alerts.py`)

`alert_rules`:
- `id uuid` PK `alert_rules_pkey`.
- `name text NOT NULL`, with `alert_rules_name_check`: `char_length(name) BETWEEN 1 AND 80`.
- `metric text NOT NULL`, with `alert_rules_metric_check`: `metric IN ('cpu.used_percent','mem.used_percent','disk.used_percent','disk.inodes_used_percent','load.1m','load.5m','load.15m','unreachable')`.
- `comparison text NULL`, `threshold double precision NULL`, with `alert_rules_condition_check`:
  `(metric = 'unreachable' AND comparison IS NULL AND threshold IS NULL) OR (metric <> 'unreachable' AND comparison IS NOT NULL AND comparison IN ('above','below') AND threshold IS NOT NULL AND threshold >= 0 AND threshold <= CASE WHEN metric LIKE 'load.%' THEN 1000 ELSE 100 END)`.
- `duration_seconds integer NOT NULL`, with `alert_rules_duration_check`: `BETWEEN 0 AND 86400`.
- `severity text NOT NULL`, with `alert_rules_severity_check`: `IN ('warning','critical')`.
- `server_group_id uuid NULL`, FK `alert_rules_server_group_id_fkey` to `server_groups` ON DELETE CASCADE.
- `server_id uuid NULL`, FK `alert_rules_server_id_fkey` to `servers` ON DELETE CASCADE.
- `alert_rules_scope_check`: `num_nonnulls(server_group_id, server_id) <= 1`.
- `enabled boolean NOT NULL DEFAULT true`, `revision integer NOT NULL DEFAULT 1`.
- `suggested_playbook_id uuid NULL` (no FK).
- `created_at`, `updated_at timestamptz NOT NULL DEFAULT now()`.
- Indexes: unique `alert_rules_name_key` on `lower(name)`, `alert_rules_server_group_id_idx`, `alert_rules_server_id_idx`.
- Inserts the four starter rules (`gen_random_uuid()`):

  | name | metric | comparison | threshold | duration | severity |
  |---|---|---|---|---|---|
  | Filesystem almost full | disk.used_percent | above | 90 | 600 | critical |
  | Memory almost full | mem.used_percent | above | 90 | 600 | warning |
  | CPU busy | cpu.used_percent | above | 90 | 900 | warning |
  | Server unreachable | unreachable | NULL | NULL | 300 | critical |

`alerts`:
- `id uuid` PK.
- `server_id uuid NOT NULL`, FK to `servers` ON DELETE CASCADE.
- `rule_id uuid NULL`, FK to `alert_rules` ON DELETE SET NULL.
- `rule_name text NOT NULL`, `metric text NOT NULL`, `comparison text NULL`, `threshold double precision NULL`, `duration_seconds integer NOT NULL`, `severity text NOT NULL` (with the same severity check).
- `instance text NOT NULL`.
- `state text NOT NULL`, with `alerts_state_check`: `IN ('firing','resolved','ended')`.
- `end_reason text NULL`, with `alerts_end_reason_check`: `(state = 'ended') = (end_reason IS NOT NULL) AND (end_reason IS NULL OR end_reason IN ('rule_changed','rule_disabled','rule_deleted','server_not_monitored'))`.
- `fired_at timestamptz NOT NULL`, `resolved_at timestamptz NULL`, with `alerts_resolved_check`: `(state = 'firing') = (resolved_at IS NULL)`.
- `value`, `last_value`, `peak_value double precision NULL`.
- Indexes:
  - unique partial `alerts_one_firing_key` on `(rule_id, server_id, instance) WHERE state = 'firing'`;
  - `alerts_server_id_fired_at_idx` on `(server_id, fired_at)`;
  - `alerts_resolved_at_idx` on `(resolved_at)`.

`alert_events`:
- `id uuid` PK, `alert_id uuid NOT NULL` FK to `alerts` ON DELETE CASCADE.
- `kind text NOT NULL`, with `alert_events_kind_check`: `IN ('fired','resolved','ended')`.
- `at timestamptz NOT NULL`, `dispatched_at timestamptz NULL`.
- Indexes: `alert_events_at_idx` on `(at)`, and partial `alert_events_undispatched_idx` on `(at) WHERE dispatched_at IS NULL`.

`notification_channels`:
- `id uuid` PK, `name text NOT NULL` (check 1 to 80 characters, unique `notification_channels_name_key` on `lower(name)`).
- `kind text NOT NULL`, with a check `IN ('webhook_json','webhook_slack','telegram')`.
- `min_severity text NOT NULL DEFAULT 'warning'`, with a check `IN ('warning','critical')`.
- `enabled boolean NOT NULL DEFAULT true`, `secret bytea NOT NULL`, `hint text NOT NULL`.
- `created_at`, `updated_at timestamptz NOT NULL DEFAULT now()`.

`notification_email`:
- `id smallint` PK, with a check `id = 1`.
- `enabled boolean NOT NULL DEFAULT false`, `host text NULL`.
- `port integer NOT NULL DEFAULT 587`, with a check `BETWEEN 1 AND 65535`.
- `security text NOT NULL DEFAULT 'starttls'`, with a check `IN ('starttls','tls','none')`.
- `username text NULL`, `password bytea NULL`.
- `from_name text NOT NULL DEFAULT 'MegooITAdmin'`, `from_address text NULL`.
- `extra_addresses text[] NOT NULL DEFAULT '{}'`, with a check `cardinality(extra_addresses) <= 20`.
- `min_severity text NOT NULL DEFAULT 'warning'`, with the severity check.
- `notification_email_ready_check`: `NOT enabled OR (host IS NOT NULL AND from_address IS NOT NULL)`.
- `updated_at timestamptz NOT NULL DEFAULT now()`.
- The migration inserts `(id) VALUES (1)`.

`notification_deliveries`:
- `id uuid` PK, `event_id uuid NOT NULL` FK to `alert_events` ON DELETE CASCADE.
- `channel_id uuid NULL` FK to `notification_channels` ON DELETE CASCADE (null means email).
- `state text NOT NULL`, with a check `IN ('pending','delivered','failed')`.
- `attempts smallint NOT NULL DEFAULT 0`, `next_attempt_at timestamptz NOT NULL`, `last_error text NULL`, `delivered_at timestamptz NULL`.
- `created_at timestamptz NOT NULL DEFAULT now()`.
- Unique `notification_deliveries_event_channel_key` on `(event_id, channel_id)` NULLS NOT DISTINCT (`postgresql_nulls_not_distinct=True`).
- Indexes: partial `notification_deliveries_due_idx` on `(next_attempt_at) WHERE state = 'pending'`, and `notification_deliveries_channel_id_idx`.

`users.alerts_seen_at timestamptz NULL`.

Grants:

| Relation | `megooitadmin_api` | `megooitadmin_collector` |
|---|---|---|
| `alert_rules` | `SELECT, INSERT, UPDATE, DELETE` | `SELECT` |
| `alerts` | `SELECT` | `SELECT, INSERT, UPDATE` |
| `alert_events` | `SELECT`, and `UPDATE (dispatched_at)` | `INSERT` |
| `notification_channels` | `SELECT, INSERT, UPDATE, DELETE` | none |
| `notification_email` | `SELECT, UPDATE` | none |
| `notification_deliveries` | `SELECT, INSERT, UPDATE, DELETE` | none |

`downgrade()` drops the six tables in reverse order, then the `users` column.

Models:
- `app/alerts/models.py`: `AlertRule`, `Alert`, `AlertEvent`.
- `app/notify/models.py`: `NotificationChannel`, `NotificationEmail`, `NotificationDelivery`.
- `User.alerts_seen_at` in `app/auth/models.py`.
- The constraint and index names above go into the models' `__table_args__`. Python-side `default=uuid.uuid4` for ids. Both packages are imported in `app/models.py`.

### B. Catalog and engine

```python
# app/alerts/catalog.py
@dataclass(frozen=True)
class MetricSpec:
    label: str            # "Space used"
    unit: Literal["%", "per core", None]
    maximum: float | None # 100, 1000, None for unreachable
    per_instance: bool    # True for disk.*: one alert per mount point
    per_core: bool        # True for load.*: value / cores
CATALOG: dict[str, MetricSpec] = {
  "cpu.used_percent": MetricSpec("CPU used", "%", 100, False, False),
  "mem.used_percent": MetricSpec("Memory used", "%", 100, False, False),
  "disk.used_percent": MetricSpec("Space used", "%", 100, True, False),
  "disk.inodes_used_percent": MetricSpec("Inodes used", "%", 100, True, False),
  "load.1m": MetricSpec("Load per core (1 min)", "per core", 1000, False, True),
  "load.5m": MetricSpec("Load per core (5 min)", "per core", 1000, False, True),
  "load.15m": MetricSpec("Load per core (15 min)", "per core", 1000, False, True),
  "unreachable": MetricSpec("Unreachable", None, None, False, False),
}
METRICS = tuple(CATALOG); SEVERITIES = ("warning", "critical"); COMPARISONS = ("above", "below")
END_REASONS = ("rule_changed", "rule_disabled", "rule_deleted", "server_not_monitored")
```

```python
# app/collector/alerts/engine.py  (pure: no I/O, no clock of its own)
GAP = 30.0
@dataclass(frozen=True)
class Rule:
    id: UUID; name: str; metric: str; comparison: str | None; threshold: float | None
    duration_seconds: int; severity: str; server_group_id: UUID | None; server_id: UUID | None
    enabled: bool; revision: int
    def applies_to(self, server: "ServerInfo") -> bool
    def snapshot(self) -> tuple  # (metric, comparison, threshold, duration_seconds, severity)
@dataclass(frozen=True)
class ServerInfo: id: UUID; group_id: UUID; name: str
@dataclass
class Firing:
    alert_id: UUID; rule_id: UUID | None; server_id: UUID; instance: str
    snapshot: tuple; rule_name: str; fired_at: datetime
    value: float | None; last_value: float | None; peak_value: float | None
@dataclass(frozen=True)
class Transition:
    kind: Literal["fired", "resolved", "ended"]; alert_id: UUID; server: ServerInfo; instance: str; at: datetime
    rule: Rule | None            # set for "fired" (the snapshot is copied from it)
    firing: Firing               # the alert as it is after the transition
    end_reason: str | None = None
class Engine:
    def load_firing(self, firing: Iterable[Firing]) -> None
    def set_servers(self, servers: Iterable[ServerInfo], monitored: Collection[UUID], at: datetime) -> list[Transition]
    def set_rules(self, rules: Iterable[Rule], at: datetime) -> list[Transition]
    def observe(self, server_id: UUID, readings: Sequence[Reading], cores: int, at: datetime) -> list[Transition]
    def unreachable(self, server_id: UUID, since: datetime, at: datetime) -> list[Transition]
    def firing(self) -> list[Firing]
```
How the engine decides:
- `observe` skips a server it does not know (not in `set_servers`). It drops that server's counting conditions when `at` is more than `GAP` seconds after its previous sample. It resolves every firing `unreachable` alert of the server (value null).
- For each enabled rule that applies (not `unreachable`), and for each value: whole-server metrics use instance `""`, per-instance metrics use every reading of that metric, and per-core metrics use `value / max(cores, 1)`.
  - The condition holds for `above` when `v > threshold`, and for `below` when `v < threshold`.
  - When it holds and nothing is firing for that key, counting starts at `at` (kept with the rule's revision). When `at - start >= duration_seconds`, the alert fires with `value = v`.
  - When it holds and the alert is firing, `last_value` and `peak_value` are updated.
  - When it does not hold, counting stops. A firing alert resolves with `last_value = v`.
  - A missing whole-server value changes nothing. A firing per-instance alert whose instance is missing from the sample resolves, and its values stay as they were.
- `unreachable(server_id, since, at)`: for each enabled `unreachable` rule that applies, the alert fires once `at - since >= duration_seconds`, if it is not firing already.
- `set_rules`: ends firing alerts.
  - The rule is missing, or the alert's `rule_id` is null: `rule_deleted`.
  - `enabled` is false: `rule_disabled`.
  - The snapshot differs, or the rule no longer applies to the server: `rule_changed`.
  - It drops counting conditions whose revision is not the rule's current one. A rename ends nothing, and later fires copy the new name.
- `set_servers`: forgets servers that are gone, with their alerts (the database cascade removes the rows). It ends firing alerts of servers that are known but not in `monitored` (`server_not_monitored`), and drops their counting conditions.

### C. Book (`app/collector/alerts/book.py`)
```python
class AlertBook:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], engine: Engine | None = None,
                 *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None
    async def load(self) -> None                     # firing rows -> engine.load_firing; raises on a database error
    async def observe(self, sample: Sample, cores: int) -> None   # never raises
    async def poll(self, servers: Sequence[Server], status: StatusBook) -> None
        # reads every alert_rules row (raises on a database error), engine.set_servers (monitored = refusal_of(row) is None
        # and status.known(id) state != "not_monitored"), engine.set_rules, engine.unreachable for each server whose
        # known state is "unreachable", writes those transitions, then the firing values not written for 60 s, then retries
    @property
    def pending(self) -> int
```
Each transition is one transaction, with `record()` last:
- `fired`: `insert(Alert)` with `state='firing'`, the rule's copy and `value = last_value = peak_value`, plus `insert(AlertEvent)`.
- `resolved` / `ended`: `update(Alert).where(id, state == 'firing')` sets `state`, `resolved_at = at`, `end_reason`, `last_value` and `peak_value`, plus `insert(AlertEvent)`.
- The audit event is built by `alert_event(transition)` in `app/alerts/actions.py`: `Event(action=ALERT_FIRED|ALERT_RESOLVED|ALERT_ENDED, actor=Actor.system("collector"), target=Target(type="alert", id=str(alert_id), name=rule_name), context={"server_id": …, "server_group_id": …}, result_detail={"server": name, "rule_id": str|None, "metric", "instance", "severity", "value": text|None, "threshold": text|None, "end_reason": …})`. Numbers go in as `format(v, ".2f")` text.

A write the database refused (`SQLAlchemyError`, `OSError`, `AuditChainBusy`) stays in an ordered `_pending` list, with its real times, and is retried at the next poll. A unique violation (`23505`) or a foreign-key violation (`23503`) drops it.

### D. Sentences (identical in `app/notify/messages.py` and `frontend/src/lib/alerts.ts`)
- `duration_text(s)`: `0` gives `""`. A multiple of 3600 gives `"N h"`. 3600 or more gives `"N h M min"`. Otherwise `"N min"` (rounded down to minutes, at least 1).
- `number(x)`: Python `format(x, "g")`, JS `String(x)` (90 → `90`, 92.5 → `92.5`).
- `rule_sentence`: for `unreachable`, `"Unreachable for {d}"`, or `"Unreachable"` when the duration is 0. Otherwise `"{label} {comparison} {number(threshold)}{unit} for {d}"`, without ` for {d}` when the duration is 0. The unit is `%` glued to the number, or ` per core`. Example: `Space used above 90% for 10 min`.
- `value_text`: percentages `f"{v:.1f}%"`, load `f"{v:.2f} per core"`.
- `headline(alert)`, for `fired`, with the value, and for `resolved` with `last_value`:

  | metric | headline |
  |---|---|
  | cpu | `{server}: CPU is {pct} busy` |
  | mem | `{server}: memory is {pct} used` |
  | disk | `{server}: {instance} is {pct} full` |
  | inodes | `{server}: {instance} has {pct} of its inodes used` |
  | load | `{server}: load is {value} ({window})`, where the window is `1 min`, `5 min` or `15 min` |
  | unreachable | `{server} is unreachable` |

- Event sentence:
  - fired: `{headline}`.
  - resolved: `Resolved: {headline}`, or `Resolved: {server} is reachable again` for unreachable.
  - ended: `Ended: {server}: {rule_name}, {reason}`. The reasons are: `rule_changed` "the rule was changed", `rule_disabled` "the rule was switched off", `rule_deleted` "the rule was deleted", `server_not_monitored` "the server is no longer monitored".
- Severity word: `Warning` or `Critical`.
- Email subject: `[{Severity}] {event sentence}`. The body is the sentence, then a blank line, then `Rule: {rule_name}: {rule_sentence}`, `Server: {server} ({group})`, `Fired: {fired_at ISO}`, and `Resolved: {resolved_at ISO}` when set.
- Slack and Telegram text: `{Severity}: {event sentence}. {rule_sentence}.`
- Generic JSON: `{"version": 1, "event": kind, "text": <slack text>, "alert": {id, severity, rule_name, metric, comparison, threshold, duration_seconds, instance, value, fired_at, resolved_at, end_reason}, "server": {id, name, group}}`. Times are ISO 8601; `value` is the fired value, or `last_value` when resolved.
- Test message: `MegooITAdmin test: this channel works.`

### E. API shapes (`app/alerts/schemas.py`, `app/notify/schemas.py`)
- `AlertOut`: `id, server_id, server_name, group_id, group_name, rule_id, rule_name, metric, comparison, threshold, duration_seconds, severity, instance, state, end_reason, fired_at, resolved_at, value, last_value, peak_value`.
- `AlertEventOut`: `id, kind, at, alert: AlertOut`. `AlertEventsOut`: `unseen: int, firing: int, events: list[AlertEventOut]`.
- `AlertRuleIn`:
  - `name` (stripped, 1 to 80 characters), `metric: Literal[METRICS]`, `comparison: Literal["above","below"] | None = None`, `threshold: float | None = None` (finite), `duration_seconds: int` (0 to 86400), `severity`.
  - `server_group_id: UUID | None = None`, `server_id: UUID | None = None`, `enabled: bool = True`.
  - `AlertRulePatch` has the same fields, all optional (`model_fields_set`).
- `AlertRuleOut`: the rule's fields, plus `server_group_name, server_name, revision, suggested_playbook_id, firing_count, created_at, updated_at`.
- `EmailIn`:
  - `enabled, host, port, security, username`;
  - `password: str | None` (omitted or null keeps the saved one, `""` removes it, anything else replaces it);
  - `from_name, from_address` (email), `extra_addresses: list[EmailStr-like]` (up to 20, lowercased, deduplicated), `min_severity`.
- `EmailOut`: the same fields without `password`, plus `password_set: bool` and `last_delivery: DeliveryOut | None`.
- `ChannelIn`:
  - `name, kind, min_severity = "warning", enabled = True`;
  - `url: str | None` (webhooks), `bot_token: str | None`, `chat_id: str | None` (telegram).
  - `ChannelPatch` has every field optional. A secret field sent replaces the secret.
- `ChannelOut`: `id, name, kind, min_severity, enabled, hint, created_at, updated_at, last_delivery: DeliveryOut | None`.
- `DeliveryOut`: `state, at, error`. `at` is `delivered_at`, or `next_attempt_at` while pending, or the last try's time when failed.
- `TestResultOut`: `ok: bool, error: str | None`.

### F. Sender (`app/notify/sender.py`)
```python
RETRY_DELAYS = (30, 120, 300, 900, 2400); MAX_ATTEMPTS = 6; EVERY = 5.0; TOO_OLD = timedelta(hours=1)
KEEP = timedelta(days=30); BATCH = 50
class Sender:
    def __init__(self, sessions, *, settings: Settings | None = None, clock=lambda: datetime.now(UTC)) -> None
    async def dispatch(self) -> int      # claims undispatched events FOR UPDATE SKIP LOCKED; one delivery per enabled
                                         # matching channel and for email if enabled+matching (INSERT … ON CONFLICT DO
                                         # NOTHING, next_attempt_at=now); events older than TOO_OLD get none; sets dispatched_at
    async def send_due(self) -> int      # claims due pending deliveries FOR UPDATE SKIP LOCKED, one transaction each, sends
    async def prune(self) -> int         # deletes deliveries created before now - KEEP
    async def run(self) -> None          # loop: dispatch, send_due, prune (once an hour); any exception: log, sleep EVERY
async def email_recipients(db, server_group_id) -> list[str]
    # owners + admins of the group (role_grants.role='admin'), disabled_at IS NULL, plus extra_addresses; lowercased, sorted, unique
```
Severity matching: `min_severity == "warning"`, or the alert is `critical`. A failed try sets `attempts += 1` and `last_error = code`. Then the delivery becomes `failed` when `attempts == MAX_ATTEMPTS`, or `next_attempt_at = now + RETRY_DELAYS[attempts-1]` otherwise.

### G. Frontend `src/lib/alerts.ts`
It exports:
- the types `Severity`, `AlertMetric`, `Comparison`, `AlertState`, `EndReason`, `Alert`, `AlertEvent`, `AlertEvents`, `AlertRule`, `AlertRuleInput`, `EmailSettings`, `ChannelKind`, `Channel`, `Delivery` (the fields of E);
- `METRICS: Record<AlertMetric, {label, unit: "%" | "per core" | null, max: number | null, perInstance: boolean}>`;
- `durationText`, `ruleSentence`, `valueText`, `alertHeadline`, `eventSentence`, `SEVERITY_LABEL`, `END_REASON_TEXT` (exactly D);
- `alertsPath(state: "firing" | "closed", filters: ServerFilters, before?: string)` (uses `withQuery`, now exported from `lib/servers.ts`, with `group_id` and `tag`);
- `firingByServer(alerts): Record<string, number>`.

## File map

| File | Change | Responsibility |
|---|---|---|
| `backend/app/core/config.py` | modify | `notification_sender: bool = True`, `webhook_allow_http: bool = False` |
| `backend/pyproject.toml`, `backend/uv.lock` | modify | `httpx` becomes a runtime dependency |
| `backend/app/notify/__init__.py`, `crypto.py` | create | HKDF key, seal and unseal |
| `backend/migrations/versions/0011_alerts.py` | create | Contract A |
| `backend/app/alerts/__init__.py`, `models.py`, `catalog.py`, `actions.py` | create | Tables, catalog, audit action names and `alert_event()` |
| `backend/app/notify/models.py` | create | Channel, email and delivery tables |
| `backend/app/auth/models.py`, `backend/app/models.py` | modify | `alerts_seen_at`; imports |
| `backend/app/collector/alerts/__init__.py`, `engine.py`, `book.py` | create | Contracts B and C |
| `backend/app/collector/state.py`, `compute.py`, `stream.py`, `supervisor.py`, `__main__.py` | modify | `since`, `cores()`, the engine wired in |
| `backend/app/alerts/schemas.py`, `service.py`, `router.py` | create | Rules CRUD, alert lists, bell |
| `backend/app/inventory/service.py`, `servers.py` | modify | Rules deleted with their group or server |
| `backend/app/notify/messages.py`, `transports.py`, `sender.py`, `schemas.py`, `service.py`, `router.py`, `actions.py` | create | Contracts D, E and F |
| `backend/app/main.py` | modify | Routers; a lifespan that runs `Sender.run()` |
| `backend/tests/conftest.py` | modify | `NOTIFICATION_SENDER=false`, fixture `clean_alerts` |
| `backend/tests/alerts_helpers.py`, `backend/tests/sinks.py` | create | Rule and alert helpers; HTTP and SMTP sinks |
| `backend/tests/alerts/*.py`, `backend/tests/notify/*.py`, `backend/tests/collector/test_alert_*.py` | create | Tests |
| `backend/tests/security/test_db_privileges.py`, `test_permission_coverage.py`, `test_audit_coverage.py`, `backend/tests/test_migrations.py`, `test_settings.py`, `test_stack.py`, `inventory/test_group_delete.py`, `inventory/test_server_remove.py` | modify | Tests |
| `docker-compose.yml`, `tools/stacks/dev.env`, `tools/stacks/e2e.env`, `megoocolab.toml`, `tools/fake-server/docker-compose.stack.yml` | modify | `WEBHOOK_ALLOW_HTTP`; the `sink` service |
| `README.md`, `.env.example` | modify | Docs |
| `frontend/src/components/ui/switch.tsx`, `popover.tsx` | create | shadcn |
| `frontend/src/lib/alerts.ts`, `src/lib/__tests__/alerts.test.ts`, `src/lib/servers.ts`, `src/lib/auth/messages.ts` | create/modify | Contract G; error codes |
| `frontend/src/components/alerts/severity-badge.tsx`, `alert-state-badge.tsx`, `alert-rows.tsx`, `alerts-card.tsx`, `server-alert-banner.tsx`, `server-alerts-tab.tsx` (+ `__tests__`) | create | Shared pieces |
| `frontend/src/components/dashboard/dashboard-page.tsx`, `fleet-summary.tsx`, `server-card.tsx`, `server-rows.tsx` (+ tests) | modify | Tile, card, marks |
| `frontend/src/components/shell/alert-bell.tsx`, `site-header.tsx` (+ tests) | create/modify | The bell |
| `frontend/src/components/servers/server-page.tsx` (+ test) | modify | Banner and Alerts tab |
| `frontend/src/components/settings/settings-tabs.tsx`, `alert-rules-page.tsx`, `alert-rule-dialog.tsx`, `delete-rule-dialog.tsx`, `notifications-page.tsx`, `email-dialog.tsx`, `channel-dialog.tsx`, `delete-channel-dialog.tsx` (+ tests) | create/modify | Settings screens |
| `frontend/src/app/(app)/settings/alert-rules/page.tsx`, `notifications/page.tsx`, `settings/layout.tsx` | create/modify | Routes; the layout's text |

**Commands.** Backend commands run from `backend/`, frontend commands from `frontend/`:
- **BT** `<paths>` = `megoocolab-runner services run test -- uv run pytest <paths>` (no paths: the whole suite)
- **MIG** = `megoocolab-runner services run migrate -- sh -c 'uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head'`
- **STK** = `megoocolab-runner services run stack -- uv run pytest -m stack`
- **FE** `<path>` = `npx vitest run <path>`; **FEALL** = `npx tsc --noEmit && npx eslint <changed files> && npm test`

Every backend step ends with the full **BT** green, and every frontend step with **FEALL** green. Commit subjects are `type(area): sentence`, with a body that says why, ending in `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not run Prettier; format by hand to 120 columns.

---

## Step 1 — Settings, httpx at runtime, and the notification secret box
**Files:** `backend/app/core/config.py`, `backend/pyproject.toml`, `backend/uv.lock`, `backend/app/notify/__init__.py`, `backend/app/notify/crypto.py`, `backend/tests/test_settings.py`, `backend/tests/notify/test_notify_crypto.py`, `backend/tests/conftest.py`.

Write these tests first:
- `test_settings.py::test_the_notification_settings_have_their_defaults`: with `NOTIFICATION_SENDER` and `WEBHOOK_ALLOW_HTTP` deleted, `Settings(database_url=URL)` gives `notification_sender is True` and `webhook_allow_http is False`.
- `tests/notify/test_notify_crypto.py`:
  - `test_a_secret_round_trips`;
  - `test_a_blob_moved_to_another_row_does_not_open` (raises `SecretUndecryptable`);
  - `test_the_key_is_not_the_auth_key` (the derived key differs from `get_settings().auth_key()`);
  - `test_a_short_blob_does_not_open`.

Run **BT** `tests/test_settings.py tests/notify`. **Expected:** they fail (attribute and import errors).

Implementation:
- `config.py`: add `notification_sender: bool = True` (comment: the backend's sender task; the tests turn it off) and `webhook_allow_http: bool = False` (comment: dev, e2e and stack stacks only).
- `pyproject.toml`: move `httpx>=0.28.1` to `dependencies`, then run `uv lock`.
- `notify/crypto.py`: `notification_key() -> bytes` (HKDF-SHA256 from `cryptography.hazmat.primitives.kdf.hkdf`, `length=32`, `salt=None`, `info=b"megooitadmin notification secrets"`, over `get_settings().auth_key()`); `seal(plain: str, bound_to: bytes) -> bytes`; `unseal(blob: bytes, bound_to: bytes) -> str`. Reuse `SecretUndecryptable` from `app.auth.crypto`. `EMAIL_ROW = b"notification_email"`.
- `conftest.py` `pytest_configure`: `os.environ["NOTIFICATION_SENDER"] = "false"`.

Run **BT** `tests/test_settings.py tests/notify`, then the full **BT**. **Expected:** pass.

**Commit:** `feat(notify): settings for the sender and a key of their own for channel secrets`.

## Step 2 — Migration 0011: rules, alerts, events, channels, deliveries
**Files:** `backend/migrations/versions/0011_alerts.py`, `backend/app/alerts/__init__.py`, `backend/app/alerts/models.py`, `backend/app/notify/models.py`, `backend/app/auth/models.py`, `backend/app/models.py`, `backend/tests/test_migrations.py`, `backend/tests/security/test_db_privileges.py`, `backend/tests/conftest.py`.

Write these tests first:
- `test_migrations.py::test_0011_goes_down_and_up_again`: down to `0010` gives `to_regclass` null for the six tables, and back to head gives them all.
- `test_0011_inserts_the_four_starter_rules`: the names, metrics and durations of contract A, all enabled and global.
- `test_the_database_refuses_a_threshold_on_unreachable_and_two_scopes`: `IntegrityError` matching `alert_rules_condition_check` and `alert_rules_scope_check`.
- `test_one_firing_alert_per_rule_server_and_instance`: a second firing row raises `alerts_one_firing_key`; a resolved one is accepted.
- `test_db_privileges.py`:
  - add the six tables to `API_GRANTS` and the three alert tables to `COLLECTOR_GRANTS` (contract A);
  - add `API_COLUMN_GRANTS = {("alert_events", "dispatched_at", "UPDATE")}` and replace `assert await _rows(COLUMN_GRANTS_SQL) == []` with `set(...) == API_COLUMN_GRANTS`;
  - add `test_the_collector_cannot_read_the_channel_tables`, which runs `SELECT` on each `notification_*` table under `SET LOCAL ROLE megooitadmin_collector` and expects 42501.

Run **BT** `tests/test_migrations.py tests/security/test_db_privileges.py`. **Expected:** they fail.

Implementation:
- The migration as in contract A.
- The models with the same names, so that `test_the_models_match_the_migrations` (alembic check) passes: `Double` for thresholds and values, `ARRAY(Text)` for `extra_addresses`, `LargeBinary` for secrets.
- `User.alerts_seen_at: Mapped[datetime | None]`.
- `app/models.py` imports `app.alerts.models` and `app.notify.models`.
- `conftest.py` gets the fixture `clean_alerts(clean_auth)`. As the owner, it deletes `notification_deliveries`, `notification_channels`, `alert_events`, `alerts` and `alert_rules`, then resets `notification_email` with `UPDATE … SET enabled=false, host=NULL, port=587, security='starttls', username=NULL, password=NULL, from_name='MegooITAdmin', from_address=NULL, extra_addresses='{}', min_severity='warning'`.

Run **MIG**, **BT** on the two files, then the full **BT**. **Expected:** pass.

**Commit:** `feat(alerts): tables for alert rules, alerts and notification channels`.

## Step 3 — The engine: metric rules fire after their duration and resolve
**Files:** `backend/app/alerts/catalog.py`, `backend/app/collector/alerts/__init__.py`, `backend/app/collector/alerts/engine.py`, `backend/tests/collector/test_alert_engine.py`.

Write unit tests first, with fixed datetimes (`T0 = datetime(2026,11,26,12,tzinfo=UTC)`) and helpers `rule(**kw) -> Rule` and `readings(**values)`:
- `test_fires_only_after_the_full_duration`;
- `test_a_single_good_sample_starts_the_count_again`;
- `test_duration_0_fires_at_the_first_sample`;
- `test_below_fires_under_the_threshold`;
- `test_each_filesystem_is_its_own_alert`;
- `test_load_is_compared_per_core`;
- `test_a_missing_whole_server_value_changes_nothing`;
- `test_a_vanished_filesystem_resolves_its_alert`;
- `test_resolve_carries_the_last_value_and_the_peak`;
- `test_a_gap_of_more_than_30_s_starts_the_count_again`;
- `test_a_disabled_rule_is_not_evaluated`;
- `test_scope_by_all_group_and_server`;
- `test_an_unknown_server_is_ignored`.

Run **BT** `tests/collector/test_alert_engine.py`. **Expected:** ImportError.

Implementation: the catalog, and `Rule`, `ServerInfo`, `Firing`, `Transition`, `Engine.set_servers` (record only, for now), `Engine.set_rules` (store only), `Engine.observe` and `Engine.firing`, exactly as contract B. Counting conditions are kept in `dict[(rule_id, server_id, instance), (revision, start)]`, and firing alerts in `dict[(rule_id, server_id, instance), Firing]`.

Run the same command. **Expected:** pass. Then the full **BT**.

**Commit:** `feat(collector): an alert engine that checks each sample against the rules`.

## Step 4 — The engine: unreachable, rule changes, servers that stop being monitored, firing alerts loaded
**Files:** `backend/app/collector/alerts/engine.py`, `backend/tests/collector/test_alert_engine.py`.

Write these tests first:
- `test_unreachable_fires_after_its_duration_from_the_status_time`;
- `test_a_sample_resolves_an_unreachable_alert`;
- `test_a_changed_rule_ends_its_alert` (threshold changed, `end_reason == "rule_changed"`);
- `test_a_rule_scoped_away_from_the_server_ends_its_alert`;
- `test_a_disabled_rule_ends_its_alert`;
- `test_a_deleted_rule_ends_its_alert`;
- `test_a_renamed_rule_ends_nothing_and_later_fires_carry_the_new_name`;
- `test_a_new_revision_starts_counting_again`;
- `test_a_server_not_monitored_ends_its_alerts`;
- `test_a_removed_server_is_forgotten_without_transitions`;
- `test_loaded_firing_alerts_resolve_normally`;
- `test_a_loaded_alert_without_a_rule_ends_as_deleted`.

Run **BT** `tests/collector/test_alert_engine.py`. **Expected:** the new tests fail.

Implementation: `unreachable`, `load_firing`, and the ending logic of `set_rules` and `set_servers` (contract B).

Run it again. **Expected:** pass. Then the full **BT**.

**Commit:** `feat(collector): alerts end when their rule changes and unreachable rules fire`.

## Step 5 — The alert book writes transitions with their events and audit events
**Files:** `backend/app/alerts/actions.py`, `backend/app/collector/alerts/book.py`, `backend/app/collector/state.py`, `backend/app/collector/compute.py`, `backend/tests/alerts_helpers.py`, `backend/tests/collector/test_alert_book.py`, `backend/tests/collector/test_collector_state.py`, `backend/tests/collector/test_collector_compute.py`.

`alerts_helpers.py` gets:
- `async def make_rule(**fields) -> AlertRule` (as the owner; defaults `name="Test rule"`, `metric="disk.used_percent"`, `comparison="above"`, `threshold=50`, `duration_seconds=0`, `severity="critical"`);
- `async def alerts_of(server_id) -> list[Alert]`;
- `async def events_of(alert_id) -> list[AlertEvent]`.

Write these tests first (with `collector_sessions`, `clean_alerts`, a server from `auth_helpers.make_server`):
- `test_a_fire_writes_the_alert_its_event_and_alert_fired_by_the_collector` (`AuditEvent` actor_type `system`, name `collector`, target type `alert`);
- `test_a_resolve_updates_the_row_and_records_alert_resolved`;
- `test_a_refused_write_is_retried_at_the_next_poll` (monkeypatch the sessionmaker to raise `OperationalError` once, or use a `FailingSessions` wrapper);
- `test_a_restart_loads_the_firing_alerts`;
- `test_a_duplicate_firing_row_is_dropped`;
- `test_poll_reads_the_rules_and_ends_alerts_of_a_disabled_rule`;
- `test_the_firing_values_are_written_at_most_once_a_minute` (fake clock);
- `StatusBook`: `test_since_comes_from_the_row_and_from_each_write`;
- `compute.cores`: `test_cores_counts_the_cpu_rows_but_the_total`.

Run **BT** on these files. **Expected:** they fail.

Implementation:
- `actions.py`: `ALERT_FIRED = "alert.fired"`, `ALERT_RESOLVED = "alert.resolved"`, `ALERT_ENDED = "alert.ended"`, plus `ALERT_RULE_CREATED`, `ALERT_RULE_CHANGED`, `ALERT_RULE_DELETED` (`alert_rule.created`, `.changed`, `.deleted`), and `alert_event(transition) -> Event` (contract C).
- `book.py` as contract C.
- `StatusBook`: `_since: dict[UUID, datetime]`, filled by `load()` from `ServerStatus.since` and by `_write()` with `datetime.now(UTC)`. Add `since(server_id) -> datetime | None`, and clear the entry in `forget`.
- `compute.cores(raw) -> int`: `max(1, sum(1 for row in raw.cpu if row[0] != "cpu"))`.

Run **BT** on these files, then the full **BT**. **Expected:** pass.

**Commit:** `feat(collector): the collector writes alerts, their events and their audit events`.

## Step 6 — The collector evaluates rules on live samples
**Files:** `backend/app/collector/stream.py`, `backend/app/collector/supervisor.py`, `backend/app/collector/__main__.py`, `backend/tests/collector/test_alert_collector.py`, `backend/tests/collector/test_collector_main.py`.

Write these tests first, with `fake_server`, `collector_sessions` and `clean_alerts` (delete every rule first, then add the test's own), using `collector_helpers` (`pinned_server`, `FAST`, `eventually`):
- `test_a_low_threshold_rule_fires_from_real_samples_and_resolves`:
  - add a rule `disk.used_percent below 101` for the server, duration 0;
  - run a `Supervisor` with `alerts=AlertBook(sessions)`, `poll_every=0.5`;
  - wait for a firing alert on `/`;
  - change the threshold with `UPDATE` (the revision goes up) and wait for `ended` with `rule_changed`;
  - add `cpu.used_percent above 101` and assert that it never fires.
- `test_a_paused_server_fires_the_unreachable_rule_and_a_sample_resolves_it`: an `unreachable` rule with duration 0; `fake_server.pause()`, wait for firing; `unpause()`, wait for resolved.
- `test_main_waits_for_the_database_and_loads_firing_alerts` (extend the existing `serve` test pattern).

Run **BT** `tests/collector/test_alert_collector.py`. **Expected:** they fail.

Implementation:
- `Stream.__init__(…, alerts: AlertBook | None = None)`. In `_read`, call `await self._got(sample, compute.cores(raw))`. In `_got`, call `await self.alerts.observe(sample, cores)` after `writer.add`, when `alerts` is set.
- `Supervisor(…, alerts: AlertBook | None = None)` passes it to every `Stream`. In `poll()`, after `status.retry()`, it calls `await self.alerts.poll(rows, self.status)`.
- `__main__.serve`: builds `alerts = AlertBook(SessionLocal)`, and calls `await alerts.load()` inside the same database-wait loop as `status.load()`.

Run it again. **Expected:** pass. Then the full **BT**.

**Commit:** `feat(collector): rules are checked on every sample and every poll`.

## Step 7 — The Owner's alert rules API
**Files:** `backend/app/alerts/schemas.py`, `backend/app/alerts/service.py`, `backend/app/alerts/router.py`, `backend/app/main.py`, `backend/tests/alerts/test_alert_rules_api.py`.

Write these tests first (`api`, `clock`, `clean_alerts`, `auth_helpers.signed_in`):
- `test_the_owner_lists_the_starter_set_with_firing_counts`: re-insert the four starter rules in the test through a helper `starter_rules()` in `alerts_helpers.py` (the `clean_alerts` fixture removes them).
- `test_create_validates_per_metric`, parametrized:
  - `unreachable` with a threshold gives `bad_threshold`;
  - a percentage above 100 gives `bad_threshold`;
  - load above 1000 gives `bad_threshold`;
  - a missing comparison gives `bad_threshold`;
  - both scopes give `bad_scope`;
  - an unknown group gives `unknown_group`;
  - an unknown server gives `unknown_server`.
- `test_a_name_is_unique_without_regard_to_case` (409 `rule_name_taken`).
- `test_patch_raises_the_revision_only_for_the_condition_scope_or_severity`, and `no_change` gives 409.
- `test_each_change_is_audited_with_the_threshold_as_text`: `alert_rule.created`, `.changed` and `.deleted`, target type `alert_rule`, and a `change` holding `"threshold": "90"`.
- `test_others_get_403_and_access_denied` (an admin, an auditor).

Run **BT** `tests/alerts/test_alert_rules_api.py`. **Expected:** 404s.

Implementation:
- `router = APIRouter(prefix="/alert-rules")`, with `GET ""`, `POST ""`, `PATCH /{rule_id}` and `DELETE /{rule_id}` (204), each with `Depends(require_owner)` and `audited(...)`.
- The service follows `inventory/service.py`: `_fields(rule)` holds the threshold as `None` or `format(t, "g")`; it uses `changes()`, `auth_event()` and `flush_unique(db, "alert_rules_name_key", "rule_name_taken")`, and calls `record()` last.
- `firing_count` is one grouped count of `Alert.state == "firing"` by `rule_id`.
- `PATCH` sets `updated_at = func.now()`.
- `main.py` includes `app.alerts.router.rules_router`.

Run it again and `tests/security`. **Expected:** pass. Then the full **BT**.

**Commit:** `feat(alerts): the Owner creates, changes and deletes alert rules`.

## Step 8 — Rules go with their group or server
**Files:** `backend/app/alerts/service.py`, `backend/app/inventory/service.py`, `backend/app/inventory/servers.py`, `backend/tests/inventory/test_group_delete.py`, `backend/tests/inventory/test_server_remove.py`.

Write these tests first:
- `test_deleting_a_group_deletes_its_rules_with_their_events`: the events are `alert_rule.deleted` for each of the group's rules, then `server_group.deleted`, and a global rule stays.
- `test_removing_a_server_deletes_its_rules_with_their_events`: the same, with `server.deleted` last, for a group Admin too. The server's alerts are gone.

Run **BT** on both files. **Expected:** fail.

Implementation:
- `alerts.service.delete_rules_of(db, request, user, *, group_id=None, server_id=None) -> list[Event]` deletes the rules scoped to that group or server and returns their deletion events.
- `delete_group` and `delete_server` call it before deleting, and record the returned events before their own (`record()` stays last).

Run both files, then the full **BT**. **Expected:** pass.

**Commit:** `feat(inventory): a group's or a server's alert rules go with it, audited`.

## Step 9 — Alert lists, the server's alerts and the bell's events
**Files:** `backend/app/alerts/schemas.py`, `backend/app/alerts/service.py`, `backend/app/alerts/router.py`, `backend/app/main.py`, `backend/tests/alerts/test_alerts_api.py`, `backend/tests/security/test_permission_coverage.py`, `backend/tests/security/test_audit_coverage.py`, `backend/tests/alerts_helpers.py`.

Add the helper `make_alert(server_id, *, state="firing", fired_at, resolved_at=None, rule=None, instance="/", kind_events=("fired",))` (as the owner).

Write these tests first:
- `test_a_person_sees_only_alerts_of_servers_they_see`;
- `test_firing_and_closed_follow_the_group_and_tag_filters`;
- `test_closed_is_newest_first_50_per_page_within_30_days_and_pages_with_before`;
- `test_the_server_route_lists_firing_first_then_history_and_404s_a_hidden_server`;
- `test_the_bell_counts_unseen_events_and_seen_moves_the_mark` (unseen before; `POST /api/alerts/seen` gives 204; then 0; a new event gives 1);
- `test_a_person_who_loses_sight_of_a_server_loses_its_events`.

Run **BT** `tests/alerts/test_alerts_api.py`. **Expected:** fail.

Implementation:
- `alerts_router` serves:
  - `GET /alerts` (`state: Literal["firing","closed"] = "firing"`, `group_id`, `tag` list, `before: datetime | None`, `limit` 1 to 50, default 50);
  - `GET /alerts/events`;
  - `POST /alerts/seen`, which sets `user.alerts_seen_at = clock.now()` and answers 204.
- `server_alerts` serves `GET /servers/{server_id}/alerts` with `require_group_visible(group=group_of_server)`. Without `before`, it answers every firing alert, then 50 closed ones; with `before`, only closed ones older than it.
- Visibility uses `access.visible_group_ids()` like `list_servers`.
- `unseen` counts `alert_events.at > alerts_seen_at` (everything when null) among visible servers within 30 days.
- Pin `GET /api/alerts`, `GET /api/alerts/events` and `POST /api/alerts/seen` in `ANY_SIGNED_IN` with reasons. Add `"POST /api/alerts/seen": "it moves the person's own read mark, which is not a change of the platform"` to `EXEMPT`.

Run it again and `tests/security`. **Expected:** pass. Then the full **BT**.

**Commit:** `feat(alerts): people read the alerts of the servers they see and their new events`.

## Step 10 — Message texts
**Files:** `backend/app/notify/messages.py`, `backend/tests/notify/test_notify_messages.py`.

Write these tests first:
- `test_duration_and_rule_sentences`;
- `test_headlines_per_metric`;
- `test_the_email_subject_and_body`;
- `test_the_slack_and_telegram_text`;
- `test_the_generic_json_shape`;
- `test_resolved_and_ended_sentences`.

Use the exact strings of contract D, for example subject `[Critical] db-prod-01: /var is 93.4% full` and Slack `{"text": "Critical: db-prod-01: /var is 93.4% full. Space used above 90% for 10 min."}`.

Run **BT** `tests/notify/test_notify_messages.py`. **Expected:** ImportError.

Implementation: `EventView` (a frozen dataclass: `event_id, kind, at, alert fields…, server_id, server_name, group_name`), plus `duration_text`, `rule_sentence`, `headline`, `event_sentence`, `email_subject`, `email_body`, `chat_text`, `generic_json` and `TEST_TEXT`.

Run it again. **Expected:** pass.

**Commit:** `feat(notify): the texts of alert messages`.

## Step 11 — Transports: SMTP, HTTPS webhooks and Telegram, with local sinks
**Files:** `backend/app/notify/transports.py`, `backend/tests/sinks.py`, `backend/tests/notify/test_notify_transports.py`.

`tests/sinks.py` (standard library only):
- `HttpSink` (asyncio): records `(path, headers, body)` for each POST; `respond_with(status, headers)`; answers 404 to a `GET /received` that is not on the JSON route; `GET /received` gives `{"webhooks": [...], "mail": [...]}` when it runs with a mail sink.
- `SmtpSink`: answers `EHLO`/`HELO`, `MAIL`, `RCPT` (a configurable set of refused addresses gets 550), `DATA` and `QUIT`, and records `{from, to, data}`.
- `async def main()` runs both on `0.0.0.0` 8080 and 2525 for the stack.

Write these tests first:
- `test_email_goes_to_every_recipient_in_bcc` (no recipient in the `To:` or `Cc:` headers);
- `test_email_counts_as_sent_when_one_recipient_is_accepted`;
- `test_email_refused_by_all_raises_recipients_refused`;
- `test_a_webhook_posts_json_and_ignores_the_body`;
- `test_a_redirect_is_not_followed` (`redirect_refused`);
- `test_an_http_url_is_refused_unless_allowed`;
- `test_a_non_2xx_answer_is_http_status`;
- `test_telegram_posts_send_message` (monkeypatch `TELEGRAM_API` to the sink);
- `test_no_error_holds_the_url_or_the_token`.

Run **BT** `tests/notify/test_notify_transports.py`. **Expected:** fail.

Implementation:
- `class DeliveryFailed(Exception): code: str`.
- `@dataclass EmailConfig(host, port, security, username, password, from_name, from_address)`.
- `async def send_email(config, recipients, subject, body) -> None` runs `smtplib` in `asyncio.to_thread`, with `timeout=10`, `ssl.create_default_context()` for `tls` and `starttls`, and `login` when `username` is set. The `To` header is the from address; recipients go only in the envelope.
- `async def post_json(url, payload, *, allow_http) -> None` uses `httpx.AsyncClient(follow_redirects=False, timeout=10)` and `client.stream("POST", …)`, and reads no body.
- `async def send_telegram(token, chat_id, text) -> None`.
- `def check_url(url, allow_http) -> None` raises `DeliveryFailed("webhook_url_https")` or `DeliveryFailed("bad_url")`.
- Map `smtplib` and `httpx` exceptions to codes by type; never `str(exc)`.

Run it again. **Expected:** pass.

**Commit:** `feat(notify): email, webhook and Telegram transports`.

## Step 12 — The sender: dispatch, deliver, retry, give up, prune
**Files:** `backend/app/notify/sender.py`, `backend/tests/notify/test_notify_sender.py`, `backend/tests/alerts_helpers.py`.

Add the helpers `make_channel(kind, secret: dict, **kw)` (seals the secret) and `set_email(**kw)` (as the owner).

Write these tests first, on the real database with local sinks and a fake clock (`settings` with `webhook_allow_http=True`):
- `test_dispatch_creates_one_delivery_per_matching_channel_by_severity`;
- `test_email_goes_to_the_owner_and_the_group_admins_plus_extra_addresses_without_disabled_or_duplicates`;
- `test_a_failed_try_is_retried_on_the_timetable_then_succeeds`;
- `test_after_six_tries_the_delivery_is_failed`;
- `test_an_event_older_than_an_hour_is_dispatched_without_deliveries`;
- `test_no_channel_and_no_email_dispatches_with_no_deliveries`;
- `test_a_channel_created_later_gets_nothing_from_the_past`;
- `test_two_senders_never_send_twice` (two `Sender`s with `asyncio.gather` on `dispatch` and `send_due`; the sink receives exactly one message per delivery);
- `test_deliveries_older_than_30_days_are_deleted`;
- `test_last_error_holds_only_a_code`.

Run **BT** `tests/notify/test_notify_sender.py`. **Expected:** fail.

Implementation: contract F.
- Building an `EventView` takes one query: event, alert, server and group.
- Email reads the `notification_email` row and unseals the password with `EMAIL_ROW`. Channels unseal with `channel.id.bytes`; `SecretUndecryptable` gives `undecryptable`.
- `run()` catches `Exception`, logs with `logger.exception` (no secrets in the message), sleeps `EVERY` and goes on.

Run it again. **Expected:** pass. Then the full **BT**.

**Commit:** `feat(notify): a sender that delivers each alert event with retries`.

## Step 13 — The backend runs the sender
**Files:** `backend/app/main.py`, `backend/tests/notify/test_notify_lifespan.py`.

Write these tests first:
- `test_the_lifespan_starts_and_stops_the_sender_when_on`: `create_app(Settings(..., notification_sender=True))`, run through `app.router.lifespan_context(app)` with `Sender.run` monkeypatched to an `asyncio.Event` setter. Leaving the context cancels it.
- `test_the_lifespan_starts_nothing_when_off`.

Run **BT** `tests/notify/test_notify_lifespan.py`. **Expected:** fail.

Implementation: an `@asynccontextmanager lifespan(app)` in `create_app`. When `settings.notification_sender` is on, it creates `asyncio.create_task(Sender(SessionLocal, settings=settings).run())`. On exit it cancels and awaits the task, suppressing `CancelledError`. Pass it as `FastAPI(lifespan=…)`.

Run it again, then the full **BT**. **Expected:** pass.

**Commit:** `feat(notify): the backend starts the sender with the API`.

## Step 14 — Email settings and the email test
**Files:** `backend/app/notify/schemas.py`, `backend/app/notify/service.py`, `backend/app/notify/router.py`, `backend/app/notify/actions.py`, `backend/app/main.py`, `backend/tests/notify/test_notify_email_api.py`.

Write these tests first:
- `test_get_shows_password_set_but_never_the_password`;
- `test_put_keeps_replaces_or_removes_the_password`;
- `test_put_is_audited_with_the_password_redacted` (`notification_email.changed`, `change.password == {"before": "[redacted]", "after": "[redacted]"}`);
- `test_enabling_needs_a_host_and_a_from_address` (422);
- `test_extra_addresses_are_lowercased_deduplicated_and_at_most_20`;
- `test_the_test_goes_to_the_owners_own_address_and_is_audited` (SMTP sink; `notification_email.tested` with `result_detail.ok`);
- `test_testing_before_setup_is_409_email_not_set_up`;
- `test_others_get_403`.

Run **BT** `tests/notify/test_notify_email_api.py`. **Expected:** 404s.

Implementation:
- `actions.py` holds the seven `notification_*` action names of the design.
- `email_router` (prefix `/notifications/email`) serves `GET`, `PUT` and `POST /test`, all with `require_owner` and `audited(...)`.
- The test sends with `transports.send_email` to `owner.email` and answers `TestResultOut`. A failure still records its event, with `result=Result.FAILURE`, and answers 200.

Run it again and `tests/security`, then the full **BT**. **Expected:** pass.

**Commit:** `feat(notify): the Owner sets up email for alerts`.

## Step 15 — Webhook and Telegram channels
**Files:** `backend/app/notify/schemas.py`, `backend/app/notify/service.py`, `backend/app/notify/router.py`, `backend/app/main.py`, `backend/tests/notify/test_notify_channels_api.py`, `backend/tests/notify/test_notify_secrets.py`.

Write these tests first:
- `test_create_list_patch_delete_with_their_events`;
- `test_the_hint_is_the_url_host_or_the_chat`;
- `test_an_http_url_is_refused_unless_webhook_allow_http`;
- `test_bad_telegram_token_and_chat_id`;
- `test_at_most_20_channels`;
- `test_a_unique_name`;
- `test_send_a_test_reaches_the_sink_and_is_audited`;
- `test_the_list_shows_the_last_delivery_state`;
- `test_others_get_403`.
- `test_notify_secrets.py::test_no_answer_audit_event_log_record_or_last_error_holds_a_secret`: save a password, a URL with a path token and a bot token. Call every notify route, make failing deliveries, and collect the logs with `caplog`. Then assert that none of the three strings appears in any answer body, any `audit_log` row (`str(columns)`), any log record or any `last_error`.

Run **BT** on both files. **Expected:** fail.

Implementation:
- `channels_router` (prefix `/notification-channels`) serves `GET`, `POST`, `PATCH /{id}`, `DELETE /{id}` and `POST /{id}/test`, all with `require_owner` and `audited(...)`.
- A new id is made in Python before sealing.
- URL checks use `transports.check_url(url, settings.webhook_allow_http)`.
- The token pattern is `^\d{5,}:[A-Za-z0-9_-]{30,}$`. The chat ID pattern is `^(-?\d{1,20}|@[A-Za-z0-9_]{5,32})$`.
- A changed secret shows in the audit change as `{"secret": {"before": "[redacted]", "after": "[redacted]"}}`.

Run them again, `tests/security`, then the full **BT**. **Expected:** pass.

**Commit:** `feat(notify): the Owner sets up webhook and Telegram channels`.

## Step 16 — Stack: a staged disk-fill fires, notifies and resolves
**Files:** `docker-compose.yml`, `tools/stacks/dev.env`, `tools/stacks/e2e.env`, `megoocolab.toml`, `tools/fake-server/docker-compose.stack.yml`, `backend/tests/test_stack.py`, `.env.example`.

Write the test first: `test_a_staged_disk_fill_fires_notifies_and_resolves(owner)`.
- Register and pin the fake server as the other stack tests do.
- Through Caddy:
  - `PUT /api/notifications/email` with host `sink`, port 2525, security `none`, from `alerts@example.com`, enabled;
  - `POST /api/notification-channels` with a `webhook_json` channel to `http://sink:8080/hook`.
- Read `df -kP /` on the fake server with `_compose_with_fake_server("exec","-T","fake-server","df","-kP","/")`, and compute `threshold = (used + 128 MiB in kB) / (used + avail) * 100`.
- `POST /api/alert-rules`: `disk.used_percent above <threshold>`, duration 0, scoped to the server.
- Fill: `exec fake-server fallocate -l 256M /var/tmp/megoo-fill` (or `dd` if `fallocate` fails).
- Wait up to 90 s for `GET /api/servers/{id}/alerts` to show a firing alert, and for the sink's `GET /received` to show the webhook and the mail. Read the sink with `exec backend python -c` and urllib, on `http://sink:8080/received`.
- Remove the file, then wait for `resolved` and for a second webhook and mail.
- Always remove the file in `finally`.

Run **STK**. **Expected:** it fails (no sink).

Implementation:
- `docker-compose.yml` backend environment: `WEBHOOK_ALLOW_HTTP: ${WEBHOOK_ALLOW_HTTP:-false}`.
- `dev.env` and `e2e.env`: `WEBHOOK_ALLOW_HTTP=true`.
- `megoocolab.toml` `[services.stack.env]`: `WEBHOOK_ALLOW_HTTP = "true"`.
- `docker-compose.stack.yml`: a service `sink` with `image: python:3.13-slim`, `command: ["python", "/sinks.py"]`, a volume `./backend/tests/sinks.py:/sinks.py:ro`, `networks: [servers]`, `restart: unless-stopped`, and a healthcheck with python and urllib on `http://127.0.0.1:8080/received`.
- `.env.example`: a commented `#WEBHOOK_ALLOW_HTTP=false` with "only for test stacks".

Run **STK** and **BT** `tests/test_stack.py tests/test_makefile.py`. **Expected:** pass.

**Commit:** `test(stack): a staged disk fill fires, notifies and resolves`.

## Step 17 — Frontend foundations: switch, popover, alert sentences, error codes
**Files:** `frontend/src/components/ui/switch.tsx`, `frontend/src/components/ui/popover.tsx`, `frontend/src/lib/alerts.ts`, `frontend/src/lib/__tests__/alerts.test.ts`, `frontend/src/lib/servers.ts`, `frontend/src/lib/auth/messages.ts`, `frontend/src/lib/auth/__tests__/messages.test.ts`.

Write these tests first:
- `alerts.test.ts`: `durationText` (0, 600, 3600, 5400); `ruleSentence` for each metric and duration 0; `valueText`; `alertHeadline` for each metric; `eventSentence` for fired, resolved and ended; `alertsPath` with a group and tags; `firingByServer`. Use the strings of contract D.
- `messages.test.ts`: each new code of "Error codes" has its own text.

Run **FE** `src/lib`. **Expected:** fail.

Implementation:
- `npx shadcn@latest add switch popover` (new-york; the files import from `radix-ui`).
- `export` `withQuery` from `servers.ts`.
- `lib/alerts.ts` as contract G.
- In `messages.ts`, add the new codes in plain sentences, for example `rule_name_taken: "An alert rule with this name exists already."`, `bad_threshold: "The limit does not fit this measure."`, `webhook_url_https: "The address must start with https://."` and `email_not_set_up: "Set up email first."`, and the transport codes.

Run **FEALL**. **Expected:** pass.

**Commit:** `feat(alerts): the sentences of alerts and rules in the frontend`.

## Step 18 — Shared alert pieces
**Files:** `frontend/src/components/alerts/severity-badge.tsx`, `alert-state-badge.tsx`, `alert-rows.tsx`, `frontend/src/components/alerts/__tests__/alert-pieces.test.tsx`.

Write these tests first:
- `SeverityBadge` shows the word "Warning" (amber) or "Critical" (pink, `destructive`): always the word.
- `AlertStateBadge` shows "Firing", "Resolved" or "Ended".
- `AlertRows` gives a table with Severity, Server (a link to `/servers/{id}?tab=alerts`), what happened (`alertHeadline`), rule (`ruleSentence`), Since/Fired and Resolved (local times), and state. It has a `showServer` prop and an empty state passed as children.

Run **FE** `src/components/alerts`. **Expected:** fail.

Implementation: build on `components/ui/badge.tsx` and `table.tsx`.

Run **FEALL**. **Expected:** pass.

**Commit:** `feat(alerts): badges and rows for alerts`.

## Step 19 — Dashboard: Firing alerts tile, Alerts card, marks on servers
**Files:** `frontend/src/components/alerts/alerts-card.tsx`, `frontend/src/components/alerts/__tests__/alerts-card.test.tsx`, `frontend/src/components/dashboard/dashboard-page.tsx`, `fleet-summary.tsx`, `server-card.tsx`, `server-rows.tsx`, `frontend/src/components/dashboard/__tests__/dashboard-page.test.tsx`, `dashboard-pieces.test.tsx`.

Write these tests first:
- `AlertsCard` has Firing and History tabs (`role="tablist"`), firing rows, the empty firing state "No alerts are firing.", and History read with `alertsPath("closed", filters)` and "Show more" (`before` = last `resolved_at`).
- The Dashboard:
  - reads `alertsPath("firing", filters)` with the lists and on every refresh;
  - shows the "Firing alerts" tile with the count;
  - puts the card in the reserved slot;
  - shows "1 alert" or "N alerts" on a server's card and table row;
  - makes the card follow the filters.
- The existing mocks learn the `/alerts` paths.

Run **FE** `src/components/dashboard src/components/alerts`. **Expected:** fail.

Implementation:
- `FleetSummary({servers, firing})` gets a sixth tile, with `lg:grid-cols-6`.
- `ServerCard` and `ServerRows` take `alerts?: number` and render a destructive badge.
- `DashboardPage` holds `firing: Alert[]`, in a foreground read and a background refresh like `servers`.

Run **FEALL**. **Expected:** pass.

**Commit:** `feat(dashboard): firing alerts and their history on the Dashboard`.

## Step 20 — The bell in the header
**Files:** `frontend/src/components/shell/alert-bell.tsx`, `frontend/src/components/shell/site-header.tsx`, `frontend/src/components/shell/__tests__/alert-bell.test.tsx`, `site-header.test.tsx`, `app-shell.test.tsx`.

Write these tests first:
- The bell button is labelled "Alerts, N new". It shows the count when `unseen > 0`, and "99+" above 99.
- Opening it shows the 10 events with `eventSentence`, a severity badge and a time, each a link to the server's Alerts tab. When there are none, it shows "No alert events yet."
- Opening it calls `POST /alerts/seen` once and sets the count to 0.
- It re-reads `/alerts/events` through `useRefresh`.
- `site-header.test.tsx` and `app-shell.test.tsx` mock `@/lib/api` (`apiFetch` resolving `{unseen:0, firing:0, events:[]}`).

Run **FE** `src/components/shell`. **Expected:** fail.

Implementation: `AlertBell` with `Popover` and lucide `Bell`, placed before `ThemeSwitch` in `SiteHeader`. Read with `background: true` on refresh.

Run **FEALL**. **Expected:** pass.

**Commit:** `feat(shell): a bell with the newest alert events`.

## Step 21 — Server page: the firing banner and the Alerts tab
**Files:** `frontend/src/components/alerts/server-alert-banner.tsx`, `server-alerts-tab.tsx`, `frontend/src/components/alerts/__tests__/server-alerts.test.tsx`, `frontend/src/components/servers/server-page.tsx`, `frontend/src/components/servers/__tests__/server-page.test.tsx`.

Write these tests first:
- A Linux server reads `/servers/{id}/alerts` with its facts.
- A destructive banner above the tabs names each firing alert (`alertHeadline` and severity), with a link to `?tab=alerts`.
- An "Alerts" tab appears, labelled with the number of firing alerts when there are any (`Alerts 2`).
- `?tab=alerts` shows firing, then history, with "Show more".
- A Windows server reads nothing and has no Alerts tab or banner.
- The existing mocks learn the path.

Run **FE** `src/components/servers/__tests__/server-page.test.tsx src/components/alerts`. **Expected:** fail.

Implementation:
- Add `"alerts"` to `Tab` and to the allowed `wanted` values for Linux.
- `readFacts` also reads the alerts, foreground and background.

Run **FEALL**. **Expected:** pass.

**Commit:** `feat(servers): a server's firing alerts and its Alerts tab`.

## Step 22 — Settings → Alert rules
**Files:** `frontend/src/components/settings/settings-tabs.tsx`, `alert-rules-page.tsx`, `delete-rule-dialog.tsx`, `frontend/src/app/(app)/settings/alert-rules/page.tsx`, `frontend/src/app/(app)/settings/layout.tsx`, tests under `frontend/src/components/settings/__tests__/` (`alert-rules-page.test.tsx`, `settings-tabs.test.tsx`), `frontend/src/app/(app)/settings/__tests__/layout.test.tsx`.

Write these tests first:
- The tabs are Users, Server groups, Alert rules and Notifications.
- The page lists the rules: name, `ruleSentence`, scope ("All servers", the group's or the server's name), severity badge, "Firing on N servers", and a `Switch` labelled "Enabled". Toggling the switch sends `PATCH {enabled}`.
- "New rule" and "Edit" open the dialog (a stub until step 23: the page imports `AlertRuleDialog` from `alert-rule-dialog.tsx`, created here with only its props and a title).
- "Delete" opens a confirmation that names the rule and says its firing alerts end. It sends `DELETE` and reloads.
- An empty list shows "No alert rules. Nothing is watched."
- The layout's text now reads "Only the Owner of this installation manages people, server groups, alert rules and notifications."

Run **FE** on these tests. **Expected:** fail.

Implementation: follow `groups-page.tsx` and `delete-group-dialog.tsx`. Route metadata title: "Alert rules".

Run **FEALL**. **Expected:** pass.

**Commit:** `feat(settings): the Owner's list of alert rules`.

## Step 23 — The rule dialog
**Files:** `frontend/src/components/settings/alert-rule-dialog.tsx`, `frontend/src/components/settings/__tests__/alert-rule-dialog.test.tsx`.

Write these tests first:
- The fields are:
  - Name;
  - Watch (`Select` of `METRICS` labels);
  - Comparison (`RadioGroup` Above or Below), Limit (a number input with the unit suffix "%" or "per core", and max 100 or 1000), both hidden for Unreachable;
  - For (minutes, 0 to 1440, hint "0 fires at the first sample");
  - Severity (Warning or Critical);
  - Applies to (All servers, a group, or a server: two selects from `/server-groups` and `/servers`).
- A live sentence below the fields uses `ruleSentence`.
- Create sends `POST` with `duration_seconds = minutes*60`. Edit sends only the changed fields with `PATCH`, and is disabled when nothing changed.
- API errors show `messageFor(detail)`.

Run **FE** `src/components/settings/__tests__/alert-rule-dialog.test.tsx`. **Expected:** fail.

Implementation: follow `group-dialog.tsx` (a form keyed by the rule, unmounted when closed).

Run **FEALL**. **Expected:** pass.

**Commit:** `feat(settings): create and edit an alert rule`.

## Step 24 — Settings → Notifications: email
**Files:** `frontend/src/components/settings/notifications-page.tsx`, `email-dialog.tsx`, `frontend/src/app/(app)/settings/notifications/page.tsx`, `frontend/src/components/settings/__tests__/notifications-page.test.tsx`, `email-dialog.test.tsx`.

Write these tests first:
- The Email card:
  - before setup, it says "Email is not set up. Alerts are shown in the app only." and offers "Set up email";
  - once set up, it shows server, from, who gets it ("The Owner and the Admins of the server's group, plus N more addresses"), the severity filter, the last delivery state, and buttons Edit and "Send a test" (result shown inline, `messageFor(error)` on failure).
- `EmailDialog` fields: Enabled switch, Host, Port, Security (STARTTLS, TLS, None), User name, Password (always empty; placeholder "Saved, type to replace" when `password_set`; a "Remove password" checkbox sends `""`), From name, From address, extra addresses (one per line, up to 20), "Warning and Critical" or "Critical only".
- It sends `PUT` without `password` unless it was typed or removed.

Run **FE** on these tests. **Expected:** fail.

Implementation: the page also reserves the "Webhooks and chat" card (filled in step 25). Route metadata title: "Notifications".

Run **FEALL**. **Expected:** pass.

**Commit:** `feat(settings): the Owner sets up email for alerts`.

## Step 25 — Settings → Notifications: webhooks and chat
**Files:** `frontend/src/components/settings/notifications-page.tsx`, `channel-dialog.tsx`, `delete-channel-dialog.tsx`, `frontend/src/components/settings/__tests__/channel-dialog.test.tsx`, `notifications-page.test.tsx`.

Write these tests first:
- The "Webhooks and chat" card lists the channels: name, kind ("Generic JSON", "Slack-compatible", "Telegram"), `hint`, severity filter, an Enabled `Switch` (`PATCH`), the last delivery state ("Failed after 6 tries" in pink when failed), "Send a test", Edit and Delete. It has "Add a channel", and the empty state "No webhooks or chats yet."
- `ChannelDialog`:
  - Name, Kind, then URL for the webhooks (hint: Slack format also works with Mattermost, Rocket.Chat, Google Chat and Discord with `/slack`), or Bot token and Chat ID for Telegram;
  - the severity filter and Enabled;
  - on edit, the secret fields are empty, with "Saved, type to replace" and the hint shown, and they are sent only when typed;
  - errors use `messageFor`.
- Delete confirmation names the channel.

Run **FE** on these tests. **Expected:** fail.

Run **FEALL**, then `megoocolab-runner services run web -- npm run test:image`. **Expected:** pass.

**Commit:** `feat(settings): the Owner sets up webhooks and Telegram chats`.

## Step 26 — README
**Files:** `README.md`.

Add an "Alerts" section:
- how rules work (threshold plus duration, load per core, one alert per filesystem, Owner only in Settings);
- the four starter rules;
- what fires, resolves and ends;
- the bell and the Dashboard;
- email (by role plus extra addresses, Bcc), Generic JSON, Slack-compatible and Telegram webhooks, the severity filter, and one message when an alert fires and one when it ends;
- retries, then failed;
- secrets encrypted with a key derived from `AUTH_SECRET_KEY`;
- `WEBHOOK_ALLOW_HTTP` for test stacks only.

Replace "The app sends no email" with the new behaviour. `AGENTS.md` is unchanged (no new suite).

Run **BT** `tests/test_makefile.py`, if it reads the README, and the full **BT**.

**Commit:** `docs: alerts, their starter rules and notification channels`.

## Final verification
From `backend/`:
- `megoocolab-runner services run test -- uv run pytest`
- `megoocolab-runner services run image -- uv run pytest -m docker`
- `megoocolab-runner services run stack -- uv run pytest -m stack` (holds the "done when" test of step 16)
- **MIG**

From the repository root: `make test-security`.

From `frontend/`:
- `npx tsc --noEmit`
- `npx eslint src`
- `npm test`
- `megoocolab-runner services run web -- npm run test:image`

By hand, on `make up STACK=dev`:
1. Register the fake server and add a disk rule just above its use.
2. Add a webhook channel to `http://sink:8080/hook`.
3. Run `fallocate` on the fake server. The Dashboard shows the firing alert, the bell counts it, and the server's Alerts tab lists it.
4. Remove the file. The alert shows as Resolved within 15 s.
