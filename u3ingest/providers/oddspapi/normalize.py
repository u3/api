"""OddsPapi → canonical. Odds payload (WS `odds` channel and REST /fixtures/odds):
  {fixtureId, odds: {bookmaker: {"<fixtureId>:<bookmaker>:<outcomeId>:<playerId>": {outcomeId, playerId, price(decimal), priceAmerican,
   active, marketActive, mainLine, marketId, bookmakerMarketId, bookmakerOutcomeId, changedAt(ms), bookmakerChangedAt(ms), limit,
   meta{back[{price,size,limit}], lay[...]}}}}}
Market semantics come from /markets: {marketId, marketType, period, handicap, playerProp, marketName, outcomes[{outcomeId, outcomeName}]}.
`participantsRotated` on the bookmakers channel means the book lists participants swapped: home/away flip and spread sign flip.
"""
from __future__ import annotations

import time
from typing import Any

from u3ingest.canonical.markets import canon_market_oddspapi, canon_selection
from u3ingest.canonical.models import OrderBookLevel, Quote, decimal_to_american
from u3ingest.mapping.registry import BookRegistry, FixtureRegistry


class MarketDict:
    def __init__(self, markets: list[dict[str, Any]] | None = None) -> None:
        self.by_id: dict[int, dict[str, Any]] = {}
        self.outcome: dict[int, tuple[int, str]] = {}  # outcomeId -> (marketId, outcomeName)
        if markets:
            self.load(markets)

    def load(self, markets: list[dict[str, Any]]) -> None:
        for m in markets:
            if not isinstance(m, dict) or "marketId" not in m:
                continue
            self.by_id[int(m["marketId"])] = m
            for o in m.get("outcomes") or []:
                self.outcome[int(o["outcomeId"])] = (int(m["marketId"]), str(o.get("outcomeName") or ""))


class OddsPapiNormalizer:
    def __init__(self, books: BookRegistry, fixtures: FixtureRegistry, markets: MarketDict) -> None:
        self.books, self.fixtures, self.markets = books, fixtures, markets
        self.rotated: dict[tuple[str, str], bool] = {}  # (fixtureId, bookmaker) -> participantsRotated

    def note_bookmakers(self, fixture_id: str, bookmakers: dict[str, Any]) -> None:
        for bk, info in (bookmakers or {}).items():
            if isinstance(info, dict) and "participantsRotated" in info:
                self.rotated[(fixture_id, bk)] = bool(info.get("participantsRotated"))

    def quotes(self, payload: dict[str, Any], recv_ns: int | None = None, gateway_ts_ms: int | None = None, kind: str = "update") -> tuple[list[Quote], list[OrderBookLevel]]:
        recv = recv_ns or time.time_ns()
        fid = str(payload.get("fixtureId") or "")
        if payload.get("bookmakers"):
            self.note_bookmakers(fid, payload["bookmakers"])
        canon_fx = self.fixtures.canonical_for("oddspapi", fid)
        qs: list[Quote] = []
        obs: list[OrderBookLevel] = []
        for bk, quotes in (payload.get("odds") or {}).items():
            book = self.books.resolve("oddspapi", bk)
            rotated = self.rotated.get((fid, bk), False)
            for odd_id, q in (quotes or {}).items():
                if not isinstance(q, dict):
                    continue
                mid = q.get("marketId")
                m = self.markets.by_id.get(int(mid)) if mid is not None else None
                oid = q.get("outcomeId")
                oname = self.markets.outcome.get(int(oid), (None, ""))[1] if oid is not None else ""
                market, period = canon_market_oddspapi((m or {}).get("marketType"), (m or {}).get("period"), (m or {}).get("marketName"))
                if m is None:
                    market = f"other:oddspapi_market_{mid}"
                line = (m or {}).get("handicap")
                pid = q.get("playerId") or 0
                sel = canon_selection(oname, home=None, away=None, player_id=str(pid) if pid else None)
                if rotated and sel in ("home", "away"):
                    sel = "away" if sel == "home" else "home"
                if market == "spread" and line is not None:
                    line = -float(line) if sel == "away" else float(line)  # /markets handicap is quoted for participant1 (home)
                if market == "team_total" and m:
                    sel = f"team:{'home' if m.get('marketType', '').endswith('team1') else 'away'}:{sel}"
                src = q.get("bookmakerChangedAt") or q.get("changedAt")
                price = q.get("price")
                qs.append(Quote(recv, "oddspapi", book, bk, canon_fx, fid, market, period, sel, line, float(price) if price is not None else None,
                                q.get("priceAmerican") if q.get("priceAmerican") is not None else decimal_to_american(price), q.get("mainLine"),
                                bool(q.get("active", True)) and bool(q.get("marketActive", True)), q.get("limit"), src, gateway_ts_ms or q.get("changedAt"),
                                (m or {}).get("marketName") or str(mid), oname, odd_id, player_id=str(pid) if pid else None, event_kind=kind,
                                extra={"bookmakerMarketId": q.get("bookmakerMarketId"), "bookmakerOutcomeId": q.get("bookmakerOutcomeId")}))
                meta = q.get("meta") or {}
                for side in ("back", "lay"):
                    for i, lvl in enumerate(meta.get(side) or []):
                        if isinstance(lvl, dict) and lvl.get("price") is not None:
                            obs.append(OrderBookLevel(recv, "oddspapi", book, canon_fx, market, period, sel, str(q.get("bookmakerMarketId") or ""), side, i,
                                                      float(lvl["price"]), float(lvl.get("size") or lvl.get("limit") or 0) or None, src, odd_id))
        return qs, obs
