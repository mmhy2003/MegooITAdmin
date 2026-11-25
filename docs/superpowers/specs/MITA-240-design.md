# MITA-240 design: the Servers pages show the monitoring state and the sample interval

## Goal

People see on the Servers list and on a server's page whether the collector reaches the server (reachable, unreachable or not monitored), and why not. The Owner and group Admins set how often a Linux server is sampled in the Register and Edit dialog. Both pages keep the state current by themselves, without keeping an idle session alive.

The approved screens are mockup **v2**.

## Decisions

| Decision | Chosen | Why, and what was rejected |
|---|---|---|
| Where the state shows | **Layout A** (your answer): a Status column on the list, and on the server page a badge beside the name plus a Monitoring card | The reason is readable without a hover, also on touch screens. Rejected layout B (badge beside the name with a tooltip, and a banner only when unreachable): the reason hides in a tooltip, and a server with an unpinned key carries two badges beside its name. |
| Refresh | **Re-read every 15 seconds while the tab is visible** (your answer) | A "Reachable" badge that stays after the server went down is misleading. Rejected "load once". The dashboard task's WebSocket can replace this later. |
| Refresh and the idle limit | **Automatic re-reads do not count as activity** (your answer) | Every signed-in request moves `last_seen_at`, so a page that re-reads every 15 seconds would never reach the 60-minute idle limit. Re-reads carry a header and the backend leaves `last_seen_at` alone for them. The header can only shorten a session, never extend it, so it gives an attacker nothing. Rejected: accepting that an open Servers page stays signed in for 12 hours. |
| Interval field | **In Register and in Edit, starting at 5** (your answer) | They are one form, and the API takes the interval on create. |
| Windows servers | **The field is hidden while Windows is selected** (your answer) | They are never monitored. Choosing Windows puts the interval back to the saved value (5 for a new server), so a hidden field never changes anything. |
| A server the collector has not looked at yet (`monitoring` is `null`) | A fourth, dashed badge **"Not checked yet"** | The API has this case; it lasts about 10 seconds after a server is registered, or as long as the collector is down. Shown in the mockup. |
| "Last sample" | Shown **only when unreachable** | The collector writes `last_sample_at` only when the state changes. For a reachable server it is the time of the first sample, not the newest, and would mislead. No backend change is needed for this. |
| Reason texts | New texts for monitoring, in the wording of the connection test | `no_samples`, and the three "not monitored" reasons, have no text today, and the connection test's advice ("test again") does not fit. |

## Architecture

**Frontend** (`frontend/src`)

- `lib/servers.ts`: the types `MonitoringState`, `MonitoringReason` and `Monitoring`; `Server` gets `metrics_interval_seconds` and `monitoring`; `DEFAULT_INTERVAL = 5`; `ServerDraft` gets `interval`, `ServerBody` gets `metrics_interval_seconds`; `draftOf`, `bodyOf` and `changesOf` handle it like the port.
- `lib/auth/messages.ts`: `MONITORING_REASONS` (a title and an advice per reason) and `monitoringText(reason)`, beside `CONNECTION_REASONS`. It returns `null` for a reason it does not know.
- `lib/api.ts`: `apiFetch` gets the option `background?: boolean`, which adds the header `X-Megoo-Background: 1`.
- `hooks/use-refresh.ts` (new): `useRefresh(refresh, active)` calls `refresh` every 15 seconds while the tab is visible and `active` is true, and once at the moment the tab becomes visible again. It clears its timer and listener on unmount.
- `components/servers/monitoring-badge.tsx` (new): `MonitoringBadge({ monitoring })`, built on `Badge`. Reachable: green outline (`border-green text-green-ink`) with a filled dot. Unreachable: `destructive`. Not monitored: muted outline. Not checked yet: dashed muted outline. The label is always text; the dot is `aria-hidden`.
- `components/servers/monitoring-card.tsx` (new): `MonitoringCard({ server })`: Status, Since, Last sample (unreachable only; "None yet" when empty), Sample interval (Linux only: "Every 5 seconds", "Every second" for 1), then the reason's title and advice.
- `components/servers/servers-page.tsx`: a **Status** column after Name with the badge and the reason's title under it. `useRefresh` re-reads only the servers path, in the background.
- `components/servers/server-page.tsx`: the badge after the name, the Monitoring card above the Connection and Details cards. `useRefresh` re-reads the server in the background.
- `components/servers/server-dialog.tsx`: the **Sample interval** number field (1 to 10, step 1, required, suffix "seconds", hint "How often its metrics are read: 1 to 10 seconds.") beside Role, only while Linux is selected.

**Backend** (`backend/app/auth`)

- `sessions.py`: `BACKGROUND_HEADER = "x-megoo-background"`, and `lookup_session(db, token, *, touch=True)` moves `last_seen_at` only when `touch` is true. The expiry check stays the same.
- `deps.py`: `current_session` passes `touch=False` when the request carries the header with the value `1`.

**Docs**: the Servers section of `README.md` says where the state shows and where the interval is set, and that the pages' automatic re-reads do not count as activity.

## Data and interfaces

No migration, and no change to the server API: `metrics_interval_seconds` and `monitoring` exist since MITA-26.

- New request header `X-Megoo-Background: 1`, honoured on every signed-in route. It has one effect: the request does not move the session's `last_seen_at`.
- Reason texts:

| Reason | Title | Advice |
|---|---|---|
| `unreachable` | The server did not answer. | Check the address and the port, and that the server accepts SSH connections from MegooITAdmin. |
| `key_refused` | The server refused the platform's key. | Run the setup script on the server with the platform's key (see Platform access). |
| `ssh_error` | The SSH connection failed. | The server may offer only old algorithms, or the metrics loop could not start there. |
| `no_samples` | No sample for 30 seconds. | The server stopped sending samples. It may be overloaded or frozen. |
| `not_an_ssh_server` | Only Linux servers are monitored. | (none) |
| `host_key_not_pinned` | The host key is not pinned yet. | Monitoring starts once the host key is pinned. |
| `host_key_changed` | The host key has changed. | Monitoring resumes once the new key is reviewed. |
| `monitoring` is `null` | The collector has not looked at this server yet. | (none) |

## Error handling and edge cases

- **A background re-read fails** (network, 5xx): nothing changes on screen and no error shows. The next one tries again.
- **The session ended**: the re-read answers 401 and `apiFetch` sends the person to sign-in, as for any request.
- **The server is gone or no longer visible** (404 on the server page): the page shows its "does not exist" card, as today.
- **No re-read while the person is busy**: `active` is false while one of the page's dialogs is open (register, edit, remove, pin, review) or a connection test runs, so nothing changes under an open form.
- **A late answer is dropped**: an answer is applied only when no newer read of the same page started meanwhile (a save, a filter change), so an old answer never overwrites a newer one.
- **Hidden tab**: no requests. One re-read at the moment it is visible again.
- **An unknown reason** (a newer backend): the badge shows without a reason text.
- **Interval input**: an empty or out-of-range value is stopped by the browser's validation; a 422 from the API shows "Check the fields and try again." as today. Edit sends the interval only when it changed.
- **Switching to Windows** in the dialog puts the interval back to the saved value, so a hidden field sends no change.
- **Collector down**: the last written state stays on screen. Detecting a stopped collector is out of scope.

## Testing

Tests first, as AGENTS.md asks.

- `lib/__tests__/servers.test.ts`: `draftOf` starts at 5 and copies a server's interval; `bodyOf` carries it; `changesOf` holds only the interval after it changed.
- `lib/__tests__/api.test.ts`: `background: true` sends the header; without it the header is absent.
- `hooks/__tests__/use-refresh.test.ts` (fake timers): calls every 15 seconds; not while hidden; once on becoming visible; not while inactive; nothing after unmount.
- `monitoring-badge.test.tsx`: the four labels. `monitoring-card.test.tsx`: each state's fields, "Last sample" only when unreachable, no interval for Windows, an unknown reason.
- `servers-page.test.tsx`: the Status column with badge and reason; a background re-read replaces the rows; a failed one keeps them and shows no error; none while a dialog is open.
- `server-page.test.tsx`: badge and card; a re-read updates the state; a 404 re-read shows the missing card.
- `server-dialog.test.tsx`: Register posts the default 5 and a chosen value; Edit sends only the changed interval; the field hides for Windows and then sends no change.
- Backend `tests/auth/test_sessions.py`: a request with the header does not move `last_seen_at`; a session kept only by such requests answers 401 after the idle limit; a request without the header still moves it.
- Gates: frontend `npx tsc --noEmit`, `npx eslint`, `npm test` and the image check; backend `pytest`; `make test-security`, because `app/auth` changes.

## Out of scope

- Live metrics, charts and the WebSocket (the dashboard and server detail tasks).
- A warning when the collector itself is not running.
- Alerts and audit events for reachable and unreachable.
- Filtering or sorting the list by state.
- Any change to the collector or the server API.
