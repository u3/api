"""OpticOdds SSE streams. Wire format: `event:` / `id:` / `data:` lines, `event: connected` (data "ok go"), `ping` every ~5 s,
then `odds` / `locked-odds` / `fixture-status` (odds stream), `fixture-results`, `futures` / `locked-futures`, prediction
markets `snapshot`. Payload: {"data": [...], "entry_id": "<ms>-<seq>", "type": ...}.

Observed on our key (2026-09-03): `last_entry_id` replay does NOT work (reconnects restart at "now"), so every
reconnect yields a `ReconnectMarker` and the consumer must re-hydrate the affected fixtures via REST.
Each connect counts against the 250/15 s streaming limit; ≤5 sportsbooks per stream.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

from u3ingest.util import SlidingWindowLimiter, loads

log = structlog.get_logger()


@dataclass(slots=True)
class SseEvent:
    event: str
    id: str | None
    data: Any
    raw: str
    recv_ns: int


@dataclass(slots=True)
class ReconnectMarker:
    reason: str
    attempt: int
    gap_s: float
    recv_ns: int = field(default_factory=time.time_ns)


def parse_sse(lines: AsyncIterator[str]) -> AsyncIterator[SseEvent]:
    async def gen() -> AsyncIterator[SseEvent]:
        ev, eid, data = None, None, []
        async for line in lines:
            line = line.rstrip("\r\n")
            if line == "":
                if data or ev:
                    raw = "\n".join(data)
                    try:
                        parsed = loads(raw) if raw and raw[0] in "{[" else raw
                    except ValueError:
                        parsed = raw
                    yield SseEvent(ev or "message", eid, parsed, raw, time.time_ns())
                ev, eid, data = None, None, []
            elif line.startswith(":"):
                continue
            elif line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("id:"):
                eid = line[3:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())
            elif line.startswith("retry:"):
                continue
    return gen()


class OpticOddsSSE:
    def __init__(self, api_key: str, base_url: str = "https://api.opticodds.com/api/v3", *, connects_per_15s: int = 200,
                 idle_timeout: float = 20.0, user_agent: str = "u3-ingest/0.1") -> None:
        self.api_key, self.base_url = api_key, base_url.rstrip("/")
        self.limiter = SlidingWindowLimiter(connects_per_15s, 15.0)
        self.idle_timeout, self.user_agent = idle_timeout, user_agent

    def _url(self, stream: str, sport: str | None) -> str:
        return f"{self.base_url}/stream/{stream}/{sport}" if sport else f"{self.base_url}/stream/{stream}"

    async def events(self, stream: str, sport: str | None = None, *, sportsbooks: Sequence[str] | None = None, leagues: Sequence[str] | None = None,
                     params: dict[str, Any] | None = None) -> AsyncIterator[SseEvent | ReconnectMarker]:
        """stream ∈ {"odds", "results", "futures", "prediction-markets"}; sport required except for prediction-markets."""
        q: list[tuple[str, str]] = [("key", self.api_key)]
        q += [("sportsbook", b) for b in (sportsbooks or [])]
        q += [("league", lg) for lg in (leagues or [])]
        q += [(k, str(v)) for k, v in (params or {}).items()]
        attempt, last_ok = 0, time.monotonic()
        while True:
            await self.limiter.acquire()
            attempt += 1
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10.0, read=self.idle_timeout), headers={"User-Agent": self.user_agent}) as c:
                    async with c.stream("GET", self._url(stream, sport), params=q, headers={"Accept": "text/event-stream"}) as r:
                        if r.status_code != 200:
                            body = (await r.aread())[:300]
                            raise RuntimeError(f"SSE {r.status_code}: {body!r}")
                        if attempt > 1:
                            yield ReconnectMarker("reconnected", attempt, time.monotonic() - last_ok)
                        attempt_ok = 0
                        async for ev in parse_sse(r.aiter_lines()):
                            last_ok = time.monotonic()
                            attempt_ok += 1
                            if attempt_ok == 1:
                                attempt = 1  # healthy stream: reset backoff
                            yield ev
            except (TimeoutError, httpx.TransportError, httpx.ReadTimeout, RuntimeError) as e:
                delay = min(30.0, 1.0 * (2 ** min(attempt, 5)))
                log.warning("sse disconnected", stream=stream, sport=sport, error=str(e)[:200], retry_in=delay)
                await asyncio.sleep(delay)
