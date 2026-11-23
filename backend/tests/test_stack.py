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

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "docker-compose.yml"
CADDYFILE = ROOT / "caddy" / "Caddyfile"
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
    networks = _declared()["networks"]
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
