"""u3-ingest CLI: run a connector and archive its raw output.

  u3-ingest archive opticodds-sse --stream odds --sport basketball --sportsbooks pinnacle,draftkings,kalshi
  u3-ingest archive opticodds-sse --stream prediction-markets --params category=politics
  u3-ingest archive oddspapi-ws --channels odds,fixtures,bookmakers --sports 10,11 --bookmakers pinnacle,polymarket
  u3-ingest snapshot oddspapi --sports 13 --bookmakers pinnacle,draftkings,fanduel,kalshi,polymarket
  u3-ingest snapshot sharpsports --league MLB
  u3-ingest snapshot opticodds --league mlb --sportsbooks pinnacle,draftkings,fanduel,kalshi,polymarket
"""
from __future__ import annotations

import argparse
import asyncio
import signal
import sys
import time

import structlog

from u3ingest.config import get_settings
from u3ingest.sinks.raw import RawArchive

log = structlog.get_logger()


def _csv(s: str | None) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()] if s else []


async def run_opticodds_sse(a: argparse.Namespace) -> None:
    from u3ingest.providers.opticodds.sse import OpticOddsSSE, ReconnectMarker

    st = get_settings()
    sse = OpticOddsSSE(st.opticodds_api_key, st.opticodds_base, user_agent=st.user_agent)
    params = dict(kv.split("=", 1) for kv in _csv(a.params))
    arch = RawArchive(st.raw_dir, "opticodds", f"sse-{a.stream}-{a.sport or 'all'}")
    await arch.start()
    deadline = time.monotonic() + a.seconds if a.seconds else None
    n = 0
    try:
        async for ev in sse.events(a.stream, a.sport, sportsbooks=_csv(a.sportsbooks), leagues=_csv(a.leagues), params=params):
            if isinstance(ev, ReconnectMarker):
                await arch.write({"marker": "reconnect", "reason": ev.reason, "gap_s": ev.gap_s}, meta={"control": True}, recv_ns=ev.recv_ns)
                continue
            n += 1
            await arch.write(ev.data, meta={"event": ev.event, "id": ev.id}, recv_ns=ev.recv_ns)
            if n % 1000 == 0:
                log.info("sse progress", stream=a.stream, sport=a.sport, events=n, written=arch.written)
            if deadline and time.monotonic() > deadline:
                break
    finally:
        await arch.close()
        log.info("sse archive closed", events=n, written=arch.written)


async def run_oddspapi_ws(a: argparse.Namespace) -> None:
    from u3ingest.providers.oddspapi.ws import OddsPapiWS, WsControl

    st = get_settings()
    ws = OddsPapiWS(st.oddspapi_api_key, st.oddspapi_ws, channels=_csv(a.channels) or ["odds"], sport_ids=[int(x) for x in _csv(a.sports)],
                    tournament_ids=[int(x) for x in _csv(a.tournaments)], bookmakers=_csv(a.bookmakers) or None, receive_type=a.receive_type)
    arch = RawArchive(st.raw_dir, "oddspapi", f"ws-{'-'.join(_csv(a.channels) or ['odds'])}")
    await arch.start()
    deadline = time.monotonic() + a.seconds if a.seconds else None
    n = 0
    try:
        async for m in ws.messages():
            if isinstance(m, WsControl):
                await arch.write(m.data, meta={"control": m.type}, recv_ns=m.recv_ns)
                log.info("ws control", type=m.type, detail={k: v for k, v in m.data.items() if k != "apiKey"} if m.type != "login_ok" else {"channels": m.data.get("channels"), "receiveType": m.data.get("receiveType")})
                continue
            n += 1
            await arch.write(m.payload, meta={"channel": m.channel, "type": m.type, "ts": m.ts, "entryId": m.entry_id, "raw_len": m.raw_len}, recv_ns=m.recv_ns)
            if n % 2000 == 0:
                log.info("ws progress", messages=n, stats=ws.stats, written=arch.written)
            if deadline and time.monotonic() > deadline:
                break
    finally:
        await arch.close()
        log.info("ws archive closed", messages=n, stats=ws.stats)


async def run_snapshot(a: argparse.Namespace) -> None:
    st = get_settings()
    arch = RawArchive(st.raw_dir, a.provider, f"snapshot-{a.league or a.sports or 'all'}")
    await arch.start()
    try:
        if a.provider == "opticodds":
            from u3ingest.providers.opticodds.rest import OpticOddsClient

            c = OpticOddsClient(st.opticodds_api_key, st.opticodds_base, user_agent=st.user_agent)
            fx = [f async for f in c.fixtures_active(league=a.league)]
            await arch.write(fx, meta={"endpoint": "/fixtures/active", "league": a.league})
            ids = [f["id"] for f in fx][: a.limit]
            for i in range(0, len(ids), 5):
                rows = await c.fixture_odds(ids[i:i + 5], _csv(a.sportsbooks))
                await arch.write(rows, meta={"endpoint": "/fixtures/odds", "fixture_ids": ids[i:i + 5]})
            log.info("opticodds snapshot", fixtures=len(fx), odds_calls=(len(ids) + 4) // 5, ratelimit=c.last_headers)
            await c.aclose()
        elif a.provider == "oddspapi":
            from u3ingest.providers.oddspapi.rest import OddsPapiClient

            c = OddsPapiClient(st.oddspapi_api_key, st.oddspapi_base)
            fx = []
            for sid in [int(x) for x in _csv(a.sports)] or [11]:
                fx += await c.fixtures(sport_id=sid, start_time_from=int(time.time()))
            await arch.write(fx, meta={"endpoint": "/fixtures", "sports": a.sports})
            main = await c.fixtures_odds_main([f["fixtureId"] for f in fx[: a.limit]], bookmakers=_csv(a.bookmakers) or None)
            await arch.write(main, meta={"endpoint": "/fixtures/odds/main"})
            log.info("oddspapi snapshot", fixtures=len(fx), ratelimit=c.last_headers)
            await c.aclose()
        elif a.provider == "sharpsports":
            from u3ingest.providers.sharpsports.rest import SharpSportsClient

            c = SharpSportsClient(st.sharpsports_token, st.sharpsports_base, user_agent=st.user_agent)
            ev = await c.events(league=a.league, upcoming=True)
            await arch.write(ev, meta={"endpoint": "/events", "league": a.league})
            pr = await c.prices(league=a.league)
            await arch.write(pr, meta={"endpoint": "/prices", "league": a.league})
            log.info("sharpsports snapshot", events=len(ev), ratelimit=c.last_headers)
            await c.aclose()
    finally:
        await arch.close()


def main(argv: list[str] | None = None) -> int:
    structlog.configure(processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.processors.add_log_level, structlog.processors.KeyValueRenderer()])
    ap = argparse.ArgumentParser(prog="u3-ingest")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a1 = sub.add_parser("archive"); s1 = a1.add_subparsers(dest="connector", required=True)
    p = s1.add_parser("opticodds-sse"); p.add_argument("--stream", default="odds"); p.add_argument("--sport"); p.add_argument("--sportsbooks")
    p.add_argument("--leagues"); p.add_argument("--params", help="k=v,k=v"); p.add_argument("--seconds", type=float, default=0); p.set_defaults(fn=run_opticodds_sse)
    p = s1.add_parser("oddspapi-ws"); p.add_argument("--channels", default="odds"); p.add_argument("--sports"); p.add_argument("--tournaments")
    p.add_argument("--bookmakers"); p.add_argument("--receive-type", default="json"); p.add_argument("--seconds", type=float, default=0); p.set_defaults(fn=run_oddspapi_ws)
    a2 = sub.add_parser("snapshot"); a2.add_argument("provider", choices=["opticodds", "oddspapi", "sharpsports"]); a2.add_argument("--league")
    a2.add_argument("--sports"); a2.add_argument("--sportsbooks"); a2.add_argument("--bookmakers"); a2.add_argument("--limit", type=int, default=50); a2.set_defaults(fn=run_snapshot)
    a = ap.parse_args(argv)

    async def runner() -> None:
        loop = asyncio.get_running_loop()
        task = asyncio.ensure_future(a.fn(a))
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, task.cancel)
        try:
            await task
        except asyncio.CancelledError:
            log.info("cancelled")

    try:
        import uvloop  # type: ignore

        uvloop.install()
    except ImportError:
        pass
    asyncio.run(runner())
    return 0


if __name__ == "__main__":
    sys.exit(main())
