"""OpticOdds v3 REST client (see docs/research/opticodds.md).

Auth: X-Api-Key header. Limits (per 15 s, documented / observed on our key): standard 2500 / 8000, historical 10 / 50,
stream connects 250. /fixtures/odds takes at most 5 fixture_id and 5 sportsbook per call; unknown sportsbook ids are
silently ignored. Pagination: `page` + `has_more` (older endpoints still return `total_pages`).
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Sequence
from typing import Any

from u3ingest.providers.base import RestClient
from u3ingest.util import SlidingWindowLimiter

MAX_IDS = 5


def chunks(seq: Sequence[Any], n: int) -> Iterable[Sequence[Any]]:
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


class OpticOddsClient(RestClient):
    def __init__(self, api_key: str, base_url: str = "https://api.opticodds.com/api/v3", *, standard_per_15s: int = 2400,
                 historical_per_15s: int = 10, stream_connects_per_15s: int = 240, user_agent: str = "u3-ingest/0.1") -> None:
        super().__init__(base_url, headers={"X-Api-Key": api_key}, user_agent=user_agent,
                         limiters={"default": SlidingWindowLimiter(standard_per_15s, 15.0),
                                   "historical": SlidingWindowLimiter(historical_per_15s, 15.0),
                                   "stream": SlidingWindowLimiter(stream_connects_per_15s, 15.0)})

    # ---- pagination ----
    async def paginate(self, path: str, params: dict[str, Any] | None = None, *, max_pages: int = 500) -> AsyncIterator[dict[str, Any]]:
        page = 1
        while page <= max_pages:
            r = await self.get(path, {**(params or {}), "page": page})
            for row in r.get("data", []) or []:
                yield row
            has_more = r.get("has_more")
            if has_more is None:
                total = r.get("total_pages") or 1
                has_more = page < total
            if not has_more:
                return
            page += 1

    # ---- metadata ----
    async def sports(self) -> list[dict]:
        return (await self.get("/sports"))["data"]

    async def sports_active(self) -> list[dict]:
        return (await self.get("/sports/active"))["data"]

    async def leagues(self, sport: str | None = None) -> list[dict]:
        return (await self.get("/leagues", {"sport": sport}))["data"]

    async def leagues_active(self, sport: str | None = None) -> list[dict]:
        return (await self.get("/leagues/active", {"sport": sport}))["data"]

    async def sportsbooks(self, active_only: bool = False) -> list[dict]:
        return (await self.get("/sportsbooks/active" if active_only else "/sportsbooks"))["data"]

    async def sportsbooks_last_polled(self, *, league: str | None = None, fixture_ids: Sequence[str] | None = None,
                                      sportsbooks: Sequence[str] | None = None) -> list[dict]:
        return (await self.get("/sportsbooks/last-polled", {"league": league, "fixture_id": fixture_ids, "sportsbook": sportsbooks}))["data"]

    async def markets(self, sport: str | None = None, league: str | None = None) -> list[dict]:
        return (await self.get("/markets", {"sport": sport, "league": league}))["data"]

    async def markets_active(self, fixture_ids: Sequence[str], sportsbooks: Sequence[str]) -> list[dict]:
        return (await self.get("/markets/active", {"fixture_id": fixture_ids, "sportsbook": sportsbooks}))["data"]

    async def market_types(self) -> list[dict]:
        return (await self.get("/market-types"))["data"]

    async def teams(self, league: str, **params: Any) -> AsyncIterator[dict]:
        async for row in self.paginate("/teams", {"league": league, **params}):
            yield row

    async def players(self, league: str, **params: Any) -> AsyncIterator[dict]:
        async for row in self.paginate("/players", {"league": league, **params}):
            yield row

    # ---- fixtures ----
    async def fixtures(self, *, league: str | None = None, sport: str | None = None, fixture_ids: Sequence[str] | None = None,
                       start_date_after: str | None = None, start_date_before: str | None = None, updated_since: str | None = None,
                       include_statsperform_id: bool = True, include_starting_lineups: bool = False) -> AsyncIterator[dict]:
        p = {"league": league, "sport": sport, "id": fixture_ids, "start_date_after": start_date_after, "start_date_before": start_date_before,
             "updated_since": updated_since, "include_statsperform_id": str(include_statsperform_id).lower(),
             "include_starting_lineups": str(include_starting_lineups).lower()}
        async for row in self.paginate("/fixtures", p):
            yield row

    async def fixtures_active(self, *, league: str | None = None, sport: str | None = None, include_statsperform_id: bool = True) -> AsyncIterator[dict]:
        async for row in self.paginate("/fixtures/active", {"league": league, "sport": sport, "include_statsperform_id": str(include_statsperform_id).lower()}):
            yield row

    # ---- odds ----
    async def fixture_odds(self, fixture_ids: Sequence[str], sportsbooks: Sequence[str], *, market: Sequence[str] | None = None,
                           is_main: bool | None = None, exclude_fees: bool | None = None, odds_format: str | None = None) -> list[dict]:
        """Returns fixture rows (each with `odds[]`) for every (≤5 fixtures × ≤5 books) chunk."""
        out: list[dict] = []
        for fx in chunks(list(fixture_ids), MAX_IDS):
            for bk in chunks(list(sportsbooks), MAX_IDS):
                p: dict[str, Any] = {"fixture_id": fx, "sportsbook": bk, "market": market}
                if is_main is not None:
                    p["is_main"] = str(is_main).lower()
                if exclude_fees is not None:
                    p["exclude_fees"] = str(exclude_fees).lower()
                if odds_format:
                    p["odds_format"] = odds_format
                out += (await self.get("/fixtures/odds", p)).get("data", [])
        return out

    async def fixture_odds_historical(self, fixture_id: str, sportsbooks: Sequence[str], *, market: str | None = None,
                                      include_timeseries: bool = False) -> dict:
        p = {"fixture_id": fixture_id, "sportsbook": list(sportsbooks)[:MAX_IDS], "market": market,
             "include_timeseries": str(include_timeseries).lower()}
        return await self.get("/fixtures/odds/historical", p, bucket="historical")

    async def futures(self, *, league: str | None = None, sport: str | None = None) -> list[dict]:
        return (await self.get("/futures", {"league": league, "sport": sport}))["data"]

    async def futures_odds(self, *, league: str, sportsbooks: Sequence[str], future: Sequence[str] | None = None) -> list[dict]:
        out: list[dict] = []
        for bk in chunks(list(sportsbooks), MAX_IDS):
            out += (await self.get("/futures/odds", {"league": league, "sportsbook": bk, "future": future})).get("data", [])
        return out

    async def parlay_odds(self, sportsbook: str, odd_ids: Sequence[str], **extra: Any) -> dict:
        return await self.post("/parlay/odds", {"sportsbook": sportsbook, "odds": list(odd_ids), **extra})

    # ---- results / grading / injuries ----
    async def fixture_results(self, *, fixture_ids: Sequence[str] | None = None, league: str | None = None, **params: Any) -> list[dict]:
        return (await self.get("/fixtures/results", {"fixture_id": fixture_ids, "league": league, **params}))["data"]

    async def fixture_player_results(self, *, fixture_ids: Sequence[str] | None = None, league: str | None = None, **params: Any) -> list[dict]:
        return (await self.get("/fixtures/player-results", {"fixture_id": fixture_ids, "league": league, **params}))["data"]

    async def grader_odds(self, fixture_id: str, market_label: str, selection_name: str, **params: Any) -> dict:
        return await self.get("/grader/odds", {"fixture_id": fixture_id, "market": market_label, "name": selection_name, **params})

    async def injuries(self, *, league: str | None = None, sport: str | None = None) -> list[dict]:
        return (await self.get("/injuries", {"league": league, "sport": sport}))["data"]

    # ---- non-sport prediction markets (Kalshi + Polymarket canonicalised) ----
    async def pm_categories(self) -> list[dict]:
        return (await self.get("/prediction-markets/categories"))["data"]

    async def pm_canonical_event_ids(self, category: str) -> list[str]:
        r = await self.get("/prediction-markets/canonical-events/ids", {"category": category})
        return r["data"] if isinstance(r, dict) else r

    async def pm_canonical_events(self, canonical_ids: Sequence[str]) -> list[dict]:
        out: list[dict] = []
        for ch in chunks(list(canonical_ids), 25):
            r = await self.get("/prediction-markets/canonical-events", {"canonical_id": ch})
            out += r.get("data", []) if isinstance(r, dict) else r
        return out
