"""The collector checks the rules on real samples from the fake server: a rule fires, ends when it changes, and the
unreachable rule fires while the server is frozen and resolves on its next sample."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import update

from app.alerts.models import AlertRule
from app.collector.alerts.book import AlertBook
from app.collector.supervisor import Supervisor
from alerts_helpers import alerts_of, make_rule
from collector_helpers import FAST, eventually, parts, pinned_server
from conftest import owner_session


@asynccontextmanager
async def collecting(sessions, tmp_path) -> AsyncIterator[Supervisor]:
    """A supervisor polling every half second with an alert book, and its writer, while inside."""
    publisher, writer, status = parts(sessions)
    alerts = AlertBook(sessions)
    sup = Supervisor(
        sessions=sessions,
        publisher=publisher,
        writer=writer,
        status=status,
        timings=FAST,
        poll_every=0.5,
        heartbeat=tmp_path / "hb",
        alerts=alerts,
    )
    tasks = [asyncio.create_task(writer.run()), asyncio.create_task(sup.run())]
    try:
        yield sup
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await sup.stop()
        await writer.flush()


async def states_of(server_id, metric: str) -> list[tuple[str, str | None, str | None]]:
    alerts = await alerts_of(server_id)
    return [(alert.state, alert.instance, alert.end_reason) for alert in alerts if alert.metric == metric]


async def test_a_low_threshold_rule_fires_from_real_samples_and_resolves(
    clean_alerts, collector_sessions, fake_server, tmp_path
):
    server = await pinned_server(fake_server, "alert-1")
    rule = await make_rule(comparison="below", threshold=100, server_id=server.id)

    async with collecting(collector_sessions, tmp_path):
        await eventually(lambda: _has(server.id, "disk.used_percent", ("firing", "/", None)))

        async with owner_session() as session:
            raised = update(AlertRule).where(AlertRule.id == rule.id)
            await session.execute(raised.values(threshold=1, revision=AlertRule.revision + 1))
            await session.commit()
        await eventually(lambda: _has(server.id, "disk.used_percent", ("ended", "/", "rule_changed")))

        await make_rule(name="CPU", metric="cpu.used_percent", comparison="above", threshold=100, server_id=server.id)
        await asyncio.sleep(3)  # several polls and samples
        assert await states_of(server.id, "cpu.used_percent") == []


async def test_a_paused_server_fires_the_unreachable_rule_and_a_sample_resolves_it(
    clean_alerts, collector_sessions, fake_server, tmp_path
):
    server = await pinned_server(fake_server, "alert-2")
    await make_rule(metric="unreachable", comparison=None, threshold=None, server_id=server.id)

    async with collecting(collector_sessions, tmp_path) as sup:
        await eventually(lambda: sup.status.known(server.id) == ("reachable", None))
        fake_server.pause()
        try:
            await eventually(lambda: _has(server.id, "unreachable", ("firing", "", None)), timeout=30)
        finally:
            fake_server.unpause()
        await eventually(lambda: _has(server.id, "unreachable", ("resolved", "", None)), timeout=60)


async def _has(server_id, metric: str, state: tuple[str, str | None, str | None]) -> bool:
    return state in await states_of(server_id, metric)
