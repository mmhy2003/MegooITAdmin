# MITA-29 design: alert rules and notifications

## Goal

The Owner sets alert rules ("filesystem above 90% for 10 minutes") in Settings. The collector checks every sample against them, and a firing alert shows on the Dashboard, on the server's page and under a bell in the header, for everyone who sees the server. Each alert also sends one message when it fires and one when it ends, by email and to webhooks and Telegram chats the Owner sets up in Settings.

The approved screens are mockup **v1** (Dashboard, bell, server Alerts tab, Settings → Alert rules, rule dialog, Settings → Notifications, channel dialog).

## Decisions

| Decision | Chosen | Why, and what was rejected |
|---|---|---|
| Channels | **In-app, email and webhook, all in this task** (your answer) | Rejected: in-app now and the outbound channels as a follow-up. |
| Who manages rules | **The Owner only, in Settings** (your answer) | Two new tabs: Alert rules and Notifications. Rejected: group Admins managing their groups' rules, and a per-server mute. |
| What a rule applies to | All servers, one server group or one server | Every rule that applies to a server is evaluated on its own. A stricter rule for one server is a second rule, with no override logic. |
| What a rule watches | **CPU used, memory used, filesystem space used, filesystem inodes used, load (1, 5 or 15 min), and "unreachable for N minutes"** (your answer) | Rejected for now: I/O wait and steal, network and disk rates, and the slow checks (services, certificates, updates). |
| Load | Compared **per CPU core** (shown in the mockup) | One rule fits small and large servers: 1.0 means every core is busy. |
| Severity | **Warning and Critical, per rule** (your answer) | Amber and pink, always with the word. |
| Starter rules | **Four active rules for all servers after the upgrade** (your answer) | Filesystem above 90% for 10 min (Critical), memory above 90% for 10 min (Warning), CPU above 90% for 15 min (Warning), unreachable for 5 min (Critical). The Owner can edit, switch off or delete them. |
| Messages per alert | **Two: fired and ended** (your answer) | No reminders while it keeps firing. |
| Channel settings and sending | **A Settings screen; the collector queues, the backend sends** (your answer) | Secrets are encrypted in the database and never shown again. The collector still has no `AUTH_SECRET_KEY` and cannot read the channel tables. Rejected: a seventh Compose service, and `.env` variables read by the collector. |
| Email recipients | **By role plus extra addresses** (your answer) | The Owner and the Admins of the server's group at their account address, plus up to 20 addresses typed in Settings, which get every alert. |
| Webhook formats | **Generic JSON, Slack-compatible, Telegram** (your answer) | Teams cards are not built. |
| Channel filter | **Severity only** (your answer) | Each channel, and email, is "Warning and Critical" or "Critical only". No group filter. |
| Who sees alerts in the app | Everyone who sees the server | Like its metrics and checks. No new grant switch. |
| Fleet history | A History tab on the Dashboard's Alerts card (shown in the mockup) | No fourteenth page in the sidebar. |
| How the screens stay current | The 15-second re-reads the pages already do | Alerts are rows in the database, not live samples. The WebSocket is unchanged. Rejected: pushing alert events through Valkey. |
| Evaluation | In the collector's memory, on each sample as it arrives | The collector's role cannot read `metrics`, and the samples are already in hand. Rejected: queries over the hypertable every few seconds. |
| Audit of firing | `alert.fired`, `alert.resolved` and `alert.ended` are audit events by the system actor `collector` | The PRD's incident trail starts with "an alert fired" and ties events by alert ID. This differs from reachable/unreachable changes, which stay out of the audit log (MITA-26). **This one is my call: say so if you want alerts kept out of the audit log too.** |
| `suggested_playbook` | A nullable column on the rule, always empty for now | No playbooks table exists yet. Phase 7 adds the foreign key, the field in the dialog and the one-click run. |
| Links in messages | None | The app does not know its public address. A message names the server, the rule and the value. |

## Architecture

**Flow**

1. The supervisor's 10-second poll also reads the enabled rules. A rule change applies within 10 seconds.
2. Each stream hands every sample to the alert engine. The engine keeps, per rule, server and filesystem, since when the condition has held. Nothing is read from the database for this.
3. When the condition has held for the rule's duration, the collector writes an `alerts` row (firing), an `alert_events` row and the audit event in one transaction. At the first sample where the condition no longer holds, it closes the alert the same way.
4. A sender task inside the backend looks every 5 seconds for events not yet dispatched. It creates one delivery per matching channel and sends them, with retries.
5. The pages read alerts over REST.

**Backend** (`backend/app`)

| File | Holds |
|---|---|
| `alerts/models.py`, `alerts/catalog.py` (new) | The tables `alert_rules`, `alerts`, `alert_events`. The catalog of what a rule can watch: its metric, unit, limits and whether it has one value per filesystem. |
| `alerts/schemas.py`, `alerts/service.py`, `alerts/router.py`, `alerts/actions.py` (new) | Rules CRUD for the Owner with its audit events; the alert lists; the bell's events and the "seen" mark. |
| `collector/alerts/engine.py` (new) | Pure: rules, a sample and the clock in, transitions (fire, resolve, end) out. No I/O. |
| `collector/alerts/book.py` (new) | Loads the rules and the firing alerts, writes transitions, and keeps what the database refused until the next poll. |
| `collector/stream.py`, `supervisor.py`, `__main__.py` | The stream passes each sample and the core count to the engine. The poll reloads the rules, checks the unreachable rules and retries pending writes. |
| `notify/models.py`, `notify/crypto.py` (new) | `notification_channels`, `notification_email`, `notification_deliveries`. AES-256-GCM under a key derived from `AUTH_SECRET_KEY` (HKDF, own label), bound to the row, like the TOTP secrets. |
| `notify/messages.py` (new) | Pure: an alert event in, the email subject and text, the Slack text, the Telegram text and the generic JSON out. |
| `notify/transports.py` (new) | SMTP (standard library, in a worker thread), HTTPS POST and Telegram's `sendMessage`. |
| `notify/sender.py` (new) | The loop: dispatch new events, send due deliveries, give up after the last try, delete deliveries older than 30 days. |
| `notify/router.py`, `notify/service.py`, `notify/actions.py` (new) | The Owner's routes for email settings and channels, and "Send a test". |
| `main.py` | Includes the routers. A lifespan starts the sender task (`NOTIFICATION_SENDER`, on by default, off in the tests that build the app). |
| `inventory/service.py` | Deleting a group or a server first deletes the rules that apply only to it, each with its `alert_rule.deleted` event. |
| `core/config.py`, `pyproject.toml` | `notification_sender`, `webhook_allow_http`. `httpx` moves from the dev group to the runtime dependencies. |

**Frontend** (`frontend/src`)

| File | Holds |
|---|---|
| `lib/alerts.ts` (new) | Types, the sentence of a rule ("Space used above 90% for 10 min"), durations, the sentence of an event. Pure. |
| `components/alerts/` (new) | `AlertsCard` (Firing and History tabs), `AlertRows`, `SeverityBadge`, `AlertStateBadge`, `ServerAlertBanner`, `ServerAlertsTab`. |
| `components/shell/alert-bell.tsx`, `site-header.tsx` | The bell with its count and the popover with the 10 latest events. Opening it sets the "seen" mark. |
| `components/dashboard/` | The "Firing alerts" tile, the Alerts card in the reserved slot, and the "1 alert" mark on a server's card and table row. The card follows the group and tag filters. |
| `components/servers/server-page.tsx` | The banner above the tabs, and the Alerts tab (`?tab=alerts`, Linux only) with the count of firing alerts. |
| `components/settings/` | `alert-rules-page.tsx`, `alert-rule-dialog.tsx`, `notifications-page.tsx`, `email-dialog.tsx`, `channel-dialog.tsx`, delete confirmations, and two more entries in `settings-tabs.tsx`. |
| `app/(app)/settings/alert-rules/page.tsx`, `notifications/page.tsx` (new) | The two pages. |
| `components/ui/switch.tsx`, `popover.tsx` (new) | From shadcn. |
| `lib/auth/messages.ts` | The new error codes. |

The email dialog was not drawn: it holds the rows of the Email card. Before email is set up, the card says so and offers "Set up email".

## Data and interfaces

**Migration `0011`**

`alert_rules`

| Column | Notes |
|---|---|
| `id`, `name` | Name of 1 to 80 characters, unique without regard to case |
| `metric` | `cpu.used_percent`, `mem.used_percent`, `disk.used_percent`, `disk.inodes_used_percent`, `load.1m`, `load.5m`, `load.15m` or `unreachable` |
| `comparison`, `threshold` | `above` or `below` and a number: 0 to 100 for a percentage, 0 to 1000 for load per core. Both empty for `unreachable` (checked by the database) |
| `duration_seconds` | 0 to 86,400. The dialog asks for minutes, 0 to 1440. 0 fires at the first sample |
| `severity` | `warning` or `critical` |
| `server_group_id`, `server_id` | At most one is set; both empty means all servers. Deleted with their group or server |
| `enabled`, `revision` | `revision` goes up when the metric, comparison, threshold, duration, scope or severity changes |
| `suggested_playbook_id` | `uuid`, null, no foreign key yet |
| `created_at`, `updated_at` | |

The migration inserts the four starter rules.

`alerts`

| Column | Notes |
|---|---|
| `id`, `server_id` | Deleted with its server |
| `rule_id` | Null once the rule is deleted; the alert keeps a copy of the rule below |
| `rule_name`, `metric`, `comparison`, `threshold`, `duration_seconds`, `severity` | The rule as it was when the alert fired |
| `instance` | The mount point, empty for a whole-server value |
| `state` | `firing`, `resolved` or `ended` |
| `end_reason` | For `ended`: `rule_changed`, `rule_disabled`, `rule_deleted` or `server_not_monitored` |
| `fired_at`, `resolved_at` | |
| `value`, `last_value`, `peak_value` | At firing, the newest and the worst. The last two are written at most once a minute while firing, and at the end |

A unique partial index allows one firing alert per rule, server and instance.

`alert_events`: `id`, `alert_id`, `kind` (`fired`, `resolved`, `ended`), `at`, `dispatched_at`. The bell reads it, and the sender dispatches from it.

`notification_channels`: `id`, `name` (unique), `kind` (`webhook_json`, `webhook_slack`, `telegram`), `min_severity`, `enabled`, `secret` (encrypted: the URL, or the bot token and chat ID), `hint` (the URL's host, or `chat <id>`), timestamps. At most 20.

`notification_email`: one row. `enabled`, `host`, `port`, `security` (`starttls`, `tls`, `none`), `username`, `password` (encrypted), `from_name`, `from_address`, `extra_addresses` (up to 20), `min_severity`.

`notification_deliveries`: `id`, `event_id`, `channel_id` (null for email), `state` (`pending`, `delivered`, `failed`), `attempts`, `next_attempt_at`, `last_error`, `delivered_at`, `created_at`.

`users.alerts_seen_at`: when the person last opened the bell.

**Grants**

| Relation | `megooitadmin_collector` | `megooitadmin_api` |
|---|---|---|
| `alert_rules` | `SELECT` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `alerts` | `SELECT`, `INSERT`, `UPDATE` | `SELECT` |
| `alert_events` | `INSERT` | `SELECT`, and `UPDATE` of `dispatched_at` only |
| `notification_channels`, `notification_email`, `notification_deliveries` | none | what each needs |

The collector is the only writer of `alerts`. The planner grants nothing beyond what the tests show these statements need.

**Routes**

| Route | Who | Notes |
|---|---|---|
| `GET /api/alerts?state=firing\|closed&group_id=&tag=&before=&limit=` | Any signed-in person | Only alerts of servers the person sees. `closed` is newest first, 50 per page, the last 30 days. |
| `GET /api/servers/{id}/alerts?before=&limit=` | Whoever sees the server | Firing first, then the whole history, 50 per page. |
| `GET /api/alerts/events` | Any signed-in person | `{unseen, firing, events: [the 10 latest]}`. |
| `POST /api/alerts/seen` | Any signed-in person | Moves the person's own mark. Exempt from the audit guard, with that reason. |
| `GET`, `POST /api/alert-rules`; `PATCH`, `DELETE /api/alert-rules/{id}` | Owner | The list carries how many servers each rule fires on. Events: `alert_rule.created`, `.changed`, `.deleted`. |
| `GET`, `PUT /api/notifications/email`; `POST /api/notifications/email/test` | Owner | The test goes to the Owner's own address. Events: `notification_email.changed`, `.tested`. |
| `GET`, `POST /api/notification-channels`; `PATCH`, `DELETE …/{id}`; `POST …/{id}/test` | Owner | Events: `notification_channel.created`, `.changed`, `.deleted`, `.tested`. |

A secret is write-only: no answer, audit event, log line or `last_error` ever holds a password, a URL or a token. Answers carry `password_set` and the channel's `hint`. Audit events show a changed secret as `[redacted]`. Thresholds go into audit events as text, because the audit log refuses floats.

**Messages**

- Email: plain text, one message per event. Subject like `[Critical] db-prod-01: /var is 93.4% full`. Recipients are in Bcc, so they do not see each other. Disabled accounts get nothing.
- Slack-compatible: `{"text": "Critical: db-prod-01: /var is 93.4% full. Space used above 90% for 10 min."}`
- Telegram: the same sentence through `https://api.telegram.org/bot<token>/sendMessage`.
- Generic JSON: `{"version": 1, "event", "text", "alert": {id, severity, rule_name, metric, comparison, threshold, duration_seconds, instance, value, fired_at, resolved_at, end_reason}, "server": {id, name, group}}`.

**Sending**

- A webhook URL must be `https://`. `WEBHOOK_ALLOW_HTTP=true` lifts that for the dev, e2e and stack-test stacks only. Redirects are not followed, the answer's body is never read into the app, and each try has 10 seconds.
- Six tries: at once, then after 30 seconds, 2, 5, 15 and 40 minutes. Then the delivery is `failed` and the channel's row shows it.
- Events are claimed with `FOR UPDATE SKIP LOCKED`, so a second backend process could not send twice.

## Error handling and edge cases

- **Each filesystem is its own alert.** Two full filesystems on one server give two alerts and two messages.
- **Load needs the core count**, taken from each sample's raw line. Rates are missing in the first sample after a connect, so CPU rules skip it.
- **A filesystem that disappears** while its alert fires resolves the alert at the next sample.
- **The server goes unreachable**: a condition that was still counting starts again when samples return. Metric alerts that were firing stay firing until a sample says otherwise.
- **"Unreachable for N minutes"** counts from when the collector marked the server unreachable, which is 30 seconds after its last sample. It resolves at the first sample.
- **A server that stops being monitored** (changed host key, key unpinned) ends its firing alerts with `server_not_monitored`. Windows servers never have alerts and get no Alerts tab.
- **A rule is changed, switched off or deleted while it fires**: the collector ends its alerts within 10 seconds (`ended`, shown as "Ended"), and the channels get an "ended" message. Renaming a rule ends nothing.
- **The collector restarts**: it loads the firing alerts, so they resolve normally. Conditions that were still counting start again, so an alert can fire up to its duration late.
- **The collector is stopped**: nothing is evaluated, and firing alerts stay firing. Its healthcheck shows the stop, as today.
- **The database is down**: transitions wait in memory with their real times and are written at the next poll. The unique index stops a duplicate.
- **The audit chain is busy**: the transition is retried like any failed write.
- **The backend was down**: events wait. One that is older than an hour when the sender first sees it is marked dispatched and not sent.
- **No channel and no email set up**: events are dispatched with no deliveries. A channel created later gets nothing from the past.
- **SMTP refuses some recipients**: the delivery counts as delivered when at least one address was accepted.
- **The sender task fails**: it logs, waits 5 seconds and starts again. It never takes the API down.
- **A removed server**: its alerts, events and deliveries go with it.
- **A person who loses sight of a server** no longer sees its alerts or events, and the bell's count follows.

## Testing

Tests first.

- **Engine** (unit, fake clock): fires only after the full duration; a single good sample resets the count; duration 0; above and below; one alert per filesystem; per-core load; a missing value; resolve; a rule's new revision, a disabled and a deleted rule end the alert; scope by all, group and server; unreachable from the status time.
- **Book** (real database): the transaction writes the alert, the event and the audit event; a refused write is retried; a restart loads firing alerts; the unique index.
- **Collector** (fake server): a low-threshold rule fires from real samples and resolves; a paused container fires the unreachable rule.
- **Rules API**: validation per metric, the name conflict, Owner only (403 and `access.denied` for others), each audit event with its change, rules removed with their group or server.
- **Alerts API**: only visible servers, the filters, paging, the bell's count before and after "seen".
- **Notify** (unit): the four message shapes; encryption round trip and a blob moved to another row; the retry timetable.
- **Sender** (real database, local SMTP and HTTP sinks): dispatch by severity filter; recipients by role plus extra addresses, without disabled accounts and without duplicates; retry then success; giving up; an old event is skipped; two senders never send twice.
- **Secrets**: no route answer, audit event, log record or `last_error` contains a saved password, URL or token. HTTP URLs are refused unless the setting allows them; redirects are not followed.
- **Migration**: `0011` goes down and up, inserts the starter rules, and its checks refuse a threshold on `unreachable`.
- **Security suites**: the new routes are pinned (Owner, group, any signed-in person with reasons), `POST /api/alerts/seen` is exempt with its reason, and `API_GRANTS`, `COLLECTOR_GRANTS` and the column grants list the new tables.
- **Frontend**: `lib/alerts.ts` sentences and durations; the Alerts card with firing, empty and history states; the tile and the card mark; the bell's count, popover and "seen" call; the server banner and tab; the rule dialog per metric (fields, the live sentence, errors); the Notifications page and both dialogs, with a secret never prefilled; Settings tabs; the existing Dashboard and server page mocks learn the new paths.
- **Stack**, the task's "done when": the fake server gets a rule just above its current filesystem use, a file fills the disk, the alert appears as firing through Caddy, a webhook sink and an SMTP sink in the stack receive the message, the file is removed, and the alert shows as resolved with its second message.
- **Docs**: README gets alerts, the starter rules, the channels and `WEBHOOK_ALLOW_HTTP`; `AGENTS.md` if a suite is added.

## Out of scope

- Rules on the slow checks, on I/O wait, steal, network or disk rates, and on containers.
- Group Admins managing rules, a per-server mute, maintenance windows, acknowledging an alert.
- Reminders while an alert keeps firing, and escalation.
- Teams cards, a group filter on a channel, and a per-person choice of which emails to get.
- Links from a message into the app, and HTML email.
- The suggested playbook's field in the dialog and its one-click run (Phase 7); opening an agent investigation from an alert (Phase 4).
- A separate Alerts page, pushing alerts over the WebSocket, and browser or desktop notifications.
- Moving the channel secrets into the vault (Phase 3), and deleting old alerts.
- More than one collector.