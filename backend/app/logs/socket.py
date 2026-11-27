"""WS /api/ws/logs: the live lines of the log sources a person follows, through the logs worker.

Browser to backend:
    {"type":"subscribe","sources":[...]}, at most 16 sources and 16 kB. It replaces the socket's set: sources already
        open stay open, new ones open, the others close.
    {"type":"active"}: the person did something in the log view.
Backend to browser:
    {"type":"subscribed","sources":[{"id","source"}],"denied":[{"source","reason"}]} after each subscribe. The id of
        a source is its key. denied keeps the asked order.
    {"type":"lines","source":id,"lines":[...],"backlog":true} once per source, then the same without backlog.
    {"type":"skipped","source":id,"count":n} where the worker's cap dropped lines.
    {"type":"ended","source":id,"reason":...} (+ "status" for exited): the source is closed for this socket. Besides
        the worker's reasons: "idle" when the person did nothing in the log view for LOG_STREAM_IDLE_MINUTES (every
        source ends, the socket stays open), and "not_found", "forbidden" or "not_allowed" when the recheck finds the
        server gone or hidden, View logs lost, or the file's pattern removed.
    {"type":"error","detail":"invalid_message"} for a message that is neither. The socket stays open.
Close codes:
    4401 not signed in, at the handshake or at a recheck every 30 seconds; 1013 the browser reads too slowly (a
    queue of 1,000 messages is full); 1011 Valkey cannot be reached, or an audit event cannot be recorded. A foreign
    Origin is refused with 403.

The socket asks the worker on REQUESTS and gets its answer on its own viewer channel. It subscribes to a source's
channel, and waits for Valkey's confirmation, before it asks: the lines that arrive before the answer are held, and
after the answer's backlog only those with a higher seq are sent, so the browser sees no gap and no line twice.

Per socket: one Valkey subscription and a bounded queue, and tasks in one TaskGroup: the reader (client messages),
the pump (Valkey to the queue), the sender (the queue to the browser), the recheck and the watch (idle). When one
ends, the others are cancelled and the socket closes; its remaining sources are recorded closed with "signed_out"
after 4401 and "left" otherwise. Each subscribe and recheck opens a short database session.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Iterable
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Annotated, Literal

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from sqlalchemy import select
from valkey.asyncio import Valkey
from valkey.asyncio.client import PubSub
from valkey.exceptions import ValkeyError

from app.access.actions import ACCESS_DENIED
from app.access.permissions import Permission
from app.access.servers import record_hidden
from app.audit import Event, Result, Target, record_alone, source_of
from app.auth.service import actor_of
from app.auth.socket import NOT_SIGNED_IN_CLOSE, SocketSession, recheck, signed_in_socket
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.valkey import valkey_client
from app.inventory.models import Server
from app.logs.actions import LOGS_STREAM_CLOSED, LOGS_STREAM_OPENED
from app.logs.allowlist import matches, patterns_of
from app.logs.protocol import (
    ON_SOURCE,
    REQUESTS,
    TO_VIEWER,
    WORKER,
    Ended,
    Lines,
    Opened,
    OpenRequest,
    Refused,
    Skipped,
    encode,
    source_channel,
    viewer_channel,
)
from app.logs.sources import FileSource, Source, describe, source_key

logger = logging.getLogger(__name__)
router = APIRouter()

ROUTE = "WS /api/ws/logs"
MAX_SOURCES = 16
MAX_MESSAGE_BYTES = 16_384
QUEUE_LIMIT = 1000
RECHECK_EVERY = 30.0
OPEN_TIMEOUT = 5.0
ALIVE_TIMEOUT = 15.0
WATCH_EVERY = 0.5
SLOW_CLOSE = 1013
VALKEY_CLOSE = 1011
INVALID = {"type": "error", "detail": "invalid_message"}
SOURCE_PREFIX = source_channel("")


def idle_after() -> float:
    """Seconds without activity after which a socket's sources end."""
    return get_settings().log_stream_idle_minutes * 60.0


class SubscribeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["subscribe"]
    sources: list[Source] = Field(max_length=MAX_SOURCES)


class ActiveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["active"]


CLIENT: TypeAdapter[SubscribeIn | ActiveIn] = TypeAdapter(
    Annotated[SubscribeIn | ActiveIn, Field(discriminator="type")]
)


class _Closed(Exception):
    """Ends the socket's tasks. A code is sent to the browser; None when the browser has gone."""

    def __init__(self, code: int | None = None) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class _Open:
    """A source this socket follows: waiting for the worker's answer, then live."""

    key: str
    source: Source
    server_id: uuid.UUID
    server_name: str
    group_id: uuid.UUID
    opened_at: float
    request_id: str
    reply: asyncio.Future
    state: Literal["waiting", "live"] = "waiting"
    # The source's messages that arrived before the answer.
    held: list[Lines | Skipped | Ended] = field(default_factory=list)
    last_seq: int = 0


class _Channels:
    """The socket's one Valkey subscription. subscribe() returns once Valkey confirmed it; the pump reads the
    confirmations and hands them over with confirmed()."""

    def __init__(self, pubsub: PubSub) -> None:
        self.pubsub = pubsub
        self._waiting: dict[str, asyncio.Future] = {}

    async def subscribe(self, channel: str) -> None:
        confirmed = asyncio.get_running_loop().create_future()
        self._waiting[channel] = confirmed
        await self.pubsub.subscribe(channel)
        try:
            await asyncio.wait_for(confirmed, OPEN_TIMEOUT)
        except TimeoutError:
            logger.warning("Closed a logs socket, Valkey did not confirm a subscription")
            raise _Closed(VALKEY_CLOSE) from None
        finally:
            self._waiting.pop(channel, None)

    def confirmed(self, channel: str) -> None:
        waiting = self._waiting.get(channel)
        if waiting is not None and not waiting.done():
            waiting.set_result(None)

    async def unsubscribe(self, channels: Iterable[str]) -> None:
        channels = list(channels)
        if channels:
            await self.pubsub.unsubscribe(*channels)


@dataclass
class _Socket:
    websocket: WebSocket
    signed: SocketSession
    client: Valkey
    channels: _Channels
    queue: asyncio.Queue
    socket_id: str
    opens: dict[str, _Open] = field(default_factory=dict)
    # The servers already given an access.denied event on this socket.
    recorded: set[uuid.UUID] = field(default_factory=set)
    run_id: str | None = None
    last_active: float = field(default_factory=time.monotonic)
    last_alive: float = field(default_factory=time.monotonic)
    # The logs.stream_closed events of sources already removed, until they are recorded: a socket that closes while
    # one is being recorded records the rest when it closes.
    unrecorded: list[Event] = field(default_factory=list)
    # A subscribe reads and replaces the open sources while the pump runs.
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


def _text(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value


async def _record(event: Event) -> None:
    """Records the event on its own. A failure closes the socket with 1011, as it answers 500 elsewhere."""
    try:
        await record_alone(event)
    except Exception:
        logger.exception("Closed a logs socket, the audit event %s cannot be recorded", event.action)
        raise _Closed(VALKEY_CLOSE) from None


def _event(socket: _Socket, action: str, server: tuple[uuid.UUID, str, uuid.UUID], detail: dict,
           result: Result = Result.SUCCESS) -> Event:
    server_id, name, group_id = server
    return Event(
        action=action,
        actor=actor_of(socket.signed.user),
        result=result,
        target=Target(type="server", id=str(server_id), name=name),
        context={"server_group_id": str(group_id)},
        result_detail=detail,
        source=source_of(socket.websocket, auth_method="password", mfa=True),
    )


def _by_server(opens: Iterable[_Open]) -> dict[uuid.UUID, list[_Open]]:
    grouped: dict[uuid.UUID, list[_Open]] = {}
    for open_ in opens:
        grouped.setdefault(open_.server_id, []).append(open_)
    return grouped


def _described(opens: list[_Open]) -> list[dict]:
    return [describe(open_.source) for open_ in sorted(opens, key=lambda open_: open_.key)]


def stream_closed(socket: _Socket, opens: Iterable[_Open], reason: str, duration: int | None = None) -> list[Event]:
    """One logs.stream_closed per server for these sources closing together, kept in socket.unrecorded. Call it with
    no await since the sources left socket.opens, so that no closing source goes unrecorded."""
    now = time.monotonic()
    events = []
    for together in _by_server(opens).values():
        first = together[0]
        # Whole seconds: an audit event holds no floats.
        seconds = duration if duration is not None else round(now - min(o.opened_at for o in together))
        detail = {"sources": _described(together), "duration_seconds": seconds, "reason": reason}
        events.append(_event(socket, LOGS_STREAM_CLOSED, (first.server_id, first.server_name, first.group_id), detail))
    socket.unrecorded.extend(events)
    return events


async def _record_closed(socket: _Socket, events: list[Event]) -> None:
    for event in events:
        await _record(event)
        socket.unrecorded = [other for other in socket.unrecorded if other is not event]


async def _close_opens(socket: _Socket, opens: list[_Open], events: list[Event]) -> None:
    """Unsubscribes these sources, already removed from the socket, and records their stream_closed events."""
    await socket.channels.unsubscribe(source_channel(open_.key) for open_ in opens)
    await _record_closed(socket, events)


async def _end(socket: _Socket, key: str, reason: str, status: int | None = None) -> None:
    """Tells the browser that the source ended and closes it. Nothing when it is no longer open."""
    open_ = socket.opens.pop(key, None)
    if open_ is None:
        return
    events = stream_closed(socket, [open_], reason)
    message = {"type": "ended", "source": key, "reason": reason}
    if status is not None:
        message["status"] = status
    socket.enqueue(message)
    await _close_opens(socket, [open_], events)


async def _end_together(socket: _Socket, keys: Iterable[str], reason: str) -> None:
    """Tells the browser that these sources ended and closes them, one stream_closed per server."""
    opens = [socket.opens.pop(key) for key in list(keys) if key in socket.opens]
    events = stream_closed(socket, opens, reason)
    for open_ in opens:
        socket.enqueue({"type": "ended", "source": open_.key, "reason": reason})
    if opens:
        await _close_opens(socket, opens, events)


def _translate(socket: _Socket, open_: _Open, message: Lines | Skipped | Ended) -> Ended | None:
    """Enqueues what the browser gets of a live source's message: the lines it has not had yet, and a skipped count
    that falls after them. An end is returned for the caller to close the source."""
    match message:
        case Lines():
            lines = [line for line in message.lines if line.get("seq", 0) > open_.last_seq]
            if lines:
                open_.last_seq = max(line["seq"] for line in lines)
                socket.enqueue({"type": "lines", "source": open_.key, "lines": lines})
        case Skipped():
            if message.after_seq >= open_.last_seq:
                socket.enqueue({"type": "skipped", "source": open_.key, "count": message.count})
        case Ended():
            return message
    return None


def _go_live(socket: _Socket, open_: _Open, opened: Opened) -> Ended | None:
    """Enqueues the backlog, then the held messages after it. No await, so no live message comes in between."""
    socket.enqueue({"type": "lines", "source": open_.key, "lines": opened.lines, "backlog": True})
    open_.last_seq = opened.last_seq
    open_.state = "live"
    held, open_.held = open_.held, []
    for message in held:
        ended = _translate(socket, open_, message)
        if ended is not None:
            return ended
    return None


async def _check(socket: _Socket, new: dict[str, Source]) -> tuple[list[_Open], dict[str, str]]:
    """The new sources the person may read, as waiting opens, and the reason of each other one. Records an
    access.denied once per socket and server."""
    if not new:
        return [], {}
    access = socket.signed.access
    server_ids = {source.server_id for source in new.values()}
    async with SessionLocal() as db:
        query = select(Server.id, Server.name, Server.server_group_id).where(Server.id.in_(server_ids))
        servers = {id_: (id_, name, group_id) for id_, name, group_id in await db.execute(query)}
        groups = {servers[s.server_id][2] for s in new.values() if isinstance(s, FileSource) and s.server_id in servers}
        patterns = await patterns_of(db, groups) if groups else {}

    accepted: list[_Open] = []
    denied: dict[str, str] = {}
    hidden: set[uuid.UUID] = set()
    refusals: dict[uuid.UUID, dict] = {}
    for key, source in new.items():
        server = servers.get(source.server_id)
        if server is None or not access.sees(server[2]):
            denied[key] = "not_found"
            if server is not None:
                hidden.add(server[0])
        elif not access.allows(Permission.VIEW_LOGS, server[2]):
            denied[key] = "forbidden"
            refusals.setdefault(server[0], {"required": "view_logs", "route": ROUTE})
        elif isinstance(source, FileSource) and not matches(source.path, patterns.get(server[2], [])):
            denied[key] = "not_allowed"
            refusals.setdefault(server[0], {"required": "log_file_allowlist", "route": ROUTE, "path": source.path})
        else:
            accepted.append(
                _Open(key=key, source=source, server_id=server[0], server_name=server[1], group_id=server[2],
                      opened_at=time.monotonic(), request_id=uuid.uuid4().hex,
                      reply=asyncio.get_running_loop().create_future())
            )

    hidden -= socket.recorded
    if hidden:
        socket.recorded |= hidden
        try:
            await record_hidden(socket.websocket, socket.signed.user, ROUTE, hidden)
        except Exception:
            logger.exception("Closed a logs socket, an access.denied event cannot be recorded")
            raise _Closed(VALKEY_CLOSE) from None
    for server_id, detail in refusals.items():
        if server_id not in socket.recorded:
            socket.recorded.add(server_id)
            await _record(_event(socket, ACCESS_DENIED, servers[server_id], detail, Result.FAILURE))
    return accepted, denied


async def _subscribe(socket: _Socket, asked: SubscribeIn) -> None:
    async with socket.lock:
        socket.last_active = time.monotonic()
        wanted = {source_key(source): source for source in asked.sources}
        left = [socket.opens.pop(key) for key in list(socket.opens) if key not in wanted]
        if left:
            await _close_opens(socket, left, stream_closed(socket, left, "left"))
        accepted, denied = await _check(socket, {k: s for k, s in wanted.items() if k not in socket.opens})

        # Recorded before anything is asked of the worker: if it cannot be recorded, nothing opens.
        for together in _by_server(accepted).values():
            first = together[0]
            server = (first.server_id, first.server_name, first.group_id)
            await _record(_event(socket, LOGS_STREAM_OPENED, server, {"sources": _described(together)}))

        asked_worker: list[asyncio.Future] = []
        for open_ in accepted:
            socket.opens[open_.key] = open_
            await socket.channels.subscribe(source_channel(open_.key))
            request = OpenRequest(type="open", socket_id=socket.socket_id, request_id=open_.request_id,
                                  source=open_.source)
            if await socket.client.publish(REQUESTS, encode(request)):
                asked_worker.append(open_.reply)
        if asked_worker:
            await asyncio.wait(asked_worker, timeout=OPEN_TIMEOUT)

        answered: list[tuple[_Open, Opened]] = []
        refused: list[tuple[_Open, list[Event]]] = []
        for open_ in accepted:
            if socket.opens.get(open_.key) is not open_ or not open_.reply.done():
                continue
            reply = open_.reply.result()
            if isinstance(reply, Refused):
                del socket.opens[open_.key]
                denied[open_.key] = reply.reason
                refused.append((open_, stream_closed(socket, [open_], reply.reason, duration=0)))
            else:
                answered.append((open_, reply))
        for open_, events in refused:
            await _close_opens(socket, [open_], events)

        socket.enqueue(
            {
                "type": "subscribed",
                "sources": [{"id": key, "source": describe(socket.opens[key].source)} for key in sorted(socket.opens)],
                "denied": [{"source": describe(wanted[key]), "reason": denied[key]} for key in wanted if key in denied],
            }
        )
        ends: list[tuple[str, Ended]] = []
        for open_, opened in answered:
            if socket.run_id is None:
                socket.run_id = opened.run_id
            ended = _go_live(socket, open_, opened)
            if ended is not None:
                ends.append((open_.key, ended))
        for key, ended in ends:
            await _end(socket, key, ended.reason, ended.status)


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
            asked = CLIENT.validate_json(text)
        except ValidationError:
            socket.enqueue(INVALID)
            continue
        if isinstance(asked, ActiveIn):
            socket.last_active = time.monotonic()
        else:
            await _subscribe(socket, asked)


def _answered(socket: _Socket, answer: Opened | Refused) -> None:
    for open_ in socket.opens.values():
        if open_.request_id == answer.request_id and not open_.reply.done():
            open_.reply.set_result(answer)
            return


async def _on_source(socket: _Socket, key: str, message: Lines | Skipped | Ended) -> None:
    open_ = socket.opens.get(key)
    if open_ is None:  # a message published before an unsubscribe can still arrive after it
        return
    if open_.state == "waiting":
        open_.held.append(message)
        if len(open_.held) > QUEUE_LIMIT:
            raise _Closed(SLOW_CLOSE)
        return
    ended = _translate(socket, open_, message)
    if ended is not None:
        await _end(socket, key, ended.reason, ended.status)


async def _pump(socket: _Socket) -> None:
    viewer = viewer_channel(socket.socket_id)
    while True:
        message = await socket.channels.pubsub.get_message(ignore_subscribe_messages=False, timeout=1.0)
        if message is None:
            continue
        channel = _text(message["channel"])
        if message["type"] == "subscribe":
            socket.channels.confirmed(channel)
            continue
        if message["type"] != "message" or channel == WORKER:
            continue
        try:
            if channel == viewer:
                _answered(socket, TO_VIEWER.validate_json(message["data"]))
            elif channel.startswith(SOURCE_PREFIX):
                await _on_source(socket, channel.removeprefix(SOURCE_PREFIX), ON_SOURCE.validate_json(message["data"]))
        except ValidationError as error:
            logger.warning("Skipped a message on %s: %s", channel, error.errors(include_input=False))


async def _sender(socket: _Socket) -> None:
    while True:
        message = await socket.queue.get()
        try:
            await _send(socket.websocket, message)
        except WebSocketDisconnect:
            raise _Closed() from None


def _lost(
    socket: _Socket, servers: dict[uuid.UUID, uuid.UUID], patterns: dict[uuid.UUID, list[str]]
) -> dict[str, str]:
    """The open sources the person may no longer read, with the reason of each. servers maps an existing server to
    its group."""
    access = socket.signed.access
    lost: dict[str, str] = {}
    for key, open_ in socket.opens.items():
        group_id = servers.get(open_.server_id)
        if group_id is None or not access.sees(group_id):
            lost[key] = "not_found"
        elif not access.allows(Permission.VIEW_LOGS, group_id):
            lost[key] = "forbidden"
        elif isinstance(open_.source, FileSource) and not matches(open_.source.path, patterns.get(group_id, [])):
            lost[key] = "not_allowed"
        else:
            open_.group_id = group_id
    return lost


async def _recheck(socket: _Socket) -> None:
    while True:
        await asyncio.sleep(RECHECK_EVERY)
        fresh = await recheck(socket.signed)
        if fresh is None:
            raise _Closed(NOT_SIGNED_IN_CLOSE)
        async with socket.lock:
            socket.signed = fresh
            if not socket.opens:
                continue
            server_ids = {open_.server_id for open_ in socket.opens.values()}
            async with SessionLocal() as db:
                query = select(Server.id, Server.server_group_id).where(Server.id.in_(server_ids))
                servers = {id_: group_id for id_, group_id in await db.execute(query)}
                groups = {servers[o.server_id] for o in socket.opens.values()
                          if isinstance(o.source, FileSource) and o.server_id in servers}
                patterns = await patterns_of(db, groups) if groups else {}
            lost = _lost(socket, servers, patterns)
            for reason in sorted(set(lost.values())):
                await _end_together(socket, [key for key, why in lost.items() if why == reason], reason)


async def _watch(socket: _Socket) -> None:
    while True:
        await asyncio.sleep(WATCH_EVERY)
        if not socket.opens:
            continue
        async with socket.lock:
            if socket.opens and time.monotonic() - socket.last_active >= idle_after():
                await _end_together(socket, socket.opens, "idle")


async def _serve(socket: _Socket) -> int | None:
    """Runs the socket's tasks until one ends it, and returns the close code to send."""
    code = None
    try:
        async with asyncio.TaskGroup() as group:
            for task in (_reader, _pump, _sender, _recheck, _watch):
                group.create_task(task(socket))
    except* _Closed as closed:
        code = closed.exceptions[0].code
    except* (ValkeyError, OSError) as failed:
        logger.warning("Closed a logs socket, Valkey failed: %s", failed.exceptions[0])
        code = VALKEY_CLOSE
    return code


async def _listening(pubsub: PubSub, *channels: str) -> None:
    """Subscribes and returns once Valkey confirmed every channel."""
    await pubsub.subscribe(*channels)
    confirmed = 0
    while confirmed < len(channels):
        message = await pubsub.get_message(timeout=OPEN_TIMEOUT)
        if message is None:
            raise TimeoutError("Valkey did not confirm the subscription")
        if message["type"] == "subscribe":
            confirmed += 1


@router.websocket("/ws/logs")
@signed_in_socket
async def logs_socket(websocket: WebSocket, signed: SocketSession) -> None:
    """The live lines of the log sources a person subscribes to and may read (see the module's docstring)."""
    socket_id = uuid.uuid4().hex
    client = valkey_client()
    async with AsyncExitStack() as stack:
        stack.push_async_callback(client.aclose)
        pubsub = client.pubsub()
        stack.push_async_callback(pubsub.aclose)
        try:
            await _listening(pubsub, viewer_channel(socket_id), WORKER)
        except (ValkeyError, OSError, TimeoutError) as error:
            logger.warning("Closed a logs socket, Valkey cannot be reached: %s", error)
            code = VALKEY_CLOSE
            socket = None
        else:
            socket = _Socket(websocket, signed, client, _Channels(pubsub), asyncio.Queue(QUEUE_LIMIT), socket_id)
            code = await _serve(socket)
        if code is not None:
            await _close(websocket, code)
        if socket is not None:
            # The pubsub closes with the socket, so the remaining sources are only recorded closed.
            reason = "signed_out" if code == NOT_SIGNED_IN_CLOSE else "left"
            stream_closed(socket, list(socket.opens.values()), reason)
            try:
                await _record_closed(socket, list(socket.unrecorded))
            except _Closed:  # logged by _record; the socket is closed already
                pass
