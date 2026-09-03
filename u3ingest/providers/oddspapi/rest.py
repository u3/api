"""OddsPapi v5 REST client (see docs/research/oddspapi.md).

Auth: query `apiKey`. Limits per key: /fixtures/odds, /fixtures/odds/main, /futures/odds → 10 req/s; everything else
200 req/min. A browser-like User-Agent is REQUIRED (python-urllib default UA gets Cloudflare 403 error 1010).
IDs: fixtureId "id{sportId}{tournamentId:06d}{nativeId}", oddsId "{fixtureId}:{bookmaker}:{outcomeId}:{playerId}".
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from u3ingest.providers.base import RestClient
from u3ingest.util import SlidingWindowLimiter


def _csv(v: Sequence[Any] | str | None) -> str | None:
    if v is None:
        return None
    return v if isinstance(v, str) else ",".join(str(x) for x in v)


class OddsPapiClient(RestClient):
    def __init__(self, api_key: str, base_url: str = "https://v5.oddspapi.io/en", *, user_agent: str = "Mozilla/5.0 (compatible; u3-ingest/0.1)") -> None:
        super().__init__(base_url, default_params={"apiKey": api_key}, user_agent=user_agent,
                         limiters={"default": SlidingWindowLimiter(190, 60.0), "odds": SlidingWindowLimiter(9, 1.0)})

    # ---- metadata ----
    async def bookmakers(self, **params: Any) -> list[dict]:
        return await self.get("/bookmakers", params)

    async def sports(self) -> list[dict]:
        return await self.get("/sports")

    async def tournaments(self, sport_id: int | None = None, **params: Any) -> list[dict]:
        return await self.get("/tournaments", {"sportId": sport_id, **params})  # NB: no sportId defaults to sportId=11

    async def seasons(self, **params: Any) -> list[dict]:
        return await self.get("/seasons", params)

    async def participants(self, **params: Any) -> list[dict]:
        return await self.get("/participants", params)

    async def players(self, **params: Any) -> list[dict]:
        return await self.get("/players", params)

    async def markets(self, sport_id: int | None = None, **params: Any) -> list[dict]:
        return await self.get("/markets", {"sportId": sport_id, **params})

    async def currencies(self) -> list[dict]:
        return await self.get("/currencies")

    # ---- fixtures ----
    async def fixtures(self, *, sport_id: int | None = None, tournament_id: int | None = None, fixture_ids: Sequence[str] | None = None,
                       start_time_from: int | None = None, bookmakers: Sequence[str] | None = None, **params: Any) -> list[dict]:
        return await self.get("/fixtures", {"sportId": sport_id, "tournamentId": tournament_id, "fixtureIds": _csv(fixture_ids),
                                             "startTimeFrom": start_time_from, "bookmakers": _csv(bookmakers), **params})

    async def fixtures_today(self, **params: Any) -> list[dict]:
        return await self.get("/fixtures/today", params)

    async def fixtures_live(self, **params: Any) -> list[dict]:
        return await self.get("/fixtures/live", params)

    async def fixture_mapping(self, *, bookmaker: str | None = None, fixture_ids: Sequence[str] | None = None,
                              bookmaker_fixture_ids: Sequence[str] | None = None) -> list[dict]:
        return await self.get("/fixtures/mapping", {"bookmaker": bookmaker, "fixtureIds": _csv(fixture_ids), "bookmakerFixtureIds": _csv(bookmaker_fixture_ids)})

    async def fixture_settlement(self, fixture_id: str, **params: Any) -> Any:
        return await self.get("/fixtures/settlement", {"fixtureId": fixture_id, **params})

    # ---- odds (10 rps bucket) ----
    async def fixture_odds(self, fixture_id: str, *, bookmakers: Sequence[str] | None = None, since_ms: int | None = None, **params: Any) -> dict:
        return await self.get("/fixtures/odds", {"fixtureId": fixture_id, "bookmakers": _csv(bookmakers), "since": since_ms, **params}, bucket="odds")

    async def fixtures_odds_main(self, fixture_ids: Sequence[str], *, bookmakers: Sequence[str] | None = None, since_ms: int | None = None, **params: Any) -> Any:
        return await self.get("/fixtures/odds/main", {"fixtureIds": _csv(fixture_ids), "bookmakers": _csv(bookmakers), "since": since_ms, **params}, bucket="odds")

    async def fixture_odds_clv(self, fixture_id: str, *, bookmakers: Sequence[str] | None = None, odds_ids: Sequence[str] | None = None) -> Any:
        return await self.get("/fixtures/odds/clv", {"fixtureId": fixture_id, "bookmakers": _csv(bookmakers), "oddsIds": _csv(odds_ids)})

    async def fixture_odds_historical(self, fixture_id: str, *, bookmaker: str | None = None, odds_ids: Sequence[str] | None = None) -> Any:
        return await self.get("/fixtures/odds/historical", {"fixtureId": fixture_id, "bookmaker": bookmaker, "oddsIds": _csv(odds_ids)})

    # ---- futures ----
    async def futures(self, **params: Any) -> list[dict]:
        return await self.get("/futures", params)

    async def futures_live(self, **params: Any) -> list[dict]:
        return await self.get("/futures/live", params)

    async def future_odds(self, future_id: str, *, bookmakers: Sequence[str] | None = None, **params: Any) -> Any:
        return await self.get("/futures/odds", {"futureId": future_id, "bookmakers": _csv(bookmakers), **params}, bucket="odds")

    async def future_odds_clv(self, future_id: str, **params: Any) -> Any:
        return await self.get("/futures/odds/clv", {"futureId": future_id, **params})

    async def future_odds_historical(self, future_id: str, **params: Any) -> Any:
        return await self.get("/futures/odds/historical", {"futureId": future_id, **params})

    async def future_mapping(self, **params: Any) -> list[dict]:
        return await self.get("/futures/mapping", params)
