"""python -m app.collector as its own process: it starts without the auth key, reports healthy through its heartbeat,
and stops cleanly on SIGTERM. The healthcheck follows the heartbeat's age."""

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

import app.collector.__main__ as main_module
from app.collector.checks.runner import Recorder
from app.collector.health import healthy
from app.collector.supervisor import Supervisor
from app.collector.writer import Writer

BACKEND = Path(__file__).resolve().parents[2]


def test_healthy_follows_the_age_of_the_heartbeat(tmp_path):
    heartbeat = tmp_path / "hb"
    now = time.time()
    assert not healthy(heartbeat, now)

    heartbeat.touch()
    os.utime(heartbeat, (now - 10, now - 10))
    assert healthy(heartbeat, now)

    os.utime(heartbeat, (now - 31, now - 31))
    assert not healthy(heartbeat, now)


def test_the_collector_starts_without_the_key_reports_healthy_and_stops_on_sigterm(clean_auth, tmp_path):
    heartbeat = tmp_path / "hb"
    env = {k: v for k, v in os.environ.items() if k not in {"AUTH_SECRET_KEY", "DATABASE_OWNER_URL"}}
    env |= {"DATABASE_URL": os.environ["DATABASE_COLLECTOR_URL"], "COLLECTOR_HEARTBEAT_FILE": str(heartbeat)}
    process = subprocess.Popen(
        [sys.executable, "-m", "app.collector"], cwd=BACKEND, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        deadline = time.monotonic() + 20
        while not heartbeat.exists():
            assert process.poll() is None, process.stderr.read().decode()
            assert time.monotonic() < deadline, "no heartbeat within 20 s"
            time.sleep(0.2)

        check = subprocess.run(
            [sys.executable, "-m", "app.collector.health"], cwd=BACKEND, env=env, capture_output=True, timeout=30
        )
        assert check.returncode == 0, check.stderr.decode()

        process.send_signal(signal.SIGTERM)
        _, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr.decode()
        assert "The collector stopped." in stderr.decode()
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


async def test_serve_raises_when_the_writer_or_the_supervisor_ends(clean_auth, monkeypatch):
    # The process must exit then, so that Compose restarts it: an unhealthy container is not restarted.
    async def broken(self) -> None:
        raise ValueError("a bug")

    monkeypatch.setattr(Writer, "run", broken)

    with pytest.raises(ValueError, match="a bug"):
        await asyncio.wait_for(main_module.serve(asyncio.Event()), 20)


def test_the_collector_exits_non_zero_when_serve_fails(monkeypatch):
    async def failing(stop: asyncio.Event) -> None:
        raise ValueError("a bug")

    monkeypatch.setattr(main_module, "serve", failing)

    with pytest.raises(SystemExit) as exit_:
        main_module.main()
    assert exit_.value.code == 1


async def test_serve_gives_the_supervisor_a_recorder_on_its_publisher_and_writer(clean_auth, monkeypatch):
    built: dict = {}

    class Built(Supervisor):
        def __init__(self, **kwargs) -> None:
            built.update(kwargs)
            super().__init__(**kwargs)

        async def run(self) -> None:
            raise ValueError("built")

    monkeypatch.setattr(main_module, "Supervisor", Built)

    with pytest.raises(ValueError, match="built"):
        await asyncio.wait_for(main_module.serve(asyncio.Event()), 20)

    recorder = built["recorder"]
    assert isinstance(recorder, Recorder)
    assert (recorder.publisher, recorder.writer) == (built["publisher"], built["writer"])
