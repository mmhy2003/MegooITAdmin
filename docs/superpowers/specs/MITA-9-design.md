# MITA-9 design: users, roles and per-group grants

## Goal

After this task an Owner manages people on Settings: invites them with a one-time link, gives each one a role per server group with seven grant switches, and disables them. The backend gets one place that answers "may this person do this in this group?", every refusal is an audit event, and every change to a user or a grant is an audit event with before and after. Mockup v1 shows the nine screens.

## What the repository looks like today

- `users` has `is_owner` and nothing else about rights. Only the Owner from setup exists, and nothing can create a second account.
- Every route needs an active session (`CurrentUser`), and no route checks who the person is.
- There are no server groups, no servers and no SSH connect. They come with MITA-10 and MITA-11.
- `/settings` is a placeholder page.
- The app sends no email.

## Decisions

Answers from the owner:

1. **A role per server group.** Owner and Auditor are platform-wide. Admin and Operator are given per group, so one person can be Admin on staging and Operator on production. Rejected: one role per person, where groups only say where the role applies.
2. **This task adds a minimal `server_groups`** (name and description) and a Server groups tab on Settings where the Owner creates, edits and deletes groups. MITA-10 adds servers and tags on top. Rejected: a bare table without management, and doing MITA-10 first.
3. **A person is invited with a one-time link** that the Owner copies and passes on. It is valid 7 days, and only its hash is stored. The person chooses their own password, then enrols their authenticator. Rejected: a temporary password, and a password typed by the Owner.
4. **Mockup v1 is approved**, with these four choices:
   - Access is one of three kinds: by server group, Auditor, or Owner. An Auditor or Owner holds no group roles.
   - An Owner can reset another person's second factor from the row menu.
   - Accounts are disabled and enabled, never deleted.
   - An Owner cannot change, disable or reset their own account on this page.

Decisions I made (say so if you want one changed):

5. **What "done" means here.** Servers and SSH connect do not exist yet, so this task cannot show a refused connection to a production server. It is done when: a staging-only Admin does not get the production group from the API; the `connect` check refuses them for production in tests, with an audit event; and a security test fails for any new route that does not declare who may call it. MITA-10 then filters the server list with `visible_group_ids()`, and MITA-11 puts `require_grant(Permission.CONNECT_SSH)` on its connect route.
6. **Seven grant switches per group role:** connect SSH, connect RDP, view logs, view processes, manage processes, run playbooks, manage playbooks. SSH and RDP are separate, as PRD §6.3 says. All seven are stored and editable. Only the two connect switches are checked by code in this sprint, and the dialog says so.
7. **What a role adds to the switches.** Choosing Admin ticks all seven. Choosing Operator ticks connect SSH, connect RDP, view logs, view processes and run playbooks. The Owner can change each one, except that an Operator can never hold manage playbooks (PRD §14.1), which the database also checks. The role itself will matter from Phase 4 (Admins approve, Operators do not).
8. **Seeing a group means holding a role in it.** A row with every switch off still lets the person see the group and, later, its servers. An Owner and an Auditor see every group. An Auditor can use none of the seven grants.
9. **A group the person cannot see answers 404, and a missing grant answers 403.** So group IDs cannot be probed. Both are recorded as `access.denied`.
10. **A denial is recorded with `record_alone` and then raised**, as the MITA-7 design planned. The check runs before the handler, so the request's transaction does not hold the audit chain yet.
11. **Rights are read from the database on every request.** A changed role or grant applies to the person's next request, and no session has to end. Disabling ends the person's sessions.
12. **One save of the access dialog is one transaction with one event per difference:** `user.role_changed`, `user.grant_added`, `user.grant_changed` and `user.grant_removed`. A save that changes nothing answers 409 `no_change`, because a state-changing route must record an event. The Save button is disabled until something differs.
13. **The invite token travels after `#`** (`/invite#<token>`), so it never reaches Caddy's or Next.js's request logs. The page posts it in a JSON body.
14. **`users.is_owner` is replaced by `users.platform_role`** (`owner`, `auditor` or null). `roles` holds the four roles as rows, and the other tables point at it.
15. **An invited account has no password** (`password_hash` is null) until the link is used. Signing in to it, or to a disabled account, is refused with the same message as a wrong password.
16. **Group names are unique without regard to case**, 1 to 64 characters.
17. **Only an Owner manages groups in this task.** MITA-10 decides what an Admin may do with the inventory.
18. **Settings stays in the sidebar for everyone.** A person who is not an Owner sees a short notice there (screen 9). Hiding sidebar items by role is left for when the pages behind them exist.
19. **The Account card on Profile and security lists the person's own access** (screen 9), so a person can see why something is refused.

## Architecture

### Backend

| Package | Module | Purpose |
|---|---|---|
| `app/access/` (new) | `models.py` | `Role`, `RoleGrant` |
| | `permissions.py` | `Permission` (the seven switches), each role's usual and allowed switches, and `Access`: the person's platform role and group roles with pure methods `allows(permission, group_id)`, `sees(group_id)`, `visible_group_ids()` (None means all) |
| | `deps.py` | `current_access` / `CurrentAccess`, `require_owner`, `require_grant(permission, group=…)`, `require_group_visible(group=…)`, and the recording of a denial |
| | `actions.py` | `access.denied` |
| `app/users/` (new) | `models.py` | `UserInvite` |
| | `invites.py` | Create, hash, find and use an invite token |
| | `service.py` | List, invite, new link, set access (the diff and its events), disable, enable, reset second factor |
| | `schemas.py`, `router.py`, `actions.py` | The routes under `/api/users` and the `user.*` action names |
| `app/inventory/` (new) | `models.py`, `service.py`, `schemas.py`, `router.py`, `actions.py` | `ServerGroup` and the routes under `/api/server-groups`. MITA-10 grows this package |
| `app/auth/` | `models.py` | `User`: `platform_role`, `disabled_at`, nullable `password_hash`; `is_owner` goes |
| | `service.py` | Sign-in refuses a disabled or not-yet-accepted account. `reset_second_factor(db, user)` moves here from `cli.py`, so the host command and the Owner's route share it. `me` returns the person's access |
| | `router.py`, `schemas.py` | `POST /auth/invite/check`, `POST /auth/invite/accept`. `UserOut.platform_role` replaces `is_owner` |
| | `cli.py` | Uses `reset_second_factor`. `reset-password` on an invited account also deletes its open invite |
| `app/` | `main.py`, `models.py` | Include the two new routers and the new model modules |

How a request is checked:

- `current_access` takes `CurrentUser` and loads the person's `role_grants` in one query (none for an Owner or Auditor). The result is an immutable `Access`.
- `require_owner` is a router-level dependency of `/api/users` and a route dependency of the group write routes.
- `require_grant(permission, group=…)` returns a dependency. `group` is itself a dependency that returns the group ID of the request's target. Its default reads the path parameter `group_id`. MITA-11 passes one that loads the server and returns its group.
- Each of the three carries a marker attribute, as `audited` does, so the coverage test can find it.

How a later task uses it:

```python
@router.post("/servers/{server_id}/connect",
             dependencies=[audited("remote_session.opened"),
                           Depends(require_grant(Permission.CONNECT_SSH, group=group_of_server))])
async def connect(...): ...

# a list filters instead of refusing
group_ids = access.visible_group_ids()   # None: every group
```

### Frontend

| File | Purpose |
|---|---|
| `src/app/(app)/settings/layout.tsx` | Loads the session user. Not an Owner: the notice of screen 9. Owner: the tab links (Users, Server groups) above the page |
| `src/app/(app)/settings/page.tsx`, `settings/users/page.tsx`, `settings/groups/page.tsx` | `/settings` redirects to `/settings/users` |
| `src/components/settings/` | `users-page`, `invite-dialog`, `invite-link-dialog`, `access-dialog`, `access-form` (the three kinds and the matrix), `disable-dialog`, `groups-page`, `group-dialog`, `delete-group-dialog` |
| `src/lib/access.ts` | Types, the seven grants with their labels, each role's usual switches, and pure helpers: the switches after a role change, whether two access values differ, the badges of a person |
| `src/app/(auth)/invite/page.tsx`, `src/components/auth/invite-flow.tsx` | Screen 8. Reads the token from the address's `#`, checks it, takes the password, then reuses `EnrolStep` and `RecoveryCodes` from the setup flow |
| `src/lib/auth/gate.ts` | `/invite` is let through unless the status is `setup_required`. `SessionUser.platform_role` replaces `is_owner` |
| `src/components/profile/profile-page.tsx` | The Account card lists the person's access |
| `src/lib/auth/messages.ts` | Texts for `forbidden`, `email_taken`, `name_taken`, `own_account`, `last_owner`, `invalid_invite`, `already_accepted`, `no_change` |

- New shadcn components: `select`, `radio-group`.
- Under 768 px the tables scroll sideways in their card, and the matrix shows one block per group, as in the mockup.
- The `/invite` page: with an active session it says who is signed in and offers Sign out. With a pending session it redirects to `/login`, which continues the code or enrolment step.
- The invite link is built in the browser from `window.location.origin` and the token.

### Tooling and docs

- `tools/test-services/stub-backend.Caddyfile`: the stub user carries `platform_role`.
- `README.md`: a short "People and access" paragraph (invite, roles per group, disable).
- `AGENTS.md`: the Security suites line names the permission-coverage and access-events suites.

## Data and interfaces

### Migration `0005_roles_and_grants`

**`roles`**: `key text` PK, `name text`, `scope text` (`platform` or `group`, check), `position smallint`. Seeded: `owner` and `auditor` (platform), `admin` and `operator` (group).

**`users`** (changed): add `platform_role text` null, FK to `roles.key`, check `IN ('owner', 'auditor')`. Add `disabled_at timestamptz` null. `password_hash` becomes nullable. `is_owner = true` becomes `platform_role = 'owner'`, then `is_owner` is dropped. The downgrade reverses this and gives an account without a password an unusable hash.

**`server_groups`**: `id uuid` PK, `name text`, `description text` null, `created_at`. Unique index on `lower(name)`.

**`role_grants`**: `id uuid` PK, `user_id` FK to `users` (cascade), `server_group_id` FK to `server_groups` (cascade), `role text` FK to `roles.key` with check `IN ('admin', 'operator')`, the booleans `connect_ssh`, `connect_rdp`, `view_logs`, `view_processes`, `manage_processes`, `run_playbooks`, `manage_playbooks` (default false), `created_at`, `updated_at`. Unique `(user_id, server_group_id)`. Check `role = 'admin' OR NOT manage_playbooks`. Index on `server_group_id`.

**`user_invites`**: `user_id uuid` PK and FK to `users` (cascade), `token_hash bytea` unique, `expires_at`, `created_at`. One open invite per person. The token is 256 random bits, stored as SHA-256.

Grants for `megooitadmin_api`, also added to `API_GRANTS`: `roles` SELECT. `server_groups`, `role_grants` and `user_invites` SELECT, INSERT, UPDATE, DELETE. `users` stays SELECT, INSERT, UPDATE.

### Routes

| Route | Who | Does | Audit events |
|---|---|---|---|
| `GET /api/users` | Owner | Every account: name, email, platform role, group roles with their switches, status (`active`, `invited`, `disabled`), whether an authenticator is enrolled, when the invite expires | none |
| `POST /api/users` `{name, email, platform_role, grants}` | Owner | Creates the account without a password and its invite. Returns the token once. 409 `email_taken` | `user.invited`, `user.grant_added` per group |
| `POST /api/users/{id}/invite` | Owner | A new link in place of the old one. 409 `already_accepted` once the person has a password | `user.invite_renewed` |
| `PUT /api/users/{id}/access` `{platform_role, grants}` | Owner | Sets the whole access. Choosing Owner or Auditor removes the group roles | `user.role_changed`, `user.grant_added`, `user.grant_changed`, `user.grant_removed` |
| `POST /api/users/{id}/disable` | Owner | Sets `disabled_at`, deletes an open invite, ends the sessions | `user.disabled`, `auth.session_revoked` per session |
| `POST /api/users/{id}/enable` | Owner | Clears `disabled_at` | `user.enabled` |
| `POST /api/users/{id}/mfa-reset` | Owner | Removes the authenticator and recovery codes and ends the sessions | `auth.mfa_reset`, `auth.session_revoked` per session |
| `POST /api/auth/invite/check` `{token}` | public | `{name, email}` for a valid link, else 404 `invalid_invite` | none (pinned in `EXEMPT`: it reads only, and POST keeps the token out of addresses) |
| `POST /api/auth/invite/accept` `{token, password}` | public | Sets the password, deletes the invite, gives a pending session. Answers `enrolment_required` | `user.invite_accepted`, or `user.invite_refused` |
| `GET /api/auth/session`, `GET /api/auth/me` | as today | `user.platform_role` replaces `is_owner`. `me` adds `grants` | none |
| `GET /api/server-groups` | signed in | The groups the person sees. For an Owner, also how many people hold a role in each | none |
| `POST /api/server-groups` `{name, description}` | Owner | 409 `name_taken` | `server_group.created` |
| `PATCH /api/server-groups/{group_id}` | Owner | Name and description. 409 `name_taken`, 409 `no_change` | `server_group.changed` |
| `DELETE /api/server-groups/{group_id}` | Owner | Deletes the group and the roles in it | `server_group.deleted`, `user.grant_removed` per role |

- The four user routes that change another account (`access`, `disable`, `enable`, `mfa-reset`) answer 409 `own_account` for the Owner's own ID.
- A grant in a request names a `group_id`, a `role` and the seven switches. An unknown group, a group listed twice, or an Operator with manage playbooks answers 422.

### Audit events

- **`user.*` and `auth.mfa_reset`**: the actor is the Owner, the target is the account (`type="user"`, its ID and email).
- **Grant events** carry `context={"server_group_id": …}`, `result_detail={"server_group": <name>}` and `change` from `changes(before, after)` over the role and the seven switches. An added grant has `before: null` for every field, a removed one `after: null`.
- **`user.role_changed`**: `change={"platform_role": {"before": …, "after": …}}`.
- **`user.invited`**: `change` holds the name, the email and the platform role. No event ever holds an invite token or a password.
- **`server_group.*`**: the target is the group, with `change` for name and description.
- **`access.denied`**: result `failure`, the actor is the person, the target is the group when there is one, and `result_detail={"required": "owner" | "group" | "<permission>", "route": "POST /api/users"}`.
- **Sign-in to a disabled or not-yet-accepted account**: the existing `auth.sign_in_failed`, with reason `disabled` or `not_accepted`.

## Error handling and edge cases

- **Two Owners remove each other at once.** A change that demotes or disables an Owner first locks every enabled Owner's row, then checks that the actor is still an enabled Owner. The second request then finds its actor demoted and is refused with 403. So at least one enabled Owner always remains. `last_owner` (409) is the answer if the count would still reach zero.
- **Disabling while the person signs in.** Sign-in and disable both lock the user's row, so they take turns: either the sign-in is refused, or its session is deleted by the disable.
- **A link used twice, replaced or expired.** Accepting locks the invite row. The second use finds it gone and gets the screen "This invite link does not work". A new link deletes the old row.
- **The invited person reloads during enrolment.** The invite is used already, and the pending session sends them to `/login`, which shows the enrolment step, as after setup.
- **An invite opened in a browser that is signed in.** The page asks to sign out first, so nobody takes over a link by accident while keeping another session.
- **A wrong email in an invite.** Disable that account and invite the right address. The disabled row stays (see Out of scope).
- **An account without any role.** It can sign in and sees the shell and no group. The Users table shows "No access".
- **A group is deleted while someone holds a role in it.** The roles go with it, each as `user.grant_removed`, and the dialog names the people first. MITA-10 adds the refusal for a group that still holds servers.
- **Stale dialog.** Saving access for a group that was deleted meanwhile answers 422, and the dialog reloads the groups.
- **Two Owners edit the same person.** The last save wins. Each save's events show what it changed from what was stored at that moment.
- **The denial cannot be recorded** (the audit chain is busy). The request answers 500, not 403: a refusal without its event does not happen.
- **A person who is refused fills the audit log.** They are signed in and named in every event, and an Owner can disable them.
- **`reset-mfa` and `reset-password` on the host** keep working for every account, disabled ones included. They do not enable an account.

## Testing

Tests are written first. Backend tests run with `megoocolab-runner services run test -- uv run pytest`.

**`tests/access/`**
- `Access` rules (no database): an Owner is allowed everything everywhere. An Auditor sees every group and is allowed none of the seven. A staging-only Admin sees staging only, is allowed connect there and nothing in production. A switch that is off is refused although the role is Admin. `visible_group_ids()` is None for Owner and Auditor.
- The dependencies on a throwaway app: `require_owner` lets an Owner through and answers 403 to anyone else. `require_grant` answers 404 for a group the person does not see and 403 for a missing switch. Each refusal leaves exactly one `access.denied` event with the route and the requirement, although the request rolled back.
- A change of grants applies to the very next request of a session that is already open.

**`tests/users/`**
- Invite: the account has no password, the token works once, only its hash is stored, a second invite for the same email gets 409.
- Accept: sets the password, gives a pending session and leads to enrolment. An expired, used, replaced or unknown token is refused and recorded. A disabled account's link is refused.
- Set access: each kind of difference gives its event with the right before and after. Owner or Auditor removes the group roles. An Operator with manage playbooks, an unknown group and a duplicate group get 422. No difference gets 409.
- Disable ends the sessions and refuses sign-in with the usual message. Enable restores sign-in with the same roles.
- Reset second factor forces enrolment at the next sign-in.
- Own account: every changing route answers 409. Two Owners demoting each other at once leave one Owner.
- Sign-in: a disabled and a not-yet-accepted account are refused with `invalid_credentials` and the right reason in the event.

**`tests/inventory/`**
- Create, edit, delete. Names clash without regard to case. Deleting removes the roles and records each.
- **The task's sentence:** a staging-only Admin's `GET /api/server-groups` holds staging and not production, and an Owner's and an Auditor's hold both.

**Security suites, `tests/security/`** (run by `make test-security`)
- `test_permission_coverage.py` (new): every route that needs an active session declares `require_owner`, `require_grant` or `require_group_visible`, or is pinned in `ANY_SIGNED_IN` with a reason (the `/api/auth/*` self-service routes, and `GET /api/server-groups`, which filters by itself). The check reports an undeclared route of a sample app.
- `test_access_events.py` (new): one walk (create groups, invite, accept, change access, deny, disable, enable, reset, delete a group) produces every action of the table above, the chain check passes, and no audit row holds the invite token or the password.
- `test_auth_coverage.py`: `PUBLIC` gains the two invite routes. `test_audit_coverage.py`: `EXEMPT` gains `POST /api/auth/invite/check`. `test_db_privileges.py`: the four new tables.

**Other backend tests**
- `test_migrations.py`: `0005` goes down and up, an Owner from `0004` keeps the role across it, and the models match.
- Existing auth tests and helpers move from `is_owner` to `platform_role`.
- `test_stack.py` (`-m stack`): after setup the Owner creates a group and invites a person, the person accepts and enrols, and their `GET /api/users` answers 403.

**Frontend** (Vitest)
- `access.ts`: the usual switches of each role, an Operator never gets manage playbooks, the difference check, the badges.
- `access-form`: choosing a role ticks its switches, "No access" clears and disables the row, Auditor and Owner hide the matrix.
- Users page: the rows and their menus by status, no menu on the own row. Invite shows the link once and copies it. Change access sends the whole access and keeps Save disabled until something differs. Disable asks first.
- Groups page: create, edit, and delete with the people named.
- Invite flow: a valid link, a dead link, mismatched passwords, the steps through to the recovery codes.
- Gate: `/invite` is let through signed out and with an active session, and goes to `/setup` on a fresh install.
- Settings layout: the notice for a person who is not an Owner. Profile: the access list.
- Image check (`web` set): without the cookie `/invite` renders and `/settings` redirects to `/login`.

Done when `make test` and `make test-security` pass, and by hand on `make up STACK=dev`: create two groups, invite a person as Admin on staging only, accept the link in a private window, see only staging on their Profile page, get refused on Settings, then disable them.

## Out of scope

- Refusing a connection to a real server and filtering the real server list: MITA-11 and MITA-10, with `require_grant` and `visible_group_ids()` from this task.
- Enforcing view logs, view processes, manage processes, run playbooks and manage playbooks: the phases that build those features.
- What an Admin, Operator or Auditor may do beyond the grants (approvals, secrets, jobs, the knowledge base, how much of the audit trail they see): the phases that build those features.
- Servers, tags, and the per-group policy switches of PRD §6.3 (reason, second factor, time window, clipboard, file transfer).
- Deleting an account, and editing another person's name or email.
- An Owner resetting someone's password. `make reset-password` stays the way back.
- Email: sending the invite link, and notices about access changes.
- Hiding sidebar items by role, and filtering the global search by grants (Phase 6).
- Asking for the second factor again before a change to users or grants.
- Custom roles, single sign-on and passkeys.
