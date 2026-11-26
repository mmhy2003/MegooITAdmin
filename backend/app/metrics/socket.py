"""WS /api/ws/metrics: the live samples of the servers on a person's screen, one socket per open page.

Browser to backend:
    {"type":"subscribe","view":"overview"|"full","server_ids":[...]}, at most 200 servers and 16 kB. Each one
    replaces the previous subscription.
Backend to browser:
    {"type":"subscribed","server_ids":[...],"denied":[...]} after each subscribe, and again when a recheck drops a
        server. denied lists the asked servers the person does not see and those that do not exist.
    {"type":"overview","server_id","time","cpu","mem","load","disk":{"mount","percent"},"rx","tx"} in the overview
        view. A number the sample lacks is null.
    {"type":"sample","server_id","time","readings":[[metric,instance,value],...]} in the full view.
    {"type":"error","detail":"invalid_message"} for a message that is not a subscribe. The socket stays open.
Close codes:
    4401 not signed in, at the handshake or at a recheck every 30 seconds; 1013 the browser reads too slowly (a
    queue of 1,000 messages is full); 1011 Valkey cannot be reached. A foreign Origin is refused with 403.

Per socket: one Valkey subscription and a bounded queue, and four tasks in one TaskGroup: the reader (client
messages), the pump (Valkey to the queue), the sender (the queue to the browser) and the recheck. When one ends,
the others are cancelled and the socket closes. Each subscribe and recheck opens a short database session.
"""

import asyncio
import logging
import uuid
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Literal

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from valkey.exceptions import ValkeyError

from app.access.servers import record_hidden, split_visible
from app.auth.socket import NOT_SIGNED_IN_CLOSE, SocketSession, recheck, signed_in_socket
from app.core.db import SessionLocal
from app.core.valkey import valkey_client
from app.metrics.fanout import Subscription
from app.metrics.overview import iso, overview_message, summarize
from app.metrics.samples import Sample

logger = logging.getLogger(__name__)
router = APIRouter()

ROUTE = "WS /api/ws/metrics"
MAX_SERVERS = 200
MAX_MESSAGE_BYTES = 16_384
QUEUE_LIMIT = 1000
RECHECK_EVERY = 30.0
SLOW_CLOSE = 1013
VALKEY_CLOSE = 1011
INVALID = {"type": "error", "detail": "invalid_message"}


class SubscribeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["subscribe"]
    view: Literal["overview", "full"]
    server_ids: list[uuid.UUID] = Field(max_length=MAX_SERVERS)


class _Closed(Exception):
    """Ends the socket's tasks. A code is sent to the browser; None when the browser has gone."""

    def __init__(self, code: int | None = None) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class _Socket:
    websocket: WebSocket
    signed: SocketSession
    subscription: Subscription
    queue: asyncio.Queue
    view: str = "overview"
    recorded: bool = False
    # A subscribe and a recheck both read and replace the subscription's servers.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def enqueue(self, message: dict) -> None:
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            raise _Closed(SLOW_CLOSE) from None


async def _send(websocket: WebSocket, message: dict) -> None:
    await websocket.send_json(message)


async def _close(websocket: WebSocket, code: int) -> None:
    try:
        await websocket.close(code)
    except (RuntimeError, WebSocketDisconnect):  # already closed, or the browser has gone
        pass


def _message(sample: Sample, view: str) -> dict:
    if view == "overview":
        return overview_message(summarize(sample))
    return {
        "type": "sample",
        "server_id": str(sample.server_id),
        "time": iso(sample.time),
        "readings": [[r.metric, r.instance, r.value] for r in sample.readings],
    }


async def _subscribe(socket: _Socket, asked: SubscribeIn) -> None:
    ids = set(asked.server_ids)
    async with socket.lock:
        async with SessionLocal() as db:
            visible, hidden = await split_visible(db, socket.signed.access, ids)
        if hidden and not socket.recorded:
            socket.recorded = True
            await record_hidden(socket.websocket, socket.signed.user, ROUTE, hidden)
        await socket.subscription.replace(visible)
        socket.view = asked.view
    socket.enqueue(
        {
            "type": "subscribed",
            "server_ids": sorted(str(id_) for id_ in visible),
            "denied": sorted(str(id_) for id_ in ids - visible),
        }
    )


async def _reader(socket: _Socket) -> None:
    while True:
        try:
            text = await socket.websocket.receive_text()
        except WebSocketDisconnect:
            raise _Closed() from None
        if len(text.encode()) > MAX_MESSAGE_BYTES:
            socket.enqueue(INVALID)
            continue
        try:
            asked = SubscribeIn.model_validate_json(text)
        except ValidationError:
            socket.enqueue(INVALID)
            continue
        await _subscribe(socket, asked)


async def _pump(socket: _Socket) -> None:
    async for sample in socket.subscription:
        socket.enqueue(_message(sample, socket.view))


async def _sender(socket: _Socket) -> None:
    while True:
        message = await socket.queue.get()
        try:
            await _send(socket.websocket, message)
        except WebSocketDisconnect:
            raise _Closed() from None


async def _recheck(socket: _Socket) -> None:
    while True:
        await asyncio.sleep(RECHECK_EVERY)
        fresh = await recheck(socket.signed)
        if fresh is None:
            raise _Closed(NOT_SIGNED_IN_CLOSE)
        async with socket.lock:
            socket.signed = fresh
            servers = socket.subscription.servers
            async with SessionLocal() as db:
                visible, _ = await split_visible(db, fresh.access, servers)
            dropped = servers - visible
            if not dropped:
                continue
            await socket.subscription.replace(visible)
        socket.enqueue(
            {
                "type": "subscribed",
                "server_ids": sorted(str(id_) for id_ in visible),
                "denied": sorted(str(id_) for id_ in dropped),
            }
        )


async def _serve(socket: _Socket) -> int | None:
    """Runs the socket's tasks until one ends it, and returns the close code to send."""
    code = None
    try:
        async with asyncio.TaskGroup() as group:
            for task in (_reader, _pump, _sender, _recheck):
                group.create_task(task(socket))
    except* _Closed as closed:
        code = closed.exceptions[0].code
    except* ValkeyError as failed:
        logger.warning("Closed a metrics socket, Valkey failed: %s", failed.exceptions[0])
        code = VALKEY_CLOSE
    return code


@router.websocket("/ws/metrics")
@signed_in_socket
async def metrics_socket(websocket: WebSocket, signed: SocketSession) -> None:
    """The live samples of the servers a person subscribes to and sees (see the module's docstring)."""
    client = valkey_client()
    async with AsyncExitStack() as stack:
        stack.push_async_callback(client.aclose)
        try:
            subscription = await stack.enter_async_context(Subscription(client))
        except (ValkeyError, OSError) as error:
            logger.warning("Closed a metrics socket, Valkey cannot be reached: %s", error)
            code = VALKEY_CLOSE
        else:
            code = await _serve(_Socket(websocket, signed, subscription, asyncio.Queue(QUEUE_LIMIT)))
        if code is not None:
            await _close(websocket, code)
