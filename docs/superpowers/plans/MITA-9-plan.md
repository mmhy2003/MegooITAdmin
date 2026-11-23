# MITA-9 plan: users, roles and per-group grants

## Goal

An Owner invites people with a one-time link, gives each one a role per server group with seven grant switches, and disables them; one backend dependency answers "may this person do this in this group?", every refusal is an `access.denied` event, and every user or grant change is an event with before and after.

## Architecture

The backend gains three packages: `app/access/` (the `roles` and `role_grants` tables, the pure `Access` rules and the route dependencies `require_owner`, `require_grant`, `require_group_visible`), `app/users/` (invites and the Owner's `/api/users` routes) and `app/inventory/` (a minimal `server_groups` table and `/api/server-groups`). Migration `0005_roles_and_grants` replaces `users.is_owner` with `users.platform_role`. A new security suite fails for any signed-in route that does not declare who may call it. The frontend gets Settings with Users and Server groups tabs, an `/invite` page that reuses the setup flow's enrolment steps, and the person's own access on Profile and security.

## Conventions every step follows

- Work on the branch `megoo/MITA-9-p0-08-users-roles-and-per-group-grants`. Do not create another branch, and do not push.
- Write the test first, run it and watch it fail for the reason given. Then implement it and run it again.
- Commits: `type(area): sentence`, then a body that says why, and the last line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Commit only the files of the step. Never commit `.megoocolab/` or any plan or design file. No `docs/` files.
- `backend/tests/` has no `__init__.py` (prepend import mode), so every test file basename must be unique. Shared helpers go in `backend/tests/auth_helpers.py` (`from auth_helpers import …`), shared fixtures in `backend/tests/conftest.py`.
- Time: code calls `clock.now()` through `from app.auth import clock`, never `datetime.now`.
- A route that returns normally must `record()` one of its `audited(...)` actions, or the guard answers 500. A refusal with no event **raises** `HTTPException`. A refusal with an event **returns** `refused(Refusal(...))` (`app/auth/router.py`) so the event commits. A denial by an access dependency uses `record_alone` and then raises (C5). Call `record()` last in a transaction: it holds the audit chain lock until the commit.
- Lock order, always: enabled Owners' `users` rows (by id), then the target `users` row, then its `user_invites` row. Sign-in already locks the user row.
- Events of an Owner's change: `auth_event(request, action, actor_of(owner), mfa=True, target=target_of(user), change=…, context=…, detail=…)` (C6).
- Frontend: client components start with `"use client"`, icons are `aria-hidden`, imports use `@/`. Tests sit in `__tests__/` beside the code. Component tests mock `@/lib/api` (keep the real `ApiError`) and `@/lib/auth/navigate`, and call `vi.mocked(apiFetch).mockReset()` in `beforeEach`. `vitest.setup.ts` already polyfills pointer capture and `scrollIntoView` for Radix popups. Read `frontend/node_modules/next/dist/docs/` before writing layout, `redirect` or page code (frontend/AGENTS.md).

### Commands (shorthand used in the steps)

- **BT `<paths>`**: `cd backend && megoocolab-runner services run test -- uv run pytest <paths> -q`
- **BACKEND**: `cd backend && megoocolab-runner services run test -- uv run pytest`
- **DOCKER**: `cd backend && megoocolab-runner services run image -- uv run pytest -m docker`
- **STACK**: `cd backend && megoocolab-runner services run stack -- uv run pytest -m stack`
- **MIGRATE-CHECK**: `cd backend && megoocolab-runner services run migrate -- sh -c 'uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head'`
- **FE `<files>`**: `cd frontend && npx vitest run <files>`
- **FE-GATE**: `cd frontend && npx tsc --noEmit && npx eslint <changed files> && npm test`
- **IMAGE**: `cd frontend && megoocolab-runner services run web -- npm run test:image`
- **SECURITY**: `make test-security`

## File map

### Backend

| File | Status | Responsibility |
|---|---|---|
| `backend/migrations/versions/0005_roles_and_grants.py` | new | C1 |
| `backend/app/auth/models.py` | modify | `User.platform_role`, `User.disabled_at`, nullable `password_hash`; `is_owner` goes |
| `backend/app/access/__init__.py` | new | Package docstring |
| `backend/app/access/models.py` | new | `Role`, `RoleGrant` (C2) |
| `backend/app/access/permissions.py` | new | `Permission`, `PlatformRole`, `GroupRole`, `USUAL`, `ALLOWED`, `GRANT_FIELDS`, `GroupGrant`, `Access` (C3) |
| `backend/app/access/actions.py` | new | `ACCESS_DENIED = "access.denied"` |
| `backend/app/access/deps.py` | new | `load_access`, `current_access`/`CurrentAccess`, `deny`, `require_owner`, `group_from_path`, `require_grant`, `require_group_visible` (C5) |
| `backend/app/users/__init__.py` | new | Package docstring |
| `backend/app/users/models.py` | new | `UserInvite` |
| `backend/app/users/actions.py` | new | `user.*` action names (C4) |
| `backend/app/users/invites.py` | new | Invite tokens; `check_invite`, `accept_invite` (C8) |
| `backend/app/users/schemas.py` | new | `GrantIn`, `GrantOut`, `AccessIn`, `InviteIn`, `UserRowOut`, `InviteLinkOut`, `InviteTokenIn`, `InviteAcceptIn`, `InviteInfoOut` (C7) |
| `backend/app/users/service.py` | new | `grants_of`, `list_users`, `invite`, `renew_invite`, `set_access`, `disable`, `enable`, `reset_mfa` (C9) |
| `backend/app/users/router.py` | new | `/api/users` (C10) |
| `backend/app/inventory/__init__.py` | new | Package docstring |
| `backend/app/inventory/models.py` | new | `ServerGroup` |
| `backend/app/inventory/actions.py` | new | `server_group.*` |
| `backend/app/inventory/schemas.py`, `service.py`, `router.py` | new | `/api/server-groups` (C11) |
| `backend/app/auth/actions.py` | modify | Reasons `DISABLED = "disabled"`, `NOT_ACCEPTED = "not_accepted"` |
| `backend/app/auth/service.py` | modify | `auth_event(..., change=, context=)`, setup sets `platform_role="owner"`, login refuses disabled/not accepted, `reset_second_factor`, `me` adds `grants` |
| `backend/app/auth/schemas.py` | modify | `UserOut.platform_role`, `MeOut.grants` |
| `backend/app/auth/router.py` | modify | `POST /auth/invite/check`, `POST /auth/invite/accept` |
| `backend/app/auth/cli.py` | modify | `reset_mfa` uses `reset_second_factor`; `reset_password` deletes an open invite |
| `backend/app/main.py`, `backend/app/models.py` | modify | Include `users_router`, `inventory_router`; import the new model modules |
| `backend/tests/conftest.py` | modify | `clean_auth` also deletes `server_groups` |
| `backend/tests/auth_helpers.py` | modify | `make_user(platform_role=…, password=…, disabled=…)`, `make_group`, `add_grant`, `other_client` |
| `backend/tests/access/test_permissions.py`, `test_access_deps.py` | new | C3, C5 |
| `backend/tests/users/test_users_invite.py`, `test_invite_accept.py`, `test_set_access.py`, `test_user_status.py` | new | Steps 6 to 9 |
| `backend/tests/inventory/test_server_groups.py`, `test_group_delete.py` | new | Steps 10, 11 |
| `backend/tests/security/routes.py` | modify | `access_requirement`, `undeclared_routes` |
| `backend/tests/security/test_permission_coverage.py`, `test_access_events.py` | new | Steps 4, 13 |
| `backend/tests/security/test_auth_coverage.py`, `test_audit_coverage.py`, `test_db_privileges.py` | modify | Invite routes in `PUBLIC`, check route in `EXEMPT`, the four tables |
| `backend/tests/test_migrations.py`, `test_stack.py`, `tests/auth/*` | modify | As in the steps |

### Frontend, tooling and docs

| File | Status | Responsibility |
|---|---|---|
| `frontend/src/lib/access.ts` (+ `__tests__/access.test.ts`) | new | C12 |
| `frontend/src/lib/auth/gate.ts`, `messages.ts`, `src/lib/api.ts` | modify | `platform_role`; `/invite` in the gate and in `apiFetch`'s sign-in exclusion; new texts (C13) |
| `frontend/src/components/ui/select.tsx`, `radio-group.tsx` | new | `npx shadcn@latest add select radio-group` |
| `frontend/src/components/settings/access-form.tsx` | new | The three kinds and the matrix (C14) |
| `frontend/src/components/settings/settings-tabs.tsx` | new | The tab links (client, `usePathname`) |
| `frontend/src/app/(app)/settings/layout.tsx`, `page.tsx`, `users/page.tsx`, `groups/page.tsx` | new/modify | C15 |
| `frontend/src/components/settings/users-page.tsx`, `invite-dialog.tsx`, `invite-link-dialog.tsx`, `access-dialog.tsx`, `disable-dialog.tsx` | new | Users tab |
| `frontend/src/components/settings/groups-page.tsx`, `group-dialog.tsx`, `delete-group-dialog.tsx` | new | Server groups tab |
| `frontend/src/app/(auth)/invite/page.tsx`, `frontend/src/components/auth/invite-flow.tsx` | new | Screen 8 |
| `frontend/src/components/profile/profile-page.tsx` | modify | The Account card lists the person's access |
| `frontend/image-tests/shell.test.ts` | modify | `/invite` renders signed out; `/settings` redirects |
| `tools/test-services/stub-backend.Caddyfile` | modify | `"platform_role":"owner"` |
| `README.md`, `AGENTS.md` | modify | "People and access"; the security suites line |

## Contracts

### C1. Migration `0005_roles_and_grants.py`

```python
"""roles, per-group grants, server groups and invites

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    roles = op.create_table(
        "roles",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint("scope IN ('platform', 'group')", name="roles_scope_check"),
        sa.PrimaryKeyConstraint("key", name="roles_pkey"),
    )
    op.bulk_insert(
        roles,
        [
            {"key": "owner", "name": "Owner", "scope": "platform", "position": 1},
            {"key": "admin", "name": "Admin", "scope": "group", "position": 2},
            {"key": "operator", "name": "Operator", "scope": "group", "position": 3},
            {"key": "auditor", "name": "Auditor", "scope": "platform", "position": 4},
        ],
    )

    op.add_column("users", sa.Column("platform_role", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("users_platform_role_fkey", "users", "roles", ["platform_role"], ["key"])
    op.create_check_constraint("users_platform_role_check", "users", "platform_role IN ('owner', 'auditor')")
    # An invited account has no password until its link is used.
    op.alter_column("users", "password_hash", nullable=True)
    op.execute("UPDATE users SET platform_role = 'owner' WHERE is_owner")
    op.drop_column("users", "is_owner")

    op.create_table(
        "server_groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="server_groups_pkey"),
    )
    op.create_index("server_groups_name_key", "server_groups", [sa.text("lower(name)")], unique=True)

    op.create_table(
        "role_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("server_group_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        *(
            sa.Column(name, sa.Boolean(), server_default=sa.text("false"), nullable=False)
            for name in ("connect_ssh", "connect_rdp", "view_logs", "view_processes",
                         "manage_processes", "run_playbooks", "manage_playbooks")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('admin', 'operator')", name="role_grants_role_check"),
        # PRD §14.1: an Operator never manages playbooks.
        sa.CheckConstraint("role = 'admin' OR NOT manage_playbooks", name="role_grants_manage_playbooks_check"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="role_grants_user_id_fkey", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["server_group_id"], ["server_groups.id"], name="role_grants_server_group_id_fkey", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["role"], ["roles.key"], name="role_grants_role_fkey"),
        sa.PrimaryKeyConstraint("id", name="role_grants_pkey"),
        sa.UniqueConstraint("user_id", "server_group_id", name="role_grants_user_id_server_group_id_key"),
    )
    op.create_index("role_grants_server_group_id_idx", "role_grants", ["server_group_id"])

    op.create_table(
        "user_invites",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="user_invites_user_id_fkey", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", name="user_invites_pkey"),
        sa.UniqueConstraint("token_hash", name="user_invites_token_hash_key"),
    )

    op.execute("GRANT SELECT ON roles TO megooitadmin_api")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON server_groups, role_grants, user_invites TO megooitadmin_api")


def downgrade() -> None:
    op.drop_table("user_invites")
    op.drop_table("role_grants")
    op.drop_table("server_groups")
    op.add_column("users", sa.Column("is_owner", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.execute("UPDATE users SET is_owner = (platform_role = 'owner')")
    # '!' is no Argon2 hash, so no password matches an account that never had one.
    op.execute("UPDATE users SET password_hash = '!' WHERE password_hash IS NULL")
    op.alter_column("users", "password_hash", nullable=False)
    op.drop_constraint("users_platform_role_check", "users", type_="check")
    op.drop_constraint("users_platform_role_fkey", "users", type_="foreignkey")
    op.drop_column("users", "disabled_at")
    op.drop_column("users", "platform_role")
    op.drop_table("roles")
```

If `alembic check` reports the functional index, declare it in the model exactly as `Index("server_groups_name_key", text("lower(name)"), unique=True)`; do not drop it.

### C2. Models

- `app/auth/models.py` `User`: `password_hash: Mapped[str | None]`, `platform_role: Mapped[str | None] = mapped_column(Text)`, `disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))`; `__table_args__` adds `ForeignKeyConstraint(["platform_role"], ["roles.key"], name="users_platform_role_fkey")` and `CheckConstraint("platform_role IN ('owner', 'auditor')", name="users_platform_role_check")`. Remove `is_owner` and the unused `Boolean` import if nothing else uses it.
- `app/access/models.py`: `Role(key, name, scope, position)` with `roles_pkey`, `roles_scope_check`. `RoleGrant` with the columns, constraint and index names of C1, `id` default `uuid.uuid4`, and
  ```python
  def fields(self) -> dict[str, str | bool]:
      """The role and the seven switches, as audit events compare them."""
      return {"role": self.role, **{p.value: getattr(self, p.value) for p in Permission}}
  ```
- `app/inventory/models.py`: `ServerGroup(id, name, description, created_at)`, `server_groups_pkey`, index `server_groups_name_key`.
- `app/users/models.py`: `UserInvite(user_id, token_hash, expires_at, created_at)` with the C1 names.
- `app/models.py` imports `app.access.models`, `app.inventory.models`, `app.users.models` too.

### C3. `app/access/permissions.py`

```python
class Permission(StrEnum):
    CONNECT_SSH = "connect_ssh"
    CONNECT_RDP = "connect_rdp"
    VIEW_LOGS = "view_logs"
    VIEW_PROCESSES = "view_processes"
    MANAGE_PROCESSES = "manage_processes"
    RUN_PLAYBOOKS = "run_playbooks"
    MANAGE_PLAYBOOKS = "manage_playbooks"

class PlatformRole(StrEnum):
    OWNER = "owner"
    AUDITOR = "auditor"

class GroupRole(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"

ALL_PERMISSIONS = frozenset(Permission)
# The switches a role ticks when it is chosen (decision 7).
USUAL: dict[GroupRole, frozenset[Permission]] = {
    GroupRole.ADMIN: ALL_PERMISSIONS,
    GroupRole.OPERATOR: frozenset({Permission.CONNECT_SSH, Permission.CONNECT_RDP, Permission.VIEW_LOGS,
                                   Permission.VIEW_PROCESSES, Permission.RUN_PLAYBOOKS}),
}
# The switches a role may hold: an Operator never manages playbooks (PRD §14.1).
ALLOWED = {GroupRole.ADMIN: ALL_PERMISSIONS, GroupRole.OPERATOR: ALL_PERMISSIONS - {Permission.MANAGE_PLAYBOOKS}}
GRANT_FIELDS = ("role", *(p.value for p in Permission))

@dataclass(frozen=True)
class GroupGrant:
    role: GroupRole
    permissions: frozenset[Permission]

@dataclass(frozen=True)
class Access:
    user_id: UUID
    platform_role: PlatformRole | None
    groups: Mapping[UUID, GroupGrant]   # built as types.MappingProxyType, so it is immutable

    @property
    def is_owner(self) -> bool: ...
    def sees(self, group_id: UUID) -> bool: ...          # Owner, Auditor: True; else group_id in groups
    def allows(self, permission: Permission, group_id: UUID) -> bool: ...  # Owner True; Auditor False; else switch on
    def visible_group_ids(self) -> frozenset[UUID] | None: ...  # None for Owner and Auditor
```

### C4. Action names

- `app/access/actions.py`: `ACCESS_DENIED = "access.denied"`.
- `app/users/actions.py`: `USER_INVITED = "user.invited"`, `USER_INVITE_RENEWED = "user.invite_renewed"`, `USER_INVITE_ACCEPTED = "user.invite_accepted"`, `USER_INVITE_REFUSED = "user.invite_refused"`, `USER_ROLE_CHANGED = "user.role_changed"`, `USER_GRANT_ADDED = "user.grant_added"`, `USER_GRANT_CHANGED = "user.grant_changed"`, `USER_GRANT_REMOVED = "user.grant_removed"`, `USER_DISABLED = "user.disabled"`, `USER_ENABLED = "user.enabled"`, and `ALL_ACTIONS` (frozenset of the ten). Invite-refused reasons: `UNKNOWN = "unknown"`, `EXPIRED = "expired"`, `DISABLED = "disabled"`.
- `app/inventory/actions.py`: `SERVER_GROUP_CREATED = "server_group.created"`, `SERVER_GROUP_CHANGED = "server_group.changed"`, `SERVER_GROUP_DELETED = "server_group.deleted"`, `ALL_ACTIONS`.
- `app/auth/actions.py`: reasons `DISABLED = "disabled"`, `NOT_ACCEPTED = "not_accepted"`.

### C5. `app/access/deps.py`

```python
async def load_access(db: AsyncSession, user: User) -> Access:
    """One query for the person's group roles (none for an Owner or an Auditor)."""

async def current_access(db: DbSession, user: CurrentUser) -> Access: return await load_access(db, user)
CurrentAccess = Annotated[Access, Depends(current_access)]

def route_of(request: Request) -> str:
    """'POST /api/users': the method and the route's path template, never the address with IDs filled in."""

async def deny(request: Request, user: User, *, required: str, status: int, detail: str,
               group_id: UUID | None = None) -> NoReturn:
    """Records access.denied with record_alone, so the request's rollback keeps it, then raises HTTPException.
    AuditChainBusy is not caught: a refusal without its event answers 500."""
    # Event(action=ACCESS_DENIED, actor=actor_of(user), result=Result.FAILURE,
    #       target=Target(type="server_group", id=str(group_id)) if group_id else None,
    #       result_detail={"required": required, "route": route_of(request)},
    #       source=source_of(request, auth_method="password", mfa=True))

async def require_owner(request: Request, user: CurrentUser, access: CurrentAccess) -> Access:
    # not an Owner: deny(required="owner", status=403, detail="forbidden")
require_owner.access_requirement = "owner"

async def group_from_path(group_id: UUID) -> UUID: return group_id

def require_grant(permission: Permission, *, group: Callable[..., Awaitable[UUID]] = group_from_path):
    async def grant_guard(request: Request, user: CurrentUser, access: CurrentAccess,
                          group_id: Annotated[UUID, Depends(group)]) -> Access:
        # not access.sees(group_id): deny(required=permission.value, status=404, detail="not_found", group_id=group_id)
        # not access.allows(permission, group_id): deny(required=permission.value, status=403, detail="forbidden", group_id=…)
    grant_guard.access_requirement = permission.value
    return grant_guard

def require_group_visible(*, group=group_from_path):
    # the same, with required="group" and only the 404 check; access_requirement = "group"
```

Use: `dependencies=[Depends(require_owner)]`, `dependencies=[Depends(require_grant(Permission.CONNECT_SSH))]`. `route_of` reads `request.scope["route"]`; check in `.venv/lib/python3*/site-packages/fastapi/routing.py` whether the scope's route carries the full path (with the `/api` prefix) in FastAPI 0.165, and build the full template either way. The test pins `"GET /api/probe/{group_id}"`.

### C6. Auth service changes

- `auth_event(request, action, actor, *, mfa, target=None, result=SUCCESS, detail=None, change: dict | None = None, context: dict[str, str] | None = None) -> Event` passes `change` and `context` (`context or {}`) to `Event`.
- `async def reset_second_factor(db, user: User) -> list[AuthSession]`: clears `totp_secret`, `totp_pending_secret`, `totp_confirmed_at`, `totp_last_step`, deletes the recovery codes, `return await end_sessions(db, user.id)`. Records nothing.
- `login`: after the unknown-account branch and before the lock check: `disabled_at is not None` → `await passwords.verify_dummy(body.password)`, record `SIGN_IN_FAILED` (actor and target the user, reason `DISABLED`), return the same `Refusal(401, "invalid_credentials")`; then `password_hash is None` → the same with `NOT_ACCEPTED`. Neither is counted.
- `setup` creates `User(..., platform_role="owner")`.
- `me` adds `grants=(await grants_of(db, [user.id])).get(user.id, [])` (import `grants_of` from `app.users.service` inside the function, as the schemas are).

### C7. Schemas

`app/users/schemas.py`:
```python
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Email = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=254, pattern=r"^[^@\s]+@[^@\s]+$")]

class GrantIn(BaseModel):
    group_id: UUID
    role: GroupRole
    connect_ssh: bool = False   # … and the other six, all bool = False
    # model_validator(mode="after"): a switch outside ALLOWED[role] → ValueError (422)
    def fields(self) -> dict[str, str | bool]: ...   # same keys as RoleGrant.fields()

class GrantOut(GrantIn):
    group_name: str

class AccessIn(BaseModel):
    platform_role: PlatformRole | None = None
    grants: list[GrantIn] = []
    # model_validator: a group_id twice → ValueError; platform_role set and grants not empty → ValueError

class InviteIn(AccessIn):
    name: Name
    email: Email

class UserRowOut(BaseModel):
    id: UUID; name: str; email: str
    platform_role: PlatformRole | None
    status: Literal["active", "invited", "disabled"]   # disabled_at set → disabled; no password → invited
    mfa_enrolled: bool                                 # totp_secret is not None
    invite_expires_at: datetime | None
    grants: list[GrantOut]                             # by group name

class InviteLinkOut(BaseModel):
    user_id: UUID; token: str; expires_at: datetime

class InviteTokenIn(BaseModel):
    token: str = Field(min_length=1, max_length=128)

class InviteAcceptIn(InviteTokenIn):
    password: str = Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)

class InviteInfoOut(BaseModel):
    name: str; email: str
```
`app/auth/schemas.py`: `UserOut.platform_role: PlatformRole | None` replaces `is_owner`; `MeOut.grants: list[GrantOut]`.

### C8. `app/users/invites.py`

```python
INVITE_LIFETIME = timedelta(days=7)

async def put_invite(db, user_id: UUID) -> tuple[str, datetime]:
    """Deletes the account's open invite and stores a new one. Returns the token (once) and when it expires.
    The token is sessions.new_token() (256 random bits); only sessions.hash_token(token) is stored."""

async def find_invite(db, token: str) -> UserInvite | None    # by hash, no lock, expired ones included
async def check_invite(db, token: str) -> InviteInfoOut        # 404 "invalid_invite" unless found, not expired, account enabled and without password
async def accept_invite(db, request, body: InviteAcceptIn) -> str | Refusal
```

`accept_invite`: `find_invite` → none: record `USER_INVITE_REFUSED` (actor `Actor(type=ActorType.HUMAN, name="unknown")`, FAILURE, `{"reason": "unknown"}`), return `Refusal(404, "invalid_invite")`. Else `lock_user(db, invite.user_id)`, then re-select the invite `FOR UPDATE` (gone → as unknown). Expired → reason `expired`, disabled → `disabled` (actor and target the user). Otherwise set `password_hash = await hash_password(body.password)`, `password_changed_at = clock.now()`, delete the invite, `create_session(stage="pending")`, record `USER_INVITE_ACCEPTED` (actor and target the user, `mfa=False`), return the token.

### C9. `app/users/service.py`

- `grants_of(db, user_ids) -> dict[UUID, list[GrantOut]]`: one query, `RoleGrant` joined to `ServerGroup`, ordered by `lower(ServerGroup.name)`.
- `list_users(db) -> list[UserRowOut]`: every account by `lower(name)`; grants with `grants_of`, invites in one query.
- `_check_groups(db, grants)`: any `group_id` not in `server_groups` → `HTTPException(422, "unknown_group")`.
- `_grant_event(request, owner, user, action, group: ServerGroup, before, after) -> Event`: `context={"server_group_id": str(group.id)}`, `detail={"server_group": group.name}`, `change=changes(before, after)`; an absent side is `dict.fromkeys(GRANT_FIELDS)`.
- `_lock_for_change(db, request, owner, user_id) -> User`: refuses `user_id == owner.id` with `HTTPException(409, "own_account")`; reads the target (404 `not_found`); if it is an Owner, locks every enabled Owner's row `ORDER BY id FOR UPDATE` and re-reads the actor (`populate_existing`): no longer an enabled Owner → `deny(request, owner, required="owner", status=403, detail="forbidden")`. Then locks the target (`lock_user`) and returns it.
- `_keep_an_owner(db, target, new_role, disabling)`: if the target is an enabled Owner and would stop being one, and no other enabled Owner exists → `HTTPException(409, "last_owner")`.
- `invite(db, request, owner, body) -> InviteLinkOut`: email taken → `HTTPException(409, "email_taken")`; `_check_groups`; add `User(email, name, password_hash=None, platform_role, password_changed_at=clock.now())`, its `RoleGrant`s, `put_invite`; record `USER_INVITED` (`change=changes({}, {"name", "email", "platform_role"})`) then one `USER_GRANT_ADDED` per grant.
- `renew_invite(db, request, owner, user_id) -> InviteLinkOut`: `lock_user`; has a password → 409 `already_accepted`; `put_invite`; record `USER_INVITE_RENEWED` with `detail={"expires_at": iso string}`.
- `set_access(db, request, owner, user_id, body: AccessIn) -> None`: `_lock_for_change`, `_check_groups`, `_keep_an_owner`; diff stored grants by group against `body.grants`: new → insert, `USER_GRANT_ADDED`; both and `fields()` differ → update fields and `updated_at = clock.now()`, `USER_GRANT_CHANGED`; stored only → delete, `USER_GRANT_REMOVED`; `platform_role` differs → set it, `USER_ROLE_CHANGED` with `change={"platform_role": {"before": …, "after": …}}`. No event → `HTTPException(409, "no_change")`. Flush all writes, then record: the role event first, then grant events by group name.
- `disable(...)`: `_lock_for_change`; already disabled → 409 `no_change`; `_keep_an_owner(disabling=True)`; `disabled_at = clock.now()`, delete its invite, `end_sessions`; record `USER_DISABLED` (`change={"status": {"before": <status>, "after": "disabled"}}`), then `auth.session_revoked` per ended session (actor the Owner, `Target(type="auth_session", id=…)`).
- `enable(...)`: `_lock_for_change`; not disabled → 409 `no_change`; clear `disabled_at`; record `USER_ENABLED` (`change={"status": {"before": "disabled", "after": <status>}}`).
- `reset_mfa(...)`: `_lock_for_change`; `reset_second_factor`; record `auth.mfa_reset` (actor the Owner, `detail={"sessions_ended": n}`) and `auth.session_revoked` per session.

### C10. `/api/users` (`app/users/router.py`)

`router = APIRouter(prefix="/users", dependencies=[Depends(require_owner)])`, included in `create_app` as `api.include_router(users_router)`.

| Route | Response | `audited(...)` |
|---|---|---|
| `GET ""` | `list[UserRowOut]` | — |
| `POST ""` `InviteIn` | `InviteLinkOut` | `USER_INVITED` |
| `POST /{user_id}/invite` | `InviteLinkOut` | `USER_INVITE_RENEWED` |
| `PUT /{user_id}/access` `AccessIn` | 204 | `USER_ROLE_CHANGED, USER_GRANT_ADDED, USER_GRANT_CHANGED, USER_GRANT_REMOVED` |
| `POST /{user_id}/disable` | 204 | `USER_DISABLED` |
| `POST /{user_id}/enable` | 204 | `USER_ENABLED` |
| `POST /{user_id}/mfa-reset` | 204 | `auth.MFA_RESET` |

The handler takes `user: CurrentUser` as the acting Owner. In `app/auth/router.py`: `POST /invite/check` (`InviteTokenIn` → `InviteInfoOut`, no `audited`) and `POST /invite/accept` (`InviteAcceptIn`, `response_model=StatusOut`, `audited(USER_INVITE_ACCEPTED, USER_INVITE_REFUSED)`; sets the cookie and returns `StatusOut(status="enrolment_required")`, or `refused(...)`).

### C11. `/api/server-groups` (`app/inventory/`)

- Schemas: `GroupName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]`, `Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]`. `ServerGroupIn {name: GroupName, description: Description | None = None}` (empty description is stored as None). `ServerGroupPatch {name: GroupName | None = None, description: Description | None = None}` using `model_fields_set`. `ServerGroupOut {id, name, description, created_at, member_count: int | None}`.
- `GET ""` (`access: CurrentAccess`, pinned in `ANY_SIGNED_IN`): the groups `access.visible_group_ids()` allows (None: all), by `lower(name)`; `member_count` (count of `role_grants`) only for an Owner, else None.
- `POST ""`, `PATCH /{group_id}`, `DELETE /{group_id}` with `Depends(require_owner)` and `audited(...)`. A clashing `lower(name)` (another group) → 409 `name_taken`; a missing group → 404 `not_found`; a PATCH that changes nothing → 409 `no_change`. Events: target `Target(type="server_group", id=…, name=…)`, `change=changes(before, after)` over `name` and `description`. Delete: one `user.grant_removed` per role in it (target the user, C9 shape) and `server_group.deleted`; delete returns 204.

### C12. `frontend/src/lib/access.ts`

```ts
export type PlatformRole = "owner" | "auditor";
export type GroupRole = "admin" | "operator";
export const PERMISSIONS = ["connect_ssh", "connect_rdp", "view_logs", "view_processes",
  "manage_processes", "run_playbooks", "manage_playbooks"] as const;
export type Permission = (typeof PERMISSIONS)[number];
export const PERMISSION_LABELS: Record<Permission, string> = {
  connect_ssh: "Connect SSH", connect_rdp: "Connect RDP", view_logs: "View logs", view_processes: "View processes",
  manage_processes: "Manage processes", run_playbooks: "Run playbooks", manage_playbooks: "Manage playbooks",
};
export const ROLE_LABELS: Record<GroupRole | PlatformRole, string> = { owner: "Owner", auditor: "Auditor", admin: "Admin", operator: "Operator" };
export const USUAL: Record<GroupRole, readonly Permission[]>;   // as C3
export type Switches = Record<Permission, boolean>;
export type Grant = { group_id: string; role: GroupRole } & Switches;
export type GrantOut = Grant & { group_name: string };
export type AccessValue = { platform_role: PlatformRole | null; grants: Grant[] };
export type UserRow = { id: string; name: string; email: string; platform_role: PlatformRole | null;
  status: "active" | "invited" | "disabled"; mfa_enrolled: boolean; invite_expires_at: string | null; grants: GrantOut[] };
export type ServerGroup = { id: string; name: string; description: string | null; created_at: string; member_count: number | null };
export type InviteLink = { user_id: string; token: string; expires_at: string };

export function switchesFor(role: GroupRole): Switches;            // the usual switches on, the rest off
export function withRole(grant: Grant, role: GroupRole): Grant;    // the role and switchesFor(role)
export function canHold(role: GroupRole, permission: Permission): boolean;  // false only for operator + manage_playbooks
export function sameAccess(a: AccessValue, b: AccessValue): boolean;        // grants compared by group_id, any order
export function accessOf(user: { platform_role: PlatformRole | null; grants: Grant[] }): AccessValue;  // strips group_name
export function badgesOf(user: { platform_role: PlatformRole | null; grants: GrantOut[] }): string[];
// ["Owner"] | ["Auditor"] | ["Admin · staging", "Operator · production"] | ["No access"]
export function inviteLink(origin: string, token: string): string;    // `${origin}/invite#${token}`
```

### C13. Frontend texts

`messages.ts` adds:

| detail | text |
|---|---|
| `forbidden` | Only the Owner can do this. |
| `email_taken` | An account with this email exists already. |
| `name_taken` | A server group with this name exists already. |
| `own_account` | You cannot change your own account here. |
| `last_owner` | At least one enabled Owner must remain. |
| `invalid_invite` | This invite link does not work. Ask the Owner for a new one. |
| `already_accepted` | This person has accepted their invite already. |
| `no_change` | Nothing has changed. |

### C14. `access-form.tsx`

`AccessForm({ value, groups, onChange }: { value: AccessValue; groups: ServerGroup[]; onChange: (v: AccessValue) => void })`.

- A radio group labelled "Access" with "By server group", "Auditor" and "Owner". Auditor and Owner show one line each ("Reads dashboards, reports, recordings and the audit log in every group. Holds none of the grants." / "Runs the platform: people, settings and every group.") and hide the matrix. Switching back to "By server group" restores the rows as they were before (kept in a ref while the form is open).
- The matrix: one block per group (a grid row from `md:`, stacked below). Each block has the group name, a Select labelled `Role in <group>` with "No access", "Admin" and "Operator", and seven checkboxes labelled `<permission label> in <group>`. Choosing a role calls `withRole`; "No access" removes the grant, so its checkboxes are unchecked and disabled. "Manage playbooks" is disabled for an Operator.
- Under the matrix: "Only Connect SSH and Connect RDP are checked by the app for now. The other switches are saved for the features that come later."
- No groups: "No server groups yet. Create one on the Server groups tab." with a link to `/settings/groups`.

### C15. Settings routes

- `settings/layout.tsx` (server): `const user = await requireUser()`. Not an Owner: a Card with heading "Settings are for the Owner" and "Only the Owner of this installation manages people and server groups. Your own access is on Profile and security.", with a link "Profile and security" to `/profile` (children are not rendered). Owner: `<SettingsTabs />` then `children`.
- `SettingsTabs`: a `nav` labelled "Settings" with links "Users" (`/settings/users`) and "Server groups" (`/settings/groups`); the active one has `aria-current="page"` (`usePathname`).
- `settings/page.tsx`: `redirect("/settings/users")`. `users/page.tsx`: metadata title "Users", renders `<UsersPage currentUserId={(await requireUser()).id} />`. `groups/page.tsx`: metadata title "Server groups", renders `<GroupsPage />`.

## Steps

### 1. Roles, grants, server groups and invites in the database; platform_role replaces is_owner

**Files:** C1 migration, C2 models (`app/auth/models.py`, `app/access/{__init__,models}.py` with `RoleGrant.fields()` importing `Permission` from a new `app/access/permissions.py` that holds only the C3 enums and `GRANT_FIELDS` for now, `app/inventory/{__init__,models}.py`, `app/users/{__init__,models}.py`), `app/models.py`, `app/auth/schemas.py` (`UserOut.platform_role: PlatformRole | None`), `app/auth/service.py` (setup sets `platform_role="owner"`), `tests/conftest.py` (`clean_auth` also runs `DELETE FROM server_groups`), `tests/auth_helpers.py` (`make_user(..., platform_role: str | None = "owner", password: str | None = PASSWORD, disabled: bool = False)`: `password=None` stores no hash, `disabled` sets `disabled_at=clock.now()`), `tests/auth/test_status.py`, `test_own_sessions.py`, `test_setup.py`, `tests/security/test_db_privileges.py`, `tests/test_migrations.py`.

1. Tests first:
   - `test_db_privileges.py` `API_GRANTS` adds `"roles": {"SELECT"}` and `"server_groups"`, `"role_grants"`, `"user_invites"`: `{"SELECT", "INSERT", "UPDATE", "DELETE"}`.
   - `test_migrations.py`: add `_execute(sql)` (like `_fetch`, but commits) and
     - `test_0005_goes_down_and_up_again_and_keeps_the_owner`: downgrade to `0004`, insert an Owner (`is_owner = true`) and a non-Owner, upgrade to head: the Owner has `platform_role = 'owner'`, the other NULL, `roles` holds the four keys; downgrade to `0004`: `is_owner` is back as it was; upgrade; delete both rows.
     - `test_0005_downgrade_gives_an_invited_account_an_unusable_hash`: at head insert a user with `password_hash` NULL, downgrade to `0004`: its hash is `'!'`; upgrade; delete it.
     - `test_an_operator_cannot_hold_manage_playbooks`: inserting such a `role_grants` row as the owner raises `IntegrityError` (check violation).
   - Update the expected `"is_owner": True` to `"platform_role": "owner"` in `test_status.py` and `test_own_sessions.py`, `make_user(..., is_owner=False)` to `platform_role=None`, and `test_setup.py` to `user.platform_role == "owner"`.
   Run **BT tests/test_migrations.py tests/security/test_db_privileges.py tests/auth**: it fails.
2. Implement C1 and C2, then the renames. `grep -rn is_owner backend` must find nothing outside `0004_auth.py` and the downgrade of `0005`.
3. Run **MIGRATE-CHECK**, then **BACKEND**: they pass (`test_the_models_match_the_migrations` included).

Commit: `feat(access): tables for roles, per-group grants, server groups and invites`

### 2. The access rules: who sees a group and who may use a grant in it

**Files:** `backend/app/access/permissions.py` (the rest of C3), `backend/tests/access/test_permissions.py`.

1. Tests first (no database):
   - `test_an_owner_is_allowed_everything_everywhere`
   - `test_an_auditor_sees_every_group_and_is_allowed_none_of_the_seven`
   - `test_a_staging_only_admin_sees_staging_only_and_may_connect_there_only`
   - `test_a_switch_that_is_off_is_refused_although_the_role_is_admin`
   - `test_a_person_without_roles_sees_no_group`
   - `test_visible_group_ids_is_none_for_owner_and_auditor_and_the_groups_otherwise`
   - `test_the_usual_switches_of_each_role` and `test_an_operator_may_never_hold_manage_playbooks` (`USUAL`, `ALLOWED`)
   - `test_access_is_immutable` (assigning to a field or an item of `groups` raises)
   Run **BT tests/access/test_permissions.py**: it fails.
2. Implement C3.
3. Run it again: it passes.

Commit: `feat(access): the rules that say who sees a group and may use a grant in it`

### 3. Route dependencies that refuse and record access.denied

**Files:** `backend/app/access/actions.py`, `backend/app/access/deps.py` (C5), `backend/tests/auth_helpers.py` (`make_group(name, description=None) -> ServerGroup`; `add_grant(user_id, group_id, role="admin", **switches) -> RoleGrant`; `set_switch(grant_id, name, value)`; `other_client(api)` moved here from `test_own_sessions.py` if it lives there), `backend/tests/access/test_access_deps.py`.

1. Tests first. A fixture `probe_api(clean_auth, clock)` builds `create_app()` and adds `GET /api/probe/owner` (`dependencies=[Depends(require_owner)]`), `GET /api/probe/{group_id}` (`Depends(require_grant(Permission.CONNECT_SSH))`) and `GET /api/probe/{group_id}/visible` (`Depends(require_group_visible())`), each returning `{"ok": True}`, behind `ASGITransport(app=…, client=("127.0.0.1", 50000))`. Tests:
   - `test_require_owner_lets_an_owner_through_and_answers_403_to_anyone_else` (an Admin, an Auditor and someone without roles)
   - `test_require_grant_answers_404_for_a_group_the_person_does_not_see`
   - `test_require_grant_answers_403_for_a_switch_that_is_off`
   - `test_a_staging_only_admin_may_connect_to_staging_and_not_to_production` (403 → no: production is unseen, so 404)
   - `test_an_auditor_gets_403_for_connect_and_passes_require_group_visible`
   - `test_each_refusal_leaves_one_access_denied_event`: actor the person, result `failure`, target `server_group` with the group's ID, `result_detail == {"required": "connect_ssh", "route": "GET /api/probe/{group_id}"}`, and for the Owner check `{"required": "owner", "route": "GET /api/probe/owner"}`
   - `test_a_refusal_whose_event_cannot_be_recorded_answers_500`: monkeypatch `app.access.deps.record_alone` to raise `AuditChainBusy`; a transport with `raise_app_exceptions=False` gets 500 and no event exists
   - `test_a_changed_grant_applies_to_the_next_request_of_an_open_session`: signed in as an Admin with connect on, 200; `set_switch(…, "connect_ssh", False)`; the next request gets 403 on the same client
   Run **BT tests/access**: it fails.
2. Implement C5.
3. Run **BT tests/access tests/security**: it passes.

Commit: `feat(access): route dependencies refuse by role and grant, and every refusal is audited`

### 4. Security suite: every signed-in route declares who may call it

**Files:** `backend/tests/security/routes.py`, `backend/tests/security/test_permission_coverage.py`.

1. Add to `routes.py`: `access_requirement(context) -> str | None` (the first `access_requirement` attribute among `dependency_calls(context)`) and `undeclared_routes(app, any_signed_in: Mapping[str, str]) -> list[str]`: sorted `"METHOD /path"` of every route whose `session_requirement` is `"active"`, that has no requirement and is not pinned.
2. Tests first in `test_permission_coverage.py`:
   ```python
   ANY_SIGNED_IN: dict[str, str] = {
       "GET /api/auth/me": "a person reads their own account",
       "GET /api/auth/sessions": "a person lists their own sessions",
       "DELETE /api/auth/sessions/{session_id}": "a person ends one of their own sessions",
       "POST /api/auth/password": "a person changes their own password",
       "POST /api/auth/recovery-codes": "a person replaces their own recovery codes",
   }
   ```
   - `test_every_signed_in_route_declares_who_may_call_it` (message: add `Depends(require_owner)`, `require_grant(...)` or `require_group_visible(...)`, or pin it with a reason)
   - `test_any_signed_in_names_only_real_routes`
   - `test_the_check_reports_an_undeclared_route_of_a_sample_app`: a sample app with `GET /mine` (`CurrentUser` only, reported), `GET /admin` (`Depends(require_owner)`), `GET /g/{group_id}` (`Depends(require_grant(Permission.VIEW_LOGS))`), a router included with `dependencies=[Depends(require_owner)]`, and an open `GET /open` (not reported: not active). Only `["GET /mine"]`; pinned, `[]`.
   - `test_access_requirement_names_what_the_route_needs` (`"owner"`, `"view_logs"`, `"group"`)
   Run **BT tests/security/test_permission_coverage.py**: the sample tests fail until step 1's helpers exist, then all pass with the list above.
3. Run **SECURITY**: it passes.

Commit: `test(security): every signed-in route declares who may call it`

### 5. Sign-in refuses disabled and not-yet-accepted accounts; the second-factor reset is shared

**Files:** `backend/app/auth/actions.py`, `backend/app/auth/service.py` (C6: `auth_event` arguments, `login`, `reset_second_factor`), `backend/app/auth/cli.py`, `backend/tests/auth/test_login.py`, `backend/tests/auth/test_cli.py`.

1. Tests first:
   - `test_login.py`: `test_a_disabled_account_is_refused_with_the_usual_message` (right password → 401 `invalid_credentials`, event `auth.sign_in_failed` with `{"reason": "disabled"}`, `failed_attempts` unchanged, no session); `test_an_account_that_has_not_accepted_its_invite_is_refused` (`make_user(password=None)`, reason `not_accepted`).
   - `test_cli.py`: `test_reset_password_of_an_invited_account_deletes_its_invite` (insert a `UserInvite` for a `password=None` account; after `reset_password` no invite row is left and sign-in works); `test_reset_mfa_works_on_a_disabled_account_and_does_not_enable_it`.
   Run **BT tests/auth**: it fails.
2. Implement. `cli.reset_mfa` calls `reset_second_factor(session, user)` and keeps its output and event (`sessions_ended = len(ended)`). `cli.reset_password` adds `await session.execute(delete(UserInvite).where(UserInvite.user_id == user.id))`.
3. Run **BT tests/auth tests/security**: it passes.

Commit: `feat(auth): a disabled or not-yet-accepted account cannot sign in`

### 6. The Owner lists people and invites one with a one-time link

**Files:** `backend/app/users/actions.py`, `schemas.py` (C7), `invites.py` (`INVITE_LIFETIME`, `put_invite`, `find_invite`), `service.py` (`grants_of`, `list_users`, `_check_groups`, `_grant_event`, `invite`), `router.py` (`GET ""`, `POST ""`), `backend/app/main.py`, `backend/tests/users/test_users_invite.py`.

1. Tests first (`api`, `clock`; the Owner from `make_user()` signed in with `sign_in`):
   - `test_only_an_owner_may_list_or_invite` (an Admin: 403 `forbidden` on both, one `access.denied` each)
   - `test_an_invite_creates_an_account_without_a_password_and_returns_the_token_once`: 200 with `user_id`, `token`, `expires_at` 7 days on; the account has `password_hash` NULL; `user_invites` holds `sha256(token)` and never the token
   - `test_the_list_shows_the_status_the_grants_and_when_the_invite_expires` (Owner `active` with `mfa_enrolled` true, the invitee `invited` with its grant and `invite_expires_at`, a disabled one `disabled`)
   - `test_an_invite_records_the_account_and_each_grant` (`user.invited` change holds name, email, platform_role; one `user.grant_added` per group with `context`, `result_detail` and every field's `before` None)
   - `test_a_second_invite_for_the_same_email_gets_409` (case-insensitive; `email_taken`)
   - `test_an_unknown_group_a_duplicate_group_or_an_operator_with_manage_playbooks_gets_422`
   - `test_a_platform_role_with_group_roles_gets_422`
   Run **BT tests/users**: it fails.
2. Implement; include the router in `create_app`.
3. Run **BT tests/users tests/security**: it passes (`test_permission_coverage` passes through the router dependency).

Commit: `feat(users): the Owner invites a person with a one-time link`

### 7. The invited person checks and accepts the link; the Owner can make a new one

**Files:** `backend/app/users/invites.py` (`check_invite`, `accept_invite`), `backend/app/users/service.py` (`renew_invite`), `backend/app/users/router.py` (`POST /{user_id}/invite`), `backend/app/auth/router.py` (C10 invite routes), `backend/tests/users/test_invite_accept.py`, `backend/tests/security/test_auth_coverage.py` (`PUBLIC` gains `"POST /api/auth/invite/check"` and `"POST /api/auth/invite/accept"` with reasons), `backend/tests/security/test_audit_coverage.py` (`EXEMPT = {"POST /api/auth/invite/check": "it only reads; POST keeps the token out of addresses and logs"}`).

1. Tests first:
   - `test_check_answers_the_name_and_email_of_a_valid_link`; `test_check_answers_404_for_an_unknown_expired_or_used_link`
   - `test_accept_sets_the_password_and_gives_a_pending_session_that_enrols`: 200 `enrolment_required`, cookie set, `GET /api/auth/session` → `enrolment_required`, the invite row gone, `user.invite_accepted` recorded; then `/auth/mfa/enrol` and `/confirm` give an active session
   - `test_a_link_works_once` (second accept → 404 `invalid_invite`, `user.invite_refused` reason `unknown`)
   - `test_an_expired_link_is_refused_and_recorded` (`clock.advance(days=7, seconds=1)`, reason `expired`)
   - `test_a_replaced_link_is_refused` (after `POST /api/users/{id}/invite`, the old token is unknown, the new one works; `user.invite_renewed`)
   - `test_renewing_an_accepted_invite_gets_409_already_accepted`
   - `test_a_disabled_accounts_link_is_refused` (set `disabled_at` directly; reason `disabled`)
   - `test_no_event_holds_the_token_or_the_password`
   Run **BT tests/users tests/security**: it fails.
2. Implement C8 and the routes.
3. Run **BT tests/users tests/auth tests/security**: it passes.

Commit: `feat(users): an invited person sets their password from the link and enrols`

### 8. The Owner sets a person's access, with one event per difference

**Files:** `backend/app/users/service.py` (`_lock_for_change`, `_keep_an_owner`, `set_access`), `backend/app/users/router.py` (`PUT /{user_id}/access`), `backend/tests/users/test_set_access.py`.

1. Tests first:
   - `test_adding_a_group_role_records_grant_added`
   - `test_changing_a_switch_records_grant_changed_with_before_and_after` (`change == {"view_logs": {"before": False, "after": True}}`)
   - `test_changing_the_role_in_a_group_records_grant_changed`
   - `test_removing_a_group_records_grant_removed_with_after_none`
   - `test_choosing_auditor_removes_the_group_roles_and_records_role_changed` (one `user.role_changed` and one `user.grant_removed` per group, in that order)
   - `test_a_save_that_changes_nothing_gets_409_no_change` (no event)
   - `test_an_unknown_group_a_duplicate_group_or_an_operator_with_manage_playbooks_gets_422`
   - `test_the_owner_cannot_change_their_own_access` (409 `own_account`)
   - `test_an_unknown_account_gets_404`
   - `test_two_owners_demoting_each_other_at_once_leave_one_owner`: Owners A and B on two clients, `asyncio.gather` of A→B and B→A `{"platform_role": null, "grants": []}`; status codes `{204, 403}`, exactly one enabled Owner, one `access.denied`
   - `test_the_new_access_applies_to_the_persons_next_request` (via `GET /api/users` 403 → 200 after becoming Owner)
   Run **BT tests/users/test_set_access.py**: it fails.
2. Implement C9 `set_access` and its helpers.
3. Run **BT tests/users tests/security**: it passes.

Commit: `feat(users): the Owner changes a person's role and grants, each difference audited`

### 9. The Owner disables, enables and resets a person's second factor

**Files:** `backend/app/users/service.py` (`disable`, `enable`, `reset_mfa`), `backend/app/users/router.py`, `backend/tests/users/test_user_status.py`.

1. Tests first:
   - `test_disable_ends_the_sessions_and_refuses_sign_in`: the person signed in on a second client; after `POST /api/users/{id}/disable` (204) their `GET /api/auth/me` is 401 and sign-in answers `invalid_credentials`; events `user.disabled` and `auth.session_revoked` (actor the Owner)
   - `test_disable_deletes_an_open_invite`
   - `test_disabling_twice_gets_409_no_change`; `test_enabling_an_enabled_account_gets_409_no_change`
   - `test_enable_restores_sign_in_with_the_same_roles` (`user.enabled`; grants unchanged)
   - `test_reset_forces_enrolment_at_the_next_sign_in` (`auth.mfa_reset` with the Owner as actor and `sessions_ended`, sign-in → `enrolment_required`)
   - `test_the_owner_cannot_disable_enable_or_reset_their_own_account` (409 `own_account` from all three)
   - `test_disabling_another_owner_leaves_at_least_one` (two Owners: disabling B works; B cannot act afterwards)
   Run **BT tests/users/test_user_status.py**: it fails.
2. Implement the three and their routes (C10).
3. Run **BT tests/users tests/auth tests/security**: it passes.

Commit: `feat(users): the Owner disables, enables and resets a person's second factor`

### 10. Server groups: the list each person sees, and the Owner creates and edits groups

**Files:** `backend/app/inventory/actions.py`, `schemas.py`, `service.py`, `router.py` (`GET ""`, `POST ""`, `PATCH /{group_id}`; C11), `backend/app/main.py`, `backend/tests/inventory/test_server_groups.py`, `backend/tests/security/test_permission_coverage.py` (`ANY_SIGNED_IN` gains `"GET /api/server-groups": "the list filters itself by the person's access"`).

1. Tests first:
   - `test_a_staging_only_admin_sees_staging_and_not_production` (**the task's sentence**), `test_an_owner_and_an_auditor_see_every_group`, `test_a_person_without_roles_sees_none`
   - `test_the_owner_sees_how_many_people_hold_a_role_and_others_do_not` (`member_count` an int vs None)
   - `test_the_owner_creates_a_group_and_it_is_recorded` (`server_group.created`, target and change)
   - `test_names_clash_without_regard_to_case` (409 `name_taken`, on create and on rename)
   - `test_a_name_must_have_1_to_64_characters` (422)
   - `test_the_owner_edits_a_group` (`server_group.changed` with only the changed field); `test_an_edit_that_changes_nothing_gets_409_no_change`
   - `test_only_an_owner_creates_or_edits` (an Admin of the group: 403 and `access.denied`)
   - `test_an_unknown_group_gets_404`
   Run **BT tests/inventory**: it fails.
2. Implement; include `inventory_router` in `create_app`.
3. Run **BT tests/inventory tests/security**: it passes.

Commit: `feat(inventory): server groups, seen only by the people who hold a role in them`

### 11. Deleting a server group removes the roles in it, each one audited

**Files:** `backend/app/inventory/service.py`, `router.py` (`DELETE /{group_id}`, `audited(SERVER_GROUP_DELETED)`), `backend/tests/inventory/test_group_delete.py`.

1. Tests first:
   - `test_deleting_a_group_removes_its_roles_and_records_each` (two people with roles: two `user.grant_removed`, target each user, `after` None, then `server_group.deleted`; 204; no `role_grants` row left)
   - `test_deleting_an_empty_group_records_only_the_deletion`
   - `test_only_an_owner_deletes` and `test_deleting_an_unknown_group_gets_404`
   - `test_saving_access_for_a_deleted_group_gets_422` (PUT with its ID → 422 `unknown_group`)
   Run **BT tests/inventory/test_group_delete.py**: it fails.
2. Implement it with the C9 `_grant_event` helper (import it from `app.users.service`).
3. Run **BT tests/inventory tests/users tests/security**: it passes.

Commit: `feat(inventory): deleting a server group removes the roles in it`

### 12. The person's own access in GET /api/auth/me

**Files:** `backend/app/auth/schemas.py` (`MeOut.grants`), `backend/app/auth/service.py` (`me`), `backend/tests/auth/test_own_sessions.py` (the `me` test), `backend/tests/auth/test_me_access.py` (new).

1. Tests first in `test_me_access.py`: `test_me_lists_the_persons_group_roles_with_their_switches` (by group name, with `group_name`), `test_me_of_an_owner_has_no_grants_and_platform_role_owner`, `test_me_of_an_auditor`. Update the expected body in `test_own_sessions.py` with `"grants": []`. Run **BT tests/auth**: it fails.
2. Implement C6 `me`.
3. Run **BT tests/auth**: it passes.

Commit: `feat(auth): a person can read their own access`

### 13. Security suite: one walk records every access and user action, and no event holds a secret

**Files:** `backend/tests/security/test_access_events.py`.

1. Write `test_one_walk_records_every_access_and_user_action_and_no_secret(api, clock)`: the Owner (`make_user()`, `sign_in`) creates groups `staging` and `production`; invites `ada@example.com` as Admin on staging (keep the token and `PASSWORD_ADA` as secrets); a second client checks and accepts the link, enrols (keep the TOTP secret and recovery codes), and a wrong token is refused once; the Owner changes Ada's access (a switch, a role, add production, remove it); Ada's client calls `GET /api/users` (denied); the Owner renews an invite of a second invitee, disables Ada, enables her, resets her second factor, and deletes `staging`. Then:
   - the recorded actions include `users.actions.ALL_ACTIONS | inventory.actions.ALL_ACTIONS | {"access.denied", "auth.mfa_reset", "auth.session_revoked"}`
   - `verify_chain(session).ok`
   - no audit row (every column, as JSON; reuse `audit_rows` from `test_auth_events.py` by moving it into `auth_helpers.py`) contains any kept secret or session token
2. Run **SECURITY**: it passes. If an action is missing, fix the route that should record it, not the test.

Commit: `test(security): every access and user action is audited and no event holds a secret`

### 14. Stack check: an invited person signs in and is refused on Users

**Files:** `backend/tests/test_stack.py`.

1. Before `test_after_sign_out_pages_redirect_to_login`, add `test_an_invited_person_accepts_enrols_and_cannot_list_users(owner)`: the Owner posts `/api/server-groups` `{"name": "staging"}` and `/api/users` with `{"name": "Ada", "email": "ada@stack.invalid", "platform_role": None, "grants": [{"group_id": …, "role": "admin", "connect_ssh": True}]}`; a new `httpx.Client` posts `/api/auth/invite/check` and `/api/auth/invite/accept`, enrols with `pyotp`, then `GET /api/users` → 403 and `GET /api/server-groups` lists only staging.
2. Run **STACK** and **DOCKER**: they pass.

Commit: `test(stack): an invited person signs in through Caddy and is refused on Users`

### 15. Frontend: access types and helpers, the invite gate and the new messages

**Files:** `frontend/src/lib/access.ts` + `src/lib/__tests__/access.test.ts` (C12), `src/lib/auth/gate.ts` (`SessionUser.platform_role: PlatformRole | null`; the default branch lets `/invite` through), `src/lib/auth/__tests__/gate.test.ts`, `src/lib/api.ts` (no sign-in redirect on `/invite`), `src/lib/__tests__/api.test.ts`, `src/lib/auth/messages.ts` (C13) + its test, `src/lib/auth/__tests__/backend.test.ts`, `src/components/profile/profile-page.tsx` (badge from `platform_role === "owner"`) and its test, `tools/test-services/stub-backend.Caddyfile` (`"platform_role":"owner"`).

1. Tests first:
   - `access.test.ts`: `switchesFor` of each role; `canHold("operator", "manage_playbooks")` false; `withRole` to operator never ticks manage playbooks; `sameAccess` ignores order and spots a switch, a role and a platform role; `accessOf` strips `group_name`; `badgesOf` for Owner, Auditor, two groups, none (`["No access"]`); `inviteLink("https://a.example", "tok")` → `https://a.example/invite#tok`.
   - `gate.test.ts` rows: `[null, "/invite", "", null]`, `["signed_out", "/invite", "", null]`, `["mfa_required", "/invite", "", null]`, `["active", "/invite", "", null]`, `["setup_required", "/invite", "", "/setup"]`.
   - `api.test.ts`: a 401 `not_signed_in` on `/invite` does not call `goTo`.
   - `messages.test.ts`: each C13 detail.
   - Fixtures with `is_owner` move to `platform_role`.
   Run **FE src/lib**: it fails.
2. Implement.
3. Run **FE-GATE**: it passes.

Commit: `feat(frontend): access types, the invite gate and the texts of the Users pages`

### 16. Frontend: the access form with the three kinds and the grant matrix

**Files:** `frontend/src/components/ui/select.tsx`, `radio-group.tsx` (`cd frontend && npx shadcn@latest add select radio-group`; keep the generated files as they are, and `package.json`/`package-lock.json` only if it adds a dependency), `frontend/src/components/settings/access-form.tsx` (C14), `src/components/settings/__tests__/access-form.test.tsx`.

1. Tests first (render with a controlled wrapper that keeps `value` in state):
   - `choosing Admin ticks all seven switches`, `choosing Operator ticks its five and disables Manage playbooks`
   - `No access clears and disables the row` (grant removed from the value)
   - `Auditor and Owner hide the matrix, and By server group brings the rows back`
   - `a switch can be turned off after choosing a role`
   - `it says only the connect switches are checked for now`
   - `without groups it points to the Server groups tab`
   Run **FE src/components/settings**: it fails.
2. Implement.
3. Run **FE-GATE**: it passes.

Commit: `feat(frontend): the access form with a role and seven grants per server group`

### 17. Frontend: Settings tabs, the Owner-only notice, the Users table and the invite dialogs

**Files:** C15 files (`settings/layout.tsx`, `page.tsx`, `users/page.tsx`, `groups/page.tsx` rendering a placeholder `<GroupsPage />` stub is **not** allowed: create `groups/page.tsx` in step 20 instead), `src/components/settings/settings-tabs.tsx`, `users-page.tsx`, `invite-dialog.tsx`, `invite-link-dialog.tsx`, tests in `src/components/settings/__tests__/` (`settings-tabs.test.tsx`, `users-page.test.tsx`, `invite-dialog.test.tsx`), `src/app/(app)/settings/__tests__/layout.test.tsx`.

- `UsersPage({ currentUserId })` loads `/users` and `/server-groups`. A Card "People" with the button "Invite person" and a Table inside `overflow-x-auto`: Name (name, email below), Access (`badgesOf`), Status ("Active"; "Invited · link expires <formatTime>"; "Disabled"), Two-step ("On" / "Not set up"), and a menu button labelled `Actions for <name>`. The own row has a "You" badge and no menu. Menu items by status: active: "Change access", "Reset two-step verification", "Disable"; invited: "Change access", "New invite link", "Disable"; disabled: "Change access", "Enable". (Their handlers come in steps 18 and 19; this step renders the items.)
- `InviteDialog` ("Invite a person"): Name, Email, `AccessForm`, button "Create invite link" → `POST /users` → `onCreated(link: InviteLink)`.
- `InviteLinkDialog({ link, name })` ("Invite link for <name>"): read-only input with `inviteLink(window.location.origin, token)`, "Copy link" (`navigator.clipboard.writeText`, then "Copied"), "This link is shown once. It works until <formatTime(expires_at)>.", "Done".

1. Tests first: tabs mark the current page; layout shows the notice to a non-Owner (mock `@/lib/auth/server`) and the tabs to an Owner; rows and menus by status, no menu on the own row; invite posts `{name, email, platform_role, grants}` and shows the link once and copies it; `email_taken` shows its text. Run **FE src/components/settings src/app**: it fails.
2. Implement; `settings/page.tsx` redirects to `/settings/users`.
3. Run **FE-GATE**: it passes.

Commit: `feat(frontend): the Owner sees people on Settings and invites one with a link`

### 18. Frontend: change a person's access

**Files:** `src/components/settings/access-dialog.tsx`, `users-page.tsx`, `__tests__/access-dialog.test.tsx`, `__tests__/users-page.test.tsx`.

`AccessDialog({ user, groups, open, onOpenChange, onSaved, onStale })` ("Change access of <name>"): `AccessForm` starting from `accessOf(user)`; "Save" is disabled while `sameAccess(initial, value)`; `PUT /users/<id>/access` with `{platform_role, grants}`; 204 → `onSaved()` (the page closes it, reloads and shows "Access of <name> saved."); 422 → `onStale()` (the page reloads the groups) and the `invalid` text; other refusals show `messageFor(detail)`.

1. Tests first: Save disabled until something differs; it sends the whole access; a 422 calls `onStale`; `own_account` shows its text; the page opens it from "Change access". Run **FE src/components/settings**: it fails.
2. Implement.
3. Run **FE-GATE**: it passes.

Commit: `feat(frontend): the Owner changes a person's role and grants`

### 19. Frontend: disable, enable, reset two-step verification and a new invite link

**Files:** `src/components/settings/disable-dialog.tsx`, `users-page.tsx`, `__tests__/disable-dialog.test.tsx`, `__tests__/users-page.test.tsx`.

- "Disable" opens `DisableDialog({ user, open, onOpenChange, onDone })`: "Disable <name>?", "They are signed out at once and cannot sign in until an Owner enables the account. Their access and history stay.", buttons "Cancel" and "Disable" (destructive) → `POST /users/<id>/disable`; `last_owner`/`own_account` show their texts.
- "Enable" → `POST /users/<id>/enable`, notice "<name> can sign in again."
- "Reset two-step verification" → `POST /users/<id>/mfa-reset`, notice "Two-step verification of <name> is reset. They set up a new authenticator at their next sign-in."
- "New invite link" → `POST /users/<id>/invite`, then `InviteLinkDialog`.
Each success reloads the list.

1. Tests first: disable asks first and posts only after "Disable"; enable, reset and new link post to their routes and show their notices; a refusal shows its text. Run **FE src/components/settings**: it fails.
2. Implement.
3. Run **FE-GATE**: it passes.

Commit: `feat(frontend): the Owner disables, enables and helps a person back in`

### 20. Frontend: the Server groups tab

**Files:** `src/app/(app)/settings/groups/page.tsx`, `src/components/settings/groups-page.tsx`, `group-dialog.tsx`, `delete-group-dialog.tsx`, tests in `__tests__/`.

- `GroupsPage` loads `/server-groups` and `/users`. Card "Server groups" with "New group"; table (scrolls sideways): Name, Description, People (`member_count`), buttons `Edit <name>` and `Delete <name>`.
- `GroupDialog({ group?, ... })` ("New server group" / "Edit <name>"): Name (1 to 64 characters, hint), Description; create `POST /server-groups`; edit `PATCH /server-groups/<id>` with `{name, description}`, Save disabled until something differs; `name_taken` shows its text.
- `DeleteGroupDialog({ group, people })`: "Delete <name>?", "These people lose their role in it: A, B." or "Nobody holds a role in it.", "Delete group" (destructive) → `DELETE /server-groups/<id>`.

1. Tests first: create, edit (disabled until changed), a name clash, delete names the people from `/users` grants. Run **FE src/components/settings**: it fails.
2. Implement.
3. Run **FE-GATE**: it passes.

Commit: `feat(frontend): the Owner creates, edits and deletes server groups`

### 21. Frontend: the /invite page

**Files:** `src/app/(auth)/invite/page.tsx`, `src/components/auth/invite-flow.tsx`, `src/components/auth/__tests__/invite-flow.test.tsx`, `frontend/image-tests/shell.test.ts`.

- Page (server): metadata title "Accept your invite". `getSession()`: `mfa_required` or `enrolment_required` → `redirect("/login")`; `active` → `<InviteSignedIn name email />`; else `<InviteFlow />`.
- `InviteSignedIn`: "You are signed in as <name> (<email>). Sign out first to use this invite link." and "Sign out" → `apiFetch("/auth/logout", { body: {} })`, then `window.location.reload()` (keeps the `#`).
- `InviteFlow`: "Step N of 3". On mount reads `window.location.hash.slice(1)`; empty, or `POST /auth/invite/check` refused → a Card "This invite link does not work" with "Ask the Owner for a new link.". Valid → "Welcome, <name>" with the email, Password and "Repeat the password" (12 to 128 code points, mismatch → "The passwords do not match."), "Set password" → `POST /auth/invite/accept {token, password}`, then `history.replaceState(null, "", "/invite")`; step 2 `EnrolStep` (`onRestart` → `goTo("/login")`); step 3 `RecoveryCodes` → `goTo("/")`. Before the check: "Checking the invite link…".

1. Tests first: a valid link; a dead link (no hash, and a 404); mismatched passwords post nothing; the steps through to the recovery codes and `/`; the signed-in notice signs out. Image test: `GET /invite` without cookie → 200 and contains "Checking the invite link"; `GET /settings` without cookie → 307 to `/login?next=%2Fsettings`. Run **FE src/components/auth**: it fails.
2. Implement.
3. Run **FE-GATE** and **IMAGE**: they pass.

Commit: `feat(frontend): an invited person sets a password and enrols from the link`

### 22. Frontend: the person's own access on Profile and security

**Files:** `src/components/profile/profile-page.tsx` (`Me.grants: GrantOut[]`), its test.

The Account card shows name and email, then "Access": Owner → badge "Owner" and "Runs the platform."; Auditor → badge "Auditor"; else one line per grant: "<Role> in <group>" with the labels of its switches that are on ("No grants" when none); no role at all → "No access yet. Ask the Owner of this installation."

1. Tests first: Owner, Auditor, an Admin on staging with Connect SSH and View logs, no access. Run **FE src/components/profile**: it fails.
2. Implement.
3. Run **FE-GATE**: it passes.

Commit: `feat(frontend): a person sees their own access on Profile and security`

### 23. README and AGENTS, then the full check

**Files:** `README.md` (a "People and access" section after "Lost access": the Owner invites on Settings → Users with a link valid 7 days and passes it on; roles are given per server group, Admin or Operator with seven switches, of which only Connect SSH and Connect RDP are checked so far; Auditor and Owner cover every group; disable instead of delete; `make reset-password` and `make reset-mfa` still work for every account), `AGENTS.md` (the Security suites line names the permission-coverage and access-events suites).

1. Run **BACKEND**, **DOCKER**, **STACK**, **SECURITY**, **FE-GATE**, **IMAGE**. All pass.
2. By hand on `make up STACK=dev`: create two groups, invite a person as Admin on staging only, accept the link in a private window, see only staging on Profile, get the notice on Settings, then disable them. `make down STACK=dev`.

Commit: `docs: people, roles per server group and the security suites`

## Final verification

```
cd backend && megoocolab-runner services run migrate -- sh -c 'uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head'
cd backend && megoocolab-runner services run test -- uv run pytest
cd backend && megoocolab-runner services run image -- uv run pytest -m docker
cd backend && megoocolab-runner services run stack -- uv run pytest -m stack
make test-security
cd frontend && npx tsc --noEmit && npx eslint src image-tests && npm test
cd frontend && megoocolab-runner services run web -- npm run test:image
```

Done when all pass, `test_a_staging_only_admin_sees_staging_and_not_production` and `test_a_staging_only_admin_may_connect_to_staging_and_not_to_production` pass, `test_access_events.py` sees every action, and the hand check on `make up STACK=dev` behaves as step 23 says.
