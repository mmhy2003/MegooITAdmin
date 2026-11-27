"""One SSH connection per server, shared by the server's running sources: each source is a channel on it.

The first source of a server signs in through open_connection, the others wait for that sign-in, and the connection
closes when the last of them leaves. A failed sign-in reaches every waiting source, and the next source tries again.
At most max_sign_ins sign-ins run at once, so a restart of the worker does not storm the servers."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from uuid import UUID

from app.audit import Actor
from app.inventory.connection import open_connection
from app.inventory.models import Server
from app.ssh.client import Connection

logger = logging.getLogger(__name__)
ACTOR = Actor.system("logs")
MAX_SIGN_INS = 20


class _Link:
    """A server's connection: its holder task, its users, and the connection once signed in."""

    def __init__(self) -> None:
        self.ready: asyncio.Future[Connection] = asyncio.get_running_loop().create_future()
        # A user cancelled while it waits leaves the sign-in's exception unread: read it here, so it is not logged.
        self.ready.add_done_callback(lambda ready: ready.cancelled() or ready.exception())
        self.done = asyncio.Event()  # set by the last user
        self.users = 0
        self.holder: asyncio.Task[None] | None = None


class Links:
    def __init__(self, *, max_sign_ins: int = MAX_SIGN_INS):
        self._sign_ins = asyncio.Semaphore(max_sign_ins)
        self._links: dict[UUID, _Link] = {}
        self._open = 0

    @asynccontextmanager
    async def use(self, server: Server) -> AsyncIterator[Connection]:
        """The server's one connection, opened by its first user through open_connection(server, actor=ACTOR,
        source=None), with at most max_sign_ins sign-ins at once, and closed when its last user leaves. A failed
        sign-in raises ConnectionRefused or an SshFailure to every waiting user, and the next use tries again."""
        link = self._links.get(server.id)
        if link is None:
            link = self._links[server.id] = _Link()
            link.holder = asyncio.create_task(self._hold(server, link))
        link.users += 1
        try:
            yield await asyncio.shield(link.ready)
        finally:
            link.users -= 1
            if link.users == 0:
                self._drop(server.id, link)
                link.done.set()
                with suppress(Exception, asyncio.CancelledError):
                    await asyncio.shield(link.holder)

    def open_count(self) -> int:
        """Connections open now."""
        return self._open

    def _drop(self, server_id: UUID, link: _Link) -> None:
        if self._links.get(server_id) is link:
            del self._links[server_id]

    async def _hold(self, server: Server, link: _Link) -> None:
        """Keeps the connection open from the sign-in until the last user leaves."""
        try:
            async with AsyncExitStack() as stack:
                async with self._sign_ins:  # the sign-in only: an open connection holds no place
                    conn = await stack.enter_async_context(open_connection(server, actor=ACTOR, source=None))
                self._open += 1
                stack.callback(self._closed)
                link.ready.set_result(conn)
                await link.done.wait()
        except asyncio.CancelledError:
            self._drop(server.id, link)
            link.ready.cancel()
            raise
        except Exception as error:
            self._drop(server.id, link)
            if link.ready.done():
                logger.warning("closing the connection to server %s failed: %r", server.id, error)
            else:
                link.ready.set_exception(error)

    def _closed(self) -> None:
        self._open -= 1
