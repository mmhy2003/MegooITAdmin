import asyncio
import os

import pytest

from app.core.config import Settings
from app.main import create_app
from app.notify.sender import Sender


class FakeRun:
    """Stands in for Sender.run: notes that it started, then waits until it is cancelled."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False

    async def __call__(self, sender: Sender) -> None:
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


@pytest.fixture
def fake_run(monkeypatch) -> FakeRun:
    fake = FakeRun()

    async def run(sender: Sender) -> None:
        await fake(sender)

    monkeypatch.setattr(Sender, "run", run)
    return fake


def _app(*, notification_sender: bool):
    return create_app(Settings(database_url=os.environ["DATABASE_URL"], notification_sender=notification_sender))


async def test_the_lifespan_starts_and_stops_the_sender_when_on(fake_run):
    app = _app(notification_sender=True)
    async with app.router.lifespan_context(app):
        await asyncio.wait_for(fake_run.started.wait(), timeout=5)
        assert not fake_run.cancelled
    assert fake_run.cancelled


async def test_the_lifespan_starts_nothing_when_off(fake_run):
    app = _app(notification_sender=False)
    async with app.router.lifespan_context(app):
        await asyncio.sleep(0.05)
    assert not fake_run.started.is_set()
