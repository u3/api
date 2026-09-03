from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from u3ingest.canonical.models import Quote

from .consensus import ConsensusConfig, FairValue, fair_value


@dataclass(slots=True)
class Edge:
    book_id: str
    outcome: str
    offered_decimal: float
    fair_probability: float
    expected_value: float
    stale: bool


class Board:
    def __init__(self, *, max_age_ms: int = 0) -> None:
        self.max_age_ms = max_age_ms
        self._latest: dict[tuple[str, str, str, float | None, str, str], dict[str, Any]] = {}

    def ingest(self, quote: Quote | dict[str, Any]) -> None:
        q = quote.row() if isinstance(quote, Quote) else quote
        key = (q["fixture_id"], q["market"], q["period"], q.get("line"), q["selection"], q["book_id"])
        cur = self._latest.get(key)
        recv_ns = int(q.get("recv_ns") or 0)
        if cur is not None and recv_ns < int(cur.get("recv_ns") or 0):
            return
        if not q.get("active", True):
            self._latest.pop(key, None)
            return
        self._latest[key] = q

    def _group(
        self,
        fixture_id: str,
        market: str,
        period: str,
        line: float | None,
    ) -> dict[str, dict[str, dict[str, Any]]]:
        out: dict[str, dict[str, dict[str, Any]]] = {}
        for (fx, mk, per, ln, sel, book), q in self._latest.items():
            if (fx, mk, per, ln) != (fixture_id, market, period, line):
                continue
            if q.get("price_dec") is None:
                continue
            out.setdefault(book, {})[sel] = q
        return out

    @staticmethod
    def _selection_kind(selection: str) -> str:
        if selection.endswith(":over"):
            return "over"
        if selection.endswith(":under"):
            return "under"
        return selection

    def _outcome_order(self, market: str, grouped: dict[str, dict[str, dict[str, Any]]]) -> list[str]:
        _ = market
        selections = {self._selection_kind(sel): sel for quotes in grouped.values() for sel in quotes}

        if "home" in selections and "away" in selections and "draw" in selections:
            return ["home", "away", "draw"]
        if "home" in selections and "away" in selections:
            return ["home", "away"]
        if "over" in selections and "under" in selections:
            return ["over", "under"]
        if "yes" in selections and "no" in selections:
            return ["yes", "no"]
        return []

    def market_prices(self, fixture_id: str, market: str, period: str, line: float | None) -> dict[str, list[float]]:
        grouped = self._group(fixture_id, market, period, line)
        order = self._outcome_order(market, grouped)
        if not order:
            return {}

        out: dict[str, list[float]] = {}
        for book, sel_map in grouped.items():
            by_kind = {self._selection_kind(sel): q for sel, q in sel_map.items()}
            if any(kind not in by_kind for kind in order):
                continue
            out[book] = [float(by_kind[k]["price_dec"]) for k in order]
        return out

    def fair(self, fixture_id: str, market: str, period: str, line: float | None, cfg: ConsensusConfig) -> FairValue | None:
        return fair_value(self.market_prices(fixture_id, market, period, line), cfg)

    def edges(self, fixture_id: str, market: str, period: str, line: float | None, cfg: ConsensusConfig) -> list[Edge]:
        grouped = self._group(fixture_id, market, period, line)
        order = self._outcome_order(market, grouped)
        if not order:
            return []
        fv = fair_value(self.market_prices(fixture_id, market, period, line), cfg)
        if fv is None:
            return []

        now_ns = time.time_ns()
        edges: list[Edge] = []
        for book, sel_map in grouped.items():
            by_kind = {self._selection_kind(sel): (sel, q) for sel, q in sel_map.items()}
            for idx, kind in enumerate(order):
                if kind not in by_kind:
                    continue
                selection, q = by_kind[kind]
                price = float(q["price_dec"])
                p = fv.probabilities[idx]
                age_ms = max(0.0, (now_ns - int(q.get("recv_ns") or 0)) / 1_000_000)
                stale = self.max_age_ms > 0 and age_ms > self.max_age_ms
                edges.append(
                    Edge(
                        book_id=book,
                        outcome=selection,
                        offered_decimal=price,
                        fair_probability=p,
                        expected_value=(p * price) - 1.0,
                        stale=stale,
                    )
                )
        return edges
