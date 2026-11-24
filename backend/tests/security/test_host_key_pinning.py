"""The platform connects to a server only with its pinned host key, and only app/ssh/client.py opens SSH connections."""

import ast
from pathlib import Path

from auth_helpers import actions, events, make_group, signed_in

from app.audit import verify_chain
from app.core.db import SessionLocal
from app.ssh.hostkeys import fingerprint

APP = Path(__file__).resolve().parents[2] / "app"
CLIENT = APP / "ssh" / "client.py"
# What opens a connection to a server, or reaches one.
CONNECTING = frozenset(
    {
        "connect",
        "connect_reverse",
        "create_connection",
        "get_server_host_key",
        "get_server_auth_methods",
        "run_client",
        "scp",
        "connect_agent",
        "SSHClientConnection",
    }
)


def connecting_names(source: str) -> list[str]:
    """The asyncssh names in the source that open SSH connections: asyncssh.<name> and from asyncssh import <name>."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "asyncssh":
            if node.attr in CONNECTING:
                found.append(node.attr)
        elif isinstance(node, ast.ImportFrom) and node.module == "asyncssh":
            found.extend(alias.name for alias in node.names if alias.name in CONNECTING)
    return found


async def test_the_platform_connects_and_a_swapped_host_key_is_refused_and_audited(api, clock, fake_server):
    group = await make_group("staging")
    async with signed_in(api, clock, "owner@example.com", "owner") as (_, client):
        body = {"name": "ssh-01", "address": fake_server.host, "group_id": str(group.id), "os": "linux"}
        registered = await client.post("/api/servers", json=body | {"port": fake_server.port})
        assert registered.status_code == 200, registered.text
        url = f"/api/servers/{registered.json()['id']}"
        fetched = await client.post(f"{url}/host-key/fetch")
        assert fetched.json()["fingerprint"] == fingerprint(fake_server.host_key())
        pinned = await client.put(f"{url}/host-key", json={"fingerprint": fetched.json()["fingerprint"]})
        assert pinned.status_code == 200, pinned.text
        works = await client.post(f"{url}/connection-test")
        assert (works.status_code, works.json()["ok"]) == (200, True)

        fake_server.swap_host_key()
        sign_ins = fake_server.sign_ins()
        refused = await client.post(f"{url}/connection-test")
        assert (refused.status_code, refused.json()["reason"]) == (200, "host_key_changed")
        assert fake_server.sign_ins() == sign_ins
        assert "server.host_key_mismatch" in await actions()

        presented = fingerprint(fake_server.host_key())
        accepted = await client.put(f"{url}/host-key", json={"fingerprint": presented, "reason": "reinstalled"})
        assert accepted.status_code == 200, accepted.text

    (replaced,) = await events("server.host_key_replaced")
    assert replaced.reason == "reinstalled"
    assert replaced.change["host_key_fingerprint"]["after"] == presented
    async with SessionLocal() as session:
        assert (await verify_chain(session)).ok


def test_only_app_ssh_client_opens_ssh_connections():
    hits = {path: names for path in APP.rglob("*.py") if (names := connecting_names(path.read_text()))}

    assert set(hits) == {CLIENT}, sorted(str(path.relative_to(APP)) for path in hits)


def test_the_check_finds_a_connect_in_a_sample():
    assert connecting_names("import asyncssh\nasync def f(): await asyncssh.connect('x')") == ["connect"]
    assert connecting_names("from asyncssh import connect") == ["connect"]
    assert connecting_names("import asyncssh\nkey = asyncssh.import_public_key('x')") == []
