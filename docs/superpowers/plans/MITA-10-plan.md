# MITA-10 plan: server inventory (servers, groups and tags)

## Goal

The Owner, or an Admin of a group, registers, edits, moves and removes servers in that group from the Servers page. Everyone with a role in the group (and the Owner and Auditors) sees them, nobody else does, and every change is an audit event.

## Architecture

The backend gets `Access.manages()` and a `require_group_admin` guard in `app/access`. A new `servers` and `server_tags` pair of tables (migration `0006_servers`) sits beside `server_groups` in `app/inventory`, with its own schemas, service, request dependencies and router (`/api/servers`, `/api/server-tags`). The frontend replaces the `/servers` placeholder with a list page (filters in the address), a Register/Edit dialog, a remove dialog and a `/servers/[serverId]` page with an Overview tab. Settings → Server groups gains a Servers column and refuses to delete a group that holds servers.

**Request body read twice (the design's open point).** FastAPI merges every body parameter of the dependency tree; a guard dependency and the handler that both declared `body: ServerIn` would turn the body into `{"body": {...}}`. So the body is read once by a plain dependency (`server_in` / `server_patch`) and both the group dependency and the handler take it with `Annotated[ServerIn, Depends(server_in)]`. The dependency cache runs it once and the body keeps its flat shape. Step 4 has a test that a flat body is accepted.

## File map

### Backend (`backend/`)

| File | Change |
|---|---|
| `app/access/permissions.py` | `Access.manages(group_id)` |
| `app/access/deps.py` | `require_group_admin(*, group=group_from_path)`, `access_requirement = "admin"` |
| `app/core/db.py` | `flush_refusing(session, refusals)`; `flush_unique` delegates to it |
| `app/inventory/models.py` | `Server`, `ServerTag` |
| `migrations/versions/0006_servers.py` (new) | Both tables, indexes, checks, grants |
| `app/inventory/server_schemas.py` (new) | `ConnectionSettings`, `ServerIn`, `ServerPatch`, `ServerOut`, the name/address/tag rules |
| `app/inventory/servers.py` (new) | List, read, create, update, delete, tags in use, events |
| `app/inventory/deps.py` (new) | `server_in`, `server_patch`, `group_of_server`, `group_of_new_server`, `target_group_of_server` |
| `app/inventory/server_router.py` (new) | Routes under `/servers` and `/server-tags` |
| `app/inventory/actions.py` | Five `server.*` names and `SERVER_ACTIONS` |
| `app/inventory/schemas.py`, `service.py` | `server_count`, `can_manage`; delete refused with `group_has_servers` |
| `app/inventory/__init__.py` | Docstring: "The inventory: server groups, servers and their tags." |
| `app/main.py` | `api.include_router(server_router)` |
| `tests/conftest.py` | `clean_auth` deletes `servers` before `server_groups` |
| `tests/auth_helpers.py` | `signed_in(...)` and `make_server(...)` |
| `tests/access/test_permissions.py`, `test_access_deps.py` | `manages`, `require_group_admin` |
| `tests/inventory/test_server_schemas.py` (new) | Pure validation rules |
| `tests/inventory/test_server_register.py` (new) | POST, GET one, the task's sentence |
| `tests/inventory/test_server_list.py` (new) | GET list, filters, `/server-tags` |
| `tests/inventory/test_server_edit.py` (new) | PATCH: events, no_change, move |
| `tests/inventory/test_server_remove.py` (new) | DELETE |
| `tests/inventory/test_server_groups.py`, `test_group_delete.py` | `server_count`, `can_manage`, refusal |
| `tests/security/test_permission_coverage.py`, `test_access_events.py`, `test_db_privileges.py` | Pins, walk, grants |
| `tests/test_migrations.py`, `tests/test_stack.py` | 0006 down/up and checks; stack walk |

### Frontend (`frontend/`)

| File | Change |
|---|---|
| `src/lib/servers.ts` (new) | Types and pure helpers |
| `src/lib/access.ts` | `ServerGroup` gains `server_count`, `can_manage` |
| `src/lib/auth/messages.ts` | `server_name_taken`, `group_has_servers`, `not_found`, new `forbidden` |
| `vitest.setup.ts` | `next/navigation` mock gains `useRouter`, `useSearchParams` |
| `src/components/settings/groups-page.tsx`, `delete-group-dialog.tsx`, `group-dialog.tsx` | Servers column, refusal, text |
| `src/components/servers/tag-input.tsx` (new) | Chips + input |
| `src/components/servers/server-dialog.tsx` (new) | Register/Edit |
| `src/components/servers/remove-server-dialog.tsx` (new) | Confirmation |
| `src/components/servers/server-filters.tsx` (new) | Group select and tag chips |
| `src/components/servers/servers-page.tsx` (new) | List, empty states, menus |
| `src/components/servers/server-page.tsx` (new) | One server: Overview tab, 404 card |
| `src/app/(app)/servers/page.tsx` | Renders `ServersPage` in `<Suspense>` |
| `src/app/(app)/servers/[serverId]/page.tsx` (new) | Renders `ServerPage` |
| `image-tests/shell.test.ts` | `/servers/<id>` checks |
| `README.md` (root) | "Servers" paragraph |

## Contracts shared by the steps

### C1. Access

```python
# app/access/permissions.py, in Access
def manages(self, group_id: UUID) -> bool:
    """Whether the person changes the inventory of the group: an Owner everywhere, an Admin in their groups."""
    if self.is_owner:
        return True
    grant = self.groups.get(group_id)
    return grant is not None and grant.role == GroupRole.ADMIN

# app/access/deps.py
def require_group_admin(*, group: GroupOf = group_from_path):
    """A dependency: the person must see the request's group (else 404) and manage it (else 403)."""
    async def admin_guard(request: Request, user: CurrentUser, access: CurrentAccess,
                          group_id: Annotated[UUID, Depends(group)]) -> Access:
        if not access.sees(group_id):
            await deny(request, user, required="admin", status=404, detail=NOT_FOUND, group_id=group_id)
        if not access.manages(group_id):
            await deny(request, user, required="admin", status=403, detail=FORBIDDEN, group_id=group_id)
        return access
    admin_guard.access_requirement = "admin"
    return admin_guard
```

### C2. `flush_refusing` (app/core/db.py)

```python
async def flush_refusing(session: AsyncSession, refusals: Mapping[str, tuple[int, str]]) -> None:
    """Flushes. A violation of one of the named constraints answers its (status, detail)."""
    try:
        await session.flush()
    except IntegrityError as e:
        for constraint, (status, detail) in refusals.items():
            if f'"{constraint}"' in str(e.orig):
                raise HTTPException(status, detail) from e
        raise

async def flush_unique(session, constraint, detail):  # unchanged behaviour
    await flush_refusing(session, {constraint: (409, detail)})
```

### C3. Models and migration

```python
# app/inventory/models.py
class Server(Base):
    __tablename__ = "servers"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="servers_pkey"),
        # No cascade: a group that holds servers cannot be deleted.
        ForeignKeyConstraint(["server_group_id"], ["server_groups.id"], name="servers_server_group_id_fkey"),
        CheckConstraint("port BETWEEN 1 AND 65535", name="servers_port_check"),
        CheckConstraint("os IN ('linux', 'windows')", name="servers_os_check"),
        # Names are unique across all groups, without regard to case.
        Index("servers_name_key", text("lower(name)"), unique=True),
        Index("servers_server_group_id_idx", "server_group_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    server_group_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(Text)
    address: Mapped[str] = mapped_column(Text)
    port: Mapped[int] = mapped_column(Integer)
    os: Mapped[str] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text)
    # Pinned by MITA-11 at the first connection.
    host_key: Mapped[str | None] = mapped_column(Text)
    connection_settings: Mapped[dict] = mapped_column(JSONB, server_default=text("""'{"username": "megoo"}'::jsonb"""))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ServerTag(Base):
    __tablename__ = "server_tags"
    __table_args__ = (
        PrimaryKeyConstraint("server_id", "tag", name="server_tags_pkey"),
        ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE", name="server_tags_server_id_fkey"),
        CheckConstraint("tag = lower(tag) AND char_length(tag) BETWEEN 1 AND 32", name="server_tags_tag_check"),
        Index("server_tags_tag_idx", "tag"),
    )
    server_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    tag: Mapped[str] = mapped_column(Text)
```

`0006_servers.py`: `revision = "0006"`, `down_revision = "0005"`, docstring `"""servers and server tags"""`. `upgrade()` creates both tables with the same column types, nullability (`role`, `host_key` nullable; the rest not), defaults, constraints and names as the models, the three indexes (`op.create_index("servers_name_key", "servers", [sa.text("lower(name)")], unique=True)`, `servers_server_group_id_idx`, `server_tags_tag_idx`), then `op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON servers, server_tags TO megooitadmin_api")`. `downgrade()` drops `server_tags`, then `servers`.

### C4. Schemas (app/inventory/server_schemas.py)

```python
NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
TAG_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,31}$"
HOST_LABEL = r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?"
HOSTNAME_PATTERN = rf"^{HOST_LABEL}(\.{HOST_LABEL})*\.?$"
MAX_TAGS = 20
DEFAULT_USERNAME = "megoo"
Os = Literal["linux", "windows"]

def clean_address(value: str) -> str:
    """An IPv4 or IPv6 address in its canonical text, or a host name of at most 253 characters; lowercase."""
    value = value.strip().lower()
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    if not 1 <= len(value) <= 253 or not re.fullmatch(HOSTNAME_PATTERN, value):
        raise ValueError("not an IP address or a host name")
    return value

def clean_tags(values: list[str]) -> list[str]:
    """Trimmed, lowercased, deduplicated and sorted; each one matches TAG_PATTERN; at most MAX_TAGS."""
    tags = sorted({v.strip().lower() for v in values})
    for tag in tags:
        if not re.fullmatch(TAG_PATTERN, tag):
            raise ValueError(f"{tag!r} is not a tag")
    if len(tags) > MAX_TAGS:
        raise ValueError(f"at most {MAX_TAGS} tags")
    return tags

ServerName = Annotated[str, StringConstraints(strip_whitespace=True, pattern=NAME_PATTERN)]
Address = Annotated[str, AfterValidator(clean_address)]
Port = Annotated[int, Field(ge=1, le=65535)]
Role = Annotated[str, StringConstraints(strip_whitespace=True, max_length=64)]
Tags = Annotated[list[str], AfterValidator(clean_tags)]
Username = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64, pattern=r"^\S+$")]

class ConnectionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: Username = DEFAULT_USERNAME

class ServerIn(BaseModel):
    name: ServerName
    address: Address
    group_id: UUID
    os: Os
    port: Port
    role: Role | None = None          # empty is stored as None (_none_if_empty)
    tags: Tags = []
    connection_settings: ConnectionSettings = ConnectionSettings()

class ServerPatch(BaseModel):
    """Only the fields sent change (model_fields_set). Only role may be sent as null."""
    name: ServerName | None = None
    address: Address | None = None
    group_id: UUID | None = None
    os: Os | None = None
    port: Port | None = None
    role: Role | None = None
    tags: Tags | None = None
    connection_settings: ConnectionSettings | None = None
    # field_validator over name, address, group_id, os, port, tags, connection_settings: None -> ValueError("may not be null")
    # field_validator("role"): "" -> None

class ServerOut(BaseModel):
    id: UUID; name: str; address: str; port: int; os: Os; role: str | None
    tags: list[str]; group_id: UUID; group_name: str
    connection_settings: ConnectionSettings; host_key: str | None
    created_at: datetime; updated_at: datetime
    can_manage: bool
```

### C5. Request dependencies (app/inventory/deps.py)

```python
async def server_in(body: ServerIn) -> ServerIn:
    """The body of POST /api/servers, read once for the guard and the handler."""
    return body

async def server_patch(body: ServerPatch) -> ServerPatch:
    return body

async def group_of_server(server_id: UUID, db: DbSession) -> UUID:
    """The group of the path's server. A server that does not exist answers 404."""
    group_id = await db.scalar(select(Server.server_group_id).where(Server.id == server_id))
    if group_id is None:
        raise HTTPException(404, NOT_FOUND)
    return group_id

async def group_of_new_server(body: Annotated[ServerIn, Depends(server_in)]) -> UUID:
    return body.group_id

async def target_group_of_server(body: Annotated[ServerPatch, Depends(server_patch)],
                                 group_id: Annotated[UUID, Depends(group_of_server)]) -> UUID:
    """The group the server ends up in: the body's group on a move, else its own."""
    return body.group_id if body.group_id is not None else group_id
```

### C6. Actions (app/inventory/actions.py)

```python
SERVER_CREATED = "server.created"
SERVER_CHANGED = "server.changed"
SERVER_MOVED = "server.moved"
SERVER_TAGS_CHANGED = "server.tags_changed"
SERVER_DELETED = "server.deleted"
SERVER_ACTIONS = frozenset({SERVER_CREATED, SERVER_CHANGED, SERVER_MOVED, SERVER_TAGS_CHANGED, SERVER_DELETED})
```
`ALL_ACTIONS` stays the group actions; the access-events walk expects `ALL_ACTIONS | SERVER_ACTIONS` from Step 9.

### C7. Service (app/inventory/servers.py)

```python
FIELDS = ("name", "address", "port", "os", "role", "connection_settings")

def _fields(server: Server) -> dict:            # the FIELDS of a server, as events compare them
def _target(server: Server) -> Target:           # Target(type="server", id=str(server.id), name=server.name)
def _event(request, user, action, server, *, change, detail=None) -> Event:
    # auth_event(request, action, actor_of(user), mfa=True, target=_target(server), change=change,
    #            detail=detail, context={"server_group_id": str(server.server_group_id)})
async def _tags_of(db, server_ids) -> dict[UUID, list[str]]   # one query, each list sorted
def _out(server, group_name, tags, access) -> ServerOut         # can_manage = access.manages(server.server_group_id)
async def _check_name(db, name, server_id=None) -> None         # lower(name) clash -> 409 "server_name_taken"
async def _group(db, group_id) -> ServerGroup                    # missing -> 422 "unknown_group"
REFUSALS = {"servers_name_key": (409, "server_name_taken"), "servers_server_group_id_fkey": (422, "unknown_group")}

async def list_servers(db, access, group_id: UUID | None, tags: list[str]) -> list[ServerOut]
async def get_server(db, access, server_id) -> ServerOut
async def create_server(db, request, user, access, body: ServerIn) -> ServerOut
async def update_server(db, request, user, access, server_id, body: ServerPatch) -> ServerOut
async def delete_server(db, request, user, server_id) -> None
async def list_tags(db, access) -> list[str]
```

Event contents:

| Action | `change` | `result_detail` |
|---|---|---|
| `server.created` | `changes({}, _fields(s) \| {"group": group.name, "tags": tags})` | none |
| `server.changed` | `changes(before_fields, after_fields)` | none |
| `server.moved` | `{"group": {"before": old.name, "after": new.name}}` | `{"from_group_id": str(old.id), "to_group_id": str(new.id)}` |
| `server.tags_changed` | `{"tags": {"before": old_tags, "after": new_tags}}` | none |
| `server.deleted` | `changes(_fields(s) \| {"group": ..., "tags": ...}, {})` | none |

`changes()` leaves out a field that is `None` on both sides (a missing `role`), as the group events do. The context always holds the server's group after the change. One save records `changed`, `moved`, `tags_changed` in that order, each only when it differs; none differ → 409 `no_change`. `record()` is called last, after the flush (it holds the audit chain lock until the commit).

### C8. Routes (app/inventory/server_router.py)

```python
router = APIRouter()

@router.get("/servers")
async def list_servers(db: DbSession, access: CurrentAccess, group_id: UUID | None = None,
                       tag: Annotated[list[str] | None, Query()] = None) -> list[ServerOut]

@router.get("/servers/{server_id}", dependencies=[Depends(require_group_visible(group=group_of_server))])
async def read_server(server_id: UUID, db: DbSession, access: CurrentAccess) -> ServerOut

@router.post("/servers", dependencies=[Depends(require_group_admin(group=group_of_new_server)),
                                       audited(actions.SERVER_CREATED)])
async def create_server(body: Annotated[ServerIn, Depends(server_in)], request: Request, db: DbSession,
                        user: CurrentUser, access: CurrentAccess) -> ServerOut

@router.patch("/servers/{server_id}", dependencies=[
    Depends(require_group_admin(group=group_of_server)),
    Depends(require_group_admin(group=target_group_of_server)),
    audited(actions.SERVER_CHANGED, actions.SERVER_MOVED, actions.SERVER_TAGS_CHANGED)])
async def update_server(server_id: UUID, body: Annotated[ServerPatch, Depends(server_patch)], ...) -> ServerOut

@router.delete("/servers/{server_id}", status_code=204, dependencies=[
    Depends(require_group_admin(group=group_of_server)), audited(actions.SERVER_DELETED)])
async def delete_server(server_id: UUID, ...) -> Response

@router.get("/server-tags")
async def list_tags(db: DbSession, access: CurrentAccess) -> list[str]
```
`app/main.py`: `from app.inventory.server_router import router as server_router` and `api.include_router(server_router)` after `inventory_router`.

### C9. Test helpers (tests/auth_helpers.py)

```python
@asynccontextmanager
async def signed_in(api, clock, email: str, platform_role: str | None = None):
    """A signed-in browser of a new account named after the email, and the account."""
    user, secret = await make_user(email=email, name=email.split("@")[0], platform_role=platform_role)
    async with other_client(api) as client:
        await sign_in(client, clock, secret, email=email)
        yield user, client

async def make_server(group_id, name: str, *, address="10.0.0.1", os="linux", port=22,
                      role=None, tags=()) -> Server:
    """Inserts a server and its tags through the API role, without events."""
```

### C10. Frontend `src/lib/servers.ts`

```ts
export type ServerOs = "linux" | "windows";
export const OS_LABELS: Record<ServerOs, string> = { linux: "Linux", windows: "Windows" };
export const DEFAULT_PORT: Record<ServerOs, number> = { linux: 22, windows: 3389 };
export const DEFAULT_USERNAME = "megoo";
export const MAX_TAGS = 20;
export type ConnectionSettings = { username: string };
export type Server = {
  id: string; name: string; address: string; port: number; os: ServerOs; role: string | null;
  tags: string[]; group_id: string; group_name: string; connection_settings: ConnectionSettings;
  host_key: string | null; created_at: string; updated_at: string; can_manage: boolean;
};
/** What the dialog edits; port is a number, role "" when none. */
export type ServerDraft = { name: string; address: string; group_id: string; os: ServerOs; port: number;
  role: string; tags: string[]; username: string };
/** The body of POST /api/servers. */
export type ServerBody = { name: string; address: string; group_id: string; os: ServerOs; port: number;
  role: string | null; tags: string[]; connection_settings: ConnectionSettings };
export type ServerFilters = { group: string | null; tags: string[] };

export function cleanTag(raw: string): string | null;     // trim + lowercase; null unless /^[a-z0-9][a-z0-9._-]{0,31}$/
export function addTag(tags: string[], raw: string): string[]; // the same array when invalid, duplicate or MAX_TAGS reached
export function draftOf(server: Server | null, groupId: string): ServerDraft; // new: os linux, port 22, username megoo
export function bodyOf(draft: ServerDraft): ServerBody;   // trims; role "" -> null; tags sorted
export function changesOf(server: Server, draft: ServerDraft): Partial<ServerBody>; // only differing keys; tags compared sorted; address compared lowercase
export function filtersFrom(params: URLSearchParams): ServerFilters; // "group", every "tag" cleaned + deduplicated
export function addressOf(filters: ServerFilters): string;  // "/servers", or "/servers?group=…&tag=…&tag=…"
export function listPath(filters: ServerFilters): string;   // API: "/servers", or "/servers?group_id=…&tag=…"
```

`src/lib/access.ts`: `ServerGroup = { id; name; description; created_at; member_count: number | null; server_count: number; can_manage: boolean }`.

### C11. Frontend texts

`messages.ts`: `forbidden: "You do not have the rights to do this."`, `server_name_taken: "A server with this name exists already."`, `group_has_servers: "This group still holds servers. Move or remove them first."`, `not_found: "It does not exist, or you cannot see it."`.

| Where | Text |
|---|---|
| Servers card | heading "Servers", button "Register server" |
| No group seen | "You do not see any server group yet. Ask the Owner of this installation for a role." |
| No servers, can manage | "No servers yet." + "Register the first one with Register server." |
| No servers, cannot manage | "No servers yet." + "Nobody has registered a server in your groups yet." |
| Filters match nothing | "No server matches these filters." + button "Clear filters" |
| Filters | select label "Group", option "All groups"; tag toggles labelled by the tag |
| Row menu | trigger "Actions for {name}", items "Edit", "Remove" |
| Dialog titles | "Register a server" / "Edit {name}"; submit "Register server" / "Save" |
| Dialog fields | "Name", "Address", "Server group", "Operating system" (Linux, Windows), "Port", "Login account", "Role", "Tags" |
| Move notice | "Moving {name} to {new} changes who sees it: the people of {old} lose it and those of {new} get it." |
| Tag input | placeholder "Type a tag, then Enter"; chip remove "Remove tag {tag}" |
| Remove dialog | "Remove {name}?", "It leaves the inventory for good. The audit log keeps its history.", "Cancel", "Remove server" |
| Server page | tab "Overview"; cards "Connection" (Address, Port, Login account, Host key = "Not pinned yet") and "Details" (Server group, Operating system, Role = "None", Tags = "None", Registered, Last changed); buttons "Edit", "Remove" |
| Server page 404 | "This server does not exist, or you cannot see it." + link "Back to servers" |
| Group delete refusal | title "{name} still holds servers", "Move or remove its {n} server(s) first. A group that holds servers cannot be deleted.", link "Show its servers" → `/servers?group={id}`, button "Close" |
| Group dialog | description "People get roles per server group, and its servers live in it." |

## Steps

### 1. Access: Admins manage their groups (`Access.manages`, `require_group_admin`)

Files: `backend/app/access/permissions.py`, `backend/app/access/deps.py`, `backend/tests/access/test_permissions.py`, `backend/tests/access/test_access_deps.py`, `backend/tests/security/test_permission_coverage.py`.

Tests first:
- `test_permissions.py`: `test_manages_is_true_for_an_owner_everywhere_and_for_an_admin_in_their_group_only`, `test_an_operator_and_an_auditor_manage_nothing` (use the file's `access(...)` helper, `GroupGrant(GroupRole.OPERATOR, USUAL[GroupRole.OPERATOR])`).
- `test_access_deps.py`: add to `probe_api` a route `@app.get("/api/probe/{group_id}/admin", dependencies=[Depends(require_group_admin())])`. Tests: `test_require_group_admin_lets_the_owner_and_the_groups_admin_through` (200 each), `test_require_group_admin_answers_403_to_an_operator_and_an_auditor` (detail `forbidden`), `test_require_group_admin_answers_404_for_a_group_the_person_does_not_see` (production and a random uuid), `test_each_admin_refusal_leaves_one_access_denied_event` (`result_detail == {"required": "admin", "route": "GET /api/probe/{group_id}/admin"}`, target `server_group`). Mind route order: the `/admin` probe must be declared before nothing clashes (`/api/probe/{group_id}/visible` uses a different suffix, so it is fine).
- `test_permission_coverage.py`: in `sample_app` add `@app.get("/a/{group_id}", dependencies=[Depends(require_group_admin())])` and expect `"/a/{group_id}": "admin"`.

Run (from `backend/`): `megoocolab-runner services run test -- uv run pytest tests/access tests/security/test_permission_coverage.py` → fails (`AttributeError: manages`, `ImportError: require_group_admin`).

Implement C1. Update the module docstring of `deps.py` to name `require_group_admin`, and the docstring of `access_requirement` in `tests/security/routes.py` to list `'admin'`.

Run again → pass. Then the full suite `megoocolab-runner services run test -- uv run pytest`.

Commit: `feat(access): an Admin manages the inventory of their own groups`.

### 2. Database: the servers and server_tags tables

Files: `backend/app/inventory/models.py`, `backend/migrations/versions/0006_servers.py`, `backend/tests/test_migrations.py`, `backend/tests/security/test_db_privileges.py`, `backend/tests/conftest.py`, `backend/app/inventory/__init__.py`.

Tests first in `test_migrations.py`:
- `test_0006_goes_down_and_up_again`: `command.downgrade(_config(), "0005")`, assert `to_regclass('servers')` and `to_regclass('server_tags')` are `None`; `finally: upgrade_to_head()`; then assert both exist.
- `test_the_database_refuses_an_uppercase_tag_and_a_port_of_0`: insert a probe group and server (`'Migration probe group 0006'`, server `'probe-0006'`), `pytest.raises(IntegrityError, match="server_tags_tag_check")` for tag `'Web'`, `match="servers_port_check"` for an insert with port 0; clean up in `finally` (delete server, then group).
- `test_db_privileges.py`: add `"servers"` and `"server_tags"` with SELECT, INSERT, UPDATE, DELETE to `API_GRANTS`.

Run: `megoocolab-runner services run test -- uv run pytest tests/test_migrations.py tests/security/test_db_privileges.py` → fails.

Implement C3 (models and migration by hand). `conftest.clean_auth`: run `DELETE FROM servers` before `DELETE FROM server_groups` (tags cascade) and say so in its comment.

Check down/up on the scratch database: `megoocolab-runner services run migrate -- sh -c 'uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head'`. `test_the_models_match_the_migrations` must pass.

Run the full backend suite → pass. Commit: `feat(inventory): the servers and server_tags tables`.

### 3. Schemas: the rules for names, addresses, ports and tags

Files: `backend/app/inventory/server_schemas.py` (new), `backend/tests/inventory/test_server_schemas.py` (new). No database.

Tests first (plain pydantic, `pytest.raises(ValidationError)`): a valid `ServerIn` keeps its values and defaults `connection_settings.username` to `megoo` and `tags` to `[]`; names `"db-01"`, `"DB_01.eu"` pass, `""`, `"-db"`, `"db 01"`, 65 chars fail; addresses `"10.0.0.1"`, `"::1"` (→ `"::1"`), `"2001:DB8::1"` → `"2001:db8::1"`, `"Db-01.Example.com"` → lowercase pass, `"bad host"`, `"a..b"`, `"-x.com"`, 254 chars fail; ports 0 and 65536 fail, 1 and 65535 pass; os `"bsd"` fails; tags `[" Web", "web", "EU-west"]` → `["eu-west", "web"]`, `"-x"`, `"a b"`, 33 chars and 21 distinct tags fail; role `""` → `None`, 65 chars fails; username `"a b"` and `""` fail, extra key in `connection_settings` fails; `ServerPatch(name=None)` explicitly sent fails, `ServerPatch(role=None)` passes, `ServerPatch(role="")` → `None`, `model_fields_set` holds only the sent fields.

Run: `megoocolab-runner services run test -- uv run pytest tests/inventory/test_server_schemas.py` → ImportError.

Implement C4 exactly. Run → pass. Commit: `feat(inventory): the rules a server's fields follow`.

### 4. API: register a server and read one

Files: `backend/app/core/db.py`, `backend/app/inventory/actions.py`, `backend/app/inventory/deps.py` (new), `backend/app/inventory/servers.py` (new: `_fields`, `_target`, `_event`, `_tags_of`, `_out`, `_check_name`, `_group`, `create_server`, `get_server`), `backend/app/inventory/server_router.py` (new: POST and GET one), `backend/app/main.py`, `backend/tests/auth_helpers.py` (C9), `backend/tests/inventory/test_server_register.py` (new).

Tests first (`api`, `clock` fixtures, `signed_in`, `make_group`, `add_grant`, `events`):
- `test_an_admin_registers_a_server_into_their_group`: flat JSON body → 200; response has every `ServerOut` key, `group_name`, `can_manage: true`, `host_key: null`, tags lowercase sorted; one `server.created` event with target `("server", id, name)`, `context == {"server_group_id": staging}`, `change` holds name/address/port/os/connection_settings/group/tags with `before: None`, `mfa` true.
- `test_registering_is_refused_403_in_a_group_where_the_person_is_operator` and `..._404_in_a_group_they_do_not_see`, `test_an_auditor_cannot_register`, each with one `access.denied` (`required: "admin"`) and no server row.
- `test_names_clash_without_regard_to_case_and_across_groups`: `DB-01` into production after `db-01` in staging → 409 `server_name_taken`.
- `test_a_bad_field_answers_422` (parametrized: name, address, port, os, tag).
- `test_the_owner_registering_into_a_group_that_does_not_exist_gets_422_unknown_group`.
- `test_the_tasks_sentence`: the Owner registers one into staging and one into production; GET `/api/servers/{production}` → 404 for a staging-only Admin and 200 for the Owner and an Auditor; GET a random uuid → 404 `not_found`.

Run: `megoocolab-runner services run test -- uv run pytest tests/inventory/test_server_register.py` → 404/405s.

Implement C2, C5, C6, the parts of C7 named above and the two routes of C8. `create_server`: `_group` (422), `_check_name`, add `Server` (`connection_settings=body.connection_settings.model_dump()`) and its `ServerTag`s, `flush_refusing(db, REFUSALS)`, `db.refresh`, record `server.created`, return `_out`. The guard already 404s an invisible server, so `get_server` only loads and returns.

Run the file and the full suite → pass (`test_audit_coverage` passes because both POST routes declare actions). Commit: `feat(inventory): an admin registers a server into their group`.

### 5. API: list servers with filters, and the tags in use

Files: `backend/app/inventory/servers.py` (`list_servers`, `list_tags`), `backend/app/inventory/server_router.py` (two GET routes), `backend/tests/security/test_permission_coverage.py`, `backend/tests/inventory/test_server_list.py` (new).

Tests first (`make_server` for fixtures):
- `test_a_staging_only_admin_lists_only_staging_servers`, `test_an_owner_and_an_auditor_list_every_server_by_name` (case-insensitive order), `test_a_person_without_roles_lists_none`.
- `test_can_manage_follows_the_role` (Admin staging + Operator production: true for staging rows, false for production rows).
- `test_filters_by_group`, `test_filters_by_one_tag`, `test_filters_by_two_tags_needs_both`, `test_a_tag_filter_ignores_case`, `test_a_group_the_person_does_not_see_gives_an_empty_list` (200 `[]`).
- `test_server_tags_holds_only_the_tags_of_servers_the_person_sees` (sorted, distinct).
- `test_permission_coverage.py`: add to `ANY_SIGNED_IN` `"GET /api/servers": "the list filters itself by the person's access"` and `"GET /api/server-tags": "the tags of the servers the person sees"`.

Run: `megoocolab-runner services run test -- uv run pytest tests/inventory/test_server_list.py tests/security/test_permission_coverage.py` → fail.

Implement: one query `select(Server, ServerGroup.name).join(ServerGroup, ...)`, `where(Server.server_group_id.in_(visible))` when `access.visible_group_ids()` is not None, the `group_id` filter, one `Server.id.in_(select(ServerTag.server_id).where(ServerTag.tag == t))` per cleaned tag (`t.strip().lower()`), `order_by(func.lower(Server.name), Server.id)`, then `_tags_of` once. `list_tags`: `select(ServerTag.tag).distinct().join(Server, ...)` with the same visibility filter, `order_by(ServerTag.tag)`.

Run → pass; full suite. Commit: `feat(inventory): each person lists the servers of their groups, by group and tags`.

### 6. API: edit and move a server

Files: `backend/app/inventory/servers.py` (`update_server`), `backend/app/inventory/server_router.py` (PATCH), `backend/tests/inventory/test_server_edit.py` (new).

Tests first:
- `test_changing_fields_records_server_changed` (address and port: `change` holds just those two, before/after; `updated_at` moves on).
- `test_changing_tags_records_server_tags_changed` (sorted before/after lists).
- `test_one_save_with_fields_group_and_tags_records_three_events_in_order`.
- `test_a_save_that_changes_nothing_answers_409_no_change` (including tags sent in another order and case, and an address in uppercase).
- `test_renaming_onto_a_taken_name_answers_409` and renaming to its own name in another case is a `server.changed`.
- `test_a_move_needs_admin_on_both_groups`: Admin staging + Operator production → 403; Admin staging only, target production → 404; Admin on both → 200 with `server.moved` `{"group": {"before": "staging", "after": "production"}}`, `result_detail` with both IDs, `context` the new group; afterwards a staging-only person gets 404 on the server and a production Operator gets it.
- `test_an_operator_cannot_edit` (403), `test_editing_a_server_that_does_not_exist_answers_404`, `test_the_owner_moving_into_a_missing_group_gets_422_unknown_group`.

Run: `megoocolab-runner services run test -- uv run pytest tests/inventory/test_server_edit.py` → 405.

Implement `update_server` per C7: load `with_for_update()` (404), load its group and tags; compute after-fields from `body.model_fields_set` (`connection_settings` via `model_dump()`); target group via `_group` when `group_id` sent and different; build the three changes; all `None` → 409; `_check_name` when the name changed; apply, `server.updated_at = func.now()`, delete removed tags and add new ones; `flush_refusing(db, REFUSALS)`; `db.refresh(server)`; record the events; return `_out`. Add the PATCH route of C8.

Run → pass; full suite. Commit: `feat(inventory): an admin edits a server and moves it between their groups`.

### 7. API: remove a server

Files: `backend/app/inventory/servers.py` (`delete_server`), `backend/app/inventory/server_router.py` (DELETE), `backend/tests/inventory/test_server_remove.py` (new).

Tests first: `test_an_admin_removes_a_server_and_its_tags` (204; no `servers` or `server_tags` rows for it, by an `owner_session` query from `conftest`); `test_removal_records_every_field` (`server.deleted` change has name, address, port, os, connection_settings, group, tags with `after: None`, role too when set); `test_an_operator_gets_403_and_a_stranger_404`; `test_removing_a_missing_server_answers_404`.

Run: `megoocolab-runner services run test -- uv run pytest tests/inventory/test_server_remove.py` → 405.

Implement: load `with_for_update()`, group name, tags; build the event; `await db.delete(server)` (the tags cascade in the database); `flush`; record. Route returns `Response(status_code=204)`.

Run → pass; full suite. Commit: `feat(inventory): an admin removes a server`.

### 8. API: groups count their servers and refuse to be deleted while they hold one

Files: `backend/app/inventory/schemas.py`, `backend/app/inventory/service.py`, `backend/tests/inventory/test_server_groups.py`, `backend/tests/inventory/test_group_delete.py`.

Tests first:
- `test_server_groups.py`: `test_each_group_says_how_many_servers_it_holds` (everyone who sees it gets `server_count`), `test_can_manage_is_true_for_the_owner_and_a_groups_admin_only` (Admin staging/Operator production: true/false; Auditor: false everywhere; Owner: true). Update any existing equality assertions on the full group JSON (POST/PATCH responses) to include `server_count` and `can_manage`.
- `test_group_delete.py`: `test_a_group_that_holds_a_server_cannot_be_deleted` → 409 `group_has_servers`; the group, its role grants and the server remain; no `server_group.deleted` or `user.grant_removed` events.

Run: `megoocolab-runner services run test -- uv run pytest tests/inventory` → fail.

Implement: `ServerGroupOut` gains `server_count: int` and `can_manage: bool`. `_out(group, member_count, server_count, can_manage)`; `list_groups` adds one grouped count of `Server.server_group_id` and `access.manages(group.id)`; create answers `server_count=0, can_manage=True`; update counts. `delete_group`: after the lock, `select(func.count()).select_from(Server).where(Server.server_group_id == group.id)` > 0 → `HTTPException(409, "group_has_servers")`; replace the final `db.flush()` with `flush_refusing(db, {"servers_server_group_id_fkey": (409, "group_has_servers")})` for a server registered meanwhile.

Run → pass; full suite. Commit: `feat(inventory): a group shows its servers and cannot be deleted while it holds one`.

### 9. Security walk and stack check for servers

Files: `backend/tests/security/test_access_events.py`, `backend/tests/test_stack.py`.

Tests (these are the change):
- `test_access_events.py`: add `async def manage_servers(walk)`, called after `ada_is_denied_users`: the Owner POSTs `web-01` into staging with tags `["nginx"]`; Ada (Operator on staging at that point) PATCHes it `{"role": "web"}` → 403; the Owner PATCHes `{"address": "10.0.0.2"}`, then `{"tags": ["nginx", "eu-west"]}`, then `{"group_id": production}`, then DELETEs it (204). `expected` gains `inventory_actions.SERVER_ACTIONS`.
- `test_stack.py`: in `test_a_staging_only_admin_sees_only_staging_is_refused_settings_and_is_disabled`, before the disable: the Owner registers `stack-staging-01` into staging and `stack-production-01` into production (`os: linux, port: 22`, address `10.0.0.1`); Ada's `GET /api/servers` names only `stack-staging-01`; Ada's GET of the production server's ID → 404.

Run: `make test-security` (or `megoocolab-runner services run test -- uv run pytest tests/security`) → pass; then `megoocolab-runner services run stack -- uv run pytest -m stack` → pass. Also run the full suite.

Commit: `test(security): the access walk and the stack cover the server inventory`.

### 10. Frontend: server types, helpers, group fields and messages

Files: `frontend/src/lib/servers.ts` (new), `frontend/src/lib/__tests__/servers.test.ts` (new), `frontend/src/lib/access.ts`, `frontend/src/lib/auth/messages.ts`, `frontend/src/lib/auth/__tests__/messages.test.ts`, the `ServerGroup` fixtures in `frontend/src/components/settings/__tests__/{access-dialog,access-form,delete-group-dialog,group-dialog,groups-page,invite-dialog,users-page}.test.tsx` and the forbidden text expected in `delete-group-dialog.test.tsx`.

Tests first: `servers.test.ts` for every C10 function: `DEFAULT_PORT`; `cleanTag(" Web ")` → `"web"`, invalid → `null`; `addTag` adds, ignores duplicate/invalid/21st; `draftOf(null, "g")`; `bodyOf` trims and maps `role ""` → `null`; `changesOf` empty for an unchanged draft (tags in another order, address in other case), holds only `port` after a port change, `group_id` after a move; `filtersFrom(new URLSearchParams("group=g1&tag=Web&tag=web&tag=db"))` → `{group: "g1", tags: ["web", "db"]}`; `addressOf`/`listPath` with none, group only, tags. `messages.test.ts`: the four C11 texts.

Run (from `frontend/`): `npx vitest run src/lib` → fail.

Implement C10 and C11 messages; add `server_count`, `can_manage` to `ServerGroup` and to each test fixture (`server_count: 0, can_manage: true`). Gate: `npx tsc --noEmit`, `npx eslint <changed files>`, `npm test` → pass.

Commit: `feat(frontend): server types and the helpers of the servers pages`.

### 11. Frontend: Settings → Server groups shows servers and refuses deleting a group that holds them

Files: `frontend/src/components/settings/groups-page.tsx`, `delete-group-dialog.tsx`, `group-dialog.tsx` and their tests.

Tests first: `groups-page.test.tsx` — a "Servers" column header and each row's `server_count`. `delete-group-dialog.test.tsx` — with `server_count: 3` it shows "staging still holds servers", the C11 sentence, a link "Show its servers" with `href="/servers?group=g-staging"`, a "Close" button and no "Delete group" button, and calls no API; with `server_count: 0` it behaves as today; a 409 `group_has_servers` from DELETE shows the message. `group-dialog.test.tsx` — the new description.

Run: `npx vitest run src/components/settings` → fail.

Implement: column after People; in `DeleteConfirm` branch on `group.server_count > 0` (use `next/link`); description text. Gate: tsc, eslint, `npm test`. Commit: `feat(settings): server groups show their servers and keep a group that holds any`.

### 12. Frontend: the tag input

Files: `frontend/src/components/servers/tag-input.tsx` (new), `frontend/src/components/servers/__tests__/tag-input.test.tsx` (new).

Contract: `export function TagInput({ id, value, onChange, suggestions }: { id: string; value: string[]; onChange: (tags: string[]) => void; suggestions: string[] })`. Renders each tag as a chip with a button `aria-label="Remove tag {tag}"`, and an `<Input id={id} placeholder="Type a tag, then Enter" list={`${id}-suggestions`}>` with a `<datalist>` of `suggestions` not yet in `value`. Enter or `,` calls `onChange(addTag(value, text))` (prevent default so Enter does not submit the form) and clears the text; the input is disabled once `value.length === MAX_TAGS`.

Tests first (render with a stateful wrapper): Enter adds `"Web"` as `web`; comma adds; × removes; a duplicate is ignored; an invalid tag is ignored and stays in the input; Enter does not submit a surrounding form; suggestions exclude chosen tags.

Run: `npx vitest run src/components/servers/__tests__/tag-input.test.tsx` → fail. Implement. Gate; commit `feat(servers): a tag input with chips`.

### 13. Frontend: the Register and Edit dialog

Files: `frontend/src/components/servers/server-dialog.tsx` (new), `frontend/src/components/servers/__tests__/server-dialog.test.tsx` (new).

Contract: `export function ServerDialog({ server, groups, defaultGroupId, tags, open, onOpenChange, onSaved, onStale }: { server: Server | null; groups: ServerGroup[]; defaultGroupId: string | null; tags: string[]; open: boolean; onOpenChange: (open: boolean) => void; onSaved: (server: Server) => void; onStale: () => void })`. `groups` are the ones the person may manage. Inner form keyed by `server?.id ?? "new"` like `GroupForm`. Fields and texts per C11; group is a `Select` (`aria-label="Server group"`), OS a `RadioGroup`; field pairs (Address/Port, OS/Login account) in `grid gap-4 sm:grid-cols-2` so they stack under 768 px. The port follows `DEFAULT_PORT[os]` until the person edits it. Register POSTs `bodyOf(draft)` to `/servers`; Edit PATCHes `changesOf(server, draft)` to `/servers/{id}`, Save disabled while that is empty. Choosing another group on Edit shows the move notice. Errors show `messageFor(detail)`; for 403, 404 and `unknown_group` it also calls `onStale()`.

Tests first: register sends the exact body (defaults `port: 22`, `connection_settings: {username: "megoo"}`, `role: null`); choosing Windows sets port 3389, but after typing a port the OS no longer changes it; Edit's Save is disabled until a field changes, then sends only that field; the move notice text; 409 `server_name_taken` shows its message; a 403 calls `onStale`.

Run: `npx vitest run src/components/servers/__tests__/server-dialog.test.tsx` → fail. Implement. Gate; commit `feat(servers): register and edit a server in a dialog`.

### 14. Frontend: the remove dialog

Files: `frontend/src/components/servers/remove-server-dialog.tsx` (new), `.../__tests__/remove-server-dialog.test.tsx` (new).

Contract: `export function RemoveServerDialog({ server, open, onOpenChange, onRemoved }: { server: Server | null; open: boolean; onOpenChange: (open: boolean) => void; onRemoved: () => void })`, shaped like `DeleteGroupDialog` (keyed inner confirm). DELETE `/servers/{id}` only after "Remove server"; errors via `messageFor`.

Tests first: title and text of C11; no API call until the button; the call `("/servers/s-1", { method: "DELETE" })` and `onRemoved`; a 403 shows "You do not have the rights to do this.". Run, implement, gate. Commit: `feat(servers): remove a server after a confirmation`.

### 15. Frontend: the Servers page with its filters

Files: `frontend/vitest.setup.ts`, `frontend/src/components/servers/server-filters.tsx` (new), `frontend/src/components/servers/servers-page.tsx` (new), `.../__tests__/servers-page.test.tsx` (new), `frontend/src/app/(app)/servers/page.tsx`.

`vitest.setup.ts`: the `next/navigation` mock becomes `{ usePathname: vi.fn(() => "/"), notFound: vi.fn(), useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() })), useSearchParams: vi.fn(() => new URLSearchParams()) }`.

`ServerFilters({ groups, tags, filters, onChange })`: a `Select` labelled "Group" with "All groups" and each group; a toggle button per tag in use with `aria-pressed`. `ServersPage()`: reads `filtersFrom(useSearchParams())`; loads `/server-groups`, `/server-tags` and `listPath(filters)`; a filter change calls `router.replace(addressOf(next))`. Table columns Name (link `/servers/{id}`), Address (`address:port`, mono), Group, OS, Role, Tags, and the row menu only where `can_manage`. "Register server" only when some group has `can_manage`; it opens `ServerDialog` with those groups and `defaultGroupId = filters.group` when manageable. The three empty states of C11. Save, remove and `onStale` reload the lists. The table sits in `overflow-x-auto`. `page.tsx` keeps its metadata and renders `<Suspense><ServersPage /></Suspense>`.

Tests first: rows from the mocked API; menu "Actions for db-01" only on manageable rows; no Register button for an Operator-only or Auditor list; each empty state (and "Clear filters" calls `replace("/servers")`); choosing a tag calls `replace("/servers?tag=web")`; with `useSearchParams` mocked to `group=g-staging&tag=web` the list request is `/servers?group_id=g-staging&tag=web`; registering reloads the list.

Run: `npx vitest run src/components/servers` → fail. Implement. Gate including `npm run build`. Commit: `feat(servers): the servers list with group and tag filters`.

### 16. Frontend: the server page with its Overview tab

Files: `frontend/src/components/servers/server-page.tsx` (new), `.../__tests__/server-page.test.tsx` (new), `frontend/src/app/(app)/servers/[serverId]/page.tsx` (new), `frontend/image-tests/shell.test.ts`.

`ServerPage({ serverId }: { serverId: string })`: loads `/servers/{serverId}`; a 404 shows the C11 card with a link to `/servers`. Otherwise a title row (h2 name, badges OS and group, "Edit" and "Remove" when `can_manage`), a `role="tablist"` with one selected tab "Overview", and the Connection and Details cards of C11 (times through `formatTime` from `@/components/profile/profile-page`). Edit opens `ServerDialog` (groups from `/server-groups` with `can_manage`) and reloads on save or stale; Remove opens `RemoveServerDialog` and `router.push("/servers")` after. The route: `export const metadata = { title: navItem("/servers").title }` and `export default async function ServerRoute({ params }: { params: Promise<{ serverId: string }> }) { const { serverId } = await params; return <ServerPage serverId={serverId} />; }`.

Tests first: both cards with their values and "Not pinned yet"; no Edit/Remove when `can_manage` is false; the 404 card; Remove then pushes `/servers`. Image test: `/servers/0b7c…` (any uuid) without cookie → 307 to `/login?next=%2Fservers%2F<id>`; with the cookie → 200 and `<title>Servers · MegooITAdmin</title>`.

Run the vitest file → fail; implement; gate: tsc, eslint, `npm test`, then `megoocolab-runner services run web -- npm run test:image`. Commit: `feat(servers): a page per server with its Overview`.

### 17. Docs: the Servers paragraph in the README

File: `README.md`, a `### Servers` section after `### People and access`: the Owner, and an Admin in their own groups, register, edit, move and remove servers on the Servers page; a server lives in exactly one group, which decides who sees it; tags are free labels for filtering and never decide access; the host key is pinned at the first SSH connection (comes with SSH connect). No test. Commit: `docs: servers, groups and tags`.

## Final verification

- From `backend/`: `megoocolab-runner services run test -- uv run pytest`, `megoocolab-runner services run image -- uv run pytest -m docker`, `megoocolab-runner services run stack -- uv run pytest -m stack`.
- `make test-security`.
- From `frontend/`: `npx tsc --noEmit`, `npx eslint src`, `npm test`, `npm run build`, `megoocolab-runner services run web -- npm run test:image`.
- `make test` end to end.
- By hand on `make up STACK=dev`: create staging and production, invite a person as Admin on staging only, register a server into each group as the Owner, and see in a private window that the person lists only the staging server, can edit it, and gets the "does not exist, or you cannot see it" card for the production one.
