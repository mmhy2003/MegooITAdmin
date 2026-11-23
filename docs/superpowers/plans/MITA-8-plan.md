# MITA-8 plan: login with mandatory MFA (local accounts, TOTP)

## Goal

Nobody reaches a page or an API route of MegooITAdmin without a password and a TOTP code. A fresh install is claimed on `/setup` with a one-time code from the host, and every auth step and failed attempt is an audit event.

## Architecture

The backend gets a package `app/auth/` that holds the tables (`users`, `auth_sessions`, `recovery_codes`, `auth_setup`, migration `0004_auth`), small pure modules (passwords, TOTP, AES-GCM, recovery codes, clock), sessions stored as rows keyed by a SHA-256 token hash, the flows in `service.py`, and the routes under `/api/auth`. The dependencies `CurrentSession` and `CurrentUser` guard the routes, and a new security suite pins the only routes that work without an active session. In the frontend, `src/proxy.ts` asks the backend about the session on every page request and redirects using a pure gate table. The `(auth)` route group holds `/setup` and `/login` without the shell, and `(app)/profile` holds the Profile and security page. Host commands (`make setup-code`, `make reset-mfa`, `make reset-password`) run `python -m app.auth.cli` in the backend container.

## Conventions every step follows

- Work on the branch `megoo/MITA-8-p0-07-login-with-mandatory-mfa-local-acc`. Do not create another branch, and do not push.
- Write the test first, run it, and watch it fail for the reason given. Then implement it and run it again.
- Commits: `type(area): sentence`, then a body that says why, and the last line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Commit only the files of the step. Never commit `.megoocolab/` or any plan or design file. No `docs/` files.
- `backend/tests/` has no `__init__.py` (prepend import mode), so every test file basename must be unique. Shared helpers go in `backend/tests/auth_helpers.py` (import it as `from auth_helpers import …`) and shared fixtures in `backend/tests/conftest.py`.
- Time: auth code never calls `datetime.now` itself. It calls `clock.now()` through the module (`from app.auth import clock`), so the `clock` fixture can replace it.
- Every route that returns normally (not by raising) must `record()` one of its `audited(...)` actions, or the guard answers 500. Refusals that write no event **raise** `HTTPException`. Refusals that write an event **return** `JSONResponse({"detail": reason}, status_code=…)`, so the transaction commits (decision 16). Call `record()` last in a transaction: it holds the audit chain lock until the commit.
- A route that returns a `JSONResponse` on some paths declares `response_model=` in the decorator and is annotated `-> XOut | JSONResponse`.
- Frontend: client components start with `"use client"`, icons are `aria-hidden`, imports use `@/`. Tests sit in `__tests__/` beside the code. Component tests mock `@/lib/api` (keep the real `ApiError`) and `@/lib/auth/navigate`, and call `vi.mocked(apiFetch).mockReset()` in `beforeEach`.
- Read `frontend/node_modules/next/dist/docs/` for `proxy.ts`, async `searchParams` and `redirect` before you write Next.js code (see frontend/AGENTS.md).

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

The throwaway test key, used in every test file, test set and throwaway stack env: `TEST_AUTH_SECRET_KEY = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"`.

## File map

### Backend

| File | Status | Responsibility |
|---|---|---|
| `backend/pyproject.toml`, `backend/uv.lock` | modify | `argon2-cffi`, `pyotp`, `cryptography` |
| `backend/app/core/config.py` | modify | `auth_secret_key` (required, 64 hex), `auth_key()`, `session_idle_minutes=60`, `session_absolute_minutes=720`, `api_docs=False` |
| `backend/app/main.py` | modify | `create_app(settings=None)`; docs only with `api_docs`; includes the auth router |
| `backend/app/models.py` | modify | Imports `app.auth.models` |
| `backend/app/auth/__init__.py` | new | Package docstring only |
| `backend/app/auth/clock.py` | new | `now()` |
| `backend/app/auth/passwords.py` | new | Argon2id hash, verify, rehash check, dummy verify, length rule |
| `backend/app/auth/totp.py` | new | Secret, `otpauth://` address, verification with drift and replay protection |
| `backend/app/auth/crypto.py` | new | AES-256-GCM for TOTP secrets, with the user ID as associated data |
| `backend/app/auth/recovery.py` | new | Recovery and setup codes: create, normalise, hash |
| `backend/app/auth/models.py` | new | `User`, `AuthSession`, `RecoveryCode`, `SetupCode` |
| `backend/app/auth/actions.py` | new | The audit action names and the reason values |
| `backend/app/auth/sessions.py` | new | Session rows and the cookie |
| `backend/app/auth/deps.py` | new | `current_session`/`CurrentSession`, `current_user`/`CurrentUser` |
| `backend/app/auth/service.py` | new | Status, setup, password step, code step, enrolment, logout, profile flows, lockout |
| `backend/app/auth/schemas.py` | new | The request and response models |
| `backend/app/auth/router.py` | new | `/api/auth/*` |
| `backend/app/auth/cli.py` | new | `setup-code [--if-no-account]`, `reset-mfa EMAIL`, `reset-password EMAIL` |
| `backend/migrations/versions/0004_auth.py` | new | The four tables and their grants |
| `backend/docker-entrypoint.sh` | modify | Refuses to start without `AUTH_SECRET_KEY`; runs `setup-code --if-no-account` |
| `backend/tests/conftest.py` | modify | Sets `AUTH_SECRET_KEY`; fixtures `clean_auth`, `clock`, `api` |
| `backend/tests/auth_helpers.py` | new | Users, codes, sign-in and audit helpers |
| `backend/tests/auth/test_*.py` | new | One file per unit or flow (named in the steps) |
| `backend/tests/security/routes.py` | modify | `session_requirement`, `unguarded_routes` |
| `backend/tests/security/test_auth_coverage.py` | new | Every route needs an active session or is pinned |
| `backend/tests/security/test_auth_events.py` | new | One walk-through produces every action; no secret in `audit_log` |
| `backend/tests/security/test_db_privileges.py` | modify | `API_GRANTS` for the four tables |
| `backend/tests/test_settings.py`, `test_health.py`, `test_migrations.py`, `test_makefile.py`, `test_container.py`, `test_stack.py` | modify | As in the steps |

### Stack and tooling

| File | Status | Responsibility |
|---|---|---|
| `docker-compose.yml` | modify | Backend: `AUTH_SECRET_KEY` (required), `SESSION_*`, `API_DOCS`. Frontend: `BACKEND_URL` |
| `Makefile` | modify | `.env` gets `AUTH_SECRET_KEY`; targets `setup-code`, `reset-mfa`, `reset-password` |
| `.env.example`, `tools/stacks/dev.env`, `tools/stacks/e2e.env` | modify | The new variables (`dev.env`: `API_DOCS=true`) |
| `megoocolab.toml` | modify | `AUTH_SECRET_KEY` in the `migrate` and `stack` sets |
| `tools/test-services/docker-compose.image.yml` | modify | `AUTH_SECRET_KEY` for the image backend |
| `tools/test-services/docker-compose.web.yml` | modify | Stub `backend` (Caddy) and `BACKEND_URL` for the frontend |
| `tools/test-services/stub-backend.Caddyfile` | new | Answers `GET /api/auth/session` |
| `README.md`, `AGENTS.md` | modify | First start, host commands, security suites |

### Frontend

| File | Status | Responsibility |
|---|---|---|
| `frontend/package.json`, `package-lock.json` | modify | `qrcode.react` |
| `frontend/src/components/ui/{card,label,alert,dialog,checkbox,table}.tsx` | new | shadcn |
| `frontend/src/lib/api.ts` | new | `apiFetch`, `ApiError` |
| `frontend/src/lib/auth/navigate.ts` | new | `goTo(path)` (full page load) |
| `frontend/src/lib/auth/gate.ts` | new | Types, `safeNext`, `gateRedirect` |
| `frontend/src/lib/auth/backend.ts` | new | `SESSION_COOKIE`, `fetchSession(token)` |
| `frontend/src/lib/auth/server.ts` | new | `getSession()` (React `cache`), `requireUser()` |
| `frontend/src/lib/auth/messages.ts` | new | Refusal reason → text |
| `frontend/src/proxy.ts` | new | The page gate |
| `frontend/src/app/(auth)/layout.tsx`, `login/page.tsx`, `setup/page.tsx` | new | The auth pages without the shell |
| `frontend/src/components/auth/{password-step,code-step,recovery-step,locked-notice,enrol-step,recovery-codes,login-flow,setup-flow}.tsx` | new | The steps and flows |
| `frontend/src/app/(app)/layout.tsx`, `src/app/not-found.tsx` | modify | `requireUser()`, pass `user` |
| `frontend/src/components/shell/{app-shell,site-header,account-menu}.tsx` | modify | `user` prop, profile link, sign-out |
| `frontend/src/lib/navigation.ts` | modify | `pageTitle(pathname)` with "/profile" |
| `frontend/src/app/(app)/profile/page.tsx` | new | The route |
| `frontend/src/components/profile/{profile-page,password-dialog,authenticator-dialog,recovery-codes-dialog,sessions-card}.tsx` | new | The four cards and four dialogs |
| `frontend/image-tests/shell.test.ts` | modify | Redirects, `/login`, cookie on the existing checks |

## Contracts

### C1. Settings (`app/core/config.py`)

```python
auth_secret_key: str = Field(repr=False)          # required
session_idle_minutes: int = 60
session_absolute_minutes: int = 720
api_docs: bool = False

@field_validator("auth_secret_key")
@classmethod
def _hex_key(cls, value: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ValueError("AUTH_SECRET_KEY must be 64 hexadecimal characters (32 bytes). make up writes one into .env")
    return value.lower()

def auth_key(self) -> bytes:
    return bytes.fromhex(self.auth_secret_key)
```

### C2. Primitives

```python
# app/auth/clock.py
def now() -> datetime: return datetime.now(UTC)

# app/auth/passwords.py   (argon2.PasswordHasher() with library defaults = Argon2id)
PASSWORD_MIN = 12; PASSWORD_MAX = 128
class PasswordRuleError(ValueError): ...      # message: "A password has 12 to 128 characters."
def check_rule(password: str) -> None
async def hash_password(password: str) -> str            # asyncio.to_thread
async def verify_password(password_hash: str, password: str) -> bool   # False on mismatch or a bad hash
def needs_rehash(password_hash: str) -> bool
async def verify_dummy(password: str) -> None             # verifies against a hash made once, lazily; for unknown emails

# app/auth/totp.py   (pyotp; 6 digits, 30 s, SHA-1)
ISSUER = "MegooITAdmin"; PERIOD = 30
def new_secret() -> str                                   # pyotp.random_base32() (32 chars)
def provisioning_uri(secret: str, email: str) -> str      # pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=ISSUER)
def verify(secret: str, code: str, last_step: int | None, at: datetime) -> int | None
    # code: spaces removed, must be 6 digits, else None. current = int(at.timestamp()) // PERIOD.
    # Tries steps current-1, current, current+1 and skips any step <= last_step.
    # Compares with hmac.compare_digest(pyotp.TOTP(secret).generate_otp(step), code). Returns the matched step or None.

# app/auth/crypto.py   (cryptography AESGCM; blob = 12-byte nonce + ciphertext)
class SecretUndecryptable(Exception): ...
def encrypt_secret(key: bytes, user_id: UUID, secret: str) -> bytes      # associated data = user_id.bytes
def decrypt_secret(key: bytes, user_id: UUID, blob: bytes) -> str       # InvalidTag or a short blob → SecretUndecryptable

# app/auth/recovery.py
RECOVERY_CODE_COUNT = 10
CODE_PATTERN = r"[A-Z2-7]{4}(-[A-Z2-7]{4}){3}"
def new_code() -> str          # base64.b32encode(os.urandom(10)) = 16 chars (80 bits), shown as XXXX-XXXX-XXXX-XXXX
def normalise_code(text: str) -> str   # upper case, with "-" and whitespace removed
def hash_code(text: str) -> bytes      # sha256(normalise_code(text).encode()).digest()
```

### C3. Tables (`app/auth/models.py`, migration `0004_auth`)

Every constraint has an explicit name, in the model and in the migration, so `alembic check` stays quiet. IDs get a Python default of `uuid.uuid4`. Times are `DateTime(timezone=True)`.

- `users`: `id Uuid` PK `users_pkey`; `email Text NOT NULL` with `UniqueConstraint("email", name="users_email_key")` and `CheckConstraint("email = lower(email)", name="users_email_lower_check")`; `name Text NOT NULL`; `password_hash Text NOT NULL`; `is_owner Boolean NOT NULL server_default false`; `totp_secret LargeBinary NULL`; `totp_pending_secret LargeBinary NULL`; `totp_confirmed_at NULL`; `totp_last_step BigInteger NULL`; `failed_attempts Integer NOT NULL server_default 0`; `locked_until NULL`; `password_changed_at NOT NULL`; `created_at NOT NULL server_default now()`.
- `auth_sessions`: `id Uuid` PK; `user_id Uuid NOT NULL` FK `users.id` `ondelete="CASCADE"` (`auth_sessions_user_id_fkey`), index `auth_sessions_user_id_idx`; `token_hash LargeBinary NOT NULL` unique `auth_sessions_token_hash_key`; `stage Text NOT NULL` with check `auth_sessions_stage_check` (`stage IN ('pending', 'active')`); `mfa_method Text NULL` with check `auth_sessions_mfa_method_check` (`mfa_method IN ('totp', 'recovery_code')`); `created_at`, `last_seen_at`, `expires_at` NOT NULL; `ip INET NULL`; `user_agent Text NULL`. `user = relationship(User, lazy="raise")`, loaded with `joinedload`.
- `recovery_codes`: `id Uuid` PK; `user_id` FK cascade (`recovery_codes_user_id_fkey`), index `recovery_codes_user_id_idx`; `code_hash LargeBinary NOT NULL` unique `recovery_codes_code_hash_key`; `created_at NOT NULL server_default now()`.
- `auth_setup` (class `SetupCode`): `id SmallInteger` PK, `autoincrement=False`, check `auth_setup_id_check` (`id = 1`); `code_hash LargeBinary NOT NULL`; `failed_attempts Integer NOT NULL server_default 0`; `created_at NOT NULL server_default now()`.

Grants in the migration: `GRANT SELECT, INSERT, UPDATE ON users TO megooitadmin_api`, and `GRANT SELECT, INSERT, UPDATE, DELETE ON auth_sessions, recovery_codes, auth_setup TO megooitadmin_api`.

### C4. Actions and reasons (`app/auth/actions.py`)

```python
OWNER_CREATED = "auth.owner_created";            SETUP_FAILED = "auth.setup_failed"
SETUP_CODE_CREATED = "auth.setup_code_created";  PASSWORD_ACCEPTED = "auth.password_accepted"
SIGN_IN = "auth.sign_in";                        SIGN_IN_FAILED = "auth.sign_in_failed"
SIGN_OUT = "auth.sign_out";                      MFA_USED = "auth.mfa_used"
MFA_FAILED = "auth.mfa_failed";                  MFA_RESET = "auth.mfa_reset"
MFA_ENROLMENT_STARTED = "auth.mfa_enrolment_started"; MFA_ENROLLED = "auth.mfa_enrolled"
RECOVERY_CODES_CREATED = "auth.recovery_codes_created"; PASSWORD_CHANGED = "auth.password_changed"
ACCOUNT_LOCKED = "auth.account_locked";          SESSION_REVOKED = "auth.session_revoked"
ALL_ACTIONS: frozenset[str]  # all sixteen

# result_detail["reason"] values
UNKNOWN_ACCOUNT = "unknown_account"; WRONG_PASSWORD = "wrong_password"; LOCKED = "locked"
WRONG_CODE = "wrong_code"; EXPIRED = "expired"; UNDECRYPTABLE = "undecryptable"; NO_CODE = "no_code"
# result_detail["method"] values: "totp", "recovery_code"
```

### C5. API refusal `detail` values

| Detail | Status | Where |
|---|---|---|
| `not_signed_in` | 401 (raised) | No valid session, or the session is not active where it has to be |
| `invalid_credentials` | 401 | `POST /login`: unknown email, wrong password or locked account (decision 12) |
| `wrong_code` | 401 | A wrong TOTP or recovery code |
| `locked` | 401 | Code step and profile actions while the account is locked |
| `undecryptable` | 401 | The stored secret no longer decrypts |
| `wrong_setup_code` / `no_setup_code` | 401 | `POST /setup` |
| `wrong_password` | 401 | `POST /password`: the current password is wrong |
| `setup_closed` | 409 (raised) | `POST /setup` once an account exists |
| `not_enrolled`, `already_enrolled`, `already_signed_in`, `no_enrolment`, `current_session` | 409 (raised) | As in the steps |
| `code_required` | 422 (raised) | `POST /mfa/enrol` on an active session without a code |
| `not_found` | 404 (raised) | `DELETE /sessions/{id}` for an ID that is not one of the person's sessions |

Schema validation errors are FastAPI's usual 422 with a list `detail`.

### C6. Sessions (`app/auth/sessions.py`) and dependencies (`app/auth/deps.py`)

```python
COOKIE = "megoo_session"
PENDING_LIFETIME = timedelta(minutes=10)
TOUCH_EVERY = timedelta(minutes=1)

@dataclass(frozen=True)
class Lookup:
    session: AuthSession | None   # valid, with .user loaded
    expired: AuthSession | None   # presented but past a limit; already deleted and flushed

def new_token() -> str                    # secrets.token_urlsafe(32)
def hash_token(token: str) -> bytes       # sha256 digest
def is_expired(s: AuthSession, now: datetime) -> bool
    # now >= s.expires_at or now - s.last_seen_at >= timedelta(minutes=settings.session_idle_minutes)
async def create_session(db, user: User, source: Source, *, stage: Literal["pending", "active"],
                         mfa_method: str | None = None) -> str
    # created_at = last_seen_at = now; expires_at = now + PENDING_LIFETIME (pending) or + session_absolute_minutes.
    # ip/user_agent from source. Returns the token; only hash_token(token) is stored.
async def lookup_session(db, token: str | None) -> Lookup
    # joinedload(AuthSession.user). Expired: delete + flush, Lookup(None, s). Valid: last_seen_at = now when
    # now - last_seen_at >= TOUCH_EVERY.
async def end_sessions(db, user_id: UUID, *, keep: UUID | None = None) -> list[AuthSession]   # deletes, returns them
async def delete_expired(db, user_id: UUID) -> None
def set_cookie(response: Response, request: Request, token: str) -> None
    # response.set_cookie(COOKIE, token, max_age=session_absolute_minutes*60, path="/", httponly=True,
    #                     samesite="lax", secure=request.url.scheme == "https")
def clear_cookie(response: Response, request: Request) -> None   # delete_cookie with the same attributes

# deps.py
NOT_SIGNED_IN = "not_signed_in"
async def current_session(request: Request, db: DbSession) -> AuthSession
    # lookup_session(db, request.cookies.get(COOKIE)). Valid → return it.
    # Expired *pending* → record(db, MFA_FAILED event: actor = its user, target = its user, result FAILURE,
    #   result_detail {"reason": "expired"}, mfa False), await db.commit(), then raise.
    # Otherwise raise HTTPException(401, NOT_SIGNED_IN).
CurrentSession = Annotated[AuthSession, Depends(current_session)]
async def current_user(session: CurrentSession) -> User      # stage != "active" → 401 NOT_SIGNED_IN
CurrentUser = Annotated[User, Depends(current_user)]
```

A route that needs the current session's ID and an active user takes both `session: CurrentSession` and `user: CurrentUser`. FastAPI's dependency cache gives both the same session.

### C7. Service helpers (`app/auth/service.py`)

```python
MAX_FAILURES = 5
LOCK_TIME = timedelta(minutes=15)
ACTOR_NAME_MAX = 254
Status = Literal["setup_required", "signed_out", "mfa_required", "enrolment_required", "active"]

@dataclass(frozen=True)
class Refusal:
    status: int
    reason: str   # a C5 detail

def actor_of(user: User) -> Actor            # Actor.human(user.id, user.name)
def target_of(user: User) -> Target          # Target(type="user", id=str(user.id), name=user.email)
def auth_event(request, action, actor, *, mfa: bool, target=None, result=Result.SUCCESS, detail=None) -> Event
    # source=source_of(request, auth_method="password", mfa=mfa); result_detail=detail
async def lock_user(db, user_id: UUID) -> User   # SELECT … FOR UPDATE, populate_existing
def is_locked(user: User, now) -> bool           # locked_until is not None and locked_until > now
def register_failure(user: User, now) -> bool
    # if locked_until is past: locked_until = None, failed_attempts = 0. Then failed_attempts += 1.
    # At MAX_FAILURES: locked_until = now + LOCK_TIME, failed_attempts = 0, return True. Else False.
def register_success(user: User) -> None         # failed_attempts = 0, locked_until = None
async def fail_attempt(db, request, user, *, action: str, reason: str, mfa: bool, method: str | None = None) -> bool
    # register_failure; record(action, FAILURE, detail {"reason": reason, "method": method (only when given)});
    # when locked also record(ACCOUNT_LOCKED, target user). Returns True when this attempt locked the account.
async def check_second_factor(db, user: User, code: str, method: str, now) -> str | None
    # None = accepted. "totp": decrypt_secret(settings.auth_key(), user.id, user.totp_secret) (SecretUndecryptable →
    # return UNDECRYPTABLE); totp.verify(..., user.totp_last_step, now) → set user.totp_last_step = step, else WRONG_CODE.
    # "recovery_code": delete the RecoveryCode row with user_id and hash_code(code) (none → WRONG_CODE).
```

**A success resets the counter** only where a check that a password alone cannot pass succeeds: an accepted second factor at sign-in, a confirmed enrolment, or an accepted proof on the profile page (current password, code or recovery code). A right password at the sign-in password step does **not** reset it. Otherwise someone who knows the password could guess codes forever.

### C8. Schemas (`app/auth/schemas.py`)

```python
class UserOut(BaseModel): id: UUID; name: str; email: str; is_owner: bool        # model_config from_attributes
class SessionStatusOut(BaseModel): status: Status; user: UserOut | None            # user only when active
class StatusOut(BaseModel): status: Status
class SetupIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+$")
    password: str = Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)
class LoginIn(BaseModel): email: str = Field(min_length=1, max_length=320); password: str = Field(min_length=1, max_length=1024)
Method = Literal["totp", "recovery_code"]
class CodeIn(BaseModel): code: str = Field(min_length=1, max_length=64); method: Method = "totp"
class EnrolIn(BaseModel): code: str | None = Field(default=None, max_length=64); method: Method = "totp"
class EnrolOut(BaseModel): secret: str; uri: str
class ConfirmIn(BaseModel): code: str = Field(min_length=1, max_length=64)
class ConfirmOut(BaseModel): recovery_codes: list[str] | None
class MeOut(BaseModel): user: UserOut; password_changed_at: datetime; totp_confirmed_at: datetime | None; recovery_codes_left: int
class SessionOut(BaseModel): id: UUID; current: bool; created_at: datetime; last_seen_at: datetime; ip: str | None; user_agent: str | None; mfa_method: str | None
class PasswordIn(BaseModel): current_password: str = Field(min_length=1, max_length=1024); new_password: str = Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)
class RecoveryCodesIn(BaseModel): code: str = Field(min_length=1, max_length=64)
class RecoveryCodesOut(BaseModel): recovery_codes: list[str]
```

`SetupIn.name` is stripped, and an empty name after stripping gets 422. Emails are `strip().lower()`ed in the service.

### C9. Routes (`app/auth/router.py`, `APIRouter(prefix="/auth")`, included into `api` in `create_app`)

| Route | Dependencies | 200 body |
|---|---|---|
| `GET /session` | `DbSession` | `SessionStatusOut` |
| `POST /setup` | `audited(OWNER_CREATED, SETUP_FAILED)` | `StatusOut("enrolment_required")` + cookie |
| `POST /login` | `audited(PASSWORD_ACCEPTED, SIGN_IN_FAILED)` | `StatusOut("mfa_required" or "enrolment_required")` + cookie |
| `POST /login/mfa` | `CurrentSession`, `audited(SIGN_IN, MFA_FAILED)` | `StatusOut("active")` + new cookie |
| `POST /mfa/enrol` | `CurrentSession`, `audited(MFA_ENROLMENT_STARTED, MFA_FAILED)` | `EnrolOut` |
| `POST /mfa/enrol/confirm` | `CurrentSession`, `audited(MFA_ENROLLED, MFA_FAILED)` | `ConfirmOut` (+ new cookie on first enrolment) |
| `POST /logout` | `CurrentSession`, `audited(SIGN_OUT)` | `StatusOut("signed_out")`, cookie cleared |
| `GET /me` | `CurrentUser` | `MeOut` |
| `GET /sessions` | `CurrentSession`, `CurrentUser` | `list[SessionOut]` |
| `DELETE /sessions/{session_id}` | `CurrentSession`, `CurrentUser`, `audited(SESSION_REVOKED)` | 204 |
| `POST /password` | `CurrentSession`, `CurrentUser`, `audited(PASSWORD_CHANGED)` | `StatusOut("active")` |
| `POST /recovery-codes` | `CurrentUser`, `audited(RECOVERY_CODES_CREATED, MFA_FAILED)` | `RecoveryCodesOut` |

```python
def refused(refusal: Refusal) -> JSONResponse:
    return JSONResponse({"detail": refusal.reason}, status_code=refusal.status)
```

### C10. Test fixtures and helpers

`backend/tests/conftest.py`, in `pytest_configure` before the `_own_file` early return? No: after it, beside `DB_NULL_POOL`. Add `os.environ["AUTH_SECRET_KEY"] = TEST_AUTH_SECRET_KEY` (a module constant). Fixtures:

```python
@pytest.fixture
async def clean_auth(empty_audit_log):
    # the owner deletes every account (sessions and codes cascade) and the setup code
    async with owner_session() as session:
        await session.execute(text("DELETE FROM auth_setup"))
        await session.execute(text("DELETE FROM users"))
        await session.commit()

class FakeClock:
    def __init__(self) -> None: self.now = datetime(2026, 11, 23, 12, 0, 5, tzinfo=UTC)
    def advance(self, **delta) -> None: self.now += timedelta(**delta)

@pytest.fixture
def clock(monkeypatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr("app.auth.clock.now", lambda: fake.now)
    return fake

@pytest.fixture
async def api(clean_auth, clock):
    from app.main import create_app
    transport = ASGITransport(app=create_app(), client=("127.0.0.1", 50000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
```

The `api` fixture is added in step 7, `clean_auth` and `clock` in step 6.

`backend/tests/auth_helpers.py`:

```python
EMAIL = "owner@example.com"; NAME = "Olive Owner"; PASSWORD = "correct horse battery staple"
async def make_user(*, email=EMAIL, name=NAME, password=PASSWORD, enrolled=True, is_owner=True,
                    recovery_codes: list[str] = ()) -> tuple[User, str | None]
    # inserts through SessionLocal (the API role); a TOTP secret encrypted with the test key when enrolled;
    # password_changed_at = clock.now(); returns the user and the plain secret
def code_for(secret: str, at: datetime) -> str            # pyotp.TOTP(secret).at(at)
async def sign_in(api, clock, secret: str, *, email=EMAIL, password=PASSWORD) -> None
    # POST /api/auth/login, then /api/auth/login/mfa with code_for(secret, clock.now); asserts 200 each;
    # then clock.advance(seconds=30) so the next code is a new time step
async def actions() -> list[str]                          # audit_log actions ordered by seq
async def events(action: str) -> list[AuditEvent]
async def load_user(email=EMAIL) -> User                  # fresh read through SessionLocal
async def put_setup_code(code: str, failed_attempts: int = 0) -> None   # upsert the auth_setup row (hash_code)
```

Step 7 creates `make_user`, `code_for`, `actions`, `events` and `load_user`. Step 8 adds `put_setup_code`, and step 11 adds `sign_in`.

### C11. Frontend library

```ts
// src/lib/auth/gate.ts (pure)
export type AuthStatus = "setup_required" | "signed_out" | "mfa_required" | "enrolment_required" | "active";
export type SessionUser = { id: string; name: string; email: string; is_owner: boolean };
export type SessionInfo = { status: AuthStatus; user: SessionUser | null };
export function safeNext(next: string | null | undefined): string | null
  // a string that starts with "/" and not with "//" or "/\\" → itself; else null
export function gateRedirect(status: AuthStatus | null, pathname: string, search = ""): string | null
  // null status = the backend did not answer → treated as signed_out
  // setup_required: "/setup" → null, else "/setup"
  // signed_out | mfa_required | enrolment_required | null: "/login" → null; "/" → "/login";
  //   else "/login?next=" + encodeURIComponent(pathname + search)
  // active: "/login" or "/setup" → "/", else null

// src/lib/auth/backend.ts (no next/headers: used by the proxy and by server.ts)
export const SESSION_COOKIE = "megoo_session";
export function backendUrl(): string    // process.env.BACKEND_URL ?? "http://localhost:8000"
export async function fetchSession(token: string | undefined): Promise<SessionInfo | null>
  // GET `${backendUrl()}/api/auth/session` with header cookie `megoo_session=<token>` when a token is given,
  // cache: "no-store", signal: AbortSignal.timeout(3000). Not ok, a bad body or a thrown error → null.

// src/lib/auth/navigate.ts
export function goTo(path: string): void   // window.location.assign(path)

// src/lib/api.ts
export class ApiError extends Error { constructor(readonly status: number, readonly detail: string) }
export async function apiFetch<T>(path: string, options?: { method?: string; body?: unknown }): Promise<T>
  // fetch(`/api${path}`, { method (default GET, or POST when a body is given), credentials: "same-origin",
  //   headers: body ? { "content-type": "application/json" } : undefined, body: JSON.stringify(body) })
  // a thrown fetch → ApiError(0, "unreachable"); 204 → undefined; ok → JSON
  // otherwise detail = typeof json.detail === "string" ? json.detail : "invalid"
  // 401 + "not_signed_in" while location.pathname is not "/login" or "/setup" →
  //   goTo("/login?next=" + encodeURIComponent(location.pathname + location.search)); then throw ApiError

// src/lib/auth/messages.ts
export function messageFor(detail: string): string
```

`messageFor` texts:

| Detail | Text |
|---|---|
| `invalid_credentials` | "The email or the password is wrong." |
| `wrong_code` | "That code is not right. Check the clock of your phone and try again." |
| `locked` | "This account is locked for 15 minutes after too many failed attempts." |
| `undecryptable` | "This account's authenticator cannot be checked any more. Ask the host's administrator to run make reset-mfa." |
| `wrong_setup_code` | "The setup code is not right." |
| `no_setup_code` | "There is no valid setup code. Run make setup-code on the host and enter the new code." |
| `wrong_password` | "The current password is wrong." |
| `not_signed_in` | "Your sign-in took too long. Start again." |
| `unreachable` | "The server is not answering. Try again in a moment." |
| `invalid` | "Check the fields and try again." |
| anything else | "Something went wrong. Try again." |

```ts
// src/lib/auth/server.ts (server components only)
export const getSession = cache(async (): Promise<SessionInfo | null> =>
  fetchSession((await cookies()).get(SESSION_COOKIE)?.value));
export async function requireUser(): Promise<SessionUser>   // not active → redirect("/login")
```

### C12. Auth components (props and visible text that tests target)

- `PasswordStep({ onDone(status: "mfa_required" | "enrolment_required"), notice?: string })`: Card titled "Sign in", inputs labelled "Email" (`autoComplete="username"`) and "Password" (`current-password`), button "Continue". Posts `/auth/login`. A refusal shows `messageFor(detail)` in an `Alert` (`role="alert"`). `notice` is shown above the form.
- `CodeStep({ onDone(), onUseRecovery(), onLocked(), onRestart(notice: string) })`: title "Enter your code", input "Code" (`inputMode="numeric"`, `autoComplete="one-time-code"`), button "Verify", link-buttons "Use a recovery code" and "Start again". Posts `/auth/login/mfa` `{code, method: "totp"}`. `locked` → `onLocked()`. `not_signed_in` → `onRestart(messageFor("not_signed_in"))`. Anything else → alert.
- `RecoveryStep({ onDone(), onUseCode(), onLocked(), onRestart(notice) })`: title "Use a recovery code", input "Recovery code" (placeholder `XXXX-XXXX-XXXX-XXXX`), button "Verify", link-button "Use your authenticator instead". Posts with `method: "recovery_code"`.
- `LockedNotice({ onBack() })`: title "Account locked". Text: "Too many failed attempts. Try again in 15 minutes, or ask the host's administrator to run make reset-password." Button "Back to sign-in".
- `EnrolStep({ enrolment?: Enrolment, onDone(codes: string[] | null), onRestart(notice) })`, with `type Enrolment = { secret: string; uri: string }`. Without `enrolment` it posts `/auth/mfa/enrol` `{}` on mount. Title "Set up your authenticator". Text: "Scan the QR code with an authenticator app, then enter the 6-digit code it shows." Shows `<QRCodeSVG value={uri} size={176} title="QR code for your authenticator" />`, then "Can't scan it? Enter this key:" and the secret in `font-mono` in groups of 4. Input "Code", button "Verify". Posts `/auth/mfa/enrol/confirm` and calls `onDone(body.recovery_codes)`.
- `RecoveryCodes({ codes: string[], onContinue(), continueLabel = "Continue" })`: title "Save your recovery codes". Text: "Each code signs you in once if you lose your authenticator. They are shown only now." The codes are a `font-mono` list. Button "Copy codes" (`navigator.clipboard.writeText(codes.join("\n"))`), checkbox "I have saved these codes", and the continue button, disabled until the box is ticked.
- `LoginFlow({ initialStep: LoginStep, next: string | null })`, with `type LoginStep = "password" | "code" | "recovery" | "locked" | "enrol" | "codes"` and the exported `initialStep(status?: AuthStatus): LoginStep` (`mfa_required` → "code", `enrolment_required` → "enrol", else "password"). The end of the flow calls `goTo(next ?? "/")`.
- `SetupFlow()`: shows "Step N of 3". Step 1 is the Card "Set up MegooITAdmin" with inputs "Setup code" (hint "Run make setup-code on the host, or look for it in the backend's log."), "Your name", "Email", "Password" (hint "12 to 128 characters."), "Repeat the password", and the button "Create the Owner account". Client checks: "Use 12 to 128 characters." and "The passwords do not match.". It posts `/auth/setup`; a 409 → `goTo("/login")`. Step 2 is `EnrolStep`, step 3 is `RecoveryCodes`, then `goTo("/")`.

## Steps

### 1. The backend requires AUTH_SECRET_KEY, and every stack and test set passes one

**Files:** `backend/pyproject.toml`, `backend/uv.lock`, `backend/app/core/config.py`, `backend/tests/conftest.py`, `backend/tests/test_settings.py`, `backend/docker-entrypoint.sh`, `backend/tests/test_container.py`, `docker-compose.yml`, `tools/test-services/docker-compose.image.yml`, `megoocolab.toml`, `tools/stacks/dev.env`, `tools/stacks/e2e.env`, `.env.example`.

1. Run `cd backend && uv add argon2-cffi pyotp cryptography`.
2. Tests first, in `backend/tests/test_settings.py`:
   - `test_auth_secret_key_is_required`: `delenv("AUTH_SECRET_KEY")` → `ValidationError` that mentions `auth_secret_key`.
   - `test_auth_secret_key_must_be_64_hex_characters`: parametrize over `"abc"`, `"zz"*32` and `"00"*33` → `ValidationError` whose text contains `AUTH_SECRET_KEY must be 64 hexadecimal characters`.
   - `test_auth_key_is_32_bytes_and_upper_case_is_accepted`: `Settings(database_url=URL, auth_secret_key="AB"*32).auth_key() == bytes.fromhex("ab"*32)`.
   - `test_session_and_docs_settings_have_their_defaults` (60, 720, False), and `test_session_settings_come_from_the_environment` (`SESSION_IDLE_MINUTES=5`, `API_DOCS=true`).
   - `test_the_key_is_not_in_the_repr`.
   Run **BT tests/test_settings.py**. The new tests fail: the fields don't exist.
3. Implement C1. In `tests/conftest.py`, add `TEST_AUTH_SECRET_KEY` and set `os.environ["AUTH_SECRET_KEY"]` beside `DB_NULL_POOL`. Run **BT tests/test_settings.py**: they pass.
4. Wire the key through:
   - `docker-compose.yml` backend `environment`: `AUTH_SECRET_KEY: ${AUTH_SECRET_KEY:?AUTH_SECRET_KEY is not set. Run make up or see .env.example}`, `SESSION_IDLE_MINUTES: ${SESSION_IDLE_MINUTES:-60}`, `SESSION_ABSOLUTE_MINUTES: ${SESSION_ABSOLUTE_MINUTES:-720}`, `API_DOCS: ${API_DOCS:-false}`.
   - `tools/test-services/docker-compose.image.yml`: `AUTH_SECRET_KEY: <test key>`.
   - `megoocolab.toml`: `AUTH_SECRET_KEY = "<test key>"` in `[services.migrate.env]` (Alembic's `env.py` builds `Settings`) and in `[services.stack.env]`.
   - `tools/stacks/dev.env` and `e2e.env`: `AUTH_SECRET_KEY=<test key>`.
   - `.env.example`: a commented `AUTH_SECRET_KEY=` paragraph: it encrypts the authenticator secrets, `make up` writes it, keep it (without it nobody can sign in with their code), and it is 64 hex characters. Also commented `#SESSION_IDLE_MINUTES=60`, `#SESSION_ABSOLUTE_MINUTES=720` and `#API_DOCS=false` with one line each.
5. Container test first, in `backend/tests/test_container.py`: add `"AUTH_SECRET_KEY": TEST_KEY` to the env of both existing `_run_once` calls. Add `test_it_refuses_to_serve_without_the_auth_secret_key`: `_run_once` with only the two URLs → returncode != 0, `"AUTH_SECRET_KEY is not set"` in the output, and `"Uvicorn running"` not in it. Then add as the first command of `docker-entrypoint.sh`, after `set -e`: `: "${AUTH_SECRET_KEY:?AUTH_SECRET_KEY is not set: run make up, or see .env.example}"`, with a comment.
6. Run **BACKEND**, **DOCKER** and **STACK**: all pass.

Commit: `feat(backend): the backend needs AUTH_SECRET_KEY to start`

### 2. make up adds AUTH_SECRET_KEY to .env

**Files:** `Makefile`, `backend/tests/test_makefile.py`.

1. Tests first, in `test_makefile.py`:
   - `test_the_env_rule_writes_two_random_passwords_only_its_owner_can_read` becomes `…writes_two_random_passwords_and_a_key_only_its_owner_can_read`, with the regex `POSTGRES_PASSWORD=([0-9a-f]{32})\nPOSTGRES_API_PASSWORD=([0-9a-f]{32})\nAUTH_SECRET_KEY=([0-9a-f]{64})\n`.
   - `test_the_env_rule_adds_the_api_password_to_an_older_env`: the appended part is `POSTGRES_API_PASSWORD=[0-9a-f]{32}\nAUTH_SECRET_KEY=[0-9a-f]{64}\n`, and the output holds both "Added POSTGRES_API_PASSWORD" and "Added AUTH_SECRET_KEY".
   - New `test_the_env_rule_adds_only_the_key_to_an_env_with_both_passwords`.
   - `test_the_env_rule_puts_the_added_line_on_a_line_of_its_own`: the regex now also holds the key line.
   - `test_the_env_rule_leaves_a_complete_env_untouched` uses a file with all three lines.
   Run **BT tests/test_makefile.py**: these fail.
2. Rewrite the `.env` rule:
   - A missing file: three values (`od -An -N32 -tx1 /dev/urandom | tr -d ' \n'` for the key), checked together with `grep -Eqx '[0-9a-f]{128}'`, written with `umask 077`.
   - Otherwise: two independent `if ! grep -q '^NAME=' .env` blocks (the existing API password block, then the key block). Each checks its random value, adds a missing final newline first, and appends one line. The key block prints `Added AUTH_SECRET_KEY to .env: it encrypts the authenticator secrets. Keep this file.`
   Update the comment above the rule.
3. Run **BT tests/test_makefile.py**: it passes.

Commit: `feat(make): make up adds AUTH_SECRET_KEY to .env`

### 3. The API docs are served only with API_DOCS=true

**Files:** `backend/app/main.py`, `backend/tests/test_health.py`, `tools/stacks/dev.env`.

1. Tests first:
   - `test_the_docs_are_not_served_by_default` (`/api/docs` and `/api/openapi.json` → 404).
   - `test_the_docs_are_served_with_api_docs` uses `create_app(Settings(database_url=os.environ["DATABASE_URL"], api_docs=True))` and expects 200 for both, with `/api/health` in the paths. It replaces `test_the_openapi_document_lists_api_health`.
   Run **BT tests/test_health.py**: it fails.
2. `create_app(settings: Settings | None = None)`: `settings = settings or get_settings()`. Pass `openapi_url`, `docs_url` and `swagger_ui_oauth2_redirect_url` only when `settings.api_docs`, and None otherwise. Keep `redoc_url=None` and the comments. Add `API_DOCS=true` to `tools/stacks/dev.env`.
3. Run **BT tests/test_health.py tests/security**: it passes.

Commit: `feat(backend): the API docs are served only with API_DOCS=true`

### 4. Password hashing and TOTP checks

**Files:** `backend/app/auth/__init__.py` (docstring: "Local accounts: passwords, a mandatory second factor and sessions."), `backend/app/auth/passwords.py`, `backend/app/auth/totp.py`, `backend/tests/auth/test_passwords.py`, `backend/tests/auth/test_totp.py`.

1. Tests first (contracts C2). In `test_passwords.py`:
   - `test_a_hash_verifies_and_a_wrong_password_does_not`
   - `test_the_hash_is_argon2id` (`startswith("$argon2id$")`)
   - `test_the_rule_refuses_11_and_129_characters_and_accepts_12_and_128`
   - `test_an_old_parameter_hash_needs_a_rehash` (`argon2.PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(...)`)
   - `test_verify_returns_false_for_a_malformed_hash`
   - `test_verify_dummy_runs_without_error`

   In `test_totp.py`, the RFC 6238 SHA-1 vectors with secret `GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ`, parametrized over (unix time, code): (59, "287082"), (1111111109, "081804"), (1111111111, "050471"), (1234567890, "005924"), (2000000000, "279037"), (20000000000, "353130"). `verify(...)` returns `t // 30`. Also:
   - `test_one_step_of_drift_either_way_is_accepted`
   - `test_two_steps_of_drift_are_refused`
   - `test_a_used_step_and_an_earlier_one_are_refused` (last_step)
   - `test_spaces_are_ignored_and_letters_refused`
   - `test_the_uri_names_the_issuer_and_the_email` (`otpauth://totp/MegooITAdmin:owner%40example.com?secret=…&issuer=MegooITAdmin`)
   - `test_a_new_secret_is_32_base32_characters`
   Run **BT tests/auth/test_passwords.py tests/auth/test_totp.py**: ImportError.
2. Implement `passwords.py` and `totp.py` exactly as C2, with a module docstring each.
3. Run the same command: it passes.

Commit: `feat(auth): Argon2id passwords and TOTP checks without replay`

### 5. The clock, the secret encryption and recovery codes

**Files:** `backend/app/auth/clock.py`, `backend/app/auth/crypto.py`, `backend/app/auth/recovery.py`, `backend/tests/auth/test_crypto.py`, `backend/tests/auth/test_recovery.py`.

1. Tests first. In `test_crypto.py`:
   - `test_a_secret_round_trips`
   - `test_another_users_id_does_not_decrypt` (raises `SecretUndecryptable`)
   - `test_a_changed_key_does_not_decrypt`
   - `test_two_encryptions_differ` (random nonce)
   - `test_a_truncated_blob_does_not_decrypt`
   - `test_the_ciphertext_does_not_hold_the_secret`

   In `test_recovery.py`:
   - `test_a_code_has_the_shown_format_and_80_bits` (fullmatch `CODE_PATTERN`; 16 base32 characters)
   - `test_codes_differ`
   - `test_normalise_ignores_case_dashes_and_spaces`
   - `test_the_hash_is_sha256_of_the_normalised_code` (and the same hash for `"abcd-efgh-ijkl-mnop"` and `"ABCDEFGHIJKLMNOP"`)
   Run **BT tests/auth/test_crypto.py tests/auth/test_recovery.py**: ImportError.
2. Implement them as C2. `clock.py` is `now()` with a docstring saying the tests replace it.
3. Run it again: it passes.

Commit: `feat(auth): TOTP secrets are encrypted with AUTH_SECRET_KEY, recovery codes are stored as hashes`

### 6. Tables for accounts, sessions, recovery codes and the setup code (migration 0004)

**Files:** `backend/app/auth/models.py`, `backend/app/models.py`, `backend/migrations/versions/0004_auth.py`, `backend/tests/test_migrations.py`, `backend/tests/security/test_db_privileges.py`, `backend/tests/conftest.py` (`clean_auth`, `FakeClock`, `clock` from C10).

1. Tests first:
   - `test_db_privileges.py`: in `API_GRANTS` add `"users": {"SELECT","INSERT","UPDATE"}` and `"auth_sessions"`, `"recovery_codes"`, `"auth_setup"`: `{"SELECT","INSERT","UPDATE","DELETE"}`.
   - `test_migrations.py`: add `test_0004_goes_down_and_up_again_with_the_auth_tables`. `command.downgrade(_config(), "0003")` → `to_regclass` is None for all four. Then `upgrade_to_head()` → all four exist, `has_table_privilege('megooitadmin_api','users','DELETE')` is False, and the same for `'auth_sessions','DELETE'` is True.
   Run **BT tests/test_migrations.py tests/security/test_db_privileges.py**: it fails.
2. Write `app/auth/models.py` as C3, and import it in `app/models.py`. Generate with `make migration name=auth`, which writes `backend/migrations/versions/0004_auth.py`. Then edit it: the constraint names as in C3, the grants from C3 after the tables, a docstring line `auth: accounts, sessions, recovery codes and the setup code`, and a downgrade that drops `recovery_codes`, `auth_sessions`, `auth_setup` and `users`.
3. Run **MIGRATE-CHECK**, then **BT tests/test_migrations.py tests/security/test_db_privileges.py**: it passes, and `test_the_models_match_the_migrations` stays green.
4. Add the `clean_auth` and `clock` fixtures (C10). They are used from step 7 on.

Commit: `feat(auth): tables for accounts, sessions, recovery codes and the setup code`

### 7. Sessions, the session dependencies, GET /api/auth/session and the auth-coverage suite

**Files:** `backend/app/auth/actions.py` (C4), `sessions.py`, `deps.py` (C6), `schemas.py` (`UserOut`, `SessionStatusOut`, `StatusOut`), `service.py` (`Status`, `status_of`), `router.py` (`GET /session`), `backend/app/main.py`, `backend/tests/conftest.py` (`api`), `backend/tests/auth_helpers.py`, `backend/tests/auth/test_sessions.py`, `backend/tests/auth/test_status.py`, `backend/tests/security/routes.py`, `backend/tests/security/test_auth_coverage.py`.

`service.status_of(db, token) -> tuple[Status, User | None]`:
- No row in `users` → `("setup_required", None)`.
- Otherwise `lookup_session` → none: `signed_out`; active: `active` with the user; pending: `mfa_required` if `user.totp_secret` is set, else `enrolment_required`.
- The route returns the user only for `active`.

1. Tests first. `test_sessions.py` (with `clean_auth` and `clock`):
   - `test_a_session_is_found_by_its_token_and_only_its_hash_is_stored`
   - `test_an_active_session_ends_after_an_hour_without_a_request` (the row is gone)
   - `test_a_request_every_50_minutes_keeps_it_alive`
   - `test_an_active_session_ends_twelve_hours_after_sign_in`
   - `test_a_pending_session_ends_after_ten_minutes`
   - `test_last_seen_at_moves_at_most_once_a_minute`
   - `test_end_sessions_keeps_the_given_one`
   - `test_delete_expired_removes_only_expired_rows`
   - `test_the_cookie_is_httponly_lax_path_root_with_the_absolute_max_age` (a Starlette `Response` and a `Request` scope with scheme `http`: no `Secure`)
   - `test_the_cookie_is_secure_under_https`
   - `test_clear_cookie_expires_it`
   - `test_a_pending_session_cannot_call_a_current_user_route`: a sample `FastAPI()` with a `GET /probe` that depends on `CurrentUser` → 401 `{"detail": "not_signed_in"}`, and 200 with an active session.
   - `test_an_expired_pending_session_records_mfa_failed_expired`

   `test_status.py` (`api`): one test for each of the five statuses, plus `user` only for `active`.

   `test_auth_coverage.py` with:
   ```python
   PUBLIC = {"GET /api/health": "…", "GET /api/auth/session": "…"}
   PENDING: dict[str, str] = {}
   ```
   and these tests:
   - `test_every_route_needs_an_active_session_or_is_pinned`
   - `test_the_pinned_lists_name_only_real_routes`
   - `test_the_check_reports_an_unprotected_route_of_a_sample_app`: a sample app with an unprotected route, a `Depends(current_user)` route, a router included with `dependencies=[Depends(current_user)]`, and a `current_session` route that is reported unless it is in pending.
   Run **BT tests/auth tests/security**: it fails.
2. In `routes.py`, add `dependency_calls(context)`. It walks `context.original_route.dependant` recursively, and `fastapi.dependencies.utils.get_dependant(path=context.path, call=d.dependency)` for each `d` of `context.dependencies` whose `dependency` is not None, collecting `.call`. Then add `session_requirement(context) -> "active" | "pending" | "none"` and `unguarded_routes(app, public, pending) -> list[str]` (sorted `"METHOD /path (requirement)"`).
3. Implement the modules. Include the router in `create_app`: `api.include_router(auth_router)` before `app.include_router(api)`.
4. Run **BT tests/auth tests/security tests/test_health.py**: it passes.

Commit: `feat(auth): sessions are rows keyed by a token hash, and every route needs one`

### 8. POST /api/auth/setup creates the Owner with the one-time setup code

**Files:** `service.py` (`setup`), `router.py`, `schemas.py` (`SetupIn`), `backend/tests/auth_helpers.py` (`put_setup_code`), `backend/tests/auth/test_setup.py`, `backend/tests/security/test_auth_coverage.py` (`PUBLIC` gets `"POST /api/auth/setup"`).

`service.setup(db, request, body) -> tuple[User, str] | Refusal`:
1. `row = SELECT SetupCode WHERE id = 1 FOR UPDATE`.
2. If there is no row: if a user exists, raise `HTTPException(409, "setup_closed")`. Otherwise record `SETUP_FAILED` (FAILURE, `{"reason": "no_code"}`) and return `Refusal(401, "no_setup_code")`.
3. If `hmac.compare_digest(hash_code(body.code), row.code_hash)` fails: `failed_attempts += 1`. At 5, delete the row and the reason is `no_setup_code`; otherwise it is `wrong_setup_code`. Record `SETUP_FAILED` (`{"reason": "wrong_code"}`) and return `Refusal(401, …)`.
4. Otherwise: hash the password, add `User(email=lower, name, is_owner=True, password_changed_at=now)`, flush, delete the row, `create_session(stage="pending")`, and record `OWNER_CREATED` (actor and target = the user, mfa False).

The actor of a failure is `Actor(type=ActorType.HUMAN, name=(email.strip()[:254] or "unknown"))`.

1. Tests first in `test_setup.py`:
   - `test_a_wrong_code_is_refused_and_counted`
   - `test_the_fifth_wrong_code_deletes_it`
   - `test_without_a_code_setup_is_refused`
   - `test_the_right_code_creates_the_owner_and_a_pending_session` (lower-cased email, cookie set, `auth_setup` empty, `GET /session` → `enrolment_required`, event `auth.owner_created`)
   - `test_a_second_setup_gets_409`
   - `test_two_setups_at_once_create_one_owner` (`asyncio.gather` on two clients → {200, 409})
   - `test_a_short_password_gets_422`
   Run **BT tests/auth/test_setup.py**: it fails.
2. Implement it. The route is `POST /setup`, `response_model=StatusOut`, `audited(OWNER_CREATED, SETUP_FAILED)`. It sets the cookie on success and returns `refused(r)` otherwise.
3. Run **BT tests/auth tests/security**: it passes.

Commit: `feat(auth): the first Owner is created on the setup page with a one-time code`

### 9. The setup-code host command, at start-up and as make setup-code

**Files:** `backend/app/auth/cli.py`, `backend/docker-entrypoint.sh`, `backend/tests/auth/test_cli.py`, `backend/tests/test_container.py`, `Makefile`, `backend/tests/test_makefile.py`.

`cli.py`:
- `async def create_setup_code(*, if_no_account: bool) -> int`:
  - An account exists: with the flag, print nothing and return 0. Without it, print `An account exists already, so setup is closed.` to stderr and return 1.
  - Otherwise delete any `auth_setup` row, insert `SetupCode(id=1, code_hash=hash_code(code))`, record `SETUP_CODE_CREATED` (actor `Actor.system("cli")`, no source), commit, and print `Setup code: <code>` and `Enter it on the setup page of MegooITAdmin. It works until the Owner account exists.`
- `def main(argv: list[str] | None = None) -> int`: argparse `prog="python -m app.auth.cli"` with the subcommand `setup-code [--if-no-account]`. It runs the coroutine with `asyncio.run(_run(coro))`, where `_run` awaits it and then `await engine.dispose()`. Add `if __name__ == "__main__": sys.exit(main())`.

1. Tests first. In `test_cli.py`:
   - `test_setup_code_prints_a_code_that_setup_accepts` (`capsys`; regex `Setup code: (CODE_PATTERN)`; the stored hash matches; event `auth.setup_code_created` with `actor_type == "system"`)
   - `test_a_new_setup_code_replaces_the_old_one`
   - `test_setup_code_refuses_once_an_account_exists`
   - `test_if_no_account_is_silent_once_an_account_exists`
   - `test_main_passes_the_flag`: a sync test that monkeypatches `cli.create_setup_code` with an async fake.

   In `test_container.py`: `test_the_log_of_a_fresh_install_holds_a_setup_code`. Find the container with `docker ps -q --filter label=com.docker.compose.project=<MEGOO_SERVICES_PROJECT> --filter label=com.docker.compose.service=backend`, then `docker logs` it, and search with the regex `Setup code: [A-Z2-7]{4}(-[A-Z2-7]{4}){3}`.

   In `test_makefile.py`: `test_setup_code_runs_the_command_in_the_chosen_stack` (`make -n setup-code STACK=dev` prints `docker compose -p megooitadmin-dev --env-file tools/stacks/dev.env exec backend python -m app.auth.cli setup-code`), and add `setup-code` to `TARGETS`.

   Run **BT tests/auth/test_cli.py tests/test_makefile.py**: it fails.
2. Implement `cli.py`. In the entrypoint, after the password step add `echo "Checking for a setup code..."` and `python -m app.auth.cli setup-code --if-no-account`. In the Makefile, add the `setup-code` target (`$(COMPOSE) exec backend python -m app.auth.cli setup-code`), its help line and `.PHONY`.
3. Run **BT tests/auth tests/test_makefile.py**, then **DOCKER**: it passes.

Commit: `feat(auth): the backend logs a setup code on a fresh install, and make setup-code prints a new one`

### 10. POST /api/auth/login: the password step, the lockout and the dummy check

**Files:** `service.py` (C7 helpers, and `login`), `router.py`, `schemas.py` (`LoginIn`), `backend/tests/auth/test_login.py`, `test_auth_coverage.py` (`PUBLIC` gets `"POST /api/auth/login"`).

`service.login(db, request, body) -> tuple[str, Status] | Refusal`:
1. `email = body.email.strip().lower()`. `user = SELECT User WHERE email FOR UPDATE`.
2. None → `verify_dummy`, record `SIGN_IN_FAILED` (actor name = the email as typed, cut to 254; `{"reason": "unknown_account"}`), and return `Refusal(401, "invalid_credentials")`.
3. `is_locked` → record `SIGN_IN_FAILED` with `{"reason": "locked"}`, without checking the password, and refuse with `invalid_credentials`.
4. A wrong password → `fail_attempt(action=SIGN_IN_FAILED, reason="wrong_password", mfa=False)`, and refuse with `invalid_credentials`.
5. A right password: `needs_rehash` → store a new hash; `delete_expired(user.id)`; `create_session(stage="pending")`; record `PASSWORD_ACCEPTED`. Return the token and `mfa_required` (secret set) or `enrolment_required`.

The password is checked before any `record()` call.

1. Tests first, in `test_login.py`:
   - `test_the_right_password_gives_a_pending_session_and_mfa_required`
   - `test_an_account_without_an_authenticator_gets_enrolment_required`
   - `test_the_email_is_case_insensitive`
   - `test_a_wrong_password_and_an_unknown_email_get_the_same_answer` (same status and body; the unknown event has `actor_id` None and `actor_name` = the email; `verify_dummy` was called, checked with a monkeypatched spy)
   - `test_five_wrong_passwords_lock_the_account` (event `auth.account_locked`)
   - `test_a_locked_account_refuses_the_right_password_with_the_same_message` (event reason `locked`)
   - `test_the_lock_ends_after_15_minutes_and_the_counter_starts_at_0`
   - `test_a_right_password_does_not_reset_the_counter`
   - `test_an_old_hash_is_rehashed_at_sign_in`
   - `test_expired_sessions_of_the_user_are_deleted_at_sign_in`
   - `test_the_cookie_is_not_secure_over_http`
   - `test_the_cookie_is_secure_over_https` (`base_url="https://test"`)
   - `test_no_event_holds_the_password`
   Run **BT tests/auth/test_login.py**: it fails.
2. Implement it.
3. Run **BT tests/auth tests/security**: it passes.

Commit: `feat(auth): the password step, with lockout after five failures`

### 11. POST /api/auth/login/mfa: the code step with TOTP or a recovery code

**Files:** `service.py` (`check_second_factor`, `verify_second_factor`), `router.py`, `schemas.py` (`CodeIn`), `auth_helpers.py` (`sign_in`), `backend/tests/auth/test_code_step.py`, `test_auth_coverage.py` (`PENDING` gets `"POST /api/auth/login/mfa"`).

`verify_second_factor(db, request, session, body) -> str | Refusal`:
1. A session that is already active → raise 409 `already_signed_in`. `user = lock_user`. No `totp_secret` → raise 409 `not_enrolled`.
2. Locked → record `MFA_FAILED` `{"reason": "locked", "method": m}` and return `Refusal(401, "locked")`.
3. `check_second_factor`. `undecryptable` → record `MFA_FAILED` with that reason, without counting, and return `Refusal(401, "undecryptable")`. `wrong_code` → `locked = fail_attempt(action=MFA_FAILED, reason="wrong_code", method=m, mfa=False)`, and return `Refusal(401, "locked" if locked else "wrong_code")`.
4. Success → `register_success`, delete the pending session, `create_session(stage="active", mfa_method=m)`, record `MFA_USED` (`{"method": m}`, mfa True), then `SIGN_IN`. The route sets the new cookie.

1. Tests first, in `test_code_step.py`:
   - `test_password_then_code_gives_an_active_session_under_a_new_token` (the old pending row is gone; events `password_accepted`, `mfa_used`, `sign_in`)
   - `test_a_code_cannot_be_used_twice`
   - `test_a_wrong_code_is_refused_and_counted`
   - `test_wrong_passwords_and_codes_share_the_counter` (3 + 2 → `locked`)
   - `test_a_success_resets_the_counter`
   - `test_a_recovery_code_signs_in_once` (`mfa_method == "recovery_code"`, the row is deleted, the second use is refused)
   - `test_a_locked_account_cannot_finish_the_sign_in`
   - `test_an_undecryptable_secret_is_refused_without_counting`
   - `test_an_unenrolled_account_gets_409`
   - `test_an_active_session_gets_409`
   - `test_after_ten_minutes_the_code_step_answers_not_signed_in`
   Run **BT tests/auth/test_code_step.py**: it fails.
2. Implement it, and add `sign_in` to `auth_helpers.py`.
3. Run **BT tests/auth tests/security**: it passes.

Commit: `feat(auth): the code step finishes the sign-in with a TOTP or a recovery code`

### 12. Authenticator enrolment and replacement

**Files:** `service.py` (`start_enrolment`, `confirm_enrolment`), `router.py`, `schemas.py` (`EnrolIn`, `EnrolOut`, `ConfirmIn`, `ConfirmOut`), `backend/tests/auth/test_enrolment.py`, `test_auth_coverage.py` (`PENDING` gets the two routes).

`start_enrolment(db, request, session, body) -> EnrolOut | Refusal`. `user = lock_user`.
- Pending: a set `totp_secret` → raise 409 `already_enrolled`. No proof is needed.
- Active: `body.code` None → raise 422 `code_required`. Locked → record `MFA_FAILED` locked and return `Refusal(401, "locked")`. Otherwise `check_second_factor(body.code, body.method)`. On failure, `fail_attempt(MFA_FAILED, mfa=True)`, and `undecryptable` is not counted. On success, `register_success`.
- Then `secret = new_secret()`, `user.totp_pending_secret = encrypt_secret(...)`, record `MFA_ENROLMENT_STARTED`, and return `{secret, uri}`.

`confirm_enrolment(db, request, session, body) -> tuple[list[str] | None, str | None] | Refusal`. `user = lock_user`.
- No pending secret → raise 409 `no_enrolment`. Locked → `Refusal(401, "locked")` with an event.
- `totp.verify(pending, code, None, now)` None → `fail_attempt(MFA_FAILED, reason="wrong_code")`.
- OK → `totp_secret = pending`, `totp_pending_secret = None`, `totp_confirmed_at = now`, `totp_last_step = step`, `register_success`.
- Pending stage: replace the recovery codes with 10 new ones, delete the pending session, `create_session(stage="active", mfa_method="totp")`, and record `MFA_ENROLLED` then `SIGN_IN`. Return `(codes, token)`.
- Active stage: `end_sessions(keep=session.id)`, record `MFA_ENROLLED` and one `SESSION_REVOKED` (target `Target(type="auth_session", id=str(s.id))`) for each ended session. Return `(None, None)`.

1. Tests first, in `test_enrolment.py`:
   - `test_an_account_without_an_authenticator_enrols_and_gets_ten_codes` (codes match `CODE_PATTERN`; the session is active under a new cookie; `GET /session` → active)
   - `test_the_pending_secret_is_stored_encrypted`
   - `test_a_wrong_confirmation_code_is_refused_and_counted`
   - `test_an_enrolled_pending_session_gets_409`
   - `test_replacing_needs_a_current_code` (no code → 422; wrong code → 401 and counted)
   - `test_replacing_with_a_recovery_code_uses_it_up`
   - `test_replacing_ends_the_other_sessions_and_keeps_this_one`
   - `test_after_replacing_the_old_secret_no_longer_signs_in`
   - `test_confirm_without_a_started_enrolment_gets_409`
   Run **BT tests/auth/test_enrolment.py**: it fails.
2. Implement it.
3. Run **BT tests/auth tests/security**: it passes.

Commit: `feat(auth): enrolment of the authenticator, with ten recovery codes`

### 13. Sign-out, and the person's own sessions

**Files:** `service.py` (`logout`, `list_sessions`, `revoke_session`), `router.py` (`POST /logout`, `GET /me`, `GET /sessions`, `DELETE /sessions/{session_id}`), `schemas.py` (`MeOut`, `SessionOut`), `backend/tests/auth/test_own_sessions.py`, `test_auth_coverage.py` (`PENDING` gets `"POST /api/auth/logout"`).

- Logout: delete the session, record `SIGN_OUT` (mfa = the session was active), `clear_cookie`, and return `{status: "signed_out"}`.
- `/me`: `recovery_codes_left` = the count of the user's `recovery_codes`.
- `/sessions`: the user's active, unexpired sessions (`is_expired` false; nothing deleted), newest first, `current = s.id == session.id`. `ip` is given as `str`.
- Revoke: `session_id == session.id` → raise 409 `current_session`. A row that is not the user's, or no row → raise 404 `not_found`. Otherwise delete it and record `SESSION_REVOKED`.

1. Tests first, in `test_own_sessions.py`:
   - `test_sign_out_deletes_the_session_and_clears_the_cookie` (event `auth.sign_out`; `GET /session` → signed_out)
   - `test_a_pending_session_can_sign_out`
   - `test_me_shows_the_user_and_the_second_factor`
   - `test_sessions_lists_the_persons_sessions_and_marks_this_one`
   - `test_revoke_ends_another_session`
   - `test_revoke_refuses_the_current_session`
   - `test_revoke_answers_404_for_someone_elses_session` (a second user made with `make_user(email="other@example.com", is_owner=False)`)
   - `test_me_needs_an_active_session`
   Run **BT tests/auth/test_own_sessions.py**: it fails.
2. Implement it.
3. Run **BT tests/auth tests/security**: it passes.

Commit: `feat(auth): sign-out, and a person can see and end their own sessions`

### 14. Change the password and create new recovery codes

**Files:** `service.py` (`change_password`, `new_recovery_codes`), `router.py`, `schemas.py` (`PasswordIn`, `RecoveryCodesIn`, `RecoveryCodesOut`), `backend/tests/auth/test_password_change.py`.

`change_password`: `user = lock_user`.
- Locked → record `PASSWORD_CHANGED` FAILURE `{"reason": "locked"}` and return `Refusal(401, "locked")`.
- A wrong current password → `fail_attempt(action=PASSWORD_CHANGED, reason="wrong_password", mfa=True)`, and return `Refusal(401, "locked" if locked else "wrong_password")`.
- OK → hash the new password, set `password_changed_at = now`, `register_success`, `end_sessions(keep=session.id)`, record `PASSWORD_CHANGED`, then a `SESSION_REVOKED` for each ended session.

`new_recovery_codes`:
- Locked → `MFA_FAILED` locked.
- `check_second_factor(code, "totp")` fails → `fail_attempt(MFA_FAILED, mfa=True)`.
- OK → `register_success`, delete all codes, insert 10, and record `RECOVERY_CODES_CREATED` `{"count": 10}`.

1. Tests first, in `test_password_change.py`:
   - `test_a_wrong_current_password_is_refused_and_counted`
   - `test_a_password_change_ends_the_other_sessions_and_keeps_this_one`
   - `test_the_new_password_signs_in_and_the_old_does_not`
   - `test_a_short_new_password_gets_422`
   - `test_new_recovery_codes_replace_the_old_ones`
   - `test_new_recovery_codes_need_a_current_code`
   - `test_five_failures_on_the_profile_lock_the_account_and_open_sessions_stay`
   Run **BT tests/auth/test_password_change.py**: it fails.
2. Implement it.
3. Run **BT tests/auth tests/security**: it passes.

Commit: `feat(auth): a person can change their password and create new recovery codes`

### 15. Host commands reset-mfa and reset-password

**Files:** `backend/app/auth/cli.py`, `backend/tests/auth/test_cli.py`, `Makefile`, `backend/tests/test_makefile.py`.

- `async def reset_mfa(email) -> int`: unknown email → stderr `No account has the email <email>.` and return 1. Otherwise clear `totp_secret`, `totp_pending_secret`, `totp_confirmed_at` and `totp_last_step`, delete the recovery codes and `end_sessions`, record `MFA_RESET` (actor `Actor.system("cli")`, target the user, `{"sessions_ended": n}`), and print `The second factor of <email> is reset and <n> sessions ended. They set up a new authenticator at their next sign-in.`
- `async def reset_password(email, password) -> int`: `check_rule`, hash, `password_changed_at = now`, `failed_attempts = 0`, `locked_until = None`, `end_sessions`, and record `PASSWORD_CHANGED` (`{"by": "cli", "sessions_ended": n}`). Print `The password of <email> is changed, the account is unlocked and <n> sessions ended.`
- `main` gets `reset-mfa EMAIL` and `reset-password EMAIL`. For `reset-password` it reads `getpass.getpass("New password: ")` and `getpass.getpass("Repeat it: ")`. A mismatch → `The passwords do not match.` and 1. A `PasswordRuleError` → its message and 1.
- Makefile: each target first checks the email from the environment, then runs the command:
  ```
  @case "$$email" in ''|*[!A-Za-z0-9.@_+-]*|*@*@*) echo "make reset-mfa needs an email, for example: make reset-mfa email=owner@example.com" >&2; exit 1;; esac
  $(COMPOSE) exec backend python -m app.auth.cli reset-mfa "$(email)"
  ```
  `reset-password` is the same. Add the help lines and `.PHONY`.

1. Tests first. In `test_cli.py`:
   - `test_reset_mfa_forces_enrolment_at_the_next_sign_in` (after it, a login → `enrolment_required`)
   - `test_reset_mfa_ends_the_sessions_and_records_its_event`
   - `test_reset_mfa_of_an_unknown_email_fails`
   - `test_reset_password_sets_the_password_and_clears_the_lock`
   - `test_reset_password_refuses_a_short_password`
   - `test_main_reset_password_asks_twice_and_refuses_a_mismatch` (monkeypatched `getpass.getpass` and a fake `reset_password`)

   In `test_makefile.py`: add `"email"` to the variables `make()` removes; `test_the_reset_targets_run_their_command_in_the_chosen_stack` (parametrize `reset-mfa` and `reset-password`; `-n … email=a@b.c STACK=dev` prints `… exec backend python -m app.auth.cli reset-mfa "a@b.c"`); and `test_a_reset_target_without_a_valid_email_runs_nothing` (a fake `docker` on PATH that touches a file, like the migration test; args `[]`, `["email="]`, `["email=a;b"]`). Add both targets to `TARGETS`.

   Run **BT tests/auth/test_cli.py tests/test_makefile.py**: it fails.
2. Implement it.
3. Run it again, then **BT tests/auth tests/security**: it passes.

Commit: `feat(auth): host commands reset a lost authenticator or a forgotten password`

### 16. Security suite: every auth event is recorded and none holds a secret

**Files:** `backend/tests/security/test_auth_events.py`, `AGENTS.md`.

`test_one_walk_records_every_auth_action_and_no_secret` (fixtures `api` and `clock`; drive the routes and the `cli` coroutines in-process):
1. `cli.create_setup_code` (capture the code) → a wrong `/setup` → the right `/setup` → `/mfa/enrol` and confirm.
2. `/logout` → a login with an unknown email → a wrong password → a login and a wrong code → a recovery code → a second login in another `AsyncClient`, revoked from the first.
3. `/password`, `/recovery-codes`, `/mfa/enrol` and confirm with a current code (replacement) → five wrong passwords (lock) → `cli.reset_password` → `cli.reset_mfa`.
4. Then assert:
   - `set(actions()) == ALL_ACTIONS`.
   - `verify_chain(session).ok`.
   - For every `audit_log` row, `json.dumps` of all its text and JSON columns holds none of: both passwords, the TOTP secrets, every code typed or returned (normalised, and as shown), the setup code, and every `megoo_session` cookie value seen.

Add the walk's steps as small helper functions in the file, so the test reads as a list.

1. Write the test and run **SECURITY**. It should pass on the first run, because it is a regression suite over steps 7–15. If it fails, fix the flow it found, not the test.
2. In `AGENTS.md`, change the Security suites line: "It runs the audit-coverage, audit-tamper, database-privilege, auth-coverage and auth-events suites."

Commit: `test(security): every auth action is audited and no event holds a secret`

### 17. Frontend: the API client, the gate table and the session lookup

**Files:** `frontend/package.json`, `package-lock.json`, `src/components/ui/{card,label,alert,dialog,checkbox,table}.tsx`, `src/lib/api.ts`, `src/lib/auth/{gate,backend,navigate,messages}.ts`, `src/lib/__tests__/api.test.ts`, `src/lib/auth/__tests__/{gate,backend,messages}.test.ts`.

1. Run `cd frontend && npx shadcn add card label alert dialog checkbox table` and `npm install qrcode.react`. Keep the files shadcn generates. Check that `src/components/ui/__tests__/caps.test.tsx` still passes.
2. Tests first (C11):
   - `gate.test.ts`: the whole table, with `it.each` rows. For example, `(null, "/servers", "") → "/login?next=%2Fservers"`, `("active", "/login") → "/"`, `("setup_required", "/login") → "/setup"`, `("signed_out", "/") → "/login"`, and a query string kept in `next`. Then `safeNext` for `"/servers"`, `"//evil.example"`, `"/\\evil"`, `"https://x"`, `""` and `undefined`.
   - `backend.test.ts` (`// @vitest-environment node`, `vi.stubGlobal("fetch", …)`): it forwards only `megoo_session=<token>` to `${BACKEND_URL}/api/auth/session`; null on a thrown error, a 500 or a body without `status`; no cookie header without a token.
   - `api.test.ts`: it sends JSON and returns JSON, a 204 → undefined, an error → `ApiError` with `detail`, a list `detail` → "invalid", a network failure → `ApiError(0, "unreachable")`. A 401 `not_signed_in` on `/servers` calls the mocked `goTo("/login?next=%2Fservers")`, and on `/login` it does not.
   - `messages.test.ts`: two known reasons and the fallback.
   Run **FE src/lib**: it fails.
3. Implement C11 (not `server.ts` yet).
4. Run **FE-GATE**: it passes.

Commit: `feat(frontend): the API client and the gate table for sign-in`

### 18. Frontend: the auth layout and the sign-in, code, recovery and locked steps

**Files:** `src/app/(auth)/layout.tsx`, `src/components/auth/{password-step,code-step,recovery-step,locked-notice}.tsx`, `src/components/auth/__tests__/{password-step,code-step,recovery-step}.test.tsx`.

The `(auth)` layout has no shell:

```tsx
<div className="flex min-h-svh flex-col">
  <header className="flex items-center justify-between p-4"><Wordmark /><ThemeSwitch /></header>
  <main id="main" tabIndex={-1} className="flex flex-1 items-start justify-center px-4 py-10 outline-none sm:items-center">
    <div className="w-full max-w-md">{children}</div>
  </main>
</div>
```

Each step is one `Card`, with the texts of C12. Buttons are disabled while a request runs.

1. Tests first (mocks as in the conventions):
   - Password step: it posts the trimmed email and the password and calls `onDone("mfa_required")`; a 401 shows "The email or the password is wrong."; `unreachable` shows the server message.
   - Code step: Verify posts `{code, method: "totp"}` and calls `onDone`; `locked` → `onLocked`; `not_signed_in` → `onRestart`; `wrong_code` → the alert; the "Use a recovery code" link → `onUseRecovery`.
   - Recovery step: it posts `method: "recovery_code"`, and the switch-back link works.
   Run **FE src/components/auth**: it fails.
2. Implement it.
3. Run **FE-GATE**: it passes.

Commit: `feat(frontend): the sign-in, code and recovery steps`

### 19. Frontend: the authenticator enrolment step and the recovery codes screen

**Files:** `src/components/auth/{enrol-step,recovery-codes}.tsx`, `src/components/auth/__tests__/{enrol-step,recovery-codes}.test.tsx`.

1. Tests first (C12):
   - Enrol step: without `enrolment` it posts `/auth/mfa/enrol` `{}` once and shows the QR (`svg` titled "QR code for your authenticator") and the key in groups of 4. With `enrolment` it posts nothing. Verify posts `/auth/mfa/enrol/confirm` `{code}` and calls `onDone(codes)`, or `onDone(null)` when `recovery_codes` is null. `wrong_code` shows the alert, and `not_signed_in` calls `onRestart`.
   - Recovery codes: all codes are shown; Continue is disabled until "I have saved these codes" is ticked, then calls `onContinue`; "Copy codes" writes them joined by newlines (`vi.spyOn(navigator.clipboard, "writeText")`, using `Object.assign(navigator, { clipboard: { writeText: vi.fn() } })` if jsdom has none); `continueLabel` changes the button.
   Run **FE src/components/auth**: it fails.
2. Implement them with `QRCodeSVG` from `qrcode.react`.
3. Run **FE-GATE**: it passes.

Commit: `feat(frontend): the authenticator enrolment step and the recovery codes screen`

### 20. Frontend: the /login and /setup pages and their flows

**Files:** `src/lib/auth/server.ts`, `src/components/auth/{login-flow,setup-flow}.tsx`, `src/app/(auth)/login/page.tsx`, `src/app/(auth)/setup/page.tsx`, `src/components/auth/__tests__/{login-flow,setup-flow}.test.tsx`.

- `server.ts` is C11: `getSession` with React `cache`, and `requireUser`.
- `login/page.tsx`: `export const metadata = { title: "Sign in" }`. It awaits `searchParams` (`Promise<{ next?: string | string[] }>`) and `getSession()`, and renders `<LoginFlow initialStep={initialStep(session?.status)} next={typeof next === "string" ? safeNext(next) : null} />`.
- `setup/page.tsx`: `title: "Set up MegooITAdmin"`. When `getSession()` answers with another status than `setup_required`, it calls `redirect("/login")`. It renders `<SetupFlow />`.
- `LoginFlow` steps:
  - password → code, or password → enrol
  - code ↔ recovery
  - code or recovery → `goTo(next ?? "/")`
  - enrol → codes → `goTo(next ?? "/")`
  - any step → locked → "Back to sign-in" → password
  - `onRestart(notice)` → password, with the notice
- `SetupFlow`: account → enrol → codes → `goTo("/")`, with the "Step N of 3" line. A 409 on `/auth/setup` → `goTo("/login")`.

1. Tests first:
   - `login-flow.test.tsx`: `initialStep` for each status; password then code then `goTo("/servers")` with `next="/servers"`; password → enrolment → codes → tick → Continue → `goTo("/")`; a `locked` code → the locked notice → back to the password; the recovery path.
   - `setup-flow.test.tsx`: the client checks (short password, mismatch) post nothing; a right submit posts `{code, name, email, password}` and shows "Step 2 of 3"; then confirm → "Step 3 of 3" → Continue → `goTo("/")`; a 409 → `goTo("/login")`; `wrong_setup_code` → the alert.
   Run **FE src/components/auth**: it fails.
2. Implement it.
3. Run **FE-GATE** and **IMAGE** (the existing image checks still pass: no gate yet).

Commit: `feat(frontend): the sign-in and setup pages`

### 21. The page gate: src/proxy.ts, a stub backend for the image check, and the stack check behind sign-in

**Files:** `src/proxy.ts`, `src/__tests__/proxy.test.ts`, `docker-compose.yml`, `tools/test-services/docker-compose.web.yml`, `tools/test-services/stub-backend.Caddyfile`, `frontend/image-tests/shell.test.ts`, `backend/tests/test_stack.py`.

`proxy.ts`:

```ts
export async function proxy(request: NextRequest) {
  const session = await fetchSession(request.cookies.get(SESSION_COOKIE)?.value);
  const target = gateRedirect(session?.status ?? null, request.nextUrl.pathname, request.nextUrl.search);
  return target ? NextResponse.redirect(new URL(target, request.url)) : NextResponse.next();
}
export const config = { matcher: ["/((?!_next/static|_next/image|icon.svg).*)"] };
```

1. Tests first:
   - `proxy.test.ts` (`// @vitest-environment node`, with `fetch` stubbed): no cookie + `signed_out` → 307 to `/login?next=%2Fservers`; `active` → no redirect (`x-middleware-next` header); `active` on `/login` → `/`; `setup_required` → `/setup`; a fetch that throws → `/login`; the cookie value reaches the backend.
   - `image-tests/shell.test.ts`: `const SIGNED_IN = "megoo_session=image-test-session"`. Add `redirect: "manual"` checks: `/` → 307 with location ending `/login`, and `/servers` → `/login?next=%2Fservers`. `/login` → 200, with "Sign in" and the theme script in the head. The five existing checks send `cookie: SIGNED_IN` (the sidebar one: `SIGNED_IN + "; sidebar_state=false"`).
   - `test_stack.py`, in order in the file (the comment says why: one fresh database per run):
     1. `test_before_setup_every_page_redirects_to_setup` (`/` and `/no-such-page` → 307 to `/setup`).
     2. A module fixture `owner` (an `httpx.Client` with cookies): the code from `_compose("exec","-T","backend","python","-m","app.auth.cli","setup-code")`, `POST /api/auth/setup`, `POST /api/auth/mfa/enrol`, then confirm with `pyotp.TOTP(secret).now()`.
     3. The two existing page checks and the 404-page check move behind `owner`.
     4. `test_the_cookie_is_secure_behind_https`: a login with `X-Forwarded-Proto: https` → `Set-Cookie` has `Secure`.
     5. `test_after_sign_out_pages_redirect_to_login`, last.
   Run **FE src/__tests__/proxy.test.ts**: it fails.
2. Implement `proxy.ts`.
   - `docker-compose.yml` frontend: `environment: { BACKEND_URL: http://backend:8000 }`. The frontend healthcheck stays: `fetch` follows the redirect to `/login`, which renders even when the backend is down.
   - `docker-compose.web.yml`: a service `backend` (`image: caddy:2`, volume `./stub-backend.Caddyfile:/etc/caddy/Caddyfile:ro`), and the frontend gets `BACKEND_URL: http://backend:8000` and `depends_on: [backend]`.
   - The stub Caddyfile serves `:8000`. A matcher `path /api/auth/session` with `header Cookie *megoo_session=image-test-session*` answers 200 `{"status":"active","user":{"id":"00000000-0000-0000-0000-000000000001","name":"Image Test","email":"image@test.invalid","is_owner":true}}` with `Content-Type: application/json`. Any other `/api/auth/session` gets `{"status":"signed_out","user":null}`, and the rest gets 404.
3. Run **FE-GATE**, **IMAGE** and **STACK**: they pass.

Commit: `feat(frontend): no page is served without an active session`

### 22. The shell shows the signed-in person and signs them out

**Files:** `src/app/(app)/layout.tsx`, `src/app/not-found.tsx`, `src/components/shell/{app-shell,site-header,account-menu}.tsx`, `src/lib/navigation.ts`, and the tests `src/components/shell/__tests__/{account-menu,app-shell,site-header}.test.tsx` and `src/lib/__tests__/navigation.test.ts`.

- `navigation.ts`: `const PAGE_TITLES: Record<string, string> = { "/profile": "Profile and security" }`, and `export function pageTitle(pathname: string): string` = `findNavItem(pathname)?.title ?? PAGE_TITLES[pathname] ?? "Page not found"`. The sidebar keeps its 13 items.
- `AppShell({ defaultOpen, user, children })` → `SiteHeader({ user })` → `AccountMenu({ user })`, with `user: AccountUser` (now `{ name; email }`, not null). Remove "Sign-in is not available yet".
- The menu label shows the name and email. "Profile and security" is `DropdownMenuItem asChild` around `<Link href="/profile">`. "Sign out" `onSelect` → `apiFetch("/auth/logout", { method: "POST" }).catch(() => undefined)`, then `goTo("/login")`.
- The `(app)` layout and `not-found.tsx` call `const user = await requireUser()` and pass `user`.

1. Tests first:
   - The account menu shows the name and email, Profile links to `/profile`, and Sign out posts and goes to `/login` (even when the post fails).
   - The site header title for `/profile` is "Profile and security".
   - `navigation.test.ts`: `pageTitle` returns the nav title, "Profile and security" and "Page not found".
   - Update the existing shell tests to pass `user={{ name: "Olive Owner", email: "owner@example.com" }}`.
   Run **FE src/components/shell src/lib**: it fails.
2. Implement it.
3. Run **FE-GATE** and **IMAGE** (the stub gives the user) and **STACK**: they pass.

Commit: `feat(frontend): the account menu shows the signed-in person and signs them out`

### 23. Profile and security page: account and password

**Files:** `src/app/(app)/profile/page.tsx`, `src/components/profile/{profile-page,password-dialog}.tsx`, `src/components/profile/__tests__/{profile-page,password-dialog}.test.tsx`.

- `page.tsx`: `metadata.title = "Profile and security"`, and it renders `<ProfilePage />`.
- `ProfilePage` loads `apiFetch<Me>("/auth/me")` and shows the cards in a `grid gap-6 lg:grid-cols-2`, with an alert on a load error:
  - "Account": the name, the email, and an "Owner" `Badge` when `is_owner`.
  - "Password": "Last changed <time>" and the button "Change password".
  - "Two-step verification" and "Sessions" are added in steps 24 and 25.
- Times use `formatTime(iso)`, exported from `profile-page.tsx`: `new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short" })`.
- `PasswordDialog({ open, onOpenChange, onChanged })`: "Change password" with "Current password", "New password" and "Repeat the new password". Client checks: 12 to 128 characters, and the passwords match. It posts `/auth/password` `{current_password, new_password}`. `wrong_password` or `locked` → the alert. On success it calls `onChanged()`, and the page shows the alert "Password changed. Your other sessions were signed out." and reloads `/auth/me`.

1. Tests first: the page renders the name, email and Owner badge from a mocked `/auth/me`; opening the dialog and a mismatch posts nothing; a wrong current password shows "The current password is wrong."; success closes the dialog and shows the notice.
   Run **FE src/components/profile**: it fails.
2. Implement it.
3. Run **FE-GATE**: it passes.

Commit: `feat(frontend): the Profile and security page, with the password change`

### 24. Profile and security: replace the authenticator and create new recovery codes

**Files:** `src/components/profile/{profile-page,authenticator-dialog,recovery-codes-dialog}.tsx`, `src/components/profile/__tests__/{authenticator-dialog,recovery-codes-dialog}.test.tsx`.

- The "Two-step verification" card: "Authenticator app added <time>", "<n> of 10 recovery codes left", and the buttons "Replace authenticator" and "New recovery codes".
- `AuthenticatorDialog({ open, onOpenChange, onReplaced })`:
  - Stage 1: "Replace authenticator", with "Enter a code from your current authenticator." and the input "Code". The checkbox "Use a recovery code instead" switches the label to "Recovery code" and the method to `recovery_code`. "Continue" posts `/auth/mfa/enrol` `{code, method}`; a refusal → the alert.
  - Stage 2: `<EnrolStep enrolment={result} onDone={() => onReplaced()} onRestart={…} />`.
  - The page then shows "Authenticator replaced. Your other sessions were signed out." and reloads `/auth/me`.
- `RecoveryCodesDialog({ open, onOpenChange, onCreated })`: "New recovery codes", with "The old codes stop working." It takes a code and posts `/auth/recovery-codes` `{code}`, then shows `<RecoveryCodes codes={…} continueLabel="Done" onContinue={close} />`. `onCreated` reloads `/auth/me`.

1. Tests first: the authenticator dialog's stage 1 posts the right method and moves to the QR; a wrong code shows the alert; confirm calls `onReplaced`. The recovery dialog shows the codes after a right code, and Done is disabled until the box is ticked.
   Run **FE src/components/profile**: it fails.
2. Implement it.
3. Run **FE-GATE**: it passes.

Commit: `feat(frontend): replace the authenticator and create new recovery codes on the profile page`

### 25. Profile and security: see and end your sessions

**Files:** `src/components/profile/{profile-page,sessions-card}.tsx`, `src/components/profile/__tests__/sessions-card.test.tsx`.

- `SessionsCard()` loads `apiFetch<SessionRow[]>("/auth/sessions")` into a `Table` with the columns "Device" (the user agent, `truncate`, or "Unknown device"), "Address" (`ip`, or "—"), "Signed in", "Last active" and an actions column.
- The current row shows the badge "This session". Other rows have a ghost button "Sign out", with `aria-label` "Sign out the session on <device>".
- That button opens a `Dialog` "Sign out this session?", with "That browser has to sign in again." and the buttons "Cancel" and "Sign out". Confirming sends `apiFetch("/auth/sessions/<id>", { method: "DELETE" })` and reloads the list. A refusal → the alert in the dialog.
- `ProfilePage` adds the card across both columns.

1. Tests first: the list marks "This session" and has no button for it; signing out another session sends DELETE and drops it from the reloaded list; Cancel sends nothing.
   Run **FE src/components/profile/__tests__/sessions-card.test.tsx**: it fails.
2. Implement it.
3. Run **FE-GATE** and **IMAGE**: they pass.

Commit: `feat(frontend): a person can see and end their other sessions`

### 26. README: first start and the host commands, then the full check

**Files:** `README.md`.

1. Under "Run it", add a "First start" paragraph:
   - `make up`, then `make setup-code` (or look in `make logs` for "Setup code:"), then open the app.
   - `/setup` takes the code, the Owner's name, email and password, and then the authenticator.
   - Save the ten recovery codes.
2. Add a bullet on `AUTH_SECRET_KEY` to the `.env` bullet: `make up` adds it, keep it, and without it no code can be checked.
3. Add a "Lost access" paragraph with `make reset-mfa email=…` and `make reset-password email=…` (it asks for the new password twice and also unlocks the account), both with `STACK=` for the copies.
4. Mention that `API_DOCS=true` serves `/api/docs`, and that the dev stack sets it.
5. Run `make test` and `make test-security`: both pass. Then follow the manual check below on `make up STACK=dev`, and say which parts you could not do.

Commit: `docs(readme): first start, sign-in and the host commands`

## Final verification

- `make test`: the backend suite, `tsc` and the frontend tests, the image start-up tests, the frontend image check with the stub backend, and the stack checks through Caddy.
- `make test-security`: audit coverage, audit tamper, database privileges, auth coverage and auth events.
- By hand on `make up STACK=dev`, then `http://127.0.0.1:8080`:
  1. `/` redirects to `/setup`. `make setup-code STACK=dev` prints a code, and setup with it creates the Owner. Enrol an authenticator app and save the codes; the shell shows the name in the account menu.
  2. Sign out → `/login`.
  3. Sign in with the password and a code.
  4. Sign out, then sign in with a recovery code.
  5. On Profile and security: change the password, create new codes, replace the authenticator, and end another session.
  6. `make reset-mfa email=… STACK=dev` → the next sign-in asks for enrolment.
  7. `make reset-password email=… STACK=dev` → the new password works.
  8. `http://127.0.0.1:8080/api/docs` answers (dev sets `API_DOCS=true`).
- `make down STACK=dev`.
