import uuid
from contextlib import asynccontextmanager

import pytest
from auth_helpers import add_grant, events, make_group, make_user, other_client, set_switch, sign_in
from fastapi import Depends
from httpx import ASGITransport, AsyncClient

from app.access.deps import require_grant, require_group_visible, require_owner
from app.access.permissions import Permission
from app.audit import AuditChainBusy
from app.main import create_app

CLIENT = ("127.0.0.1", 50000)


@pytest.fixture
async def probe_api(clean_auth, clock):
    """The real app with three probe routes behind the access dependencies."""
    app = create_app()

    @app.get("/api/probe/owner", dependencies=[Depends(require_owner)])
    async def probe_owner() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/probe/{group_id}", dependencies=[Depends(require_grant(Permission.CONNECT_SSH))])
    async def probe_connect(group_id: uuid.UUID) -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/probe/{group_id}/visible", dependencies=[Depends(require_group_visible())])
    async def probe_visible(group_id: uuid.UUID) -> dict[str, bool]:
        return {"ok": True}

    transport = ASGITransport(app=app, client=CLIENT)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@asynccontextmanager
async def person(api, clock, email: str, platform_role: str | None = None):
    """A signed-in browser of a new account, and the account."""
    user, secret = await make_user(email=email, name=email.split("@")[0], platform_role=platform_role)
    async with other_client(api) as client:
        await sign_in(client, clock, secret, email=email)
        yield user, client


async def test_require_owner_lets_an_owner_through_and_answers_403_to_anyone_else(probe_api, clock):
    staging = await make_group("staging")
    async with person(probe_api, clock, "owner@example.com", "owner") as (_, owner):
        response = await owner.get("/api/probe/owner")
        assert (response.status_code, response.json()) == (200, {"ok": True})

    async with person(probe_api, clock, "admin@example.com") as (admin_user, admin):
        await add_grant(admin_user.id, staging.id, "admin")
        async with person(probe_api, clock, "auditor@example.com", "auditor") as (_, auditor):
            async with person(probe_api, clock, "nobody@example.com") as (_, nobody):
                for client in (admin, auditor, nobody):
                    response = await client.get("/api/probe/owner")
                    assert (response.status_code, response.json()) == (403, {"detail": "forbidden"})


async def test_require_grant_answers_404_for_a_group_the_person_does_not_see(probe_api, clock):
    staging = await make_group("staging")
    production = await make_group("production")
    async with person(probe_api, clock, "admin@example.com") as (user, admin):
        await add_grant(user.id, staging.id, "admin")
        for group_id in (production.id, uuid.uuid4()):
            response = await admin.get(f"/api/probe/{group_id}")
            assert (response.status_code, response.json()) == (404, {"detail": "not_found"})


async def test_require_grant_answers_403_for_a_switch_that_is_off(probe_api, clock):
    staging = await make_group("staging")
    async with person(probe_api, clock, "admin@example.com") as (user, admin):
        await add_grant(user.id, staging.id, "admin", connect_ssh=False)
        response = await admin.get(f"/api/probe/{staging.id}")
        assert (response.status_code, response.json()) == (403, {"detail": "forbidden"})
        # Seeing the group does not need a switch.
        assert (await admin.get(f"/api/probe/{staging.id}/visible")).status_code == 200


async def test_a_staging_only_admin_may_connect_to_staging_and_not_to_production(probe_api, clock):
    staging = await make_group("staging")
    production = await make_group("production")
    async with person(probe_api, clock, "admin@example.com") as (user, admin):
        await add_grant(user.id, staging.id, "admin")
        assert (await admin.get(f"/api/probe/{staging.id}")).status_code == 200
        # Production is not even seen, so its ID cannot be told from one that does not exist.
        assert (await admin.get(f"/api/probe/{production.id}")).status_code == 404
        assert (await admin.get(f"/api/probe/{production.id}/visible")).status_code == 404


async def test_an_auditor_gets_403_for_connect_and_passes_require_group_visible(probe_api, clock):
    production = await make_group("production")
    async with person(probe_api, clock, "auditor@example.com", "auditor") as (_, auditor):
        response = await auditor.get(f"/api/probe/{production.id}")
        assert (response.status_code, response.json()) == (403, {"detail": "forbidden"})
        response = await auditor.get(f"/api/probe/{production.id}/visible")
        assert (response.status_code, response.json()) == (200, {"ok": True})


async def test_each_refusal_leaves_one_access_denied_event(probe_api, clock):
    staging = await make_group("staging")
    production = await make_group("production")
    async with person(probe_api, clock, "admin@example.com") as (user, admin):
        await add_grant(user.id, staging.id, "admin", connect_ssh=False)

        refusals = [
            (f"/api/probe/{production.id}", 404, production.id, "connect_ssh", "GET /api/probe/{group_id}"),
            (f"/api/probe/{staging.id}", 403, staging.id, "connect_ssh", "GET /api/probe/{group_id}"),
            (f"/api/probe/{production.id}/visible", 404, production.id, "group", "GET /api/probe/{group_id}/visible"),
            ("/api/probe/owner", 403, None, "owner", "GET /api/probe/owner"),
        ]
        for count, (path, status, group_id, required, route) in enumerate(refusals, start=1):
            assert (await admin.get(path)).status_code == status
            recorded = await events("access.denied")
            assert len(recorded) == count
            event = recorded[-1]
            assert (event.actor_type, event.actor_id, event.actor_name) == ("human", str(user.id), "admin")
            assert event.result == "failure"
            assert event.result_detail == {"required": required, "route": route}
            if group_id is None:
                assert (event.target_type, event.target_id) == (None, None)
            else:
                assert (event.target_type, event.target_id) == ("server_group", str(group_id))
            assert (str(event.source_ip), event.auth_method, event.mfa) == ("127.0.0.1", "password", True)

        assert (await admin.get(f"/api/probe/{staging.id}/visible")).status_code == 200
        assert len(await events("access.denied")) == len(refusals)


async def test_a_refusal_whose_event_cannot_be_recorded_answers_500(probe_api, clock, monkeypatch):
    production = await make_group("production")
    user, secret = await make_user(email="admin@example.com", name="admin", platform_role=None)
    transport = ASGITransport(app=probe_api._transport.app, client=CLIENT, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as admin:
        await sign_in(admin, clock, secret, email="admin@example.com")

        async def busy(event):
            raise AuditChainBusy("the audit chain stayed locked for 5s")

        monkeypatch.setattr("app.access.deps.record_alone", busy)
        assert (await admin.get(f"/api/probe/{production.id}")).status_code == 500
        assert (await admin.get("/api/probe/owner")).status_code == 500
    assert await events("access.denied") == []


async def test_a_changed_grant_applies_to_the_next_request_of_an_open_session(probe_api, clock):
    staging = await make_group("staging")
    async with person(probe_api, clock, "admin@example.com") as (user, admin):
        grant = await add_grant(user.id, staging.id, "admin")
        assert (await admin.get(f"/api/probe/{staging.id}")).status_code == 200

        await set_switch(grant.id, "connect_ssh", False)
        assert (await admin.get(f"/api/probe/{staging.id}")).status_code == 403

        await set_switch(grant.id, "connect_ssh", True)
        assert (await admin.get(f"/api/probe/{staging.id}")).status_code == 200
