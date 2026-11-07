"""Sliding-window rate limiter (in-memory MVP). For multi-instance deployments back this with
Redis or database counters (see RateLimitCounter in the blueprint)."""
import time
from collections import defaultdict, deque
from threading import Lock


class RateLimiter:
    def __init__(self, clock=time.monotonic):
        self._hits = defaultdict(deque)
        self._lock = Lock()
        self._clock = clock

    def _prune(self, q, window):
        now = self._clock()
        while q and now - q[0] > window:
            q.popleft()

    def allow(self, key: str, limit: int, window: float) -> bool:
        """Record a hit if under the limit. Returns False (and records nothing) when exceeded."""
        with self._lock:
            q = self._hits[key]
            self._prune(q, window)
            if len(q) >= limit:
                return False
            q.append(self._clock())
            return True

    def record(self, key: str, window: float):
        with self._lock:
            q = self._hits[key]
            self._prune(q, window)
            q.append(self._clock())

    def count(self, key: str, window: float) -> int:
        with self._lock:
            q = self._hits[key]
            self._prune(q, window)
            return len(q)

    def reset(self, key: str):
        with self._lock:
            self._hits.pop(key, None)
