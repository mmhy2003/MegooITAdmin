import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

import pytest
import valkey.exceptions
from valkey.asyncio import from_url

from app.core.valkey import valkey_client
from app.metrics.fanout import Subscription, channel, encode, publish
from app.metrics.samples import Reading, Sample

NOW = datetime(2026, 11, 25, 10, 0, 5, tzinfo=UTC)


def _sample(server_id: uuid.UUID, value: float = 12.5) -> Sample:
    return Sample(time=NOW, server_id=server_id, readings=(Reading(metric="cpu.used_percent", value=value),))


@pytest.fixture
async def client():
    client = valkey_client()
    yield client
    await client.aclose()


async def on_valkey(client, server_id: uuid.UUID, count: int = 1) -> None:
    """Waits until Valkey counts this many subscribers of the server: replace() returns before Valkey applied it."""
    async with asyncio.timeout(5):
        while (await client.pubsub_numsub(channel(server_id)))[0][1] != count:
            await asyncio.sleep(0.02)


async def _next(sub: Subscription) -> Sample:
    return await asyncio.wait_for(anext(aiter(sub)), 5)


async def test_a_subscription_without_servers_waits_quietly(client):
    async with Subscription(client) as sub:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(anext(aiter(sub)), 0.3)
        assert sub.servers == frozenset()


async def test_replace_adds_a_server_while_reading(client):
    a = uuid.uuid4()
    async with Subscription(client) as sub:
        reading = asyncio.create_task(_next(sub))
        await asyncio.sleep(0.05)
        await sub.replace({a})
        await on_valkey(client, a)
        await publish(client, _sample(a))
        assert await reading == _sample(a)


async def test_replace_removes_a_server(client):
    a, b = uuid.uuid4(), uuid.uuid4()
    async with Subscription(client) as sub:
        await sub.replace({a})
        await sub.replace({b})
        await on_valkey(client, b)
        await on_valkey(client, a, 0)
        await publish(client, _sample(a, 1.0))
        await publish(client, _sample(b, 2.0))
        assert await _next(sub) == _sample(b, 2.0)
        assert sub.servers == {b}


async def test_a_sample_of_a_server_no_longer_subscribed_is_dropped(client):
    a, b = uuid.uuid4(), uuid.uuid4()
    async with Subscription(client) as sub:
        await sub.replace({a})
        await on_valkey(client, a)
        await publish(client, _sample(a, 1.0))
        await sub.replace({b})
        await on_valkey(client, b)
        await publish(client, _sample(b, 2.0))
        assert await _next(sub) == _sample(b, 2.0)


async def test_a_malformed_message_is_skipped_with_a_warning(client, caplog):
    sample = _sample(uuid.uuid4())
    bad_version = json.loads(encode(sample)) | {"v": 2}
    with caplog.at_level(logging.WARNING, logger="app.metrics.fanout"):
        async with Subscription(client) as sub:
            await sub.replace({sample.server_id})
            await on_valkey(client, sample.server_id)
            for bad in (b"not json", json.dumps(bad_version)):
                await client.publish(channel(sample.server_id), bad)
            await publish(client, sample)
            assert await _next(sub) == sample
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 2


async def test_leaving_closes_the_connection(client):
    server_id = uuid.uuid4()
    async with Subscription(client) as sub:
        await sub.replace({server_id})
        await on_valkey(client, server_id)
    name = channel(server_id).encode()
    assert await client.pubsub_numsub(name) == [(name, 0)]


async def test_an_unreachable_valkey_raises_on_enter():
    unreachable = from_url("valkey://127.0.0.1:1/0")
    try:
        with pytest.raises(valkey.exceptions.ConnectionError):
            async with Subscription(unreachable):
                pass
    finally:
        await unreachable.aclose()
