"""Shared helpers of the WebSocket tests: a real Uvicorn server on a free port, a client that sends a session cookie
and an Origin, and the close code a server sends."""

import asyncio
from contextlib import asynccontextmanager

import uvicorn
from websockets.asyncio.client import ClientConnection, connect as ws_connect
from websockets.exceptions import ConnectionClosed
from websockets.typing import Origin

from app.auth.sessions import COOKIE


@asynccontextmanager
async def serving(app):
    """Serves the app on 127.0.0.1 and a free port in this event loop, and yields '127.0.0.1:<port>'. The WebSocket
    implementation is the one the image's `--ws auto` picks."""
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, ws="websockets-sansio", lifespan="off", log_level="warning")
    )
    task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            if task.done():
                await task
            await asyncio.sleep(0.01)
        host, port = server.servers[0].sockets[0].getsockname()[:2]
        yield f"{host}:{port}"
    finally:
        server.should_exit = True
        await task


def connect(base: str, path: str, cookie: str | None = None, origin: str | None = "default"):
    """A websockets client for ws://<base><path>. The Origin is the server's own unless given; None sends none."""
    if origin == "default":
        origin = f"http://{base}"
    headers = {"Cookie": f"{COOKIE}={cookie}"} if cookie else None
    return ws_connect(
        f"ws://{base}{path}", origin=None if origin is None else Origin(origin), additional_headers=headers
    )


async def close_code(ws: ClientConnection, timeout: float = 5) -> int:
    """Reads until the server closes the socket, and returns the code it sent."""
    try:
        async with asyncio.timeout(timeout):
            while True:
                await ws.recv()
    except ConnectionClosed as e:
        return e.rcvd.code
