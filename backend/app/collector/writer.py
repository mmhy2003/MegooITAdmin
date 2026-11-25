"""Samples on their way to the metrics hypertable: buffered, written in one insert per batch, and kept in memory while
the database is down. The buffer is bounded, so a long outage keeps the newest samples and drops the oldest."""

import asyncio
import logging
from collections import deque
from itertools import chain

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.collector.throttle import Throttle
from app.metrics.samples import Sample
from app.metrics.store import write_samples

logger = logging.getLogger(__name__)

MAX_SAMPLES = 10_000


class Writer:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], *, max_samples: int = MAX_SAMPLES, every: float = 1.0
    ) -> None:
        self.sessions = sessions
        self.max_samples = max_samples
        self.every = every
        self.dropped = 0
        self._buffer: deque[Sample] = deque(maxlen=max_samples)
        self._warn_dropped, self._warn_failed = Throttle(), Throttle()

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
        refused them, which then wait for the next flush."""
        if not self._buffer:
            return 0
        batch, self._buffer = self._buffer, deque(maxlen=self.max_samples)
        try:
            async with self.sessions() as session:
                await write_samples(session, batch)
                await session.commit()
        except (SQLAlchemyError, OSError) as exc:
            # What arrived meanwhile is newer than the batch, so it goes after it, and the oldest overflow.
            overflow = len(batch) + len(self._buffer) - self.max_samples
            self._buffer = deque(chain(batch, self._buffer), maxlen=self.max_samples)
            if overflow > 0:
                self._drop(overflow)
            if self._warn_failed():
                logger.warning("Could not write %d samples, will retry: %s", len(self._buffer), type(exc).__name__)
            return 0
        return len(batch)

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self.every)
            await self.flush()

    def _drop(self, count: int) -> None:
        self.dropped += count
        if self._warn_dropped():
            logger.warning("The sample buffer is full: dropped the oldest, %d so far", self.dropped)
