"""Shared helpers of the collector tests: a server pinned to the fake server, what the collector wrote, and waiting."""

import asyncio
import inspect
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update

from app.inventory.models import Server, ServerStatus
from app.metrics.models import Metric
from auth_helpers import make_group, make_server
from conftest import owner_session


async def pinned_server(
    fake_server, name: str, *, username: str = "megoo", interval: int = 1, os: str = "linux", pinned: bool = True
) -> Server:
    """A server of its own group at the fake server's address, with the fake server's host key (pinned unless told
    otherwise), the account to sign in as and the sample interval."""
    group = await make_group(f"{name}-group")
    server = await make_server(group.id, name, address=fake_server.host, port=fake_server.port, os=os)
    values: dict[str, Any] = {
        "host_key": fake_server.host_key(),
        "connection_settings": {"username": username},
        "metrics_interval_seconds": interval,
    }
    if pinned:
        values["host_key_pinned_at"] = func.now()
    async with owner_session() as session:
        await session.execute(update(Server).where(Server.id == server.id).values(values))
        await session.commit()
        return (await session.execute(select(Server).where(Server.id == server.id))).scalar_one()


async def status_of(server_id: UUID) -> tuple[str, str | None] | None:
    async with owner_session() as session:
        found = await session.execute(select(ServerStatus).where(ServerStatus.server_id == server_id))
        row = found.scalar_one_or_none()
    return None if row is None else (row.state, row.reason)


async def metric_rows(server_id: UUID) -> int:
    async with owner_session() as session:
        count = select(func.count()).select_from(Metric).where(Metric.server_id == server_id)
        return (await session.execute(count)).scalar_one()


async def eventually(check: Callable[[], Any], timeout: float = 15.0, every: float = 0.1) -> None:
    """Calls check, and awaits what it returns when that is awaitable, until it is truthy."""
    deadline = time.monotonic() + timeout
    while True:
        result = check()
        if inspect.isawaitable(result):
            result = await result
        if result:
            return
        if time.monotonic() >= deadline:
            raise AssertionError(f"not within {timeout} s")
        await asyncio.sleep(every)
