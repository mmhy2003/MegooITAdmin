"""Shared helpers of the log tests: allowlist patterns, log files, the log socket's messages, and a fake logs worker."""

import asyncio
import json
from contextlib import suppress
from uuid import UUID, uuid4

from conftest import owner_session
from pydantic import BaseModel
from valkey.asyncio import Valkey

from app.logs.models import LogFileAllowlist
from app.logs.protocol import (
    REQUESTS,
    WORKER,
    Alive,
    Opened,
    OpenRequest,
    Refused,
    encode,
    source_channel,
    viewer_channel,
)
from app.logs.sources import source_key

NOW_TEXT = "2026-11-27T10:00:00Z"


async def add_pattern(group_id: UUID, pattern: str) -> None:
    """Inserts a log_file_allowlist row as the owner, without events."""
    async with owner_session() as session:
        session.add(LogFileAllowlist(server_group_id=group_id, pattern=pattern))
        await session.commit()


def log_file(name: str) -> str:
    """A path of its own on the fake server, which the starter patterns cover."""
    return f"/var/log/nginx/{name}-{uuid4().hex[:8]}.log"


def text_line(seq: int, text: str) -> dict:
    return {"seq": seq, "time": NOW_TEXT, "text": text}


async def viewers(client: Valkey, key: str) -> int:
    """How many subscribers the source's channel has."""
    return (await client.pubsub_numsub(source_channel(key)))[0][1]


async def receive(ws, timeout: float = 5) -> dict:
    return json.loads(await asyncio.wait_for(ws.recv(), timeout))


async def receive_type(ws, kind: str, timeout: float = 5) -> dict:
    """The next message of this type; the others before it are skipped."""
    async with asyncio.timeout(timeout):
        while (message := await receive(ws, timeout))["type"] != kind:
            pass
    return message


async def subscribe(ws, sources: list[dict]) -> dict:
    """Sends a subscribe and returns the "subscribed" answer."""
    await ws.send(json.dumps({"type": "subscribe", "sources": sources}))
    return await receive_type(ws, "subscribed")


class FakeWorker:
    """Stands in for the logs worker on Valkey: answers each open request, and publishes what a test tells it to."""

    def __init__(self, client: Valkey, *, run_id: str = "f" * 32, answer: bool = True):
        self.requests: list[OpenRequest] = []
        self.refusals: dict[str, str] = {}
        self.backlogs: dict[str, tuple[list[dict], int]] = {}
        self.run_id = run_id
        self._client = client
        self._answer = answer
        self._pubsub = client.pubsub()
        self._task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> "FakeWorker":
        await self._pubsub.subscribe(REQUESTS)
        async with asyncio.timeout(5):
            while (message := await self._pubsub.get_message(timeout=1.0)) is None or message["type"] != "subscribe":
                pass
        self._task = asyncio.create_task(self._serve())
        return self

    async def __aexit__(self, *exc) -> None:
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        await self._pubsub.aclose()

    async def publish(self, key: str, message: BaseModel) -> None:
        await self._client.publish(source_channel(key), encode(message))

    async def alive(self, run_id: str | None = None) -> None:
        await self._client.publish(WORKER, encode(Alive(type="alive", run_id=run_id or self.run_id)))

    async def _serve(self) -> None:
        while True:
            message = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is None:
                continue
            request = OpenRequest.model_validate_json(message["data"])
            self.requests.append(request)
            if not self._answer:
                continue
            key = source_key(request.source)
            answer: Opened | Refused
            if key in self.refusals:
                answer = Refused(type="refused", request_id=request.request_id, key=key, reason=self.refusals[key])
            else:
                lines, last_seq = self.backlogs.get(key, ([], 0))
                answer = Opened(type="opened", request_id=request.request_id, key=key, run_id=self.run_id,
                                lines=lines, last_seq=last_seq)
            await self._client.publish(viewer_channel(request.socket_id), encode(answer))
