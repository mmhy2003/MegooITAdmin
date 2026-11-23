# MITA-4 implementation plan: Docker Compose stack, Caddy and Makefile

## Goal

`make up` on a clean machine creates `.env`, builds and starts `caddy`, `frontend`, `backend` and `db`, and returns once `curl http://localhost/api/health` answers `{"status": "ok"}` through Caddy; a `stack` check proves it on a throwaway copy.

## Architecture

One `docker-compose.yml` at the root (project `megooitadmin`) holds the four Phase 0 services on five declared networks; only `caddy` publishes a port, `${MEGOOITADMIN_HTTP_PORT:-80}:80`. `caddy/Caddyfile` sends `/api/*` to `backend:8000` and the rest to `frontend:3000`. A root `Makefile` is the entry point: `STACK=` picks the real, dev or e2e Compose project, and `test`/`migration` wrap `megoocolab-runner`. A new `stack` service set in `megoocolab.toml` starts the real Compose file on a free port for `pytest -m stack`.

## Facts this plan relies on

- `caddy/` holds only `.gitkeep`. There is no `docker-compose.yml`, `Makefile` or `.env.example`. `README.md` is the single line `# MegooITAdmin`. `.gitattributes` holds `*.sh text eol=lf`. `.gitignore` already has `.env`.
- `backend/pyproject.toml` has `markers = ["docker: …"]` and `addopts = "-m 'not docker'"`. `backend/tests/conftest.py` has `_docker_only(config)` (markexpr == `"docker"`): it skips the test-database setup and collects only `test_container.py`.
- The backend image answers `/api/health`, redirects `/api/health/` (307) and honours `X-Forwarded-Proto` (`--proxy-headers --forwarded-allow-ips=*`); Uvicorn has `websockets`, so a handshake to an unknown socket path gets 403. An unknown `/api/...` gives `{"detail": "Not Found"}`. The image has Python but no curl; `bash` exists (python:3.12-slim).
- The frontend image (node:22-alpine, `HOSTNAME=0.0.0.0`, port 3000) serves `/` and `/servers` with `MegooITAdmin` in the page, and `/no-such-page` with status 404 and `Page not found`.
- `timescale/timescaledb-ha:pg18` runs as `postgres` and keeps `PGDATA` under `/home/postgres/pgdata` (not `/var/lib/postgresql/data`). Health is checked over TCP (`pg_isready -h 127.0.0.1`), as in `tools/test-services/docker-compose.yml`.
- **MC-Q10 (answered):** `megoocolab-runner services run` calls `docker compose … up -d --build --wait --wait-timeout 300`, and on failure saves logs, removes everything and exits 125. So a backend stuck in a restart loop ends the `stack` check after about 5 minutes. **No override file with `restart: "no"` is needed**, and none is added.
- The runner passes the set's `env`, its ports and `MEGOO_SERVICES_PROJECT` both to Compose and to the command; it never reads `.env`. `-p` beats `name:` in the Compose file.
- GNU Make exports variables set on the command line into recipe environments, so a recipe can read `name=` safely as `"$$name"`.
- Backend commands run from `backend/`; `megoocolab-runner` finds `megoocolab.toml` in a parent folder.
- Commits: `type(area): plain sentence`, a body saying why, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Only the intended files. Never write under `docs/`, never commit `.megoocolab/`.
- **Never run a stack target (`up`, `down`, `logs`, `migrate`, `shell-backend`) without `STACK=dev` or `STACK=e2e`**: without it, it acts on the owner's real instance. Never read `.env`.

## File map

| Path | Step | Responsibility |
|---|---|---|
| `docker-compose.yml` | 1 | Listing L1: caddy, frontend, backend, db; five networks; volume `db_data` |
| `caddy/Caddyfile` | 1 | Listing L2 (the PRD's file). `caddy/.gitkeep` is deleted |
| `.gitattributes` | 1, 2 | `Caddyfile text eol=lf` (1), `Makefile text eol=lf` (2) |
| `megoocolab.toml` | 1 | The `stack` set (listing L3) |
| `backend/pyproject.toml` | 1 | Marker `stack`, `addopts = "-m 'not docker and not stack'"` |
| `backend/tests/conftest.py` | 1 | `-m stack` uses no test database and collects only `test_stack.py` |
| `backend/tests/test_stack.py` | 1 | Listing L4, marked `stack` |
| `Makefile` | 2, 3 | Listing L5 part A (2), part B appended (3) |
| `tools/stacks/dev.env`, `tools/stacks/e2e.env` | 2 | Listing L6: port and throwaway password of dev and e2e |
| `.env.example` | 2 | Listing L7 |
| `backend/tests/test_makefile.py` | 2, 3 | Listing L8 part A (2), part B appended (3) |
| `AGENTS.md` | 1, 2, 3 | Stack check line (1), Safety Docker line (2), `make test` sentence, skip rule and Migrations (3) |
| `README.md` | 4 | "Run it" section (listing L9) |

---

## Code listings

### L1 `docker-compose.yml`

```yaml
# MegooITAdmin's stack. Start and stop it with the Makefile (make up, make down; see README.md).
# Only caddy publishes a port: an upstream TLS proxy sends plain HTTP to it.
name: megooitadmin

x-healthcheck-timing: &healthcheck-timing
  interval: 5s
  timeout: 5s
  retries: 5
  start_period: 120s

services:
  caddy:
    image: caddy:2
    restart: unless-stopped
    ports:
      - "${MEGOOITADMIN_HTTP_PORT:-80}:80"
    volumes:
      - ./caddy/Caddyfile:/etc/caddy/Caddyfile:ro
    # Caddy asks for no certificate (auto_https off), so it has nothing to keep.
    tmpfs:
      - /data
      - /config
    networks: [edge]
    depends_on:
      backend:
        condition: service_healthy
      frontend:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1/api/health"]
      <<: *healthcheck-timing

  frontend:
    build: ./frontend
    restart: unless-stopped
    networks: [edge]
    healthcheck:
      # The image has no curl.
      test: ["CMD", "node", "-e", "fetch('http://127.0.0.1:3000/').then((r) => process.exit(r.ok ? 0 : 1), () => process.exit(1))"]
      <<: *healthcheck-timing

  backend:
    build: ./backend
    restart: unless-stopped
    environment:
      DATABASE_URL: postgresql+asyncpg://megooitadmin:${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is not set. Run make up or see .env.example}@db:5432/megooitadmin
    networks: [edge, core, servers]
    depends_on:
      db:
        condition: service_healthy
    healthcheck:
      # The image has no curl.
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"]
      <<: *healthcheck-timing

  db:
    image: timescale/timescaledb-ha:pg18
    restart: unless-stopped
    environment:
      # The image's superuser, so the first migration can create the extensions. Separate roles come later.
      POSTGRES_USER: megooitadmin
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is not set. Run make up or see .env.example}
      POSTGRES_DB: megooitadmin
    volumes:
      # The image runs as postgres and keeps its data under /home/postgres/pgdata, not /var/lib/postgresql/data.
      - db_data:/home/postgres/pgdata
    networks: [core, exec]
    healthcheck:
      # TCP, not the socket: on first start the image's temporary server listens only on its socket.
      test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U megooitadmin -d megooitadmin"]
      <<: *healthcheck-timing

networks:
  # edge and servers have a route out: caddy publishes a port, and the backend reaches managed servers.
  edge: {}
  core:
    internal: true
  servers: {}
  exec:
    internal: true
  sandbox:
    internal: true

volumes:
  db_data: {}
```

### L2 `caddy/Caddyfile` (indent with tabs)

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

### L3 `megoocolab.toml` (appended)

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

### L4 `backend/tests/test_stack.py`

```python
"""Checks of the whole Compose stack, through Caddy. They start nothing themselves: the stack service set has
built docker-compose.yml from this checkout and waited until every service was healthy."""

import base64
import json
import os
import subprocess
from functools import cache
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.stack

COMPOSE_FILE = Path(__file__).resolve().parents[2] / "docker-compose.yml"
RUN = "megoocolab-runner services run stack -- uv run pytest -m stack"
NETWORKS = {
    "caddy": {"edge"},
    "frontend": {"edge"},
    "backend": {"edge", "core", "servers"},
    "db": {"core", "exec"},
}


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"{name} is not set. Run: {RUN}")
    return value


def _compose(*args: str) -> subprocess.CompletedProcess[str]:
    command = ["docker", "compose", "-p", _env("MEGOO_SERVICES_PROJECT"), "-f", str(COMPOSE_FILE), *args]
    return subprocess.run(command, capture_output=True, text=True, timeout=120)


@cache
def _model() -> dict:
    result = _compose("config", "--format", "json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _get(path: str, headers: dict[str, str] | None = None) -> httpx.Response:
    with httpx.Client(base_url=_env("STACK_URL"), timeout=10) as client:
        return client.get(path, headers=headers)


def test_api_health_answers_ok_through_caddy():
    response = _get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("path", ["/", "/servers"])
def test_the_frontend_serves_its_pages_through_caddy(path):
    response = _get(path)
    assert response.status_code == 200
    assert "MegooITAdmin" in response.text


def test_an_unknown_api_path_gets_the_backends_json_404():
    response = _get("/api/no-such-route")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_an_unknown_page_gets_the_frontends_404_page():
    response = _get("/no-such-page")
    assert response.status_code == 404
    assert "Page not found" in response.text


def test_caddy_passes_the_upstream_proxys_forwarded_proto_on():
    response = _get("/api/health/", headers={"X-Forwarded-Proto": "https"})
    assert response.status_code == 307
    assert response.headers["location"].startswith("https://")


def test_a_websocket_upgrade_reaches_the_backend():
    # No socket route exists yet, so the backend refuses the handshake (403) where a plain GET gets 404.
    # That 403 proves the upgrade headers came through Caddy. Phase 1's first socket replaces this check.
    handshake = {
        "Connection": "Upgrade",
        "Upgrade": "websocket",
        "Sec-WebSocket-Version": "13",
        "Sec-WebSocket-Key": base64.b64encode(os.urandom(16)).decode(),
    }
    assert _get("/api/ws/check").status_code == 404
    assert _get("/api/ws/check", headers=handshake).status_code == 403


def test_the_stack_has_exactly_the_four_phase_0_services():
    assert set(_model()["services"]) == set(NETWORKS)


def test_only_caddy_publishes_a_port():
    services = _model()["services"]
    assert {name for name, service in services.items() if service.get("ports")} == {"caddy"}
    assert [port["target"] for port in services["caddy"]["ports"]] == [80]


def test_each_service_is_only_on_its_own_networks():
    for name, networks in NETWORKS.items():
        assert set(_model()["services"][name]["networks"]) == networks, name


def test_core_exec_and_sandbox_are_internal_and_edge_and_servers_are_not():
    networks = _model()["networks"]
    assert set(networks) == {"edge", "core", "servers", "exec", "sandbox"}
    assert {name for name, network in networks.items() if network.get("internal")} == {"core", "exec", "sandbox"}


def test_the_backend_waits_for_a_healthy_database():
    assert _model()["services"]["backend"]["depends_on"]["db"]["condition"] == "service_healthy"


def test_caddy_waits_for_a_healthy_backend_and_frontend():
    depends_on = _model()["services"]["caddy"]["depends_on"]
    assert {name: d["condition"] for name, d in depends_on.items()} == {
        "backend": "service_healthy",
        "frontend": "service_healthy",
    }


def test_the_database_has_a_healthcheck_and_the_named_volume():
    db = _model()["services"]["db"]
    assert db["healthcheck"]["test"]
    assert [(volume["type"], volume["source"]) for volume in db["volumes"]] == [("volume", "db_data")]
    assert "db_data" in _model()["volumes"]


def test_every_service_restarts_has_a_healthcheck_and_no_fixed_container_name():
    for name, service in _model()["services"].items():
        assert service["restart"] == "unless-stopped", name
        assert service["healthcheck"]["test"], name
        assert "container_name" not in service, name


def _resolves(service: str, host: str) -> bool:
    commands = {
        "caddy": ["getent", "hosts", host],
        "frontend": ["node", "-e", f"require('dns').lookup('{host}', (error) => process.exit(error ? 1 : 0))"],
        "backend": ["python", "-c", f"import socket; socket.gethostbyname('{host}')"],
    }
    return _compose("exec", "-T", service, *commands[service]).returncode == 0


# The True cases prove the lookup itself works in that container, so a False means "no route", not "no tool".
@pytest.mark.parametrize(
    ("service", "host", "expected"),
    [
        ("caddy", "backend", True),
        ("caddy", "db", False),
        ("frontend", "caddy", True),
        ("frontend", "db", False),
        ("backend", "db", True),
    ],
)
def test_only_the_backend_can_find_the_database(service, host, expected):
    assert _resolves(service, host) is expected


def test_the_database_keeps_its_data_inside_the_db_data_volume():
    container = _compose("ps", "-q", "db").stdout.strip()
    inspected = subprocess.run(
        ["docker", "inspect", "--format", "{{json .Mounts}}", container], capture_output=True, text=True, timeout=30
    )
    mounts = [m for m in json.loads(inspected.stdout) if m["Type"] == "volume" and m["Name"].endswith("_db_data")]
    assert len(mounts) == 1, inspected.stdout
    mount = mounts[0]["Destination"]
    result = _compose(
        "exec", "-T", "-e", f"PGPASSWORD={_env('POSTGRES_PASSWORD')}", "db",
        "psql", "-h", "127.0.0.1", "-U", "megooitadmin", "-d", "megooitadmin", "-tAc", "SHOW data_directory",
    )
    assert result.returncode == 0, result.stderr
    data_directory = result.stdout.strip()
    assert data_directory == mount or data_directory.startswith(mount + "/"), (data_directory, mount)


def test_caddy_accepts_the_caddyfile_and_finds_nothing_to_reformat():
    validate = _compose("exec", "-T", "caddy", "caddy", "validate", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile")
    assert validate.returncode == 0, validate.stdout + validate.stderr
    fmt = _compose("exec", "-T", "caddy", "caddy", "fmt", "--diff", "/etc/caddy/Caddyfile")
    assert fmt.returncode == 0 and fmt.stdout == "", fmt.stdout + fmt.stderr
```

### L5 `Makefile`

Part A (step 2):

```make
# MegooITAdmin's entry point. Run `make` for the list of targets. Recipes need a POSIX shell: on Windows,
# run make from Git Bash.
#
# Without STACK, the stack targets act on the real instance: project megooitadmin, port 80, .env.
# STACK=dev or STACK=e2e acts on megooitadmin-dev (port 8080) or megooitadmin-e2e (port 8081) instead,
# with the throwaway values of tools/stacks/<STACK>.env. Those never read .env.

.DEFAULT_GOAL := help
.PHONY: help up down logs migrate shell-backend migration test test-security release-check

RUNNER := megoocolab-runner
VERSIONS := backend/migrations/versions

ifeq ($(STACK),)
COMPOSE := docker compose
ENV_FILE := .env
else ifeq ($(filter-out dev e2e,$(STACK))$(word 2,$(STACK)),)
COMPOSE := docker compose -p megooitadmin-$(STACK) --env-file tools/stacks/$(STACK).env
ENV_FILE :=
else
$(error STACK must be dev or e2e)
endif

help:
	@echo "Usage: make <target> [STACK=dev|STACK=e2e]"
	@echo ""
	@echo "  up                     Build and start the stack, and wait until it is healthy (creates .env first)"
	@echo "  down                   Stop the stack. The database volume stays"
	@echo "  logs                   Follow the logs of the stack"
	@echo "  migrate                Apply the migrations in the running backend"
	@echo "  shell-backend          Open a shell in the running backend"
	@echo "  migration name=<name>  Create the next numbered migration on the scratch database"
	@echo "  test                   Run every backend, frontend and stack check"
	@echo "  test-security          Run the security suites"
	@echo "  release-check          Check the versions and the release plan"
	@echo ""
	@echo "Without STACK, up, down, logs, migrate and shell-backend act on the real instance."

# Only the real instance reads .env, and an existing file is never touched.
.env:
	@pw=$$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n'); \
	if ! printf '%s' "$$pw" | grep -Eqx '[0-9a-f]{32}'; then \
		echo "Could not read a random password from /dev/urandom: .env was not written." >&2; exit 1; \
	fi; \
	(umask 077; printf 'POSTGRES_PASSWORD=%s\n' "$$pw" > .env); \
	echo "Created .env with a new database password. Keep this file: the database keeps the password it was first started with."

up: $(ENV_FILE)
	$(COMPOSE) up -d --build --wait --wait-timeout 300

# Never with -v: the database volume holds the data.
down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

migrate:
	$(COMPOSE) exec backend alembic upgrade head

shell-backend:
	$(COMPOSE) exec backend bash
```

Part B (step 3, appended after part A):

```make

# The highest migration number plus one, with four digits. The leading 1 keeps 0008 from being read as octal.
LAST_MIGRATION = $(lastword $(sort $(foreach file,$(notdir $(wildcard $(VERSIONS)/[0-9][0-9][0-9][0-9]_*.py)),$(firstword $(subst _, ,$(file))))))
NEXT_MIGRATION = $(shell printf '%04d' $$((1$(or $(LAST_MIGRATION),0000) - 10000 + 1)))
REQUIRE_RUNNER = @command -v $(RUNNER) >/dev/null 2>&1 || { echo "make $@ needs $(RUNNER) on PATH: it starts the throwaway databases of the checks." >&2; exit 1; }

# The name is checked by the shell from the environment, before make puts it into a command.
migration:
	@case "$$name" in ''|[!a-z]*|*[!a-z0-9_]*) echo "make migration needs a name of a-z, 0-9 and _ that starts with a letter, for example: make migration name=add_users" >&2; exit 1;; esac
	$(REQUIRE_RUNNER)
	cd backend && $(RUNNER) services run migrate -- sh -c 'uv run alembic upgrade head && uv run alembic revision --autogenerate --rev-id $(NEXT_MIGRATION) -m "$(subst _, ,$(name))"'

test:
	$(REQUIRE_RUNNER)
	cd backend && $(RUNNER) services run test -- uv run pytest
	cd frontend && if [ ! -d node_modules ]; then npm ci; fi && npx tsc --noEmit && npm test
	cd backend && $(RUNNER) services run image -- uv run pytest -m docker
	cd frontend && $(RUNNER) services run web -- npm run test:image
	cd backend && $(RUNNER) services run stack -- uv run pytest -m stack

test-security:
	@echo "make test-security: the security suites are not in the repository yet. They come with Phases 3 and 4." >&2; exit 1

release-check:
	@test -f tools/release/versions.py || { echo "make release-check: tools/release/versions.py is not in the repository yet." >&2; exit 1; }
	python tools/release/versions.py check
	python tools/release/versions.py plan
```

### L6 `tools/stacks/dev.env` (and `e2e.env`)

```dotenv
# The megooitadmin-dev stack (make up STACK=dev). Throwaway values, not secrets.
MEGOOITADMIN_HTTP_PORT=127.0.0.1:8080
POSTGRES_PASSWORD=megooitadmin
```

`tools/stacks/e2e.env` is the same with `megooitadmin-e2e`, `STACK=e2e` and port `8081`.

### L7 `.env.example`

```dotenv
# The real instance reads .env. `make up` creates it with a random POSTGRES_PASSWORD when it is missing.

# The database password. Letters and digits only: it is also part of the backend's database URL.
# The database keeps the password it was first started with, so keep .env once the stack has run.
POSTGRES_PASSWORD=

# Caddy's published port, the only port the stack opens. Put an address before it to listen on that
# address only, for example 127.0.0.1:8080. Use another port when 80 is taken or Docker is rootless.
#MEGOOITADMIN_HTTP_PORT=80
```

### L8 `backend/tests/test_makefile.py`

Part A (step 2):

```python
"""The Makefile's targets, run in a copy of the Makefile. Most use make -n, which prints the commands and runs
none of them. They need make, not Docker."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

MAKEFILE = Path(__file__).resolve().parents[2] / "Makefile"
UP = "up -d --build --wait --wait-timeout 300"
TARGETS = ["up", "down", "logs", "migrate", "shell-backend", "migration", "test", "test-security", "release-check"]


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    if shutil.which("make") is None:
        pytest.fail("make is not on PATH. Install GNU Make to run these tests.")
    shutil.copy(MAKEFILE, tmp_path / "Makefile")
    versions = tmp_path / "backend" / "migrations" / "versions"
    versions.mkdir(parents=True)
    for name in ("0001_initial.py", "0007_add_servers.py"):
        (versions / name).write_text("")
    return tmp_path


def make(workdir: Path, *args: str, path: str | None = None) -> subprocess.CompletedProcess[str]:
    # Without the caller's STACK, name or make flags (make test runs this suite from inside make).
    env = {k: v for k, v in os.environ.items() if k not in {"STACK", "name", "MAKEFLAGS", "MAKELEVEL", "MFLAGS"}}
    if path:
        env["PATH"] = path
    return subprocess.run(["make", "--no-print-directory", *args], cwd=workdir, env=env, capture_output=True, text=True, timeout=30)


def test_plain_make_lists_the_targets(workdir):
    result = make(workdir)
    assert result.returncode == 0, result.stderr
    for target in TARGETS:
        assert target in result.stdout


def test_up_creates_env_then_starts_the_real_instance_and_waits(workdir):
    result = make(workdir, "-n", "up")
    assert result.returncode == 0, result.stderr
    assert f"docker compose {UP}" in result.stdout.splitlines()
    assert result.stdout.index("/dev/urandom") < result.stdout.index(f"docker compose {UP}")
    assert not (workdir / ".env").exists()


@pytest.mark.parametrize("stack", ["dev", "e2e"])
def test_up_with_a_stack_uses_its_own_project_and_env_file_and_never_env(workdir, stack):
    result = make(workdir, "-n", "up", f"STACK={stack}")
    assert result.returncode == 0, result.stderr
    assert f"docker compose -p megooitadmin-{stack} --env-file tools/stacks/{stack}.env {UP}" in result.stdout.splitlines()
    assert "/dev/urandom" not in result.stdout
    assert not (workdir / ".env").exists()


@pytest.mark.parametrize(
    ("target", "command"),
    [
        ("logs", "logs -f"),
        ("migrate", "exec backend alembic upgrade head"),
        ("shell-backend", "exec backend bash"),
    ],
)
def test_the_stack_targets_act_on_the_chosen_stack(workdir, target, command):
    result = make(workdir, "-n", target, "STACK=dev")
    assert f"docker compose -p megooitadmin-dev --env-file tools/stacks/dev.env {command}" in result.stdout.splitlines()


def test_down_keeps_the_database_volume(workdir):
    result = make(workdir, "-n", "down")
    assert result.stdout.splitlines() == ["docker compose down"]


@pytest.mark.parametrize("stack", ["prod", "dev e2e"])
def test_an_unknown_stack_stops(workdir, stack):
    result = make(workdir, "-n", "down", f"STACK={stack}")
    assert result.returncode != 0
    assert "STACK must be dev or e2e" in result.stderr


def test_the_env_rule_writes_a_random_password_only_its_owner_can_read(workdir):
    first = make(workdir, ".env")
    assert first.returncode == 0, first.stderr
    assert "Created .env" in first.stdout
    env_file = workdir / ".env"
    assert re.fullmatch(r"POSTGRES_PASSWORD=[0-9a-f]{32}\n", env_file.read_text())
    assert env_file.stat().st_mode & 0o777 == 0o600
    content, mtime = env_file.read_text(), env_file.stat().st_mtime_ns
    second = make(workdir, ".env")
    assert second.returncode == 0, second.stderr
    assert "Created" not in second.stdout
    assert (env_file.read_text(), env_file.stat().st_mtime_ns) == (content, mtime)
```

Part B (step 3, appended):

```python


def test_migration_takes_the_next_number_and_the_name_as_its_message(workdir):
    result = make(workdir, "-n", "migration", "name=add_users")
    assert result.returncode == 0, result.stderr
    assert "--rev-id 0008 " in result.stdout
    assert '-m "add users"' in result.stdout


@pytest.mark.parametrize("args", [[], ["name="], ["name=x;y"], ["name=1abc"], ["name=add-users"]])
def test_migration_without_a_valid_name_runs_nothing(workdir, args):
    bin_dir = workdir / "bin"
    bin_dir.mkdir()
    runner = bin_dir / "megoocolab-runner"
    runner.write_text('#!/bin/sh\ntouch "$(dirname "$0")/ran"\n')
    runner.chmod(0o755)
    result = make(workdir, "migration", *args, path=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    assert result.returncode != 0
    assert "make migration needs a name" in result.stderr
    assert not (bin_dir / "ran").exists()


def test_test_security_says_its_suites_are_not_in_the_repository_yet(workdir):
    result = make(workdir, "test-security")
    assert result.returncode != 0
    assert "the security suites are not in the repository yet" in result.stderr


def test_release_check_says_the_release_tool_is_not_in_the_repository_yet(workdir):
    result = make(workdir, "release-check")
    assert result.returncode != 0
    assert "tools/release/versions.py is not in the repository yet" in result.stderr
```

### L9 `README.md`

```markdown
# MegooITAdmin

## Run it

You need Docker with Compose v2 and GNU Make. On Windows, run `make` from Git Bash.

    make up

This builds and starts Caddy, the frontend, the backend and the database, and returns once the app answers.
The app is then at `http://<this host>/`, and `curl http://localhost/api/health` gives `{"status": "ok"}`.
`make down` stops it and keeps the data; `make` lists every target.

- **`.env`.** The first `make up` creates `.env` with a random database password. Keep this file: the database
  keeps the password it was first started with, so a new one would lock the backend out. `.env.example`
  explains every variable.
- **The port.** Caddy is the only service with a published port, 80 by default. Set `MEGOOITADMIN_HTTP_PORT` in
  `.env` to use another one, or an address and port such as `127.0.0.1:8080` (for example when port 80 is taken
  or Docker is rootless).
- **TLS.** Caddy serves plain HTTP. Put a TLS proxy in front of it on a private address: Caddy trusts the
  `X-Forwarded-*` headers only from private addresses.
- **A second copy.** `make up STACK=dev` starts the project `megooitadmin-dev` on `127.0.0.1:8080`, beside the
  real one, with throwaway values. Pass the same `STACK=dev` to `down`, `logs`, `migrate` and `shell-backend`.
```

---

## Steps

### 1. The Compose stack runs Caddy, the frontend, the backend and the database, proved by a stack check

See the step detail.

### 2. `make up` starts the stack, creating `.env`, and `STACK=dev` or `STACK=e2e` starts a throwaway copy

See the step detail.

### 3. `make migration`, `make test`, `make test-security` and `make release-check`

See the step detail.

### 4. The README says how to run it, and the whole feature is checked end to end

See the step detail.

(Each step's full detail is in the `steps` list submitted with this plan, word for word.)

---

## Final verification

From the repository root unless noted. Never without `STACK=` for the stack targets.

1. `cd backend && megoocolab-runner services run test -- uv run pytest` passes (includes `test_makefile.py`).
2. `cd backend && megoocolab-runner services run stack -- uv run pytest -m stack` passes.
3. `cd backend && megoocolab-runner services run image -- uv run pytest -m docker` and `cd frontend && megoocolab-runner services run web -- npm run test:image` still pass.
4. `make up STACK=dev`; `curl -fsS http://127.0.0.1:8080/api/health` prints `{"status":"ok"}`; `make migrate STACK=dev`; `make down STACK=dev`; `make up STACK=dev` again and `docker compose -p megooitadmin-dev --env-file tools/stacks/dev.env exec -T db psql -h 127.0.0.1 -U megooitadmin -d megooitadmin -tAc 'SELECT version_num FROM alembic_version'` prints `0001` (the volume kept it); `make down STACK=dev`.
5. `make test` runs from start to end and exits 0.
6. Skipped, and to be reported as skipped: `make test-security` and `make release-check` (their parts are not in the repository yet; both targets stop with that message).
