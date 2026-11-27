"""The per-second cap on a source's lines, and the batcher that orders kept lines and skipped counts.

A source that prints faster than the cap loses the lines over it, and the viewer is told how many it lost and where:
a skipped message sits after the last line kept before the gap.
"""

import time
from collections.abc import Callable


class Cap:
    """At most per_second lines in each whole second of the clock."""

    def __init__(self, per_second: int, clock: Callable[[], float] = time.monotonic):
        self._per_second = per_second
        self._clock = clock
        self._second: int | None = None
        self._count = 0

    def admit(self) -> bool:
        second = int(self._clock())
        if second != self._second:
            self._second = second
            self._count = 0
        if self._count >= self._per_second:
            return False
        self._count += 1
        return True


class Batcher:
    """A source's outgoing messages in order: batches of kept lines, and a skipped count at the place of each gap."""

    def __init__(self, max_lines: int = 500):
        self._max_lines = max_lines
        self._messages: list[dict] = []
        self._batch: list[dict] = []
        self._waiting = 0
        self._drops = 0
        self._last_seq = 0

    def keep(self, message: dict) -> None:
        """A line_message, after the drops before it."""
        if self._drops:
            self._close()
        self._batch.append(message)
        self._waiting += 1
        self._last_seq = message["seq"]

    def drop(self) -> None:
        self._drops += 1

    @property
    def full(self) -> bool:
        return self._waiting >= self._max_lines

    def take(self) -> list[dict]:
        """Every message that waits, drops still pending included; [] when nothing waits."""
        self._close()
        messages, self._messages, self._waiting = self._messages, [], 0
        return messages

    def _close(self) -> None:
        if self._batch:
            self._messages.append({"type": "lines", "lines": self._batch})
            self._batch = []
        if self._drops:
            self._messages.append({"type": "skipped", "count": self._drops, "after_seq": self._last_seq})
            self._drops = 0
