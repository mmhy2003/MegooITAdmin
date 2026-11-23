import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        yield client


async def test_api_health_answers_ok(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("path", ["/health", "/docs", "/openapi.json", "/redoc"])
async def test_nothing_is_served_outside_api(client, path):
    assert (await client.get(path)).status_code == 404


@pytest.mark.parametrize("path", ["/api/docs", "/api/openapi.json"])
async def test_the_docs_are_not_served_by_default(client, path):
    assert (await client.get(path)).status_code == 404


async def test_the_docs_are_served_with_api_docs():
    app = create_app(Settings(database_url=os.environ["DATABASE_URL"], api_docs=True))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/docs")).status_code == 200
        response = await client.get("/api/openapi.json")
        assert response.status_code == 200
        assert "/api/health" in response.json()["paths"]
