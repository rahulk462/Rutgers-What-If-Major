"""A tiny rate limiter so we never hammer Rutgers servers."""

from __future__ import annotations

import random
import time

from . import config


class Throttle:
    """Ensures at least a random 1-2 s gap between consecutive calls to ``wait``."""

    def __init__(self, min_delay: float | None = None, max_delay: float | None = None,
                 sleep=time.sleep, clock=time.monotonic):
        self.min_delay = config.MIN_DELAY if min_delay is None else min_delay
        self.max_delay = config.MAX_DELAY if max_delay is None else max_delay
        if self.max_delay < self.min_delay:
            self.max_delay = self.min_delay
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None

    def wait(self) -> float:
        """Sleep if needed; returns the seconds slept."""
        slept = 0.0
        if self._last is not None:
            gap = random.uniform(self.min_delay, self.max_delay)
            elapsed = self._clock() - self._last
            if elapsed < gap:
                slept = gap - elapsed
                self._sleep(slept)
        self._last = self._clock()
        return slept
