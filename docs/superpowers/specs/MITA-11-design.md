# MITA-11 design: SSH connect with host-key pinning, and the fake-server fixture

## Goal

After this task the Owner, or an Admin of a server's group, fetches the server's host key, confirms its fingerprint and pins it. Anyone with Connect SSH in the group then tests the connection, which signs in as `megoo` with the platform's key. A server that presents another key is refused before sign-in, flagged, and stays blocked until someone reviews the key. Every step is an audit event. Tests and dev stacks connect only to a fake server, a container running sshd. Mockup v1 shows the eight screens.

## What the repository looks like today

- `servers.host_key` exists and is always empty (MITA-10). The server page shows "Not pinned yet". There is no SSH code and no `asyncssh` dependency.
- `app/access` has the guards this task needs: `require_group_admin` (Owner, or Admin of the group) and `require_grant(Permission.CONNECT_SSH)`. Both answer 404 for a group the person does not see and record `access.denied`.
- The backend container runs as the unprivileged user `megooitadmin` (uid 10001). Compose already gives the backend the `servers` network.
- `make test-security` runs `tests/security` in the `test` service set, which starts only a database.
- The security suites read every route: a state-changing route must declare its audit actions, and a signed-in route must declare who may call it.

## Decisions

Answers from the owner:

1. **The platform's private key lives in a Docker volume, and the backend creates it at its first start.** Only the backend mounts the volume. Rejected: a host file beside `.env` (the backend's user could not read a root-only file without a chown), and the database encrypted with `AUTH_SECRET_KEY` (the API's database role could read it). Phase 3 moves the key into the vault.
2. **Anyone with Connect SSH tests a connection. The Owner and Admins of the group pin a key and accept a changed one.** Auditors only read. Rejected: only the Owner accepts a changed key, and Operators who cannot test.
3. **Mockup v1 is approved**, with these choices:
   - A server with a changed key stays blocked until someone reviews it, even when the old key comes back. The review either accepts the new key, which needs a reason, or keeps the pinned one.
   - Test connection also checks that the account is not root and not in the `docker` group, and fails otherwise.
   - The public key is shown on the server page to the people who can manage the server.
   - The test result is shown on the page only. Its history is the audit log.

Decisions I made (say so if you want one changed):

4. **One Ed25519 key for the whole platform.** Per-server keys and certificates come with the vault.
5. **One host key is pinned per server**, as an OpenSSH public key line. The fetch prefers Ed25519, then ECDSA, then RSA. The app shows its SHA256 fingerprint and type.
6. **The backend pins only a key it fetched itself.** The fetch stores the key as a candidate on the server row, and the pin request names the fingerprint the admin saw. A request cannot pin a key the backend never saw.
7. **All SSH goes through one module, `app/ssh/client.py`.** It is the only place that calls `asyncssh.connect`, always with the pinned key as the only trusted key, the platform key as the only credential, and no agent, password or user SSH config. A test fails if another module opens an SSH connection.
8. **Editing the address or the port keeps the pinned key.** The same machine at a new address still matches, and another machine is refused and flagged. An unconfirmed candidate is dropped on such an edit.
9. **The "alert" is a flag on the server plus an audit event.** The flag gives the badge in the list and the banner on the server page. The alert rules and notifications of Phase 1 can pick the event up later.
10. **The login account `root` is refused** when a server is registered or edited (422). The account check of the test still catches an account with uid 0 under another name.
11. **Only Linux servers have these actions.** A Windows server shows no host key row, no badge and no Test connection: nothing connects to Windows before Phase 2.
12. **A test or a fetch answers 200 with an outcome**, also when the connection failed, because the failed attempt is recorded too. What the remote side sent is never put into a response or an event: failures are a fixed set of reasons.
13. **The fake server is one image with real OpenSSH**, driven with `docker compose exec`, as `test_stack.py` already drives the backend. Rejected: an in-process asyncssh server (it is not sshd, and dev stacks could not use it), and a throwaway private key committed to the repository.

## Architecture

### Backend

| Package | Module | Change |
|---|---|---|
| `app/ssh/` (new) | `keys.py` | `ensure_key()` creates the key file once (mode 0600, created exclusively) and refuses a file readable by others. `load_key()` and `public_key()` read it |
| | `hostkeys.py` | Parses a public key line, gives its SHA256 fingerprint and its type |
| | `client.py` | `fetch_host_key(address, port)`: key exchange only, no sign-in. `connect(address, port, username, pinned)`: decision 7. Both raise one of `Unreachable`, `HostKeyChanged` (with the presented key when it can be read), `KeyRefused`, `SshError` |
| | `cli.py` | `python -m app.ssh.cli ensure-key` and `public-key` |
| `app/inventory/` | `connection.py` (new) | The four actions with their events: fetch, pin or replace, keep, test. `open_connection(server, …)` is the door later features use: it refuses a server without a pinned key or with a changed one, and on `HostKeyChanged` it flags the server and records the event in a transaction of its own, so a caller's rollback keeps both |
| | `connection_schemas.py` (new) | The bodies and results of the four routes |
| | `server_router.py` | The four routes under `/api/servers/{server_id}`, and `GET /api/ssh/public-key` |
| | `models.py`, `server_schemas.py`, `servers.py` | The new columns and response fields, decision 8 and decision 10. The `server.deleted` event also keeps the pinned fingerprint |
| | `actions.py` | The six new action names |
| `app/core/` | `config.py` | `SSH_KEY_FILE`, default `/var/lib/megooitadmin/ssh/id_ed25519` |

A test never holds a database lock while it talks to a server: it reads the row, connects, then writes the result. Pin and keep lock the row.

The connection test, in order: refuse without a pinned key or with a changed one; connect (10 seconds to connect, 10 to sign in); run `id -u; id -Gn` with a 5-second limit; report four checks: host key, platform key, not root, not in the `docker` group.

### Container and Compose

- `backend/Dockerfile` creates `/var/lib/megooitadmin/ssh` owned by `megooitadmin` with mode 0700, so a new named volume takes that ownership.
- `docker-compose.yml`: the backend mounts the new volume `ssh_key` there. No other service mounts it.
- `docker-entrypoint.sh` runs `python -m app.ssh.cli ensure-key` after the migrations. A key file with a wider mode stops the start.
- `Makefile`: `make ssh-public-key [STACK=]` prints the public key.

### Fake-server fixture (`tools/fake-server/`)

- **Image:** Debian slim with `openssh-server`. Key sign-in only. It makes fresh host keys at every start.
- **Accounts:** `megoo` (not root, not in `docker`, no sudo rule yet: later phases add the rules their features need), `megoo-docker` (in the `docker` group) and `megoo-root` (uid 0). The last two exist so the account check can be tested.
- **Two commands in the image:** `authorize-key` reads a public key on stdin and installs it for the three accounts. `swap-host-key` makes new host keys and restarts sshd.
- **Compose files:** `docker-compose.test.yml` publishes sshd on `127.0.0.1:${SSH_PORT}` for pytest on the host. `docker-compose.stack.yml` puts the service `fake-server` on the `servers` network without a published port.
- **`megoocolab.toml`:** the `test` set gains the first file and the port `SSH_PORT`. The `stack` set gains the second.
- **Dev and e2e stacks:** `make up STACK=dev` (or `e2e`) also starts the fake server and installs that stack's public key in it. `make fake-server-swap STACK=dev` swaps its host key, to try screens 5 and 6 by hand. Without `STACK=` neither exists: the real instance never gets a fake server.
- **pytest:** a `fake_server` fixture gives the host and port, installs the test run's public key, and offers `swap_host_key()`. `conftest.py` points `SSH_KEY_FILE` at a temporary file.

### Frontend

| File | Purpose |
|---|---|
| `src/components/servers/server-page.tsx` | The Test connection button, the state badge, the two banners, the host key row with fingerprint, type and pin date |
| `src/components/servers/host-key-dialog.tsx` (new) | Fetches the key when it opens, shows the fingerprint and the command to compare it. Pin this key is off until the box is ticked |
| `src/components/servers/review-host-key-dialog.tsx` (new) | Both fingerprints, the reason, Accept the new key and Keep the pinned key |
| `src/components/servers/connection-result.tsx` (new) | The result of a test with its four checks and what to do |
| `src/components/servers/platform-access-card.tsx` (new) | The two steps and the public key with Copy, only when `can_manage` |
| `src/components/servers/servers-page.tsx` | The badges "Host key changed" and "Host key not pinned" beside the name |
| `src/lib/servers.ts` | The new fields and types |
| `src/lib/auth/messages.ts` | Texts for the new refusals and the test results |

### Docs

`README.md`: the "Servers" section says how to prepare the `megoo` account, where the public key is, how a key is pinned, what a changed key means, and that the `ssh_key` volume must be backed up (a lost key means a new one on every server). `AGENTS.md`: the fake server and its two make targets under Safety, and the new suite in the Security suites line.

## Data and interfaces

### Migration `0007_host_key_pinning`

New columns on `servers`. No new table, so no new grant.

| Column | Type | Notes |
|---|---|---|
| `host_key` | text, null | Exists. Now holds the pinned key as `ssh-ed25519 AAAA…` |
| `host_key_pinned_at` | timestamptz, null | Set together with `host_key` (checked) |
| `host_key_offered` | text, null | The candidate: the key last fetched for pinning, or the key presented at a blocked connection |
| `host_key_offered_at` | timestamptz, null | |
| `host_key_changed_at` | timestamptz, null | Set when a connection met another key. While set, the server is blocked. Only with a pinned key (checked) |

### Routes

| Route | Who | Does | Audit events |
|---|---|---|---|
| `POST /api/servers/{id}/host-key/fetch` | Owner, or Admin of its group | Reads the server's key without signing in, stores it as the candidate, answers `{ok, reason, fingerprint, type}`. 409 `host_key_pinned` when a key is pinned | `server.host_key_fetched` |
| `PUT /api/servers/{id}/host-key` | Owner, or Admin of its group | Body `{fingerprint, reason?}`. Pins the candidate with that fingerprint. On a changed key it needs the reason (422 without) and removes the block. 409 `stale_host_key` when the candidate is another key or missing. 409 `host_key_pinned` when a key is pinned and has not changed | `server.host_key_pinned`, `server.host_key_replaced` |
| `POST /api/servers/{id}/host-key/keep` | Owner, or Admin of its group | Removes the block and the candidate, keeps the pinned key. 409 `host_key_not_changed` otherwise | `server.host_key_kept` |
| `POST /api/servers/{id}/connection-test` | Connect SSH in its group | Answers `{ok, reason, checks}`. 409 `host_key_not_pinned` or `host_key_changed` without connecting | `server.connection_tested`, `server.host_key_mismatch` |
| `GET /api/ssh/public-key` | signed in | The platform's public key. It is not a secret | none |

All four server routes answer 409 `not_an_ssh_server` for a Windows server.

A server in a response gains: `host_key_state` (`none` for Windows, `not_pinned`, `pinned`, `changed`), `host_key_fingerprint`, `host_key_type`, `host_key_pinned_at`, `host_key_changed_at`, `host_key_offered` (`{fingerprint, type, at}`, only in the state `changed`) and `can_connect`.

Reasons of a failed test or fetch: `unreachable`, `host_key_changed`, `key_refused`, `account_is_root`, `account_in_docker_group`, `account_check_failed`, `ssh_error`.

### Audit events

Every event has the server as its target and `context={"server_group_id": …}`, as in MITA-10.

| Action | Holds |
|---|---|
| `server.host_key_fetched` | Success with the fingerprint and type, or failure with the reason |
| `server.host_key_pinned` | `change`: the fingerprint, from none |
| `server.host_key_mismatch` | Failure. The pinned and the presented fingerprint, address and port. Recorded in its own transaction |
| `server.host_key_replaced` | `change`: the fingerprint before and after. `reason`: the admin's text |
| `server.host_key_kept` | The pinned fingerprint and the presented one that was turned down |
| `server.connection_tested` | Success or failure, the account, the reason and the four checks |

### Settings

`SSH_KEY_FILE` only. The time limits are constants in `app/ssh/client.py`.

## Error handling and edge cases

- **Two admins pin at once.** The row lock makes them take turns, and the second gets 409 `host_key_pinned`.
- **The server's key changes between the fetch and the pin.** The pin stores what the admin confirmed. The next connection meets another key and flags the server.
- **Keep the pinned key, and the server still presents the new one.** The next connection is refused and flags the server again, with a new event.
- **The presented key cannot be read at a mismatch** (the server answers differently the second time). The server is flagged all the same, the banner says the key is unknown, and the review offers only Keep the pinned key. A fetch-and-accept is not possible while a key is pinned, so the admin removes the block, and the next connection decides.
- **A server is moved to another group while it is flagged.** It stays flagged, and the new group's Admins review it.
- **A person loses Connect SSH or the Admin role while a dialog is open.** Rights are read on every request: 403 or 404, and the page reloads.
- **The key file is missing while the backend runs** (the volume was removed). The test answers 500 and the log says which file is missing. The next start creates a new key, which then has to go on every server.
- **A slow or silent server.** The request ends within about 25 seconds. The button shows "Testing…" and is off meanwhile.
- **An Admin registers an address inside the platform's own network.** The backend then opens a connection to it. The answer is only one of the fixed reasons, never what the other side sent.
- **An old server that offers only `ssh-rsa` with SHA-1.** The fetch fails with `ssh_error`. Such servers are not supported.
- **The denial or the mismatch cannot be recorded.** The request answers 500, as with every other guard.

## Testing

Tests are written first. Backend tests run with `megoocolab-runner services run test -- uv run pytest`, which now also starts the fake server.

**`tests/ssh/`**
- `keys`: the first call creates a 0600 file, the second keeps it, a file readable by others is refused, and the public line parses back to the same key.
- `hostkeys`: the fingerprint of a known key, and a bad line is refused.
- `client` against the fake server: fetch returns the server's key; connect with the right pinned key signs in; with another pinned key it raises `HostKeyChanged` and does not sign in; without the authorized key it raises `KeyRefused`; a closed port raises `Unreachable`.

**`tests/inventory/`**
- Fetch and pin: the candidate is stored, the pin needs its fingerprint, a wrong fingerprint gets 409, a second pin gets 409.
- Test connection: passes as `megoo`; fails with `account_in_docker_group` and `account_is_root` for the two wrong accounts; 409 before a key is pinned; `root` as login account gets 422.
- Rights: an Operator with Connect SSH tests but cannot fetch, pin, accept or keep (403); without the switch the test gets 403; an Auditor gets 403; a staging-only Admin gets 404 for every route of a production server.
- Changed key: after `swap_host_key()` the test answers `host_key_changed`, the server is `changed` with both fingerprints, the next test gets 409, accept without a reason gets 422, accept with one unblocks and the test passes, and keep unblocks without changing the key.
- An edit of the address keeps the pin and drops an unconfirmed candidate. Windows servers get 409.

**Security suites** (`make test-security`)
- `test_host_key_pinning.py` (new), the task's sentence: the platform connects to the fake server; after a swapped host key the connection is refused before sign-in; `server.host_key_mismatch` is in the audit log and the chain verifies; re-accepting is an event with the reason.
- The same file: no module but `app/ssh/client.py` opens an SSH connection.
- `test_audit_coverage.py` and `test_permission_coverage.py`: the new routes declare their actions and guards, and `GET /api/ssh/public-key` joins `ANY_SIGNED_IN`.
- `test_access_events.py`: the walk also fetches, pins, tests, meets a changed key, keeps and accepts, expects each action, and counts the private key among the secrets no event or response may hold.

**Other backend tests**
- `test_migrations.py`: `0007` goes down and up, and the two checks hold.
- `test_container.py` (`-m docker`): the key file exists with mode 0600 and `public-key` prints an Ed25519 line.
- `test_stack.py` (`-m stack`): through Caddy the Owner registers `fake-server`, pins and tests it; after `swap-host-key` the test is refused. The backend mounts `ssh_key`, and `docker-compose.yml` holds no fake server.
- `test_makefile.py`: `ssh-public-key`, the fake server only with `STACK=`, and `fake-server-swap` refusing to run without `STACK=`.

**Frontend** (Vitest)
- Server page: each of the four states, the button and banners for a manager, an Operator and an Auditor, and nothing for a Windows server.
- Pin dialog: fetches on open, Pin is off until the box is ticked, a failed fetch shows its text, a stale candidate fetches again.
- Review dialog: Accept needs a reason, Keep does not, each calls its route.
- Connection result: the checks and the advice for every reason.
- Access card: shown only with `can_manage`, and Copy copies the key.
- Servers list: the two badges.

Done when `make test` and `make test-security` pass, and by hand on `make up STACK=dev`: register `fake-server`, pin its key, test it, run `make fake-server-swap STACK=dev`, see the test refused and the server flagged, then accept the new key with a reason and test again.

## Out of scope

- The browser terminal, SFTP, live logs, the process manager and the metrics collector: Phases 1 and 2. They will use `open_connection`.
- The vault, moving the key into it, rotating the platform key, per-server keys and short-lived certificates: Phase 3.
- Sudo rules for `megoo`, on real servers and in the fixture: the phases whose features need them.
- Alert rules, notifications by email or webhook, and a platform-wide list of flagged servers: Phase 1.
- A stored last test result, a reachability status and automatic re-tests.
- Windows servers and RDP: Phase 2.
- Jump hosts, SSH config options per server, and password sign-in.
- The Audit page: Phase 4.
