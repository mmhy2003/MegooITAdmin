"""Rate limiting for log lines."""

import time
from collections.abc import Callable


class Throttle:
    """True at most once per `every` seconds: for warnings that would otherwise repeat on every sample."""

    def __init__(self, every: float = 60.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.every = every
        self._clock = clock
        self._last: float | None = None

    def __call__(self) -> bool:
        now = self._clock()
        if self._last is not None and now - self._last < self.every:
            return False
        self._last = now
        return True
