# MITA-24 plan: managed-server onboarding (the `megoo` account and its sudo policy)

## Goal

One POSIX `sh` script, `backend/app/ssh/megoo-setup.sh`, prepares a Linux server for MegooITAdmin (account, log groups, `megoo-ctl` as the only sudo command, key limited to the platform's address), the fake server is prepared by that same script, and Test connection proves it with seven checks.

## Architecture

The script carries `megoo-ctl` (version 1) and the sudoers line inside it. The backend bundles it (`app/ssh/setup.py` reads its text and its `CTL_VERSION`), serves it at `GET /api/ssh/setup-script`, and `app/ssh/client.setup_of()` asks a signed-in account for `megoo-ctl version` and `sudo -n -l`, so `connection.test_connection` reports seven checks. The fake-server image takes the script through an additional build context, `authorize-key` runs it for `megoo` and three deliberately broken accounts, and stub `docker`/`systemctl` commands log what `megoo-ctl` passes on. The Platform access card shows Download, the command to copy, and the firewall note.

## Conventions every step follows

- Work on the branch `megoo/MITA-24-p1-01-managed-server-onboarding-megoo-ac`. Do not create another branch, do not push.
- Write the test first, run it, watch it fail for the reason given, then implement and run it again.
- Commits: `type(area): sentence`, a body that says why, last line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Commit only the step's files. Never commit `.megoocolab/` or any plan or design file.
- Test files under `backend/tests/` have no `__init__.py` and import helpers by basename, so every new test file needs a unique basename.
- Never connect to a real server. All SSH tests use the fake server of the `test` set.

## Commands used in the steps

- **BT `<paths>`** (from `backend/`): `megoocolab-runner services run test -- uv run pytest <paths>` (starts the database and the fake server, rebuilt from this checkout).
- **BACKEND** (from `backend/`): `megoocolab-runner services run test -- uv run pytest`
- **SECURITY** (repository root): `make test-security`
- **DOCKER** (from `backend/`): `megoocolab-runner services run image -- uv run pytest -m docker`
- **STACK** (from `backend/`): `megoocolab-runner services run stack -- uv run pytest -m stack`
- **LINT** (from `backend/`): `uv run ruff check . && uv run ruff format --check .` (if ruff is configured in `pyproject.toml`; otherwise skip and say so)
- **FE `<path>`** (from `frontend/`): `npx vitest run <path>`
- **FE-GATE** (from `frontend/`): `npx tsc --noEmit && npx eslint <changed files> && npm test`

## File map

### Backend (`backend/`)

| File | Change |
|---|---|
| `app/ssh/megoo-setup.sh` (new) | The setup script with `megoo-ctl` inside (Appendix A, B). Steps 1 and 3 |
| `app/ssh/setup.py` (new) | `SCRIPT`, `script_text()`, `ctl_version()` (Appendix C). Step 4 |
| `app/ssh/client.py` | `CTL`, `Setup`, `sudo_commands()`, `setup_of()` (Appendix C). Step 4 |
| `app/inventory/connection_schemas.py` | Three reasons, three check names. Step 5 |
| `app/inventory/connection.py` | Seven checks, `_reason()`, `_statuses()` (Appendix D). Step 5 |
| `app/inventory/server_router.py` | `GET /api/ssh/setup-script`. Step 6 |
| `tests/fake_server.py` | `exec(..., user=)`, `authorize(addresses=)`, `ACCOUNTS`, `tool_log()`/`clear_tool_log()`. Steps 1–3 |
| `tests/conftest.py` | `fake_server` fixture docstring. Step 2 |
| `tests/ssh/test_setup_script.py` (new) | The script on scratch accounts. Step 1 |
| `tests/ssh/test_fake_server.py` | The prepared and broken accounts. Step 2 |
| `tests/ssh/test_ssh_client.py` | Key limited by address; `setup_of`; `sudo_commands`. Steps 2, 4 |
| `tests/ssh/test_setup_bundle.py` (new) | `script_text`, `ctl_version`. Step 4 |
| `tests/security/test_server_setup.py` (new) | What `megoo` may and may not do with sudo. Step 3 |
| `tests/inventory/test_connection_test.py` | Seven checks, the three new wrong accounts, reason order. Step 5 |
| `tests/inventory/test_setup_script_route.py` (new) | The download. Step 6 |
| `tests/security/test_permission_coverage.py` | `GET /api/ssh/setup-script` in `ANY_SIGNED_IN`. Step 6 |
| `tests/test_container.py`, `tests/test_stack.py` | The image holds the script; seven passed checks and the download through Caddy. Step 7 |

### Fixture (`tools/fake-server/`)

| File | Change |
|---|---|
| `Dockerfile` | `sudo`, `procps`, group `systemd-journal`, stubs, the script from the `setup` build context; no hand-made `megoo`. Steps 1–2 |
| `fake-tool` (new) | The stub installed as `/usr/local/bin/docker` and `/usr/local/bin/systemctl`. Step 1 |
| `authorize-key` | Runs the script for `megoo`, `megoo-nologs`, `megoo-nosudo`, `megoo-wide`, then breaks the three; plain key for `megoo-docker` and `megoo-root` (Appendix E). Step 2 |
| `sshd_config` | `AllowUsers` gains the three names. Step 2 |
| `docker-compose.test.yml`, `docker-compose.stack.yml` | `additional_contexts: {setup: …/backend/app/ssh}`. Step 1 |

### Frontend (`frontend/`)

| File | Change |
|---|---|
| `src/lib/servers.ts`, `src/lib/__tests__/servers.test.ts` | Check names, labels, reasons. Step 8 |
| `src/lib/auth/messages.ts` | Three reasons, new `key_refused` advice. Step 8 |
| `src/components/servers/__tests__/connection-result.test.tsx`, `server-page.test.tsx` | Seven rows. Step 8 |
| `src/components/servers/platform-access-card.tsx` + its test | The three steps and the note. Step 9 |

### Docs

`docs/server-setup.md` (new), `README.md` "Servers", `AGENTS.md` (fixture accounts, security suite list). Steps 3 and 10.

## Steps

### 1. The setup script, run on scratch accounts in the fake server

**Files:** `backend/app/ssh/megoo-setup.sh` (new, Appendix A with the `megoo-ctl` body of Appendix B), `tools/fake-server/Dockerfile`, `tools/fake-server/fake-tool` (new), `tools/fake-server/docker-compose.test.yml`, `tools/fake-server/docker-compose.stack.yml`, `backend/tests/fake_server.py`, `backend/tests/ssh/test_setup_script.py` (new).

**Fixture changes.**
- `Dockerfile`: `apt-get install -y --no-install-recommends openssh-server sudo procps`; `groupadd -r systemd-journal` (Debian slim has `adm`, but no systemd); keep `megoo` created by hand **in this step** (step 2 removes it); `COPY --from=setup megoo-setup.sh /usr/local/lib/megoo-setup.sh`; `COPY fake-tool /usr/local/bin/docker`, `COPY fake-tool /usr/local/bin/systemctl`, `chmod 0755` both; `touch /var/log/fake-tools.log`.
- `fake-tool`:
  ```sh
  #!/bin/sh
  # Stands in for docker and systemctl: logs its name and each argument in brackets to /var/log/fake-tools.log, so a
  # test sees exactly what megoo-ctl passed on.
  { printf '%s' "${0##*/}"; printf ' [%s]' "$@"; printf '\n'; } >> /var/log/fake-tools.log
  ```
- `docker-compose.test.yml`: `build: {context: ../fake-server, additional_contexts: {setup: ../../backend/app/ssh}}` (paths relative to `tools/test-services`, as the file's comment says). `docker-compose.stack.yml`: `build: {context: ./tools/fake-server, additional_contexts: {setup: ./backend/app/ssh}}`. Update both comments.
- `tests/fake_server.py`: `exec(self, *args, input=None, user=None)` adds `-u <user>` to `docker exec` when given. Add `SETUP = "/usr/local/lib/megoo-setup.sh"` and `def setup(self, *args) -> CompletedProcess` that runs `sh SETUP *args` as root.

**Tests first** (`tests/ssh/test_setup_script.py`). A fixture `scratch(fake_server)` yields a fresh name `f"megoo-t{uuid4().hex[:8]}"` and afterwards runs `userdel -r <name>` and `rm -f /etc/sudoers.d/megoo-ctl-<name>`. `KEY = keys.public_key()` (after `keys.ensure_key()`), `FROM = "192.0.2.10,10.0.0.0/8"`.
- `test_a_first_run_prepares_everything_and_check_passes`: exit 0; stdout holds `Created the account <name>.`, `Added <name> to systemd-journal.`, `Added <name> to adm.`, `Wrote /etc/sudoers.d/megoo-ctl-<name>.`, `Wrote /home/<name>/.ssh/authorized_keys.`, and `The server is ready.`; the key file is exactly `from="192.0.2.10,10.0.0.0/8" <KEY>\n`; `stat -c '%U %a'` gives `root 755` for `/usr/local/sbin/megoo-ctl`, `root 440` for the sudoers file, `<name> 600` for the key file, `<name> 700` for `.ssh`; `--check --user <name>` exits 0, has no `[FAIL]`, and prints the fingerprint (`ssh-keygen -lf` of KEY) and `192.0.2.10,10.0.0.0/8`.
- `test_a_second_run_changes_no_file`: run twice; `stat -c '%n %i %Y %a %U'` of the four files is identical; the second stdout holds `Nothing to change.`
- `test_a_missing_group_fails_check_and_a_new_run_repairs_it`: `gpasswd -d <name> adm`; `--check` exits 1 with `[FAIL] <name> is not in adm.` and `1 check(s) failed.`; a full run adds it back and exits 0.
- `test_it_leaves_docker`: `useradd -m -G docker <name>` first; the run prints `Removed <name> from the docker group` and `id -Gn` has no `docker`.
- `test_bad_input_stops_before_any_change` (parametrized): `--key 'not a key'`, `--key 'ssh-ed25519 AAAA" x'`, `--from '1.2.3.4" command="id'`, `--from '1.2.3.4 5.6.7.8'`, no `--from`, `--user root`, `--user 'Bad;name'`: exit 2, stderr holds `Nothing was changed.`, `getent passwd <name>` fails (for `--user root`, check the scratch name was never created and no `/etc/sudoers.d/megoo-ctl-root`).
- `test_a_uid_0_account_is_refused`: `--user megoo-root` exits 2.
- `test_an_invalid_sudoers_file_is_not_installed`: write `/usr/local/sbin/visudo` = `#!/bin/sh\nexit 1` (0755), run, then remove it in `finally`; exit 1, stderr holds `was not installed`, no `/etc/sudoers.d/megoo-ctl-<name>`, and no `/etc/sudoers.d/.megoo-ctl.*` left behind.
- `test_check_of_a_missing_account_fails`: `--check --user <name>` exits 1 with `[FAIL] The account <name> does not exist.`

Run **BT tests/ssh/test_setup_script.py**: fails (no script, image has no `sudo`).

**Implement** Appendix A and B exactly as written (adjust only what a failing test proves wrong, keeping the output strings). Run **BT tests/ssh/test_setup_script.py** → pass, then **BACKEND** → green (other tests are unaffected: `megoo` is still made by hand).

**Commit:** `feat(ssh): megoo-setup.sh prepares a server's megoo account, its log groups and the one sudo rule`

### 2. The fake server is prepared by the script, with three broken accounts

**Files:** `tools/fake-server/Dockerfile`, `authorize-key`, `sshd_config`, `backend/tests/fake_server.py`, `backend/tests/conftest.py`, `backend/tests/ssh/test_fake_server.py`, `backend/tests/ssh/test_ssh_client.py`.

**Tests first.**
- `test_fake_server.py`: replace the "three accounts" test with `test_the_platform_key_is_authorized_for_every_account`: for `megoo`, `megoo-nologs`, `megoo-nosudo`, `megoo-wide` the key file is one line starting with `from="127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,::1,fc00::/7" ` followed by the key's type and base64; for `megoo-docker` and `megoo-root` the first two fields are the key's. Extend `test_the_accounts_are_what_the_checks_expect`: `megoo` is in `systemd-journal` and `adm`, not in `docker`; `megoo-nologs` is in `systemd-journal`, not `adm`; `/etc/sudoers.d/megoo-ctl-megoo-nosudo` does not exist; `/etc/sudoers.d/megoo-wide-all` exists; `sh /usr/local/lib/megoo-setup.sh --check --user megoo` exits 0.
- `test_ssh_client.py`: `test_a_key_limited_to_another_address_is_refused`: `fake_server.authorize("192.0.2.1")`, then `connect(... "megoo" ...)` raises `KeyRefused`; in `finally` `fake_server.authorize()`, then `connect` as `megoo` signs in. Extend `test_the_two_wrong_accounts` → also sign in as each of the three new accounts (they sign in).

Run **BT tests/ssh** → fails.

**Implement.**
- `Dockerfile`: drop `useradd … megoo` and its `usermod -p`; keep `megoo-docker` and `megoo-root`; update the comment (megoo and the three broken accounts are made by `authorize-key` through the script).
- `authorize-key`: Appendix E.
- `sshd_config`: `AllowUsers megoo megoo-nologs megoo-nosudo megoo-wide megoo-docker megoo-root`.
- `tests/fake_server.py`: `ACCOUNTS = ("megoo", "megoo-nologs", "megoo-nosudo", "megoo-wide", "megoo-docker", "megoo-root")`; module docstring lists them; `def authorize(self, addresses: str | None = None) -> None` pipes `keys.public_key()` into `authorize-key [addresses]` and asserts exit 0; `start()` calls `server.authorize()`.
- `conftest.py`: the `fake_server` docstring says "prepared by megoo-setup.sh, with this run's platform key".

Run **BT tests/ssh** → pass. **BACKEND** → green (`test_connection_test.py` still sees four passed checks for `megoo`).

**Commit:** `test(fake-server): the fake server is prepared by megoo-setup.sh and keeps three broken accounts`

### 3. Security suite: megoo may run megoo-ctl and nothing else

**Files:** `backend/tests/security/test_server_setup.py` (new), `backend/tests/fake_server.py`, `AGENTS.md` (Security suites line), possibly `backend/app/ssh/megoo-setup.sh` (megoo-ctl fixes).

**Helpers** in `fake_server.py`: `LOG = "/var/log/fake-tools.log"`; `clear_tool_log()` (`truncate -s 0`); `tool_log() -> list[str]`; `ctl(self, *args, user="megoo")` runs `sudo -n /usr/local/sbin/megoo-ctl *args` as `user`.

**Tests first** (module docstring: "The task's sentence: the platform's account may use sudo only through megoo-ctl, and megoo-ctl passes on only the calls in its table."):
- `test_sudo_refuses_anything_but_megoo_ctl`: as `megoo`, `sudo -n true`, `sudo -n /bin/sh -c id`, `sudo -n docker ps` exit non-zero; the tool log stays empty; `ctl("version")` prints `megoo-ctl 1`.
- `test_megoo_is_in_the_log_groups_and_not_in_docker`.
- `test_an_allowed_call_reaches_the_tool_with_exactly_these_arguments` (parametrized, `(args, logged)`), the table in Appendix F.
- `test_a_refused_call_reaches_no_tool` (parametrized), the table in Appendix F: exit 2, stderr starts with `megoo-ctl: refused`, tool log empty.
- `test_kill_and_renice_act_on_a_real_process`: as root, `sh -c 'setsid sleep 300 > /dev/null 2>&1 < /dev/null & echo $!'` gives a PID; `ctl("renice", "5", pid)` → `ps -o ni= -p pid` is `5`; `ctl("kill", "STOP", pid)` → `ps -o stat=` starts with `T`; `CONT`; `ctl("kill", "TERM", pid)` → within 5 s `ps -o stat=` is empty or starts with `Z`.

Run **SECURITY** → the new suite fails only where `megoo-ctl` is wrong (or passes at once if Appendix B was exact; then say so). Fix `megoo-ctl` in the script until it passes. Update `AGENTS.md`: "…access-events, host-key-pinning and server-setup suites." Run **SECURITY** and **BT tests/ssh** → pass.

**Commit:** `test(security): megoo may use sudo only through megoo-ctl, which passes on only its listed calls`

### 4. The backend reads the bundled script and the account's sudo setup

**Files:** `backend/app/ssh/setup.py` (new), `backend/app/ssh/client.py`, `backend/tests/ssh/test_setup_bundle.py` (new), `backend/tests/ssh/test_ssh_client.py`. Code in Appendix C.

**Tests first.**
- `test_setup_bundle.py`: `script_text()` starts with `#!/bin/sh\n` and equals `SCRIPT.read_text()`; `ctl_version() == 1`; `sh -n` on `SCRIPT` exits 0 (`subprocess.run(["sh", "-n", str(SCRIPT)])`).
- `test_ssh_client.py`, pure: `sudo_commands()` on Appendix C's sample texts: the `megoo` sample → `["/usr/local/sbin/megoo-ctl"]`; the wide sample → `["/usr/local/sbin/megoo-ctl", "ALL"]`; `(ALL : ALL) ALL` → `["ALL"]`; a German/unknown text → `None`; a header with no entries → `[]`.
- Against the fake server: `setup_of` as `megoo` → `Setup(version=1, limited=True)`; `megoo-nologs` → `Setup(1, True)`; `megoo-nosudo` → `Setup(None, None)`; `megoo-wide` → `Setup(1, False)`.

Run **BT tests/ssh** → ImportError. Implement Appendix C. Run again → pass; **BACKEND** green.

**Commit:** `feat(ssh): the client reads megoo-ctl's version and what sudo allows the signed-in account`

### 5. Test connection reports seven checks

**Files:** `backend/app/inventory/connection_schemas.py`, `backend/app/inventory/connection.py`, `backend/tests/inventory/test_connection_test.py`. Code in Appendix D.

**Tests first** (`test_connection_test.py`): `CHECKS` gains `in_log_groups`, `sudo_checker`, `sudo_limited`; every `checks(...)` call gets seven statuses.
- `test_the_test_passes_as_megoo`: seven `passed`; the event's `checks` holds the seven.
- The parametrized wrong accounts become five rows:
  - `megoo-docker`, `account_in_docker_group`, `(p, p, p, f, f, f, not_run)`
  - `megoo-root`, `account_is_root`, `(p, p, f, p, f, p, f)`
  - `megoo-nologs`, `account_not_in_log_groups`, `(p, p, p, p, f, p, p)`
  - `megoo-nosudo`, `sudo_checker_missing`, `(p, p, p, p, p, f, not_run)`
  - `megoo-wide`, `sudo_too_wide`, `(p, p, p, p, p, p, f)`
  (megoo-root: `id -Gn` is `root`; sudo maps uid 0 to `root`, which runs `megoo-ctl` and is allowed `ALL`. If the fixture shows otherwise for its last three statuses, fix the expectation of those three only and say why in the commit body; the reason must stay `account_is_root`.)
- `test_an_older_megoo_ctl_fails_the_checker`: `monkeypatch.setattr("app.inventory.connection.ctl_version", lambda: 2)`; as `megoo` → `sudo_checker_missing`, `sudo_checker` failed, the rest passed.
- `test_the_swapped_key` test: `("failed", "not_run" × 6)`.
- Pure `test_the_reason_order` (parametrized over `_reason(account, setup, bundled=1)`): `(0, ["docker"]), Setup(None, False)` → `account_is_root`; `(1000, ["docker"]), Setup(None, None)` → `account_in_docker_group`; `(1000, ["adm"]), Setup(None, False)` → `account_not_in_log_groups`; `(1000, ["adm", "systemd-journal"]), Setup(None, False)` → `sudo_checker_missing`; same groups, `Setup(1, False)` → `sudo_too_wide`; `Setup(1, None)` → `account_check_failed`; `Setup(1, True)` → `None`.
- Pure `test_an_unreadable_list_is_not_checked`: `_checks(None, (1000, ["adm","systemd-journal"]), Setup(1, None))` ends with `not_run`.

Run **BT tests/inventory/test_connection_test.py** → fails. Implement Appendix D. Run again → pass; **BACKEND** green.

**Commit:** `feat(inventory): Test connection checks the log groups, megoo-ctl and the limit of sudo`

### 6. GET /api/ssh/setup-script

**Files:** `backend/app/inventory/server_router.py`, `backend/tests/inventory/test_setup_script_route.py` (new), `backend/tests/security/test_permission_coverage.py`.

**Tests first.** `test_setup_script_route.py` (uses `api`, `clock`, `signed_in` from `auth_helpers`):
- `test_a_signed_in_person_downloads_the_bundled_script`: an operator with no grants (`signed_in(api, clock, "otto@example.com")`) gets 200, `response.text == setup.script_text()`, `content-type` starts with `text/x-shellscript`, `content-disposition == 'attachment; filename="megoo-setup.sh"'`; no audit event is added (`await actions()` unchanged).
- `test_401_when_signed_out`: `api.get("/api/ssh/setup-script")` → 401.
- Permission coverage: add `"GET /api/ssh/setup-script": "the setup script, which is in the public repository"` to `ANY_SIGNED_IN` (write it first, watch `test_any_signed_in_names_only_real_routes` fail).

Run **BT tests/inventory/test_setup_script_route.py tests/security/test_permission_coverage.py** → fails.

**Implement** in `server_router.py` (update the module docstring: "…and GET /api/ssh/setup-script the setup script"):
```python
@router.get("/ssh/setup-script")
async def read_setup_script(user: CurrentUser) -> Response:
    return Response(
        setup.script_text(),
        media_type="text/x-shellscript",
        headers={"Content-Disposition": 'attachment; filename="megoo-setup.sh"'},
    )
```
with `from app.ssh import keys, setup`. Run again → pass; **BACKEND** and **SECURITY** green.

**Commit:** `feat(inventory): every signed-in person can download the setup script`

### 7. The image holds the script; the stack shows seven passed checks

**Files:** `backend/tests/test_container.py`, `backend/tests/test_stack.py`.

**Tests first.**
- `test_container.py`: `test_the_image_holds_the_setup_script`: `_exec("python", "-c", "from app.ssh import setup; print(setup.ctl_version(), setup.script_text().splitlines()[0])") == "1 #!/bin/sh"`.
- `test_stack.py`: in `test_the_owner_pins_and_tests_the_fake_server_and_a_swapped_key_is_refused`, the first test answers `ok is True` **and** `[c["status"] for c in checks] == ["passed"] * 7`; add `test_the_setup_script_downloads_through_caddy(owner)` (before the sign-out test): `owner.get("/api/ssh/setup-script")` → 200, body starts with `#!/bin/sh`, the `content-disposition` header names `megoo-setup.sh`.

Run **DOCKER** and **STACK**. These need no code change if steps 1–6 are right (the image copies `app/`, the stack fake server builds with the `setup` context): if they already pass, say so in the commit body. If the stack build fails on `additional_contexts`, fix `tools/fake-server/docker-compose.stack.yml`.

**Commit:** `test(stack): the image carries the setup script and the stack's fake server passes seven checks`

### 8. Frontend: seven checks and the new reasons

**Files:** `frontend/src/lib/servers.ts`, `frontend/src/lib/__tests__/servers.test.ts`, `frontend/src/lib/auth/messages.ts`, `frontend/src/components/servers/__tests__/connection-result.test.tsx`, `frontend/src/components/servers/__tests__/server-page.test.tsx`.

**Tests first.**
- `servers.test.ts`: "names the seven checks": sorted keys `["host_key","in_log_groups","not_in_docker_group","not_root","platform_key","sudo_checker","sudo_limited"]`.
- `connection-result.test.tsx`: `ALL_PASSED` has seven entries in backend order; "shows a working connection with its seven passed checks" (7 list items, 7 `Passed`, the label `sudo allows only megoo-ctl`); the changed-key test expects 1 `Failed` and 6 `Not checked`; the `it.each(CONNECTION_REASONS)` test covers the new reasons automatically; add `it("tells how to fix a refused key")` expecting the new `key_refused` advice text.
- `server-page.test.tsx`: its result fixture gets the three new checks.

Run **FE src/lib src/components/servers** → fails.

**Implement.**
- `servers.ts`: `ConnectionReason` adds `"account_not_in_log_groups" | "sudo_checker_missing" | "sudo_too_wide"`; `CheckName` adds `"in_log_groups" | "sudo_checker" | "sudo_limited"`; `CHECK_LABELS` adds `in_log_groups: "The account is in systemd-journal and adm"`, `sudo_checker: "megoo-ctl answers through sudo"`, `sudo_limited: "sudo allows only megoo-ctl"`.
- `messages.ts` `CONNECTION_REASONS`:
  - `key_refused.advice`: `"Run the setup script on the server with the platform's key (see Platform access), and check that --from holds the address the server sees MegooITAdmin connect from."`
  - `account_not_in_log_groups`: title `"The login account cannot read the logs."`, advice `"Run the setup script on the server again: it adds the account to systemd-journal and adm."`
  - `sudo_checker_missing`: title `"megoo-ctl is missing or out of date."`, advice `"Run the setup script on the server again: it installs megoo-ctl and the sudo rule that allows it."`
  - `sudo_too_wide`: title `"The login account may run more than megoo-ctl with sudo."`, advice `"Remove its other sudo rights (the sudo or wheel group, other files in /etc/sudoers.d), then test again."`

Run **FE** again → pass; **FE-GATE** green.

**Commit:** `feat(servers): the connection result names the three setup checks and their advice`

### 9. Frontend: the Platform access card gives the script and the command

**Files:** `frontend/src/components/servers/platform-access-card.tsx`, `frontend/src/components/servers/__tests__/platform-access-card.test.tsx`.

**Tests first** (replace the "both steps" test; keep the error test):
- "gives the script": a link named `Download megoo-setup.sh` with `href="/api/ssh/setup-script"` and a `download` attribute; the text `or take backend/app/ssh/megoo-setup.sh from the repository.`
- "shows the command with the key": once the key loads, a `code` element with exactly `sudo sh megoo-setup.sh --from <platform-address> --key 'KEY'`; text `2. Run it as root on the server, with the platform's address in place of <platform-address>:`.
- "adds --user only for another account": `username="ops-bot"` → the command ends with ` --user 'ops-bot'`; with `megoo` there is no `--user`. A name with a quote, `o'x`, is shown as `--user 'o'\''x'`.
- "copies the command": Copy writes the whole command; the button then reads `Copied`.
- "shows step 3 and the firewall note": `3. Pin the host key and test the connection on this page.` and `The script accepts the key only from that address. Limit SSH (port 22) to it in the firewall too: see docs/server-setup.md.`
- The error test: no Copy button and no command.

Run **FE src/components/servers/__tests__/platform-access-card.test.tsx** → fails.

**Implement**: keep the key fetch and copy logic; add `export function setupCommand(key: string, username: string): string` (`--user` only when `username !== "megoo"`, value single-quoted with `'` → `'\''`); step 1 renders `<Button asChild variant="outline" size="sm"><a href="/api/ssh/setup-script" download="megoo-setup.sh">Download megoo-setup.sh</a></Button>` and the repository text; step 2 the command in `<code className="font-mono break-all">` with Copy; step 3 text; the note in a `<p className="text-muted-foreground">`. Update the component's doc comment. Run → pass; **FE-GATE** green.

**Commit:** `feat(servers): the Platform access card gives the setup script and the command to run`

### 10. Docs: preparing a server

**Files:** `docs/server-setup.md` (new), `README.md` ("Servers"), `AGENTS.md` (Safety bullet on the fake server).

`docs/server-setup.md` sections (plain sentences, the repository's style):
1. **What the script does**: the seven steps of the design, both commands (`sudo sh megoo-setup.sh --from <addresses> --key '<key>' [--user <name>]`, `--check`), exit codes 0 ready / 1 checks failed / 2 refused before any change, where to get it (Platform access → Download, or `backend/app/ssh/megoo-setup.sh`), supported systems, what it never does (no packages, no sshd or firewall change, never removes other sudo rights).
2. **What megoo-ctl allows**: the version 1 table of the design.
3. **Limit SSH to the platform's address**: `ufw allow from <addr> to any port 22 proto tcp` then `ufw deny 22/tcp`; firewalld rich rule `firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="<addr>" port port="22" protocol="tcp" accept'` plus removing the `ssh` service, `firewall-cmd --reload`; a cloud security group inbound rule for TCP 22 from `<addr>/32` only. Warn to keep a console or another allowed address before closing port 22.
4. **Remote Desktop (Windows, Phase 2)**: `Set-NetFirewallRule -DisplayGroup "Remote Desktop" -RemoteAddress <addr>` in an elevated PowerShell.
5. **Run it again**: after a MegooITAdmin upgrade that raises megoo-ctl's version (Test connection says `megoo-ctl is missing or out of date`), and after a new platform key.
6. **Remove the setup**: `rm /etc/sudoers.d/megoo-ctl-megoo /usr/local/sbin/megoo-ctl`, `userdel -r megoo`.
7. **Checklist for a real server** (the owner's, by hand): download, run, see `The server is ready.`, register, pin the host key, Test connection shows seven passed checks; run `--check` once more.

`README.md` Servers: replace the "Prepare the account `megoo`…" and "The platform's public key…" bullets with: "Prepare each Linux server with the setup script (Platform access card → Download, or `backend/app/ssh/megoo-setup.sh`): it creates `megoo` in `systemd-journal` and `adm`, never in `docker`, allows it only `megoo-ctl` with sudo, and accepts the platform's key only from the platform's address. See [docs/server-setup.md](docs/server-setup.md)." Keep `make ssh-public-key`. Mention that Test connection checks seven things.

`AGENTS.md` Safety: the fake server is prepared by `megoo-setup.sh` and has `megoo` plus the wrong accounts `megoo-docker`, `megoo-root`, `megoo-nologs`, `megoo-nosudo`, `megoo-wide`.

No test; run **BACKEND** once more (`test_makefile.py` reads nothing here) and confirm the links resolve (`ls docs/server-setup.md`).

**Commit:** `docs: preparing a server with megoo-setup.sh, limiting SSH and RDP to the platform, and removing the setup`

## Final verification

From the repository root: `make test` and `make test-security` pass. By hand: `make up STACK=dev`, register the fake server as `fake-server`, port 22, pin its key and press Test connection: seven passed checks; the card's Download gives `megoo-setup.sh`; `make down STACK=dev`. Then the owner runs the script on one real test server (an agent never does).

---

## Appendix A: `backend/app/ssh/megoo-setup.sh`

```sh
#!/bin/sh
# megoo-setup.sh: prepares a Linux server for MegooITAdmin. Run it as root:
#   sh megoo-setup.sh --from <addresses> --key '<public key line>' [--user <name>]
#   sh megoo-setup.sh --check [--user <name>]
# It creates the account (megoo by default), puts it in systemd-journal and adm and never in docker, installs
# /usr/local/sbin/megoo-ctl and the one sudo rule that allows it, and accepts the platform's key only from the given
# addresses. Then it checks all of that. --check only checks and changes nothing. It installs no packages and
# changes no firewall or sshd setting. Exit: 0 ready, 1 a check failed, 2 refused before any change.
# See docs/server-setup.md.
set -eu
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
LC_ALL=C
export PATH LC_ALL
umask 022

CTL_VERSION=1
CTL=/usr/local/sbin/megoo-ctl
NL='
'

usage() {
  echo "Usage: sh megoo-setup.sh --from <addresses> --key '<public key line>' [--user <name>]" >&2
  echo "       sh megoo-setup.sh --check [--user <name>]" >&2
  exit 2
}
stop() { echo "megoo-setup: $1 Nothing was changed." >&2; exit 2; }

user=megoo from= key= check=
while [ $# -gt 0 ]; do
  case "$1" in
    --from) [ $# -ge 2 ] || usage; from=$2; shift 2 ;;
    --key) [ $# -ge 2 ] || usage; key=$2; shift 2 ;;
    --user) [ $# -ge 2 ] || usage; user=$2; shift 2 ;;
    --check) check=1; shift ;;
    *) usage ;;
  esac
done

# 1. Everything is checked before anything changes.
[ "$(id -u)" = 0 ] || stop "Run it as root: sudo sh megoo-setup.sh …"
for tool in sudo visudo useradd usermod gpasswd getent ssh-keygen stat cmp mktemp; do
  command -v "$tool" > /dev/null 2>&1 || stop "$tool is missing: install it first."
done
getent group systemd-journal > /dev/null || stop "The group systemd-journal is missing: the server needs systemd."
getent group adm > /dev/null || stop "The group adm is missing."
[ -d /etc/sudoers.d ] || stop "/etc/sudoers.d is missing."
case "$user" in
  root) stop "The account may not be root." ;;
  ''|[!a-z_]*|*[!a-z0-9_-]*) stop "Not an account name: $user (use a-z, 0-9, _ and -)." ;;
esac
[ ${#user} -le 32 ] || stop "Not an account name: $user (32 characters at most)."
if getent passwd "$user" > /dev/null && [ "$(id -u "$user")" = 0 ]; then
  stop "$user has uid 0: use an account that is not root."
fi
if [ -z "$check" ]; then
  [ -n "$from" ] || stop "--from is required: the platform's address, for example --from 203.0.113.10."
  case "$from" in
    *[!A-Za-z0-9.:/,*?!-]*) stop "--from may hold only addresses, ranges, host names, * ? ! and commas." ;;
  esac
  [ -n "$key" ] || stop "--key is required: the platform's public key line, from the server page."
  case "$key" in
    *"$NL"*|*\"*|*\'*) stop "--key must be one public key line." ;;
    ssh-ed25519\ *|ssh-rsa\ *|ecdsa-sha2-*\ *|sk-*\ *) ;;
    *) stop "--key must start with the key type, such as ssh-ed25519." ;;
  esac
  keyfile=$(mktemp)
  printf '%s\n' "$key" > "$keyfile"
  if ! ssh-keygen -l -f "$keyfile" > /dev/null 2>&1; then rm -f "$keyfile"; stop "--key is not a public key."; fi
  rm -f "$keyfile"
fi

changed=
say() { echo "$1"; changed=1; }
in_group() { id -Gn "$1" | tr ' ' '\n' | grep -qx "$2"; }

# write_file <path> <owner> <group> <mode> <tmp>: moves tmp into place, unless the path already holds the same
# content with that owner and mode.
write_file() {
  if [ -f "$1" ] && cmp -s "$5" "$1" && [ "$(stat -c '%U:%G %a' "$1")" = "$2:$3 $4" ]; then
    rm -f "$5"
    return 0
  fi
  chown "$2:$3" "$5"
  chmod "$4" "$5"
  mv -f "$5" "$1"
  say "Wrote $1."
}

ctl_text() {
  printf '#!/bin/sh\n# megoo-ctl %s, written by megoo-setup.sh: the only command MegooITAdmin may run with sudo.\n' "$CTL_VERSION"
  printf '# Do not edit it: run megoo-setup.sh again instead.\nCTL_VERSION=%s\n' "$CTL_VERSION"
  cat << 'CTL'
# (Appendix B, from "PATH=" to the final "esac")
CTL
}

if [ -z "$check" ]; then
  # 2. The account.
  if ! getent passwd "$user" > /dev/null; then
    useradd -m -s /bin/bash "$user"
    usermod -p '*' "$user"
    say "Created the account $user."
  fi
  # 3. Its groups.
  for group in systemd-journal adm; do
    if ! in_group "$user" "$group"; then usermod -aG "$group" "$user"; say "Added $user to $group."; fi
  done
  if getent group docker > /dev/null && in_group "$user" docker; then
    gpasswd -d "$user" docker > /dev/null
    say "Removed $user from the docker group: that group is as strong as root."
  fi
  # 4. megoo-ctl.
  [ -d /usr/local/sbin ] || install -d -m 0755 -o root -g root /usr/local/sbin
  tmp=$(mktemp /usr/local/sbin/.megoo-ctl.XXXXXX)
  ctl_text > "$tmp"
  write_file "$CTL" root root 755 "$tmp"
  # 5. The sudo rule. sudo skips files in /etc/sudoers.d whose name holds a dot, so the temporary file is never read.
  tmp=$(mktemp /etc/sudoers.d/.megoo-ctl.XXXXXX)
  printf '%s ALL=(root) NOPASSWD: %s\n' "$user" "$CTL" > "$tmp"
  chmod 440 "$tmp"
  if ! visudo -cf "$tmp" > /dev/null 2>&1; then
    rm -f "$tmp"
    echo "megoo-setup: the sudo rule did not pass visudo -c, so it was not installed." >&2
    exit 1
  fi
  write_file "/etc/sudoers.d/megoo-ctl-$user" root root 440 "$tmp"
  # 6. The key, accepted only from the platform's addresses.
  home=$(getent passwd "$user" | cut -d: -f6)
  group=$(id -gn "$user")
  [ -d "$home/.ssh" ] || install -d -m 0700 -o "$user" -g "$group" "$home/.ssh"
  chown "$user:$group" "$home/.ssh"
  chmod 0700 "$home/.ssh"
  tmp=$(mktemp "$home/.ssh/.authorized_keys.XXXXXX")
  printf 'from="%s" %s\n' "$from" "$key" > "$tmp"
  write_file "$home/.ssh/authorized_keys" "$user" "$group" 600 "$tmp"
  [ -n "$changed" ] || echo "Nothing to change."
fi

# 7. The checks.
failed=0
ok() { printf '[ok]   %s\n' "$1"; }
fail() { printf '[FAIL] %s\n' "$1"; failed=$((failed + 1)); }
if ! getent passwd "$user" > /dev/null; then
  fail "The account $user does not exist."
  echo "$failed check(s) failed. Run megoo-setup.sh with --from and --key."
  exit 1
fi
ok "The account $user exists and is not root (uid $(id -u "$user"))."
if in_group "$user" docker; then fail "$user is in the docker group."; else ok "$user is not in the docker group."; fi
for group in systemd-journal adm; do
  if in_group "$user" "$group"; then ok "$user is in $group."; else fail "$user is not in $group."; fi
done
if [ -f "$CTL" ] && [ "$(stat -c '%U %a' "$CTL")" = "root 755" ] && [ "$("$CTL" version 2> /dev/null)" = "megoo-ctl $CTL_VERSION" ]; then
  ok "$CTL is version $CTL_VERSION, owned by root, mode 755."
else
  fail "$CTL is missing, out of date, or not owned by root with mode 755."
fi
allowed=$(sudo -l -U "$user" 2> /dev/null | sed -n '/may run the following commands/,$p' | sed '1d' \
  | sed -e 's/^[[:space:]]*//' -e '/^$/d' -e 's/^([^)]*)[[:space:]]*//' -e 's/^\([A-Z_]*:[[:space:]]*\)*//')
if [ "$allowed" = "$CTL" ]; then
  ok "sudo allows $user only $CTL."
else
  fail "sudo allows $user more than $CTL, or not $CTL. It allows:"
  printf '%s\n' "${allowed:-nothing}" | sed 's/^/         /'
fi
home=$(getent passwd "$user" | cut -d: -f6)
keys=$home/.ssh/authorized_keys
if [ -f "$keys" ] && [ "$(stat -c '%U %a' "$keys")" = "$user 600" ] && [ "$(stat -c '%U %a' "$home/.ssh")" = "$user 700" ] \
  && [ "$(grep -cv -e '^[[:space:]]*#' -e '^[[:space:]]*$' "$keys")" = 1 ] && grep -q '^from="[^"]*" ' "$keys"; then
  ok "$keys holds one key, $(ssh-keygen -l -f "$keys" | cut -d' ' -f2), accepted from $(sed -n 's/^from="\([^"]*\)" .*/\1/p' "$keys")."
else
  fail "$keys must hold exactly one key limited with from=\"…\", owned by $user, mode 600, in a 700 directory."
fi
if [ "$failed" = 0 ]; then
  echo "The server is ready. Pin its host key and test the connection on the server page."
  echo "Also limit SSH (port 22) to the platform's address in the firewall or security group: see docs/server-setup.md."
  exit 0
fi
echo "$failed check(s) failed."
exit 1
```

Output contract used by the tests: change lines `Created the account <u>.`, `Added <u> to <group>.`, `Removed <u> from the docker group…`, `Wrote <path>.`, `Nothing to change.`; check lines start with `[ok]   ` or `[FAIL] `; last lines `The server is ready.…` or `<n> check(s) failed.`; refusals on stderr end with `Nothing was changed.` and exit 2.

## Appendix B: the `megoo-ctl` body (inside the `CTL` heredoc)

```sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
LC_ALL=C
export PATH LC_ALL

refuse() { echo "megoo-ctl: refused: $1" >&2; exit 2; }
container() {
  case "$1" in ''|[!A-Za-z0-9]*|*[!A-Za-z0-9_.-]*) refuse "not a container: $1" ;; esac
  [ ${#1} -le 128 ] || refuse "not a container: $1"
}
pid() {
  case "$1" in ''|*[!0-9]*|0*) refuse "not a process id: $1" ;; esac
  [ ${#1} -le 10 ] && [ "$1" -gt 1 ] || refuse "process $1 may not be touched"
}

verb=${1-}
[ $# -eq 0 ] || shift
case "$verb" in
  version)
    [ $# -eq 0 ] || refuse "version takes no arguments"
    echo "megoo-ctl $CTL_VERSION" ;;
  docker)
    sub=${1-}
    [ $# -eq 0 ] || shift
    case "$sub" in
      ps)
        [ $# -eq 0 ] || refuse "docker ps takes no arguments"
        exec docker ps --all --no-trunc --format '{{json .}}' ;;
      logs)
        [ $# -ge 1 ] || refuse "docker logs needs a container"
        name=$1
        shift
        container "$name"
        follow= tail= since=
        while [ $# -gt 0 ]; do
          case "$1" in
            --follow) follow=1; shift ;;
            --tail)
              [ $# -ge 2 ] || refuse "--tail needs a number"
              case "$2" in ''|*[!0-9]*) refuse "not a number: $2" ;; esac
              [ ${#2} -le 7 ] || refuse "not a number: $2"
              tail=$2; shift 2 ;;
            --since)
              [ $# -ge 2 ] || refuse "--since needs a time"
              case "$2" in ''|[!0-9]*|*[!0-9A-Za-z:.+-]*) refuse "not a time: $2" ;; esac
              [ ${#2} -le 40 ] || refuse "not a time: $2"
              since=$2; shift 2 ;;
            *) refuse "docker logs does not take $1" ;;
          esac
        done
        set -- --timestamps
        if [ -n "$follow" ]; then set -- "$@" --follow; fi
        if [ -n "$tail" ]; then set -- "$@" --tail "$tail"; fi
        if [ -n "$since" ]; then set -- "$@" --since "$since"; fi
        exec docker logs "$@" "$name" ;;
      start|stop|restart)
        [ $# -eq 1 ] || refuse "docker $sub takes one container"
        container "$1"
        exec docker "$sub" "$1" ;;
      *) refuse "docker ${sub:-without a command} is not allowed" ;;
    esac ;;
  kill)
    [ $# -ge 2 ] || refuse "kill needs a signal and a process id"
    case "$1" in TERM|KILL|HUP|STOP|CONT) ;; *) refuse "signal $1 is not allowed" ;; esac
    signal=$1
    shift
    for p in "$@"; do pid "$p"; done
    kill -s "$signal" "$@" ;;
  renice)
    [ $# -ge 2 ] || refuse "renice needs a priority and a process id"
    case "$1" in -[0-9]|-1[0-9]|-20|[0-9]|1[0-9]) ;; *) refuse "priority $1 is not allowed" ;; esac
    priority=$1
    shift
    for p in "$@"; do pid "$p"; done
    exec renice -n "$priority" -p "$@" ;;
  systemctl)
    [ $# -eq 2 ] || refuse "systemctl takes a verb and one unit"
    case "$1" in start|stop|restart|reload|enable|disable) ;; *) refuse "systemctl $1 is not allowed" ;; esac
    case "$2" in
      [!A-Za-z0-9]*|*[!A-Za-z0-9:_.@-]*) refuse "not a unit: $2" ;;
      *.service|*.socket|*.timer) ;;
      *) refuse "not a unit: $2" ;;
    esac
    exec systemctl --no-pager --no-ask-password "$1" -- "$2" ;;
  *) refuse "unknown call: ${verb:-none}" ;;
esac
```

## Appendix C: `app/ssh/setup.py` and the client

`backend/app/ssh/setup.py`:
```python
"""The setup script an admin runs on each server (megoo-setup.sh, bundled with the backend), and the version of the
megoo-ctl it installs: the script is the only place that version is written."""

import re
from functools import cache
from pathlib import Path

SCRIPT = Path(__file__).with_name("megoo-setup.sh")


@cache
def script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


@cache
def ctl_version() -> int:
    match = re.search(r"^CTL_VERSION=(\d+)$", script_text(), re.MULTILINE)
    if match is None:
        raise RuntimeError(f"{SCRIPT} sets no CTL_VERSION")
    return int(match.group(1))
```

Added to `backend/app/ssh/client.py` (module docstring gains: "and what the signed-in account may do with sudo"):
```python
CTL = "/usr/local/sbin/megoo-ctl"
_SUDO_HEADER = re.compile(r"^User \S+ may run the following commands on ")
_RUNAS = re.compile(r"^\([^)]*\)\s*")
_TAGS = re.compile(r"^(?:[A-Z_]+:\s*)+")


@dataclass(frozen=True)
class Setup:
    """What the setup script left on the server, as the signed-in account sees it."""

    version: int | None  # megoo-ctl's version through sudo; None when it did not answer
    limited: bool | None  # True: sudo allows only megoo-ctl; False: it allows more; None: the list could not be read


def sudo_commands(text: str) -> list[str] | None:
    """The commands of `sudo -l` (LC_ALL=C), or None when the text is not that list."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if _SUDO_HEADER.match(line)), None)
    if start is None:
        return None
    commands: list[str] = []
    for line in lines[start + 1 :]:
        if not line.strip():
            continue
        if not line[0].isspace():
            break
        entry = _TAGS.sub("", _RUNAS.sub("", line.strip()))
        commands += [command.strip() for command in entry.split(",") if command.strip()]
    return commands


async def setup_of(conn: asyncssh.SSHClientConnection) -> Setup:
    """megoo-ctl's version and whether sudo allows the account only megoo-ctl. Only an integer and a yes/no leave
    this function: what the server printed never reaches a response or an event."""
    try:
        version = await conn.run(f"sudo -n {CTL} version", timeout=COMMAND_TIMEOUT)
        listed = await conn.run("LC_ALL=C sudo -n -l", timeout=COMMAND_TIMEOUT)
    except (asyncssh.Error, TimeoutError) as error:
        raise AccountCheckFailed() from error
    found = re.fullmatch(r"megoo-ctl (\d{1,6})", str(version.stdout).strip()) if version.exit_status == 0 else None
    commands = sudo_commands(str(listed.stdout)) if listed.exit_status == 0 else None
    limited = None if not commands else all(command == CTL for command in commands)
    return Setup(version=int(found.group(1)) if found else None, limited=limited)
```
(Imports: `re`, `from dataclasses import dataclass`.)

Samples for the pure tests:
```
Matching Defaults entries for megoo on fake:
    env_reset, mail_badpass, secure_path=/usr/local/sbin\:/usr/local/bin

User megoo may run the following commands on fake:
    (root) NOPASSWD: /usr/local/sbin/megoo-ctl
```
The wide sample adds `    (ALL) NOPASSWD: ALL`. The root sample has `    (ALL : ALL) ALL`. The unknown sample is `Benutzer megoo darf die folgenden Befehle ausführen:` + an entry. The empty sample is the header alone.

## Appendix D: `connection.py` and `connection_schemas.py`

Schemas: `Reason` adds `"account_not_in_log_groups"`, `"sudo_checker_missing"`, `"sudo_too_wide"` (after `account_in_docker_group`); `CheckName = Literal["host_key", "platform_key", "not_root", "not_in_docker_group", "in_log_groups", "sudo_checker", "sudo_limited"]`; the `checks` comment says "Always the seven".

`connection.py` (`from app.ssh.setup import ctl_version`; docstrings say seven):
```python
LOG_GROUPS = frozenset({"systemd-journal", "adm"})


def _passed(ok: bool) -> CheckStatus:
    return "passed" if ok else "failed"


def _checks(reason: str | None, account: tuple[int, list[str]] | None, sudo: client.Setup | None) -> list[Check]:
    """The seven checks of an outcome, in CheckName order. `account` and `sudo` are what was read, or None."""
    statuses: tuple[CheckStatus, ...] = _SIGN_IN_CHECKS.get(reason, ("passed", "passed"))
    if account is None:
        statuses += ("not_run",) * 3
    else:
        uid, groups = account
        statuses += (_passed(uid != 0), _passed("docker" not in groups), _passed(LOG_GROUPS <= set(groups)))
    if sudo is None:
        statuses += ("not_run",) * 2
    else:
        statuses += (
            _passed(sudo.version is not None and sudo.version >= ctl_version()),
            "not_run" if sudo.limited is None else _passed(sudo.limited),
        )
    return [Check(name=name, status=status) for name, status in zip(get_args(CheckName), statuses, strict=True)]


def _reason(account: tuple[int, list[str]], sudo: client.Setup, bundled: int) -> str | None:
    """The first failed check, in the order root, docker, log groups, checker, too wide; an unreadable sudo list with
    a working checker is account_check_failed."""
    uid, groups = account
    if uid == 0:
        return "account_is_root"
    if "docker" in groups:
        return "account_in_docker_group"
    if not LOG_GROUPS <= set(groups):
        return "account_not_in_log_groups"
    if sudo.version is None or sudo.version < bundled:
        return "sudo_checker_missing"
    if sudo.limited is False:
        return "sudo_too_wide"
    if sudo.limited is None:
        return "account_check_failed"
    return None
```
In `test_connection`: `account = None; sudo: client.Setup | None = None`; inside the connection `account = await client.account_of(conn)` then `sudo = await client.setup_of(conn)`; `else: reason = _reason(account, sudo, ctl_version())`; `checks = _checks(reason, account, sudo)`. When `setup_of` raises `AccountCheckFailed` the account statuses are still reported and the two sudo checks are `not_run`. The event detail is unchanged apart from holding seven checks.

## Appendix E: `tools/fake-server/authorize-key`

```sh
#!/bin/sh
# Reads one public key line on stdin and prepares the fake server with it, as megoo-setup.sh prepares a real server:
# megoo, and megoo-nologs (then taken out of adm), megoo-nosudo (then without its sudo rule) and megoo-wide (then
# allowed everything). megoo-docker and megoo-root get the plain key. $1: the addresses the key is accepted from; the
# default is loopback and the private ranges, which covers pytest on the host and the Compose networks.
set -e
from=${1:-127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,::1,fc00::/7}
key=$(head -n 1)
printf '%s\n' "$key" > /tmp/authorized.pub
ssh-keygen -l -f /tmp/authorized.pub > /dev/null || { echo "Not a public key." >&2; exit 1; }
# The script refuses a server where megoo-wide may do more, so its extra rule goes first and comes back after.
rm -f /etc/sudoers.d/megoo-wide-all
for user in megoo megoo-nologs megoo-nosudo megoo-wide; do
  out=$(sh /usr/local/lib/megoo-setup.sh --user "$user" --from "$from" --key "$key") || { printf '%s\n' "$out" >&2; exit 1; }
done
gpasswd -d megoo-nologs adm > /dev/null
rm -f /etc/sudoers.d/megoo-ctl-megoo-nosudo
printf 'megoo-wide ALL=(ALL) NOPASSWD: ALL\n' > /tmp/megoo-wide-all
visudo -cf /tmp/megoo-wide-all > /dev/null
install -m 0440 -o root -g root /tmp/megoo-wide-all /etc/sudoers.d/megoo-wide-all
rm -f /tmp/megoo-wide-all
for user in megoo-docker megoo-root; do
  home=$(getent passwd "$user" | cut -d: -f6)
  group=$(id -gn "$user")
  install -d -m 0700 -o "$user" -g "$group" "$home/.ssh"
  install -m 0600 -o "$user" -g "$group" /tmp/authorized.pub "$home/.ssh/authorized_keys"
done
rm -f /tmp/authorized.pub
echo "Prepared megoo and the wrong accounts with the key, accepted from $from."
```

## Appendix F: megoo-ctl test tables (`tests/security/test_server_setup.py`)

Allowed `(args → logged line)`; `version` logs nothing and prints `megoo-ctl 1`:

| args | logged |
|---|---|
| `docker ps` | `docker [ps] [--all] [--no-trunc] [--format] [{{json .}}]` |
| `docker logs web-1` | `docker [logs] [--timestamps] [web-1]` |
| `docker logs web-1 --follow --tail 100 --since 10m` | `docker [logs] [--timestamps] [--follow] [--tail] [100] [--since] [10m] [web-1]` |
| `docker logs 0123abcd --since 2026-11-24T10:00:00Z` | `docker [logs] [--timestamps] [--since] [2026-11-24T10:00:00Z] [0123abcd]` |
| `docker start web-1` / `stop` / `restart` | `docker [start] [web-1]` (and so on) |
| `systemctl restart nginx.service` | `systemctl [--no-pager] [--no-ask-password] [restart] [--] [nginx.service]` |
| `systemctl enable getty@tty1.service` | `systemctl [--no-pager] [--no-ask-password] [enable] [--] [getty@tty1.service]` |
| `systemctl stop docker.socket` | `… [stop] [--] [docker.socket]` |
| `systemctl disable apt-daily.timer` | `… [disable] [--] [apt-daily.timer]` |

Refused (exit 2, nothing logged): `systemctl enable /home/megoo/x.service`; `systemctl start reboot.target`; `systemctl start a.service b.service`; `systemctl daemon-reload`; `systemctl start -x.service`; `systemctl start x.service;id`; `docker run alpine`; `docker exec web-1 sh`; `docker ps --all`; `docker logs --host=tcp://x`; `docker logs -H`; `docker logs web-1 --tail ten`; `docker logs web-1 --since $(id)`; `docker restart ../x`; `docker restart a b`; `kill INT 1234`; `kill TERM 1`; `kill TERM 0`; `kill TERM -1`; `kill TERM 1;id`; `kill TERM 12 1`; `renice 99 1234`; `renice -21 1234`; `renice 5 1`; `version extra`; `sh`; no arguments.
