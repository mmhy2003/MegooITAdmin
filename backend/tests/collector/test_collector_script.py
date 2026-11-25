"""The server-side loop (app/collector/script.sh) on the fake server: one valid line per interval, read-only, without
sudo, and gone once its channel closes."""

import asyncio
import time

import pytest

from app.collector import compute, script
from app.collector.parse import Lines, Raw, parse
from app.ssh.client import Connection, connect, script_output


async def samples(conn: Connection, interval: int, count: int, *, during=None) -> list[Raw]:
    """The first `count` samples of a loop at `interval`. `during(samples)` runs after each one."""
    found: list[Raw] = []
    lines = Lines()
    async with asyncio.timeout(15), script_output(conn, script(), interval) as chunks:
        async for chunk in chunks:
            for line in lines.feed(chunk):
                found.append(parse(line))
                if during is not None:
                    during(found)
                if len(found) == count:
                    return found
    raise AssertionError(f"the output ended after {len(found)} lines")


async def test_the_loop_prints_a_valid_line_every_interval(fake_server):
    async with connect(fake_server.host, fake_server.port, "megoo", fake_server.host_key()) as conn:
        first, second, third = await samples(conn, 1, 3)

    for earlier, later in ((first, second), (second, third)):
        assert 0.9 <= later.uptime - earlier.uptime <= 3.0
    found = {(reading.metric, reading.instance) for reading in compute.readings(first, second)}
    assert {("cpu.used_percent", ""), ("mem.total_bytes", ""), ("load.1m", ""), ("disk.used_percent", "/")} <= found


async def test_it_runs_without_sudo(fake_server):
    assert b"sudo" not in script()
    users: list[str] = []

    def look(found: list[Raw]) -> None:
        if len(found) == 1:
            users.extend(fake_server.exec("ps", "-o", "user=", "-C", "sh").stdout.split())

    async with connect(fake_server.host, fake_server.port, "megoo-nosudo", fake_server.host_key()) as conn:
        assert len(await samples(conn, 1, 2, during=look)) == 2

    assert "megoo-nosudo" in users


async def test_the_loop_ends_after_its_channel_closes(fake_server):
    async with connect(fake_server.host, fake_server.port, "megoo", fake_server.host_key()) as conn:
        await samples(conn, 1, 1)

    deadline = time.monotonic() + 6
    while fake_server.loops() != 0:
        assert time.monotonic() < deadline, "the loop still runs 6 s after its channel closed"
        await asyncio.sleep(0.2)


async def test_the_loop_refuses_an_interval_outside_1_to_10(fake_server):
    assert fake_server.exec("sh", "-s", "11", input=script().decode(), user="megoo").returncode == 2

    async with connect(fake_server.host, fake_server.port, "megoo", fake_server.host_key()) as conn:
        with pytest.raises(ValueError):
            async with script_output(conn, script(), 0):
                pass


def new_files(fake_server) -> set[str]:
    found = fake_server.exec("find", "/", "-xdev", "-newer", "/tmp/marker", "-type", "f").stdout.split("\n")
    return {path for path in found if path.startswith(("/home/megoo/", "/tmp/")) and path != "/tmp/marker"}


async def test_the_loop_writes_no_file(fake_server):
    assert fake_server.exec("touch", "/tmp/marker").returncode == 0
    before = new_files(fake_server)

    async with connect(fake_server.host, fake_server.port, "megoo", fake_server.host_key()) as conn:
        await samples(conn, 1, 2)

    assert new_files(fake_server) == before
