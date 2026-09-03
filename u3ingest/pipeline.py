"""End-to-end pipeline: bootstrap registries → run connectors → normalize → raw archive (+ ClickHouse).

Bootstrap (REST, rate-limited):
  OpticOdds  /fixtures/active per league (+statsperform ids)      → FixtureRegistry (canonical ids)
  OddsPapi   /fixtures per sport (startTimeFrom=now) + /markets   → join via externalProviders.opticoddsId; MarketDict
  SharpSports /events per league (private key)                     → join via oddsjamId == game_id, else team+time
Streams:
  OpticOdds SSE /stream/odds/{sport} (≤5 books each)  → quotes (+ order book levels for exchanges)
  OddsPapi WS odds (+bookmakers, fixtures channels)    → quotes, depth, participantsRotated flags
  SharpSports /prices?league= polled every N seconds   → quote snapshots (stamped at receive)
Every raw payload is archived before normalization; normalization errors never drop raw data.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from u3ingest.config import Settings
from u3ingest.mapping.registry import BookRegistry, FixtureRegistry
from u3ingest.providers.oddspapi.normalize import MarketDict, OddsPapiNormalizer
from u3ingest.providers.opticodds.normalize import OpticOddsNormalizer
from u3ingest.providers.sharpsports.normalize import SharpSportsNormalizer
from u3ingest.sinks.raw import RawArchive

log = structlog.get_logger()

# OpticOdds sport id -> (OpticOdds leagues, OddsPapi sportId, SharpSports league keys)
DEFAULT_UNIVERSE: dict[str, tuple[list[str], int, list[str]]] = {
    "baseball": (["mlb"], 13, ["MLB"]),
    "basketball": (["nba", "wnba", "ncaab"], 11, ["NBA", "WNBA", "NCAAB"]),
    "football": (["nfl", "ncaaf"], 14, ["NFL", "NCAAF"]),
    "hockey": (["nhl"], 15, ["NHL"]),
    "soccer": (["england_-_premier_league", "mls"], 10, ["EPL", "MLS"]),
}
DEFAULT_BOOKS_OPTICODDS = ["pinnacle", "draftkings", "fanduel", "kalshi", "polymarket"]
DEFAULT_BOOKS_ODDSPAPI = ["pinnacle", "draftkings", "fanduel", "kalshi", "polymarket", "betonline.ag", "circasports", "novig", "prophetx"]


@dataclass
class Stats:
    quotes: int = 0
    levels: int = 0
    raw: int = 0
    errors: int = 0
    by_provider: dict[str, int] = field(default_factory=dict)


class Pipeline:
    def __init__(self, st: Settings, *, universe: dict[str, tuple[list[str], int, list[str]]] | None = None, books_oo: list[str] | None = None,
                 books_op: list[str] | None = None, sharpsports_poll_s: float = 30.0, clickhouse: Any = None) -> None:
        self.st = st
        self.universe = universe or DEFAULT_UNIVERSE
        self.books_oo = books_oo or DEFAULT_BOOKS_OPTICODDS
        self.books_op = books_op or DEFAULT_BOOKS_ODDSPAPI
        self.poll_s = sharpsports_poll_s
        self.books = BookRegistry()
        self.fixtures = FixtureRegistry()
        self.markets = MarketDict()
        self.n_oo = OpticOddsNormalizer(self.books, self.fixtures)
        self.n_op = OddsPapiNormalizer(self.books, self.fixtures, self.markets)
        self.n_ss = SharpSportsNormalizer(self.books, self.fixtures)
        self.ch = clickhouse
        self.stats = Stats()
        self._archives: dict[str, RawArchive] = {}

    def archive(self, provider: str, stream: str) -> RawArchive:
        key = f"{provider}/{stream}"
        if key not in self._archives:
            self._archives[key] = RawArchive(self.st.raw_dir, provider, stream)
        return self._archives[key]

    async def emit(self, quotes: list[Any], levels: list[Any]) -> None:
        self.stats.quotes += len(quotes)
        self.stats.levels += len(levels)
        for q in quotes:
            self.stats.by_provider[q.provider] = self.stats.by_provider.get(q.provider, 0) + 1
        if self.ch:
            await self.ch.write("quotes", [q.row() for q in quotes])
            await self.ch.write("order_book_levels", [lv.row() for lv in levels])

    # ---------------- bootstrap ----------------
    async def bootstrap(self) -> dict[str, Any]:
        from u3ingest.providers.oddspapi.rest import OddsPapiClient
        from u3ingest.providers.opticodds.rest import OpticOddsClient
        from u3ingest.providers.sharpsports.rest import SharpSportsClient

        oo = OpticOddsClient(self.st.opticodds_api_key, self.st.opticodds_base, user_agent=self.st.user_agent)
        op = OddsPapiClient(self.st.oddspapi_api_key, self.st.oddspapi_base)
        ss = SharpSportsClient(self.st.sharpsports_token, self.st.sharpsports_base, user_agent=self.st.user_agent)
        arch = self.archive("bootstrap", "registries")
        await arch.start()
        report: dict[str, Any] = {"opticodds": {}, "oddspapi": {}, "sharpsports": {}}
        try:
            for _sport, (leagues, _sid, _ssl) in self.universe.items():
                for lg in leagues:
                    rows = [f async for f in oo.fixtures_active(league=lg)]
                    await arch.write(rows, meta={"provider": "opticodds", "endpoint": "/fixtures/active", "league": lg})
                    for f in rows:
                        self.n_oo.remember_fixture(f)
                    report["opticodds"][lg] = len(rows)
            for _sport, (_lg, sid, _ssl) in self.universe.items():
                mk = await op.markets(sport_id=sid)
                self.markets.load(mk if isinstance(mk, list) else [])
                fx = await op.fixtures(sport_id=sid, start_time_from=int(time.time()) - 6 * 3600)
                await arch.write(fx, meta={"provider": "oddspapi", "endpoint": "/fixtures", "sportId": sid})
                matched = 0
                for f in fx if isinstance(fx, list) else []:
                    ref = self.fixtures.add_oddspapi(f)
                    matched += bool(ref.opticodds_id)
                    if f.get("bookmakers"):
                        self.n_op.note_bookmakers(f["fixtureId"], f["bookmakers"])
                report["oddspapi"][sid] = {"fixtures": len(fx) if isinstance(fx, list) else 0, "matched_opticodds": matched, "markets": len(self.markets.by_id)}
            for _sport, (leagues, _sid, ss_leagues) in self.universe.items():
                for lg_key, ss_lg in zip(leagues, ss_leagues, strict=False):
                    try:
                        ev = await ss.events(league=ss_lg, upcoming=True)
                    except Exception as e:  # noqa: BLE001
                        report["sharpsports"][ss_lg] = f"error: {str(e)[:120]}"
                        continue
                    await arch.write(ev, meta={"provider": "sharpsports", "endpoint": "/events", "league": ss_lg})
                    joined = 0
                    for e in ev if isinstance(ev, list) else []:
                        self.n_ss.remember_event(e, lg_key)
                        joined += not self.fixtures.canonical_for("sharpsports", e["id"]).startswith("sharpsports:")
                    report["sharpsports"][ss_lg] = {"events": len(ev) if isinstance(ev, list) else 0, "joined": joined}
            report["unresolved_fuzzy"] = len(self.fixtures.unresolved)
            report["fixtures"] = len(self.fixtures.by_canon)
        finally:
            await arch.close()
            await oo.aclose()
            await op.aclose()
            await ss.aclose()
        log.info("bootstrap complete", **{k: v for k, v in report.items() if k in ("fixtures", "unresolved_fuzzy")})
        return report

    # ---------------- streams ----------------
    async def run_opticodds_sse(self, sport: str, sportsbooks: list[str], stop: asyncio.Event) -> None:
        from u3ingest.providers.opticodds.sse import OpticOddsSSE, ReconnectMarker

        sse = OpticOddsSSE(self.st.opticodds_api_key, self.st.opticodds_base, user_agent=self.st.user_agent)
        arch = self.archive("opticodds", f"sse-odds-{sport}")
        await arch.start()
        try:
            async for ev in sse.events("odds", sport, sportsbooks=sportsbooks, params={"include_fixture_updates": "true"}):
                if stop.is_set():
                    return
                if isinstance(ev, ReconnectMarker):
                    await arch.write({"marker": "reconnect", "gap_s": ev.gap_s}, meta={"control": True}, recv_ns=ev.recv_ns)
                    continue
                await arch.write(ev.data, meta={"event": ev.event, "id": ev.id}, recv_ns=ev.recv_ns)
                self.stats.raw += 1
                if ev.event in ("odds", "locked-odds") and isinstance(ev.data, dict):
                    try:
                        qs, obs = self.n_oo.quotes_from_sse(ev.event, ev.data, ev.recv_ns)
                        await self.emit(qs, obs)
                    except Exception as e:  # noqa: BLE001
                        self.stats.errors += 1
                        log.warning("opticodds normalize failed", error=str(e)[:160])
        finally:
            await arch.close()

    async def run_oddspapi_ws(self, sport_ids: list[int], bookmakers: list[str] | None, stop: asyncio.Event) -> None:
        from u3ingest.providers.oddspapi.ws import OddsPapiWS, WsControl

        ws = OddsPapiWS(self.st.oddspapi_api_key, self.st.oddspapi_ws, channels=["odds", "bookmakers", "fixtures"], sport_ids=sport_ids, bookmakers=bookmakers)
        arch = self.archive("oddspapi", "ws-odds")
        await arch.start()
        try:
            async for m in ws.messages():
                if stop.is_set():
                    return
                if isinstance(m, WsControl):
                    await arch.write(m.data, meta={"control": m.type}, recv_ns=m.recv_ns)
                    if m.type == "snapshot_required":
                        log.warning("oddspapi snapshot_required", reason=m.data.get("reason"), channels=m.data.get("channels"))
                    continue
                await arch.write(m.payload, meta={"channel": m.channel, "ts": m.ts, "entryId": m.entry_id}, recv_ns=m.recv_ns)
                self.stats.raw += 1
                try:
                    if m.channel == "odds" and isinstance(m.payload, dict):
                        qs, obs = self.n_op.quotes(m.payload, m.recv_ns, m.ts)
                        await self.emit(qs, obs)
                    elif m.channel == "bookmakers" and isinstance(m.payload, dict):
                        self.n_op.note_bookmakers(str(m.payload.get("fixtureId")), m.payload.get("bookmakers") or {k: v for k, v in m.payload.items() if isinstance(v, dict)})
                    elif m.channel == "fixtures" and isinstance(m.payload, dict) and m.payload.get("fixtureId"):
                        self.fixtures.add_oddspapi(m.payload)
                except Exception as e:  # noqa: BLE001
                    self.stats.errors += 1
                    log.warning("oddspapi normalize failed", error=str(e)[:160])
        finally:
            await arch.close()

    async def run_sharpsports_poll(self, leagues: list[str], stop: asyncio.Event) -> None:
        from u3ingest.providers.sharpsports.rest import SharpSportsClient

        ss = SharpSportsClient(self.st.sharpsports_token, self.st.sharpsports_base, user_agent=self.st.user_agent)
        arch = self.archive("sharpsports", "prices-poll")
        await arch.start()
        try:
            while not stop.is_set():
                t0 = time.monotonic()
                for lg in leagues:
                    try:
                        pr = await ss.prices(league=lg)
                    except Exception as e:  # noqa: BLE001
                        self.stats.errors += 1
                        log.warning("sharpsports prices failed", league=lg, error=str(e)[:160])
                        continue
                    recv = time.time_ns()
                    await arch.write(pr, meta={"endpoint": "/prices", "league": lg}, recv_ns=recv)
                    self.stats.raw += 1
                    rows = pr if isinstance(pr, list) else [pr]
                    for ev_prices in rows:
                        if isinstance(ev_prices, dict) and ev_prices.get("markets"):
                            await self.emit(self.n_ss.quotes(ev_prices, recv), [])
                await asyncio.wait_for(stop.wait(), timeout=max(1.0, self.poll_s - (time.monotonic() - t0))) if not stop.is_set() else None
        except TimeoutError:
            pass
        finally:
            await arch.close()
            await ss.aclose()

    async def run(self, seconds: float | None = None, *, opticodds: bool = True, oddspapi: bool = True, sharpsports: bool = True) -> Stats:
        stop = asyncio.Event()
        if self.ch:
            await self.ch.start()
        tasks: list[asyncio.Task] = []
        if opticodds:
            for sport in self.universe:
                tasks.append(asyncio.create_task(self.run_opticodds_sse(sport, self.books_oo, stop)))
        if oddspapi:
            tasks.append(asyncio.create_task(self.run_oddspapi_ws([v[1] for v in self.universe.values()], self.books_op, stop)))
        if sharpsports:
            tasks.append(asyncio.create_task(self.run_sharpsports_poll([lg for v in self.universe.values() for lg in v[2]], stop)))

        async def reporter() -> None:
            while not stop.is_set():
                await asyncio.sleep(30)
                log.info("pipeline", quotes=self.stats.quotes, levels=self.stats.levels, raw=self.stats.raw, errors=self.stats.errors, by_provider=self.stats.by_provider,
                         unknown_books=dict(self.books.unknown), fixtures=len(self.fixtures.by_canon))
        tasks.append(asyncio.create_task(reporter()))
        try:
            if seconds:
                await asyncio.sleep(seconds)
            else:
                await asyncio.gather(*tasks)
        finally:
            stop.set()
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if self.ch:
                await self.ch.close()
        return self.stats
