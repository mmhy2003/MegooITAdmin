# MITA-28 design: live dashboard and server performance charts

## Goal

The Dashboard shows every server the person sees with live CPU, memory, disk, load and network, fed by one WebSocket, as cards or as a table. A Linux server's page gets a live strip on Overview and a new Performance tab with live and historical charts, from 15 minutes back to one year.

The approved screens are mockup **v3** (Dashboard, Server: Overview, Server: Performance).

## Decisions

| Decision | Chosen | Why, and what was rejected |
|---|---|---|
| Scope | **All three pieces in this task** (your answer): the WebSocket, the Dashboard, the history API with the server charts | Rejected: server charts as a follow-up task. |
| Dashboard layout | **Cards and Table, with a switch** (your answer) | Cards are the default; `?view=table` keeps the table in the address. |
| Place of the charts | **A Performance tab, plus a live strip on Overview** (your answer) | Rejected: charts on Overview without a tab. |
| Time ranges | **Live, 1 hour, 6 hours, 24 hours, 7 days, 30 days, 1 year** (your answer) | Each reads the finest data that still exists and returns at most about 360 points per line. 90 days was not chosen. |
| Warning colours | **Amber from 80%, pink from 90%** (your answer), each with a ▲ mark | A visual hint only. Alert rules come with MITA-29. |
| Idle sign-out | **The live pages sign out after the idle limit** (your answer) | The socket never counts as activity, like the 15-second re-reads. A wall screen needs a higher `SESSION_IDLE_MINUTES`. |
| Chart drawing | **Recharts through shadcn's `chart` component** (your answer) | Sparklines and meters are our own small SVG. Rejected: uPlot (canvas) and a chart component of our own. |
| "Servers on screen" | The cards or rows inside the viewport, plus a small margin | It is the PRD's sentence, and it keeps a fleet of a few hundred cheap. The summary counts come from the server list, so they cover every server. |
| What the socket carries | Samples only. The server list is still re-read every 15 seconds | States, new and removed servers arrive with the list, as on the Servers pages. The collector does not change. Rejected: publishing state changes on Valkey now. |
| Two views of a subscription | `overview` (six numbers per sample, computed by the backend) and `full` (every reading) | The Dashboard does not download per-core and per-device readings for every server. |
| History for a new or returning viewer | Read over REST, then continued by the socket | Valkey delivers at most once and the database is the source of truth. The same read fills the gap after a reconnect. Rejected: a snapshot sent by the socket. |
| Valkey connections | One subscription connection per open socket | No shared state between sockets. Rejected: one hub per backend process with reference counts. |
| Who may see metrics | Everyone who sees the server, as for its checks | The PRD has no "view metrics" switch. |

## Architecture

**Backend** (`backend/app`)

| File | Holds |
|---|---|
| `metrics/ranges.py` (new) | The range table below. |
| `metrics/overview.py` (new) | `summarize(sample)`: CPU used, memory used, load (1 minute), the fullest filesystem, bytes received and sent per second summed over interfaces. A pure function, used by the socket and by the overview read. |
| `metrics/store.py` | `read_series(session, server_id, metrics, range)` and `read_overview(session, server_ids)`. |
| `metrics/fanout.py` | `Subscription`: like `subscribe`, but its set of servers can change while it is read. |
| `metrics/schemas.py`, `metrics/router.py` (new) | The two REST routes. |
| `metrics/socket.py` (new) | The route `/api/ws/metrics`: three tasks per socket (client messages, Valkey to the browser through a bounded queue, the 30-second recheck). |
| `auth/socket.py` (new) | The handshake of every socket: the Origin check and the active session. Live logs and terminals reuse it later. |
| `access/servers.py` (new) | `split_visible(db, access, server_ids)`: the servers the person sees, and the existing ones they do not. |
| `main.py` | Includes the two routers. |

The socket opens short database sessions when it needs one (handshake, subscribe, recheck). It never holds one for its lifetime.

**Frontend** (`frontend/src`)

| File | Holds |
|---|---|
| `lib/metrics.ts` (new) | Types, the range list, formatters (percent, bytes, rates), `toneOf(percent)`, the 5-minute trend buffer, merging history with live samples, and gap detection. All pure. |
| `lib/live-socket.ts` (new) | The WebSocket client: connect, subscribe again after a reconnect, backoff, close while the tab is hidden, close codes. |
| `hooks/use-live-metrics.ts`, `hooks/use-on-screen.ts` (new) | The React side of the socket, and the IntersectionObserver that says which servers are on screen. |
| `hooks/use-refresh.ts` | An optional interval (the history ranges re-read every 60 seconds). |
| `components/metrics/` (new) | `Sparkline`, `Meter`, `PercentValue` (value plus ▲), `LiveBadge`, `ServerVitals` (the rows of a card, also used by the live strip). |
| `components/dashboard/` (new) | `DashboardPage`, `FleetSummary`, `ServerCard`, `ServerRows` (table), `ViewSwitch`. `app/(app)/page.tsx` renders `DashboardPage`. |
| `components/servers/performance/` (new) | `PerformanceTab`, `RangePicker`, `MetricChart` (Recharts: lines, the band, crosshair tooltip), the six cards, and `LiveStrip` for Overview. |
| `components/ui/chart.tsx` (new) | From `npx shadcn add chart`. Recharts loads only with the Performance tab (`next/dynamic`). |
| `components/servers/server-page.tsx` | The Performance tab (Linux only, `?tab=performance&range=…`) and the live strip. |
| `lib/servers.ts` | `addressOf` takes the page, so the Dashboard keeps `group` and `tag` in its address like the Servers page. |
| `app/globals.css` | `--chart-3` (the theme's violet) for the third line of the Load chart. |

One socket per open page. The Dashboard subscribes with `overview` to the servers on screen. A server's page subscribes to its one server: `overview` on Overview, `full` on Performance, nothing on Containers.

Dashboard order: unreachable, reachable, then not monitored and not checked yet, by name within each.

## Data and interfaces

No migration: the API role already reads `metrics`, `metrics_1m` and `metrics_1h`.

**`WS /api/ws/metrics`**

| Direction | Message |
|---|---|
| Browser → backend | `{"type":"subscribe","view":"overview"\|"full","server_ids":[…]}`. Replaces the previous subscription. At most 200 servers and 16 kB. |
| Backend → browser | `{"type":"subscribed","server_ids":[…],"denied":[…]}` after each subscribe, and again when a recheck drops a server. |
| | `{"type":"overview","server_id","time","cpu","mem","load","disk":{"mount","percent"},"rx","tx"}`. A value the sample lacks is `null`. |
| | `{"type":"sample","server_id","time","readings":[[metric,instance,value],…]}` in the `full` view. |
| | `{"type":"error","detail":"invalid_message"}`. The socket stays open. |

Close codes: `4401` not signed in (the browser goes to sign-in), `1013` the browser reads too slowly, `1011` Valkey cannot be reached. A handshake with a foreign `Origin` is refused with 403.

**`GET /api/servers/{server_id}/metrics?range=…&metric=…`** (guard: `require_group_visible`). Up to 16 metric names, all their instances. Answer: `{range, step_seconds, start, end, series:[{metric, instance, time:[…], avg:[…], min:[…], max:[…]}]}`. `min` and `max` are `null` for `live`. A step without samples is left out.

| Range | Window | Read from | Step |
|---|---|---|---|
| `live` | 15 minutes | `metrics` | every sample |
| `1h` | 1 hour | `metrics` | 10 seconds |
| `6h` | 6 hours | `metrics_1m` | 1 minute |
| `24h` | 24 hours | `metrics_1m` | 5 minutes |
| `7d` | 7 days | `metrics_1m` | 30 minutes |
| `30d` | 30 days | `metrics_1h` | 2 hours |
| `1y` | 365 days | `metrics_1h` | 1 day |

An average over rollup buckets is weighted by their sample counts, like `metrics_1h`.

**`GET /api/metrics/overview?server_id=…`** (up to 200). Answer per visible server: the newest values of the last 5 minutes in the shape of an `overview` message, plus `trend`: 60 five-second averages of CPU and memory. Also `denied`.

**Performance cards**

| Card | Lines | Also |
|---|---|---|
| CPU | CPU used | User, system, I/O wait and steal as numbers; a small chart per core |
| Memory | Memory used, swap used (bytes) | "of 16 GiB" |
| Load | 1, 5 and 15 minutes | |
| Network | Received, sent | Select: all interfaces or one |
| Disk I/O | Read, written | Select: all disks or one; busy % |
| Filesystems | Space used, inodes used of one filesystem | Select, starting on the fullest; a table of all |

Each card reads its own series, so one failed read does not empty the tab.

## Error handling and edge cases

- **No session, a pending session or an expired one**: the socket closes with `4401`. Every 30 seconds the backend checks the session again without touching it, so a revoked or idle session loses its socket within 30 seconds.
- **A server the person does not see, or that does not exist**: listed in `denied`, never subscribed. For an existing one, `access.denied` is recorded once per socket (and per overview read). A recheck that finds a lost grant, a moved or a removed server drops it and sends `subscribed` again.
- **Cross-site WebSocket hijacking**: an `Origin` whose host differs from the request's `Host` is refused. A request without `Origin` (not a browser) is allowed, since it carries no ambient cookie. The upstream proxy must pass `Host` and allow WebSocket upgrades (README).
- **The socket drops**: the badge shows "Reconnecting…", retries run after 1, 2, 4 … 30 seconds, and the 15-second re-read also reads the overview, so values keep moving. After the reconnect the gap is filled from REST.
- **Hidden tab**: the socket closes. It opens again, and history is read again, when the tab is visible.
- **A slow browser**: 1,000 waiting messages close the socket with `1013`; the browser reconnects and refills.
- **Unreachable server**: its card keeps the last values of the last 5 minutes, greyed, with the reason, then shows dashes. Charts show a break wherever two points are more than three steps apart.
- **First sample after a connect** has no rates: those values are `null` and the screen keeps the previous ones.
- **"All interfaces" or "All disks"**: the lines are sums, and no band is drawn, because lows and highs of different devices cannot be added.
- **Changing the range**: the charts keep the previous drawing, dimmed, until the answer arrives. A card whose read failed says so and offers "Try again". A range without data says "No data in this range".
- **1-day steps** are cut at midnight UTC. Axis labels use the browser's time zone.
- **Windows servers** have no Performance tab and no live strip. The strip is also hidden while a Linux server is not monitored.
- **More than 200 servers on screen** cannot happen in practice; the backend answers `invalid_message`.

## Testing

Tests first.

- **Backend, unit**: `summarize` (fullest filesystem, summed interfaces, missing rates); the range table; `Subscription` adds and removes servers while reading.
- **Store** (real TimescaleDB): every range returns the right steps, averages, lows and highs; the weighted average over rollups; `read_overview` gives the newest values and 60 trend slots.
- **REST**: the guard (404 for an unseen server), unknown range or metric name (422), the 16-metric and 200-server limits, `denied`.
- **Socket** (real Valkey): no cookie and a pending session close with `4401`; a foreign `Origin` gets 403; a published sample arrives as `overview` or as `sample`; a server of another group is denied, is recorded as `access.denied`, and its samples never arrive; a new subscribe replaces the old one; an ended session and a removed grant are noticed by the recheck; an invalid message; the full queue.
- **Security suites**: a new socket-coverage suite pins every WebSocket route and requires its handshake to use `auth/socket.py`; `unknown_routes` accepts pinned sockets only. The overview route is pinned in `ANY_SIGNED_IN` with its reason. `make test-security` and `AGENTS.md` name the new suite.
- **Frontend, unit**: formatters, `toneOf` at 79, 80, 89 and 90, the trend buffer, merging and gaps; `live-socket` with a fake WebSocket (subscribe, resubscribe after a reconnect, backoff, `4401` goes to sign-in, closes while hidden).
- **Frontend, components**: the Dashboard with ten servers updates each one from socket messages without a reload (the task's "done when"); the switch and filters keep the address; only servers on screen are subscribed; the order; the unreachable and not-monitored cards. The server page: the strip, the tab for Linux only, the range in the address, each card with data, without data and after a failed read.
- **Theme**: `themeTokens.test.ts` knows `--chart-3`. The three chart colours are checked with the dataviz palette validator on both surfaces during the build (this read-only stage could not run it). If a pair fails, `--chart-3` changes, never the Knowledge Base's `--chart-1` and `--chart-2`.
- **Stack**: the placeholder `test_a_websocket_upgrade_reaches_the_backend` is replaced: ten server rows point at the fake server, and one socket through Caddy receives `overview` messages for all ten. The plan checks the fake server's sshd limits for ten sign-ins.
- **Docs**: README gets the Dashboard, the Performance tab, the idle rule and the proxy requirements.

## Out of scope

- Firing alerts on the Dashboard and alert rules (MITA-29).
- Pushing state changes over the socket, and replacing the 15-second re-reads of the Servers pages.
- Custom date ranges, zoom, comparing servers, a table view or a download of a chart.
- Sorting the Dashboard by a metric, and settings for the thresholds.
- Container and process metrics, Windows servers.
- A limit on sockets per person, and more than one backend replica.
- `query_metrics` for agents and the report charts (Phases 4 and 7).
