"""python -m app.collector as its own process: it starts without the auth key, reports healthy through its heartbeat,
and stops cleanly on SIGTERM. The healthcheck follows the heartbeat's age."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from app.collector.health import healthy

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
