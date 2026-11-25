"""Live metric fan-out through Valkey: one channel per server, metrics:<server_id>, one JSON message per Sample.

Delivery is at most once. A subscriber that was disconnected misses what was published meanwhile (valkey-py
subscribes again on reconnect). The database is the source of truth, and a dashboard fills its gaps from it.
Anything on the core network can publish, so a message that does not parse or validate is skipped with a warning.
"""

import json
import logging
import uuid
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from datetime import UTC
from typing import Literal

from pydantic import AwareDatetime, BaseModel
from valkey.asyncio import Valkey
from valkey.asyncio.client import PubSub

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
            "time": sample.time.astimezone(UTC).isoformat().replace("+00:00", "Z"),
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
