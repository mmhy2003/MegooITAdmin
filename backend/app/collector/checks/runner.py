"""Running the slow checks of a server, and recording what each run found."""

import logging
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.checks.models import Kind
from app.checks.store import replace_containers, write_check
from app.collector.checks.parse import ContainersResult, Outcome
from app.collector.state import FOREIGN_KEY_VIOLATION
from app.collector.throttle import Throttle
from app.collector.writer import Writer
from app.metrics.samples import Sample

if TYPE_CHECKING:
    from app.collector.stream import Publisher

logger = logging.getLogger(__name__)


class Recorder:
    """Writes a check's row (and a listing's containers) and sends its numbers as metrics. Never raises."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], publisher: "Publisher", writer: Writer) -> None:
        self.sessions, self.publisher, self.writer = sessions, publisher, writer
        self._warn = Throttle()

    async def record(self, server_id: UUID, kind: Kind, outcome: Outcome, at: datetime) -> None:
        result = outcome.result if outcome.status == "ok" else None
        await self._write(server_id, kind, outcome, at)
        if result is None:
            return
        readings = result.readings(at)
        if readings:
            # The writer keeps its own buffer, so the numbers go even when the row could not be written.
            sample = Sample(time=at, server_id=server_id, readings=readings)
            await self.publisher.publish(sample)
            self.writer.add(sample)

    async def _write(self, server_id: UUID, kind: Kind, outcome: Outcome, at: datetime) -> None:
        result = outcome.result if outcome.status == "ok" else None
        try:
            async with self.sessions() as session:
                data = result.data() if result is not None else None
                await write_check(session, server_id, kind, outcome.status, checked_at=at, data=data)
                if kind == "containers" and isinstance(result, ContainersResult):
                    # A failed listing leaves the containers as they were last seen.
                    await replace_containers(session, server_id, result.containers, seen_at=at)
                await session.commit()
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == FOREIGN_KEY_VIOLATION:
                return  # the server was removed since the collector read it
            self._warn_failed(server_id, exc)
        except (SQLAlchemyError, OSError) as exc:
            # No retry queue: the next run writes the row again.
            self._warn_failed(server_id, exc)

    def _warn_failed(self, server_id: UUID, exc: Exception) -> None:
        if self._warn():
            logger.warning(
                "Could not write a check result of server %s, it is written again at its next run: %s",
                server_id,
                type(exc).__name__,
            )
