"""Canonical records. Every provider is normalized to these before storage (see docs/research/cross-provider-mapping.md).

Quote  = one price for one selection at one book at one instant (tick). Order-book venues (exchanges, Kalshi, Polymarket)
additionally emit OrderBookLevel rows for depth. Prices are stored both decimal and American; `line` is the handicap /
total / player line (sign from the perspective of the selection).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

CANON_PERIODS = {"full", "reg", "1h", "2h", "1q", "2q", "3q", "4q", "1p", "2p", "3p", "f5i", "1i", "set1", "set2", "set3", "ot"}


def american_to_decimal(a: float | int | None) -> float | None:
    if a is None:
        return None
    a = float(a)
    if a == 0:
        return None
    return round(1 + a / 100, 6) if a > 0 else round(1 + 100 / abs(a), 6)


def decimal_to_american(d: float | None) -> int | None:
    if d is None or d <= 1:
        return None
    return round((d - 1) * 100) if d >= 2 else -round(100 / (d - 1))


@dataclass(slots=True)
class Quote:
    recv_ns: int                 # our receive time (authoritative for latency work)
    provider: str                # opticodds | oddspapi | sharpsports
    book_id: str                 # canonical book id (see mapping.registry.BOOKS)
    provider_book: str           # provider's own slug/name
    fixture_id: str              # canonical fixture id (OpticOdds id when resolvable, else "<provider>:<id>")
    provider_fixture_id: str
    market: str                  # canonical market key: moneyline | 3way | spread | total | team_total | player:<metric> | other:<slug>
    period: str                  # full | reg | 1h | 2h | 1q.. | 1p.. | f5i | set1.. | <raw>
    selection: str               # home | away | draw | over | under | yes | no | team:<id> | player:<id>
    line: float | None           # handicap/total/prop line as the selection sees it
    price_dec: float | None
    price_us: int | None
    is_main: bool | None
    active: bool
    limit_max: float | None
    source_ts_ms: int | None     # provider/book timestamp (OpticOdds odd.timestamp, OddsPapi bookmakerChangedAt)
    gateway_ts_ms: int | None    # OddsPapi changedAt / SSE entry ts
    provider_market: str
    provider_selection: str
    provider_odd_id: str
    player_id: str | None = None
    team_id: str | None = None
    event_kind: str = "update"   # update | lock | snapshot
    grouping_key: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def row(self) -> dict[str, Any]:
        d = asdict(self)
        d["extra"] = d["extra"] or {}
        return d


@dataclass(slots=True)
class OrderBookLevel:
    recv_ns: int
    provider: str
    book_id: str
    fixture_id: str
    market: str
    period: str
    selection: str
    venue_market_id: str         # e.g. Kalshi ticker, Polymarket token id, OpticOdds "<platform>:<source_market_id>"
    side: str                    # back|lay (exchange) or bid|ask (prediction market yes-price ladder)
    level: int
    price: float                 # decimal odds for back/lay; probability (0-1) for bid/ask
    size: float | None
    source_ts_ms: int | None
    provider_odd_id: str = ""

    def row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FixtureRef:
    fixture_id: str              # canonical
    sport: str                   # canonical sport slug (opticodds ids: basketball, football, baseball, soccer, hockey, tennis, ...)
    league: str                  # canonical league key (opticodds league id when known)
    start_time_ms: int | None
    home: str | None
    away: str | None
    status: str | None
    opticodds_id: str | None = None
    opticodds_game_id: str | None = None
    oddspapi_id: str | None = None
    sharpsports_id: str | None = None
    betradar_id: str | None = None
    pinnacle_id: str | None = None
    statsperform_id: str | None = None
    sportradar_id: str | None = None
    the_odds_api_id: str | None = None
    home_rot: int | None = None
    away_rot: int | None = None
    updated_ns: int = 0

    def row(self) -> dict[str, Any]:
        return asdict(self)
