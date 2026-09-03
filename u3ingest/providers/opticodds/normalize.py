"""OpticOdds → canonical. Odd fields (REST /fixtures/odds and SSE `odds`/`locked-odds`): id, sportsbook, market, market_id, name,
selection, normalized_selection, selection_line ('over'/'under' on totals), selection_points, points, price (American),
timestamp (float seconds), grouping_key, is_main, is_live, player_id, team_id, limits{max}, order_book [[price,size]], source_ids.
"""
from __future__ import annotations

import time
from typing import Any

from u3ingest.canonical.markets import canon_market_from_name, canon_selection
from u3ingest.canonical.models import OrderBookLevel, Quote, american_to_decimal
from u3ingest.mapping.registry import BookRegistry, FixtureRegistry


class OpticOddsNormalizer:
    def __init__(self, books: BookRegistry, fixtures: FixtureRegistry) -> None:
        self.books, self.fixtures = books, fixtures
        self._fx_ctx: dict[str, dict[str, Any]] = {}  # fixture id -> {home, away, home_id, away_id}

    def remember_fixture(self, f: dict[str, Any]) -> None:
        h = (f.get("home_competitors") or [{}])[0]
        a = (f.get("away_competitors") or [{}])[0]
        self._fx_ctx[f["id"]] = {"home": h.get("name") or f.get("home_team_display"), "away": a.get("name") or f.get("away_team_display"),
                                 "home_id": h.get("id"), "away_id": a.get("id")}
        if f.get("start_date") or f.get("league"):
            self.fixtures.add_opticodds(f)

    def quotes_from_fixture_rows(self, rows: list[dict[str, Any]], recv_ns: int | None = None, kind: str = "snapshot") -> tuple[list[Quote], list[OrderBookLevel]]:
        """REST /fixtures/odds rows: each row is a fixture with `odds[]`."""
        qs: list[Quote] = []
        obs: list[OrderBookLevel] = []
        for row in rows:
            self.remember_fixture(row)
            for od in row.get("odds") or []:
                q, ob = self.quote(od, row["id"], recv_ns, kind)
                qs.append(q)
                obs += ob
        return qs, obs

    def quotes_from_sse(self, event: str, data: dict[str, Any], recv_ns: int) -> tuple[list[Quote], list[OrderBookLevel]]:
        kind = "lock" if event == "locked-odds" else "update"
        qs: list[Quote] = []
        obs: list[OrderBookLevel] = []
        for od in (data.get("data") if isinstance(data, dict) else data) or []:
            fid = od.get("fixture_id")
            if not fid:  # stream odds may only carry game_id (first segment of the odd id): resolve via the registry
                gid = od.get("game_id") or (od.get("id") or "").split(":")[0]
                fid = self.fixtures.by_game_id.get(gid) or gid
            q, ob = self.quote(od, fid, recv_ns, kind)
            qs.append(q)
            obs += ob
        return qs, obs

    def quote(self, od: dict[str, Any], fixture_id: str, recv_ns: int | None, kind: str) -> tuple[Quote, list[OrderBookLevel]]:
        recv = recv_ns or time.time_ns()
        ctx = self._fx_ctx.get(fixture_id, {})
        market, period = canon_market_from_name(od.get("market") or od.get("market_id") or "")
        line = od.get("points")
        sel_raw = od.get("selection") or od.get("name") or ""
        if od.get("selection_line") in ("over", "under"):
            sel = od["selection_line"]
            if od.get("player_id"):
                sel = f"player:{od['player_id']}:{sel}"
            elif market.startswith("team_total") and od.get("team_id"):
                sel = f"team:{od['team_id']}:{sel}"
        else:
            sel = canon_selection(sel_raw, home=ctx.get("home"), away=ctx.get("away"), home_id=ctx.get("home_id"), away_id=ctx.get("away_id"),
                                  team_id=od.get("team_id"), player_id=od.get("player_id"))
        ts = od.get("timestamp")
        src_ms = int(float(ts) * 1000) if ts else None
        book = self.books.resolve("opticodds", od.get("sportsbook") or "")
        canon_fx = self.fixtures.canonical_for("opticodds", fixture_id)
        limits = od.get("limits") or {}
        q = Quote(recv, "opticodds", book, od.get("sportsbook") or "", canon_fx, fixture_id, market, period, sel, line,
                  american_to_decimal(od.get("price")), int(od["price"]) if od.get("price") is not None else None, od.get("is_main"),
                  kind != "lock", limits.get("max") or limits.get("max_stake"), src_ms, None, od.get("market") or "", sel_raw, od.get("id") or "",
                  player_id=od.get("player_id"), team_id=od.get("team_id"), event_kind=kind, grouping_key=od.get("grouping_key"),
                  extra={"is_live": od.get("is_live"), "source_ids": od.get("source_ids")} if od.get("source_ids") else {})
        obs: list[OrderBookLevel] = []
        for i, lvl in enumerate(od.get("order_book") or []):
            if isinstance(lvl, (list, tuple)) and len(lvl) >= 2:
                obs.append(OrderBookLevel(recv, "opticodds", book, canon_fx, market, period, sel, str((od.get("source_ids") or {}).get("market_id") or ""),
                                          "back", i, float(lvl[0]), float(lvl[1]), src_ms, od.get("id") or ""))
        return q, obs

    @staticmethod
    def pm_snapshot_levels(data: dict[str, Any], recv_ns: int) -> list[OrderBookLevel]:
        """/stream/prediction-markets `snapshot`: market_id "<platform>:<source_market_id>", outcomes.{yes,no}.{bids[],asks[]}."""
        out: list[OrderBookLevel] = []
        mid = str(data.get("market_id") or "")
        platform = mid.split(":", 1)[0] if ":" in mid else "pm"
        ts = data.get("timestamp_ns")
        src_ms = int(ts) // 1_000_000 if isinstance(ts, (int, float)) and ts > 1e15 else None
        canon = str(data.get("canonical_id") or "") or f"pm:{mid}"
        for outcome in ("yes", "no"):
            o = (data.get("outcomes") or {}).get(outcome) or {}
            for side in ("bids", "asks"):
                for i, lvl in enumerate(o.get(side) or []):
                    p, s = (lvl.get("price"), lvl.get("size")) if isinstance(lvl, dict) else (lvl[0], lvl[1] if len(lvl) > 1 else None)
                    out.append(OrderBookLevel(recv_ns, "opticodds", platform, canon, "pm", "full", outcome, mid, side[:-1], i, float(p), float(s) if s is not None else None, src_ms))
        return out
