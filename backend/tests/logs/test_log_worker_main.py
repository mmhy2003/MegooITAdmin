"""python -m app.logs.worker: serve says the hub is alive, stops every source when told to, and ends with a Valkey
error, so the process exits 1. The healthcheck follows the heartbeat's age."""

import asyncio
import os
import time
from contextlib import suppress

import pytest
from valkey.asyncio import from_url
from valkey.exceptions import ValkeyError

import app.logs.worker.__main__ as main_module
from app.logs.protocol import WORKER, Alive
from app.logs.sources import source_key
from app.logs.worker.health import healthy
from collector_helpers import eventually
from logs_helpers import log_file
from test_log_hub import Viewer, file_server, listened, valkey  # noqa: F401 (valkey is a fixture)
from test_log_running import source_of


@pytest.fixture
def worker_sessions(logs_sessions, monkeypatch):
    monkeypatch.setattr(main_module, "SessionLocal", logs_sessions)
    return logs_sessions


async def stopped(task: asyncio.Task, stop: asyncio.Event) -> None:
    stop.set()
    await asyncio.wait_for(task, 10)


async def test_serve_publishes_alive_and_stops_on_the_event(clean_auth, worker_sessions, valkey):
    pubsub = valkey.pubsub()
    await pubsub.subscribe(WORKER)
    stop = asyncio.Event()
    task = asyncio.create_task(main_module.serve(stop))
    try:
        async with asyncio.timeout(5):
            while (message := await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)) is None:
                pass
        assert Alive.model_validate_json(message["data"]).type == "alive"
        await stopped(task, stop)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await pubsub.aclose()


async def test_serve_stops_every_source_on_stop(clean_auth, worker_sessions, fake_server, valkey):
    server = await file_server(fake_server, "main-stop")
    path = log_file("stop")
    fake_server.append(path, "first\n")
    source = source_of(server.id, kind="file", path=path)
    stop = asyncio.Event()
    task = asyncio.create_task(main_module.serve(stop))
    try:
        await eventually(lambda: listened(valkey), timeout=5)
        async with Viewer(valkey) as viewer:
            answer = await viewer.open(source)
            assert answer.type == "opened"
            await eventually(lambda: [line["text"] for line in viewer.lines(source_key(source))] == ["first"])
            await stopped(task, stop)
        await eventually(lambda: asyncio.to_thread(lambda: fake_server.followers() == 0), timeout=5)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def test_a_valkey_failure_ends_serve_with_the_error(clean_auth, worker_sessions, monkeypatch):
    monkeypatch.setattr(main_module, "valkey_client", lambda settings: from_url("valkey://127.0.0.1:1/0"))

    with pytest.raises((ValkeyError, OSError)):
        await asyncio.wait_for(main_module.serve(asyncio.Event()), 20)


def test_health_is_healthy_only_with_a_fresh_heartbeat(tmp_path):
    heartbeat = tmp_path / "hb"
    now = time.time()
    assert not healthy(heartbeat, now)

    heartbeat.touch()
    os.utime(heartbeat, (now - 10, now - 10))
    assert healthy(heartbeat, now)

    os.utime(heartbeat, (now - 31, now - 31))
    assert not healthy(heartbeat, now)
