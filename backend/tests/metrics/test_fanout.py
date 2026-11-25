import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

import pytest

from app.core.valkey import valkey_client
from app.metrics.fanout import channel, encode, publish, subscribe
from app.metrics.samples import Reading, Sample

NOW = datetime(2026, 11, 25, 10, 0, 5, tzinfo=UTC)


def _sample(server_id: uuid.UUID, value: float = 12.5) -> Sample:
    return Sample(
        time=NOW,
        server_id=server_id,
        readings=(
            Reading(metric="cpu.used_percent", value=value),
            Reading(metric="disk.used_percent", instance="/var", value=81.0),
        ),
    )


@pytest.fixture
async def client():
    client = valkey_client()
    yield client
    await client.aclose()


async def _next(samples) -> Sample:
    return await asyncio.wait_for(anext(samples), 5)


def test_the_payload_is_the_designs_json():
    server_id = uuid.UUID("0b6c5f7e-2a51-4c1e-9d43-7a8f9e1c2b3d")
    assert json.loads(encode(_sample(server_id))) == {
        "v": 1,
        "server_id": str(server_id),
        "time": "2026-11-25T10:00:05Z",
        "readings": [["cpu.used_percent", "", 12.5], ["disk.used_percent", "/var", 81.0]],
    }
    assert channel(server_id) == f"metrics:{server_id}"


async def test_a_published_sample_reaches_a_subscriber_of_its_server(client):
    sample = _sample(uuid.uuid4())
    async with subscribe(client, [sample.server_id]) as samples:
        assert await publish(client, sample) == 1
        assert await _next(samples) == sample


async def test_a_subscriber_of_another_server_does_not_get_it(client):
    a, b = _sample(uuid.uuid4(), 1.0), _sample(uuid.uuid4(), 2.0)
    async with subscribe(client, [b.server_id]) as samples:
        assert await publish(client, a) == 0
        assert await publish(client, b) == 1
        assert await _next(samples) == b


async def test_a_malformed_message_is_skipped_and_the_next_one_arrives(client, caplog):
    sample = _sample(uuid.uuid4())
    bad_version = json.loads(encode(sample)) | {"v": 2}
    bad_metric = json.loads(encode(sample)) | {"readings": [["CPU", "", 1.0]]}
    with caplog.at_level(logging.WARNING, logger="app.metrics.fanout"):
        async with subscribe(client, [sample.server_id]) as samples:
            for bad in (b"not json", json.dumps(bad_version), json.dumps(bad_metric)):
                await client.publish(channel(sample.server_id), bad)
            await publish(client, sample)
            assert await _next(samples) == sample
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 3


async def test_leaving_the_subscription_closes_its_connection(client):
    server_id = uuid.uuid4()
    name = channel(server_id).encode()
    async with subscribe(client, [server_id]):
        assert await client.pubsub_numsub(name) == [(name, 1)]
    assert await client.pubsub_numsub(name) == [(name, 0)]


async def test_subscribe_needs_a_server(client):
    with pytest.raises(ValueError):
        async with subscribe(client, []):
            pass
