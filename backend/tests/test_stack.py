"""Checks of the whole Compose stack, through Caddy. They start nothing themselves: the stack service set has
built the stack from this checkout through docker-compose.build.yml and waited until every service was healthy."""

import base64
import json
import os
import re
import subprocess
from functools import cache
from pathlib import Path
from uuid import UUID

import httpx
import pyotp
import pytest
import yaml

pytestmark = pytest.mark.stack

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "docker-compose.yml"
BUILD_FILE = ROOT / "docker-compose.build.yml"
FAKE_SERVER_FILE = ROOT / "tools" / "fake-server" / "docker-compose.stack.yml"
CADDYFILE = ROOT / "caddy" / "Caddyfile"
GHCR = "ghcr.io/mmhy2003/megooitadmin-"
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
    command = ["docker", "compose", "-p", _env("MEGOO_SERVICES_PROJECT"), "-f", str(COMPOSE_FILE), "-f", str(BUILD_FILE), *args]
    return subprocess.run(command, capture_output=True, text=True, timeout=120)


def _compose_with_fake_server(*args: str, input: str | None = None) -> subprocess.CompletedProcess[str]:
    # The stack set also runs the fake server, which only docker-compose.stack.yml declares.
    project = _env("MEGOO_SERVICES_PROJECT")
    command = ["docker", "compose", "-p", project, "-f", str(COMPOSE_FILE), "-f", str(BUILD_FILE), "-f", str(FAKE_SERVER_FILE), *args]
    return subprocess.run(command, input=input, capture_output=True, text=True, timeout=120)


@cache
def _model() -> dict:
    result = _compose("config", "--format", "json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@cache
def _declared() -> dict:
    # The file as written: the normalised model leaves out networks no service joins yet, such as sandbox.
    result = _compose("config", "--no-interpolate", "--no-normalize", "--format", "json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _get(path: str, headers: dict[str, str] | None = None) -> httpx.Response:
    with httpx.Client(base_url=_env("STACK_URL"), timeout=10) as client:
        return client.get(path, headers=headers)


def test_api_health_answers_ok_through_caddy():
    response = _get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# The tests run in file order on one fresh database per run: the first one needs the install unclaimed, the
# `owner` fixture claims it, and the sign-out test comes last because it ends the owner's session.
@pytest.mark.parametrize("path", ["/", "/no-such-page"])
def test_before_setup_every_page_redirects_to_setup(path):
    response = _get(path)
    assert response.status_code == 307
    assert response.headers["location"].endswith("/setup")


OWNER_EMAIL = "owner@stack.invalid"
OWNER_PASSWORD = "correct horse battery staple"


@pytest.fixture(scope="module")
def owner():
    """A client signed in as the Owner: setup with the code from the host, then an enrolled authenticator."""
    result = _compose("exec", "-T", "backend", "python", "-m", "app.auth.cli", "setup-code")
    assert result.returncode == 0, result.stderr
    match = re.search(r"Setup code: (\S+)", result.stdout)
    assert match, result.stdout
    with httpx.Client(base_url=_env("STACK_URL"), timeout=10) as client:
        setup = {"code": match[1], "name": "Stack Owner", "email": OWNER_EMAIL, "password": OWNER_PASSWORD}
        response = client.post("/api/auth/setup", json=setup)
        assert response.status_code == 200, response.text
        response = client.post("/api/auth/mfa/enrol", json={})
        assert response.status_code == 200, response.text
        code = pyotp.TOTP(response.json()["secret"]).now()
        response = client.post("/api/auth/mfa/enrol/confirm", json={"code": code})
        assert response.status_code == 200, response.text
        yield client


@pytest.mark.parametrize("path", ["/", "/servers"])
def test_the_frontend_serves_its_pages_through_caddy(owner, path):
    response = owner.get(path)
    assert response.status_code == 200
    assert "MegooITAdmin" in response.text


def test_an_unknown_api_path_gets_the_backends_json_404():
    response = _get("/api/no-such-route")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_an_unknown_page_gets_the_frontends_404_page(owner):
    response = owner.get("/no-such-page")
    assert response.status_code == 404
    assert "Page not found" in response.text


def test_the_cookie_is_secure_behind_https(owner):
    login = {"email": OWNER_EMAIL, "password": OWNER_PASSWORD}
    with httpx.Client(base_url=_env("STACK_URL"), timeout=10) as client:
        response = client.post("/api/auth/login", json=login, headers={"X-Forwarded-Proto": "https"})
    assert response.status_code == 200, response.text
    assert re.search(r";\s*secure(;|$)", response.headers["set-cookie"], re.IGNORECASE), response.headers["set-cookie"]


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
    networks = _declared()["networks"]
    assert set(networks) == {"edge", "core", "servers", "exec", "sandbox"}
    assert {name for name, network in networks.items() if network.get("internal")} == {"core", "exec", "sandbox"}


def test_only_the_backend_mounts_the_ssh_key_volume():
    services = _model()["services"]
    backend = [(v["type"], v["source"], v["target"]) for v in services["backend"]["volumes"]]
    assert backend == [("volume", "ssh_key", "/var/lib/megooitadmin/ssh")]
    others = {name for name, service in services.items() if name != "backend" and any(v["source"] == "ssh_key" for v in service.get("volumes", []))}
    assert others == set()
    assert "ssh_key" in _model()["volumes"]


def test_docker_compose_yml_holds_no_fake_server():
    assert "fake-server" not in _declared()["services"]


def _written(path: Path) -> dict:
    return yaml.safe_load(path.read_text())["services"]


def test_docker_compose_yml_pulls_the_two_release_images_and_builds_nothing():
    services = _written(COMPOSE_FILE)
    for name in ("backend", "frontend"):
        assert services[name]["image"] == f"{GHCR}{name}:${{MEGOOITADMIN_VERSION:-latest}}"
    assert {name for name, service in services.items() if "build" in service} == set()


def test_the_build_overlay_builds_exactly_the_two_images_under_local_names():
    services = _written(BUILD_FILE)
    assert set(services) == {"backend", "frontend"}
    for name, service in services.items():
        assert service["build"] == f"./{name}"
        assert service["image"] == f"megooitadmin-{name}:${{MEGOOITADMIN_VERSION:-dev}}"
        assert "/" not in service["image"].split(":")[0]  # no registry


def test_the_stack_runs_the_images_it_built_under_its_own_tag():
    project = _env("MEGOO_SERVICES_PROJECT")
    for name in ("backend", "frontend"):
        container = _compose("ps", "-q", name).stdout.strip()
        inspected = subprocess.run(
            ["docker", "inspect", "--format", "{{.Config.Image}}", container], capture_output=True, text=True, timeout=30
        )
        assert inspected.stdout.strip() == f"megooitadmin-{name}:{project}"


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


def test_the_server_holds_only_the_api_roles_url():
    # Names and booleans only, so a failure never prints a password.
    result = _compose("exec", "-T", "backend", "cat", "/proc/1/environ")
    assert result.returncode == 0, result.stderr
    variables = dict(item.split("=", 1) for item in result.stdout.split("\0") if "=" in item)
    names = set(variables)
    assert "DATABASE_OWNER_URL" not in names
    serves_as_api_role = variables.get("DATABASE_URL", "").startswith("postgresql+asyncpg://megooitadmin_api:")
    assert serves_as_api_role is True


def _psql_as_api_role(sql: str) -> subprocess.CompletedProcess[str]:
    return _compose(
        "exec", "-T", "-e", f"PGPASSWORD={_env('POSTGRES_API_PASSWORD')}", "db",
        "psql", "-h", "127.0.0.1", "-U", "megooitadmin_api", "-d", "megooitadmin", "-tAc", sql,
    )


def test_the_api_role_logs_in_and_may_not_update_audit_log():
    login = _psql_as_api_role("SELECT current_user")
    assert login.returncode == 0, login.stderr
    assert login.stdout.strip() == "megooitadmin_api"
    update = _psql_as_api_role("UPDATE audit_log SET reason = 'changed'")
    assert update.returncode != 0, update.stdout
    assert "permission denied" in update.stderr


def test_caddy_accepts_the_caddyfile_and_finds_nothing_to_reformat():
    validate = _compose("exec", "-T", "caddy", "caddy", "validate", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile")
    assert validate.returncode == 0, validate.stdout + validate.stderr
    # caddy fmt prints the file as it would format it; --diff prints every line too, so it cannot be empty.
    fmt = _compose("exec", "-T", "caddy", "caddy", "fmt", "/etc/caddy/Caddyfile")
    assert fmt.returncode == 0, fmt.stderr
    assert fmt.stdout == CADDYFILE.read_text()


def test_a_staging_only_admin_sees_only_staging_is_refused_settings_and_is_disabled(owner):
    # The design's walkthrough on the real stack: two groups, an Admin on staging only, then disabled.
    groups = {}
    for name in ("staging", "production"):
        response = owner.post("/api/server-groups", json={"name": name})
        assert response.status_code == 200, response.text
        groups[name] = response.json()["id"]
    invite = {
        "name": "Ada",
        "email": "ada@stack.invalid",
        "platform_role": None,
        "grants": [{"group_id": groups["staging"], "role": "admin", "connect_ssh": True}],
    }
    response = owner.post("/api/users", json=invite)
    assert response.status_code == 200, response.text
    ada_id, token = response.json()["user_id"], response.json()["token"]
    with httpx.Client(base_url=_env("STACK_URL"), timeout=10) as client:
        response = client.post("/api/auth/invite/check", json={"token": token})
        assert response.status_code == 200, response.text
        assert response.json() == {"name": "Ada", "email": "ada@stack.invalid"}
        response = client.post("/api/auth/invite/accept", json={"token": token, "password": "ada's own long password"})
        assert response.status_code == 200, response.text
        response = client.post("/api/auth/mfa/enrol", json={})
        assert response.status_code == 200, response.text
        code = pyotp.TOTP(response.json()["secret"]).now()
        response = client.post("/api/auth/mfa/enrol/confirm", json={"code": code})
        assert response.status_code == 200, response.text

        response = client.get("/api/auth/me")
        assert response.status_code == 200, response.text
        assert [(g["group_name"], g["role"]) for g in response.json()["grants"]] == [("staging", "admin")]
        response = client.get("/api/server-groups")
        assert response.status_code == 200, response.text
        assert [group["name"] for group in response.json()] == ["staging"]
        assert client.get("/api/users").status_code == 403
        assert client.get("/settings").status_code == 200

        server_ids = {}
        for name in ("staging", "production"):
            server = {"name": f"stack-{name}-01", "address": "10.0.0.1", "group_id": groups[name], "os": "linux", "port": 22}
            response = owner.post("/api/servers", json=server)
            assert response.status_code == 200, response.text
            server_ids[name] = response.json()["id"]
        response = client.get("/api/servers")
        assert response.status_code == 200, response.text
        assert [server["name"] for server in response.json()] == ["stack-staging-01"]
        assert client.get(f"/api/servers/{server_ids['production']}").status_code == 404

        response = owner.post(f"/api/users/{ada_id}/disable")
        assert response.status_code == 204, response.text
        assert client.get("/api/auth/me").status_code == 401
        response = client.post("/api/auth/login", json={"email": "ada@stack.invalid", "password": "ada's own long password"})
        assert (response.status_code, response.json()) == (401, {"detail": "invalid_credentials"})


def _audit_of_server(server_id: str) -> list[tuple[str, str]]:
    """(action, result) of each audit event of the server, oldest first, read as the database owner."""
    UUID(server_id)  # only a UUID goes into the SQL
    sql = f"SELECT action, result FROM audit_log WHERE target_type = 'server' AND target_id = '{server_id}' ORDER BY seq"
    result = _compose(
        "exec", "-T", "-e", f"PGPASSWORD={_env('POSTGRES_PASSWORD')}", "db",
        "psql", "-h", "127.0.0.1", "-U", "megooitadmin", "-d", "megooitadmin", "-tA", "-F", "|", "-c", sql,
    )
    assert result.returncode == 0, result.stderr
    return [tuple(line.split("|")) for line in result.stdout.splitlines() if line]


def test_the_owner_pins_and_tests_the_fake_server_and_a_swapped_key_is_refused(owner):
    public = _compose_with_fake_server("exec", "-T", "backend", "python", "-m", "app.ssh.cli", "public-key")
    assert public.returncode == 0, public.stderr
    authorized = _compose_with_fake_server("exec", "-T", "fake-server", "authorize-key", input=public.stdout)
    assert authorized.returncode == 0, authorized.stderr
    group = owner.post("/api/server-groups", json={"name": "ssh-lab"}).json()["id"]
    server = {"name": "fake-server", "address": "fake-server", "group_id": group, "os": "linux", "port": 22}
    server_id = owner.post("/api/servers", json=server).json()["id"]
    fetched = owner.post(f"/api/servers/{server_id}/host-key/fetch", timeout=30).json()
    assert fetched["ok"], fetched
    assert owner.put(f"/api/servers/{server_id}/host-key", json={"fingerprint": fetched["fingerprint"]}).status_code == 200
    assert owner.post(f"/api/servers/{server_id}/connection-test", timeout=30).json()["ok"] is True
    assert _compose_with_fake_server("exec", "-T", "fake-server", "swap-host-key").returncode == 0
    refused = owner.post(f"/api/servers/{server_id}/connection-test", timeout=30).json()
    assert (refused["ok"], refused["reason"]) == (False, "host_key_changed")
    assert owner.get(f"/api/servers/{server_id}").json()["host_key_state"] == "changed"
    events = _audit_of_server(server_id)
    assert ("server.created", "success") in events
    assert ("server.connection_tested", "success") in events


def test_after_sign_out_pages_redirect_to_login(owner):
    # Last in the file: it ends the session the `owner` fixture holds.
    response = owner.post("/api/auth/logout")
    assert response.status_code == 200, response.text
    response = owner.get("/")
    assert response.status_code == 307
    assert response.headers["location"].endswith("/login")
