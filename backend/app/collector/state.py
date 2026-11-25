"""server_status as the collector keeps it: the last state of each server in memory, and a row written only when the
state or the reason changes. A write the database refused waits until retry()."""

import logging
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.collector.throttle import Throttle
from app.inventory.models import ServerStatus

logger = logging.getLogger(__name__)

State = Literal["reachable", "unreachable", "not_monitored"]
FOREIGN_KEY_VIOLATION = "23503"


class StatusBook:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions
        self._known: dict[UUID, tuple[str, str | None]] = {}
        self._pending: dict[UUID, tuple[str, str | None, datetime | None]] = {}
        self._warn = Throttle()

    async def load(self) -> None:
        """Reads every row into memory, so a restart writes nothing that did not change. Raises on a database error."""
        async with self.sessions() as session:
            rows = select(ServerStatus.server_id, ServerStatus.state, ServerStatus.reason)
            found = (await session.execute(rows)).all()
        self._known = {server_id: (state, reason) for server_id, state, reason in found}

    def known(self, server_id: UUID) -> tuple[str, str | None] | None:
        return self._known.get(server_id)

    def known_ids(self) -> set[UUID]:
        return set(self._known)

    def forget(self, server_id: UUID) -> None:
        self._known.pop(server_id, None)
        self._pending.pop(server_id, None)

    async def set(
        self, server_id: UUID, state: State, reason: str | None = None, *, last_sample_at: datetime | None = None
    ) -> None:
        """Writes the state when it differs from the last one. Never raises."""
        value = (state, reason)
        pending = self._pending.get(server_id)
        if pending is not None and pending[:2] == value:
            return
        if self._known.get(server_id) == value:
            # Back to what is written: a change that was waiting is no longer true.
            self._pending.pop(server_id, None)
            return
        self._pending[server_id] = (state, reason, last_sample_at)
        await self._write(server_id)

    async def retry(self) -> None:
        """Writes what set() could not."""
        for server_id in list(self._pending):
            await self._write(server_id)

    async def _write(self, server_id: UUID) -> None:
        written = self._pending[server_id]
        state, reason, last_sample_at = written
        values = insert(ServerStatus).values(
            server_id=server_id, state=state, reason=reason, since=func.now(), last_sample_at=last_sample_at
        )
        upsert = values.on_conflict_do_update(
            index_elements=["server_id"],
            set_={
                "state": values.excluded.state,
                "reason": values.excluded.reason,
                "since": func.now(),
                "last_sample_at": values.excluded.last_sample_at,
            },
            where=or_(
                ServerStatus.state != values.excluded.state,
                ServerStatus.reason.is_distinct_from(values.excluded.reason),
            ),
        )
        try:
            async with self.sessions() as session:
                await session.execute(upsert)
                await session.commit()
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == FOREIGN_KEY_VIOLATION:
                # The server was removed since the collector read it.
                self.forget(server_id)
                return
            self._keep_pending(exc)
            return
        except (SQLAlchemyError, OSError) as exc:
            self._keep_pending(exc)
            return
        self._known[server_id] = (state, reason)
        if self._pending.get(server_id) == written:  # unless a newer set() came in meanwhile
            del self._pending[server_id]

    def _keep_pending(self, exc: Exception) -> None:
        if self._warn():
            logger.warning("Could not write server_status, will retry: %s", type(exc).__name__)
