"""Start-up tests of the built image. They start nothing themselves: the image service set has built the image and
started it with its own database. They do not import the app or run Alembic."""

import asyncio
import os
import subprocess
from pathlib import Path

import asyncpg
import httpx
import pytest

pytestmark = pytest.mark.docker

TESTS = Path(__file__).resolve().parent
VERSIONS = TESTS.parent / "migrations" / "versions"
FAILING_REVISION = TESTS / "fixtures" / "9999_fails.py"


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"{name} is not set. Run: megoocolab-runner services run image -- uv run pytest -m docker")
    return value


def _head() -> str:
    return max(path.name[:4] for path in VERSIONS.glob("[0-9][0-9][0-9][0-9]_*.py"))


async def _fetch(sql: str) -> list[asyncpg.Record]:
    url = _env("IMAGE_DATABASE_URL").replace("postgresql+asyncpg://", "postgresql://", 1)
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


def test_it_refuses_to_serve_when_a_migration_fails():
    result = subprocess.run(
        [
            "docker", "run", "--rm",
            "--network", _env("BACKEND_NETWORK"),
            "-e", f"DATABASE_URL=postgresql+asyncpg://megooitadmin:megooitadmin@db:5432/{_env('DB_NAME')}",
            "-e", f"DATABASE_OWNER_URL=postgresql+asyncpg://megooitadmin:megooitadmin@db:5432/{_env('DB_NAME')}",
            "-v", f"{FAILING_REVISION}:/app/migrations/versions/9999_fails.py:ro",
            _env("BACKEND_IMAGE"),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "Applying database migrations..." in output
    assert "9999_fails: this migration fails on purpose" in output
    assert "Uvicorn running" not in output
    versions = [row["version_num"] for row in asyncio.run(_fetch("SELECT version_num FROM alembic_version"))]
    assert versions == [_head()]
