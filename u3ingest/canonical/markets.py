"""Canonical market / period / selection keys derived from each provider's naming.

Design: market key + period + selection + line uniquely identify a tradeable outcome across providers, so the same
Pinnacle NBA spread quoted by OpticOdds and OddsPapi lands on the same key (book_id, fixture_id, market, period, selection, line).
Unknown markets are kept as `other:<provider-slug>` so nothing is dropped; the mapping QA job reviews the `other:` tail.
"""
from __future__ import annotations

import re

PERIOD_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^(1st|first)[ _]half|^1h[ _]"), "1h"), (re.compile(r"^(2nd|second)[ _]half|^2h[ _]"), "2h"),
    (re.compile(r"^(1st|first)[ _]quarter|^1q[ _]"), "1q"), (re.compile(r"^(2nd|second)[ _]quarter"), "2q"),
    (re.compile(r"^(3rd|third)[ _]quarter"), "3q"), (re.compile(r"^(4th|fourth)[ _]quarter"), "4q"),
    (re.compile(r"^(1st|first)[ _]period"), "1p"), (re.compile(r"^(2nd|second)[ _]period"), "2p"), (re.compile(r"^(3rd|third)[ _]period"), "3p"),
    (re.compile(r"^(1st|first)[ _](5|five)[ _]innings?|^f5"), "f5i"), (re.compile(r"^(1st|first)[ _](3|three)[ _]innings?"), "f3i"),
    (re.compile(r"^(1st|first)[ _](7|seven)[ _]innings?"), "f7i"), (re.compile(r"^(1st|first)[ _]inning"), "1i"),
    (re.compile(r"^(1st|first)[ _]set|^set[ _]1"), "set1"), (re.compile(r"^(2nd|second)[ _]set|^set[ _]2"), "set2"),
]
_REG = re.compile(r"reg(ulation)?[ _]time|\(reg", re.I)


def split_period(name: str) -> tuple[str, str]:
    """('1st Half Moneyline') -> ('1h', 'Moneyline'); full-game names -> ('full', name)."""
    n = name.strip()
    low = n.lower()
    for pat, per in PERIOD_PATTERNS:
        m = pat.match(low)
        if m:
            return per, n[m.end():].lstrip(" _-")
    if _REG.search(low):
        return "reg", n
    return "full", n


_PROP_METRIC = re.compile(r"^(player|batter|pitcher|goalie|goalkeeper)[ _](prop[ _])?(total[ _])?(?P<metric>.+)$", re.I)
_TEAM_PROP = re.compile(r"^team[ _](prop[ _])?(total[ _])?(?P<metric>.+)$", re.I)
_ALIAS = {
    "moneyline": "moneyline", "money line": "moneyline", "winner": "moneyline", "match winner": "moneyline", "1x2": "3way", "3-way": "3way",
    "3 way": "3way", "3-way moneyline": "3way", "moneyline 3-way": "3way", "point spread": "spread", "spread": "spread", "run line": "spread",
    "puck line": "spread", "goal spread": "spread", "game spread": "spread", "asian handicap": "spread", "handicap": "spread", "total": "total",
    "total points": "total", "total runs": "total", "total goals": "total", "total games": "total", "over/under": "total", "over under": "total",
    "asian total": "total", "team total": "team_total", "team total points": "team_total", "team total runs": "team_total", "team total goals": "team_total",
}


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def canon_market_from_name(name: str) -> tuple[str, str]:
    """Generic mapper for display names (OpticOdds `market`, SharpSports `Market.name`). Returns (market_key, period)."""
    period, rest = split_period(name)
    r = re.sub(r"\s*\((incl\.?|including) (ot|overtime|et|extra time)\)\s*$", "", rest, flags=re.I).strip()
    low = r.lower().replace("_", " ")
    if low in _ALIAS:
        return _ALIAS[low], period
    m = _PROP_METRIC.match(low)
    if m:
        return f"player:{slug(m.group('metric'))}", period
    m = _TEAM_PROP.match(low)
    if m:
        return f"team_total:{slug(m.group('metric'))}" if "total" in low else f"team_prop:{slug(m.group('metric'))}", period
    return f"other:{slug(r)}", period


_OP_TYPE = {"moneyline": "moneyline", "1x2": "3way", "spreads": "spread", "totals": "total", "teamtotals-team1": "team_total", "teamtotals-team2": "team_total"}
_OP_PERIOD = {"result": "full", "regular-time": "reg", "regular_time": "reg", "1st-half": "1h", "2nd-half": "2h", "1st-quarter": "1q", "2nd-quarter": "2q",
              "3rd-quarter": "3q", "4th-quarter": "4q", "1st-period": "1p", "2nd-period": "2p", "3rd-period": "3p", "1st-5-innings": "f5i", "1st-inning": "1i"}


def canon_market_oddspapi(market_type: str | None, period: str | None, market_name: str | None = None) -> tuple[str, str]:
    mt = (market_type or "").lower()
    per = _OP_PERIOD.get((period or "result").lower(), (period or "result").lower())
    if mt in _OP_TYPE:
        return _OP_TYPE[mt], per
    if mt.startswith(("players-", "playertotals-")):
        return f"player:{slug(mt.split('-', 1)[1])}", per
    if market_name:
        return canon_market_from_name(market_name)[0], per
    return f"other:{slug(mt)}", per


def canon_selection(name: str, *, home: str | None, away: str | None, home_id: str | None = None, away_id: str | None = None,
                    team_id: str | None = None, player_id: str | None = None) -> str:
    """Map a provider selection label to home|away|draw|over|under|yes|no|team:<id>|player:<id>."""
    n = (name or "").strip()
    low = n.lower()
    if player_id:
        if low.startswith("over") or low.endswith(" over"):
            return f"player:{player_id}:over"
        if low.startswith("under") or low.endswith(" under"):
            return f"player:{player_id}:under"
        return f"player:{player_id}:{slug(n) or 'yes'}"
    if low in ("over", "o") or low.startswith("over "):
        return "over"
    if low in ("under", "u") or low.startswith("under "):
        return "under"
    if low in ("draw", "x", "tie"):
        return "draw"
    if low in ("yes", "no"):
        return low
    if low in ("1", "home"):
        return "home"
    if low in ("2", "away"):
        return "away"
    if team_id and home_id and team_id == home_id:
        return "home"
    if team_id and away_id and team_id == away_id:
        return "away"
    base = re.sub(r"\s*[-+]\d+(\.\d+)?$", "", n).strip().lower()  # strip trailing handicap "Liverpool FC -1.5"
    if home and base == home.strip().lower():
        return "home"
    if away and base == away.strip().lower():
        return "away"
    if team_id:
        return f"team:{team_id}"
    return f"other:{slug(base)}"
