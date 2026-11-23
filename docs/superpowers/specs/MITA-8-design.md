# MITA-8 design: login with mandatory MFA (local accounts, TOTP)

## Goal

After this task nobody reaches a page or an API route of MegooITAdmin without a password and a TOTP code. A fresh installation is claimed through a setup page that needs a one-time code from the host. A signed-in person can sign out, change their password, replace their authenticator, get new recovery codes and revoke their other sessions on the Profile and security page. Every one of these steps, and every failed attempt, is an audit event. Mockup v1 shows the ten screens.

## What the repository looks like today

- The backend has one route, `GET /api/health`, the audit package (`record`, `audited`, `source_of`) and no user table. It serves as `megooitadmin_api`.
- The frontend serves 13 placeholder pages in one shell to anyone. `AccountMenu` gets `user={null}` and says "Sign-in is not available yet".
- `GET /api/docs` and `GET /api/openapi.json` are open.
- The stack has four services and no Valkey. `make up` creates and completes `.env`.

## Decisions

Answers from the owner:

1. **The first Owner is created on a setup page that needs a one-time setup code.** The backend writes the code to its log, and `make setup-code` prints a new one. Rejected: a setup page without a code, a terminal command, and credentials in `.env`.
2. **A lost authenticator has two ways back:** 10 one-time recovery codes shown at enrolment, and `make reset-mfa email=…` on the host. Rejected: only one of the two.
3. **The Profile and security page is part of this task**, with its API. Rejected: a follow-up task, and API now with the page later.
4. **TOTP secrets are encrypted with a key in `.env`** (`AUTH_SECRET_KEY`, AES-256-GCM), which `make up` adds. Rejected: plain text until the vault exists.
5. **A session ends after 1 hour without a request and 12 hours after sign-in at the latest.** Both are settings.
6. **Mockup v1 is approved** as shown.

Decisions I made (say so if you want one changed):

7. **Two gates.** The backend refuses every route without an active session, except a short public list that a security test pins. The frontend's `src/proxy.ts` asks the backend about the session on every page request and redirects. Rejected: a check in the `(app)` layout (Next.js renders a page segment without its layout on client navigation, so the check can be skipped), a check for the cookie's presence only (any made-up cookie would get the pages), and Caddy `forward_auth` (it changes the PRD's Caddyfile and puts the list of public pages into Caddy).
8. **Sessions are rows in PostgreSQL.** The cookie holds a random 256-bit token, and the table holds only its SHA-256. Revoking is deleting the row. Rejected: a signed stateless cookie, which cannot be revoked. The table is `auth_sessions`, because the PRD keeps `sessions` for agent conversations.
9. **Sign-in has two stages.** A right password gives a `pending` session that lives 10 minutes and can only finish the sign-in. A right code replaces it with an `active` session under a new token.
10. **The cookie** is `megoo_session`: `HttpOnly`, `SameSite=Lax`, `Path=/`, `Max-Age` of the absolute lifetime, and `Secure` when the request's scheme is `https` (Uvicorn takes it from `X-Forwarded-Proto`). `Lax`, not `Strict`: a link from a notification must open the app signed in, and no state changes on a GET.
11. **Lockout:** 5 wrong attempts in a row lock the account for 15 minutes. Wrong passwords, wrong codes and wrong recovery codes share the counter, at sign-in and on the profile page. A success resets it. Sessions that are already open stay open.
12. **One message for an unknown email, a wrong password and a locked account**, so the sign-in page never says whether an account exists. After a right password the code step may say that the account is locked.
13. **Passwords:** 12 to 128 characters, no composition rules. Argon2id with the defaults of `argon2-cffi`, run in a worker thread, and rehashed at sign-in when the parameters change.
14. **TOTP:** 6 digits, 30 seconds, SHA-1 (what authenticator apps expect), one step of clock drift either way, with `pyotp`. A time step is accepted once, so a code cannot be replayed.
15. **Recovery codes** are 80 random bits each, shown as `XXXX-XXXX-XXXX-XXXX`, stored as SHA-256, and deleted when used.
16. **A refused attempt answers 401 without raising.** The failure counter, the lock and their audit events then commit in the request's own transaction, and the `audited` guard still sees an event.
17. **`users.is_owner`** is a boolean. MITA-9 brings roles and grants, and inviting other users.
18. **People sign in with their email**, stored in lower case.
19. **`make reset-password email=…`** is added beside `reset-mfa`: there is no email delivery, so a forgotten password has no other way back.
20. **The API docs and `openapi.json` are served only with `API_DOCS=true`** (the dev stack sets it). Otherwise they would stay open to anyone.
21. **Re-proving identity on the profile page:** a password change needs the current password. Replacing the authenticator needs a current code or a recovery code. New recovery codes need a current code.
22. **The QR code is drawn in the browser** with `qrcode.react` from the `otpauth://` address the backend returns.

## Architecture

### Backend: `backend/app/auth/`

| Module | Purpose |
|---|---|
| `models.py` | `User`, `AuthSession`, `RecoveryCode`, `SetupCode` |
| `passwords.py` | Hash, verify, needs-rehash, the length rule |
| `totp.py` | New secret, `otpauth://` address, verify a code against a secret and the last used step |
| `crypto.py` | Encrypt and decrypt a TOTP secret with `AUTH_SECRET_KEY`; the user's ID is the associated data, so a ciphertext cannot be moved to another user |
| `recovery.py` | Create, normalise and hash recovery codes and the setup code |
| `sessions.py` | Create, find, touch and delete sessions; set and clear the cookie |
| `service.py` | The flows: setup, password step, code step, enrolment, password change, lockout |
| `deps.py` | `CurrentSession` (pending or active) and `CurrentUser` (active only), as FastAPI dependencies |
| `actions.py` | The audit action names as constants |
| `schemas.py`, `router.py` | The request and response models, and the routes below |
| `cli.py` | `python -m app.auth.cli setup-code | reset-mfa | reset-password` |

- `app/main.py` includes the auth router, and serves the docs only when `API_DOCS` is true.
- `app/models.py` imports `app.auth.models`.
- `app/core/config.py` gets `auth_secret_key` (required: a backend without it does not start), `session_idle_minutes = 60`, `session_absolute_minutes = 720` and `api_docs = False`.
- `docker-entrypoint.sh` runs `python -m app.auth.cli setup-code --if-no-account` after the password step. With no account it stores a fresh code and prints it to the log. With an account it does nothing.
- Migration `0004_auth.py` creates the four tables and their grants.
- New dependencies: `argon2-cffi`, `pyotp`, `cryptography`.

How a request is checked: `CurrentSession` reads the cookie, hashes the token and loads the session with its user. A session past its idle or absolute limit is deleted and counts as absent. `last_seen_at` is written at most once a minute. `CurrentUser` also requires the stage `active`. Later features put their routers under `Depends(CurrentUser)`, and `user.auth_method` and `user.mfa` feed `source_of`, as the MITA-7 design planned.

### Frontend

| File | Purpose |
|---|---|
| `src/proxy.ts` | The page gate. Forwards the request's cookie to `GET {BACKEND_URL}/api/auth/session` and redirects by the table below. Its matcher leaves out `/_next/static`, `/_next/image` and `/icon.svg` |
| `src/lib/auth/gate.ts` | Pure: `(status, pathname) → redirect target or null`, and the check of `next` |
| `src/lib/auth/server.ts` | Server only: `getSession()`, cached per request |
| `src/lib/api.ts` | The browser's JSON client for `/api/*`. A 401 outside the auth flow sends the browser to `/login?next=…` |
| `src/app/(auth)/layout.tsx` | The page without the shell: wordmark, theme button, one card |
| `src/app/(auth)/setup/page.tsx`, `login/page.tsx` | Read the status on the server and start the flow at the right step |
| `src/components/auth/` | `setup-flow`, `login-flow`, `password-step`, `code-step`, `recovery-step`, `enrol-step`, `recovery-codes` |
| `src/app/(app)/profile/page.tsx`, `src/components/profile/` | The four cards and four dialogs of screen 10 |
| `src/app/(app)/layout.tsx`, `src/app/not-found.tsx`, `app-shell.tsx`, `site-header.tsx`, `account-menu.tsx` | The layout loads the session and passes the user down. The menu shows name and email, links to `/profile`, and Sign out posts `/api/auth/logout` and goes to `/login` |
| `src/lib/navigation.ts` | The header title for `/profile` ("Profile and security"). The sidebar keeps its 13 items |

New shadcn components: `card`, `label`, `alert`, `dialog`, `checkbox`, `table`. New dependency: `qrcode.react`.

The gate, by status:

| Status | Pages allowed | Anything else goes to |
|---|---|---|
| `setup_required` | `/setup` | `/setup` |
| `signed_out`, `mfa_required`, `enrolment_required`, or the backend does not answer | `/login` | `/login?next=<path>` |
| `active` | every page except `/login` and `/setup` | from those two: `/` |

`next` is used only when it is a path of this site (one leading `/`, not `//`). Setup keeps its three steps on `/setup` as client state. After a reload in step 2 the gate sends the person to `/login`, which shows the same enrolment step.

### Stack and tooling

- `docker-compose.yml`: the backend gets `AUTH_SECRET_KEY` (required), `SESSION_IDLE_MINUTES`, `SESSION_ABSOLUTE_MINUTES` and `API_DOCS`. The frontend gets `BACKEND_URL: http://backend:8000` (both are on `edge`).
- `Makefile`: the `.env` rule also adds a random `AUTH_SECRET_KEY` (32 bytes as hex) to a new or an older file, and still never changes a line. New targets `setup-code`, `reset-mfa email=…` and `reset-password email=…` run `app.auth.cli` in the running backend and honour `STACK=`. The email is checked by the shell from the environment, as `migration` does with its name.
- `.env.example`, `tools/stacks/dev.env`, `tools/stacks/e2e.env`, `megoocolab.toml` (`stack` set), `tools/test-services/docker-compose.image.yml`: the new variables with throwaway values. `dev.env` sets `API_DOCS=true`.
- `tools/test-services/docker-compose.web.yml`: a stub backend beside the frontend image. It is a Caddy container that answers `GET /api/auth/session` with `active` for one fixed cookie value and `signed_out` otherwise.
- `README.md`: a "First start" paragraph (`make up`, `make setup-code`, open the app) and the three host commands. `AGENTS.md`: the Security suites line names the auth-coverage suite.

## Data and interfaces

### Tables (migration `0004_auth`)

**`users`**: `id uuid` PK, `email text` unique (lower case), `name text`, `password_hash text`, `is_owner boolean`, `totp_secret bytea` (encrypted, null until enrolled), `totp_pending_secret bytea` (encrypted, during enrolment or replacement), `totp_confirmed_at timestamptz`, `totp_last_step bigint`, `failed_attempts integer` default 0, `locked_until timestamptz`, `password_changed_at timestamptz`, `created_at timestamptz`.

**`auth_sessions`**: `id uuid` PK, `user_id` FK to `users` (cascade), `token_hash bytea` unique, `stage text` (`pending` or `active`, check), `mfa_method text` (`totp` or `recovery_code`, null while pending), `created_at`, `last_seen_at`, `expires_at timestamptz`, `ip inet`, `user_agent text`.

**`recovery_codes`**: `id uuid` PK, `user_id` FK (cascade), `code_hash bytea` unique, `created_at`.

**`auth_setup`**: one row (`id = 1`, check), `code_hash bytea`, `failed_attempts integer`, `created_at`. The row exists only while no account exists.

Grants for `megooitadmin_api`, also added to `API_GRANTS`: `users` SELECT, INSERT, UPDATE. `auth_sessions`, `recovery_codes` and `auth_setup` SELECT, INSERT, UPDATE, DELETE.

### Routes (all under `/api/auth`)

| Route | Needs | Does | Audit events |
|---|---|---|---|
| `GET /session` | nothing | `{status, user}`, always 200. `user` is `{id, name, email, is_owner}` or null | none |
| `POST /setup` `{code, name, email, password}` | no account | Creates the Owner and a pending session | `auth.owner_created`, or `auth.setup_failed` |
| `POST /login` `{email, password}` | nothing | Pending session. Answers `mfa_required` or `enrolment_required` | `auth.password_accepted`, or `auth.sign_in_failed` (and `auth.account_locked`) |
| `POST /login/mfa` `{code, method}` | pending session, authenticator enrolled | Active session under a new token | `auth.mfa_used` and `auth.sign_in`, or `auth.mfa_failed` (and `auth.account_locked`) |
| `POST /mfa/enrol` `{code?}` | pending session without authenticator, or active session with a current code | Stores a pending secret. Returns the secret and the `otpauth://` address | `auth.mfa_enrolment_started`, or `auth.mfa_failed` |
| `POST /mfa/enrol/confirm` `{code}` | the same | The pending secret becomes the authenticator. First enrolment: returns 10 recovery codes and makes the session active. Replacement: ends the other sessions | `auth.mfa_enrolled` (and `auth.sign_in`, or `auth.session_revoked` per ended session), or `auth.mfa_failed` |
| `POST /logout` | any session | Deletes the session and clears the cookie | `auth.sign_out` |
| `GET /me` | active | For the profile page: the user, `password_changed_at`, `totp_confirmed_at`, recovery codes left | none |
| `GET /sessions` | active | The person's sessions, the current one marked | none |
| `DELETE /sessions/{id}` | active | Ends another session of the same person. 409 for the current one, 404 for anyone else's | `auth.session_revoked` |
| `POST /password` `{current_password, new_password}` | active | Changes the password and ends the other sessions | `auth.password_changed` (success or failure), `auth.session_revoked` per ended session |
| `POST /recovery-codes` `{code}` | active | 10 new codes, the old ones deleted | `auth.recovery_codes_created`, or `auth.mfa_failed` |

Host commands record `auth.setup_code_created`, `auth.mfa_reset` and `auth.password_changed` with the actor `Actor.system("cli")` and the user as the target. `reset-mfa` and `reset-password` also end the user's sessions, and `reset-password` clears a lock.

Every event of a request carries `source_of(request, auth_method="password", mfa=…)`. The actor is the user. For an unknown email the actor's name is the email as typed (cut to 254 characters) with no ID. `result_detail` holds the reason (`unknown_account`, `wrong_password`, `locked`, `wrong_code`, `expired`) and the method (`totp`, `recovery_code`). No event ever holds a password, a code, a secret or a token.

The task's list maps to: sign-in `auth.sign_in`, failed sign-in `auth.sign_in_failed`, sign-out `auth.sign_out`, MFA used, failed and reset `auth.mfa_used`, `auth.mfa_failed`, `auth.mfa_reset`, password changed `auth.password_changed`, account locked `auth.account_locked`.

Public routes, pinned by the security test: `GET /api/health`, `GET /api/auth/session`, `POST /api/auth/setup`, `POST /api/auth/login`. The routes that take a pending session (`/login/mfa`, `/mfa/enrol`, `/mfa/enrol/confirm`, `/logout`) are a second pinned list.

## Error handling and edge cases

- **Two people run setup at once.** The unique Owner is guarded by the lock on the `auth_setup` row: the second request finds the row gone and gets 409. `/setup` then redirects to `/login`.
- **Wrong setup code.** 5 wrong tries delete the code. The page then says to run `make setup-code` again. A restart of the backend also replaces the code.
- **Parallel password guesses.** The password step locks the user's row, so the counter cannot be passed. The password is checked before `record` takes the audit chain lock.
- **Unknown email.** A dummy Argon2 verification runs, so the answer takes as long as for a real account.
- **Locked account.** The password is not checked at all, so the lock gives no hint about it. After `locked_until` the counter starts at 0.
- **An attacker keeps the Owner locked** by failing 5 times every 15 minutes, and fills `audit_log` with failed sign-ins. The app is reachable only on the internal network or VPN. `make reset-password` clears a lock. Throttling by address is out of scope.
- **A code typed twice, or replayed.** The second use of the same time step is refused.
- **The pending session expires** (10 minutes) before the code is typed. The code step answers 401 and the page returns to the password step.
- **`AUTH_SECRET_KEY` is missing or not 64 hex characters.** Compose and the backend stop with a message that names the variable. If the key is lost or changed, a secret no longer decrypts: the code step refuses with reason `undecryptable`, and `make reset-mfa` lets the person enrol again.
- **The backend does not answer the frontend.** The gate fails closed: only `/login` renders, and submitting says "The server is not answering".
- **An unknown address without a session** goes to `/login`, so the gate does not reveal which pages exist. With a session it is the 404 page in the shell, as today.
- **Plain HTTP** (the dev stack on `127.0.0.1:8080`). The cookie has no `Secure` flag, so sign-in works. Behind the TLS proxy it has.
- **Cross-site requests.** `SameSite=Lax` keeps the cookie off cross-site POSTs, bodies are JSON only, and no GET changes state.
- **Expired sessions** are deleted when they are next presented and when their user next signs in. There is no cleanup job, and expiry is not an audit event.
- **Reload on the recovery codes screen.** The codes are gone. The profile page creates new ones.
- **A WebSocket route.** There is none yet. The existing coverage test already fails when the first appears, and that task must give it the session check.

## Testing

Tests are written first. Time-dependent code takes its clock from one function the tests replace.

**Backend, `tests/auth/`**
- Passwords: a hash verifies, a wrong password does not, the hash is Argon2id, 11 and 129 characters are refused, an old-parameter hash is rehashed at sign-in.
- TOTP: the RFC 6238 SHA-1 vectors, one step of drift accepted and two refused, a used step refused.
- Crypto: a round trip, another user's ID refused, a changed key refused. Recovery codes: format, single use, stored only as a hash.
- Setup: with no account the status is `setup_required`. A wrong code is refused and the fifth deletes it. A right code creates the Owner, and a second setup gets 409.
- Sign-in: password, then code, gives an active session under a new token. A pending session cannot call a protected route. Enrolment is forced for an account without an authenticator and returns 10 codes. A recovery code signs in once.
- Lockout: 5 failures lock, the sixth attempt with the right password is refused with the same message, the lock ends after 15 minutes, a success resets the counter.
- Sessions: idle and absolute expiry, `last_seen_at` moves at most once a minute, sign-out deletes the row and clears the cookie, the cookie is `HttpOnly`, `SameSite=Lax` and `Secure` only under `https`.
- Profile: wrong current password refused and counted, a password change ends the other sessions and keeps this one, revoke ends another session and refuses the current one and another user's, replacing the authenticator invalidates the old secret, new codes replace the old ones.
- CLI: `setup-code` prints a code only without an account, `reset-mfa` forces enrolment at the next sign-in, `reset-password` sets the password and clears the lock. Each ends the user's sessions and records its event.

**Security suites, `tests/security/`** (run by `make test-security`)
- `test_auth_coverage.py`: every route of the real app requires an active session, or is in one of the two pinned lists with a reason. The check reports an unprotected route of a sample app.
- `test_auth_events.py`: one walk through setup, sign-in, failures, lock, sign-out, password change and resets produces every action of the table above, the chain check passes, and no audit row contains the password, the TOTP secret, a code or a session token.
- `test_audit_coverage.py` passes unchanged: every state-changing auth route declares its actions. `test_db_privileges.py` gets the four tables.

**Other backend tests**
- `test_migrations.py`: `0004` goes down and up, and the models match. `test_settings.py`: the new settings. `test_health.py`: the docs answer 404 by default and 200 with `API_DOCS=true`.
- `test_makefile.py`: a new `.env` holds three values, an older file gets `AUTH_SECRET_KEY` appended and keeps its lines, and the three new targets print their commands.
- `test_container.py` (`-m docker`): on an empty database the log holds a setup code, and a container without `AUTH_SECRET_KEY` does not serve.
- `test_stack.py` (`-m stack`): `/` and an unknown address redirect to `/setup`. After setup with the code from the backend and a code computed with `pyotp`, `/` serves the shell and an unknown address the 404 page. With `X-Forwarded-Proto: https` the cookie is `Secure`. After sign-out, `/` redirects to `/login`. The two existing page checks move behind this sign-in.

**Frontend**
- Vitest: the gate table and the `next` check; the proxy with a mocked backend, including a backend that does not answer; each step component (errors shown, Continue disabled until the box is ticked); the login and setup flows across their steps; the profile cards and dialogs; the account menu with a user and its sign-out. The storage test stays as it is.
- Image check (`web` set, with the stub backend): without the cookie `/` and `/servers` redirect to `/login`, and `/login` renders with the theme script. With the cookie the five existing checks pass.

Done when `make test` and `make test-security` pass, and by hand on `make up STACK=dev`: setup, sign-out, sign-in with a code, sign-in with a recovery code, and the three host commands.

## Out of scope

- Single sign-on (OIDC) and passkeys.
- Inviting, changing, disabling and deleting users, roles and grants, and an Owner resetting someone else's second factor: MITA-9.
- Asking for the second factor again before destructive approvals and production sessions: Phases 2 and 4.
- Email: a "forgot password" link and notices of new sign-ins.
- Throttling by client address, and an `Origin` check on top of `SameSite=Lax`.
- Editing the name or email on the profile page.
- The session check for WebSocket routes: the task that adds the first socket.
- Audit highlights such as "sign-in from a new address": the Audit page.
- A job that removes expired sessions, and an audit event for expiry.
- Browser end-to-end tests (Playwright).
