# MITA-4 design: Docker Compose stack, Caddy and Makefile

## Goal

After this task, `make up` on a clean machine builds and starts MegooITAdmin (Caddy, frontend, backend, database), and `curl http://localhost/api/health` answers `{"status": "ok"}` through Caddy. The Makefile becomes the one entry point for starting, stopping, migrating and testing, and a new check proves the whole stack on a throwaway copy.

## What the repository looks like today

- `backend/` and `frontend/` each build an image (MITA-5, MITA-6). Both images have checks of their own (`image` and `web` service sets in `megoocolab.toml`).
- `caddy/` holds only `.gitkeep`. There is no `docker-compose.yml`, no `Makefile` and no `.env.example`.
- `tools/release/` is empty (MITA-3), and there are no security suites yet (Phases 3 and 4).
- `AGENTS.md` names three Compose projects: `megooitadmin` (your real instance), `megooitadmin-dev` and `megooitadmin-e2e`.

## Decisions

Your answers:

1. **`make up STACK=dev` starts the dev project.** Every stack target takes `STACK`. `STACK=dev` is the project `megooitadmin-dev` on port 8080, `STACK=e2e` is `megooitadmin-e2e` on port 8081, each with its own database volume. Without `STACK`, the target acts on the real instance on port 80. Rejected: two environment variables with no Makefile support, a separate hot-reload dev mode, and nothing.
2. **`make up` creates `.env` with a random database password** when `.env` is missing. It never touches an existing one. `.env.example` documents every variable. The dev and e2e stacks use a fixed throwaway password and never read `.env`. Rejected: a fixed default password, and a required variable with a manual step.
3. **`make test` and `make migration` wrap the `megoocolab-runner` commands.** `megoocolab.toml` stays the only definition of the test services. Rejected: plain Docker Compose on fixed ports, and both paths.

Decisions I made (say so if you want one changed):

4. **The Compose file carries `name: megooitadmin`.** Without it, the project name is the folder name, so a worktree folder `MITA-4` would start a project `mita-4`. `-p` (used by `STACK=` and by the runner) has precedence over `name:`.
5. **The published port is `${MEGOOITADMIN_HTTP_PORT:-80}:80`**, the same pattern as MegooArti. It lets the dev stack, the checks and a machine where port 80 is taken choose another port or address (`127.0.0.1:8080`).
6. **Only the four Phase 0 services are in the file:** `caddy`, `frontend`, `backend`, `db`. All five networks are declared now, so later services only join them.
7. **`core`, `exec` and `sandbox` are `internal: true`** (no route out of the host). `edge` and `servers` are normal bridge networks: Caddy must publish a port, and the backend must reach managed servers. The egress allowlist of `sandbox` belongs to Phase 5.
8. **Every service has a healthcheck and `restart: unless-stopped`**, and `make up` runs `docker compose up -d --build --wait --wait-timeout 300`. So `make up` returns only when `/api/health` answers through Caddy, and the stack comes back after a reboot.
9. **A new `stack` service set and `pytest -m stack` prove the "done when"**, on a throwaway copy of the real Compose file on a free port. It follows MITA-5's rule: proved by an automated check, not by hand.
10. **`make test-security` and `make release-check` exist now and fail with a clear message** until their part is in the repository. `release-check` already holds the real commands, so MITA-3 only adds the tool. Rejected: leaving the targets out (the task lists them), and targets that pass while doing nothing.
11. **Plain `make` prints the list of targets.** It must not start or stop anything by accident.
12. **Recipes need a POSIX shell.** On Windows, run `make` from Git Bash, as `AGENTS.md` already assumes with its `sh -c` commands.
13. **`make down` keeps the data.** It runs `docker compose down`, never with `-v`.
14. **Images are not named in the Compose file.** Compose names them `<project>-backend` and `<project>-frontend`, so every project (real, dev, a check) builds its own. GHCR names and the version build argument belong to MITA-13.

## Architecture

```text
docker-compose.yml                    new: caddy, frontend, backend, db; five networks; volume db_data
caddy/Caddyfile                       new (caddy/.gitkeep deleted)
Makefile                              new
.env.example                          new
tools/stacks/dev.env, e2e.env         new: port and throwaway password of the dev and e2e stacks
megoocolab.toml                       changed: the stack set
backend/pyproject.toml                changed: the stack marker
backend/tests/conftest.py             changed: -m stack collects only test_stack.py, without a test database
backend/tests/test_stack.py           new, marked "stack"
backend/tests/test_makefile.py        new, in the normal suite
.gitattributes                        changed: Caddyfile and Makefile keep LF
AGENTS.md                             changed: Checks, Migrations, Safety
README.md                             changed: a short "Run it" section
```

How a request travels:

```text
upstream TLS proxy ──HTTP──▶ caddy :80 (the only published port)
                               ├── /api/*  ──▶ backend:8000 ──▶ db:5432
                               └── the rest ──▶ frontend:3000
```

| Service | Image or build | Networks | Depends on | Healthcheck |
|---|---|---|---|---|
| `caddy` | `caddy:2` | `edge` | `backend` and `frontend` healthy | `wget` of `http://127.0.0.1/api/health` |
| `frontend` | `./frontend` | `edge` | none | Node `fetch` of `/` (as in the `web` set) |
| `backend` | `./backend` | `edge`, `core`, `servers` | `db` healthy | Python `urllib` on `/api/health` (as in the `image` set) |
| `db` | `timescale/timescaledb-ha:pg18` | `core`, `exec` | none | `pg_isready` over TCP (as in the `test` set) |

- No service uses the default network, and none has `container_name`.
- `caddy` mounts `./caddy/Caddyfile` read-only and has `tmpfs` on `/data` and `/config`: it asks for no certificate, so it keeps nothing.
- `db` has the named volume `db_data`. The image runs as a non-root user and keeps its data under `/home/postgres/pgdata`, not under `/var/lib/postgresql/data`. The volume is mounted at the image's own data folder, and a test proves that PostgreSQL's `data_directory` lies inside the mount. Without that, the data would silently live in the container and vanish on `make down`.
- `db` is created with the user and database `megooitadmin`. That user is the image's superuser, so the first migration can create the extensions. The separate roles come with MITA-7.

## Data and interfaces

### `caddy/Caddyfile`

The PRD's file, unchanged:

```caddyfile
{
	auto_https off
	servers {
		# Trust X-Forwarded-* headers from the upstream proxy
		trusted_proxies static private_ranges
	}
}

:80 {
	handle /api/* {
		reverse_proxy backend:8000
	}
	handle {
		reverse_proxy frontend:3000
	}
}
```

`reverse_proxy` passes WebSocket upgrades through with no extra line. The path reaches the backend unchanged.

### Variables Compose reads

| Variable | Default | Use |
|---|---|---|
| `POSTGRES_PASSWORD` | none, required | The database password, also placed in the backend's `DATABASE_URL`. Letters and digits only, because it sits in a URL |
| `MEGOOITADMIN_HTTP_PORT` | `80` | The published port. With an address before it (`127.0.0.1:8080`), on that address only |

- `.env.example` lists both with these explanations. `.env` stays in `.gitignore`.
- `tools/stacks/dev.env` holds `MEGOOITADMIN_HTTP_PORT=127.0.0.1:8080` and `POSTGRES_PASSWORD=megooitadmin`. `e2e.env` is the same with port 8081. Both say in a comment that these are throwaway values, not secrets.
- A variable on the command line wins over these files: `make up STACK=dev MEGOOITADMIN_HTTP_PORT=0.0.0.0:8080`.

### Makefile

`STACK` chooses the Compose call for the stack targets:

| `STACK` | Compose call |
|---|---|
| not set | `docker compose` (project `megooitadmin`, reads `.env`) |
| `dev` or `e2e` | `docker compose -p megooitadmin-<STACK> --env-file tools/stacks/<STACK>.env` (never reads `.env`) |
| anything else | Stops: "STACK must be dev or e2e" |

| Target | Does |
|---|---|
| `make` or `make help` | Prints this list |
| `make up` | Without `STACK`, creates `.env` first if it is missing. Then `up -d --build --wait --wait-timeout 300` |
| `make down` | `down`. The database volume stays |
| `make logs` | `logs -f` |
| `make migrate` | `exec backend alembic upgrade head` |
| `make shell-backend` | `exec backend bash` |
| `make migration name=add_users` | Creates the next numbered migration on the scratch database (below) |
| `make test` | Runs every backend, frontend and stack check (below) |
| `make test-security` | Stops: the security suites are not in the repository yet |
| `make release-check` | `python tools/release/versions.py check`, then `plan`. Stops with "not in the repository yet" while the tool is missing |

- **`.env` creation.** The file gets `POSTGRES_PASSWORD=` and 32 hex characters read from `/dev/urandom`, with mode 600. The Makefile then prints: "Created .env with a new database password. Keep this file: the database keeps the password it was first started with." If the random value does not come out as 32 hex characters, nothing is written and `make up` stops.
- **`make migration`.** `name` is required and must match `[a-z][a-z0-9_]*`. The number is the highest one in `backend/migrations/versions/` plus one, with four digits. The target runs, from `backend/`, the command `AGENTS.md` already gives: `megoocolab-runner services run migrate -- sh -c 'uv run alembic upgrade head && uv run alembic revision --autogenerate --rev-id 0002 -m "add users"'`. The message is the name with spaces for underscores, so the file is `0002_add_users.py`.
- **`make test`** runs these in order and stops at the first failure:
  1. `megoocolab-runner services run test -- uv run pytest` (in `backend/`)
  2. `npx tsc --noEmit`, then `npm test` (in `frontend/`; `npm ci` first when `node_modules` is missing)
  3. `megoocolab-runner services run image -- uv run pytest -m docker`
  4. `megoocolab-runner services run web -- npm run test:image`
  5. `megoocolab-runner services run stack -- uv run pytest -m stack`
- `make test` and `make migration` stop with one line when `megoocolab-runner` is not on `PATH`.

### `megoocolab.toml`

```toml
[services.stack]
description = "The whole Compose stack built from this checkout (caddy, frontend, backend, db), for pytest -m stack"
compose = ["docker-compose.yml"]
ports = ["STACK_PORT"]

[services.stack.env]
MEGOOITADMIN_HTTP_PORT = "127.0.0.1:${STACK_PORT}"
POSTGRES_PASSWORD = "megooitadmin"
STACK_URL = "http://localhost:${STACK_PORT}"
```

The runner starts the file under its own project name with its own env file, so it never reads `.env` and never touches the `megooitadmin` project.

### `backend/pyproject.toml` and `conftest.py`

- A new marker `stack`, and `addopts = "-m 'not docker and not stack'"`.
- `conftest.py` treats `-m stack` as it treats `-m docker` today: no test database, and only `test_stack.py` is collected.

### `AGENTS.md`

- **Checks.** A new line: "**Stack** (`backend/`): `megoocolab-runner services run stack -- uv run pytest -m stack`. It starts the whole Compose stack and checks it through Caddy." And one sentence: "`make test` runs the backend, frontend and stack checks in one go." The skip rule also covers "a Makefile target that says its part is not in the repository yet".
- **Migrations.** "Create each migration with the next number: `make migration name=add_users`", followed by the full command it runs.
- **Safety**, the Docker line: the dev and e2e projects are started with `make up STACK=dev` and `make up STACK=e2e`, with the same `STACK=` on `down`, `logs`, `migrate` and `shell-backend`. "Never run one of these targets without `STACK=`: it then acts on the owner's real instance."

### `README.md`

A short "Run it" section: what is needed (Docker with Compose, GNU Make), `make up`, where the app answers, what `.env` holds, `MEGOOITADMIN_HTTP_PORT`, the upstream TLS proxy in front of Caddy, and `STACK=dev`.

## Error handling and edge cases

- **Port 80 is taken, or Docker is rootless.** `make up` fails with Docker's message. `.env.example` and the README point at `MEGOOITADMIN_HTTP_PORT`.
- **`docker compose up` without the Makefile and without `.env`.** Compose stops and names `POSTGRES_PASSWORD` as required.
- **`.env` is lost while the database volume stays.** A new password would not match the one the database was created with, and the backend would fail to log in. The message at creation says to keep the file, and the README says the same.
- **A migration fails.** The backend exits before Uvicorn starts, and the restart policy starts it again. Caddy waits for a healthy backend, so nothing is served. `make up` gives up after 5 minutes, and `make logs` shows the Alembic error.
- **The same failure inside the stack check.** I asked MegooColab whether the runner limits its own wait in that case (question MC-Q10, not answered yet). The plan reads the answer. If the runner waits without end, the `stack` set gets a second small Compose file that sets `restart: "no"` for the check.
- **Forwarded headers.** Caddy trusts `X-Forwarded-*` only from private addresses, which is where the upstream proxy lives. From any other address it replaces them. The backend trusts every peer, which is safe because it publishes no port.
- **The database cannot reach the internet**, because both of its networks are internal. TimescaleDB's telemetry therefore sends nothing.
- **`/api` without a trailing path** does not match `/api/*` and goes to the frontend, which answers 404. The backend serves nothing at `/api` itself.
- **A Windows checkout.** `.gitattributes` keeps `Caddyfile` and `Makefile` with LF endings.
- **`make migrate` or `make shell-backend` while the stack is down.** Compose says the service is not running.
- **Two dev stacks at once** would both want port 8080. Checks never use the dev stack, so tasks working at the same time do not meet there.

## Testing

Tests are written first. Names read as sentences.

**`megoocolab-runner services run stack -- uv run pytest -m stack`** (`backend/tests/test_stack.py`, against `STACK_URL`):

- `GET /api/health` through Caddy gives 200 and `{"status": "ok"}`.
- `GET /` and `GET /servers` give 200 from the frontend, with the wordmark.
- `GET /api/no-such-route` gives the backend's JSON 404, and `GET /no-such-page` gives the frontend's 404 page. So each side gets its own paths, unchanged.
- `GET /api/health/` with `X-Forwarded-Proto: https` is redirected to an `https://` address: Caddy passed the upstream proxy's header on.
- A WebSocket handshake to a path under `/api/ws/` gets the backend's own refusal (403), where a plain `GET` of the same path gets 404. So the upgrade headers arrived. The first real socket (Phase 1) replaces this with a real connection.
- The resolved Compose model (`docker compose config --format json`):
  - the services are exactly `caddy`, `frontend`, `backend` and `db`;
  - only `caddy` has `ports`;
  - each service is on the networks of the table above, and `core`, `exec` and `sandbox` are internal;
  - `backend` depends on `db` with `service_healthy`;
  - `db` has a healthcheck and the volume `db_data`;
  - every service has `restart: unless-stopped` and none has `container_name`.
- In the running stack, `frontend` and `caddy` cannot resolve the name `db`, and `backend` can.
- PostgreSQL's `data_directory` lies inside the mount of `db_data`.
- `caddy validate` accepts the Caddyfile, and `caddy fmt --diff` finds nothing to change.

**`megoocolab-runner services run test -- uv run pytest`** (`backend/tests/test_makefile.py`; it needs `make`, not Docker, and uses `make -n`, which prints the commands without running them):

- `make -n up` prints `docker compose up -d --build --wait --wait-timeout 300`.
- `make -n up STACK=dev` and `STACK=e2e` print the call with `-p megooitadmin-<STACK>` and the stack's env file, and do not create `.env`.
- `make -n down STACK=prod` stops with "STACK must be dev or e2e".
- `make -n down` has no `-v`.
- `make -n migration name=add_users` prints the next number after the highest file in `migrations/versions/`, and the message `add users`.
- `make migration` without a name, or with a name such as `x;y`, stops and runs nothing.
- `make test-security` stops with its message. `make release-check` does too while `tools/release/versions.py` is missing.
- Plain `make` prints the target list.
- In a temporary folder with a copy of the Makefile, the `.env` rule writes `POSTGRES_PASSWORD` with 32 hex characters and mode 600, and a second run leaves the file as it is.

**By hand in the build:** `make up STACK=dev`, `curl http://127.0.0.1:8080/api/health`, `make migrate STACK=dev`, `make down STACK=dev`, then `make up STACK=dev` again to see the database volume kept its migration state. Then `make test` once from start to end.

The implementer never runs a stack target without `STACK=`. The security and release checks are skipped in this task, because their parts are not in the repository yet, and the finish report says so.

## Out of scope

- `guacd`, `valkey`, `meilisearch`, the workers, the gateway and the executor: each comes in the phase that uses it. `make reindex` comes in Phase 6.
- A hot-reload dev mode (`make dev`).
- `tools/release/versions.py` (MITA-3), the security suites and the fake-server fixture (MITA-11 and Phases 3 and 4), `ci.yml` (MITA-12), `release.yml`, GHCR image names and the version build argument (MITA-13).
- The separate database roles (MITA-7), TLS, the upstream proxy's configuration, backups of `db_data`.
- The egress allowlist of the `sandbox` network (Phase 5).
- Any change to the backend or frontend images, or to the `test`, `migrate`, `image` and `web` service sets.
