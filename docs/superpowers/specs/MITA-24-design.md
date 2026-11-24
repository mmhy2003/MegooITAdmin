# MITA-24 design: managed-server onboarding (the `megoo` account and its sudo policy)

## Goal

An admin prepares a Linux server with one script: it creates `megoo`, gives it the log groups, limits its sudo to a small checker script, and accepts the platform's key only from the platform's address. Test connection then proves the server is prepared with seven checks instead of four, and the fake server is prepared by the same script. Mockup v2 shows the card, the checks and the script's output.

## What the repository looks like today

- MITA-11 left `megoo` on real servers to the admin ("create the account, add the key") and gave the fixture's `megoo` no groups and no sudo rule.
- Test connection (`app/inventory/connection.py`) runs `id -u; id -Gn` and reports four checks: host key, platform key, not root, not in `docker`.
- The Platform access card shows two manual steps and the public key.
- `tools/fake-server/` is a Debian image with OpenSSH, three accounts (`megoo`, `megoo-docker`, `megoo-root`) and `authorize-key`, which writes a plain key line for all three.
- Nothing connects to a server yet except the key fetch and the test. Live logs and the process manager come later and will run their commands through what this task sets up.

## Decisions

Answers from the owner:

1. **Sudo allows only one root-owned checker script, `megoo-ctl`.** A plain sudoers line cannot limit arguments: `systemctl enable /home/megoo/x.service` runs anything as root, and `systemctl start reboot.target` reboots the server. Rejected: sudoers regular expressions (need sudo 1.9.10+, which leaves out Ubuntu 22.04, Debian 11 and RHEL 8/9) and plain wildcards (only the platform would guard the arguments). This installs one file on each server, a known exception to "nothing is installed on the managed servers".
2. **The script limits `megoo`'s key to the platform's address (`from="…"` in `authorized_keys`) and does not touch the firewall.** Other accounts keep working, so nobody is locked out. The docs say how to close port 22 for other addresses. Rejected: an opt-in firewall step, an sshd `AllowUsers` rule, and documentation only.
3. **The setup check lives in the app and in the script.** Test connection gains the checks `megoo` can see for itself. The script verifies its own work as root, and `--check` runs that verification alone.
4. **An admin gets the script from the app (Download) or from the repository.** Both are the same file.

Decisions I made (say so if you want one changed):

5. **One self-contained file, `backend/app/ssh/megoo-setup.sh`**, POSIX `sh`. It holds `megoo-ctl` and the sudoers line inside it, so one file is copied to a server. It lives in the backend package because the backend serves it and the image build copies only `app/`.
6. **`megoo-ctl` owns the options of each command.** A caller chooses a verb and a target, never free options. The list is in "Data and interfaces".
7. **Units are limited to `.service`, `.socket` and `.timer`**, named without a path. `megoo-ctl` also refuses PID 1. The other protected processes and the PID-plus-start-time check belong to the process manager (Phase 2).
8. **`--from` is required and typed by the admin.** The platform does not know the address a server sees it under (NAT, several interfaces), so the card shows a placeholder.
9. **The script owns `megoo`'s `authorized_keys`**: the file holds only the platform's key. The account is the platform's alone, and running the script again with another key replaces it.
10. **The script fixes what is safely its own and reports the rest.** It creates the account, adds the two groups, removes `megoo` from `docker`, and writes its three files. It does not remove other sudo rights (membership of `sudo` or `wheel`, other sudoers files): it reports them as a failed check and exits non-zero.
11. **The script installs no packages and changes no sshd setting.** It stops with a clear message when `sudo`, `visudo`, `useradd` or the `systemd-journal` group is missing. Supported: Linux with systemd, sudo and OpenSSH (Debian and Ubuntu, the RHEL family). It is tested on the Debian fixture, and by the owner on one real server.
12. **A half-prepared server fails Test connection.** A server prepared the MITA-11 way fails the three new checks until the script has run. Nothing else connects yet, so nothing breaks.
13. **RDP is documented only.** Windows servers connect from Phase 2. The docs give the Windows Firewall rule that limits Remote Desktop to the platform's address.
14. **The run on a real test server is the owner's, by hand.** `AGENTS.md` forbids agents to connect to a managed server, so the build ends at the fake server. The docs carry the short checklist.
15. **Docker only.** Podman gets its `megoo-ctl` verbs with the feature that needs them.

## Architecture

### The setup script (`backend/app/ssh/megoo-setup.sh`, new)

Run as root on the server: `sh megoo-setup.sh --from <addresses> --key '<public key line>' [--user <name>]`, or `sh megoo-setup.sh --check [--user <name>]`.

A run does these steps, each safe to repeat, then verifies all of them and prints one line per check (mockup v2, section 3):

1. Validate the arguments before changing anything: the key with `ssh-keygen -l`, the addresses against a fixed character set (no quotes or spaces), the user name (never `root`, never an account with uid 0).
2. Create the account when it is missing: home directory, `/bin/bash`, no password (`*`, not locked).
3. Add it to `systemd-journal` and `adm`. Remove it from `docker` when it is a member, and say so.
4. Write `/usr/local/sbin/megoo-ctl` (root, 0755) through a temporary file and a rename.
5. Write `/etc/sudoers.d/megoo-ctl-<user>` (root, 0440): `<user> ALL=(root) NOPASSWD: /usr/local/sbin/megoo-ctl`. The file is checked with `visudo -cf` before it is moved into place.
6. Write `~/.ssh/authorized_keys` (0600, directory 0700) with one line: `from="<addresses>" <key>`.
7. Verify. As root it can see everything: uid, groups, the installed `megoo-ctl` (owner, mode, version), what `sudo -l -U <user>` allows, and the key file. Exit 0 with "The server is ready" and the firewall reminder, or non-zero with the number of failed checks.

`--check` runs only step 7 and changes nothing. For the key it prints the fingerprint and the addresses it finds.

### `megoo-ctl` (inside the script)

A short `sh` script with a fixed `PATH`, no `eval`, and one `case` per verb. It validates every argument against a pattern, then `exec`s the real tool with options it chose itself. Anything else ends with exit 2 and one line on stderr.

### Backend

| Module | Change |
|---|---|
| `app/ssh/client.py` | `setup_of(conn)`: runs `sudo -n /usr/local/sbin/megoo-ctl version` and `LC_ALL=C sudo -n -l`, and returns the installed version (or none) and the commands sudo allows (or none when they cannot be read). Same 5-second limit and `AccountCheckFailed` as `account_of` |
| `app/ssh/setup.py` (new) | Reads the bundled script: its text for the download, and the `megoo-ctl` version it carries, so the version has one source |
| `app/inventory/connection.py` | The test also calls `setup_of` and builds seven checks. Reason order when several fail: root, `docker`, log groups, checker, too wide |
| `app/inventory/connection_schemas.py` | Three check names and three reasons (below) |
| `app/inventory/server_router.py` | `GET /api/ssh/setup-script` |

The three new checks:

| Check | Passes when |
|---|---|
| `in_log_groups` | `id -Gn` holds both `systemd-journal` and `adm` |
| `sudo_checker` | `megoo-ctl version` answers through sudo with a version not older than the bundled script's |
| `sudo_limited` | `sudo -n -l` lists exactly one command, `megoo-ctl`. "Not checked" when the list cannot be read |

Only a parsed integer and a yes/no leave `setup_of`: what the server printed never reaches a response or an event, as in MITA-11.

### Fake-server fixture (`tools/fake-server/`)

- The image adds `sudo`, the `systemd-journal` group, and stub `docker` and `systemctl` commands that write their arguments to a log file, so a test can see exactly what `megoo-ctl` passed on. `kill` and `renice` are the real ones.
- The image build takes `megoo-setup.sh` from `backend/app/ssh/` (an additional build context in the two Compose files). The image no longer creates `megoo` by hand.
- `authorize-key` runs the real script for `megoo`, so the fixture is prepared exactly like a server. It takes the allowed addresses as an optional argument. The default is the private ranges and loopback, which covers pytest on the host and the Compose networks.
- Three more wrong accounts, each prepared by the script and then broken in one way: `megoo-nologs` (not in `adm`), `megoo-nosudo` (no sudoers file) and `megoo-wide` (an extra sudoers line that allows everything). `megoo-docker` and `megoo-root` stay. `AllowUsers` and `tests/fake_server.py` learn the new names.

### Frontend

| File | Change |
|---|---|
| `src/components/servers/platform-access-card.tsx` | The three steps of mockup v2: Download (a link to `/api/ssh/setup-script`) and the repository path, the command with the key filled in and Copy (with `--user <name>` when the login account is not `megoo`), then pin and test. The firewall note below |
| `src/lib/servers.ts` | The three check names, their labels, the three reasons |
| `src/lib/auth/messages.ts` | Title and advice of the three reasons, and the new advice for a refused key |
| `src/components/servers/connection-result.tsx` | No change: it lists whatever checks arrive |

### Docs

- `docs/server-setup.md` (new): what the script does and its options, the `megoo-ctl` list, how to limit port 22 (ufw, firewalld, a security group) and Remote Desktop (Windows Firewall) to the platform's address, running the script again after an upgrade or a new platform key, how to remove the setup, and the checklist for a real server.
- `README.md` "Servers": prepare a server with the script, and the link.
- `AGENTS.md`: the fixture's new accounts, and the new suite in the Security suites line.

## Data and interfaces

No migration and no new setting.

### `megoo-ctl`, version 1

Called as `sudo -n /usr/local/sbin/megoo-ctl <call>`.

| Call | Runs | Accepts |
|---|---|---|
| `version` | prints `megoo-ctl 1` | nothing else |
| `docker ps` | `docker ps --all --no-trunc --format '{{json .}}'` | nothing else |
| `docker logs <container> [--follow] [--tail <n>] [--since <time>]` | `docker logs --timestamps …` | a number for `--tail`, a timestamp or a duration for `--since` |
| `docker start\|stop\|restart <container>` | the same | one container |
| `kill <TERM\|KILL\|HUP\|STOP\|CONT> <pid>…` | `kill -s <signal> <pid>…` | numeric PIDs above 1 |
| `renice <priority> <pid>…` | `renice -n <priority> -p <pid>…` | -20 to 19, numeric PIDs above 1 |
| `systemctl start\|stop\|restart\|reload\|enable\|disable <unit>` | `systemctl --no-pager --no-ask-password <verb> -- <unit>` | one unit of letters, digits and `:_.@-`, ending in `.service`, `.socket` or `.timer` |

A container is a name or an id: it starts with a letter or digit and holds only letters, digits and `_.-`. A later feature that needs another call adds it here and raises the version. Servers then fail `sudo_checker` until the script runs again.

### Routes

| Route | Who | Does | Audit |
|---|---|---|---|
| `GET /api/ssh/setup-script` | signed in | The script as a download named `megoo-setup.sh`. It is not a secret: it is in the public repository | none |
| `POST /api/servers/{id}/connection-test` | unchanged | `checks` now holds seven entries, in a fixed order | `server.connection_tested` holds the seven |

New check names: `in_log_groups`, `sudo_checker`, `sudo_limited`. New reasons: `account_not_in_log_groups`, `sudo_checker_missing`, `sudo_too_wide`.

## Error handling and edge cases

- **The script runs twice.** The second run changes nothing and prints the same list.
- **`megoo` exists already**, with other keys or in `docker`. The account is kept, its key file is replaced (decision 9) and it leaves `docker`. The script says what it changed.
- **`megoo` has other sudo rights.** The script reports the failed check with what sudo allows, exits non-zero, and Test connection answers `sudo_too_wide`.
- **A wrong `--from`.** The server refuses the key. The test answers `key_refused`, and its advice now names the address. No other account is affected.
- **A broken sudoers file would lock sudo for everyone.** The file is validated with `visudo -cf` before it is moved in, and an invalid one is never installed.
- **The script is not run as root, or a tool is missing.** It stops before changing anything and says what is missing.
- **A server prepared by an older script.** `megoo-ctl version` is lower, so `sudo_checker` fails with "run the setup script again".
- **`sudo -n -l` prints something unexpected** (another language, an old sudo). The list counts as unreadable: `sudo_limited` is "Not checked" and the test fails with `sudo_too_wide` only when a second command was actually read. An unreadable list with a working checker fails as `account_check_failed`.
- **A `megoo-ctl` argument that looks like an option** (`--host=x`, `-H`), a path, a second unit, a signal outside the list, PID 1. Refused with exit 2 before any tool runs.
- **The download while signed out.** 401, as every other route.

## Testing

Tests are written first. All of them use the fake server: no test and no agent connects to a real server.

**Security suite, `tests/security/test_server_setup.py` (new, `make test-security`)**
- As `megoo` in the fixture: `sudo -n true`, `sudo -n /bin/sh` and `sudo -n docker ps` are refused, and `sudo -n megoo-ctl version` answers.
- A table of allowed calls: each reaches the stub (or the real `kill` and `renice` on a `sleep` process) with exactly the expected arguments.
- A table of refused calls: a unit path, `reboot.target`, two units, `daemon-reload`, `docker run`, `docker exec`, an option as a container name, an unknown signal, PID 1, a PID with shell text, a priority of 99. None reaches a tool.
- `megoo` is in `systemd-journal` and `adm`, and not in `docker`.

**`tests/ssh/`**
- The script on scratch accounts in the fixture (`--user`): a first run creates everything and `--check` passes; a second run changes no file; after removing a group `--check` fails and names it, and a new run repairs it; a bad key, a bad address and `--user root` stop before any change; an invalid sudoers file is not installed.
- A key authorized for another address is refused (`KeyRefused`), and the default addresses sign in.
- `setup_of` against `megoo` and the three new wrong accounts.

**`tests/inventory/`**
- Test connection: seven passed checks for `megoo`; `account_not_in_log_groups`, `sudo_checker_missing` and `sudo_too_wide` for the three wrong accounts, each with the right statuses; the reason order when several fail; the event holds the seven checks.
- `GET /api/ssh/setup-script`: the bundled file, the download header, 401 when signed out.

**Coverage suites and other backend tests**
- `test_permission_coverage.py`: the new route joins `ANY_SIGNED_IN` with its reason.
- `test_fake_server.py`: the new accounts are what the checks expect.
- `test_stack.py` (`-m stack`): the Owner's test of the fake server through Caddy shows seven passed checks, and the download answers.
- `test_container.py` (`-m docker`): the image holds the script.

**Frontend** (Vitest)
- Access card: the download link, the repository path, the command with the key, `--user` only for another account, Copy copies the command.
- Connection result: seven rows, and title and advice for the three new reasons and the refused key.

Done when `make test` and `make test-security` pass, and by hand on `make up STACK=dev`: the fake server shows seven passed checks. Then the owner downloads the script, runs it on one real test server, sees "The server is ready", pins the key and sees seven passed checks there too.

## Out of scope

- Changing a firewall or sshd from the script, and any script for Windows: documented only.
- Live logs, the collector, the process manager, and the platform-side rules for actions (protected processes, PID plus start time, reasons, audit of each action): their own tasks, which call `megoo-ctl`.
- Podman, reading log files by an allowlist, and any `megoo-ctl` call not in the table.
- Running the script from the platform over SSH, and re-running it on every server after an upgrade: an admin runs it.
- Extra key options (`restrict`, no forwarding), per-server keys and SSH certificates: with the vault, Phase 3.
- A stored setup state per server, and a platform-wide list of unprepared servers.
