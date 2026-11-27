import asyncio
import time

import pytest

from app.ssh import client
from app.ssh.client import CTL, Exit, follow


async def until(check, within: float = 5) -> None:
    """Waits until check() is true, failing after `within` seconds."""
    deadline = time.monotonic() + within
    while not check():
        if time.monotonic() > deadline:
            pytest.fail(f"not true within {within} s")
        await asyncio.sleep(0.1)


async def read_until(followed, wanted: bytes, within: float = 5) -> bytes:
    """Reads output chunks until they hold `wanted`, and returns what was read."""
    read = b""
    chunks = aiter(followed)
    async with asyncio.timeout(within):
        while wanted not in read:
            stream, chunk = await anext(chunks)
            if stream == "out":
                read += chunk
    return read


async def run(followed) -> tuple[bytes, bytes]:
    """Reads every chunk until both streams end: the output and the error output."""
    out = err = b""
    async with asyncio.timeout(10):
        async for stream, chunk in followed:
            if stream == "out":
                out += chunk
            else:
                err += chunk
    return out, err


def connect(fake_server):
    return client.connect(fake_server.host, fake_server.port, "megoo", fake_server.host_key())


async def test_follow_prints_the_fixture_then_what_is_fed(fake_server):
    with fake_server.fixture("journalctl", "a\n"):
        async with connect(fake_server) as conn, follow(conn, ["journalctl", "-f"]) as followed:
            assert await read_until(followed, b"a\n") == b"a\n"
            fake_server.feed("journalctl", "b\n")
            assert await read_until(followed, b"b\n") == b"b\n"


async def test_leaving_ends_the_command_on_the_server(fake_server):
    fake_server.append("/var/log/megoo-tests/quiet.log", "")
    async with connect(fake_server) as conn:
        async with follow(conn, ["tail", "-F", "/var/log/megoo-tests/quiet.log"]):
            await until(lambda: fake_server.followers() > 0)
        await until(lambda: fake_server.followers() == 0)


async def test_the_exit_status_and_the_error_output(fake_server):
    async with connect(fake_server) as conn:
        async with follow(conn, ["sh", "-c", "echo out; echo err >&2; exit 3"]) as followed:
            assert await run(followed) == (b"out\n", b"err\n")
            assert followed.exit == Exit(3, b"err\n")


async def test_a_missing_command_exits_127(fake_server):
    async with connect(fake_server) as conn, follow(conn, ["megoo-no-such-command"]) as followed:
        await run(followed)
        assert followed.exit is not None
        assert followed.exit.status == 127


async def test_arguments_reach_the_command_unchanged(fake_server):
    text = "a b'c\"$(x)"
    async with connect(fake_server) as conn, follow(conn, ["printf", "%s\\n", text]) as followed:
        assert await run(followed) == (text.encode() + b"\n", b"")
        assert followed.exit == Exit(0, b"")


@pytest.mark.parametrize("argv", [[], ["echo"] * 33, ["echo", "a\nb"], ["echo", "a" * 4097]])
async def test_bad_arguments_are_refused(fake_server, argv):
    async with connect(fake_server) as conn:
        with pytest.raises(ValueError):
            async with follow(conn, argv):
                pass


async def test_a_container_follow_stops_through_sudo(fake_server):
    argv = ["sudo", "-n", CTL, "docker", "logs", "web-1", "--follow", "--tail", "200"]
    with fake_server.fixture("docker_logs", "2026-11-27T10:00:00Z hi\n"):
        async with connect(fake_server) as conn:
            async with follow(conn, argv) as followed:
                assert await read_until(followed, b"hi\n") == b"2026-11-27T10:00:00Z hi\n"
                assert fake_server.followers() > 0
            await until(lambda: fake_server.followers() == 0)
