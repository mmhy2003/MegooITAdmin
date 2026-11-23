import pytest
from fastapi import FastAPI, HTTPException, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from starlette.requests import Request as StarletteRequest

from app.audit import Actor, AuditChainHead, AuditEvent, Event, audited, record, source_of
from app.core.db import DbSession, SessionLocal

pytestmark = pytest.mark.usefixtures("empty_audit_log")

PROBE = "audit_http_probe"


@pytest.fixture(autouse=True)
async def probe_table():
    async with SessionLocal() as session:
        await session.execute(text(f"CREATE TABLE {PROBE} (id int)"))
        await session.commit()
    yield
    async with SessionLocal() as session:
        await session.execute(text(f"DROP TABLE IF EXISTS {PROBE}"))
        await session.commit()


def probe_event(action: str) -> Event:
    return Event(action=action, actor=Actor.human(7, "Alice"))


async def insert_probe(session: DbSession) -> None:
    await session.execute(text(f"INSERT INTO {PROBE} (id) VALUES (1)"))


app = FastAPI()


@app.post("/ok", dependencies=[audited("probe.created")])
async def ok(session: DbSession) -> dict[str, bool]:
    await insert_probe(session)
    await record(session, probe_event("probe.created"))
    return {"ok": True}


@app.post("/forgot", dependencies=[audited("probe.created")])
async def forgot(session: DbSession) -> dict[str, bool]:
    await insert_probe(session)
    return {"ok": True}


@app.post("/refused", dependencies=[audited("probe.created")])
async def refused(session: DbSession) -> dict[str, bool]:
    await insert_probe(session)
    await record(session, probe_event("probe.created"))
    raise HTTPException(409)


@app.post("/other", dependencies=[audited("probe.created")])
async def other(session: DbSession) -> dict[str, bool]:
    await record(session, probe_event("probe.deleted"))
    return {"ok": True}


@app.get("/source")
async def source(request: Request) -> dict:
    return source_of(request, auth_method="password", mfa=True).model_dump()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def probes() -> int:
    async with SessionLocal() as session:
        return (await session.execute(text(f"SELECT count(*) FROM {PROBE}"))).scalar_one()


async def events() -> int:
    async with SessionLocal() as session:
        return (await session.execute(select(func.count()).select_from(AuditEvent))).scalar_one()


async def head_seq() -> int:
    async with SessionLocal() as session:
        return (await session.execute(select(AuditChainHead.seq))).scalar_one()


async def test_a_route_that_records_its_declared_action_commits_both(client):
    response = await client.post("/ok")

    assert response.status_code == 200
    assert await probes() == 1
    assert await events() == 1


async def test_a_route_that_records_nothing_answers_500_and_commits_nothing(client):
    response = await client.post("/forgot")

    assert response.status_code == 500
    assert await probes() == 0
    assert await events() == 0


async def test_a_route_that_records_another_action_answers_500(client):
    response = await client.post("/other")

    assert response.status_code == 500
    assert await events() == 0
    assert await head_seq() == 0


async def test_a_route_that_raises_rolls_back_and_keeps_its_status(client):
    response = await client.post("/refused")

    assert response.status_code == 409
    assert await probes() == 0
    assert await events() == 0
    assert await head_seq() == 0


@pytest.mark.parametrize("actions", [(), ("Probe Created",), ("probe.created", "probe")])
def test_audited_refuses_a_bad_or_missing_action(actions):
    with pytest.raises(ValueError):
        audited(*actions)


async def test_source_of_takes_the_client_address_and_the_user_agent():
    transport = ASGITransport(app=app, client=("127.0.0.1", 50000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/source", headers={"User-Agent": "probe/1.0"})

    assert response.json() == {"ip": "127.0.0.1", "user_agent": "probe/1.0", "auth_method": "password", "mfa": True}


def test_source_of_drops_a_client_host_that_is_not_an_ip():
    request = StarletteRequest(
        {"type": "http", "method": "GET", "path": "/", "headers": [], "client": ("testclient", 50000)}
    )

    source = source_of(request)

    assert source.ip is None
    assert source.user_agent is None
