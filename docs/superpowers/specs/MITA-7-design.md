# MITA-7 design: audit log event model and transactional, hash-chained writer

## Goal

After this task the backend has an `audit_log` hypertable and one module that writes events to it in the same transaction as the action, each event chained to the one before by SHA-256. A chain check finds a changed or removed row, a trigger refuses UPDATE, DELETE and TRUNCATE, and every state-changing route must declare and write its audit events or the request is rolled back.

## What the repository looks like today

- `backend/` has one route, `GET /api/health`, no model and one migration (`0001_initial`, the extensions). `app/models.py` says "MITA-7 adds the first".
- `get_session` commits after the handler and rolls back when it raises. No route uses it yet.
- The backend connects as `megooitadmin`, the database superuser.
- `make test-security` exits with "the security suites are not in the repository yet", and `tests/test_makefile.py` expects that message.
- Sign-in, users and roles, the server inventory and SSH connect do not exist yet. They come in later tasks of this sprint.

## Decisions

Answers from the owner:

1. **Restricted database roles are a follow-up task.** This task adds the trigger and the hash chain. The backend keeps its superuser connection until the follow-up, so until then the trigger is the only barrier against the backend's own connection, and the chain check is what detects a change. Rejected: doing the roles here (touches the Compose stack, the Makefile and the test services), and creating a role without login now.
2. **The hash chain is computed in the Python writer.** The chain check is Python too, so Phase 8's nightly job, Verify button and signed exports reuse it, and an export can be checked outside the database. Rejected: a `BEFORE INSERT` trigger that computes the hashes (the logic would live in PL/pgSQL, and checking outside the database would mean rebuilding PostgreSQL's text format), and computing in Python with a second check in a trigger.
3. **Routes declare their audit actions, and a guard enforces them.** A state-changing route names its actions with `audited("server.created")`. A request that ends without writing one of them is rolled back and answered with 500. The coverage test fails for a state-changing route without a declaration. Rejected: a test scenario per route with no check at run time, and both together.

Decisions I made (say so if you want them changed):

4. **"Done when" for this task.** The sprint's actions (sign-in, user and role changes, server register, host key pin, SSH connect) are built by later tasks, so they cannot produce events here. This task is done when an event written through the writer commits and rolls back with its transaction, events are chained, the tamper test makes the chain check fail, and the guard and the coverage test are in place. Each later task then declares its actions and calls the writer. The coverage test fails if one forgets.
5. **A one-row table `audit_chain_head` holds the number and hash of the newest event.** The writer locks that row (`SELECT … FOR UPDATE`), so writers take turns, numbers have no gaps, and the head is found without scanning the hypertable. It also lets the chain check notice that the newest rows were removed, which a chain alone cannot. Rejected: an advisory lock plus "newest row by time" (no protection for the tail), and a sequence (gaps after a rollback).
6. **The hash covers one canonical JSON document per event:** every field, the number, the time and the previous hash, with keys sorted, no spaces, UTF-8. A field that is `NULL` is left out, so a nullable column added later does not change the hash of older events. JSON values may be strings, integers, booleans, null, lists and objects. A float is refused, because PostgreSQL may write it back differently.
7. **No foreign keys on `audit_log`.** An event stores the ID and the name as they were at that moment, as text, so it survives the deletion of the user or server it names.
8. **Common filters are columns, the rest is JSONB.** Actor, action, target, result, risk class and the source are columns. Agent details, context IDs, the change and the result's details are JSONB. Only the primary key and the time index are created. The Audit page (Phase 4) adds the indexes its filters need.
9. **`record_alone` writes one event in its own transaction.** A refused action (failed sign-in, permission denial) raises, and the request's transaction rolls back, which would take the event with it. `record_alone` is for exactly those events.
10. **`DbSession` gets `scope="function"`.** FastAPI runs the exit code of a `yield` dependency after the response is sent unless the scope is `function` (FastAPI docs, since 0.121). With it, the commit and the guard run before the response, so a failed commit or a missing audit event gives a 500 and not a 200 for something that was not saved.
11. **The client address comes from `request.client.host`.** Uvicorn already sets it from `X-Forwarded-For` (`--proxy-headers`, MITA-5), and Caddy is the only service that reaches the backend. Parsing the header again in the app would be a second place to get it wrong.
12. **`changes(before, after)` builds the change diff** and replaces the values of secret fields with `[redacted]`: the fields the caller names, and any field whose name contains `password`, `secret` or `token`.
13. **`make test-security` runs `backend/tests/security`.** The same tests also run in the normal backend check, because they sit under `tests/`.
14. **No retention or compression policy yet.** The PRD's default is 2 years with compression. Dropping old chunks removes the start of the chain, so the chain check already accepts a starting point, but the policies themselves are left out (see Out of scope).

## Architecture

```text
backend/app/audit/
  __init__.py      exports the names below
  models.py        AuditEvent (audit_log), AuditChainHead (audit_chain_head)
  events.py        Event, Actor, Person, Target, Source, the enums, changes()
  chain.py         canonical(), event_hash(), GENESIS, verify_chain(), ChainReport
  writer.py        record(), record_alone(), AuditChainBusy
  http.py          audited(), source_of(), AuditMissing
backend/app/models.py                         imports app.audit.models
backend/app/core/db.py                        DbSession with scope="function"
backend/migrations/versions/0002_audit_log.py tables, hypertable, triggers
backend/tests/audit/                          test_chain.py, test_events.py, test_writer.py, test_http.py
backend/tests/security/                       routes.py, test_audit_coverage.py, test_audit_tamper.py
backend/tests/conftest.py                     fixture empty_audit_log
backend/tests/test_migrations.py              0002 down and up, models match migrations
backend/tests/test_makefile.py                test-security runs the suite
Makefile                                      test-security
AGENTS.md                                     Checks: the Security suites line
```

How the pieces connect:

- **`events.py`** holds frozen Pydantic models. They validate what goes into an event (the action name, the JSON values) before anything touches the database.
- **`chain.py`** is pure except for `verify_chain`: it turns an event into its canonical bytes and its hash. The writer and the chain check both use it, so they cannot disagree.
- **`writer.record(session, event)`** runs inside the caller's transaction and never commits:
  1. Lock the head row. The wait is limited to 5 seconds.
  2. Take the time: now in UTC, cut to milliseconds, and never earlier than the head's time, so time order and chain order agree.
  3. Compute the hash from the head's hash and the event.
  4. Insert the event with the next number, update the head, flush.
  5. Add the action to `session.info["audit_actions"]` for the guard.
- **`http.audited(*actions)`** returns a dependency for a route's `dependencies=[…]`. It depends on `DbSession`, so it ends before the session does. When the handler returned normally and none of the declared actions is in `session.info["audit_actions"]`, it raises `AuditMissing`. `get_session` then rolls back, and the caller gets a 500. When the handler raised, the guard checks nothing: the transaction rolls back anyway.
- **`http.source_of(request, auth_method=None, mfa=None)`** builds the `Source` of an event. Login (MITA-8) passes the sign-in method and whether a second factor was used.

How a later task uses it:

```python
@router.post("/servers", dependencies=[audited("server.created")])
async def create_server(body: ServerIn, request: Request, session: DbSession, user: CurrentUser):
    server = Server(**body.model_dump())
    session.add(server)
    await session.flush()
    # Last in the transaction: the chain lock is held until the commit.
    await record(session, Event(
        action="server.created",
        actor=Actor.human(user.id, user.name),
        target=Target(type="server", id=str(server.id), name=server.name),
        source=source_of(request, auth_method=user.auth_method, mfa=user.mfa),
    ))
    return server
```

## Data and interfaces

### `audit_log` (hypertable on `time`, chunks of 30 days)

| Column | Type | Notes |
|---|---|---|
| `seq` | `bigint`, not null | Position in the chain, from 1, no gaps |
| `time` | `timestamptz`, not null | UTC, milliseconds |
| `actor_type` | `text`, not null | `human`, `agent` or `system` (check) |
| `actor_id` | `text` | User ID, agent session ID, or null for the platform |
| `actor_name` | `text`, not null | Name at that moment: user name, agent profile, or the component (`scheduler`, `collector`, `executor`) |
| `actor_details` | `jsonb`, not null, default `{}` | For an agent: session, profile, model |
| `on_behalf_of_id`, `on_behalf_of_name` | `text` | The person who started the agent session, playbook run or job |
| `action` | `text`, not null | Dotted, lower case: `server.created`, `auth.sign_in_failed` (check: at least two parts of `a-z`, `0-9`, `_`) |
| `target_type`, `target_id`, `target_name` | `text` | `server`, `user`, `secret`, `file`, … with its ID and name |
| `context` | `jsonb`, not null, default `{}` | IDs that tie events together, as strings: `agent_session_id`, `playbook_run_id`, `cron_run_id`, `remote_session_id`, `approval_id`, `alert_id`, `server_id` |
| `source_ip` | `inet` | Client address |
| `user_agent` | `text` | Cut to 1,024 characters |
| `auth_method` | `text` | `password`, `oidc`, … (set by MITA-8) |
| `mfa` | `boolean` | Whether a second factor was used |
| `reason` | `text` | Typed by the person, or the agent's stated reason |
| `change` | `jsonb` | `{"field": {"before": …, "after": …}}`, secrets redacted |
| `result` | `text`, not null | `success`, `failure` or `error` (check) |
| `result_detail` | `jsonb` | For example `{"exit_code": 1}` or `{"error": "…"}` |
| `risk_class` | `text` | `platform_read`, `server_read`, `change`, `destructive`, `forbidden` (check), PRD §8.4 |
| `prev_hash` | `bytea`, not null | 32 bytes. 32 zero bytes for the first event |
| `hash` | `bytea`, not null | 32 bytes |

- Primary key `(seq, time)`: a unique index on a hypertable must include the partitioning column. That `seq` alone is unique is guaranteed by the head lock and checked by the chain check.
- Index `audit_log_time_idx` on `time DESC`, declared on the model. `create_hypertable` is called with `create_default_indexes => false`, so the model and the database hold the same indexes and autogenerate stays quiet.

### `audit_chain_head`

`id smallint` primary key with check `id = 1`, `seq bigint not null`, `hash bytea not null`, `time timestamptz`. The migration inserts the one row: `(1, 0, 32 zero bytes, null)`.

### Migration `0002_audit_log`

- `upgrade`: create both tables, turn `audit_log` into a hypertable (`create_hypertable('audit_log', by_range('time', INTERVAL '30 days'), create_default_indexes => false)`), insert the head row, create the function `audit_refuse_change()` that raises `audit_log is append-only`, and the triggers:
  - `audit_log`: `BEFORE UPDATE OR DELETE … FOR EACH ROW` and `BEFORE TRUNCATE … FOR EACH STATEMENT`.
  - `audit_chain_head`: `BEFORE DELETE … FOR EACH ROW` and `BEFORE TRUNCATE … FOR EACH STATEMENT`. UPDATE stays allowed: the writer needs it.
- `downgrade`: drop both tables and the function.

### The hash

```text
document = { "seq", "time" ("2026-11-23T07:45:31.362Z"), "prev_hash" (hex), and every event column that is not NULL }
hash     = SHA-256( canonical(document) )
canonical = JSON with sorted keys, separators "," and ":", no ASCII escaping, encoded as UTF-8
```

`source_ip` enters the document in its canonical text form. `hash` itself is not part of the document.

### Python interface (`app.audit`)

```python
class Actor:   type, id, name, details      # Actor.human(id, name), Actor.agent(session_id, profile, model), Actor.system(component)
class Person:  id, name                     # on behalf of
class Target:  type, id, name
class Source:  ip, user_agent, auth_method, mfa
class Event:   action, actor, result=Result.SUCCESS, target=None, on_behalf_of=None, context={},
               source=None, reason=None, change=None, result_detail=None, risk_class=None

async def record(session: AsyncSession, event: Event) -> AuditEvent
async def record_alone(event: Event) -> AuditEvent
def changes(before: Mapping, after: Mapping, *, secret: Collection[str] = ()) -> dict | None
async def verify_chain(session: AsyncSession, *, from_seq: int = 1) -> ChainReport
def audited(*actions: str) -> Depends
def source_of(request: Request, *, auth_method: str | None = None, mfa: bool | None = None) -> Source
```

`ChainReport` holds `ok`, `checked` (number of events), `head_seq`, and for the first problem found `broken_at` (the number) and `problem`:

| `problem` | Meaning |
|---|---|
| `hash_mismatch` | The stored hash is not the hash of the row's content: the row was changed |
| `broken_link` | `prev_hash` is not the hash of the event before: a row was replaced or re-hashed |
| `missing` | A number is absent: a row was removed |
| `head_mismatch` | The newest row is not the one the head names: the newest rows were removed, or the head was changed |

`verify_chain` reads the head first, then the events up to the head's number in batches ordered by `seq`, so events written during the check do not disturb it. With `from_seq` above 1 it takes the hash of the event before as the starting point, or the first event's own `prev_hash` when that event no longer exists.

### `Makefile` and `AGENTS.md`

```make
test-security:
	$(REQUIRE_RUNNER)
	cd backend && $(RUNNER) services run test -- uv run pytest tests/security
```

The Security suites line in `AGENTS.md` becomes: "`make test-security`. It runs the audit-coverage and audit-tamper suites. The secret-leak and approval-bypass suites join it with Phases 3 and 4."

## Error handling and edge cases

- **The action fails after its event was written.** Both are in one transaction, so both roll back. The head row rolls back too, and the next event takes the same number.
- **The event cannot be written** (invalid event, database error). `record` raises, and the action rolls back with it.
- **A refused action.** The handler calls `record_alone` and then raises. Call it before anything was recorded in the request's own transaction: that transaction would hold the head lock, and `record_alone` would wait for it.
- **Two writers at once.** The second waits on the head row and continues after the first commits or rolls back. Under the default isolation level it then reads the new head.
- **A transaction holds the head lock too long.** A writer waits at most 5 seconds, then `record` raises `AuditChainBusy` and its action rolls back. Record the event last in the transaction, and never await a slow call (SSH, HTTP) between `record` and the commit.
- **The clock goes backwards.** The event takes the head's time, so times never decrease along the chain.
- **A float, or a value that is not JSON, in `context`, `change`, `actor_details` or `result_detail`.** `Event` refuses it with a validation error before any database work.
- **A route forgets its event.** The guard raises `AuditMissing`, nothing is committed, and the caller gets a 500. The route's own tests see this at once.
- **A route with POST, PUT, PATCH or DELETE that needs no event.** It must be listed with a reason in `EXEMPT` in `tests/security/test_audit_coverage.py`, so an exemption is a visible change to the security suite. The list starts empty.
- **A WebSocket route or a mounted sub-app.** The guard is built for HTTP routes. The coverage test fails when one appears and says to extend the test, so it cannot go unchecked silently.
- **UPDATE, DELETE or TRUNCATE on `audit_log`.** The trigger raises. A superuser can still switch triggers off or drop chunks. The chain check finds a changed or removed row, and the follow-up task takes the superuser away from the backend.
- **Someone rewrites the whole chain and the head.** Nothing inside the database can detect that. Streaming to an external SIEM (Phase 8) is the answer to it.
- **No request** (a test, a worker). `source_of` is not used, and `source` stays empty.
- **`0001` must still go down.** `0002`'s downgrade drops the hypertable before `0001` drops the extension. The existing test walks down to `0001` and proves it.

## Testing

Tests are written first. Names read as sentences. All run with `megoocolab-runner services run test -- uv run pytest`. The fixture `empty_audit_log` empties both audit tables before a test, with the triggers switched off for its own transaction, because the tables cannot be cleaned any other way.

**`tests/audit/test_chain.py`** (no database)
- The canonical form sorts keys, leaves out null fields and keeps non-ASCII text as UTF-8.
- A fixed event gives a fixed hash (a known answer), so the format cannot change by accident.
- A float is refused.

**`tests/audit/test_events.py`**
- An action without a dot, or with upper case, is refused.
- `changes` lists only the fields that differ, redacts named and password-like fields, and returns `None` when nothing differs.

**`tests/audit/test_writer.py`**
- The first event has number 1 and the zero hash as `prev_hash`. The second links to the first.
- Every field comes back from the database as it was written, and the time has milliseconds.
- An event recorded in a transaction that rolls back leaves no row and an unchanged head.
- Twenty events recorded at the same time from separate sessions get the numbers 1 to 20, and the chain check passes.
- `record_alone` commits its event although the caller's transaction rolls back.
- A writer that cannot get the head lock raises `AuditChainBusy`.

**`tests/audit/test_http.py`** (a throwaway FastAPI app built in the test)
- A route that records its declared action commits the action and the event, and answers 200.
- A route that records nothing answers 500, and nothing is committed.
- A route that raises is rolled back and keeps its own status code.
- `source_of` takes the address from `request.client` and the user agent from the header.

**`tests/security/test_audit_coverage.py`**
- Every route of the real app with POST, PUT, PATCH or DELETE declares its actions with `audited`, or is listed in `EXEMPT`.
- The app holds no kind of route the check does not understand (WebSocket, mount).
- The check itself reports an undeclared POST route of a sample app, so the test can fail.

**`tests/security/test_audit_tamper.py`**
- UPDATE, DELETE and TRUNCATE on `audit_log` are refused, and so are DELETE and TRUNCATE on `audit_chain_head`.
- An untouched chain passes the check.
- With the triggers switched off as a superuser could (`SET LOCAL session_replication_role = replica`):
  - a changed field gives `hash_mismatch` at that number;
  - a removed middle row gives `missing` at that number;
  - a removed newest row gives `head_mismatch`;
  - a row rewritten together with its own hash gives `broken_link` at the next number.

**`tests/test_migrations.py`**
- After `upgrade head`, `audit_log` is a hypertable and the head row exists.
- `0002` goes down (both tables gone) and up again.
- The models match the migrations: `alembic check` finds nothing to generate.

**`tests/test_makefile.py`**: `make -n test-security` prints the pytest command for `tests/security`. The test for the "not in the repository yet" message is replaced.

**By hand in the build:** the down-and-up command of `AGENTS.md` on the `migrate` set.

## Out of scope

- The restricted database roles and the backend's connection through one: the follow-up task below.
- Events for sign-in, users and roles, servers, host keys and SSH connect: the tasks that build those actions.
- The nightly chain check, the Verify button, the alert on a broken chain, auditing the check itself, the outbox and SIEM streaming, signed exports: Phase 8 (MITA-74).
- The Audit page, its filters, indexes and API, and `audit_saved_views`: Phase 4.
- Retention and compression policies on `audit_log`. No task tracks them yet: add one at review if you want it now.
- A guard for WebSocket routes and for background actions of the workers. The coverage test fails when the first WebSocket route appears. The workers do not exist yet.
- A keyed hash (HMAC). The PRD asks for a plain hash chain, and the vault that would hold a key comes in Phase 3.
- The secret-leak and approval-bypass suites: Phases 3 and 4.
