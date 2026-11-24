import socket

import asyncssh
import pytest

from app.ssh.client import HostKeyChanged, KeyRefused, Unreachable, account_of, connect, fetch_host_key
from app.ssh.hostkeys import openssh_line
from app.ssh.keys import KeyFileError


def closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def test_fetch_returns_the_servers_ed25519_key(fake_server):
    assert await fetch_host_key(fake_server.host, fake_server.port) == fake_server.host_key()


async def test_connect_with_the_pinned_key_signs_in_as_megoo(fake_server):
    before = fake_server.sign_ins()

    async with connect(fake_server.host, fake_server.port, "megoo", fake_server.host_key()) as conn:
        uid, groups = await account_of(conn)

    assert uid != 0
    assert "docker" not in groups
    assert fake_server.sign_ins() == before + 1


async def test_the_two_wrong_accounts(fake_server):
    async with connect(fake_server.host, fake_server.port, "megoo-root", fake_server.host_key()) as conn:
        uid, _ = await account_of(conn)
    assert uid == 0

    async with connect(fake_server.host, fake_server.port, "megoo-docker", fake_server.host_key()) as conn:
        _, groups = await account_of(conn)
    assert "docker" in groups


async def test_another_pinned_key_raises_host_key_changed_before_sign_in(fake_server):
    pinned = openssh_line(asyncssh.generate_private_key("ssh-ed25519"))
    before = fake_server.sign_ins()

    with pytest.raises(HostKeyChanged) as raised:
        async with connect(fake_server.host, fake_server.port, "megoo", pinned):
            pass

    assert raised.value.presented == fake_server.host_key()
    assert raised.value.reason == "host_key_changed"
    assert fake_server.sign_ins() == before


async def test_a_key_the_server_does_not_know_raises_key_refused(fake_server, monkeypatch):
    monkeypatch.setattr("app.ssh.client.load_key", lambda: asyncssh.generate_private_key("ssh-ed25519"))

    with pytest.raises(KeyRefused):
        async with connect(fake_server.host, fake_server.port, "megoo", fake_server.host_key()):
            pass


async def test_a_closed_port_raises_unreachable(fake_server):
    port = closed_port()

    with pytest.raises(Unreachable):
        await fetch_host_key("127.0.0.1", port)
    with pytest.raises(Unreachable):
        async with connect("127.0.0.1", port, "megoo", fake_server.host_key()):
            pass


async def test_a_missing_key_file_is_not_reported_as_unreachable(fake_server, monkeypatch):
    def missing():
        raise KeyFileError("x")

    monkeypatch.setattr("app.ssh.client.load_key", missing)

    with pytest.raises(KeyFileError):
        async with connect("127.0.0.1", closed_port(), "megoo", fake_server.host_key()):
            pass
