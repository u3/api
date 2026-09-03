from __future__ import annotations

import asyncio
import gzip
import os
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import orjson
import structlog

log = structlog.get_logger()
T = TypeVar("T")


def now_ns() -> int:
    return time.time_ns()


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def dumps(obj: Any) -> bytes:
    return orjson.dumps(obj, option=orjson.OPT_SERIALIZE_NUMPY)


def loads(b: bytes | str) -> Any:
    return orjson.loads(b)


class SlidingWindowLimiter:
    """Async sliding-window rate limiter: at most `limit` acquisitions per `window` seconds.

    Provider limits we honour (documented / observed):
      OpticOdds  standard 2500 (observed 8000) / 15 s, streaming connects 250 / 15 s, historical 10 (observed 50) / 15 s
      OddsPapi   odds endpoints 10 / 1 s, everything else 200 / 60 s (per apiKey)
      SharpSports general 50 / 1 s, large-list 20 / 1 s
    """

    def __init__(self, limit: int, window: float) -> None:
        self.limit, self.window = limit, window
        self._hits: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                while self._hits and now - self._hits[0] >= self.window:
                    self._hits.popleft()
                if len(self._hits) < self.limit:
                    self._hits.append(now)
                    return
                await asyncio.sleep(self._hits[0] + self.window - now + 0.001)


async def retry(fn: Callable[[], Awaitable[T]], *, attempts: int = 5, base: float = 0.5, max_delay: float = 30.0,
                retry_on: tuple[type[BaseException], ...] = (Exception,), what: str = "call") -> T:
    delay = base
    for i in range(attempts):
        try:
            return await fn()
        except retry_on as e:  # noqa: PERF203
            if i == attempts - 1:
                raise
            log.warning("retrying", what=what, attempt=i + 1, error=str(e)[:200], delay=delay)
            await asyncio.sleep(delay)
            delay = min(max_delay, delay * 2)
    raise RuntimeError("unreachable")


def gz_open_append(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return gzip.open(path, "ab", compresslevel=3)
