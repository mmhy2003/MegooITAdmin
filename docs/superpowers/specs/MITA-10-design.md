# MITA-10 design: server inventory (servers, groups and tags)

## Goal

After this task the Owner, or an Admin of a group, registers a server into that group on the Servers page, edits it, moves it and removes it. Everyone with a role in the group sees the server in the list and on its own page, and nobody else does. Every change is an audit event. Mockup v1 shows the eight screens.

## What the repository looks like today

- `server_groups` exists with name and description, and the Owner manages groups on Settings → Server groups (MITA-9).
- `app/access` answers "does this person see this group" (`Access.sees`, `visible_group_ids()`) and "do they hold this grant" (`require_grant`). Nothing asks yet whether a person is **Admin** of a group.
- `/servers` is a placeholder page. There is no `servers` table and no SSH code.
- Two security suites read every route: each state-changing route must declare its audit actions, and each signed-in route must declare who may call it.

## Decisions

Answers from the owner:

1. **The Owner and Admins in their own groups change the inventory.** An Admin of staging registers, edits and removes servers in staging only. Moving a server needs Admin on both groups. Operators and Auditors only read. Rejected: Owner only, and Admins who cannot remove or move.
2. **Tags are free labels typed on the server.** A tag exists while a server carries it, so there is nothing to manage. Rejected: a managed list of tags with its own screen, and bulk rename or delete of a tag.
3. **Mockup v1 is approved**, with these choices:
   - Register and Edit are one dialog on the Servers page.
   - The fields are name, address, server group, operating system, port, login account, role and tags.
   - The host key is not asked for. The column exists and stays empty until MITA-11 pins it at the first connection.
   - The server page has one tab, Overview, and no Connect or Run playbook button yet.
   - Remove deletes the server after a confirmation. There is no archive.
   - The list filters by group and tags only, and the filters live in the address.
   - A group that still holds servers cannot be deleted.

Decisions I made (say so if you want one changed):

4. **A server lives in exactly one group.** The group decides who sees it and who may connect, as MITA-9 planned with `group_of_server`. Tags never decide access.
5. **Server names are unique across all groups**, without regard to case, because people and agents address a server by its name ("Connect to db-01"). The cost: an Admin who types a name used in a group they cannot see learns that the name is taken. Addresses are not unique.
6. **Seeing follows the MITA-9 rules.** A server in a group the person does not see answers 404, the same as a server that does not exist. A person who sees the group but is not its Admin gets 403 on a change. Both refusals are recorded as `access.denied`.
7. **One save is one transaction with one event per kind of difference:** `server.changed` for the fields, `server.moved` for the group, `server.tags_changed` for the tags. A move changes who can reach the server, so it gets its own action that is easy to find later. A save that changes nothing answers 409 `no_change`.
8. **Connection settings are a JSON column** that holds only `username` for now (default `megoo`, PRD §4). Later phases add keys without a migration each. The port is its own column: the SSH port for Linux and the RDP port for Windows.
9. **Windows servers can be registered**, although nothing connects to them before Phase 2.
10. **The backend filters the list** (`group_id`, `tag`), so later callers such as the agents' `list_servers` get the same filters. The list is not paged: the PRD plans for a few hundred servers.
11. **The backend tells the page what the person may do** (`can_manage` on each group and server), so the rule lives in one place.

## Architecture

### Backend

| Package | Module | Change |
|---|---|---|
| `app/access/` | `permissions.py` | `Access.manages(group_id)`: true for an Owner, and for a person whose role in the group is Admin |
| | `deps.py` | `require_group_admin(group=…)`: 404 when the person does not see the group, 403 when they are not its Admin. It carries `access_requirement = "admin"` and records the denial like the other guards |
| `app/inventory/` | `models.py` | `Server`, `ServerTag` beside `ServerGroup` |
| | `server_schemas.py` (new) | `ServerIn`, `ServerPatch`, `ServerOut`, `ConnectionSettings`, and the rules for names, addresses and tags |
| | `servers.py` (new) | List, read, create, update, delete, the tags in use, and the events of each change |
| | `deps.py` (new) | The group of a request: `group_of_server` (loads the server from the path, 404 when it does not exist), `group_of_new_server` (the body's `group_id`) and `target_group_of_server` (the body's `group_id`, or the server's own group when the body has none) |
| | `server_router.py` (new) | The routes under `/api/servers` and `/api/server-tags` |
| | `actions.py` | The five `server.*` action names |
| | `service.py`, `schemas.py` | A group gains `server_count` and `can_manage`. Deleting a group that holds servers is refused |
| `app/` | `main.py` | Includes the new router |

How a change is checked: `POST` uses `require_group_admin(group=group_of_new_server)`. `PATCH` uses two guards, one for the server's own group and one for `target_group_of_server`, so a move needs Admin on both. `DELETE` uses the server's own group. `GET /api/servers/{id}` uses the existing `require_group_visible(group=group_of_server)`.

One point for the plan: `group_of_new_server` and the handler both read the request body. The plan checks how FastAPI treats that, and if it changes the body's shape, the handler takes the validated body from the dependency instead.

### Frontend

| File | Purpose |
|---|---|
| `src/app/(app)/servers/page.tsx` | Renders `ServersPage` in place of the placeholder |
| `src/app/(app)/servers/[serverId]/page.tsx` | Renders `ServerPage`. The header keeps the title "Servers" |
| `src/components/servers/servers-page.tsx` | The list card, the three empty states, and the Register button when a group has `can_manage` |
| `src/components/servers/server-filters.tsx` | The Group select and the tag chips, read from and written to `/servers?group=…&tag=…` |
| `src/components/servers/server-dialog.tsx` | Register and Edit. The port follows the operating system until it is edited. Choosing another group shows what a move means. Save stays disabled until something differs |
| `src/components/servers/tag-input.tsx` | Chips with an input: Enter or comma adds a tag, × removes it, tags in use are suggested |
| `src/components/servers/remove-server-dialog.tsx` | The confirmation |
| `src/components/servers/server-page.tsx` | The title row, the Overview tab, the Connection and Details cards, and a "does not exist, or you cannot see it" card for a 404 |
| `src/lib/servers.ts` | Types and pure helpers: the default port of an operating system, tag clean-up, whether two servers differ, filters to and from the address |
| `src/lib/access.ts` | `ServerGroup` gains `server_count` and `can_manage` |
| `src/components/settings/groups-page.tsx`, `delete-group-dialog.tsx`, `group-dialog.tsx` | A Servers column. Delete shows the refusal of screen 8 with a link to `/servers?group=<id>`. The dialog text no longer says "later" |
| `src/lib/auth/messages.ts` | Texts for `server_name_taken`, `group_has_servers` and `not_found`. `forbidden` becomes "You do not have the rights to do this", because it is no longer only about the Owner |

Under 768 px the table scrolls sideways in its card and the dialog's field pairs stack, as in the mockup.

### Docs

`README.md` gets a short "Servers" paragraph: who registers, one group per server, tags, and that the host key comes with SSH connect.

## Data and interfaces

### Migration `0006_servers`

**`servers`**

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | Primary key |
| `server_group_id` | uuid | FK to `server_groups`, no cascade: a group with servers cannot be deleted |
| `name` | text | 1 to 64 of letters, digits, `.`, `-`, `_`, starting with a letter or digit. Unique index on `lower(name)` |
| `address` | text | An IPv4 or IPv6 address, or a host name of at most 253 characters, stored in lowercase |
| `port` | integer | Check 1 to 65535 |
| `os` | text | Check `linux` or `windows` |
| `role` | text, null | What the server does, at most 64 characters. Empty is stored as null |
| `host_key` | text, null | Empty in this task. MITA-11 writes it |
| `connection_settings` | jsonb | `{"username": "megoo"}`. The username is 1 to 64 characters without spaces |
| `created_at`, `updated_at` | timestamptz | |

Index on `server_group_id`.

**`server_tags`**: `server_id` (FK to `servers`, cascade) and `tag`, primary key on both, index on `tag`. A tag is lowercase, 1 to 32 of `a-z`, digits, `.`, `-`, `_`, starting with a letter or digit, and the database checks the case and length. A server carries at most 20 tags. The request's tags are trimmed, lowercased and deduplicated.

`megooitadmin_api` gets SELECT, INSERT, UPDATE and DELETE on both tables, and both join `API_GRANTS`.

### Routes

| Route | Who | Does | Audit events |
|---|---|---|---|
| `GET /api/servers?group_id=…&tag=…` | signed in | The servers of the groups the person sees, by name. `tag` may repeat, and a server must carry all of them. A `group_id` the person does not see gives an empty list | none |
| `GET /api/servers/{server_id}` | sees its group | One server | none |
| `POST /api/servers` | Owner, or Admin of the body's group | Registers the server. 409 `server_name_taken` | `server.created` |
| `PATCH /api/servers/{server_id}` | Owner, or Admin of its group, and of the new group on a move | Changes the fields sent. 409 `server_name_taken`, 409 `no_change` | `server.changed`, `server.moved`, `server.tags_changed` |
| `DELETE /api/servers/{server_id}` | Owner, or Admin of its group | Deletes the server and its tags. 204 | `server.deleted` |
| `GET /api/server-tags` | signed in | The tags in use on the servers the person sees, sorted | none |
| `GET /api/server-groups` | as today | Each group gains `server_count` and `can_manage` | none |
| `DELETE /api/server-groups/{group_id}` | Owner | 409 `group_has_servers` when the group holds a server | as today |

A server in a response holds: `id`, `name`, `address`, `port`, `os`, `role`, `tags` (sorted), `group_id`, `group_name`, `connection_settings`, `host_key`, `created_at`, `updated_at` and `can_manage`.

### Audit events

Every event has the server as its target (`type="server"`, its ID and its name as it is now) and `context={"server_group_id": …}`, so a later Audit page can show an Admin the events of their groups.

| Action | `change` |
|---|---|
| `server.created` | Every field with `before: null`: name, address, port, os, role, connection settings, group name and tags |
| `server.changed` | The fields that differ among name, address, port, os, role and connection settings |
| `server.moved` | `{"group": {"before": "staging", "after": "production"}}`, with both group IDs in `result_detail`. The context holds the new group |
| `server.tags_changed` | `{"tags": {"before": […], "after": […]}}` |
| `server.deleted` | Every field with `after: null` |
| `access.denied` | As today, with `required` set to `admin` or `group` |

## Error handling and edge cases

- **A group is deleted while a server is being registered into it.** The foreign key makes the two take turns. Either the delete is refused with `group_has_servers`, or the registration answers 422 `unknown_group` and the dialog reloads the groups.
- **A move into a group that does not exist.** For an Admin it answers 404 like any group they cannot see. For an Owner it answers 422 `unknown_group`.
- **Two people register the same name at once.** The unique index decides, and the loser gets 409 `server_name_taken`.
- **Two people edit the same server.** The row is locked during a save and the last save wins. Each event shows what that save changed from what was stored at that moment.
- **An Admin loses the role while the dialog is open.** Rights are read on every request, so the save answers 403 or 404, and the page reloads the list.
- **A server page of a server removed or moved out of sight.** The page shows the "does not exist, or you cannot see it" card with a link back to the list.
- **A filter in the address names a group or tag that is gone.** The list is empty and offers Clear filters.
- **A person with a role whose seven switches are all off** still sees the group's servers (MITA-9, decision 8).
- **The denial cannot be recorded.** The request answers 500, as with every other guard.

## Testing

Tests are written first. Backend tests run with `megoocolab-runner services run test -- uv run pytest`.

**`tests/access/`**
- `manages`: true for an Owner everywhere, true for an Admin in their group only, false for an Operator and an Auditor.
- `require_group_admin` on a throwaway app: 404 for a group the person does not see, 403 for an Operator of the group, and one `access.denied` event each.

**`tests/inventory/`**
- **The task's sentence:** the Owner registers one server into staging and one into production. A staging-only Admin's list holds the staging server only, and the production server's own route answers 404 to them. An Owner and an Auditor get both.
- Register: an Admin registers into their own group, is refused with 403 in a group where they are Operator and with 404 in a group they do not see. An Auditor is refused.
- Rules: names clash without regard to case and across groups, a bad name, address, port, operating system or tag gets 422, tags come back lowercase, deduplicated and sorted.
- Edit: each kind of difference gives its event with the right before and after, one save with all three gives three events, and no difference gives 409.
- Move: needs Admin on both groups, and afterwards the server is seen by the new group's people only.
- Remove: deletes the tags too and records every field.
- Filters: by group, by one tag, by two tags, and a group the person does not see gives an empty list.
- `GET /api/server-tags` holds only the tags of the servers the person sees.
- Groups: `server_count` and `can_manage` per person, and deleting a group with a server answers 409 and keeps the group and its roles.

**Security suites** (`make test-security`)
- `test_permission_coverage.py`: `ANY_SIGNED_IN` gains `GET /api/servers` and `GET /api/server-tags`, which filter by themselves. `access_requirement` reports `admin` for the new guard.
- `test_access_events.py`: the walk also registers, edits, tags, moves and removes a server and has a refused change, and expects each `server.*` action.
- `test_db_privileges.py`: the two new tables.

**Other backend tests**
- `test_migrations.py`: `0006` goes down and up, the models match, and the database refuses an uppercase tag and a port of 0.
- `test_stack.py` (`-m stack`): through Caddy, the Owner registers a server into each of two groups, and the staging-only Admin gets one of them and a 404 for the other.

**Frontend** (Vitest)
- `servers.ts`: the default port per operating system, tag clean-up, the difference check, filters to and from the address.
- Servers page: the rows, the menus only where `can_manage` is true, no Register button for an Operator or Auditor, the three empty states, and the filters changing the address and the request.
- Server dialog: register sends the fields, the port follows the operating system until it is edited, the move notice appears, Save is disabled until something differs, and a taken name shows its message.
- Tag input: Enter and comma add, × removes, a duplicate is ignored.
- Remove dialog, and the server page with its two cards and its 404 card.
- Groups page: the Servers column, and the refusal dialog for a group with servers.
- Image check (`web` set): `/servers/<id>` without the cookie redirects to `/login`, and with it serves the shell.

Done when `make test` and `make test-security` pass, and by hand on `make up STACK=dev`: create staging and production, invite a person as Admin on staging only, register a server into each group as the Owner, and see in a private window that the person gets only the staging server, can edit it, and cannot open the production one.

## Out of scope

- Connecting to a server, fetching and pinning the host key, and the Connect button: MITA-11.
- The connection credential (SSH key or RDP password) and the vault: MITA-11's stopgap key and Phase 3.
- Server status, metrics and the Processes, Performance, Services, Containers, Logs and Audit tabs: their own phases.
- The Run playbook button, and jobs or playbooks that target groups or tags: Phase 7.
- Indexing servers for the global search (`search_outbox`): Phase 6.
- A name search box, paging, bulk actions, importing servers from a file, and archiving a removed server.
- Renaming or deleting a tag across servers, tag colours, and a managed list of tags.
- The per-group policy switches of PRD §6.3, and hiding sidebar items by role.
