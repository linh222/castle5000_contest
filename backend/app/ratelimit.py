from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimiter:
    """Fixed-window-ish rate limiter, per user per endpoint, in memory."""

    def __init__(self, limit_per_min: int):
        self._limit = limit_per_min
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.time()
        window_start = now - 60
        hits = self._hits[key]
        while hits and hits[0] < window_start:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        return True
