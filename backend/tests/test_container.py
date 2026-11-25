"""Start-up tests of the built image. They start nothing themselves: the image service set has built the image and
started it with its own database. They do not import the app or run Alembic."""

import asyncio
import os
import re
import subprocess
from pathlib import Path

import asyncpg
import httpx
import pytest

pytestmark = pytest.mark.docker

TESTS = Path(__file__).resolve().parent
VERSIONS = TESTS.parent / "migrations" / "versions"
FAILING_REVISION = TESTS / "fixtures" / "9999_fails.py"
# The throwaway key of every test set.
TEST_KEY = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"{name} is not set. Run: megoocolab-runner services run image -- uv run pytest -m docker")
    return value


def _head() -> str:
    return max(path.name[:4] for path in VERSIONS.glob("[0-9][0-9][0-9][0-9]_*.py"))


async def _fetch(sql: str, variable: str = "IMAGE_DATABASE_URL") -> list[asyncpg.Record]:
    url = _env(variable).replace("postgresql+asyncpg://", "postgresql://", 1)
    connection = await asyncpg.connect(url)
    try:
        return await connection.fetch(sql)
    finally:
        await connection.close()


async def test_the_container_migrates_on_start():
    versions = [row["version_num"] for row in await _fetch("SELECT version_num FROM alembic_version")]
    assert versions == [_head()]
    extensions = {row["extname"] for row in await _fetch("SELECT extname FROM pg_extension")}
    assert {"timescaledb", "vector"} <= extensions


async def test_api_health_responds():
    async with httpx.AsyncClient(base_url=_env("BACKEND_URL")) as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_the_proxy_headers_are_honoured():
    async with httpx.AsyncClient(base_url=_env("BACKEND_URL")) as client:
        response = await client.get("/api/health/", headers={"X-Forwarded-Proto": "https"})
    assert response.status_code == 307
    assert response.headers["location"].startswith("https://")


async def test_the_api_role_logs_in_and_is_not_a_superuser():
    sql = "SELECT current_user, rolsuper FROM pg_roles WHERE rolname = current_user"
    rows = await _fetch(sql, variable="IMAGE_API_DATABASE_URL")
    assert [tuple(row) for row in rows] == [("megooitadmin_api", False)]


async def test_the_collector_role_logs_in_and_is_not_a_superuser():
    sql = "SELECT current_user, rolsuper FROM pg_roles WHERE rolname = current_user"
    rows = await _fetch(sql, variable="IMAGE_COLLECTOR_DATABASE_URL")
    assert [tuple(row) for row in rows] == [("megooitadmin_collector", False)]


def _url(credentials: str) -> str:
    return f"postgresql+asyncpg://{credentials}@db:5432/{_env('DB_NAME')}"


def _run_once(env: dict[str, str], *extra_args: str) -> subprocess.CompletedProcess[str]:
    """Runs a one-off container of the image on the image set's network, with the given environment."""
    variables = [arg for name, value in env.items() for arg in ("-e", f"{name}={value}")]
    return subprocess.run(
        ["docker", "run", "--rm", "--network", _env("BACKEND_NETWORK"), *variables, *extra_args, _env("BACKEND_IMAGE")],
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_it_refuses_to_serve_when_a_migration_fails():
    result = _run_once(
        {
            "DATABASE_URL": _url("megooitadmin_api:megooitadminapi"),
            "DATABASE_OWNER_URL": _url("megooitadmin:megooitadmin"),
            "AUTH_SECRET_KEY": TEST_KEY,
        },
        "-v", f"{FAILING_REVISION}:/app/migrations/versions/9999_fails.py:ro",
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "Applying database migrations..." in output
    assert "9999_fails: this migration fails on purpose" in output
    assert "Uvicorn running" not in output
    versions = [row["version_num"] for row in asyncio.run(_fetch("SELECT version_num FROM alembic_version"))]
    assert versions == [_head()]


def test_it_refuses_to_serve_as_any_other_role():
    owner = _url("megooitadmin:megooitadmin")
    result = _run_once({"DATABASE_URL": owner, "DATABASE_OWNER_URL": owner, "AUTH_SECRET_KEY": TEST_KEY})
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "Applying database migrations..." in output
    assert "DATABASE_URL must connect as megooitadmin_api" in output
    assert "Uvicorn running" not in output
    assert "megooitadmin:megooitadmin@" not in output


def test_it_refuses_to_serve_without_the_auth_secret_key():
    result = _run_once(
        {
            "DATABASE_URL": _url("megooitadmin_api:megooitadminapi"),
            "DATABASE_OWNER_URL": _url("megooitadmin:megooitadmin"),
        }
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "AUTH_SECRET_KEY is not set" in output
    assert "Uvicorn running" not in output


def _container() -> str:
    """The id of the image set's backend container."""
    project = _env("MEGOO_SERVICES_PROJECT")
    container = subprocess.run(
        [
            "docker", "ps", "-q",
            "--filter", f"label=com.docker.compose.project={project}",
            "--filter", "label=com.docker.compose.service=backend",
        ],
        capture_output=True, text=True, timeout=30, check=True,
    ).stdout.strip()
    assert container, f"No backend container in the Compose project {project}"
    return container


def _exec(*command: str) -> str:
    return subprocess.run(
        ["docker", "exec", _container(), *command], capture_output=True, text=True, timeout=30, check=True
    ).stdout.strip()


def test_the_server_holds_neither_the_owners_nor_the_collectors_url():
    names = {entry.split("=", 1)[0] for entry in _exec("cat", "/proc/1/environ").split("\0") if entry}
    assert "DATABASE_URL" in names
    assert not names & {"DATABASE_OWNER_URL", "DATABASE_COLLECTOR_URL"}


def test_the_log_of_a_fresh_install_holds_a_setup_code():
    logs = subprocess.run(["docker", "logs", _container()], capture_output=True, text=True, timeout=30, check=True)
    assert re.search(r"Setup code: [A-Z2-7]{4}(-[A-Z2-7]{4}){3}", logs.stdout + logs.stderr), logs.stdout + logs.stderr


def test_the_backend_made_its_ssh_key_with_mode_0600():
    assert _exec("stat", "-c", "%a", "/var/lib/megooitadmin/ssh/id_ed25519") == "600"
    assert _exec("stat", "-c", "%a", "/var/lib/megooitadmin/ssh") == "700"


def test_public_key_prints_an_ed25519_line():
    line = _exec("python", "-m", "app.ssh.cli", "public-key")
    assert re.fullmatch(r"ssh-ed25519 [A-Za-z0-9+/=]+ megooitadmin", line), line


def test_the_image_holds_the_setup_script():
    code = "from app.ssh import setup; print(setup.ctl_version(), setup.script_text().splitlines()[0])"
    assert _exec("python", "-c", code) == "1 #!/bin/sh"


def test_it_refuses_to_start_with_a_key_readable_by_others(tmp_path):
    key = tmp_path / "id_ed25519"
    key.write_text("not a key")
    key.chmod(0o644)
    result = _run_once(
        {
            "DATABASE_URL": _url("megooitadmin_api:megooitadminapi"),
            "DATABASE_OWNER_URL": _url("megooitadmin:megooitadmin"),
            "AUTH_SECRET_KEY": TEST_KEY,
        },
        "-v", f"{key}:/var/lib/megooitadmin/ssh/id_ed25519:ro",
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "readable by others" in output
    assert "Uvicorn running" not in output
