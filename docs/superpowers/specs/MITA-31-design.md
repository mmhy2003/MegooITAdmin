# MITA-31 design: live log viewer, saved views and the allowlist editor

## Goal

People with View logs follow a server's journal, its allowlisted files and its containers in the browser: on the Logs page across servers, and on a server's new Logs tab. They filter, pause, merge, download and save what they watch as a view, private or shared. The Owner and a group's Admins manage the group's log file patterns in a dialog.

Mockup **v1** is the picture of every screen. Phase 1 exit: an admin follows a container's logs and a journal unit side by side.

## Decisions

| Decision | Chosen | Why, and what was rejected |
|---|---|---|
| Saved views | **In this design** (your answer) | A saved view is a name plus the state the viewer already keeps in the address. Rejected: a follow-up task. |
| Picking a unit and a file | **Typed, with help** (your answer) | No new command on servers. A list is the follow-up task below. Rejected: unit names from the collector, live discovery by the worker. |
| Allowlist editor | **In this design, two doors to one dialog** (your answers) | A "Log files" button per group on Settings → Server groups (the Owner), and "Manage patterns" in the file picker (the Owner and the group's Admins, who cannot open Settings). |
| The list | **TanStack Virtual** (your answer) | `@tanstack/react-virtual` measures rows, anchors to the end and follows appended rows. Rejected: our own windowing, CSS `content-visibility`. |
| Level of file and container lines | **Read from the text** (your answer) | A line without a level word shows only while "No level" is on. Rejected: journal lines only. |
| Who sees a shared view | **People who hold View logs on every server of the view** (your answer) | Nobody gets a half-working view. Rejected: at least one server. |
| Who changes a shared view | **The person who saved it, and the Owner** (your answer) | Others use "Save as a new view". |
| Times | **Browser's time zone, with a Local / UTC switch** (your answer) | No time zone is stored per person. |
| Layout | **Mockup v1** (your answer) | |

Decisions I made (say so if you want one changed):

1. **The address holds the view**: sources, filter, levels, layout, wrap and the time switch. A reload or a pasted link shows the same view, as the Servers page does with its filters. Nothing goes into browser storage.
2. **The socket protocol does not change.** The viewer is a client of `/api/ws/logs` as MITA-30 built it. The only backend additions are `can_view_logs` on a server, and the saved views.
3. **Filters run in the browser** on the lines it holds. They never change what the server streams. A journal's priority is part of the source, as in MITA-30.
4. **Filters ignore case.** There is no match-case switch.
5. **Five level switches**: Error (emerg, alert, crit, err), Warning, Info (notice, info), Debug, No level.
6. **Download is per pane**: the lines that pane holds after its filters, not only the rows in sight.
7. **The log socket stays open in a hidden tab**, unlike the metrics socket: a paused stream would lose lines. The 30-minute idle rule closes forgotten views.
8. **A stream that ends for a passing reason is retried up to 5 times**, then waits for the person. Every retry is an opened and a closed audit event, so it must be bounded.
9. **A container source also remembers the container's name.** Compose recreates containers with new IDs, and a saved view would break at every deploy. The viewer follows the one container of that name when the ID is gone.
10. **ANSI**: the 16 foreground colours, bold, dim, italic and underline, drawn with theme tokens. 256-colour and true-colour codes fall to the nearest of the 16. Background colours and every other escape sequence are dropped.
11. **The Logs tab has no Views menu.** "Open in Logs" carries its state to the Logs page.
12. **The Logs tab shows only with View logs** on that server. The Containers tab gets a "Logs" link per row under the same rule.

## Architecture

**Frontend, pure logic in `frontend/src/lib/logs/`** (each with Vitest tests)

| File | Holds |
|---|---|
| `sources.ts` | The three source types, their labels, the field rules of `backend/app/logs/sources.py`, the address codec, and the comparison of a source with the socket's description of it. |
| `socket.ts` | `LogSocket`: the `/api/ws/logs` client. Reconnects with `BACKOFF_MS`, sends the wanted set after every open and every change, goes to sign-in on `4401`, sends `active`. |
| `store.ts` | `LogStore`: per source its rows, state, skipped total and retry count. Takes the socket's messages, notifies at most once per animation frame. |
| `ansi.ts` | SGR codes to styled segments, and the plain text of a line. |
| `levels.ts` | The level group of a line: from the journal priority, else from the text. |
| `filter.ts` | Compiles the filter (text or regex), tests a line, gives the ranges to highlight. |
| `merge.ts` | Orders rows of several sources by time. |
| `download.ts` | The text file of a pane and its name. |
| `allowlist.ts` | `checkPattern` and `matches`, ports of `backend/app/logs/allowlist.py`. |
| `views.ts` | The saved view types, the API calls, and "does the address differ from the saved view". |

**Components in `frontend/src/components/logs/`**

| Component | Does |
|---|---|
| `LogViewer` | The toolbar and the panes for one state. Owns the `LogSocket` and `LogStore`. Used by the page and the tab; `serverId` fixes the server. |
| `LogToolbar` | Filter, regex switch, match count, levels, layout, wrap, Local / UTC. |
| `LogPane`, `LogList`, `LogLine` | A pane with its header, the virtualised list, one row. |
| `SourceDialog` | Add a source: server, then Journal, File or Containers. |
| `ViewsMenu`, `SaveViewDialog`, `DeleteViewDialog` | Saved views on the Logs page. |
| `LogsPage` | The Logs page: reads the address, the servers and the views. |
| `ServerLogsTab` | The server's tab: `LogViewer` with the server fixed. |

**Other frontend changes**

- `components/settings/allowlist-dialog.tsx`: the dialog. `groups-page.tsx` gets the "Log files" button per row.
- `app/(app)/logs/page.tsx`: `LogsPage` in a `Suspense` instead of the placeholder.
- `components/servers/server-page.tsx`: the `logs` tab, loaded with `next/dynamic` like Performance, when `server.can_view_logs`.
- `components/servers/checks/containers-tab.tsx`: the "Logs" link when `canViewLogs`.
- `lib/servers.ts`: `can_view_logs`. `lib/auth/messages.ts`: the new API reasons.
- `app/globals.css`: the ANSI classes and the highlight colour, from the theme's tokens.
- `package.json`: `@tanstack/react-virtual`.

**Backend**

- `app/inventory/servers.py`, `server_schemas.py`: `can_view_logs` (a Linux server and View logs in its group).
- `app/logs/models.py`: `LogView`. `app/logs/views.py`: the rules and the service. `app/logs/views_router.py`: the routes. `app/logs/schemas.py`, `actions.py`: the shapes and the three actions. `app/main.py` includes the router.
- Migration `0013_log_views.py`.
- Docs: the "Live logs" part of `README.md`.

### How the viewer works

- **Opening.** The viewer reads the sources from the address, the servers from `GET /api/servers`, and the containers of each server that has a container source. It opens the socket when it has a source and sends `subscribe` with the wanted set.
- **Rows.** A row is a line, or a marker ("1,240 lines skipped", "Reconnected"). A line keeps its raw text, its plain text (ANSI removed, made once on arrival) and its level group. ANSI is parsed when a row is drawn.
- **The cap.** A source keeps its last 10,000 rows. Old rows go in blocks of 1,000, so a trim is not paid per line.
- **Follow.** The list anchors to its end and follows appended rows while the person is within 24 px of the end. Scrolling up pauses the pane: its badge says Paused and "Jump to latest · n new" appears. Rows have stable keys (source, run, seq), which following through a trim needs.
- **Wrap.** Off: one fixed row height and a horizontal scrollbar. On: rows are measured.
- **Filter.** Typing is debounced 200 ms. A new filter is applied to the held rows in slices of 5,000 per frame, then to each row as it arrives. Matches are highlighted. The toolbar says "212 of 4,203 lines match".
- **Merged.** One pane with every source's rows ordered by time, then by source order and seq. Each row carries a coloured tag, server and source. A late line is inserted at its time.
- **Side by side.** Up to three panes in a row, then a new row. Under 768 px the panes stack.
- **Activity.** A pointer press, a key, a wheel or a scroll inside the viewer sends `active`, at most once a minute.

## Data and interfaces

### The address

Used by `/logs` and `/servers/{id}?tab=logs`. A default is left out.

| Parameter | Value |
|---|---|
| `src` (repeated, at most 16) | `j~<server>~<unit>~<priority>~<1 for this boot>`, `f~<server>~<path>`, `c~<server>~<container id>~<name>`. `~` is in no unit, path or container name. An entry that breaks a rule is dropped. |
| `q`, `re=1` | The filter, and whether it is a regex. At most 200 characters. |
| `lv` | The levels that are on, when not all five. |
| `layout=merged`, `wrap=1`, `tz=utc` | |
| `view` | The saved view this came from (Logs page only). |

Opening a view from the menu loads it and writes its state into the address. The view counts as changed while the address differs from what is saved.

### `log_views` (migration `0013`)

| Column | |
|---|---|
| `id` | UUID |
| `owner_id` | `users.id`, deleted with the user |
| `name` | 1 to 80 characters, unique per owner without regard to case |
| `shared` | boolean, default false |
| `sources` | JSON: 1 to 16 sources, each the socket's source, a container also with `name` |
| `settings` | JSON: `q`, `regex`, `levels`, `layout`, `wrap`, `utc` |
| `created_at`, `updated_at` | |

`megooitadmin_api` gets `SELECT, INSERT, UPDATE, DELETE`, declared in `API_GRANTS`. The other roles get nothing.

### Saved views API

| Route | Who | Does | Audit |
|---|---|---|---|
| `GET /api/log-views` | Signed in | The person's own views, and the shared views whose every server is a Linux server they hold View logs on. Each: `id`, `name`, `shared`, `owner_name`, `is_mine`, `can_edit`, `sources`, `settings`, `updated_at`. | none |
| `POST /api/log-views` | Signed in | Saves `{name, shared, sources, settings}`. A server the person does not see: 404. No View logs on one: 403. `409 view_name_taken`, `409 too_many_views` (100 per person), 422 invalid. | `log_view.created` |
| `PUT /api/log-views/{id}` | Its owner, the Owner | Replaces the four fields, with the same checks. A view the person cannot see: 404. One they see but may not change: 403. | `log_view.updated` |
| `DELETE /api/log-views/{id}` | Its owner, the Owner | Deletes it. Same 404 and 403. | `log_view.deleted` |

- The Owner sees every shared view. Nobody but its owner sees a private one.
- A file path is not checked against the allowlist when a view is saved: the allowlist changes, and the socket decides at open.
- The events carry the view as target (`log_view`) and the before and after of name, shared, sources and settings.
- The four routes are pinned in `ANY_SIGNED_IN` of the permission-coverage suite, with the reason that each filters or checks by the person itself.

### `can_view_logs`

`GET /api/servers` and `GET /api/servers/{id}` answer `can_view_logs`: the server is Linux and the person holds View logs in its group.

### The socket, as the viewer uses it

- `subscribe` always carries the full wanted set, without the sources that wait for the person (ended for good, refused).
- A `subscribed` answer is matched to the viewer's sources by comparing the described source field by field. Its `id` then names the source in `lines`, `skipped` and `ended`.
- **A backlog after a reconnect.** If the backlog holds the row the pane last got (same seq, time and text), only the newer rows are added. If not, a "Reconnected" marker goes in and the whole backlog follows, under a new run number.

| What arrives | The pane |
|---|---|
| Denied `not_found`, `forbidden`, `not_allowed`, `not_an_ssh_server`, `host_key_not_pinned`, `host_key_changed`, `too_many_sources` | Says why, in words. `not_allowed` offers "Manage patterns" to those who may. Waits for the person. |
| Ended `worker_unavailable`, `worker_restarted`, `unreachable`, `ssh_error` | "Retrying", with "Try now". Up to 5 tries, after 2, 5, 15, 30 and 30 s (`worker_restarted`: the first at once). A backlog resets the count. Then it waits. |
| Ended `exited` (with status), `not_readable`, `not_available`, `denied`, `key_refused`, `host_key_changed`, `forbidden`, `not_found`, `not_allowed` | Says why, keeps its lines, offers "Reconnect". |
| Ended `idle` (every source) | A banner over the panes: paused after 30 minutes, with "Resume". |
| `skipped` | A marker row at the gap, and the total in the pane's header. |
| Socket closed (`1013`, `1011`, the network) | The badge says Reconnecting; the socket reconnects with backoff and subscribes again. |

### Levels from text

For a line without a journal priority, the first level word in its first 200 plain characters: bare in upper case (`FATAL`, `CRITICAL`, `ERROR`, `ERR`, `WARN`, `WARNING`, `INFO`, `NOTICE`, `DEBUG`, `TRACE`), or in any case inside `[...]`, after `level=` or `lvl=`, or as a JSON `"level"` value. `FATAL`, `CRITICAL`, `PANIC`, `EMERG` and `ALERT` count as Error; `TRACE` as Debug.

### Download

A text file made in the browser: one line per row, the time with its offset in the chosen zone, the server and source in a merged pane, then the plain text. Markers become `#` lines. Name: `logs-<server>-<source>-<date>-<time>.log`, or `logs-merged-…`.

### Add a source

- **Server**: the Linux servers with `can_view_logs`, by group. Fixed on the Logs tab.
- **Journal**: an optional unit, a priority ("warning and worse"), "This boot only".
- **File**: a path. The group's patterns show below it; one without a wildcard is offered as you type. A path that matches none cannot be added.
- **Containers**: the server's containers by Compose project, with their state. Several can be ticked.
- Limits, said in the dialog: 16 sources in a view, 8 per server.

### Allowlist dialog

Uses the three routes of MITA-30. It lists the group's patterns with Remove, and adds one. It says the server's reasons in words: invalid, `pattern_exists`, `too_many_patterns`. Someone who cannot manage the group sees the patterns only in the file picker, read-only.

## Error handling and edge cases

- **No View logs anywhere**: the Logs page says so and names where the Owner grants it. An Auditor sees this.
- **No source yet**: the page offers "Add source" and the views.
- **A server removed or moved out of sight**: its sources show "Unknown server" and the socket's `not_found`.
- **A recreated container**: before subscribing, an ID the server no longer lists is swapped for the one container with the stored name, and the address is updated. No such container, or two: the worker's answer shows.
- **An invalid regex**: the field turns pink with "Not a valid regular expression", and the last valid filter stays.
- **A slow regex** can stall the person's own tab. The filter is capped at 200 characters and applied in slices, so the page stays usable between slices. A shared view carries its regex to others under the same cap.
- **A burst**: redraws are once per frame whatever the rate, and the cap bounds memory (16 sources of 10,000 rows).
- **A line over 8 kB** arrives cut and marked `truncated`: the row ends with "…".
- **A view that names a lost server** stays in its owner's list, so they can fix or delete it, and leaves everyone else's.
- **A view deleted or unshared while open**: the address keeps working without the `view` link, and the menu reloads.
- **A disabled owner**: their shared views stay. The Owner can delete them.
- **Two tabs on one source** share the worker's one channel, as two people do.
- **Session ended** (`4401`): the socket closes for good and the page goes to sign-in, as the metrics socket does.
- **Accessibility**: a pane is `role="log"` with `aria-live="off"`, the switches are pressed buttons, and a level is a text tag (ERR, WRN) besides its colour.

## Testing

Tests first.

- **Backend views**: create, list, replace, delete; the shared rule (every server, Linux, View logs) for an Operator of one group, an Admin of two, the Owner and an Auditor; a private view is nobody else's; 404 and 403 on change; the name clash without regard to case; the 101st view; invalid sources and settings; the three events with before and after.
- **Backend rest**: `can_view_logs` per role and OS; migration `0013` down and up; the declared grants are the exact ones; audit-coverage and permission-coverage know the four routes.
- **`lib/logs` units**: the address codec both ways and with broken entries; ANSI (the 16 colours, 256 and true colour, bold, stripped sequences); the level table; the filter (text, regex, invalid, highlight ranges); the store (backlog, live rows, the cap, skipped markers, the continuity rule, every ended and denied reason, the retry schedule on fake timers, idle and resume); merge order with late lines; the download text; `matches` and `checkPattern` against the cases of the backend's tests.
- **`LogSocket`** on `FakeWebSocket`: subscribe after open and after a change, the reconnect backoff, `4401`, `active` at most once a minute, open while the tab is hidden.
- **Components** (Testing Library): the viewer subscribes to the address's sources and shows their lines; filter, levels and highlight; pause and "Jump to latest"; merged and side by side; wrap; Local and UTC; each pane state of the table above; the source dialog per kind, its path check and its limits; the Views menu per person (owner, another reader, the Owner), save, save as, rename or share, delete; the allowlist dialog and both doors; the Logs tab and the Containers link only with `can_view_logs`; the empty states. The list is given a fixed size in jsdom through a test helper.
- **Guards that stay green**: `storage.test.ts` (no browser storage), `themeTokens.test.ts` (colours only in `globals.css`).
- **Stack**: through Caddy, `/logs` answers, and a view saved by one person is listed for another who holds View logs on its server.
- All gates: backend `pytest`, `-m docker`, `-m stack`, `make test-security`, frontend `tsc`, ESLint, `npm test`, the image test.

## Out of scope

- A list of a server's units and of the files that match a pattern (the follow-up task).
- "Send to assistant" (Phase 4).
- Storing or searching log history.
- Any change to the stream: the socket's messages, the worker, the caps.
- Podman and the Windows Event Log.
- A time zone or other viewer preferences stored per person.
- A match-case switch, and ANSI background colours.
- A log stream as a tab of the Sessions workspace (Phase 2).
