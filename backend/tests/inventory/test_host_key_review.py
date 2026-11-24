import pytest
from auth_helpers import add_grant, events, make_group, make_server, pin_host_key, signed_in
from conftest import owner_session
from sqlalchemy import func, update

from app.inventory.models import Server
from app.ssh.hostkeys import fingerprint

OWNER = "owner@example.com"
ADMIN = "ada@example.com"
OPERATOR = "otto@example.com"


async def ssh_server(fake_server, group_name: str = "staging", **fields) -> Server:
    group = await make_group(group_name)
    return await make_server(group.id, "ssh-01", address=fake_server.host, port=fake_server.port, **fields)


async def flag(client, fake_server, server_id) -> dict:
    """Pins the server's key, swaps it and runs one test, which flags the server. Returns the pinned server."""
    pinned = await pin_host_key(client, server_id)
    fake_server.swap_host_key()
    tested = await client.post(f"/api/servers/{server_id}/connection-test")
    assert tested.json()["reason"] == "host_key_changed", tested.text
    return pinned


@pytest.mark.parametrize("reason", [{}, {"reason": "  "}])
async def test_accepting_needs_a_reason(api, clock, fake_server, reason):
    server = await ssh_server(fake_server)
    async with signed_in(api, clock, OWNER, "owner") as (_, client):
        await flag(client, fake_server, server.id)
        body = {"fingerprint": fingerprint(fake_server.host_key())} | reason
        response = await client.put(f"/api/servers/{server.id}/host-key", json=body)
        after = (await client.get(f"/api/servers/{server.id}")).json()

    assert (response.status_code, response.json()) == (422, {"detail": "reason_required"})
    assert after["host_key_state"] == "changed"
    assert await events("server.host_key_replaced") == []


async def test_accepting_with_a_reason_unblocks_and_the_test_passes(api, clock, fake_server):
    server = await ssh_server(fake_server)
    async with signed_in(api, clock, OWNER, "owner") as (owner, client):
        pinned = await flag(client, fake_server, server.id)
        presented = fingerprint(fake_server.host_key())
        response = await client.put(
            f"/api/servers/{server.id}/host-key", json={"fingerprint": presented, "reason": "reinstalled"}
        )
        tested = await client.post(f"/api/servers/{server.id}/connection-test")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["host_key_state"] == "pinned"
    assert body["host_key_fingerprint"] == presented
    assert (body["host_key_changed_at"], body["host_key_offered"]) == (None, None)
    (replaced,) = await events("server.host_key_replaced")
    assert (replaced.actor_id, replaced.result) == (str(owner.id), "success")
    assert (replaced.target_type, replaced.target_id) == ("server", str(server.id))
    assert replaced.change == {"host_key_fingerprint": {"before": pinned["host_key_fingerprint"], "after": presented}}
    assert replaced.reason == "reinstalled"
    assert replaced.result_detail == {"type": "ssh-ed25519"}
    assert len(await events("server.host_key_pinned")) == 1
    assert (tested.status_code, tested.json()["ok"]) == (200, True)


async def test_accepting_another_fingerprint_answers_409_stale_host_key(api, clock, fake_server):
    server = await ssh_server(fake_server)
    async with signed_in(api, clock, OWNER, "owner") as (_, client):
        pinned = await flag(client, fake_server, server.id)
        response = await client.put(
            f"/api/servers/{server.id}/host-key",
            json={"fingerprint": pinned["host_key_fingerprint"], "reason": "reinstalled"},
        )
        after = (await client.get(f"/api/servers/{server.id}")).json()

    assert (response.status_code, response.json()) == (409, {"detail": "stale_host_key"})
    assert after["host_key_state"] == "changed"
    assert await events("server.host_key_replaced") == []


async def test_keep_unblocks_without_changing_the_key(api, clock, fake_server):
    server = await ssh_server(fake_server)
    async with signed_in(api, clock, OWNER, "owner") as (owner, client):
        pinned = await flag(client, fake_server, server.id)
        response = await client.post(f"/api/servers/{server.id}/host-key/keep")
        tested = await client.post(f"/api/servers/{server.id}/connection-test")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["host_key_state"] == "pinned"
    assert body["host_key_fingerprint"] == pinned["host_key_fingerprint"]
    assert (body["host_key_changed_at"], body["host_key_offered"]) == (None, None)
    (kept,) = await events("server.host_key_kept")
    assert (kept.actor_id, kept.result) == (str(owner.id), "success")
    assert (kept.target_type, kept.target_id) == ("server", str(server.id))
    assert kept.context == {"server_group_id": str(server.server_group_id)}
    assert kept.result_detail == {
        "pinned_fingerprint": pinned["host_key_fingerprint"],
        "presented_fingerprint": fingerprint(fake_server.host_key()),
    }
    # The server still presents the other key: the next test is refused and flags it again.
    assert (tested.status_code, tested.json()["reason"]) == (200, "host_key_changed")
    assert len(await events("server.host_key_mismatch")) == 2


async def test_keep_on_an_unflagged_server_answers_409_host_key_not_changed(api, clock, fake_server):
    server = await ssh_server(fake_server)
    async with signed_in(api, clock, OWNER, "owner") as (_, client):
        not_pinned = await client.post(f"/api/servers/{server.id}/host-key/keep")
        await pin_host_key(client, server.id)
        pinned = await client.post(f"/api/servers/{server.id}/host-key/keep")

    assert (not_pinned.status_code, not_pinned.json()) == (409, {"detail": "host_key_not_changed"})
    assert (pinned.status_code, pinned.json()) == (409, {"detail": "host_key_not_changed"})
    assert await events("server.host_key_kept") == []


async def test_an_unread_presented_key_can_only_be_kept(api, clock, fake_server):
    server = await ssh_server(fake_server)
    async with signed_in(api, clock, OWNER, "owner") as (_, client):
        pinned = await pin_host_key(client, server.id)
        async with owner_session() as session:
            await session.execute(update(Server).where(Server.id == server.id).values(host_key_changed_at=func.now()))
            await session.commit()
        flagged = (await client.get(f"/api/servers/{server.id}")).json()
        accept = await client.put(
            f"/api/servers/{server.id}/host-key",
            json={"fingerprint": pinned["host_key_fingerprint"], "reason": "reinstalled"},
        )
        keep = await client.post(f"/api/servers/{server.id}/host-key/keep")

    assert (flagged["host_key_state"], flagged["host_key_offered"]) == ("changed", None)
    assert (accept.status_code, accept.json()) == (409, {"detail": "stale_host_key"})
    assert keep.status_code == 200, keep.text
    assert keep.json()["host_key_state"] == "pinned"
    (kept,) = await events("server.host_key_kept")
    assert kept.result_detail == {"pinned_fingerprint": pinned["host_key_fingerprint"], "presented_fingerprint": None}


async def test_an_operator_gets_403_and_a_staging_only_admin_404(api, clock, fake_server):
    staging = await make_group("staging")
    server = await ssh_server(fake_server, "production")
    url = f"/api/servers/{server.id}/host-key"
    async with (
        signed_in(api, clock, OWNER, "owner") as (_, owner),
        signed_in(api, clock, OPERATOR) as (otto, operator),
        signed_in(api, clock, ADMIN) as (ada, staging_admin),
    ):
        await flag(owner, fake_server, server.id)
        await add_grant(otto.id, server.server_group_id, "operator", connect_ssh=True)
        await add_grant(ada.id, staging.id, "admin")
        body = {"fingerprint": fingerprint(fake_server.host_key()), "reason": "reinstalled"}
        refusals = ((operator, (403, {"detail": "forbidden"})), (staging_admin, (404, {"detail": "not_found"})))
        for client, expected in refusals:
            accept = await client.put(url, json=body)
            keep = await client.post(f"{url}/keep")
            assert (accept.status_code, accept.json()) == expected
            assert (keep.status_code, keep.json()) == expected
        after = (await owner.get(f"/api/servers/{server.id}")).json()

    assert after["host_key_state"] == "changed"
    assert await events("server.host_key_replaced") == []
    assert await events("server.host_key_kept") == []


async def test_a_windows_server_answers_409_not_an_ssh_server(api, clock, fake_server):
    server = await ssh_server(fake_server, os="windows")
    async with signed_in(api, clock, OWNER, "owner") as (_, client):
        response = await client.post(f"/api/servers/{server.id}/host-key/keep")

    assert (response.status_code, response.json()) == (409, {"detail": "not_an_ssh_server"})
    assert await events("server.host_key_kept") == []
