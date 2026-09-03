"""SharpSports REST client (see docs/research/sharpsports.md).

Auth: `Authorization: Token <key>`. The PRIVATE key is required for /events, /prices, marketSelections/historicData and
players/historicData (public key → 403 "Your private API key is required"). Limits: 50 req/s general, 20 req/s on
large-list endpoints (betSlips lists, marketSelections list, bookRegions list); 429 body {"detail":"Request was throttled."}.
Prices carry no server timestamp: stamp them at receive time. IDs: EVNT_/MKT_/MKTO_/MRKT_/BOOK_/TEAM_/PLYR_ prefixes.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from u3ingest.providers.base import RestClient
from u3ingest.util import SlidingWindowLimiter


class SharpSportsClient(RestClient):
    LARGE_LIST = {"/betSlips", "/marketSelections", "/bookRegions"}

    def __init__(self, token: str, base_url: str = "https://api.sharpsports.io/v1", *, user_agent: str = "u3-ingest/0.1") -> None:
        super().__init__(base_url, headers={"Authorization": f"Token {token}"}, user_agent=user_agent,
                         limiters={"default": SlidingWindowLimiter(45, 1.0), "large": SlidingWindowLimiter(18, 1.0)})

    async def get(self, path: str, params: Any = None, *, bucket: str | None = None, attempts: int = 4) -> Any:  # type: ignore[override]
        b = bucket or ("large" if any(path.startswith(p) for p in self.LARGE_LIST) else "default")
        return await super().get(path, params, bucket=b, attempts=attempts)

    # ---- reference ----
    async def books(self, **params: Any) -> list[dict]:
        return await self.get("/books", params)

    async def book_regions(self, **params: Any) -> list[dict]:
        return await self.get("/bookRegions", params)

    async def sports(self) -> list[dict]:
        return await self.get("/sports")

    async def leagues(self, **params: Any) -> list[dict]:
        return await self.get("/leagues", params)

    async def teams(self, league: str | None = None, **params: Any) -> list[dict]:
        return await self.get("/teams", {"league": league, **params})

    async def players(self, league: str | None = None, **params: Any) -> list[dict]:
        return await self.get("/players", {"league": league, **params})

    async def markets(self, *, league: str | None = None, name: str | None = None, the_odds_api_id: str | None = None, **params: Any) -> list[dict]:
        return await self.get("/markets", {"league": league, "name": name, "theOddsApiId": the_odds_api_id, **params})

    async def segments(self) -> Any:
        return await self.get("/segments")

    async def metrics(self) -> Any:
        return await self.get("/metrics")

    # ---- events / selections / prices (private key) ----
    async def events(self, *, league: str | None = None, start_time_start: str | None = None, start_time_end: str | None = None,
                     upcoming: bool | None = None, **params: Any) -> list[dict]:
        p = {"league": league, "startTimeStart": start_time_start, "startTimeEnd": start_time_end, **params}
        if upcoming is not None:
            p["upcoming"] = str(upcoming).lower()
        return await self.get("/events", p)

    async def event(self, event_id: str) -> dict:
        return await self.get(f"/events/{event_id}")

    async def market_offers(self, *, event_id: str | None = None, market: str | None = None, **params: Any) -> list[dict]:
        return await self.get("/marketOffers", {"eventId": event_id, "market": market, **params})

    async def market_selections(self, *, event_id: str | None = None, market: str | None = None, prices: bool = False,
                                line_availability: bool = False, limit: int | None = None, **params: Any) -> list[dict]:
        p = {"eventId": event_id, "market": market, "prices": str(prices).lower(), "lineAvailability": str(line_availability).lower(), "limit": limit, **params}
        return await self.get("/marketSelections", p)

    async def prices(self, *, event_id: str | None = None, league: str | None = None, sport: str | None = None, market_id: str | None = None,
                     book: Sequence[str] | str | None = None, **params: Any) -> Any:
        b = ",".join(book) if isinstance(book, (list, tuple)) else book
        return await self.get("/prices", {"eventId": event_id, "league": league, "sport": sport, "marketId": market_id, "book": b, **params})

    async def prices_historic_summary(self, **params: Any) -> Any:
        return await self.get("/prices/historic/summary", params)

    async def prices_historic_timeseries(self, *, market_selection_id: str, timeseries_start: str | None = None, timeseries_end: str | None = None,
                                         rollup: str = "1h", **params: Any) -> Any:
        return await self.get("/prices/historic/timeseries", {"marketSelectionId": market_selection_id, "timeseriesStart": timeseries_start,
                                                              "timeseriesEnd": timeseries_end, "rollup": rollup, **params})

    # ---- historicData / metadata ----
    async def selection_historic_data(self, market_selection_id: str, *, line: float | None = None, games_back: int | None = None, **params: Any) -> Any:
        return await self.get(f"/marketSelections/{market_selection_id}/historicData", {"line": line, "gamesBack": games_back, **params})

    async def selection_metadata(self, market_selection_id: str, *, line: float | None = None, **params: Any) -> Any:
        return await self.get(f"/marketSelections/{market_selection_id}/metadata", {"line": line, **params})

    async def player_historic_data(self, player_id: str) -> list[dict]:
        return await self.get(f"/players/{player_id}/historicData")

    async def player_aggregate_stats(self, **params: Any) -> Any:
        return await self.get("/players/aggregateStats", params)

    async def team_aggregate_stats(self, **params: Any) -> Any:
        return await self.get("/teams/aggregateStats", params)

    async def injuries(self, **params: Any) -> Any:
        return await self.get("/injuries", params)

    async def trends(self, **params: Any) -> Any:
        return await self.get("/trends", params)

    async def trades(self, **params: Any) -> Any:
        return await self.get("/trades", params)

    # ---- bet sync (public flow data from linked bettors) ----
    async def bet_slips(self, **params: Any) -> list[dict]:
        return await self.get("/betSlips", params)
