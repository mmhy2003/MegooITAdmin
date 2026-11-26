"""Checks of the whole Compose stack, through Caddy. They start nothing themselves: the stack service set has
built the stack from this checkout through docker-compose.build.yml and waited until every service was healthy."""

import base64
import json
import os
import re
import subprocess
import time
from collections.abc import Callable
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
    "collector": {"core", "servers"},
    "db": {"core", "exec"},
    "valkey": {"core"},
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


def test_the_stack_has_exactly_its_six_services():
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


def test_the_backend_mounts_the_ssh_key_volume_and_the_collector_reads_it():
    services = _model()["services"]
    for name, read_only in (("backend", False), ("collector", True)):
        volumes = services[name]["volumes"]
        assert [(v["type"], v["source"], v["target"]) for v in volumes] == [("volume", "ssh_key", "/var/lib/megooitadmin/ssh")], name
        assert volumes[0].get("read_only", False) is read_only, name
    mounting = {"backend", "collector"}
    others = {name for name, service in services.items() if name not in mounting and any(v["source"] == "ssh_key" for v in service.get("volumes", []))}
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
    assert services["collector"]["image"] == f"{GHCR}backend:${{MEGOOITADMIN_VERSION:-latest}}"
    assert {name for name, service in services.items() if "build" in service} == set()


def test_the_build_overlay_builds_exactly_the_two_images_under_local_names():
    services = _written(BUILD_FILE)
    assert set(services) == {"backend", "frontend", "collector"}
    # The collector runs the image the backend service builds, and never pulls it.
    assert services.pop("collector") == {"image": "megooitadmin-backend:${MEGOOITADMIN_VERSION:-dev}", "pull_policy": "never"}
    for name, service in services.items():
        assert service["build"] == f"./{name}"
        assert service["image"] == f"megooitadmin-{name}:${{MEGOOITADMIN_VERSION:-dev}}"
        assert "/" not in service["image"].split(":")[0]  # no registry


def test_the_stack_runs_the_images_it_built_under_its_own_tag():
    project = _env("MEGOO_SERVICES_PROJECT")
    for name, image in (("backend", "backend"), ("frontend", "frontend"), ("collector", "backend")):
        container = _compose("ps", "-q", name).stdout.strip()
        inspected = subprocess.run(
            ["docker", "inspect", "--format", "{{.Config.Image}}", container], capture_output=True, text=True, timeout=30
        )
        assert inspected.stdout.strip() == f"megooitadmin-{image}:{project}", name


def _environ_of(service: str) -> dict[str, str]:
    result = _compose("exec", "-T", service, "cat", "/proc/1/environ")
    assert result.returncode == 0, result.stderr
    return dict(item.split("=", 1) for item in result.stdout.split("\0") if "=" in item)


def test_the_collector_runs_the_backends_image_as_its_own_role():
    collector = _model()["services"]["collector"]
    assert collector["entrypoint"] == ["python", "-m", "app.collector"]
    # Names and booleans only, so a failure never prints a password.
    for variables in (collector["environment"], _environ_of("collector")):
        assert variables.get("DATABASE_URL", "").startswith("postgresql+asyncpg://megooitadmin_collector:") is True
        assert not set(variables) & {"AUTH_SECRET_KEY", "DATABASE_OWNER_URL", "DATABASE_COLLECTOR_URL"}
    assert {name: d["condition"] for name, d in collector["depends_on"].items()} == {
        "backend": "service_healthy",
        "valkey": "service_healthy",
    }
    assert collector["healthcheck"]["test"] == ["CMD", "python", "-m", "app.collector.health"]


def test_the_backend_waits_for_a_healthy_database():
    assert _model()["services"]["backend"]["depends_on"]["db"]["condition"] == "service_healthy"


def test_the_backend_waits_for_a_healthy_valkey_and_has_its_url():
    backend = _model()["services"]["backend"]
    assert backend["depends_on"]["valkey"]["condition"] == "service_healthy"
    assert backend["environment"]["VALKEY_URL"] == "valkey://valkey:6379/0"


def test_valkey_keeps_an_append_only_file_in_valkey_data():
    valkey = _model()["services"]["valkey"]
    assert valkey["command"] == ["valkey-server", "--appendonly", "yes"]
    assert [(v["type"], v["source"], v["target"]) for v in valkey["volumes"]] == [("volume", "valkey_data", "/data")]
    assert "valkey_data" in _model()["volumes"]
    result = _compose("exec", "-T", "valkey", "valkey-cli", "CONFIG", "GET", "appendonly")
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["appendonly", "yes"]


FANOUT_PROBE = """
import asyncio, uuid
from datetime import UTC, datetime
from app.core.valkey import valkey_client
from app.metrics.fanout import publish, subscribe
from app.metrics.samples import Reading, Sample

async def main():
    client = valkey_client()
    sample = Sample(time=datetime.now(UTC), server_id=uuid.uuid4(), readings=(Reading(metric="cpu.used_percent", value=12.5),))
    async with subscribe(client, [sample.server_id]) as samples:
        await publish(client, sample)
        received = await asyncio.wait_for(anext(samples), 5)
    await client.aclose()
    print("received" if received == sample else "different")

asyncio.run(main())
"""


def test_a_sample_published_in_the_backend_reaches_a_subscriber_there():
    result = _compose("exec", "-T", "backend", "python", "-c", FANOUT_PROBE)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "received"


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
        "collector": ["python", "-c", f"import socket; socket.gethostbyname('{host}')"],
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
        ("backend", "valkey", True),
        ("caddy", "valkey", False),
        ("frontend", "valkey", False),
        ("collector", "db", True),
        ("collector", "valkey", True),
        ("frontend", "collector", False),
    ],
)
def test_only_the_backend_and_the_collector_can_find_the_database_and_valkey(service, host, expected):
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
    variables = _environ_of("backend")
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


def _psql_as_collector(sql: str) -> subprocess.CompletedProcess[str]:
    return _compose(
        "exec", "-T", "-e", f"PGPASSWORD={_env('POSTGRES_COLLECTOR_PASSWORD')}", "db",
        "psql", "-h", "127.0.0.1", "-U", "megooitadmin_collector", "-d", "megooitadmin", "-tAc", sql,
    )


def test_the_backend_sets_the_collector_password_and_does_not_hold_it():
    login = _psql_as_collector("SELECT current_user")
    assert login.returncode == 0, login.stderr
    assert login.stdout.strip() == "megooitadmin_collector"
    assert "DATABASE_COLLECTOR_URL" not in _environ_of("backend")


def test_the_api_role_can_read_metrics_1m():
    result = _psql_as_api_role("SELECT count(*) FROM metrics_1m")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "0"


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


def _owner_sql(sql: str) -> str:
    """What the SQL prints, read as the database owner: one line per row, columns split by |."""
    result = _compose(
        "exec", "-T", "-e", f"PGPASSWORD={_env('POSTGRES_PASSWORD')}", "db",
        "psql", "-h", "127.0.0.1", "-U", "megooitadmin", "-d", "megooitadmin", "-tA", "-F", "|", "-c", sql,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _audit_of_server(server_id: str) -> list[tuple[str, str]]:
    """(action, result) of each audit event of the server, oldest first, read as the database owner."""
    UUID(server_id)  # only a UUID goes into the SQL
    sql = f"SELECT action, result FROM audit_log WHERE target_type = 'server' AND target_id = '{server_id}' ORDER BY seq"
    return [tuple(line.split("|")) for line in _owner_sql(sql).splitlines() if line]


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
    result = owner.post(f"/api/servers/{server_id}/connection-test", timeout=30).json()
    assert result["ok"] is True, result
    assert [c["status"] for c in result["checks"]] == ["passed"] * 7, result
    assert _compose_with_fake_server("exec", "-T", "fake-server", "swap-host-key").returncode == 0
    refused = owner.post(f"/api/servers/{server_id}/connection-test", timeout=30).json()
    assert (refused["ok"], refused["reason"]) == (False, "host_key_changed")
    assert owner.get(f"/api/servers/{server_id}").json()["host_key_state"] == "changed"
    events = _audit_of_server(server_id)
    assert ("server.created", "success") in events
    assert ("server.connection_tested", "success") in events


def test_the_setup_script_downloads_through_caddy(owner):
    response = owner.get("/api/ssh/setup-script")
    assert response.status_code == 200, response.text
    assert response.text.startswith("#!/bin/sh")
    assert "megoo-setup.sh" in response.headers["content-disposition"]


def _wait(check: Callable[[], bool], timeout: float, what: str, every: float = 2) -> None:
    deadline = time.monotonic() + timeout
    while not check():
        if time.monotonic() > deadline:
            pytest.fail(f"Not within {timeout:.0f} s: {what}")
        time.sleep(every)


def _db_now() -> str:
    return _owner_sql("SELECT now()").strip()


def _newest(server_id: str) -> str:
    """The time of the server's newest sample, -infinity without one."""
    UUID(server_id)  # only a UUID goes into the SQL
    return _owner_sql(f"SELECT coalesce(max(time), '-infinity') FROM metrics WHERE server_id = '{server_id}'").strip()


def _newer(server_id: str, t: str) -> bool:
    """Whether the server has a sample newer than t, a time the database printed."""
    UUID(server_id)  # only a UUID goes into the SQL
    return _owner_sql(f"SELECT coalesce(max(time) > '{t}', false) FROM metrics WHERE server_id = '{server_id}'").strip() == "t"


def _monitoring(owner: httpx.Client, server_id: str) -> dict | None:
    return owner.get(f"/api/servers/{server_id}").json()["monitoring"]


def _state(owner: httpx.Client, server_id: str) -> str | None:
    monitoring = _monitoring(owner, server_id)
    return monitoring and monitoring["state"]


SUBSCRIBE_PROBE = """
import asyncio, sys, uuid
from app.core.valkey import valkey_client
from app.metrics.fanout import subscribe

async def main():
    client = valkey_client()
    async with subscribe(client, [uuid.UUID(sys.argv[1])]) as samples:
        await asyncio.wait_for(anext(samples), 20)
    await client.aclose()
    print("received")

asyncio.run(main())
"""


def test_the_collector_streams_the_fake_server_and_survives_restarts_and_a_network_drop(owner):
    public = _compose_with_fake_server("exec", "-T", "backend", "python", "-m", "app.ssh.cli", "public-key")
    assert public.returncode == 0, public.stderr
    authorized = _compose_with_fake_server("exec", "-T", "fake-server", "authorize-key", input=public.stdout)
    assert authorized.returncode == 0, authorized.stderr
    group = owner.post("/api/server-groups", json={"name": "metrics-lab"}).json()["id"]
    server = {"name": "fake-server-metrics", "address": "fake-server", "group_id": group, "os": "linux", "port": 22}
    server_id = owner.post("/api/servers", json=server).json()["id"]
    fetched = owner.post(f"/api/servers/{server_id}/host-key/fetch", timeout=30).json()
    assert fetched["ok"], fetched
    assert owner.put(f"/api/servers/{server_id}/host-key", json={"fingerprint": fetched["fingerprint"]}).status_code == 200

    # The collector finds the pinned server within one poll and streams it.
    _wait(lambda: _newest(server_id) != "-infinity", 60, "a sample of the fake server in metrics")
    _wait(lambda: _state(owner, server_id) == "reachable", 60, "the fake server is reachable")
    probe = _compose("exec", "-T", "backend", "python", "-c", SUBSCRIBE_PROBE, server_id)
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == "received"

    t = _db_now()
    assert _compose_with_fake_server("restart", "fake-server").returncode == 0
    _wait(lambda: _newer(server_id, t), 90, "a sample after the fake server restarted")

    t = _db_now()
    assert _compose("restart", "collector").returncode == 0
    _wait(lambda: _newer(server_id, t), 90, "a sample after the collector restarted")

    container = _compose_with_fake_server("ps", "-q", "fake-server").stdout.strip()
    assert container
    network = f"{_env('MEGOO_SERVICES_PROJECT')}_servers"
    disconnected = subprocess.run(["docker", "network", "disconnect", network, container], capture_output=True, text=True, timeout=60)
    assert disconnected.returncode == 0, disconnected.stderr
    try:
        _wait(lambda: _state(owner, server_id) == "unreachable", 90, "the fake server is unreachable without its network")
    finally:
        # Back on its network even when the wait failed, so the checks after this one find it.
        t = _db_now()
        connect = ["docker", "network", "connect", "--alias", "fake-server", network, container]
        reconnected = subprocess.run(connect, capture_output=True, text=True, timeout=60)
    assert reconnected.returncode == 0, reconnected.stderr
    _wait(lambda: _state(owner, server_id) == "reachable" and _newer(server_id, t), 150, "samples again once the network is back")


def _checks(owner: httpx.Client, server_id: str) -> dict:
    return owner.get(f"/api/servers/{server_id}/checks").json()


def test_the_collector_checks_the_fake_server_and_lists_its_containers(owner):
    public = _compose_with_fake_server("exec", "-T", "backend", "python", "-m", "app.ssh.cli", "public-key")
    assert public.returncode == 0, public.stderr
    authorized = _compose_with_fake_server("exec", "-T", "fake-server", "authorize-key", input=public.stdout)
    assert authorized.returncode == 0, authorized.stderr
    group = owner.post("/api/server-groups", json={"name": "checks-lab"}).json()["id"]
    server = {"name": "fake-server-checks", "address": "fake-server", "group_id": group, "os": "linux", "port": 22}
    server_id = owner.post("/api/servers", json=server).json()["id"]
    fetched = owner.post(f"/api/servers/{server_id}/host-key/fetch", timeout=30).json()
    assert fetched["ok"], fetched
    assert owner.put(f"/api/servers/{server_id}/host-key", json={"fingerprint": fetched["fingerprint"]}).status_code == 200

    # The first round starts soon after the stream and runs one check at a time.
    _wait(lambda: all(c["status"] == "ok" for c in _checks(owner, server_id)["checks"]), 120, "six ok checks of the fake server")
    checks = _checks(owner, server_id)
    assert [c["kind"] for c in checks["checks"]] == ["containers", "processes", "services", "logins", "updates", "certificates"]
    assert checks["can_view_processes"] is True
    services = next(c for c in checks["checks"] if c["kind"] == "services")
    assert services["data"]["failed"] == 1

    containers = owner.get(f"/api/servers/{server_id}/containers").json()
    assert [(c["compose_project"], c["name"]) for c in containers] == [
        ("monitoring", "monitoring-grafana-1"),
        ("shop", "shop-db-1"),
        ("shop", "shop-web-1"),
        (None, "hello-adhoc"),
    ]


def test_after_sign_out_pages_redirect_to_login(owner):
    # Last in the file: it ends the session the `owner` fixture holds.
    response = owner.post("/api/auth/logout")
    assert response.status_code == 200, response.text
    response = owner.get("/")
    assert response.status_code == 307
    assert response.headers["location"].endswith("/login")
