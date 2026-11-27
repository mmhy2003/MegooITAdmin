"""How a running source ends, against the fake server and a real Valkey: a missing tool, an unreadable file, sudo
refused, a server it cannot reach or sign in to, a changed host key and a broken channel. Also a burst over the cap
and a line cut at 8 kB."""

import asyncio
import subprocess
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select, update

from app.core.valkey import valkey_client
from app.inventory.models import Server
from app.logs.lines import MAX_LINE_BYTES
from app.logs.protocol import Ended, Lines, Skipped
from app.logs.sources import NOT_READABLE, source_key
from app.logs.worker import source as source_module
from app.logs.worker.links import Links
from app.logs.worker.source import Limits, RunningSource, ended_by
from app.ssh import client
from app.ssh.client import Exit
from auth_helpers import events
from collector_helpers import eventually, pinned_server
from conftest import owner_session
from logs_helpers import log_file
from test_log_running import source_of, streamed, watching

LIMITS = Limits(batch_every=0.05)


@pytest.fixture
async def valkey():
    client = valkey_client()
    yield client
    await client.aclose()


@pytest.mark.parametrize(
    ("kind", "exit", "expected"),
    [
        ("journal", Exit(127, b""), ("not_available", None)),
        ("container", Exit(127, b""), ("not_available", None)),
        ("file", Exit(NOT_READABLE, b""), ("not_readable", None)),
        ("journal", Exit(NOT_READABLE, b""), ("exited", NOT_READABLE)),
        ("container", Exit(1, b"sudo: a password is required\n"), ("denied", None)),
        ("container", Exit(1, b"warming up\nsudo: a password is required\n"), ("denied", None)),
        ("container", Exit(1, b"not sudo: here\n"), ("exited", 1)),
        ("file", Exit(1, b"sudo: a password is required\n"), ("exited", 1)),
        ("container", Exit(3, b""), ("exited", 3)),
        ("journal", Exit(None, b""), ("exited", None)),
    ],
)
def test_ended_by(kind, exit, expected):
    assert ended_by(kind, exit) == expected


async def changed(server: Server, **values) -> Server:
    """The server with these columns changed in the database."""
    async with owner_session() as session:
        await session.execute(update(Server).where(Server.id == server.id).values(values))
        await session.commit()
        return (await session.execute(select(Server).where(Server.id == server.id))).scalar_one()


@asynccontextmanager
async def ending(source, server, valkey, limits: Limits = LIMITS, clock=None) -> AsyncIterator[tuple[list, list]]:
    """The messages on the source's channel and the sources passed to on_end, while the source runs."""
    extra = {} if clock is None else {"clock": clock}
    ran = RunningSource(source_key(source), source, server, links=Links(), valkey=valkey, limits=limits, **extra)
    ended: list = []
    async with watching(valkey, source_key(source)) as messages:
        ran.start(ended.append)
        try:
            yield messages, ended
        finally:
            await ran.stop()


async def the_end(messages: list, ended: list) -> Ended:
    await eventually(lambda: ended and messages and isinstance(messages[-1], Ended))
    return messages[-1]


async def test_a_missing_journalctl_ends_with_not_available(clean_auth, logs_sessions, fake_server, valkey):
    server = await pinned_server(fake_server, "ends-journal")
    with fake_server.hidden("/usr/local/bin/journalctl"):
        async with ending(source_of(server.id, kind="journal"), server, valkey) as (messages, ended):
            assert await the_end(messages, ended) == Ended(type="ended", reason="not_available")


async def test_a_file_megoo_cannot_read_ends_with_not_readable(clean_auth, logs_sessions, fake_server, valkey):
    server = await pinned_server(fake_server, "ends-unreadable")
    path = log_file("unreadable")
    fake_server.append(path, "secret\n")
    assert fake_server.exec("chmod", "600", path).returncode == 0

    async with ending(source_of(server.id, kind="file", path=path), server, valkey) as (messages, ended):
        assert await the_end(messages, ended) == Ended(type="ended", reason="not_readable")
        assert streamed(messages) == []


async def test_a_missing_file_ends_with_not_readable(clean_auth, logs_sessions, fake_server, valkey):
    server = await pinned_server(fake_server, "ends-missing")
    source = source_of(server.id, kind="file", path=log_file("missing"))

    async with ending(source, server, valkey) as (messages, ended):
        assert await the_end(messages, ended) == Ended(type="ended", reason="not_readable")


async def test_a_container_without_the_sudo_rule_ends_with_denied(clean_auth, logs_sessions, fake_server, valkey):
    server = await pinned_server(fake_server, "ends-nosudo", username="megoo-nosudo")
    source = source_of(server.id, kind="container", container_id="web-1")

    with fake_server.fixture("docker_logs", "2026-11-27T10:00:00Z hi\n"):
        async with ending(source, server, valkey) as (messages, ended):
            assert await the_end(messages, ended) == Ended(type="ended", reason="denied")
            assert streamed(messages) == []


async def test_an_unreachable_server_ends_with_unreachable(clean_auth, logs_sessions, fake_server, valkey):
    server = await changed(await pinned_server(fake_server, "ends-unreachable"), port=1)

    async with ending(source_of(server.id, kind="journal"), server, valkey) as (messages, ended):
        assert await the_end(messages, ended) == Ended(type="ended", reason="unreachable")


async def test_a_refused_key_ends_with_key_refused(clean_auth, logs_sessions, fake_server, valkey):
    server = await pinned_server(fake_server, "ends-refused", username="nobody")

    async with ending(source_of(server.id, kind="journal"), server, valkey) as (messages, ended):
        assert await the_end(messages, ended) == Ended(type="ended", reason="key_refused")


async def test_a_changed_host_key_flags_the_server_and_ends_the_source(
    clean_auth, logs_sessions, fake_server, valkey, tmp_path
):
    key = tmp_path / "other"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
    other = " ".join(key.with_suffix(".pub").read_text().split()[:2])
    server = await changed(await pinned_server(fake_server, "ends-changed"), host_key=other)

    async with ending(source_of(server.id, kind="journal"), server, valkey) as (messages, ended):
        assert await the_end(messages, ended) == Ended(type="ended", reason="host_key_changed")

    async with owner_session() as session:
        row = (await session.execute(select(Server).where(Server.id == server.id))).scalar_one()
    assert row.host_key_changed_at is not None
    (mismatch,) = await events("server.host_key_mismatch")
    assert (mismatch.actor_type, mismatch.actor_name) == ("system", "logs")


async def test_a_broken_channel_ends_with_ssh_error(clean_auth, logs_sessions, fake_server, valkey, monkeypatch):
    @asynccontextmanager
    async def follow(conn, argv):
        raise client.SshError()
        yield

    monkeypatch.setattr(source_module.client, "follow", follow)
    server = await pinned_server(fake_server, "ends-broken")

    async with ending(source_of(server.id, kind="journal"), server, valkey) as (messages, ended):
        assert await the_end(messages, ended) == Ended(type="ended", reason="ssh_error")


async def test_a_burst_over_the_cap_is_counted(clean_auth, logs_sessions, fake_server, valkey):
    server = await pinned_server(fake_server, "ends-burst")
    path = log_file("burst")
    fake_server.append(path, "")
    now = [0.0]
    limits = Limits(max_lines_per_second=50, batch_every=0.05)

    async with ending(source_of(server.id, kind="file", path=path), server, valkey, limits, lambda: now[0]) as (
        messages,
        _,
    ):
        # One line first, so the burst reaches a tail that already follows; then a second of its own for the burst.
        fake_server.append(path, "ready\n")
        await eventually(lambda: streamed(messages))
        now[0] = 10.0
        fake_server.append(path, "".join(f"burst {n}\n" for n in range(1, 501)))

        seen = -1
        while len(messages) != seen:  # until nothing came for 1 s
            seen = len(messages)
            await asyncio.sleep(1)

    burst = messages[1:]
    kept = streamed(burst)
    skipped = [message for message in burst if isinstance(message, Skipped)]
    assert len(kept) + sum(message.count for message in skipped) == 500
    assert [line["text"] for line in kept[:50]] == [f"burst {n}" for n in range(1, 51)]
    first = next(i for i, message in enumerate(burst) if isinstance(message, Skipped))
    assert len(streamed(burst[:first])) == 50
    assert skipped[0].after_seq == 51
    seqs = [line["seq"] for line in streamed(messages)]
    assert seqs == list(range(1, len(seqs) + 1))


async def test_a_line_over_8_kb_is_cut(clean_auth, logs_sessions, fake_server, valkey):
    server = await pinned_server(fake_server, "ends-long")
    path = log_file("long")
    fake_server.append(path, "x" * 10_000 + "\nafter\n")

    async with ending(source_of(server.id, kind="file", path=path), server, valkey) as (messages, _):
        await eventually(lambda: len(streamed(messages)) == 2)
        long, after = streamed(messages)
        assert long["truncated"] is True
        assert long["text"] == "x" * MAX_LINE_BYTES
        assert after == {"seq": 2, "time": after["time"], "text": "after"}
        assert all(isinstance(message, Lines) for message in messages)
