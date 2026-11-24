# MITA-11 plan: SSH connect with host-key pinning, and the fake-server fixture

## Goal

The Owner, or an Admin of a server's group, fetches a Linux server's host key, confirms its fingerprint and pins it. Anyone with Connect SSH in the group then tests the connection as `megoo` with the platform's Ed25519 key. A server that presents another key is refused before sign-in, flagged and blocked until someone reviews it. Every step is an audit event, and tests and dev stacks connect only to a fake sshd container.

## Architecture

A new package `backend/app/ssh/` holds the platform key (`keys.py`, a 0600 file in the `ssh_key` volume, made by the entrypoint), host-key helpers (`hostkeys.py`), the only module that opens SSH connections (`client.py`, asyncssh) and a CLI. `app/inventory/connection.py` adds the four server actions (fetch, pin/replace, keep, test) and `open_connection()`, the door later features use. It flags a server and records `server.host_key_mismatch` in a transaction of its own. Migration `0007` adds four columns to `servers`. `tools/fake-server/` is a Debian image with OpenSSH, three accounts and two commands. It joins the `test` service set (published port for pytest), the `stack` set and the dev/e2e stacks (on the `servers` network). The frontend server page gains the state badge, banners, a pin dialog, a review dialog, the test result and the Platform access card. The list gains two badges.

## Commands used in the steps

- **BT `<paths>`** (from `backend/`): `megoocolab-runner services run test -- uv run pytest <paths>`. The `test` set starts the database **and the fake server** (after step 2).
- **BACKEND** (from `backend/`): `megoocolab-runner services run test -- uv run pytest`
- **MIGRATE** (from `backend/`): `megoocolab-runner services run migrate -- sh -c 'uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head'`
- **DOCKER** (from `backend/`): `megoocolab-runner services run image -- uv run pytest -m docker`
- **STACK** (from `backend/`): `megoocolab-runner services run stack -- uv run pytest -m stack`
- **SECURITY** (root): `make test-security`
- **FE `<path>`** (from `frontend/`): `npx vitest run <path>`
- **FE-GATE** (from `frontend/`): `npx tsc --noEmit && npx eslint <changed files> && npm test`

Test files under `backend/tests/` have no `__init__.py` and import helpers by basename (`from auth_helpers import …`), so every new test file needs a unique basename.

## File map

### Backend (`backend/`)

| File | Change |
|---|---|
| `pyproject.toml`, `uv.lock` | `asyncssh` dependency (`uv add asyncssh`) |
| `app/core/config.py` | `ssh_key_file: str = "/var/lib/megooitadmin/ssh/id_ed25519"` |
| `app/ssh/__init__.py` (new) | Docstring: "SSH: the platform's key, host keys, and the one module that connects." |
| `app/ssh/keys.py` (new) | C2 |
| `app/ssh/hostkeys.py` (new) | C3 |
| `app/ssh/client.py` (new) | C4 |
| `app/ssh/cli.py` (new) | C5 |
| `migrations/versions/0007_host_key_pinning.py` (new), `app/inventory/models.py` | C6 |
| `app/inventory/actions.py` | C7 |
| `app/inventory/server_schemas.py` | `HostKeyOffer`, new `ServerOut` fields, `root` refused (C8) |
| `app/inventory/servers.py` | `host_key_state`, `_out` fields, decision 8 in `update_server`, fingerprint in `server.deleted` (C8) |
| `app/inventory/connection_schemas.py` (new) | C9 |
| `app/inventory/connection.py` (new) | C10 |
| `app/inventory/server_router.py` | Five routes (C11) |
| `Dockerfile`, `docker-entrypoint.sh` | Key directory 0700, `ensure-key` at start |
| `tests/conftest.py` | `SSH_KEY_FILE` to a temporary file; the `fake_server` fixture |
| `tests/fake_server.py` (new) | C12 |
| `tests/auth_helpers.py` | `make_server(..., host_key=None)` unchanged signature plus `pin_host_key(client, server_id)` |
| `tests/ssh/test_ssh_keys.py`, `test_host_keys.py`, `test_ssh_cli.py`, `test_fake_server.py`, `test_ssh_client.py` (new) | Unit and fake-server tests |
| `tests/inventory/test_host_key_pin.py`, `test_connection_test.py`, `test_host_key_review.py` (new) | Route tests |
| `tests/inventory/test_server_schemas.py`, `test_server_register.py`, `test_server_edit.py`, `test_server_remove.py` | New fields, root, decision 8, deleted fingerprint |
| `tests/security/test_host_key_pinning.py` (new) | The task's sentence; the only-client.py check |
| `tests/security/test_permission_coverage.py`, `test_access_events.py` | `GET /api/ssh/public-key` pinned; the walk |
| `tests/test_migrations.py`, `test_container.py`, `test_stack.py`, `test_makefile.py` | 0007; key in the image; stack walk; make targets |

### Root and tools

| File | Change |
|---|---|
| `tools/fake-server/Dockerfile`, `sshd_config`, `entrypoint.sh`, `authorize-key`, `swap-host-key` (new) | The fake server image (C12) |
| `tools/fake-server/docker-compose.test.yml` (new) | For the `test` set: sshd on `127.0.0.1:${SSH_PORT}` |
| `tools/fake-server/docker-compose.stack.yml` (new) | For the `stack` set and the dev/e2e stacks: `fake-server` on `servers` |
| `megoocolab.toml` | `test` set: second Compose file, port `SSH_PORT`; `stack` set: second Compose file |
| `.gitattributes` | `tools/fake-server/* text eol=lf` (two scripts have no `.sh`) |
| `docker-compose.yml` | Volume `ssh_key` on the backend only |
| `Makefile` | Stacks include the fake server; `ssh-public-key`; `fake-server-swap` |
| `README.md`, `AGENTS.md` | Docs |

### Frontend (`frontend/`)

| File | Change |
|---|---|
| `src/lib/servers.ts` | C13 types, `CHECK_LABELS`, `fingerprintCommand` |
| `src/lib/auth/messages.ts` | C14 refusals, `CONNECTION_REASONS`, `reasonText` |
| `src/components/servers/connection-result.tsx` (new) | `ConnectionResult` |
| `src/components/servers/host-key-dialog.tsx` (new) | `HostKeyDialog` |
| `src/components/servers/review-host-key-dialog.tsx` (new) | `ReviewHostKeyDialog` |
| `src/components/servers/platform-access-card.tsx` (new) | `PlatformAccessCard` |
| `src/components/servers/server-page.tsx` | Badge, banners, host key row, Test connection, dialogs, card |
| `src/components/servers/servers-page.tsx` | Two badges |
| Tests beside each, and the `Server` fixtures in `src/lib/__tests__/servers.test.ts`, `src/components/servers/__tests__/{servers-page,remove-server-dialog,server-page,server-dialog}.test.tsx` | New fields |

## Contracts shared by the steps

### C1. Settings

`app/core/config.py`, in `Settings` after `api_docs`:

```python
# The platform's SSH private key: one Ed25519 key, made by the entrypoint at the first start (Phase 3 moves it
# into the vault).
ssh_key_file: str = "/var/lib/megooitadmin/ssh/id_ed25519"
```

`tests/conftest.py`, in `pytest_configure` after `AUTH_SECRET_KEY` (only the database branch, not `-m docker`/`-m stack`):

```python
# Each run makes its own platform key in a fresh directory, never the image's path.
os.environ["SSH_KEY_FILE"] = str(Path(tempfile.mkdtemp(prefix="megooitadmin-ssh-")) / "id_ed25519")
```

### C2. `app/ssh/keys.py`

```python
KEY_COMMENT = "megooitadmin"

class KeyFileError(RuntimeError):
    """The key file is missing, not a file, or readable by others."""

def key_path() -> Path:                       # Path(get_settings().ssh_key_file)
def ensure_key(path: Path | None = None) -> bool:
    """Creates the key once: parent made with 0700 when missing; asyncssh.generate_private_key("ssh-ed25519",
    comment=KEY_COMMENT); written through os.open(path, O_WRONLY | O_CREAT | O_EXCL, 0o600). Returns True when it
    made the key. An existing file (or FileExistsError from a race) is checked with _check_file and kept: False."""
def _check_file(path: Path) -> None:
    # not stat.S_ISREG -> KeyFileError(f"{path} is not a file")
    # mode & 0o077 -> KeyFileError(f"The platform's SSH key {path} is readable by others (mode {mode:o}). Run chmod 600 on it.")
def load_key(path: Path | None = None) -> asyncssh.SSHKey:
    # missing -> KeyFileError(f"The platform's SSH key {path} is missing. Restart the backend to make a new one, then put its public key on every server.")
    # then _check_file, then asyncssh.read_private_key(path)
def public_key(path: Path | None = None) -> str:
    # load_key(path).export_public_key("openssh").decode().strip()  -> "ssh-ed25519 AAAA… megooitadmin"
```

### C3. `app/ssh/hostkeys.py`

```python
class InvalidHostKey(ValueError): ...

def parse(line: str) -> asyncssh.SSHKey        # asyncssh.import_public_key(line.strip()); any error -> InvalidHostKey
def openssh_line(key: asyncssh.SSHKey) -> str  # " ".join(key.export_public_key("openssh").decode().split()[:2]): no comment
def fingerprint(line: str) -> str              # parse(line).get_fingerprint("sha256") -> "SHA256:…"
def key_type(line: str) -> str                 # parse(line).get_algorithm().decode() if bytes, e.g. "ssh-ed25519"
```

### C4. `app/ssh/client.py` (the only module that opens SSH connections)

```python
CONNECT_TIMEOUT = 10   # seconds: TCP and key exchange
LOGIN_TIMEOUT = 10     # seconds: sign-in
COMMAND_TIMEOUT = 5    # seconds: the account check
# What a fetch accepts, best first. No "ssh-rsa" (SHA-1): such servers fail with ssh_error.
HOST_KEY_ALGS = ["ssh-ed25519", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521",
                 "rsa-sha2-512", "rsa-sha2-256"]

class SshFailure(Exception):
    reason = "ssh_error"
class Unreachable(SshFailure):        reason = "unreachable"
class KeyRefused(SshFailure):         reason = "key_refused"
class SshError(SshFailure):           reason = "ssh_error"
class AccountCheckFailed(SshFailure): reason = "account_check_failed"
class HostKeyChanged(SshFailure):
    reason = "host_key_changed"
    def __init__(self, presented: str | None) -> None:   # the presented key as an openssh_line, or None
        super().__init__("the server presented another host key")
        self.presented = presented

class _PinnedClient(asyncssh.SSHClient):
    """Remembers the key a server presented when it was not the pinned one; trusts nothing else."""
    def __init__(self) -> None:
        self.presented: asyncssh.SSHKey | None = None
    def validate_host_public_key(self, host, addr, port, key) -> bool:
        self.presented = key
        return False

async def fetch_host_key(address: str, port: int) -> str:
    """Key exchange only, no sign-in: asyncssh.get_server_host_key(address, port,
    server_host_key_algs=HOST_KEY_ALGS, config=None, connect_timeout=CONNECT_TIMEOUT), returned as openssh_line.
    OSError / TimeoutError -> Unreachable; asyncssh.Error -> SshError."""

@asynccontextmanager
async def connect(address: str, port: int, username: str, pinned: str) -> AsyncIterator[asyncssh.SSHClientConnection]:
    pinned_key = hostkeys.parse(pinned)
    client_key = load_key()          # BEFORE the try: a missing key file is a 500, not "unreachable"
    client = _PinnedClient()
    try:
        conn = await asyncssh.connect(
            address, port, username=username, client_keys=[client_key],
            known_hosts=([pinned_key], [], []),   # the pinned key is the only trusted key; asyncssh then offers only its algorithms
            client_factory=lambda: client, agent_path=None, preferred_auth="publickey", password=None,
            config=None, connect_timeout=CONNECT_TIMEOUT, login_timeout=LOGIN_TIMEOUT)
    except asyncssh.HostKeyNotVerifiable as e:
        raise HostKeyChanged(None if client.presented is None else hostkeys.openssh_line(client.presented)) from e
    except asyncssh.PermissionDenied as e:
        raise KeyRefused() from e
    except (OSError, TimeoutError) as e:
        raise Unreachable() from e
    except asyncssh.Error as e:
        raise SshError() from e
    async with conn:
        yield conn

async def account_of(conn: asyncssh.SSHClientConnection) -> tuple[int, list[str]]:
    """Runs `id -u; id -Gn` (check=True, timeout=COMMAND_TIMEOUT): (uid, group names). Any asyncssh.Error,
    TimeoutError or unparsable output -> AccountCheckFailed."""
```

If the installed asyncssh refuses the 3-tuple for `known_hosts`, pass the seven-list form (`([pinned_key], [], [], [], [], [], [])`). The client tests in step 3 prove which form works. The except order matters: `HostKeyNotVerifiable` and `PermissionDenied` are `asyncssh.Error`s.

### C5. `app/ssh/cli.py`

`python -m app.ssh.cli ensure-key | public-key`, `def main(argv: list[str] | None = None) -> int` (argparse, subcommands), `if __name__ == "__main__": sys.exit(main())`.
- `ensure-key`: `ensure_key()`. True → prints `Created the platform's SSH key in {path}. Put its public key on every server: make ssh-public-key`. False → prints `The platform's SSH key is in {path}.` Exit 0. `KeyFileError` → its text on stderr, exit 1.
- `public-key`: prints `public_key()`, exit 0. `KeyFileError` → stderr, exit 1.

### C6. Migration `0007_host_key_pinning` and the model

`app/inventory/models.py`, `Server`: change the `host_key` comment to `# The pinned host key as an OpenSSH line ("ssh-ed25519 AAAA…"), set only by a pin.` and add:

```python
host_key_pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
# The candidate: the key last fetched for pinning, or the key presented at a blocked connection.
host_key_offered: Mapped[str | None] = mapped_column(Text)
host_key_offered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
# Set when a connection met another key: the server is blocked until it is reviewed.
host_key_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```
and in `__table_args__`:
```python
CheckConstraint("(host_key IS NULL) = (host_key_pinned_at IS NULL)", name="servers_host_key_pinned_check"),
CheckConstraint("host_key_changed_at IS NULL OR host_key IS NOT NULL", name="servers_host_key_changed_check"),
```
`migrations/versions/0007_host_key_pinning.py`: docstring `"""host key pinning"""`, `revision = "0007"`, `down_revision = "0006"`. `upgrade()`: `op.add_column("servers", sa.Column(<name>, sa.DateTime(timezone=True) | sa.Text(), nullable=True))` for the four columns, then `op.create_check_constraint("servers_host_key_pinned_check", "servers", "(host_key IS NULL) = (host_key_pinned_at IS NULL)")` and the changed check. `downgrade()`: drop both constraints, then the four columns. No grant: the API role already has UPDATE on `servers`.

### C7. Actions (`app/inventory/actions.py`)

```python
SERVER_HOST_KEY_FETCHED = "server.host_key_fetched"
SERVER_HOST_KEY_PINNED = "server.host_key_pinned"
SERVER_HOST_KEY_MISMATCH = "server.host_key_mismatch"
SERVER_HOST_KEY_REPLACED = "server.host_key_replaced"
SERVER_HOST_KEY_KEPT = "server.host_key_kept"
SERVER_CONNECTION_TESTED = "server.connection_tested"

CONNECTION_ACTIONS = frozenset({SERVER_HOST_KEY_FETCHED, SERVER_HOST_KEY_PINNED, SERVER_HOST_KEY_MISMATCH,
                                SERVER_HOST_KEY_REPLACED, SERVER_HOST_KEY_KEPT, SERVER_CONNECTION_TESTED})
```
Update the module docstring: "…, of the servers an Admin manages in them, and of their SSH host keys and connection tests."

### C8. Server responses, root, edits and deletes

`server_schemas.py`:
```python
HostKeyState = Literal["none", "not_pinned", "pinned", "changed"]

class HostKeyOffer(BaseModel):
    fingerprint: str
    type: str
    at: datetime

# ConnectionSettings gains:
    @field_validator("username")
    @classmethod
    def _not_root(cls, value: str) -> str:
        if value == "root":
            raise ValueError("the login account may not be root")
        return value

# ServerOut gains, after host_key:
    host_key_state: HostKeyState
    host_key_fingerprint: str | None
    host_key_type: str | None
    host_key_pinned_at: datetime | None
    host_key_changed_at: datetime | None
    # Only in the state "changed", and only when the presented key could be read.
    host_key_offered: HostKeyOffer | None
    # Whether the person may test the connection: a Linux server and Connect SSH in its group.
    can_connect: bool
```
`servers.py`:
```python
def host_key_state(server: Server) -> str:
    if server.os != "linux":
        return "none"
    if server.host_key is None:
        return "not_pinned"
    return "changed" if server.host_key_changed_at is not None else "pinned"
```
`_out` fills the fields: fingerprint/type through `hostkeys.fingerprint/key_type` when `host_key` is set; `host_key_offered = HostKeyOffer(fingerprint=…, type=…, at=server.host_key_offered_at)` only when the state is `changed` and `host_key_offered` is set; `can_connect = server.os == "linux" and access.allows(Permission.CONNECT_SSH, server.server_group_id)`.
`update_server` (decision 8): when the address or the port differs and `server.host_key is None`, set `host_key_offered = host_key_offered_at = None`. A pinned key is never touched by an edit.
`delete_server`: the `change` gains `"host_key_fingerprint": fingerprint or None` (`changes()` leaves it out when there is none).

### C9. `app/inventory/connection_schemas.py`

```python
Reason = Literal["unreachable", "host_key_changed", "key_refused", "account_is_root",
                 "account_in_docker_group", "account_check_failed", "ssh_error"]
CheckName = Literal["host_key", "platform_key", "not_root", "not_in_docker_group"]
CheckStatus = Literal["passed", "failed", "not_run"]

class Check(BaseModel):
    name: CheckName
    status: CheckStatus

class ConnectionTestResult(BaseModel):
    ok: bool
    reason: Reason | None
    checks: list[Check]          # always the four, in CheckName order

class HostKeyFetchResult(BaseModel):
    ok: bool
    reason: Reason | None
    fingerprint: str | None
    type: str | None

class HostKeyPin(BaseModel):
    fingerprint: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    # Needed only to accept a changed key. Empty is none.
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    _reason = field_validator("reason")(_none_if_empty)   # from app.inventory.schemas

class PublicKeyOut(BaseModel):
    public_key: str
```

The checks of each outcome:

| Outcome | host_key | platform_key | not_root | not_in_docker_group |
|---|---|---|---|---|
| ok | passed | passed | passed | passed |
| `unreachable`, `ssh_error` | not_run | not_run | not_run | not_run |
| `host_key_changed` | failed | not_run | not_run | not_run |
| `key_refused` | passed | failed | not_run | not_run |
| `account_check_failed` | passed | passed | not_run | not_run |
| uid 0 and/or `docker` in groups | passed | passed | failed if uid 0 else passed | failed if docker else passed |

When both account checks fail, the reason is `account_is_root`.

### C10. `app/inventory/connection.py`

```python
class ConnectionRefused(Exception):
    """Refused before connecting: detail is not_an_ssh_server, host_key_not_pinned or host_key_changed."""
    def __init__(self, detail: str) -> None: ...

def _event(server, action, *, actor, source, result=Result.SUCCESS, change=None, detail=None, reason=None) -> Event:
    # Event(action=…, actor=actor, result=result, target=servers._target(server), change=change,
    #       result_detail=detail, reason=reason, context={"server_group_id": str(server.server_group_id)}, source=source)

def _who(request, user) -> tuple[Actor, Source]:   # (actor_of(user), source_of(request, auth_method="password", mfa=True))

async def _flag_changed(server: Server, presented: str | None, *, actor, source) -> None:
    """In a SessionLocal() of its own: lock the row (with_for_update), set host_key_changed_at = func.now(),
    host_key_offered = presented, host_key_offered_at = func.now() if presented else None, flush, then record
    server.host_key_mismatch (result FAILURE, detail {"pinned_fingerprint", "presented_fingerprint" (None when
    unread), "address", "port"}), commit. A caller's rollback keeps both."""

@asynccontextmanager
async def open_connection(server: Server, *, actor: Actor, source: Source | None) -> AsyncIterator[SSHClientConnection]:
    """The door to a server for every feature. Refuses (ConnectionRefused) a non-Linux server, one without a
    pinned key and one that is flagged; on client.HostKeyChanged it calls _flag_changed and re-raises."""

async def fetch_host_key(db, request, user, server_id) -> HostKeyFetchResult
async def pin_host_key(db, request, user, access, server_id, body: HostKeyPin) -> ServerOut
async def keep_host_key(db, request, user, access, server_id) -> ServerOut
async def test_connection(db, request, user, server_id) -> ConnectionTestResult
```

Rules (every `Server` load uses `select(Server).where(Server.id == server_id)`; `record()` is always last):
- **fetch**: load without lock. Not Linux → 409 `not_an_ssh_server`. `host_key` set → 409 `host_key_pinned`. `client.fetch_host_key(address, port)`. On `SshFailure` record `server.host_key_fetched` (FAILURE, detail `{"reason", "address", "port"}`) and answer `ok=False`. On success load again `with_for_update()`, still pinned → 409 `host_key_pinned`, else set `host_key_offered = line`, `host_key_offered_at = func.now()`, flush, record SUCCESS with detail `{"fingerprint", "type", "address", "port"}`, answer `ok=True`.
- **pin** (`PUT`): load `with_for_update()`. Not Linux → 409 `not_an_ssh_server`. Pinned and not changed → 409 `host_key_pinned`. Changed and `body.reason is None` → 422 `reason_required`. `host_key_offered` missing or its fingerprint ≠ `body.fingerprint` → 409 `stale_host_key`. Then `host_key = host_key_offered`, `host_key_pinned_at = func.now()`, offered/offered_at/changed_at = None, flush, refresh. Record `server.host_key_pinned` (`change={"host_key_fingerprint": {"before": None, "after": fp}}`, detail `{"type"}`) when nothing was pinned before, else `server.host_key_replaced` (`change` before/after, `reason=body.reason`, detail `{"type"}`). Return `servers.get_server(db, access, server_id)`.
- **keep**: load `with_for_update()`. Not Linux → 409 `not_an_ssh_server`. `host_key_changed_at is None` → 409 `host_key_not_changed`. Clear changed_at, offered, offered_at. Flush, then record `server.host_key_kept` with detail `{"pinned_fingerprint", "presented_fingerprint" (None when unread)}` and return `get_server`.
- **test**: load without lock (no lock is held while talking to the server). `open_connection` → `client.account_of`, then build the checks (C9). `ConnectionRefused` → `HTTPException(409, e.detail)`. `SshFailure` → its reason. Record `server.connection_tested` in the request's session: SUCCESS or FAILURE, detail `{"username", "address", "port", "reason", "checks": {name: status}}`. Return the result.

### C11. Routes (`app/inventory/server_router.py`)

```python
admin = Depends(require_group_admin(group=group_of_server))

@router.post("/servers/{server_id}/host-key/fetch", dependencies=[admin, audited(actions.SERVER_HOST_KEY_FETCHED)])
async def fetch_host_key(server_id: UUID, request: Request, db: DbSession, user: CurrentUser) -> HostKeyFetchResult

@router.put("/servers/{server_id}/host-key",
            dependencies=[admin, audited(actions.SERVER_HOST_KEY_PINNED, actions.SERVER_HOST_KEY_REPLACED)])
async def pin_host_key(server_id: UUID, body: HostKeyPin, request: Request, db: DbSession, user: CurrentUser,
                       access: CurrentAccess) -> ServerOut

@router.post("/servers/{server_id}/host-key/keep", dependencies=[admin, audited(actions.SERVER_HOST_KEY_KEPT)])
async def keep_host_key(server_id: UUID, request: Request, db: DbSession, user: CurrentUser, access: CurrentAccess) -> ServerOut

@router.post("/servers/{server_id}/connection-test", dependencies=[
    Depends(require_grant(Permission.CONNECT_SSH, group=group_of_server)),
    audited(actions.SERVER_CONNECTION_TESTED, actions.SERVER_HOST_KEY_MISMATCH)])
async def test_connection(server_id: UUID, request: Request, db: DbSession, user: CurrentUser) -> ConnectionTestResult

@router.get("/ssh/public-key")
async def read_public_key(user: CurrentUser) -> PublicKeyOut     # PublicKeyOut(public_key=keys.public_key())
```
Update the router's module docstring to name the SSH routes.

### C12. The fake server

`tools/fake-server/Dockerfile`:
```dockerfile
# The fake server of the tests and the dev stacks: real OpenSSH, key sign-in only. It is never a real server.
FROM debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server && rm -rf /var/lib/apt/lists/*
# megoo is the account the platform uses. megoo-docker (in docker) and megoo-root (uid 0) exist so the account
# check can be tested. '*' is no password, but not a locked account, so key sign-in works.
RUN groupadd docker \
 && useradd -m -s /bin/bash megoo \
 && useradd -m -s /bin/bash -G docker megoo-docker \
 && useradd -o -u 0 -g 0 -M -d /home/megoo-root -s /bin/bash megoo-root \
 && install -d -m 0755 /home/megoo-root \
 && usermod -p '*' megoo && usermod -p '*' megoo-docker && usermod -p '*' megoo-root
COPY sshd_config /etc/ssh/sshd_config.d/fake-server.conf
COPY entrypoint.sh authorize-key swap-host-key /usr/local/bin/
RUN chmod 0755 /usr/local/bin/entrypoint.sh /usr/local/bin/authorize-key /usr/local/bin/swap-host-key
EXPOSE 22
ENTRYPOINT ["entrypoint.sh"]
```
`sshd_config` (Debian's main file includes `sshd_config.d/*.conf` first, so these win):
```
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
PermitRootLogin prohibit-password
AllowUsers megoo megoo-docker megoo-root
LogLevel INFO
```
`entrypoint.sh`:
```sh
#!/bin/sh
# Fresh host keys at every start, then sshd in the foreground as PID 1, logging to stderr (docker logs).
set -e
rm -f /etc/ssh/ssh_host_*
ssh-keygen -A
mkdir -p /run/sshd
exec /usr/sbin/sshd -D -e
```
`authorize-key`:
```sh
#!/bin/sh
# Reads one public key line on stdin and makes it the only authorized key of megoo, megoo-docker and megoo-root.
set -e
head -n 1 > /tmp/authorized.pub
ssh-keygen -l -f /tmp/authorized.pub > /dev/null || { echo "Not a public key." >&2; exit 1; }
for user in megoo megoo-docker megoo-root; do
  home=$(getent passwd "$user" | cut -d: -f6)
  group=$(id -gn "$user")
  install -d -m 0700 -o "$user" -g "$group" "$home/.ssh"
  install -m 0600 -o "$user" -g "$group" /tmp/authorized.pub "$home/.ssh/authorized_keys"
done
rm -f /tmp/authorized.pub
echo "Authorized the key for megoo, megoo-docker and megoo-root."
```
`swap-host-key`:
```sh
#!/bin/sh
# Makes new host keys, has sshd (PID 1) re-execute itself with SIGHUP so it loads them, and waits until it serves
# the new Ed25519 key.
set -e
rm -f /etc/ssh/ssh_host_*
ssh-keygen -A > /dev/null
new=$(cut -d ' ' -f 2 /etc/ssh/ssh_host_ed25519_key.pub)
kill -HUP 1
for _ in $(seq 1 50); do
  if ssh-keyscan -T 2 -t ed25519 127.0.0.1 2> /dev/null | grep -qF "$new"; then
    echo "The fake server has new host keys."
    exit 0
  fi
  sleep 0.2
done
echo "sshd did not load the new host keys." >&2
exit 1
```
Compose paths resolve relative to the **first** file of a set (Docker's merge rule), so the two files differ:

`docker-compose.test.yml` (the first file of the `test` set is `tools/test-services/docker-compose.yml`):
```yaml
# The fake server for backend pytest (the test set in megoocolab.toml): sshd on 127.0.0.1:${SSH_PORT}.
# Paths are relative to tools/test-services, the first file of the set.
services:
  fake-server:
    build: ../fake-server
    ports:
      - "127.0.0.1:${SSH_PORT}:22"
    healthcheck:
      test: ["CMD-SHELL", "ssh-keyscan -T 2 -t ed25519 127.0.0.1 2>/dev/null | grep -q ssh-ed25519"]
      interval: 2s
      timeout: 5s
      retries: 60
```
`docker-compose.stack.yml` (the first file is the root `docker-compose.yml`):
```yaml
# The fake server of the stack set and of make up STACK=dev|e2e, on the servers network, without a published
# port. The real instance never gets it. Paths are relative to the repository root, where docker-compose.yml is.
services:
  fake-server:
    build: ./tools/fake-server
    restart: unless-stopped
    networks: [servers]
    healthcheck:
      test: ["CMD-SHELL", "ssh-keyscan -T 2 -t ed25519 127.0.0.1 2>/dev/null | grep -q ssh-ed25519"]
      interval: 5s
      timeout: 5s
      retries: 5
      start_period: 60s
```
`backend/tests/fake_server.py`:
```python
@dataclass(frozen=True)
class FakeServer:
    host: str          # "127.0.0.1"
    port: int          # int(SSH_PORT)
    container: str     # the container ID
    def exec(self, *args: str, input: str | None = None) -> subprocess.CompletedProcess[str]:
        # docker exec -i <container> *args, text=True, capture_output, timeout=60
    def host_key(self) -> str:      # first two fields of /etc/ssh/ssh_host_ed25519_key.pub (cat via exec)
    def swap_host_key(self) -> None:  # exec("swap-host-key"), assert returncode 0
    def sign_ins(self) -> int:      # count of "Accepted publickey" in `docker logs <container>` (stdout+stderr)

def start() -> FakeServer:
    # SSH_PORT and MEGOO_SERVICES_PROJECT missing -> pytest.fail(f"… is not set. Run the suite as: {RUN_TESTS}")
    # container = docker ps -q --filter label=com.docker.compose.project=<project>
    #                        --filter label=com.docker.compose.service=fake-server  (empty -> pytest.fail)
    # keys.ensure_key(); exec("authorize-key", input=keys.public_key() + "\n") must succeed
```
`tests/conftest.py`:
```python
@pytest.fixture(scope="session")
def fake_server():
    """The fake sshd of the test set, with this run's platform key authorized for its three accounts."""
    from fake_server import start
    return start()
```
`RUN_TESTS` moves to stay importable from `conftest` (it is already a module constant there; `fake_server.py` does `from conftest import RUN_TESTS`).

`tests/auth_helpers.py` gains:
```python
async def pin_host_key(client: AsyncClient, server_id) -> dict:
    """Fetches the server's key and pins it with the fingerprint fetched. Returns the server."""
    fetched = await client.post(f"/api/servers/{server_id}/host-key/fetch")
    assert fetched.status_code == 200 and fetched.json()["ok"], fetched.text
    pinned = await client.put(f"/api/servers/{server_id}/host-key", json={"fingerprint": fetched.json()["fingerprint"]})
    assert pinned.status_code == 200, pinned.text
    return pinned.json()
```

### C13. Frontend types (`src/lib/servers.ts`)

```ts
export type HostKeyState = "none" | "not_pinned" | "pinned" | "changed";
export type HostKeyOffer = { fingerprint: string; type: string; at: string };
// Server gains:
//   host_key_state: HostKeyState; host_key_fingerprint: string | null; host_key_type: string | null;
//   host_key_pinned_at: string | null; host_key_changed_at: string | null; host_key_offered: HostKeyOffer | null;
//   can_connect: boolean;
export type ConnectionReason = "unreachable" | "host_key_changed" | "key_refused" | "account_is_root"
  | "account_in_docker_group" | "account_check_failed" | "ssh_error";
export type CheckName = "host_key" | "platform_key" | "not_root" | "not_in_docker_group";
export type CheckStatus = "passed" | "failed" | "not_run";
export type ConnectionCheck = { name: CheckName; status: CheckStatus };
export type ConnectionTestResult = { ok: boolean; reason: ConnectionReason | null; checks: ConnectionCheck[] };
export type HostKeyFetchResult = { ok: boolean; reason: ConnectionReason | null; fingerprint: string | null; type: string | null };
export const CHECK_LABELS: Record<CheckName, string> = {
  host_key: "The host key matches the pinned key",
  platform_key: "The server accepts the platform's key",
  not_root: "The account is not root",
  not_in_docker_group: "The account is not in the docker group",
};
export const CHECK_STATUS_LABELS: Record<CheckStatus, string> = { passed: "Passed", failed: "Failed", not_run: "Not checked" };
/** The command that prints the key's fingerprint on the server: ed25519, ecdsa or rsa. */
export function fingerprintCommand(type: string | null): string;
// "ssh-ed25519" | null -> "ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub"; "ecdsa-…" -> …_ecdsa_key.pub; "ssh-rsa"/"rsa-…" -> …_rsa_key.pub
```

### C14. Frontend texts

`messages.ts` `MESSAGES` gains:
- `host_key_pinned`: "A host key is pinned already. The page has been reloaded."
- `stale_host_key`: "The server's key is no longer the one you compared. It has been fetched again: compare the new fingerprint."
- `host_key_not_changed`: "This server's host key has not changed. The page has been reloaded."
- `host_key_not_pinned`: "Pin the server's host key before testing the connection."
- `host_key_changed`: "The server's host key has changed. Review it before connecting."
- `not_an_ssh_server`: "Only Linux servers connect over SSH."
- `reason_required`: "Say why you accept the new key."

And:
```ts
export const CONNECTION_REASONS: Record<ConnectionReason, { title: string; advice: string }> = {
  unreachable: { title: "The server did not answer.", advice: "Check the address and the port, and that the server accepts SSH connections from MegooITAdmin." },
  host_key_changed: { title: "The server presented another host key.", advice: "The connection stopped before signing in. Review the host key on this page." },
  key_refused: { title: "The server refused the platform's key.", advice: "Add the platform's public key to the authorized_keys of the login account (see Platform access)." },
  account_is_root: { title: "The login account is root.", advice: "Use the megoo account: MegooITAdmin never signs in as root." },
  account_in_docker_group: { title: "The login account is in the docker group.", advice: "Remove it from the docker group: that group is as strong as root." },
  account_check_failed: { title: "The account could not be checked.", advice: "The id command did not answer in time. Try again." },
  ssh_error: { title: "The SSH connection failed.", advice: "The server may offer only old algorithms, such as ssh-rsa with SHA-1, which are not supported." },
};
export function reasonText(reason: ConnectionReason): { title: string; advice: string };
```

| Where | Text |
|---|---|
| State badge (title row, Linux only) | "Host key pinned" (secondary), "Host key not pinned" (outline), "Host key changed" (destructive) |
| Test button (when `can_connect`) | "Test connection", "Testing…" while running (disabled); disabled unless state `pinned` |
| Banner `not_pinned` | "The host key of {name} is not pinned yet. Nothing connects to it until it is." + manager button "Pin host key", else "Ask an Admin of {group} to pin it." |
| Banner `changed` (destructive) | title "Host key changed: connections to {name} are blocked", text "On {time} the server presented another host key than the pinned one. The server may have been reinstalled, or someone may be in the way." + when `host_key_offered` is null "The new key could not be read." + manager button "Review host key", else "An Admin of {group} must review it." |
| Host key row | not_pinned: "Not pinned yet"; else the fingerprint (mono), the type, "Pinned {time}" |
| Pin dialog | title "Pin the host key of {name}"; "Fetching the server's key…"; labels "Fingerprint", "Type"; "Compare it on the server, from a console you trust:" + `fingerprintCommand(type)` in `<code>`; checkbox "I compared the fingerprint and it matches"; buttons "Cancel", "Pin this key"; on failure the reason's title and advice + button "Try again" |
| Review dialog | title "Review the host key of {name}"; "Pinned key", "Presented key" (or "Could not be read"); input label "Why you accept the new key"; buttons "Keep the pinned key", "Accept the new key" (no Accept when the presented key is unknown) |
| Result | heading "Connection works" or the reason's title; the four checks with status labels; the advice |
| Access card | title "Platform access"; "1. On the server, create the account {username}: not root, not in the docker group." "2. Add this public key to its ~/.ssh/authorized_keys:" + key in `<code>` + button "Copy" ("Copied" after) |
| List badges | "Host key changed" (destructive), "Host key not pinned" (outline), beside the name |

## Steps

### 1. The platform key and host-key helpers (`app/ssh/keys.py`, `hostkeys.py`)

Files: `backend/pyproject.toml`, `backend/uv.lock`, `backend/app/core/config.py`, `backend/app/ssh/__init__.py`, `backend/app/ssh/keys.py`, `backend/app/ssh/hostkeys.py`, `backend/tests/conftest.py`, `backend/tests/test_settings.py`, `backend/tests/ssh/test_ssh_keys.py`, `backend/tests/ssh/test_host_keys.py`.

1. `cd backend && uv add asyncssh`.
2. Tests first:
   - `test_ssh_keys.py` (each test passes `tmp_path / "ssh" / "id_ed25519"` explicitly): `test_the_first_call_creates_a_0600_key_and_the_second_keeps_it` (True then False, same bytes, `st_mode & 0o777 == 0o600`, parent mode 0o700); `test_a_key_readable_by_others_is_refused` (chmod 0o640 → `KeyFileError` matching `readable by others`, for `ensure_key` and `load_key`); `test_a_missing_key_is_named_in_the_error` (`load_key` → `KeyFileError` containing the path); `test_the_public_line_parses_back_to_the_same_key` (`public_key()` starts `ssh-ed25519 ` and ends ` megooitadmin`; `asyncssh.import_public_key(line).public_data == load_key().public_data`); `test_key_path_follows_the_setting` (`key_path() == Path(os.environ["SSH_KEY_FILE"])`).
   - `test_host_keys.py`: build a key with `asyncssh.generate_private_key("ssh-ed25519")`, line = `openssh_line(key)`: `fingerprint(line) == key.get_fingerprint("sha256")` and starts `SHA256:`; `key_type(line) == "ssh-ed25519"`; `openssh_line` has two fields; a line with a comment gives the same fingerprint; `parse("not a key")` and `parse("ssh-ed25519 AAAA")` raise `InvalidHostKey`.
   - `test_settings.py`: `test_ssh_key_file_has_its_default` (`Settings(database_url=…, auth_secret_key=…)` with `monkeypatch.delenv("SSH_KEY_FILE")` → `/var/lib/megooitadmin/ssh/id_ed25519`).
3. Run **BT tests/ssh tests/test_settings.py** → ImportError / AttributeError.
4. Implement C1 (setting and conftest), C2, C3 exactly.
5. Run again → pass; then **BACKEND**.

Commit: `feat(ssh): the platform's SSH key and host key fingerprints`.

### 2. The fake server and its pytest fixture

Files: `tools/fake-server/{Dockerfile,sshd_config,entrypoint.sh,authorize-key,swap-host-key,docker-compose.test.yml}` (new), `.gitattributes`, `megoocolab.toml`, `backend/tests/fake_server.py` (new), `backend/tests/conftest.py`, `backend/tests/ssh/test_fake_server.py` (new).

1. Test first, `test_fake_server.py`: `test_the_fake_server_answers_with_openssh` (a TCP socket to `fake_server.host:port` reads a banner starting `SSH-2.0-OpenSSH`); `test_swap_host_key_gives_new_keys_and_sshd_keeps_answering` (`before = fake_server.host_key()`, `swap_host_key()`, the new key differs and starts `ssh-ed25519 `, and the banner still reads); `test_the_platform_key_is_authorized_for_the_three_accounts` (`exec("cat", "/home/megoo/.ssh/authorized_keys")` etc. equals `keys.public_key()` without the comment's effect: compare the first two fields; `/home/megoo-root/.ssh/authorized_keys` too); `test_the_accounts_are_what_the_checks_expect` (`exec("id", "-u", "megoo-root")` → `0`; `exec("id", "-Gn", "megoo-docker")` contains `docker`; `exec("id", "-Gn", "megoo")` does not, `id -u megoo` ≠ 0).
2. Run **BT tests/ssh/test_fake_server.py** → fixture `fake_server` not found.
3. Implement C12: the five image files, `docker-compose.test.yml`, `.gitattributes` line `tools/fake-server/* text eol=lf`, `fake_server.py`, the conftest fixture. `megoocolab.toml`:
   ```toml
   [services.test]
   description = "PostgreSQL with TimescaleDB and pgvector, and the fake sshd server, for backend pytest"
   compose = ["tools/test-services/docker-compose.yml", "tools/fake-server/docker-compose.test.yml"]
   ports = ["DB_PORT", "SSH_PORT"]
   ```
4. Run again → pass; then **BACKEND**.

Commit: `test(ssh): a fake sshd server for the tests, with three accounts and a host key swap`.

### 3. The SSH client: fetch a host key, connect with the pinned one

Files: `backend/app/ssh/client.py` (new), `backend/tests/ssh/test_ssh_client.py` (new).

1. Tests first (async, `fake_server` fixture):
   - `test_fetch_returns_the_servers_ed25519_key`: `await fetch_host_key(host, port) == fake_server.host_key()`.
   - `test_connect_with_the_pinned_key_signs_in_as_megoo`: `async with connect(host, port, "megoo", fake_server.host_key()) as conn: uid, groups = await account_of(conn)`; uid ≠ 0, `"docker" not in groups`; `sign_ins()` went up by one.
   - `test_the_two_wrong_accounts`: `megoo-root` → uid 0; `megoo-docker` → `docker` in groups.
   - `test_another_pinned_key_raises_host_key_changed_before_sign_in`: pinned = `openssh_line(asyncssh.generate_private_key("ssh-ed25519"))`; `pytest.raises(HostKeyChanged)` with `.presented == fake_server.host_key()` and `.reason == "host_key_changed"`; `sign_ins()` unchanged.
   - `test_a_key_the_server_does_not_know_raises_key_refused`: `monkeypatch.setattr("app.ssh.client.load_key", lambda: asyncssh.generate_private_key("ssh-ed25519"))` → `KeyRefused`.
   - `test_a_closed_port_raises_unreachable` (bind a socket to `127.0.0.1:0`, read its port, close it) for both `fetch_host_key` and `connect`.
   - `test_a_missing_key_file_is_not_reported_as_unreachable`: `monkeypatch.setattr("app.ssh.client.load_key", …raise KeyFileError("x"))` → `KeyFileError` propagates.
2. Run **BT tests/ssh/test_ssh_client.py** → ImportError.
3. Implement C4 exactly (the known_hosts note applies).
4. Run → pass; **BACKEND**.

Commit: `feat(ssh): connect only with the pinned host key and the platform's key`.

### 4. The backend makes its key at start (CLI, image, Compose volume)

Files: `backend/app/ssh/cli.py` (new), `backend/tests/ssh/test_ssh_cli.py` (new), `backend/Dockerfile`, `backend/docker-entrypoint.sh`, `docker-compose.yml`, `backend/tests/test_container.py`.

1. Tests first:
   - `test_ssh_cli.py` (`monkeypatch.setattr("app.ssh.keys.key_path", lambda: tmp_path / "k" / "id_ed25519")`, `capsys`): `ensure-key` twice → 0, first prints `Created the platform's SSH key in`, second `The platform's SSH key is in`; `public-key` → 0, stdout one `ssh-ed25519 ` line; a 0644 file → `ensure-key` 1, stderr `readable by others`; `public-key` without a file → 1, stderr `is missing`.
   - `test_container.py`: `_container()` helper (the existing `docker ps` filter of `test_the_log_of_a_fresh_install_holds_a_setup_code`, extracted). `test_the_backend_made_its_ssh_key_with_mode_0600` (`docker exec <id> stat -c %a /var/lib/megooitadmin/ssh/id_ed25519` → `600`; `stat -c %a /var/lib/megooitadmin/ssh` → `700`); `test_public_key_prints_an_ed25519_line` (`docker exec <id> python -m app.ssh.cli public-key` matches `^ssh-ed25519 [A-Za-z0-9+/=]+ megooitadmin$`); `test_it_refuses_to_start_with_a_key_readable_by_others(tmp_path)` (a file with `chmod 0o644`, `_run_once({...the three env vars...}, "-v", f"{file}:/var/lib/megooitadmin/ssh/id_ed25519:ro")` → non-zero, `readable by others` in output, no `Uvicorn running`).
2. Run **BT tests/ssh/test_ssh_cli.py** → fail; **DOCKER** → the new tests fail.
3. Implement C5. Dockerfile: the user line becomes `RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh && useradd --system --uid 10001 megooitadmin && install -d -o megooitadmin -g megooitadmin -m 0700 /var/lib/megooitadmin/ssh` with a comment that a new named volume takes this owner and mode. Entrypoint, after `python -m app.core.db_roles`:
   ```sh
   # The platform's SSH key: made at the first start, kept after. A key others can read stops the start.
   echo "Checking the platform's SSH key..."
   python -m app.ssh.cli ensure-key
   ```
   `docker-compose.yml`, backend: `volumes: ["ssh_key:/var/lib/megooitadmin/ssh"]` with the comment `# The platform's SSH private key. Back it up: a lost key means a new one on every server.`; top-level `ssh_key: {}` beside `db_data`.
4. Run both again → pass; **BACKEND**.

Commit: `feat(ssh): the backend makes the platform's SSH key at its first start`.

### 5. Database: host key columns (migration 0007)

Files: `backend/app/inventory/models.py`, `backend/migrations/versions/0007_host_key_pinning.py` (new), `backend/tests/test_migrations.py`.

1. Tests first in `test_migrations.py`:
   - `test_0007_goes_down_and_up_again`: `command.downgrade(_config(), "0006")`; `SELECT column_name FROM information_schema.columns WHERE table_name = 'servers' AND column_name LIKE 'host_key_%'` → empty; `finally: upgrade_to_head()`; then the four names.
   - `test_the_database_refuses_a_pin_without_its_time_and_a_block_without_a_pin`: group `'Migration probe group 0007'`, server `probe-0007` (as `_insert_probe_server` does, with its own group name); `UPDATE servers SET host_key = 'ssh-ed25519 AAAA' WHERE name = 'probe-0007'` → `IntegrityError` matching `servers_host_key_pinned_check`; `UPDATE … SET host_key_changed_at = now()` → `servers_host_key_changed_check`; clean up in `finally`.
2. Run **BT tests/test_migrations.py** → fail.
3. Implement C6. Run **MIGRATE**. `test_the_models_match_the_migrations` must pass.
4. **BACKEND** → pass.

Commit: `feat(inventory): servers hold a pinned host key, a candidate and a changed flag`.

### 6. Servers show their host key state; root is refused; edits keep the pin

Files: `backend/app/inventory/actions.py`, `server_schemas.py`, `servers.py`, `backend/tests/inventory/test_server_schemas.py`, `test_server_register.py`, `test_server_edit.py`, `test_server_remove.py`.

1. Tests first:
   - Schemas: `ConnectionSettings(username="root")` and `" root "` raise `ValidationError`; `"rooty"` passes.
   - Register: the full-response test also expects `host_key_state: "not_pinned"`, `host_key_fingerprint/type/pinned_at/changed_at/offered: None`, `can_connect: true`. New: `test_root_as_the_login_account_answers_422` (POST and PATCH), `test_a_windows_server_has_no_host_key_state` (`"none"`, `can_connect: false`), `test_can_connect_follows_connect_ssh` (Operator with `connect_ssh=False` → false; Auditor → false).
   - Edit: `test_an_address_edit_keeps_the_pin_and_drops_an_unpinned_candidate`: `make_server`, then the owner session sets `host_key_offered`/`_at` on one server and `host_key`/`host_key_pinned_at` on another (any valid `openssh_line`); PATCH address on both: the first loses the candidate, the second keeps `host_key_fingerprint`.
   - Remove: `test_removal_records_the_pinned_fingerprint` (a pinned server's `server.deleted` change has `host_key_fingerprint.before` = its fingerprint).
2. Run **BT tests/inventory** → fail.
3. Implement C7 and C8.
4. Run → pass; **BACKEND**.

Commit: `feat(inventory): a server shows its host key state, and root cannot be its login account`.

### 7. Fetch and pin a host key, and read the platform's public key

Files: `backend/app/inventory/connection_schemas.py`, `connection.py` (new: `ConnectionRefused`, `_event`, `_who`, `fetch_host_key`, `pin_host_key`), `server_router.py` (fetch, PUT, public-key), `backend/tests/auth_helpers.py` (`pin_host_key`), `backend/tests/inventory/test_host_key_pin.py` (new), `backend/tests/security/test_permission_coverage.py`.

1. Tests first (`api`, `clock`, `fake_server`; server at `fake_server.host:port` in staging):
   - `test_fetch_stores_the_candidate_and_answers_its_fingerprint` (ok, `fingerprint(fake_server.host_key())`, type `ssh-ed25519`; one SUCCESS `server.host_key_fetched` with target, context, detail; the server stays `not_pinned`).
   - `test_a_failed_fetch_answers_200_with_its_reason` (server on a closed port → `ok: false, reason: "unreachable"`; FAILURE event).
   - `test_pin_needs_the_fetched_fingerprint`: wrong fingerprint → 409 `stale_host_key`; no fetch → 409; right one → 200 `pinned`, `host_key_pinned_at` set, one `server.host_key_pinned` with `change == {"host_key_fingerprint": {"before": None, "after": fp}}`.
   - `test_a_second_pin_or_fetch_answers_409_host_key_pinned`.
   - `test_an_operator_and_an_auditor_get_403_and_a_staging_only_admin_404` for fetch and PUT on production.
   - `test_a_windows_server_answers_409_not_an_ssh_server` (fetch, PUT).
   - `test_any_signed_in_person_reads_the_public_key` (200 `{public_key: keys.public_key()}`; signed out → 401).
   - `test_permission_coverage.py`: `ANY_SIGNED_IN["GET /api/ssh/public-key"] = "the platform's public key, which is not a secret"`.
2. Run **BT tests/inventory/test_host_key_pin.py tests/security** → fail.
3. Implement C9, the C10 parts named, the three C11 routes.
4. Run → pass; **BACKEND**.

Commit: `feat(inventory): an admin fetches a server's host key and pins it`.

### 8. Test a connection; a changed key is refused, flagged and audited

Files: `backend/app/inventory/connection.py` (`_flag_changed`, `open_connection`, `test_connection`), `server_router.py` (connection-test), `backend/tests/inventory/test_connection_test.py` (new).

1. Tests first (`fake_server`, `pin_host_key`):
   - `test_the_test_passes_as_megoo`: `{ok: true, reason: null}` and four `passed` checks in C9 order; one SUCCESS `server.connection_tested` with `username`, `checks`.
   - `test_the_two_wrong_accounts_fail` (PATCH `connection_settings.username` to `megoo-docker` / `megoo-root`): reasons `account_in_docker_group` / `account_is_root` and the C9 checks.
   - `test_409_before_a_key_is_pinned` (`host_key_not_pinned`, no event but none).
   - `test_a_swapped_key_is_refused_flagged_and_blocks_the_next_test`: after `fake_server.swap_host_key()`: 200 `{ok: false, reason: "host_key_changed"}`, checks `failed/not_run…`; `sign_ins()` unchanged; GET → `changed`, `host_key_changed_at` set, `host_key_offered.fingerprint == fingerprint(fake_server.host_key())`; one FAILURE `server.host_key_mismatch` (pinned and presented fingerprints, address, port) and one FAILURE `server.connection_tested`; the next test → 409 `host_key_changed`.
   - `test_the_mismatch_survives_the_callers_rollback`: `async with SessionLocal() as s`, load the pinned `Server`, then inside `pytest.raises(HostKeyChanged)` enter `open_connection(server, actor=Actor.system("test"), source=None)`; `s.rollback()`; then the flag and the event exist.
   - Rights: an Operator with `connect_ssh` tests (200); `connect_ssh=False` → 403; an Auditor → 403; a staging-only Admin → 404 on production. Windows → 409 `not_an_ssh_server`.
2. Run **BT tests/inventory/test_connection_test.py** → 405.
3. Implement the rest of C10 for these functions and the C11 route.
4. Run → pass; **BACKEND**.

Commit: `feat(inventory): test a connection; a changed host key blocks the server`.

### 9. Review a changed key: accept it with a reason, or keep the pinned one

Files: `backend/app/inventory/connection.py` (`pin_host_key` changed branch, `keep_host_key`), `server_router.py` (keep), `backend/tests/inventory/test_host_key_review.py` (new).

1. Tests first (pin, `swap_host_key()`, one test to flag):
   - `test_accepting_needs_a_reason` (PUT with the offered fingerprint, no reason or `"  "` → 422 `reason_required`).
   - `test_accepting_with_a_reason_unblocks_and_the_test_passes`: 200 `pinned`, fingerprint = new key; `server.host_key_replaced` change before/after and `reason`; the next test is ok.
   - `test_accepting_another_fingerprint_answers_409_stale_host_key`.
   - `test_keep_unblocks_without_changing_the_key`: 200 `pinned`, same fingerprint, offered cleared; `server.host_key_kept` detail with both fingerprints; the next test → `host_key_changed` again with a new mismatch event.
   - `test_keep_on_an_unflagged_server_answers_409_host_key_not_changed`.
   - `test_an_unread_presented_key_can_only_be_kept`: owner session sets `host_key_changed_at = now()`, offered None → state `changed`, `host_key_offered: null`; PUT → 409 `stale_host_key`; keep → 200.
   - Rights: Operator 403 and staging-only Admin 404 for PUT and keep; Windows keep → 409.
2. Run **BT tests/inventory/test_host_key_review.py** → fail.
3. Implement.
4. Run → pass; **BACKEND**.

Commit: `feat(inventory): an admin accepts a changed host key with a reason, or keeps the pinned one`.

### 10. Security suites: the task's sentence, one SSH door, the walk

Files: `backend/tests/security/test_host_key_pinning.py` (new), `backend/tests/security/test_access_events.py`.

1. `test_host_key_pinning.py`:
   - `test_the_platform_connects_and_a_swapped_host_key_is_refused_and_audited` (`api`, `clock`, `fake_server`): the Owner registers, pins, tests ok; `swap_host_key()`; the test answers `host_key_changed` with `sign_ins()` unchanged; `server.host_key_mismatch` in `actions()`; the PUT with a reason records `server.host_key_replaced` with that `reason`; `verify_chain(...).ok`.
   - `test_only_app_ssh_client_opens_ssh_connections`: walk `backend/app/**/*.py` with `ast`; collect `asyncssh.<name>` attributes and `from asyncssh import <name>` where name is in `{"connect", "connect_reverse", "create_connection", "get_server_host_key", "get_server_auth_methods", "run_client", "scp", "connect_agent", "SSHClientConnection"}`; every hit is in `app/ssh/client.py`, and that file has at least one (so the check sees something).
   - `test_the_check_finds_a_connect_in_a_sample` (the detector applied to `"import asyncssh\nasync def f(): await asyncssh.connect('x')"` and `"from asyncssh import connect"` finds both).
2. `test_access_events.py`: the test takes `fake_server`. New `async def connect_servers(walk, fake_server)` after `manage_servers`: the Owner registers `ssh-01` at `fake_server.host:port` in staging; fetch, PUT; Ada (Operator with Connect SSH) tests → ok and fetch → 403; `swap_host_key()`; the Owner tests (`host_key_changed`), keeps, tests again, PUTs the offered fingerprint with reason `"reinstalled"`, tests ok, DELETEs the server (204). `walk.secrets` gains every base64 line of `keys.load_key().export_private_key().decode()`; `Walk.call` asserts no such line in `response.text`. `expected` gains `inventory_actions.CONNECTION_ACTIONS`.
3. Run **SECURITY** → pass (the audit-coverage suite passes because every new route declares actions).

Commit: `test(security): a swapped host key is refused and audited, and only one module connects`.

### 11. Stacks: the fake server in dev, e2e and the stack set; make targets

Files: `tools/fake-server/docker-compose.stack.yml` (new), `megoocolab.toml`, `Makefile`, `backend/tests/test_makefile.py`, `backend/tests/test_stack.py`.

1. Tests first:
   - `test_makefile.py`: `TARGETS` gains `ssh-public-key` and `fake-server-swap`. A constant `STACK_FILES = "-f docker-compose.yml -f tools/fake-server/docker-compose.stack.yml"`; every expected STACK line becomes `docker compose -p megooitadmin-{stack} --env-file tools/stacks/{stack}.env {STACK_FILES} …`. New: `test_up_with_a_stack_authorizes_its_key_in_the_fake_server` (a line holding `exec -T backend python -m app.ssh.cli public-key | ` and `exec -T fake-server authorize-key`); `test_the_real_instance_never_gets_a_fake_server` (`make -n up` and `down` without STACK contain no `fake-server`); `test_ssh_public_key_prints_the_key_of_the_chosen_stack` (with and without STACK); `test_fake_server_swap_swaps_in_the_chosen_stack`; `test_fake_server_swap_without_a_stack_runs_nothing` (a fake `docker` on PATH as in the reset tests → non-zero, `needs STACK=dev or STACK=e2e` in stderr, nothing ran).
   - `test_stack.py`: `FAKE_SERVER_FILE = ROOT / "tools" / "fake-server" / "docker-compose.stack.yml"` and `_compose_with_fake_server(*args, input=None)` (both `-f`). `test_only_the_backend_mounts_the_ssh_key_volume` (backend volumes `[("volume", "ssh_key", "/var/lib/megooitadmin/ssh")]`, no other service, `ssh_key` in `_model()["volumes"]`); `test_docker_compose_yml_holds_no_fake_server` (`"fake-server" not in _declared()["services"]`); `test_the_owner_pins_and_tests_the_fake_server_and_a_swapped_key_is_refused(owner)`, placed before the sign-out test (see markdown).
2. Run (root) `uv run --project backend pytest backend/tests/test_makefile.py` → fail.
3. Implement (see markdown), then **STACK** → pass; **BACKEND**.

Commit: `feat(stacks): dev and e2e stacks get a fake server, and make prints the platform's public key`.

### 12. Frontend: server types, texts and fixtures

Files: `frontend/src/lib/servers.ts`, `src/lib/__tests__/servers.test.ts`, `src/lib/auth/messages.ts`, `src/lib/auth/__tests__/messages.test.ts`, the `Server` fixtures in `src/components/servers/__tests__/{servers-page,remove-server-dialog,server-page,server-dialog}.test.tsx`.

1. Tests first: `fingerprintCommand` for `ssh-ed25519`, `null`, `ecdsa-sha2-nistp256`, `ssh-rsa`, `rsa-sha2-512`; `CHECK_LABELS` has the four names; `messageFor` of the seven C14 refusals; `reasonText` of every reason has a title and advice.
2. Run **FE src/lib** → fail.
3. Implement C13 and C14. Add to every `Server` fixture: `host_key_state: "not_pinned", host_key_fingerprint: null, host_key_type: null, host_key_pinned_at: null, host_key_changed_at: null, host_key_offered: null, can_connect: true`.
4. **FE-GATE** → pass.

Commit: `feat(frontend): host key and connection test types and texts`.

### 13. Frontend: the connection test result

Files: `frontend/src/components/servers/connection-result.tsx` (new), `src/components/servers/__tests__/connection-result.test.tsx` (new).

Contract: `export function ConnectionResult({ result }: { result: ConnectionTestResult })`: an `Alert` (`role="status"`; default variant when ok, `destructive` otherwise) with a heading "Connection works" or `reasonText(reason).title`, a list (`<ul aria-label="Checks">`) of the four checks: `CHECK_LABELS[name]` and `CHECK_STATUS_LABELS[status]`, then the advice when failed.

1. Tests first: ok shows "Connection works" and four "Passed"; `it.each` over the seven reasons shows the title and advice; `host_key_changed` shows "Failed" once and "Not checked" three times.
2. Run **FE src/components/servers/__tests__/connection-result.test.tsx** → fail.
3. Implement. **FE-GATE**.

Commit: `feat(servers): show a connection test's checks and what to do`.

### 14. Frontend: the pin dialog

Files: `frontend/src/components/servers/host-key-dialog.tsx` (new), `.../__tests__/host-key-dialog.test.tsx` (new).

Contract: `export function HostKeyDialog({ server, open, onOpenChange, onPinned, onStale }: { server: Server; open: boolean; onOpenChange: (open: boolean) => void; onPinned: (server: Server) => void; onStale: () => void })`. Inner component keyed by an attempt counter. On open: `apiFetch<HostKeyFetchResult>(`/servers/${id}/host-key/fetch`, { method: "POST" })`. Shows the C14 texts; the checkbox (`@/components/ui/checkbox`) gates "Pin this key", which calls `apiFetch<Server>(`/servers/${id}/host-key`, { method: "PUT", body: { fingerprint } })` and then `onPinned`. Error 409 `stale_host_key` shows its message and fetches again. 403, 404, 409 `host_key_pinned`/`not_an_ssh_server` show `messageFor` and call `onStale`. A failed fetch shows `reasonText` and "Try again".

1. Tests first: fetches on open with POST; the fingerprint, type and `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` appear; "Pin this key" is disabled until the box is ticked, then sends the PUT body and calls `onPinned`; a failed fetch shows "The server did not answer." and "Try again" refetches; a 409 `stale_host_key` shows its text and fetches a second time; a 403 calls `onStale`.
2. Run the file → fail. Implement. **FE-GATE**.

Commit: `feat(servers): pin a host key after comparing its fingerprint`.

### 15. Frontend: the review dialog

Files: `frontend/src/components/servers/review-host-key-dialog.tsx` (new), `.../__tests__/review-host-key-dialog.test.tsx` (new).

Contract: `export function ReviewHostKeyDialog({ server, open, onOpenChange, onDone, onStale }: { server: Server; open: boolean; onOpenChange: (open: boolean) => void; onDone: (server: Server) => void; onStale: () => void })`. Shows "Pinned key" (`host_key_fingerprint`) and "Presented key" (`host_key_offered?.fingerprint` or "Could not be read"), an `Input` labelled "Why you accept the new key", "Keep the pinned key" (POST `/servers/{id}/host-key/keep`, `{ method: "POST" }`) and, only when `host_key_offered` is set, "Accept the new key" (disabled while the trimmed reason is empty; PUT `/servers/{id}/host-key` with `{ fingerprint: host_key_offered.fingerprint, reason }`). Errors as in step 14.

1. Tests first: both fingerprints; Accept is disabled until a reason is typed, then sends the PUT body and calls `onDone`; Keep needs no reason and sends the POST; with `host_key_offered: null` there is no Accept and "Could not be read" shows; a 404 calls `onStale`.
2. Run → fail. Implement. **FE-GATE**.

Commit: `feat(servers): review a changed host key`.

### 16. Frontend: the Platform access card

Files: `frontend/src/components/servers/platform-access-card.tsx` (new), `.../__tests__/platform-access-card.test.tsx` (new).

Contract: `export function PlatformAccessCard({ username }: { username: string })`: loads `apiFetch<{ public_key: string }>("/ssh/public-key")`; a `Card` titled "Platform access" (h3) with the two C14 steps (`{username}` filled in), the key in `<code className="font-mono break-all">`, and "Copy" → `navigator.clipboard.writeText(key)`, then "Copied". The server page decides when it shows (step 17).

1. Tests first: the key and both steps render (`megoo`); Copy writes the key (mock `navigator.clipboard` as `recovery-codes.test.tsx` does) and shows "Copied".
2. Run → fail. Implement. **FE-GATE**.

Commit: `feat(servers): show the platform's public key and how to install it`.

### 17. Frontend: the server page shows the host key state and tests the connection

Files: `frontend/src/components/servers/server-page.tsx`, `src/components/servers/__tests__/server-page.test.tsx`.

Implement in `ServerPage` (C14 texts): the state badge beside the OS badge when `host_key_state !== "none"`; "Test connection" when `can_connect` (disabled unless `pinned`, "Testing…" while running), which POSTs `/servers/{id}/connection-test` with `{ method: "POST" }`, shows `<ConnectionResult>` under the title row and reloads; an `ApiError` shows `messageFor` and reloads on 403/404/409. Banner `not_pinned` and banner `changed` (`Alert`), each with its manager button or its text. The Host key row: hidden for Windows; "Not pinned yet", or fingerprint, type and "Pinned {formatTime}". `HostKeyDialog` and `ReviewHostKeyDialog` open from the buttons; `onPinned`/`onDone` set the server and clear the result; `onStale` reloads. `PlatformAccessCard` below the two cards when `can_manage && os === "linux"`, with `connection_settings.username`.

1. Tests first: `it.each` over the four states for a manager (badge, banners, buttons); an Operator (`can_manage: false, can_connect: true`) sees the Test button and "Ask an Admin of staging to pin it." but no Pin/Review/Access card; an Auditor (`can_connect: false`) has no Test button; a Windows server shows none of these and no Host key row; Test posts and shows the result; "Pin host key" opens the dialog (fetch POST seen); the changed banner says "The new key could not be read." when offered is null.
2. Run **FE src/components/servers/__tests__/server-page.test.tsx** → fail. Implement. **FE-GATE** including `npm run build`.

Commit: `feat(servers): the server page pins, reviews and tests the host key`.

### 18. Frontend: the list flags servers by host key state

Files: `frontend/src/components/servers/servers-page.tsx`, `src/components/servers/__tests__/servers-page.test.tsx`.

In the Name cell, after the link: `Badge variant="destructive"` "Host key changed" for `changed`, `Badge variant="outline"` "Host key not pinned" for `not_pinned`, nothing for `pinned` or `none`; the cell becomes `flex flex-wrap items-center gap-2`.

1. Tests first: rows with each state show the right badge or none.
2. Run → fail. Implement. **FE-GATE**.

Commit: `feat(servers): the list flags servers with a changed or unpinned host key`.

### 19. Docs, then every check

Files: `README.md`, `AGENTS.md`.

- `README.md` `### Servers`: replace the last bullet with: prepare `megoo` on each Linux server (not root, not in `docker`; the platform never signs in as root); the public key is on each server's Platform access card and from `make ssh-public-key`; the Owner or a group Admin pins the key after comparing the fingerprint (`ssh-keygen -lf …`); Connect SSH lets a person test the connection; a changed key blocks the server until an Admin accepts it with a reason or keeps the pinned one, and both are in the audit log; back up the `ssh_key` volume (a lost key means a new one on every server); Windows servers connect from Phase 2.
- `AGENTS.md` Safety: the fake server starts with `make up STACK=dev|e2e` (register it as `fake-server`, port 22), and `make fake-server-swap STACK=dev` gives it new host keys; the test set starts its own. Security suites line: add "host-key-pinning".

Then run **BACKEND**, **DOCKER**, **STACK**, **SECURITY**, `cd frontend && npx tsc --noEmit && npx eslint src && npm test && npm run build`, `megoocolab-runner services run web -- npm run test:image`, and by hand on `make up STACK=dev`: the walkthrough of Final verification. `make down STACK=dev`.

Commit: `docs: SSH host keys, the platform key and the fake server`.

## Step 11 details

`Makefile`:
```make
.PHONY: … ssh-public-key fake-server-swap
else ifeq (…)
# The dev and e2e stacks also run the fake server (tools/fake-server), on the servers network.
COMPOSE := docker compose -p megooitadmin-$(STACK) --env-file tools/stacks/$(STACK).env -f docker-compose.yml -f tools/fake-server/docker-compose.stack.yml
…
help:
	@echo "  ssh-public-key         Print the platform's SSH public key, for the megoo account's authorized_keys"
	@echo "  fake-server-swap       Give the stack's fake server new host keys (needs STACK=dev or STACK=e2e)"

up: $(ENV_FILE)
	$(COMPOSE) up -d --build --wait --wait-timeout 300
ifneq ($(STACK),)
	$(COMPOSE) exec -T backend python -m app.ssh.cli public-key | $(COMPOSE) exec -T fake-server authorize-key
endif

ssh-public-key:
	$(COMPOSE) exec -T backend python -m app.ssh.cli public-key

# Only a dev or e2e stack has a fake server.
fake-server-swap:
	@if [ -z "$(STACK)" ]; then echo "make fake-server-swap needs STACK=dev or STACK=e2e: the real instance has no fake server." >&2; exit 1; fi
	$(COMPOSE) exec -T fake-server swap-host-key
```
Also add `ssh-public-key` to the help's "Without STACK, … act on the real instance." sentence.

`megoocolab.toml`: `[services.stack] compose = ["docker-compose.yml", "tools/fake-server/docker-compose.stack.yml"]` and its description names the fake server.

`test_stack.py`, the walk (httpx `timeout=30` on the fetch/test calls):
```python
def test_the_owner_pins_and_tests_the_fake_server_and_a_swapped_key_is_refused(owner):
    public = _compose_with_fake_server("exec", "-T", "backend", "python", "-m", "app.ssh.cli", "public-key")
    assert public.returncode == 0, public.stderr
    authorized = _compose_with_fake_server("exec", "-T", "fake-server", "authorize-key", input=public.stdout)
    assert authorized.returncode == 0, authorized.stderr
    group = owner.post("/api/server-groups", json={"name": "ssh-lab"}).json()["id"]
    server = {"name": "fake-server", "address": "fake-server", "group_id": group, "os": "linux", "port": 22}
    server_id = owner.post("/api/servers", json=server).json()["id"]
    fetched = owner.post(f"/api/servers/{server_id}/host-key/fetch", timeout=30).json()
    assert fetched["ok"], fetched
    assert owner.put(f"/api/servers/{server_id}/host-key", json={"fingerprint": fetched["fingerprint"]}).status_code == 200
    assert owner.post(f"/api/servers/{server_id}/connection-test", timeout=30).json()["ok"] is True
    assert _compose_with_fake_server("exec", "-T", "fake-server", "swap-host-key").returncode == 0
    refused = owner.post(f"/api/servers/{server_id}/connection-test", timeout=30).json()
    assert (refused["ok"], refused["reason"]) == (False, "host_key_changed")
    assert owner.get(f"/api/servers/{server_id}").json()["host_key_state"] == "changed"
```
`_compose_with_fake_server` passes `input` to `subprocess.run`.

## Final verification

```
cd backend && megoocolab-runner services run migrate -- sh -c 'uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head'
cd backend && megoocolab-runner services run test -- uv run pytest
cd backend && megoocolab-runner services run image -- uv run pytest -m docker
cd backend && megoocolab-runner services run stack -- uv run pytest -m stack
make test-security
cd frontend && npx tsc --noEmit && npx eslint src && npm test && npm run build
cd frontend && megoocolab-runner services run web -- npm run test:image
make test
```

Done when all pass, `test_the_platform_connects_and_a_swapped_host_key_is_refused_and_audited` passes, and by hand on `make up STACK=dev`: register `fake-server` (address `fake-server`, port 22), pin its key, test it, run `make fake-server-swap STACK=dev`, see the test refused and the server flagged in the list and on its page, accept the new key with a reason, and test again. Then `make down STACK=dev`.
