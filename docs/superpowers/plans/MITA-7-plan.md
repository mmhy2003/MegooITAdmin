# MITA-7 plan: audit log event model and transactional, hash-chained writer

## Goal

Give the backend an append-only `audit_log` hypertable and one package, `app.audit`, that writes SHA-256-chained events in the caller's transaction, checks the chain, and makes every state-changing route declare and write its events.

## Architecture

`app/audit/events.py` validates an event with frozen Pydantic models and turns it into column values. `chain.py` turns those columns plus the number, time and previous hash into canonical JSON bytes and a hash. The writer (`writer.py`) and the chain check (`verify_chain`, in `chain.py`) both use these, so they cannot disagree. The writer locks the one-row `audit_chain_head` to number events without gaps. `http.py` holds the route guard `audited(...)`. It runs as a `scope="function"` dependency inside `DbSession`, so a missing event raises before the commit and the request rolls back with a 500.

## Conventions every step follows

- Run every command from `backend/`. Run DB tests as `megoocolab-runner services run test -- uv run pytest <paths> -q`. The whole backend suite is `megoocolab-runner services run test -- uv run pytest`.
- Write the test first, run it, and see it fail for the stated reason. Then implement and run it again.
- `tests/` has no `__init__.py` (pytest "prepend" import mode). New test file basenames must be unique, and they are.
- Commits: `type(area): sentence`, a body that says why, and the last line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never commit `.megoocolab/` or `docs/` plan files.
- `app/audit/__init__.py` re-exports the public names. Each step adds its own names to `__all__`, so the package imports at every step.

## File map

| File | Status | Responsibility |
|---|---|---|
| `backend/app/audit/__init__.py` | new | Re-exports the public names |
| `backend/app/audit/events.py` | new | Enums, `Actor`, `Person`, `Target`, `Source`, `Event`, `Event.columns()`, `check_json`, `changes` |
| `backend/app/audit/chain.py` | new | `GENESIS`, `canonical`, `document`, `event_hash`, `Problem`, `ChainReport`, `verify_chain` |
| `backend/app/audit/models.py` | new | ORM `AuditEvent` (`audit_log`), `AuditChainHead` (`audit_chain_head`), `CHAINED_COLUMNS` |
| `backend/app/audit/writer.py` | new | `record`, `record_alone`, `AuditChainBusy`, `AUDIT_ACTIONS`, `LOCK_TIMEOUT` |
| `backend/app/audit/http.py` | new | `audited`, `source_of`, `AuditMissing` |
| `backend/app/models.py` | modify | Imports `app.audit.models`. Docstring updated |
| `backend/app/core/db.py` | modify | `DbSession` uses `Depends(get_session, scope="function")` |
| `backend/migrations/versions/0002_audit_log.py` | new | Tables, hypertable, head row, function, triggers |
| `backend/tests/conftest.py` | modify | Fixtures `database_at_head` (session) and `empty_audit_log` |
| `backend/tests/audit/test_events.py`, `test_chain.py`, `test_writer.py`, `test_http.py` | new | Unit and DB tests |
| `backend/tests/security/routes.py` | new | Route inspection helpers for the coverage check |
| `backend/tests/security/test_audit_coverage.py` | new | Coverage suite with `EXEMPT = {}` |
| `backend/tests/security/test_audit_tamper.py` | new | Trigger refusals and tamper detection |
| `backend/tests/test_db.py` | modify | `DbSession` has function scope |
| `backend/tests/test_migrations.py` | modify | Hypertable, head row, 0002 down/up, `alembic check` |
| `backend/tests/test_makefile.py` | modify | `test-security` runs `tests/security` |
| `Makefile` | modify | `test-security` target |
| `AGENTS.md` | modify | Security suites line |

## Contracts

### C1. `app/audit/events.py`

```python
ACTION_PATTERN = r"^[a-z0-9_]+(\.[a-z0-9_]+)+$"
USER_AGENT_MAX = 1024
REDACTED = "[redacted]"
SECRET_HINTS = ("password", "secret", "token")

class ActorType(StrEnum):  HUMAN = "human"; AGENT = "agent"; SYSTEM = "system"
class Result(StrEnum):     SUCCESS = "success"; FAILURE = "failure"; ERROR = "error"
class RiskClass(StrEnum):  PLATFORM_READ = "platform_read"; SERVER_READ = "server_read"; CHANGE = "change"
                           DESTRUCTIVE = "destructive"; FORBIDDEN = "forbidden"

class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

class Actor(_Frozen):
    type: ActorType
    id: str | None = None
    name: str = Field(min_length=1)
    details: dict[str, Any] = {}          # validated by check_json
    @classmethod human(cls, id: object, name: str) -> Actor         # type=HUMAN, id=str(id)
    @classmethod agent(cls, session_id: object, profile: str, model: str) -> Actor
        # type=AGENT, id=str(session_id), name=profile,
        # details={"session": str(session_id), "profile": profile, "model": model}
    @classmethod system(cls, component: str) -> Actor               # type=SYSTEM, id=None, name=component

class Person(_Frozen):  id: str; name: str
class Target(_Frozen):  type: str = Field(min_length=1); id: str | None = None; name: str | None = None
class Source(_Frozen):
    ip: str | None = None            # validator: str(ipaddress.ip_address(v)), so ValueError on junk
    user_agent: str | None = None    # validator: v[:USER_AGENT_MAX]
    auth_method: str | None = None
    mfa: bool | None = None

class Event(_Frozen):
    action: str = Field(pattern=ACTION_PATTERN)
    actor: Actor
    result: Result = Result.SUCCESS
    target: Target | None = None
    on_behalf_of: Person | None = None
    context: dict[str, str] = {}
    source: Source | None = None
    reason: str | None = None
    change: dict[str, Any] | None = None          # check_json
    result_detail: dict[str, Any] | None = None   # check_json
    risk_class: RiskClass | None = None
    def columns(self) -> dict[str, Any]: ...      # exactly the 20 keys of CHAINED_COLUMNS, see below

def check_json(value: Any) -> Any
    # Walks the value. Allows str, int, bool, None, list and dict with str keys. Raises ValueError
    # ("audit values must be JSON without floats") for a float or any other type. Returns the value unchanged.

def changes(before: Mapping[str, Any], after: Mapping[str, Any], *, secret: Collection[str] = ()) -> dict | None
    # For each key of before | after, in sorted order, where before.get(k) != after.get(k):
    #   {k: {"before": before.get(k), "after": after.get(k)}}, with both values replaced by REDACTED
    #   when k is in `secret` or any SECRET_HINT is in k.lower(). Returns None when nothing differs.
```

`Event.columns()` returns these keys. Enums become `.value`, and an absent object gives `None`:

```text
actor_type, actor_id, actor_name, actor_details, on_behalf_of_id, on_behalf_of_name, action,
target_type, target_id, target_name, context, source_ip, user_agent, auth_method, mfa,
reason, change, result, result_detail, risk_class
```

### C2. `app/audit/chain.py` (pure part)

```python
GENESIS = bytes(32)

def time_text(time: datetime) -> str
    # time.astimezone(UTC), formatted "%Y-%m-%dT%H:%M:%S.mmmZ" (isoformat(timespec="milliseconds"), "+00:00" -> "Z")

def document(seq: int, time: datetime, prev_hash: bytes, columns: Mapping[str, Any]) -> dict[str, Any]
    # {"seq": seq, "time": time_text(time), "prev_hash": prev_hash.hex()} plus every column whose value
    # is not None. source_ip becomes str(ipaddress.ip_interface(str(v)).ip) so an IPv4Address or str from
    # asyncpg gives the same text. Only the top level drops None. Nested JSON nulls stay.

def canonical(doc: Mapping[str, Any]) -> bytes
    # json.dumps(check_json(doc), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()

def event_hash(seq: int, time: datetime, prev_hash: bytes, columns: Mapping[str, Any]) -> bytes
    # hashlib.sha256(canonical(document(...))).digest()
```

Known answer, which the test pins: `seq=1`, `time=datetime(2026, 11, 23, 7, 45, 31, 362000, tzinfo=UTC)`, `prev_hash=GENESIS`, columns `{"action": "server.created", "actor_type": "human", "actor_id": "7", "actor_name": "Zoë", "actor_details": {}, "context": {}, "result": "success", "source_ip": "203.0.113.9", "reason": None}` give exactly these canonical bytes (UTF-8):

```text
{"action":"server.created","actor_details":{},"actor_id":"7","actor_name":"Zoë","actor_type":"human","context":{},"prev_hash":"0000000000000000000000000000000000000000000000000000000000000000","result":"success","seq":1,"source_ip":"203.0.113.9","time":"2026-11-23T07:45:31.362Z"}
```

The test also pins `event_hash(...).hex()` as a literal. Compute it once with `uv run python -c` on hashlib.sha256 of the literal above, and paste the hex into the test.

### C3. ORM models (`app/audit/models.py`)

`AuditEvent(Base)`, `__tablename__ = "audit_log"`, with the columns of the design table: `seq` `BigInteger` and `time` `DateTime(timezone=True)` together as the primary key; `actor_details` and `context` as `JSONB`, `nullable=False`, `server_default=text("'{}'::jsonb")`; `change` and `result_detail` as nullable `JSONB`; `source_ip` as `postgresql.INET`; `mfa` as `Boolean`; `prev_hash` and `hash` as `LargeBinary`, not null; the rest `Text`. `__table_args__` holds these check constraints:

- `audit_log_actor_type_check`: `actor_type IN ('human', 'agent', 'system')`
- `audit_log_action_check`: `action ~ '^[a-z0-9_]+(\.[a-z0-9_]+)+$'`, written as a Python raw string
- `audit_log_result_check`: `result IN ('success', 'failure', 'error')`
- `audit_log_risk_class_check`: `risk_class IN ('platform_read', 'server_read', 'change', 'destructive', 'forbidden')`
- `audit_log_hash_length_check`: `octet_length(prev_hash) = 32 AND octet_length(hash) = 32`

After the class, `Index("audit_log_time_idx", AuditEvent.time.desc())`.

`AuditChainHead(Base)`, `__tablename__ = "audit_chain_head"`: `id SmallInteger` primary key (`autoincrement=False`) with check `audit_chain_head_id_check` `id = 1`; `seq BigInteger` not null; `hash LargeBinary` not null; `time DateTime(timezone=True)` nullable.

`CHAINED_COLUMNS: tuple[str, ...] = tuple(c.name for c in AuditEvent.__table__.columns if c.name not in {"seq", "time", "prev_hash", "hash"})`. It must equal the keys of `Event.columns()`, and a test checks this.

### C4. Migration `0002_audit_log.py`

`revision = "0002"`, `down_revision = "0001"`, with a docstring header in the style of 0001.

```python
def upgrade() -> None:
    op.create_table("audit_log", ...columns and checks of C3..., sa.PrimaryKeyConstraint("seq", "time", name="audit_log_pkey"))
    op.create_index("audit_log_time_idx", "audit_log", [sa.text("time DESC")])
    # create_default_indexes => false: the model declares every index, so autogenerate stays quiet.
    op.execute("SELECT create_hypertable('audit_log', by_range('time', INTERVAL '30 days'), create_default_indexes => false)")
    op.create_table("audit_chain_head", ...C3...)
    op.execute("INSERT INTO audit_chain_head (id, seq, hash, time) VALUES (1, 0, decode(repeat('00', 32), 'hex'), NULL)")
    op.execute("""
        CREATE FUNCTION audit_refuse_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only';
        END
        $$
    """)
    op.execute("CREATE TRIGGER audit_log_refuse_change BEFORE UPDATE OR DELETE ON audit_log FOR EACH ROW EXECUTE FUNCTION audit_refuse_change()")
    op.execute("CREATE TRIGGER audit_log_refuse_truncate BEFORE TRUNCATE ON audit_log FOR EACH STATEMENT EXECUTE FUNCTION audit_refuse_change()")
    # UPDATE stays allowed on the head: the writer moves it.
    op.execute("CREATE TRIGGER audit_chain_head_refuse_delete BEFORE DELETE ON audit_chain_head FOR EACH ROW EXECUTE FUNCTION audit_refuse_change()")
    op.execute("CREATE TRIGGER audit_chain_head_refuse_truncate BEFORE TRUNCATE ON audit_chain_head FOR EACH STATEMENT EXECUTE FUNCTION audit_refuse_change()")

def downgrade() -> None:
    op.drop_table("audit_chain_head")
    op.drop_table("audit_log")
    op.execute("DROP FUNCTION audit_refuse_change()")
```

### C5. Test fixtures (`tests/conftest.py`)

```python
ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"

@pytest.fixture(scope="session")
def database_at_head():
    # Sync: Alembic's env.py runs its own event loop.
    command.upgrade(Config(str(ALEMBIC_INI)), "head")

@pytest.fixture
async def empty_audit_log(database_at_head):
    # The triggers refuse DELETE, so they are switched off for this transaction only, as a superuser can.
    async with SessionLocal() as session:
        await session.execute(text("SET LOCAL session_replication_role = replica"))
        await session.execute(text("DELETE FROM audit_log"))
        await session.execute(text("UPDATE audit_chain_head SET seq = 0, hash = :zero, time = NULL"), {"zero": bytes(32)})
        await session.commit()
```

Import `SessionLocal` and Alembic inside the fixture bodies, or below `pytest_configure`'s environment setup. `app.core.db` must not be imported at module import time of `conftest.py`, because `DATABASE_URL` is set in `pytest_configure`. A DB test module that uses the audit tables uses `pytestmark = pytest.mark.usefixtures("empty_audit_log")`.

### C6. `app/audit/writer.py`

```python
AUDIT_ACTIONS = "audit_actions"     # key in session.info: set[str] of actions recorded in this session
LOCK_TIMEOUT = "5s"

class AuditChainBusy(RuntimeError): """The head of the chain stayed locked longer than LOCK_TIMEOUT."""

async def record(session: AsyncSession, event: Event) -> AuditEvent:
    # Never commits. Call it last in the transaction: the head lock is held until the commit.
    try:
        previous = (await session.execute(
            text("SELECT current_setting('lock_timeout'), set_config('lock_timeout', :timeout, true)"),
            {"timeout": LOCK_TIMEOUT})).first()[0]
        head = (await session.execute(
            select(AuditChainHead).where(AuditChainHead.id == 1).with_for_update()
            .execution_options(populate_existing=True))).scalar_one()
        await session.execute(text("SELECT set_config('lock_timeout', :timeout, true)"), {"timeout": previous})
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == "55P03":   # lock_not_available
            raise AuditChainBusy(f"the audit chain stayed locked for {LOCK_TIMEOUT}") from exc
        raise
    now = datetime.now(UTC)
    now = now.replace(microsecond=now.microsecond // 1000 * 1000)
    if head.time is not None and now < head.time:
        now = head.time                       # times never decrease along the chain
    columns = event.columns()
    seq = head.seq + 1
    digest = event_hash(seq, now, head.hash, columns)
    row = AuditEvent(seq=seq, time=now, prev_hash=head.hash, hash=digest, **columns)
    session.add(row)
    head.seq, head.hash, head.time = seq, digest, now
    await session.flush()
    session.info.setdefault(AUDIT_ACTIONS, set()).add(event.action)
    return row

async def record_alone(event: Event) -> AuditEvent:
    # For refused actions: commits on its own, so the request's rollback cannot take it away.
    async with SessionLocal() as session:
        row = await record(session, event)
        await session.commit()
        return row
```

### C7. `verify_chain` (added to `chain.py`)

```python
class Problem(StrEnum): HASH_MISMATCH = "hash_mismatch"; BROKEN_LINK = "broken_link"; MISSING = "missing"; HEAD_MISMATCH = "head_mismatch"

@dataclass(frozen=True)
class ChainReport:
    ok: bool; checked: int; head_seq: int; broken_at: int | None = None; problem: Problem | None = None

BATCH = 1000

async def verify_chain(session: AsyncSession, *, from_seq: int = 1) -> ChainReport:
    head = AuditChainHead read without a lock (populate_existing)
    if from_seq > head.seq: return ChainReport(ok=True, checked=0, head_seq=head.seq)
    expected_prev = GENESIS if from_seq == 1 else hash of the row seq == from_seq - 1, or None when that row is absent
    expected_seq, checked, last_hash = from_seq, 0, None
    loop: rows = select(AuditEvent).where(AuditEvent.seq >= expected_seq, AuditEvent.seq <= head.seq)
                 .order_by(AuditEvent.seq).limit(BATCH), with populate_existing; stop when empty
        for row in rows:
            if row.seq != expected_seq:                          -> fail MISSING at expected_seq
            if expected_prev is not None and row.prev_hash != expected_prev -> fail BROKEN_LINK at row.seq
            if event_hash(row.seq, row.time, row.prev_hash, {c: getattr(row, c) for c in CHAINED_COLUMNS}) != row.hash
                                                                 -> fail HASH_MISMATCH at row.seq
            expected_prev = last_hash = row.hash; expected_seq += 1; checked += 1
    if expected_seq - 1 != head.seq or last_hash != head.hash:  -> fail HEAD_MISMATCH at expected_seq - 1 if expected_seq > from_seq else head.seq
    return ChainReport(ok=True, checked=checked, head_seq=head.seq)
```

Every "fail" returns `ChainReport(ok=False, checked=checked, head_seq=head.seq, broken_at=..., problem=...)`.

### C8. `app/audit/http.py`

```python
class AuditMissing(RuntimeError): """A state-changing route ended without recording any of its declared actions."""

def audited(*actions: str) -> params.Depends:
    # ValueError when no action is given or one does not match ACTION_PATTERN.
    declared = frozenset(actions)
    async def audit_guard(session: DbSession) -> AsyncIterator[None]:
        yield
        # Reached only when the handler returned. When it raised, the exception passes through here
        # and get_session rolls back.
        if not declared & session.info.get(AUDIT_ACTIONS, set()):
            raise AuditMissing(f"{', '.join(sorted(declared))}: no event was recorded, so nothing is committed")
    audit_guard.audit_actions = declared    # read by tests/security/routes.py
    return Depends(audit_guard, scope="function")

def source_of(request: Request, *, auth_method: str | None = None, mfa: bool | None = None) -> Source:
    # Uvicorn's --proxy-headers already set request.client from X-Forwarded-For. A host that is not an IP
    # address (Starlette's TestClient sends "testclient") gives ip=None.
    ...
    return Source(ip=ip, user_agent=request.headers.get("user-agent"), auth_method=auth_method, mfa=mfa)
```

`DbSession` in `app/core/db.py` becomes `Annotated[AsyncSession, Depends(get_session, scope="function")]`. Add a comment: the commit and the audit guard run before the response is sent, so a failed commit gives a 500. The guard depends on the same `DbSession` alias, so FastAPI's dependency cache gives it the handler's session.

### C9. `tests/security/routes.py`

```python
STATE_CHANGING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
READ_ONLY = frozenset({"GET", "HEAD"})

def declared_actions(route: APIRoute) -> frozenset[str]
    # union of getattr(dep.dependency, "audit_actions", frozenset()) over route.dependencies
    # (router-level dependencies are merged into route.dependencies by include_router)

def unaudited_routes(app: FastAPI, exempt: Mapping[str, str]) -> list[str]
    # "METHOD /path" for each APIRoute method in STATE_CHANGING, when declared_actions(route) is empty
    # and "METHOD /path" is not in exempt. Sorted.

def unknown_routes(app: FastAPI) -> list[str]
    # f"{type(route).__name__} {getattr(route, 'path', '?')}" for every route that is neither an APIRoute
    # nor a starlette Route whose methods are within READ_ONLY (the docs routes). WebSocket routes and Mounts land here.
```

The test module imports it with `from routes import declared_actions, unaudited_routes, unknown_routes`. pytest's prepend mode puts `tests/security` on `sys.path`.

## Steps

### 1. Audit event model and change diff

Files: create `backend/app/audit/__init__.py`, `backend/app/audit/events.py` (contract C1), and `backend/tests/audit/test_events.py`.

Tests first (no database is needed, but the suite still runs through the runner):
- `test_an_action_without_a_dot_is_refused` (`"created"`), `test_an_action_with_upper_case_is_refused` (`"Server.created"`), `test_a_dotted_lower_case_action_is_accepted` (`"auth.sign_in_failed"`).
- `test_a_float_in_change_is_refused`, `test_a_float_nested_in_result_detail_is_refused`, `test_actor_details_must_be_json`. Each expects `pydantic.ValidationError`.
- `test_actor_human_agent_and_system_fill_type_id_name_and_details`.
- `test_source_normalises_the_ip_and_cuts_the_user_agent`. `"2001:DB8::1"` gives `"2001:db8::1"`. A user agent of 2000 characters keeps 1024. `"not-an-ip"` is refused.
- `test_columns_holds_every_field_as_plain_values`: an event with every field set gives `columns()` with enum values as strings and nested objects flattened. A minimal event gives `None` for `target_type`, `{}` for `context`, and `"success"` for `result`.
- `test_changes_lists_only_differing_fields`, `test_changes_redacts_named_and_password_like_fields` (`secret={"pin"}`; the keys `"db_password"`, `"api_token"` and `"client_secret"` give `[redacted]` on both sides), `test_changes_returns_none_when_nothing_differs`, `test_changes_reports_a_field_present_on_one_side_only`.

Run `megoocolab-runner services run test -- uv run pytest tests/audit/test_events.py -q`. Expected: `ModuleNotFoundError: No module named 'app.audit'`.

Implement C1. `__init__.py` exports `Actor, ActorType, Event, Person, Result, RiskClass, Source, Target, changes`. Run again: everything passes. Then run the whole suite.

Commit: `feat(audit): an audit event is validated before it reaches the database`.

### 2. Canonical form and event hash

Files: create `backend/app/audit/chain.py` with the pure part of C2 only (no `verify_chain` yet), `backend/tests/audit/test_chain.py`. Update `__init__.py` with `GENESIS, canonical, event_hash`.

Tests first:
- `test_canonical_sorts_keys_without_spaces`.
- `test_document_leaves_out_null_columns_but_keeps_nested_nulls`.
- `test_canonical_keeps_non_ascii_text_as_utf8` (`"Zoë"` encodes as `b"Zo\xc3\xab"`, not `ë`).
- `test_time_is_utc_with_milliseconds` (a `+02:00` time is converted to `Z`).
- `test_source_ip_has_one_text_form` (`ipaddress.ip_address("203.0.113.9")` and `"203.0.113.9"` give the same document).
- `test_a_fixed_event_has_a_fixed_hash`: the known answer from C2, asserting both the canonical bytes and the pinned hex.
- `test_a_float_is_refused` (`ValueError`).
- `test_genesis_is_32_zero_bytes`.

Run `megoocolab-runner services run test -- uv run pytest tests/audit/test_chain.py -q`. Expected: ImportError on `app.audit.chain`. Implement, run again, then run the whole suite.

Commit: `feat(audit): every event has one canonical form and its SHA-256`.

### 3. The audit_log hypertable, the chain head and the append-only triggers

Files: create `backend/app/audit/models.py` (C3) and `backend/migrations/versions/0002_audit_log.py` (C4). Modify `backend/app/models.py` (`import app.audit.models  # noqa: F401`; the docstring drops "There are none yet: MITA-7 adds the first."), `backend/app/audit/__init__.py` (add `AuditEvent, AuditChainHead`), `backend/tests/conftest.py` (C5) and `backend/tests/test_migrations.py`. Add a test to `tests/audit/test_events.py`.

Tests first:
- `tests/audit/test_events.py::test_columns_match_the_chained_columns_of_the_table`: `set(Event(...).columns()) == set(CHAINED_COLUMNS)`, and the length is 20.
- `tests/test_migrations.py::test_audit_log_is_a_hypertable_on_time`: `SELECT hypertable_name FROM timescaledb_information.hypertables WHERE hypertable_name = 'audit_log'` returns one row.
- `test_0002_goes_down_and_up_again_with_an_empty_chain`: `downgrade "0001"`, then both `to_regclass('audit_log')` and `to_regclass('audit_chain_head')` are NULL, and `audit_refuse_change` is absent from `pg_proc`. Then `upgrade head`, and the head row is exactly `(1, 0, bytes(32), None)`.
- `test_the_models_match_the_migrations`: `command.check(_config())` raises nothing.

Run `megoocolab-runner services run test -- uv run pytest tests/test_migrations.py tests/audit -q`. Expected: ImportError for `app.audit.models`, then, after the models exist, `AutogenerateDiffsDetected` until 0002 exists.

Implement C3 and C4 exactly. If `alembic check` reports the `time DESC` index, make the model and the migration declare it the same way until it is quiet. Do not drop the index. Run again: everything passes. Then run by hand, as `AGENTS.md` asks:
`megoocolab-runner services run migrate -- sh -c 'uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head'`.
Then run the whole suite. `test_revisions_are_numbered_consecutively_from_0001` must pass with 0002.

Commit: `feat(audit): an append-only audit_log hypertable and its chain head`.

### 4. The transactional, chained writer

Files: create `backend/app/audit/writer.py` (C6) and `backend/tests/audit/test_writer.py`. Update `__init__.py` with `AuditChainBusy, record, record_alone`.

Tests first, all with `pytestmark = pytest.mark.usefixtures("empty_audit_log")`. Build events with a helper `sample(action="server.created", **kw)`:
- `test_the_first_event_has_number_1_and_the_zero_hash`.
- `test_the_second_event_links_to_the_first`: `prev_hash == first.hash`, `seq == 2`, and the head equals `(2, second.hash, second.time)`.
- `test_every_field_comes_back_as_written`: an event with every field set is recorded and committed, then read in a fresh session. Each `CHAINED_COLUMNS` value equals `columns()`; compare `source_ip` with `str(...)`. `time.microsecond % 1000 == 0`, and `tzinfo` is UTC.
- `test_a_rolled_back_event_leaves_no_row_and_an_unchanged_head`.
- `test_the_next_event_after_a_rollback_takes_the_same_number`.
- `test_twenty_concurrent_writers_get_numbers_1_to_20`: `asyncio.gather` over 20 coroutines, each `async with SessionLocal() as s: await record(s, sample()); await s.commit()`. The seqs are `1..20`, and each `prev_hash` equals the previous row's hash, checked by reading the rows ordered by seq. Step 5 adds `verify_chain` to this test.
- `test_times_never_decrease_along_the_chain`: monkeypatch `writer.datetime` with a `now()` that goes backwards for the second call. The second event's time equals the first's.
- `test_record_alone_commits_although_the_caller_rolls_back`.
- `test_record_adds_the_action_to_session_info`.
- `test_a_writer_that_cannot_get_the_head_lock_raises_audit_chain_busy`: monkeypatch `writer.LOCK_TIMEOUT` to `"200ms"`. Session A records and does not commit. Session B's `record` raises `AuditChainBusy`. Then roll back both.

Run `megoocolab-runner services run test -- uv run pytest tests/audit/test_writer.py -q`. Expected: ImportError on `app.audit.writer`. Implement C6, run again: everything passes. Then run the whole suite.

Commit: `feat(audit): events are written in the caller's transaction and chained to the one before`.

### 5. Chain check and the tamper suite

Files: add `Problem`, `ChainReport`, `BATCH` and `verify_chain` (C7) to `backend/app/audit/chain.py`, and update `__init__.py`. Create `backend/tests/security/test_audit_tamper.py`. Extend `tests/audit/test_writer.py::test_twenty_concurrent_writers_get_numbers_1_to_20` to assert `(await verify_chain(s)).ok`.

The tamper test module uses `empty_audit_log`, plus a fixture `chain` that writes 5 events with `record_alone` and returns their rows. Helpers:
- `async def tamper(sql, params=None)`: one session, `SET LOCAL session_replication_role = replica`, then the statement, then commit.
- `async def check(**kw)`: a fresh session that returns `await verify_chain(session, **kw)`.

Tests first:
- Refusals, each expecting `sqlalchemy.exc.DBAPIError` with "append-only" in `str(exc)`, run without tamper: `test_update_on_audit_log_is_refused`, `test_delete_on_audit_log_is_refused`, `test_truncate_on_audit_log_is_refused`, `test_delete_on_the_chain_head_is_refused`, `test_truncate_on_the_chain_head_is_refused`.
- `test_an_untouched_chain_passes`: `ok`, `checked == 5`, `head_seq == 5`.
- `test_an_empty_chain_passes`: no `chain` fixture.
- `test_a_changed_field_gives_hash_mismatch_at_that_number`: `UPDATE audit_log SET reason = 'changed' WHERE seq = 3` gives `(False, HASH_MISMATCH, 3)`.
- `test_a_removed_middle_row_gives_missing_at_that_number`: delete seq 3 gives `MISSING` at 3.
- `test_a_removed_newest_row_gives_head_mismatch`: delete seq 5 gives `HEAD_MISMATCH`.
- `test_a_row_rewritten_with_its_own_hash_gives_broken_link_at_the_next_number`: compute `event_hash` for row 3 with a changed reason, then update `reason` and `hash`. The result is `BROKEN_LINK` at 4.
- `test_a_changed_head_gives_head_mismatch`: `UPDATE audit_chain_head SET hash = :x`.
- `test_from_seq_starts_from_the_event_before`: `from_seq=3` gives `checked == 3`.
- `test_from_seq_accepts_a_missing_start`: delete seqs 1 and 2, then `from_seq=3` passes.

Run `megoocolab-runner services run test -- uv run pytest tests/security/test_audit_tamper.py -q`. Expected: ImportError for `verify_chain`. Implement C7, run again: everything passes. If the TRUNCATE trigger does not fire on the hypertable, stop and report it. Do not weaken the test. Then run the whole suite.

Commit: `feat(audit): the chain check finds a changed or removed event`.

### 6. Route guard, request source and function-scoped sessions

Files: modify `backend/app/core/db.py` (C8 `DbSession`) and `backend/tests/test_db.py`. Create `backend/app/audit/http.py` (C8) and `backend/tests/audit/test_http.py`. Update `__init__.py` with `AuditMissing, audited, source_of`.

Tests first:
- `tests/test_db.py::test_db_session_closes_before_the_response`: `typing.get_args(DbSession)[1].scope == "function"`.
- `tests/audit/test_http.py` uses `empty_audit_log`. A fixture creates and drops the table `audit_http_probe (id int)`, as `tests/test_db.py` does. A throwaway `FastAPI()` app has these routes:
  - `POST /ok` with `dependencies=[audited("probe.created")]`: inserts a probe row and records `probe.created`.
  - `POST /forgot` with the same declaration: inserts a probe row and records nothing.
  - `POST /refused` with the same declaration: inserts, records, then `raise HTTPException(409)`.
  - `POST /other` declaring `probe.created`: records `probe.deleted` only.
  - `GET /source`: returns `source_of(request, auth_method="password", mfa=True).model_dump()`.
  Client: `AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")`.
- `test_a_route_that_records_its_declared_action_commits_both`: 200, one probe row, one event.
- `test_a_route_that_records_nothing_answers_500_and_commits_nothing`.
- `test_a_route_that_records_another_action_answers_500`.
- `test_a_route_that_raises_rolls_back_and_keeps_its_status`: 409, no probe row, no event, and the head seq is 0.
- `test_audited_refuses_a_bad_or_missing_action`.
- `test_source_of_takes_the_client_address_and_the_user_agent`: `ip == "127.0.0.1"`, plus the header and the passed values.
- `test_source_of_drops_a_client_host_that_is_not_an_ip`: a fake `Request` scope with `client=("testclient", 50000)`.

Run `megoocolab-runner services run test -- uv run pytest tests/test_db.py tests/audit/test_http.py -q`. Expected: ImportError for `app.audit.http`, and the scope assertion fails. Implement, run again: everything passes. Then run the whole suite: `test_health.py` and the existing `test_db.py` tests must still pass.

Commit: `feat(audit): a state-changing route is rolled back unless it records its declared events`.

### 7. Audit-coverage security suite

Files: create `backend/tests/security/routes.py` (C9) and `backend/tests/security/test_audit_coverage.py`.

`test_audit_coverage.py` holds:

```python
# A POST, PUT, PATCH or DELETE route that needs no audit event, with the reason. Adding one is a visible
# change to the security suite.
EXEMPT: dict[str, str] = {}
```

Tests:
- `test_every_state_changing_route_declares_its_audit_actions`: `unaudited_routes(create_app(), EXEMPT) == []`. The message tells the reader to add `dependencies=[audited("…")]` and call `record`.
- `test_the_app_has_no_route_the_check_does_not_understand`: `unknown_routes(create_app()) == []`. The message says the guard covers HTTP routes only, and to extend this check before adding a WebSocket route or a mount.
- `test_exempt_lists_only_real_routes`: every key of `EXEMPT` is a "METHOD /path" of the app.
- `test_the_check_reports_an_undeclared_route_of_a_sample_app`: a sample `FastAPI()` with an undeclared `POST /things`, a declared `PUT /things/{id}` (`audited("thing.updated")`) and a `GET /things`. The result is exactly `["POST /things"]`. With `{"POST /things": "reason"}` as the exemption, the result is `[]`.
- `test_the_check_finds_the_actions_of_a_router_dependency`: `include_router(router, dependencies=[audited("thing.created")])` gives `declared_actions == {"thing.created"}`.
- `test_the_check_reports_websocket_routes_and_mounts`.

Run `megoocolab-runner services run test -- uv run pytest tests/security/test_audit_coverage.py -q`. Expected: `ModuleNotFoundError: No module named 'routes'`. Implement `routes.py`, run again: everything passes. Then run the whole suite.

Commit: `test(security): every state-changing route must declare its audit events`.

### 8. make test-security runs the security suites

Files: modify `Makefile`, `backend/tests/test_makefile.py` and `AGENTS.md`.

Test first: replace `test_test_security_says_its_suites_are_not_in_the_repository_yet` with `test_test_security_runs_the_security_suites`. It runs `make(workdir, "-n", "test-security")` and expects `returncode == 0` and `"cd backend && megoocolab-runner services run test -- uv run pytest tests/security" in result.stdout.splitlines()`.

Run `megoocolab-runner services run test -- uv run pytest tests/test_makefile.py -q`. Expected: it fails, because the target exits 1 with the old message.

Implement. The `Makefile` target becomes:

```make
test-security:
	$(REQUIRE_RUNNER)
	cd backend && $(RUNNER) services run test -- uv run pytest tests/security
```

The help text stays "Run the security suites". In `AGENTS.md`, the Security suites bullet becomes: "**Security suites**: `make test-security`. It runs the audit-coverage and audit-tamper suites. The secret-leak and approval-bypass suites join it with Phases 3 and 4."

Run the test again: it passes. Then run `make test-security` from the repository root (it passes), and the whole backend suite.

Commit: `chore(make): make test-security runs the audit security suites`.

## Final verification

From `backend/`:

1. `megoocolab-runner services run test -- uv run pytest`: everything passes, including `tests/audit` and `tests/security`.
2. `megoocolab-runner services run migrate -- sh -c 'uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head'`: succeeds.
3. `megoocolab-runner services run image -- uv run pytest -m docker`: the container migrates to 0002 and serves.
4. From the root, `make test-security`: the coverage and tamper suites pass.
5. `megoocolab-runner services run stack -- uv run pytest -m stack`: the stack still comes up healthy.

## Requirement map

| Design item | Steps |
|---|---|
| Event fields, enums, JSON without floats, action format | 1 |
| `changes()` with redaction | 1 |
| Canonical JSON, nulls left out, SHA-256, known answer | 2 |
| `audit_log` hypertable (30-day chunks, `(seq, time)` primary key, time index, no FKs), `audit_chain_head`, triggers, downgrade | 3 |
| Models match migrations, 0002 down and up | 3 |
| `record` in the caller's transaction, head lock with 5 s timeout, millisecond time that never decreases, `AuditChainBusy`, `record_alone` | 4 |
| `verify_chain`, `ChainReport` with its four problems, `from_seq` | 5 |
| Tamper suite and trigger refusals | 5 |
| `DbSession` with `scope="function"`, `audited` guard with 500 and rollback, `source_of` from `request.client` | 6 |
| Coverage suite, `EXEMPT`, WebSocket and mount detection | 7 |
| `make test-security`, `AGENTS.md` | 8 |
