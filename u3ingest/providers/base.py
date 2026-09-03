from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
import structlog

from u3ingest.util import SlidingWindowLimiter, loads, retry

log = structlog.get_logger()


class RestError(RuntimeError):
    def __init__(self, status: int, body: str, url: str) -> None:
        super().__init__(f"HTTP {status} for {url}: {body[:300]}")
        self.status, self.body, self.url = status, body, url


class RetryableRestError(RestError):
    pass


class RestClient:
    """httpx-based client with per-bucket sliding-window limiters, retries on 429/5xx, and rate-limit header capture."""

    def __init__(self, base_url: str, *, headers: Mapping[str, str] | None = None, default_params: Mapping[str, str] | None = None,
                 limiters: Mapping[str, SlidingWindowLimiter] | None = None, timeout: float = 30.0, user_agent: str = "u3-ingest/0.1") -> None:
        self.base_url = base_url.rstrip("/")
        self.default_params = dict(default_params or {})
        self.limiters = dict(limiters or {})
        self._client = httpx.AsyncClient(base_url=self.base_url, headers={"User-Agent": user_agent, "Accept": "application/json", **(headers or {})},
                                         timeout=httpx.Timeout(timeout, connect=10.0), http2=False)
        self.last_headers: dict[str, str] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(self, path: str, params: Mapping[str, Any] | None = None, *, bucket: str = "default", attempts: int = 4) -> Any:
        return await self.request("GET", path, params=params, bucket=bucket, attempts=attempts)

    async def post(self, path: str, json: Any, params: Mapping[str, Any] | None = None, *, bucket: str = "default", attempts: int = 3) -> Any:
        return await self.request("POST", path, params=params, json=json, bucket=bucket, attempts=attempts)

    async def request(self, method: str, path: str, *, params: Mapping[str, Any] | None = None, json: Any = None, bucket: str = "default",
                      attempts: int = 4) -> Any:
        limiter = self.limiters.get(bucket) or self.limiters.get("default")
        q: list[tuple[str, Any]] = list(self.default_params.items())
        for k, v in (params or {}).items():
            if v is None:
                continue
            if isinstance(v, (list, tuple, set)):
                q += [(k, x) for x in v]  # repeated keys (OpticOdds style: sportsbook=a&sportsbook=b)
            else:
                q.append((k, v))

        async def once() -> Any:
            if limiter:
                await limiter.acquire()
            r = await self._client.request(method, path, params=q, json=json)
            self.last_headers = {k.lower(): v for k, v in r.headers.items() if k.lower().startswith(("x-ratelimit", "ratelimit", "retry-after"))}
            if r.status_code == 429 or r.status_code >= 500:
                raise RetryableRestError(r.status_code, r.text, str(r.url))
            if r.status_code >= 400:
                raise RestError(r.status_code, r.text, str(r.url))
            return loads(r.content) if r.content else None

        return await retry(once, attempts=attempts, retry_on=(RetryableRestError, httpx.TransportError), what=f"{method} {path}")
