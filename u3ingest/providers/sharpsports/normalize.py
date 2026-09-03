"""SharpSports /prices → canonical. Shape: {eventId, markets[{id, name, marketOffers[{id, player{id,...}|null, team{id,...}|null,
marketSelections[{id, position, positionId (TEAM_/PLYR_), books[{id, abbr, name, prices[{line, odds(American), impliedProbability,
main, live, ...}]}]}]}]}]}. No server timestamp exists: quotes are stamped at receive time (source_ts_ms = None).
"""
from __future__ import annotations

import time
from typing import Any

from u3ingest.canonical.markets import canon_market_from_name, canon_selection
from u3ingest.canonical.models import Quote, american_to_decimal
from u3ingest.mapping.registry import BookRegistry, FixtureRegistry


class SharpSportsNormalizer:
    def __init__(self, books: BookRegistry, fixtures: FixtureRegistry) -> None:
        self.books, self.fixtures = books, fixtures
        self._ev_ctx: dict[str, dict[str, Any]] = {}

    def remember_event(self, e: dict[str, Any], league_key: str | None = None) -> None:
        self._ev_ctx[e["id"]] = {"home": (e.get("contestantHome") or {}).get("fullName"), "away": (e.get("contestantAway") or {}).get("fullName"),
                                 "home_id": (e.get("contestantHome") or {}).get("id"), "away_id": (e.get("contestantAway") or {}).get("id")}
        self.fixtures.add_sharpsports(e, league_key)

    def quotes(self, prices: dict[str, Any], recv_ns: int | None = None) -> list[Quote]:
        recv = recv_ns or time.time_ns()
        eid = str(prices.get("eventId") or "")
        ctx = self._ev_ctx.get(eid, {})
        canon_fx = self.fixtures.canonical_for("sharpsports", eid)
        out: list[Quote] = []
        for mk in prices.get("markets") or []:
            market, period = canon_market_from_name(mk.get("name") or "")
            for offer in mk.get("marketOffers") or []:
                player = (offer.get("player") or {}).get("id")
                team = (offer.get("team") or {}).get("id")
                for sel in offer.get("marketSelections") or []:
                    pos = sel.get("position") or ""
                    pos_id = sel.get("positionId") or ""
                    key = canon_selection(pos, home=ctx.get("home"), away=ctx.get("away"), home_id=ctx.get("home_id"), away_id=ctx.get("away_id"),
                                          team_id=pos_id if pos_id.startswith("TEAM_") else None, player_id=player)
                    if team and key in ("over", "under"):
                        key = f"team:{team}:{key}"
                    for bk in sel.get("books") or []:
                        book = self.books.resolve("sharpsports", bk.get("abbr") or bk.get("name") or "")
                        for p in bk.get("prices") or []:
                            out.append(Quote(recv, "sharpsports", book, bk.get("abbr") or bk.get("name") or "", canon_fx, eid, market, period, key, p.get("line"),
                                             american_to_decimal(p.get("odds")), int(p["odds"]) if p.get("odds") is not None else None, p.get("main"), True, None,
                                             None, None, mk.get("name") or "", pos, f"{sel.get('id')}|{bk.get('abbr')}|{p.get('line')}", player_id=player, team_id=team,
                                             event_kind="snapshot", extra={"live": p.get("live"), "implied": p.get("impliedProbability"), "market_selection_id": sel.get("id")}))
        return out
