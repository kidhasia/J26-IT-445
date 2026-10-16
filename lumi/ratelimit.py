"""In-memory sliding-window rate limiter, one window per client_id.

Good enough for a single-process prototype. It resets on restart and is not shared
between server processes; a multi-process deployment would need Redis or similar.
"""

import math
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

from lumi.errors import LumiError
from lumi.schemas import ErrorCode


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self._max_requests = max_requests
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, client_id: str) -> None:
        now = self._clock()
        with self._lock:
            hits = self._hits[client_id]
            while hits and hits[0] <= now - self._window:
                hits.popleft()
            if len(hits) >= self._max_requests:
                retry_after = max(1, math.ceil(hits[0] + self._window - now))
                raise LumiError(
                    429,
                    ErrorCode.RATE_LIMITED,
                    f"Rate limit of {self._max_requests} requests per {self._window:g} seconds exceeded.",
                    headers={"Retry-After": str(retry_after)},
                )
            hits.append(now)
