"""Samples on their way to the metrics hypertable: buffered, written in one insert per batch, and kept in memory while
the database is down. The buffer is bounded, so a long outage keeps the newest samples and drops the oldest. A batch the
database refuses for its data is written again sample by sample, so one bad sample cannot hold back the others."""

import asyncio
import logging
from collections import deque
from itertools import chain

from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.collector.throttle import Throttle
from app.metrics.samples import Sample
from app.metrics.store import write_samples

logger = logging.getLogger(__name__)

MAX_SAMPLES = 10_000


def refused(error: DBAPIError) -> bool:
    """Whether the database refused the data itself (SQLSTATE class 22 or 23), so that writing it again fails again.
    asyncpg's errors mostly arrive as a bare DBAPIError, so the class is read from the code, not the type."""
    return (getattr(error.orig, "sqlstate", None) or "")[:2] in {"22", "23"}


class Writer:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], *, max_samples: int = MAX_SAMPLES, every: float = 1.0
    ) -> None:
        self.sessions = sessions
        self.max_samples = max_samples
        self.every = every
        self.dropped = 0
        self.refused = 0  # samples the database refused, never retried
        self._buffer: deque[Sample] = deque(maxlen=max_samples)
        self._warn_dropped, self._warn_failed, self._warn_refused = Throttle(), Throttle(), Throttle()

    @property
    def pending(self) -> int:
        return len(self._buffer)

    def add(self, sample: Sample) -> None:
        """Buffers the sample. Never blocks: a full buffer drops its oldest sample."""
        if len(self._buffer) == self.max_samples:
            self._drop(1)
        self._buffer.append(sample)

    async def flush(self) -> int:
        """Writes everything buffered in one insert and one commit. Returns the samples written: 0 when the database
        could not be reached, and the batch then waits for the next flush. A cancelled flush puts its batch back too:
        a sample written twice is ignored, so the final flush may write it again."""
        if not self._buffer:
            return 0
        batch, self._buffer = self._buffer, deque(maxlen=self.max_samples)
        try:
            try:
                return await self._write(batch)
            except DBAPIError as error:
                if not refused(error):
                    raise
                return await self._write_each(batch)
        except (SQLAlchemyError, OSError) as exc:
            self._put_back(batch)
            if self._warn_failed():
                logger.warning("Could not write %d samples, will retry: %s", len(self._buffer), type(exc).__name__)
            return 0
        except asyncio.CancelledError:
            self._put_back(batch)
            raise

    async def _write(self, batch: deque[Sample]) -> int:
        async with self.sessions() as session:
            await write_samples(session, batch)
            await session.commit()
        return len(batch)

    async def _write_each(self, batch: deque[Sample]) -> int:
        """Writes the batch one sample per savepoint, in one commit, and drops the samples the database refuses."""
        written = 0
        async with self.sessions() as session:
            for sample in batch:
                try:
                    async with session.begin_nested():
                        await write_samples(session, [sample])
                except DBAPIError as error:
                    if not refused(error):
                        raise
                    self.refused += 1
                    if self._warn_refused():
                        logger.warning(
                            "The database refused a sample of server %s, dropped it (%d so far): %s",
                            sample.server_id,
                            self.refused,
                            type(error.orig).__name__,
                        )
                    continue
                written += 1
            await session.commit()
        return written

    def _put_back(self, batch: deque[Sample]) -> None:
        # What arrived meanwhile is newer than the batch, so it goes after it, and the oldest overflow.
        overflow = len(batch) + len(self._buffer) - self.max_samples
        self._buffer = deque(chain(batch, self._buffer), maxlen=self.max_samples)
        if overflow > 0:
            self._drop(overflow)

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self.every)
            await self.flush()

    def _drop(self, count: int) -> None:
        self.dropped += count
        if self._warn_dropped():
            logger.warning("The sample buffer is full: dropped the oldest, %d so far", self.dropped)
