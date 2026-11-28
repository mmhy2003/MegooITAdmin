# MegooITAdmin

## Run it

You need Docker with Compose v2 and GNU Make. On Windows, run `make` from Git Bash.

    make up

This creates `.env`, pulls the images of the latest release (`ghcr.io/mmhy2003/megooitadmin-backend` and
`-frontend`, for amd64 and arm64) and starts Caddy, the frontend, the backend, the collector, the database and
Valkey, and returns once the app answers. It pulls only images that are missing.
The app is then at `http://<this host>/`, and `curl http://localhost/api/health` gives `{"status":"ok"}`.
`make down` stops it and keeps the data; `make` lists every target.

### First start

- After the first `make up` nobody can use the app yet. Run `make setup-code`, or look in `make logs` for
  `Setup code:`, then open the app: it shows the setup page.
- Enter the code, the Owner's name, email and a password of 12 to 128 characters. Then scan the QR code with an
  authenticator app and enter its code.
- Save the ten recovery codes: each signs in once if the phone is lost.
- Every sign-in then asks for the password and a code. A session ends after 1 hour without use and 12 hours after
  sign-in (`SESSION_IDLE_MINUTES`, `SESSION_ABSOLUTE_MINUTES`).

- **`.env`.** The first `make up` creates `.env` with three random database passwords. `POSTGRES_PASSWORD` is the
  owner's, used only at start-up to migrate. `POSTGRES_API_PASSWORD` belongs to `megooitadmin_api`, the
  restricted role the backend serves as, and `POSTGRES_COLLECTOR_PASSWORD` to `megooitadmin_collector`, the
  restricted role the collector writes samples as. Keep this file: the database keeps the owner's password it was
  first started with, so a new one would lock the backend out. `make up` and `make upgrade` add
  `POSTGRES_API_PASSWORD` and `POSTGRES_COLLECTOR_PASSWORD` to an older `.env` and change nothing else.
  `.env.example` explains every variable.
  `make up` also writes `AUTH_SECRET_KEY`, which encrypts the authenticator secrets. Keep it: with another key no
  code can be checked and everyone needs `make reset-mfa`. `make up` adds it to an older `.env`.
- **The port.** Caddy is the only service with a published port, 80 by default. Set `MEGOOITADMIN_HTTP_PORT` in
  `.env` to use another one, or an address and port such as `127.0.0.1:8080` (for example when port 80 is taken
  or Docker is rootless).
- **TLS.** Caddy serves plain HTTP. Put a TLS proxy in front of it on a private address: Caddy trusts the
  `X-Forwarded-*` headers only from private addresses.
- **WebSockets.** A proxy in front of Caddy must pass the `Host` header unchanged and allow WebSocket upgrades on
  `/api/ws/`. The backend refuses a socket whose `Origin` names another host.
- **A second copy.** `make up STACK=dev` starts the project `megooitadmin-dev` on `127.0.0.1:8080`, beside the
  real one, with throwaway values. It builds the images from this checkout (`docker-compose.build.yml`) under the
  local names `megooitadmin-backend:dev` and `megooitadmin-frontend:dev`. Pass the same `STACK=dev` to `down`,
  `logs`, `migrate` and `shell-backend`. `make upgrade` refuses a `STACK=`: run `make up STACK=dev` again instead.
- **API docs.** `/api/docs` is served only with `API_DOCS=true` in `.env`, and the dev stack sets it.

### Upgrade

    git pull
    make upgrade

- Run `git pull` first, so the Compose file and the images belong to the same release.
- `make upgrade` pulls every image of the stack, Caddy and the database included, and restarts what changed.
  It also pulls the Valkey image and creates its `valkey_data` volume the first time, and starts the collector,
  so nobody has to act.
- It also adds `POSTGRES_LOGS_PASSWORD` to `.env` when it is missing and starts the `logs` service, so nobody has
  to act. Run one `logs` service.
- To stay on a release, set `MEGOOITADMIN_VERSION=0.1.0` in `.env`. `make upgrade` then pulls that version until
  the line changes.
- Each release note's "Upgrading" says what else the release needs.

### Lost access

- `make reset-mfa email=<email>` makes that account set up a new authenticator at the next sign-in.
- `make reset-password email=<email>` asks twice for a new password, sets it and unlocks the account.
- Both end the account's sessions and are recorded in the audit log, and both take `STACK=` for the copies.
- After five failed attempts an account is locked for 15 minutes.

### People and access

- The Owner invites a person on Settings → Users and gets a one-time link. The app emails only alerts (see
  [Alerts](#alerts)), not invitations: pass the link on by hand. It is valid 7 days. The person opens it, chooses a password and sets up an authenticator.
- Roles are given per server group (Settings → Server groups). A person is Admin or Operator on each group, or
  has no access to it, and each group's role carries seven switches. Connect SSH, View processes and View logs
  are checked so far; the other four are kept for the features that use them.
- Auditor and Owner are platform-wide and cover every group. Everyone sees their own access on Profile and
  security.
- An account is disabled, never deleted: its sessions end and it can be enabled again. Every change to a person,
  a role or a switch is recorded in the audit log with before and after.
- `make reset-password` and `make reset-mfa` still work for every account.

### Servers

- The Owner, and an Admin in their own groups, register, edit, move and remove servers on the Servers page.
  Moving a server to another group needs Admin on both groups.
- A server lives in exactly one server group, and the group decides who sees it: everyone with a role in the
  group sees it, and so do the Owner and Auditors. Nobody else does.
- Tags are free labels typed on the server. They filter the list and never decide access.
- A group that still holds servers cannot be deleted: move or remove its servers first.
- Prepare each Linux server with the setup script (Platform access card → Download, or
  `backend/app/ssh/megoo-setup.sh`): it creates `megoo` in `systemd-journal` and `adm`, never in `docker`, allows
  it only `megoo-ctl` with sudo, and accepts the platform's key only from the platform's address. See
  [docs/server-setup.md](docs/server-setup.md). MegooITAdmin never signs in as root, and refuses root as the login
  account.
- The platform's public key is on each server's Platform access card, in the command to run, and
  `make ssh-public-key` prints it.
- The Owner, or an Admin of the server's group, pins the server's host key after comparing its fingerprint with
  the one on the server: `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`.
- People with Connect SSH in the group test the connection from the server page. The test checks seven things:
  the host key, the platform's key, not root, not in `docker`, the log groups, `megoo-ctl` through sudo, and that
  sudo allows nothing else.
- A changed host key blocks the server until an Admin accepts the new key, with a reason, or keeps the pinned one.
  Every step is in the audit log.
- Once a Linux server's host key is pinned, the collector signs in as its login account from the platform's
  address and keeps one channel open, sampling every 5 seconds by default (1 to 10, `metrics_interval_seconds` in
  the API). A server without a sample for 30 seconds is unreachable. Run one collector: a second one would publish
  every sample twice. See [What the collector runs](docs/server-setup.md#what-the-collector-runs).
- The Servers list (Status column) and each server's page (a badge beside the name and the Monitoring card) show
  whether the collector reaches the server: Reachable, Unreachable with the reason and what to do, Not monitored
  (Windows, or a host key not pinned or changed) or Not checked yet. The Owner and Admins of the group set a Linux
  server's sample interval in the Register and Edit dialog.
- A Linux server's Overview shows Services, Updates, Failed sign-ins, Certificates, Top processes (needs the View
  processes right) and a Containers summary, each with when it was last checked. The Containers tab lists the
  Docker containers grouped by Compose project. A result older than three intervals shows in amber. The intervals
  are fixed: containers and processes 30 seconds, services 1 minute, failed sign-ins 5 minutes, updates 1 hour and
  certificates 6 hours. See [Slow checks](docs/server-setup.md#slow-checks).
- A Linux server's Overview starts with a live strip, hidden while the server is not monitored. The Performance
  tab shows CPU (user, system, I/O wait, steal, per core), memory and swap, load, network, disk I/O and
  filesystems. Live covers the last 15 minutes sample by sample. 1 hour, 6 hours, 24 hours, 7 days, 30 days and
  1 year read the samples or the 1-minute or 1-hour rollups, and a light band shows the lowest and highest value of
  each step. Times show in the browser's time zone, and 1-day steps are cut at midnight UTC.
- Both pages re-read the servers every 15 seconds while the tab is visible. These re-reads carry
  `X-Megoo-Background: 1` and do not count as activity, so a page left open still signs out after
  `session_idle_minutes`. The live socket and the 60-second re-read of the charts never count as activity either: a
  Dashboard or Performance tab left open signs out after `SESSION_IDLE_MINUTES`, so a wall screen needs a higher
  value.
- Back up the `ssh_key` Docker volume: it holds the platform's private key, and a lost key means a new one has to
  go on every server.
- Windows servers connect from Phase 2.

### Dashboard

- The Dashboard lists every server the person sees, as cards or a table (Cards/Table switch; `?view=table` keeps
  the table in the address), narrowed by the group and tag filters of the Servers page.
- A summary counts the servers by state. Servers with a problem come first: unreachable, then reachable, then not
  monitored or not checked yet, by name.
- Each Linux server shows CPU, memory, its fullest filesystem, load (1 minute) and network, updated live over one
  WebSocket for the servers on screen. CPU and memory carry a 5-minute sparkline.
- A percentage turns amber with ▲ from 80% and pink from 90%. This is a visual hint only: alerts come from the
  alert rules below.
- An unreachable server keeps its last values for 5 minutes, greyed, with the reason.

### Alerts

- An alert rule is a threshold plus a duration, such as "space used above 90% for 10 min". Only the Owner sets the
  rules, on Settings → Alert rules: create, edit, switch off or delete. Every change is in the audit log.
- A rule watches CPU used, memory used, filesystem space or inodes used, load (1, 5 or 15 minutes) or
  "unreachable for N minutes". Load is per CPU core: 1.0 means every core is busy. Each filesystem is its own
  alert, so two full filesystems give two alerts. A duration of 0 fires at the first sample.
- A rule applies to all servers, one server group or one server, and has the severity Warning or Critical. Every
  rule that applies to a server counts on its own: a stricter rule for one server is a second rule.
- The upgrade adds four starter rules for all servers, which the Owner can edit, switch off or delete:

  | Rule | Condition | Severity |
  |---|---|---|
  | Filesystem almost full | Space used above 90% for 10 min | Critical |
  | Memory almost full | Memory used above 90% for 10 min | Warning |
  | CPU busy | CPU used above 90% for 15 min | Warning |
  | Server unreachable | Unreachable for 5 min | Critical |

- The collector checks every sample. An alert fires once its condition has held for the rule's whole duration, and
  is resolved by the first sample that no longer meets it. "Unreachable" counts from when the server was marked
  unreachable, and resolves at the next sample. An alert ends instead (shown as Ended) when its rule is changed,
  switched off or deleted, or when the server is no longer monitored (a changed or unpinned host key). Renaming a
  rule ends nothing. While the collector is stopped nothing is checked, and firing alerts stay firing.
- Everyone who sees a server sees its alerts: on the Dashboard (the Firing alerts tile, the Alerts card with
  Firing and History, and a mark on the server's card or row), on the server's Alerts tab with a banner above the
  tabs (Linux only), and under the bell in the header, which counts what is new and lists the 10 latest events.
- Settings → Notifications (Owner only) sends one message when an alert fires and one when it is resolved or ends,
  with no reminders in between:
  - **Email**, through the SMTP server set there, to the Owner and the Admins of the server's group at their
    account address, plus up to 20 extra addresses that get every alert. Everyone is in Bcc. Disabled accounts get
    nothing. "Send a test" mails the Owner.
  - **Channels**, up to 20: Generic JSON (a versioned JSON body), Slack-compatible (`{"text": …}`) and Telegram
    (a bot token and a chat ID).
  - Email and each channel are "Warning and Critical" or "Critical only".
- A message that fails is tried six times over about an hour (at once, then after 30 seconds, 2, 5, 15 and 40
  minutes), then marked failed, and the channel's row shows the error.
- The SMTP password, webhook URLs and bot tokens are encrypted in the database with a key derived from
  `AUTH_SECRET_KEY`, and never shown again: the page shows only the host or the chat. A new `AUTH_SECRET_KEY`
  means typing them again.
- A webhook URL must be `https://`. `WEBHOOK_ALLOW_HTTP=true` in `.env` also allows `http://`: set it on test
  stacks only (the dev, e2e and stack-test stacks do).

### Live logs

- People with View logs in a server's group follow its logs live, and so does the Owner. Auditors never do. They
  follow them on the Logs page, across servers, and on a server's Logs tab, which shows to people with View logs
  on that server. The WebSocket `/api/ws/logs` serves both.
- A Linux server has three kinds of source: its journal (optionally one unit, a priority and worse, and this boot
  only), one file that the group's allowlist allows, and one Docker container.
- Each server group has its own file allowlist. The upgrade gives every group, and a new group, four starter
  patterns: `/var/log/syslog`, `/var/log/messages`, `/var/log/nginx/*.log` and `/var/log/apache2/*.log`. The Owner
  and the group's Admins change them through `/api/server-groups/{id}/log-allowlist`. A wildcard stays inside one
  path segment, so `/var/log/*.log` does not reach `/var/log/nginx/access.log`. A group has at most 50 patterns.
  One dialog edits them, and it has two doors: Settings → Server groups → Log files (the Owner), and Manage
  patterns in the file picker (the Owner and the group's Admins).
- The viewer follows the newest lines. Scrolling up pauses it, and "Jump to latest" follows again. Each source
  keeps its last 10,000 lines.
- Text and regex filters ignore case and highlight what they match. Five switches show or hide the levels, read
  from the journal priority or from the text of the line. Sources show side by side or merged by time, with ANSI
  colours, Wrap, and times in Local or UTC. Each pane downloads the lines it holds after its filters.
- The address holds the view: its sources and its settings. Copy it to share what is on screen.
- Saved views keep a name, the sources and the settings, private or shared. A shared view shows to people who
  hold View logs on every server of it. Its owner and the Owner change or delete it; others save it as a new
  view. A person has at most 100 views. The audit log records `log_view.created`, `log_view.updated` and
  `log_view.deleted`.
- A stream that ends for a passing reason (the worker unavailable or restarted, the server unreachable, an SSH
  error) is retried 5 times, then waits for the person.
- A viewer first gets the last 200 lines, then the new ones. The `logs` worker opens one SSH channel per source,
  shared by everyone who watches it, and closes it a few seconds after the last viewer leaves.
- A source sends at most `LOG_STREAM_MAX_LINES_PER_SECOND` lines a second (2000 by default). The lines above it are
  dropped, and the viewer is told how many were skipped.
- Sources end after `LOG_STREAM_IDLE_MINUTES` (30 by default) without activity in the log view. Reading lines does
  not count as activity.
- Log lines are never stored. The audit log records each opened stream (`logs.stream_opened`: the person, the
  server and the sources) and its end (`logs.stream_closed`), and every allowlist change
  (`log_allowlist.pattern_added`, `log_allowlist.pattern_removed`).
- Run one `logs` service: a second one would open every source twice. See
  [What the logs worker runs](docs/server-setup.md#what-the-logs-worker-runs).
