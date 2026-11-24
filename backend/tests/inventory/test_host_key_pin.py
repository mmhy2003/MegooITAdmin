import socket

from auth_helpers import add_grant, events, make_group, make_server, signed_in
from sqlalchemy import select

from app.core.db import SessionLocal
from app.inventory.models import Server
from app.ssh import hostkeys, keys

OWNER = "owner@example.com"
ADMIN = "ada@example.com"
OPERATOR = "otto@example.com"
AUDITOR = "aude@example.com"


async def stored(server_id) -> Server:
    async with SessionLocal() as session:
        return await session.scalar(select(Server).where(Server.id == server_id))


def closed_port() -> int:
    """A port on 127.0.0.1 that nothing listens on."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


async def ssh_server(fake_server, group_name: str = "staging", name: str = "ssh-01", **fields) -> Server:
    group = await make_group(group_name)
    return await make_server(group.id, name, address=fake_server.host, port=fake_server.port, **fields)


async def test_fetch_stores_the_candidate_and_answers_its_fingerprint(api, clock, fake_server):
    server = await ssh_server(fake_server)
    async with signed_in(api, clock, OWNER, "owner") as (owner, client):
        response = await client.post(f"/api/servers/{server.id}/host-key/fetch")
        after = await client.get(f"/api/servers/{server.id}")

    fingerprint = hostkeys.fingerprint(fake_server.host_key())
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "reason": None, "fingerprint": fingerprint, "type": "ssh-ed25519"}
    assert after.json()["host_key_state"] == "not_pinned"
    assert after.json()["host_key_fingerprint"] is None
    row = await stored(server.id)
    assert row.host_key_offered == fake_server.host_key()
    assert row.host_key_offered_at is not None

    (fetched,) = await events("server.host_key_fetched")
    assert (fetched.actor_id, fetched.result, fetched.mfa) == (str(owner.id), "success", True)
    assert (fetched.target_type, fetched.target_id, fetched.target_name) == ("server", str(server.id), "ssh-01")
    assert fetched.context == {"server_group_id": str(server.server_group_id)}
    assert fetched.result_detail == {
        "fingerprint": fingerprint,
        "type": "ssh-ed25519",
        "address": fake_server.host,
        "port": fake_server.port,
    }


async def test_a_failed_fetch_answers_200_with_its_reason(api, clock):
    port = closed_port()
    group = await make_group("staging")
    server = await make_server(group.id, "ssh-01", address="127.0.0.1", port=port)
    async with signed_in(api, clock, OWNER, "owner") as (_, client):
        response = await client.post(f"/api/servers/{server.id}/host-key/fetch")

    assert response.status_code == 200, response.text
    assert response.json() == {"ok": False, "reason": "unreachable", "fingerprint": None, "type": None}
    assert (await stored(server.id)).host_key_offered is None
    (fetched,) = await events("server.host_key_fetched")
    assert fetched.result == "failure"
    assert fetched.result_detail == {"reason": "unreachable", "address": "127.0.0.1", "port": port}


async def test_pin_needs_the_fetched_fingerprint(api, clock, fake_server):
    server = await ssh_server(fake_server)
    url = f"/api/servers/{server.id}/host-key"
    async with signed_in(api, clock, OWNER, "owner") as (owner, client):
        unfetched = await client.put(url, json={"fingerprint": hostkeys.fingerprint(fake_server.host_key())})
        fetched = await client.post(f"{url}/fetch")
        fingerprint = fetched.json()["fingerprint"]
        wrong = await client.put(url, json={"fingerprint": "SHA256:" + "A" * 43})
        pinned = await client.put(url, json={"fingerprint": fingerprint})

    assert (unfetched.status_code, unfetched.json()) == (409, {"detail": "stale_host_key"})
    assert (wrong.status_code, wrong.json()) == (409, {"detail": "stale_host_key"})
    assert pinned.status_code == 200, pinned.text
    body = pinned.json()
    assert body["host_key_state"] == "pinned"
    assert (body["host_key_fingerprint"], body["host_key_type"]) == (fingerprint, "ssh-ed25519")
    assert body["host_key_pinned_at"] is not None
    assert body["host_key_offered"] is None
    row = await stored(server.id)
    assert row.host_key == fake_server.host_key()
    assert (row.host_key_offered, row.host_key_offered_at, row.host_key_changed_at) == (None, None, None)

    (event,) = await events("server.host_key_pinned")
    assert (event.actor_id, event.result, event.mfa) == (str(owner.id), "success", True)
    assert (event.target_type, event.target_id) == ("server", str(server.id))
    assert event.context == {"server_group_id": str(server.server_group_id)}
    assert event.change == {"host_key_fingerprint": {"before": None, "after": fingerprint}}
    assert event.result_detail == {"type": "ssh-ed25519"}
    assert await events("server.host_key_replaced") == []


async def test_a_second_pin_or_fetch_answers_409_host_key_pinned(api, clock, fake_server):
    server = await ssh_server(fake_server)
    url = f"/api/servers/{server.id}/host-key"
    async with signed_in(api, clock, OWNER, "owner") as (_, client):
        fingerprint = (await client.post(f"{url}/fetch")).json()["fingerprint"]
        assert (await client.put(url, json={"fingerprint": fingerprint})).status_code == 200
        again = await client.put(url, json={"fingerprint": fingerprint})
        fetch = await client.post(f"{url}/fetch")

    assert (again.status_code, again.json()) == (409, {"detail": "host_key_pinned"})
    assert (fetch.status_code, fetch.json()) == (409, {"detail": "host_key_pinned"})
    assert len(await events("server.host_key_pinned")) == 1
    assert len(await events("server.host_key_fetched")) == 1


async def test_an_operator_and_an_auditor_get_403_and_a_staging_only_admin_404(api, clock, fake_server):
    staging = await make_group("staging")
    server = await ssh_server(fake_server, "production")
    production_id = server.server_group_id
    url = f"/api/servers/{server.id}/host-key"
    fingerprint = {"fingerprint": hostkeys.fingerprint(fake_server.host_key())}
    async with (
        signed_in(api, clock, OPERATOR) as (otto, operator),
        signed_in(api, clock, AUDITOR, "auditor") as (_, auditor),
        signed_in(api, clock, ADMIN) as (ada, staging_admin),
    ):
        await add_grant(otto.id, production_id, "operator", connect_ssh=True)
        await add_grant(ada.id, staging.id, "admin")
        for client, expected in ((operator, (403, "forbidden")), (auditor, (403, "forbidden"))):
            fetch = await client.post(f"{url}/fetch")
            pin = await client.put(url, json=fingerprint)
            assert (fetch.status_code, fetch.json()["detail"]) == expected
            assert (pin.status_code, pin.json()["detail"]) == expected
        fetch = await staging_admin.post(f"{url}/fetch")
        pin = await staging_admin.put(url, json=fingerprint)
        assert (fetch.status_code, fetch.json()) == (404, {"detail": "not_found"})
        assert (pin.status_code, pin.json()) == (404, {"detail": "not_found"})

    row = await stored(server.id)
    assert (row.host_key, row.host_key_offered) == (None, None)
    assert await events("server.host_key_fetched") == []
    assert await events("server.host_key_pinned") == []


async def test_a_windows_server_answers_409_not_an_ssh_server(api, clock, fake_server):
    server = await ssh_server(fake_server, os="windows")
    url = f"/api/servers/{server.id}/host-key"
    async with signed_in(api, clock, OWNER, "owner") as (_, client):
        fetch = await client.post(f"{url}/fetch")
        pin = await client.put(url, json={"fingerprint": hostkeys.fingerprint(fake_server.host_key())})

    assert (fetch.status_code, fetch.json()) == (409, {"detail": "not_an_ssh_server"})
    assert (pin.status_code, pin.json()) == (409, {"detail": "not_an_ssh_server"})
    assert await events("server.host_key_fetched") == []


async def test_any_signed_in_person_reads_the_public_key(api, clock):
    signed_out = await api.get("/api/ssh/public-key")
    async with signed_in(api, clock, OPERATOR) as (_, client):
        response = await client.get("/api/ssh/public-key")

    assert signed_out.status_code == 401
    assert response.status_code == 200, response.text
    assert response.json() == {"public_key": keys.public_key()}
