"""Live metric fan-out through Valkey: one channel per server, metrics:<server_id>, one JSON message per Sample.

Delivery is at most once. A subscriber that was disconnected misses what was published meanwhile (valkey-py
subscribes again on reconnect). The database is the source of truth, and a dashboard fills its gaps from it.
Anything on the core network can publish, so a message that does not parse or validate is skipped with a warning.

subscribe() reads a fixed set of servers. A Subscription's servers can change while it is read, so one dashboard
socket follows the servers on its screen with one connection.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel
from valkey.asyncio import Valkey
from valkey.asyncio.client import PubSub

from app.metrics.overview import iso
from app.metrics.samples import Reading, Sample

logger = logging.getLogger(__name__)
SUBSCRIBE_TIMEOUT = 5.0


class _Message(BaseModel):
    v: Literal[1]
    server_id: uuid.UUID
    time: AwareDatetime
    readings: list[tuple[str, str, float]]


def channel(server_id: uuid.UUID) -> str:
    return f"metrics:{server_id}"


def encode(sample: Sample) -> str:
    return json.dumps(
        {
            "v": 1,
            "server_id": str(sample.server_id),
            "time": iso(sample.time),
            "readings": [[r.metric, r.instance, r.value] for r in sample.readings],
        },
        separators=(",", ":"),
    )


def decode(data: bytes | str) -> Sample:
    """The Sample of a message. Raises ValueError (pydantic's ValidationError is one) when it is not one."""
    message = _Message.model_validate_json(data)
    return Sample(
        time=message.time,
        server_id=message.server_id,
        readings=tuple(Reading(metric=m, instance=i, value=v) for m, i, v in message.readings),
    )


async def publish(client: Valkey, sample: Sample) -> int:
    """Sends the sample to the subscribers of its server. Returns how many got it."""
    return await client.publish(channel(sample.server_id), encode(sample))


async def _samples(pubsub: PubSub) -> AsyncIterator[Sample]:
    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        try:
            yield decode(message["data"])
        except ValueError as error:
            logger.warning("Skipped a message on %s: %s", message["channel"], error)


@asynccontextmanager
async def subscribe(client: Valkey, server_ids: Iterable[uuid.UUID]) -> AsyncIterator[AsyncIterator[Sample]]:
    """The samples of these servers, from the moment Valkey confirmed the subscription. Leaving closes its connection."""
    channels = sorted({channel(server_id) for server_id in server_ids})
    if not channels:
        raise ValueError("subscribe needs at least one server")
    async with client.pubsub() as pubsub:
        await pubsub.subscribe(*channels)
        confirmed = 0
        while confirmed < len(channels):
            message = await pubsub.get_message(timeout=SUBSCRIBE_TIMEOUT)
            if message is None:
                raise TimeoutError("Valkey did not confirm the subscription")
            if message["type"] == "subscribe":
                confirmed += 1
        yield _samples(pubsub)


class Subscription:
    """Samples of a set of servers that can change while it is read. One pubsub connection; leaving closes it."""

    def __init__(self, client: Valkey) -> None:
        self._client = client
        self._pubsub: PubSub | None = None
        self._servers: frozenset[uuid.UUID] = frozenset()
        self._connected = asyncio.Event()

    async def __aenter__(self) -> Self:
        self._pubsub = self._client.pubsub()
        await self._client.ping()
        return self

    async def __aexit__(self, *exc) -> None:
        await self._pubsub.aclose()

    @property
    def servers(self) -> frozenset[uuid.UUID]:
        return self._servers

    async def replace(self, server_ids: Iterable[uuid.UUID]) -> None:
        """Subscribes the new servers' channels and unsubscribes the gone ones. Returns once the commands are sent."""
        servers = frozenset(server_ids)
        new = sorted(channel(server_id) for server_id in servers - self._servers)
        gone = sorted(channel(server_id) for server_id in self._servers - servers)
        if new:
            await self._pubsub.subscribe(*new)
            self._connected.set()
        if gone:
            await self._pubsub.unsubscribe(*gone)
        self._servers = servers

    def __aiter__(self) -> AsyncIterator[Sample]:
        return self._samples()

    async def _samples(self) -> AsyncIterator[Sample]:
        while True:
            # The pubsub has no connection to read until its first subscribe.
            await self._connected.wait()
            message = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is None:
                continue
            try:
                sample = decode(message["data"])
            except ValueError as error:
                logger.warning("Skipped a message on %s: %s", message["channel"], error)
                continue
            # A message published before an unsubscribe can still arrive after it.
            if sample.server_id in self._servers:
                yield sample
