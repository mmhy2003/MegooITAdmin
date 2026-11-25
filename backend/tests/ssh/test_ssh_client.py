import asyncio
import socket
import time

import asyncssh
import pytest

from app import collector
from app.ssh.client import (
    CTL,
    HostKeyChanged,
    KeyRefused,
    ScriptTimeout,
    Setup,
    Unreachable,
    account_of,
    connect,
    fetch_host_key,
    run_script,
    script_output,
    setup_of,
    sudo_commands,
)
from app.ssh.hostkeys import openssh_line
from app.ssh.keys import KeyFileError


SUDO_LIST = """Matching Defaults entries for megoo on fake:
    env_reset, mail_badpass, secure_path=/usr/local/sbin\\:/usr/local/bin

User megoo may run the following commands on fake:
    (root) NOPASSWD: /usr/local/sbin/megoo-ctl
"""


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

    for user in ("megoo-nologs", "megoo-nosudo", "megoo-wide"):
        async with connect(fake_server.host, fake_server.port, user, fake_server.host_key()) as conn:
            uid, _ = await account_of(conn)
        assert uid != 0, user


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


async def test_a_key_limited_to_another_address_is_refused(fake_server):
    fake_server.authorize("192.0.2.1")
    try:
        with pytest.raises(KeyRefused):
            async with connect(fake_server.host, fake_server.port, "megoo", fake_server.host_key()):
                pass
    finally:
        fake_server.authorize()

    async with connect(fake_server.host, fake_server.port, "megoo", fake_server.host_key()) as conn:
        uid, _ = await account_of(conn)
    assert uid != 0


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


def test_sudo_commands_of_the_megoo_account():
    assert sudo_commands(SUDO_LIST) == ["/usr/local/sbin/megoo-ctl"]


def test_sudo_commands_of_a_wide_account():
    assert sudo_commands(SUDO_LIST + "    (ALL) NOPASSWD: ALL\n") == [CTL, "ALL"]


def test_sudo_commands_of_a_root_like_account():
    text = "User megoo may run the following commands on fake:\n    (ALL : ALL) ALL\n"
    assert sudo_commands(text) == ["ALL"]


def test_sudo_commands_of_another_language_is_none():
    text = "Benutzer megoo darf die folgenden Befehle ausführen:\n    (root) NOPASSWD: /usr/local/sbin/megoo-ctl\n"
    assert sudo_commands(text) is None


def test_sudo_commands_of_a_header_alone_is_empty():
    assert sudo_commands("User megoo may run the following commands on fake:\n") == []


@pytest.mark.parametrize(
    ("user", "expected"),
    [
        ("megoo", Setup(version=1, limited=True)),
        ("megoo-nologs", Setup(version=1, limited=True)),
        ("megoo-nosudo", Setup(version=None, limited=None)),
        ("megoo-wide", Setup(version=1, limited=False)),
    ],
)
async def test_setup_of_each_prepared_account(fake_server, user, expected):
    async with connect(fake_server.host, fake_server.port, user, fake_server.host_key()) as conn:
        assert await setup_of(conn) == expected


async def test_run_script_returns_the_output_and_the_exit_status(fake_server):
    async with connect(fake_server.host, fake_server.port, "megoo", fake_server.host_key()) as conn:
        result = await run_script(conn, b'echo "$1"; exit 3', ("db.example.com",), timeout=5, max_output=1000)

    assert result.exit_status == 3
    assert result.output == b"db.example.com\n"
    assert result.truncated is False


async def test_run_script_refuses_an_argument_outside_the_pattern(fake_server):
    async with connect(fake_server.host, fake_server.port, "megoo", fake_server.host_key()) as conn:
        for bad in ("a;b", "", "a" * 254):
            with pytest.raises(ValueError) as raised:
                await run_script(conn, b"echo hi", ("ok", bad), timeout=5, max_output=100)
            assert "argument 1" in str(raised.value)
            assert bad == "" or bad not in str(raised.value)


async def test_run_script_refuses_before_any_channel_opens():
    class NoConnection:
        async def create_process(self, *args, **kwargs):
            raise AssertionError("a channel was opened")

    with pytest.raises(ValueError):
        await run_script(NoConnection(), b"echo hi", ("a;b",), timeout=5, max_output=100)


async def test_run_script_caps_the_output(fake_server):
    async with connect(fake_server.host, fake_server.port, "megoo", fake_server.host_key()) as conn:
        result = await run_script(conn, b"head -c 3000000 /dev/zero", timeout=10, max_output=1_000_000)

    assert result.truncated is True
    assert len(result.output) == 1_000_000


async def test_run_script_times_out(fake_server):
    async with connect(fake_server.host, fake_server.port, "megoo", fake_server.host_key()) as conn:
        started = time.monotonic()
        with pytest.raises(ScriptTimeout) as raised:
            await run_script(conn, b"exec sleep 5", timeout=1, max_output=100)

    assert time.monotonic() - started < 3
    assert raised.value.reason == "timeout"


async def test_run_script_beside_a_running_loop(fake_server):
    async with connect(fake_server.host, fake_server.port, "megoo", fake_server.host_key()) as conn:
        async with asyncio.timeout(15), script_output(conn, collector.script(), 1) as chunks:
            assert await anext(chunks)
            result = await run_script(conn, b"echo hi", timeout=5, max_output=100)

    assert result.output == b"hi\n"
    assert result.exit_status == 0
