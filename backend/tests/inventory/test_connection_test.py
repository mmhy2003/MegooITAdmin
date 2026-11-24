import pytest
from auth_helpers import add_grant, events, make_group, make_server, pin_host_key, signed_in
from sqlalchemy import select

from app.audit import Actor
from app.core.db import SessionLocal
from app.inventory.models import Server
from app.ssh.client import HostKeyChanged
from app.ssh.hostkeys import fingerprint

OWNER = "owner@example.com"
ADMIN = "ada@example.com"
OPERATOR = "otto@example.com"
AUDITOR = "aude@example.com"
CHECKS = ("host_key", "platform_key", "not_root", "not_in_docker_group")


def checks(*statuses: str) -> list[dict]:
    return [{"name": name, "status": status} for name, status in zip(CHECKS, statuses, strict=True)]


async def ssh_server(fake_server, group_name: str = "staging", name: str = "ssh-01", **fields) -> Server:
    group = await make_group(group_name)
    return await make_server(group.id, name, address=fake_server.host, port=fake_server.port, **fields)


async def test_the_test_passes_as_megoo(api, clock, fake_server):
    server = await ssh_server(fake_server)
    async with signed_in(api, clock, OWNER, "owner") as (owner, client):
        await pin_host_key(client, server.id)
        response = await client.post(f"/api/servers/{server.id}/connection-test")

    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "reason": None, "checks": checks("passed", "passed", "passed", "passed")}
    (tested,) = await events("server.connection_tested")
    assert (tested.actor_id, tested.result, tested.mfa) == (str(owner.id), "success", True)
    assert (tested.target_type, tested.target_id, tested.target_name) == ("server", str(server.id), "ssh-01")
    assert tested.context == {"server_group_id": str(server.server_group_id)}
    assert tested.result_detail == {
        "username": "megoo",
        "address": fake_server.host,
        "port": fake_server.port,
        "reason": None,
        "checks": dict.fromkeys(CHECKS, "passed"),
    }
    assert await events("server.host_key_mismatch") == []


@pytest.mark.parametrize(
    ("username", "reason", "statuses"),
    [
        ("megoo-docker", "account_in_docker_group", ("passed", "passed", "passed", "failed")),
        ("megoo-root", "account_is_root", ("passed", "passed", "failed", "passed")),
    ],
)
async def test_the_two_wrong_accounts_fail(api, clock, fake_server, username, reason, statuses):
    server = await ssh_server(fake_server)
    async with signed_in(api, clock, OWNER, "owner") as (_, client):
        await pin_host_key(client, server.id)
        patched = await client.patch(f"/api/servers/{server.id}", json={"connection_settings": {"username": username}})
        assert patched.status_code == 200, patched.text
        response = await client.post(f"/api/servers/{server.id}/connection-test")

    assert response.status_code == 200, response.text
    assert response.json() == {"ok": False, "reason": reason, "checks": checks(*statuses)}
    (tested,) = await events("server.connection_tested")
    assert tested.result == "failure"
    assert tested.result_detail["username"] == username
    assert tested.result_detail["reason"] == reason
    assert tested.result_detail["checks"] == dict(zip(CHECKS, statuses, strict=True))


async def test_409_before_a_key_is_pinned(api, clock, fake_server):
    server = await ssh_server(fake_server)
    async with signed_in(api, clock, OWNER, "owner") as (_, client):
        response = await client.post(f"/api/servers/{server.id}/connection-test")

    assert (response.status_code, response.json()) == (409, {"detail": "host_key_not_pinned"})
    assert await events("server.connection_tested") == []


async def test_a_swapped_key_is_refused_flagged_and_blocks_the_next_test(api, clock, fake_server):
    server = await ssh_server(fake_server)
    url = f"/api/servers/{server.id}/connection-test"
    async with signed_in(api, clock, OWNER, "owner") as (owner, client):
        pinned = await pin_host_key(client, server.id)
        fake_server.swap_host_key()
        sign_ins = fake_server.sign_ins()
        response = await client.post(url)
        assert fake_server.sign_ins() == sign_ins
        after = (await client.get(f"/api/servers/{server.id}")).json()
        blocked = await client.post(url)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "ok": False,
        "reason": "host_key_changed",
        "checks": checks("failed", "not_run", "not_run", "not_run"),
    }
    presented = fingerprint(fake_server.host_key())
    assert after["host_key_state"] == "changed"
    assert after["host_key_changed_at"] is not None
    assert after["host_key_fingerprint"] == pinned["host_key_fingerprint"]
    assert after["host_key_offered"]["fingerprint"] == presented
    assert (blocked.status_code, blocked.json()) == (409, {"detail": "host_key_changed"})

    (mismatch,) = await events("server.host_key_mismatch")
    assert (mismatch.actor_id, mismatch.result) == (str(owner.id), "failure")
    assert (mismatch.target_type, mismatch.target_id) == ("server", str(server.id))
    assert mismatch.context == {"server_group_id": str(server.server_group_id)}
    assert mismatch.result_detail == {
        "pinned_fingerprint": pinned["host_key_fingerprint"],
        "presented_fingerprint": presented,
        "address": fake_server.host,
        "port": fake_server.port,
    }
    (tested,) = await events("server.connection_tested")
    assert tested.result == "failure"
    assert tested.result_detail["reason"] == "host_key_changed"


async def test_the_mismatch_survives_the_callers_rollback(api, clock, fake_server):
    from app.inventory.connection import open_connection

    server = await ssh_server(fake_server)
    async with signed_in(api, clock, OWNER, "owner") as (_, client):
        await pin_host_key(client, server.id)

    async with SessionLocal() as session:
        loaded = await session.scalar(select(Server).where(Server.id == server.id))
        fake_server.swap_host_key()
        with pytest.raises(HostKeyChanged):
            async with open_connection(loaded, actor=Actor.system("test"), source=None):
                pass
        await session.rollback()

    async with SessionLocal() as session:
        row = await session.scalar(select(Server).where(Server.id == server.id))
    assert row.host_key_changed_at is not None
    assert row.host_key_offered == fake_server.host_key()
    (mismatch,) = await events("server.host_key_mismatch")
    assert (mismatch.actor_type, mismatch.actor_name) == ("system", "test")


async def test_an_operator_with_connect_ssh_tests_and_the_others_cannot(api, clock, fake_server):
    staging = await make_group("staging")
    server = await ssh_server(fake_server, "production")
    production_id = server.server_group_id
    url = f"/api/servers/{server.id}/connection-test"
    async with (
        signed_in(api, clock, OWNER, "owner") as (_, owner),
        signed_in(api, clock, OPERATOR) as (otto, operator),
        signed_in(api, clock, "olga@example.com") as (olga, no_ssh),
        signed_in(api, clock, AUDITOR, "auditor") as (_, auditor),
        signed_in(api, clock, ADMIN) as (ada, staging_admin),
    ):
        await pin_host_key(owner, server.id)
        await add_grant(otto.id, production_id, "operator", connect_ssh=True)
        await add_grant(olga.id, production_id, "operator", connect_ssh=False)
        await add_grant(ada.id, staging.id, "admin")
        tested = await operator.post(url)
        forbidden = await no_ssh.post(url)
        audited = await auditor.post(url)
        hidden = await staging_admin.post(url)

    assert (tested.status_code, tested.json()["ok"]) == (200, True)
    assert (forbidden.status_code, forbidden.json()) == (403, {"detail": "forbidden"})
    assert (audited.status_code, audited.json()) == (403, {"detail": "forbidden"})
    assert (hidden.status_code, hidden.json()) == (404, {"detail": "not_found"})
    (event,) = await events("server.connection_tested")
    assert event.actor_id == str(otto.id)


async def test_a_windows_server_answers_409_not_an_ssh_server(api, clock, fake_server):
    server = await ssh_server(fake_server, os="windows")
    async with signed_in(api, clock, OWNER, "owner") as (_, client):
        response = await client.post(f"/api/servers/{server.id}/connection-test")

    assert (response.status_code, response.json()) == (409, {"detail": "not_an_ssh_server"})
    assert await events("server.connection_tested") == []
