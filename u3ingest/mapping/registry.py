"""Book registry and fixture cross-reference.

Book ids are canonical lowercase slugs; each provider's slug/name is mapped here (seed from the live registries; unknown
books get `provider:<slug>` and are queued for review). Fixture resolution order (see cross-provider-mapping.md):
  1. OddsPapi fixture.externalProviders.opticoddsId  == OpticOdds fixture.id        (exact, observed 100% on MLB/EPL)
  2. SharpSports event.oddsjamId                     == OpticOdds fixture.game_id   (exact, observed 37/40 MLB)
  3. normalized home/away team names + start time within ±15 min within the same league (fallback)
"""
from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

from u3ingest.canonical.models import FixtureRef

# canonical_id -> {provider: [provider slugs/names (lowercase)]}
BOOKS: dict[str, dict[str, list[str]]] = {
    "pinnacle": {"opticodds": ["pinnacle", "ps3838", "ps4848"], "oddspapi": ["pinnacle"], "sharpsports": []},
    "draftkings": {"opticodds": ["draftkings"], "oddspapi": ["draftkings"], "sharpsports": ["dk", "draftkings"]},
    "fanduel": {"opticodds": ["fanduel"], "oddspapi": ["fanduel"], "sharpsports": ["fd", "fanduel"]},
    "betmgm": {"opticodds": ["betmgm"], "oddspapi": ["betmgm"], "sharpsports": ["mg", "betmgm"]},
    "caesars": {"opticodds": ["caesars"], "oddspapi": ["caesars"], "sharpsports": ["ca", "caesars"]},
    "betrivers": {"opticodds": ["betrivers"], "oddspapi": ["betrivers"], "sharpsports": ["br", "betrivers"]},
    "fanatics": {"opticodds": ["fanatics"], "oddspapi": ["fanatics"], "sharpsports": ["fn", "fanatics"]},
    "hardrock": {"opticodds": ["hard_rock"], "oddspapi": ["hardrock"], "sharpsports": ["hr", "hardrock"]},
    "fliff": {"opticodds": ["fliff"], "oddspapi": ["fliff"], "sharpsports": ["fl", "fliff"]},
    "thescore": {"opticodds": ["thescore"], "oddspapi": ["thescore"], "sharpsports": ["bs", "thescore"]},
    "sleeper": {"opticodds": ["sleeper"], "oddspapi": [], "sharpsports": ["sl", "sleeper"]},
    "circa": {"opticodds": ["circa_sports", "circa_vegas"], "oddspapi": ["circasports"], "sharpsports": []},
    "betonline": {"opticodds": ["betonline"], "oddspapi": ["betonline.ag"], "sharpsports": []},
    "bookmaker": {"opticodds": ["bookmaker"], "oddspapi": ["bookmaker.eu"], "sharpsports": []},
    "bet365": {"opticodds": ["bet365"], "oddspapi": ["bet365"], "sharpsports": []},
    "kalshi": {"opticodds": ["kalshi"], "oddspapi": ["kalshi"], "sharpsports": ["kl", "kalshi"]},
    "polymarket": {"opticodds": ["polymarket", "polymarket_usa_"], "oddspapi": ["polymarket"], "sharpsports": ["pm", "polymarket"]},
    "novig": {"opticodds": ["novig"], "oddspapi": ["novig"], "sharpsports": []},
    "prophetx": {"opticodds": ["prophet_x"], "oddspapi": ["prophetx"], "sharpsports": []},
    "sporttrade": {"opticodds": ["sporttrade"], "oddspapi": ["sporttrade"], "sharpsports": ["st", "sporttrade"]},
    "betfair_exchange": {"opticodds": ["betfair_exchange"], "oddspapi": ["betfair"], "sharpsports": []},
    "betfair_exchange_lay": {"opticodds": ["betfair_exchange_lay_"], "oddspapi": [], "sharpsports": []},
    "prizepicks": {"opticodds": ["prizepicks"], "oddspapi": ["prizepicks"], "sharpsports": ["pp", "prizepicks"]},
    "underdog": {"opticodds": ["underdog_fantasy_2_pick_"], "oddspapi": ["underdog"], "sharpsports": ["ud", "underdog"]},
    "draftkings_predictions": {"opticodds": ["draftkings_predictions"], "oddspapi": [], "sharpsports": []},
}


class BookRegistry:
    def __init__(self, books: dict[str, dict[str, list[str]]] | None = None) -> None:
        self._idx: dict[tuple[str, str], str] = {}
        self.unknown: dict[tuple[str, str], int] = {}
        for cid, provs in (books or BOOKS).items():
            for prov, slugs in provs.items():
                for s in slugs:
                    self._idx[(prov, s.lower())] = cid

    @staticmethod
    def normalize(name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")

    def resolve(self, provider: str, provider_book: str) -> str:
        key = (provider, (provider_book or "").lower())
        cid = self._idx.get(key) or self._idx.get((provider, self.normalize(provider_book)))
        if cid:
            return cid
        self.unknown[key] = self.unknown.get(key, 0) + 1
        return f"{provider}:{self.normalize(provider_book)}"


def norm_team(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(fc|sc|cf|afc|the|club)\b", " ", s)
    return re.sub(r"[^a-z0-9]", "", s)


@dataclass
class FixtureRegistry:
    """In-memory xref; persisted to the `fixture_xref` table by the pipeline. Keys: canonical id (OpticOdds id when known)."""

    by_canon: dict[str, FixtureRef] = field(default_factory=dict)
    by_opticodds: dict[str, str] = field(default_factory=dict)
    by_game_id: dict[str, str] = field(default_factory=dict)
    by_oddspapi: dict[str, str] = field(default_factory=dict)
    by_sharpsports: dict[str, str] = field(default_factory=dict)
    by_teams: dict[tuple[str, str, str], list[tuple[int, str]]] = field(default_factory=dict)  # (league, home, away) -> [(start_ms, canon)]
    unresolved: dict[str, int] = field(default_factory=dict)

    def _index(self, ref: FixtureRef) -> None:
        self.by_canon[ref.fixture_id] = ref
        if ref.opticodds_id:
            self.by_opticodds[ref.opticodds_id] = ref.fixture_id
        if ref.opticodds_game_id:
            self.by_game_id[ref.opticodds_game_id] = ref.fixture_id
        if ref.oddspapi_id:
            self.by_oddspapi[ref.oddspapi_id] = ref.fixture_id
        if ref.sharpsports_id:
            self.by_sharpsports[ref.sharpsports_id] = ref.fixture_id
        if ref.home and ref.away and ref.start_time_ms:
            self.by_teams.setdefault((ref.league, norm_team(ref.home), norm_team(ref.away)), []).append((ref.start_time_ms, ref.fixture_id))

    def add_opticodds(self, f: dict[str, Any]) -> FixtureRef:
        home = (f.get("home_competitors") or [{}])[0]
        away = (f.get("away_competitors") or [{}])[0]
        start = _iso_ms(f.get("start_date"))
        ref = self.by_canon.get(f["id"]) or FixtureRef(f["id"], (f.get("sport") or {}).get("id", ""), (f.get("league") or {}).get("id", ""), start,
                                                       home.get("name"), away.get("name"), f.get("status"))
        ref.opticodds_id, ref.opticodds_game_id = f["id"], f.get("game_id")
        ref.home_rot, ref.away_rot = f.get("home_rotation_number"), f.get("away_rotation_number")
        ref.statsperform_id = (f.get("source_ids") or {}).get("statsperform_id") or ref.statsperform_id
        ref.status, ref.updated_ns = f.get("status") or ref.status, time.time_ns()
        if ref.start_time_ms is None:
            ref.start_time_ms = start
        self._index(ref)
        return ref

    def add_oddspapi(self, f: dict[str, Any]) -> FixtureRef:
        ext = f.get("externalProviders") or {}
        p = f.get("participants") or {}
        oid = ext.get("opticoddsId")
        canon = self.by_opticodds.get(oid) if oid else None
        start = int(f["startTime"]) * 1000 if isinstance(f.get("startTime"), (int, float)) else None
        if canon is None and not oid:
            canon = self._fuzzy(str((f.get("tournament") or {}).get("tournamentId", "")), p.get("participant1Name"), p.get("participant2Name"), start)
        ref = self.by_canon.get(canon) if canon else None
        if ref is None:
            ref = FixtureRef(oid or f"oddspapi:{f['fixtureId']}", str((f.get("sport") or {}).get("sportId", "")), str((f.get("tournament") or {}).get("tournamentId", "")),
                             start, p.get("participant1Name"), p.get("participant2Name"), (f.get("status") or {}).get("statusName"))
        ref.oddspapi_id = f["fixtureId"]
        ref.opticodds_id = ref.opticodds_id or oid
        ref.betradar_id = str(ext.get("betradarId")) if ext.get("betradarId") else ref.betradar_id
        ref.pinnacle_id = str(ext.get("pinnacleId")) if ext.get("pinnacleId") else ref.pinnacle_id
        if ref.home_rot is None and p.get("participant1RotNr"):
            ref.home_rot, ref.away_rot = p.get("participant1RotNr"), p.get("participant2RotNr")
        ref.updated_ns = time.time_ns()
        self._index(ref)
        return ref

    def add_sharpsports(self, e: dict[str, Any], league_key: str | None = None) -> FixtureRef:
        oj = e.get("oddsjamId")
        canon = self.by_game_id.get(oj) if oj else None
        home = (e.get("contestantHome") or {}).get("fullName")
        away = (e.get("contestantAway") or {}).get("fullName")
        start = _iso_ms(e.get("startTime"))
        if canon is None:
            canon = self._fuzzy(league_key or (e.get("league") if isinstance(e.get("league"), str) else ""), home, away, start)
        ref = self.by_canon.get(canon) if canon else None
        if ref is None:
            ref = FixtureRef(f"sharpsports:{e['id']}", str(e.get("sport") or ""), str(league_key or e.get("league") or ""), start, home, away, None)
        ref.sharpsports_id = e["id"]
        ref.sportradar_id = e.get("sportradarId") or ref.sportradar_id
        ref.the_odds_api_id = e.get("theOddsApiId") or ref.the_odds_api_id
        if oj and not ref.opticodds_game_id:
            ref.opticodds_game_id = oj
        ref.updated_ns = time.time_ns()
        self._index(ref)
        return ref

    def _fuzzy(self, league: str, home: str | None, away: str | None, start_ms: int | None, tol_ms: int = 15 * 60_000) -> str | None:
        if not (home and away and start_ms):
            return None
        h, a = norm_team(home), norm_team(away)
        cands = list(self.by_teams.get((league, h, a), []))
        if not cands:  # league keys differ across providers: fall back to team pair only
            for (_lg, hh, aa), lst in self.by_teams.items():
                if (hh == h or h in hh or hh in h) and (aa == a or a in aa or aa in a):
                    cands += lst
        best = [(abs(s - start_ms), cid) for s, cid in cands if abs(s - start_ms) <= tol_ms]
        if best:
            return min(best)[1]
        self.unresolved[f"{league}|{home}|{away}|{start_ms}"] = self.unresolved.get(f"{league}|{home}|{away}|{start_ms}", 0) + 1
        return None

    def canonical_for(self, provider: str, provider_fixture_id: str) -> str:
        m = {"opticodds": self.by_opticodds, "oddspapi": self.by_oddspapi, "sharpsports": self.by_sharpsports}[provider]
        return m.get(provider_fixture_id) or f"{provider}:{provider_fixture_id}"


def _iso_ms(s: str | None) -> int | None:
    if not s:
        return None
    from datetime import datetime

    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return int(dt.timestamp() * 1000)
    except ValueError:
        return None
