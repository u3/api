from __future__ import annotations

import gzip
import heapq
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from glob import glob
from typing import Any

import structlog

from u3ingest.mapping.registry import BookRegistry, FixtureRegistry
from u3ingest.providers.oddspapi.normalize import MarketDict, OddsPapiNormalizer
from u3ingest.providers.opticodds.normalize import OpticOddsNormalizer
from u3ingest.providers.sharpsports.normalize import SharpSportsNormalizer
from u3ingest.util import loads

log = structlog.get_logger()


@dataclass
class ReplayStats:
    files_read: int = 0
    messages: int = 0
    quotes: int = 0
    levels: int = 0
    normalization_errors: int = 0
    unknown_books: int = 0


def _dt_from_ns(recv_ns: int) -> str:
    return datetime.fromtimestamp(recv_ns / 1e9, tz=UTC).strftime("%Y-%m-%d")


def _iter_file(path: str) -> Iterator[dict[str, Any]]:
    with gzip.open(path, "rb") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = loads(line)
            if isinstance(row, dict):
                yield row


def _iter_merged(paths: list[str]) -> Iterator[dict[str, Any]]:
    iters: list[Iterator[dict[str, Any]]] = [_iter_file(p) for p in paths]
    heap: list[tuple[int, int, dict[str, Any]]] = []
    for i, it in enumerate(iters):
        try:
            row = next(it)
        except StopIteration:
            continue
        heapq.heappush(heap, (int(row.get("recv_ns") or 0), i, row))
    while heap:
        _ns, i, row = heapq.heappop(heap)
        yield row
        try:
            nxt = next(iters[i])
        except StopIteration:
            continue
        heapq.heappush(heap, (int(nxt.get("recv_ns") or 0), i, nxt))


def _jsonify_extra(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        rr = dict(r)
        rr["extra"] = json.dumps(rr.get("extra") or {}, separators=(",", ":"), sort_keys=True) if "extra" in rr else rr.get("extra")
        out.append(rr)
    return out


def _bootstrap_files(root: str) -> list[str]:
    return sorted(glob(os.path.join(root, "bootstrap", "registries", "dt=*", "hour=*", "*.jsonl.gz")))


def _provider_files(root: str, providers: set[str] | None) -> list[str]:
    if providers:
        return sorted(
            p
            for prov in providers
            for p in glob(os.path.join(root, prov, "*", "dt=*", "hour=*", "*.jsonl.gz"))
        )
    out: list[str] = []
    for prov in sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)) and d != "bootstrap"):
        out.extend(glob(os.path.join(root, prov, "*", "dt=*", "hour=*", "*.jsonl.gz")))
    return sorted(out)


def replay_with_stats(
    root: str,
    since: datetime,
    until: datetime,
    providers: set[str] | None = None,
    markets_json: str | None = None,
) -> tuple[Iterator[tuple[str, list[dict[str, Any]]]], ReplayStats]:
    stats = ReplayStats()
    books = BookRegistry()
    fixtures = FixtureRegistry()
    markets = MarketDict()
    if markets_json:
        with open(markets_json, encoding="utf-8") as fh:
            payload = json.load(fh)
        markets.load(payload if isinstance(payload, list) else [])
    n_oo = OpticOddsNormalizer(books, fixtures)
    n_op = OddsPapiNormalizer(books, fixtures, markets)
    n_ss = SharpSportsNormalizer(books, fixtures)
    since_ns = int(since.timestamp() * 1e9)
    until_ns = int(until.timestamp() * 1e9)
    bootstrap_files = _bootstrap_files(root)
    provider_files = _provider_files(root, providers)
    stats.files_read = len(bootstrap_files) + len(provider_files)

    for rec in _iter_merged(bootstrap_files):
        recv_ns = int(rec.get("recv_ns") or 0)
        if recv_ns > until_ns:
            continue
        stats.messages += 1
        meta = rec.get("meta") or {}
        provider = meta.get("provider")
        endpoint = meta.get("endpoint")
        body = rec.get("body")
        rows = body if isinstance(body, list) else [body]
        if provider == "opticodds" and endpoint == "/fixtures/active":
            for row in rows:
                if isinstance(row, dict):
                    n_oo.remember_fixture(row)
        elif provider == "oddspapi" and endpoint == "/fixtures":
            for row in rows:
                if isinstance(row, dict):
                    fixtures.add_oddspapi(row)
                    if row.get("bookmakers"):
                        n_op.note_bookmakers(str(row.get("fixtureId") or ""), row["bookmakers"])
        elif provider == "oddspapi" and endpoint == "/markets":
            markets.load(rows if isinstance(rows, list) else [])
        elif provider == "sharpsports" and endpoint == "/events":
            for row in rows:
                if isinstance(row, dict):
                    n_ss.remember_event(row)

    def _gen() -> Iterator[tuple[str, list[dict[str, Any]]]]:
        for rec in _iter_merged(provider_files):
            recv_ns = int(rec.get("recv_ns") or 0)
            if recv_ns < since_ns or recv_ns > until_ns:
                continue
            provider = str(rec.get("provider") or "")
            if providers and provider not in providers:
                continue
            stats.messages += 1
            meta = rec.get("meta") or {}
            body = rec.get("body")
            try:
                quotes = []
                levels = []
                if provider == "opticodds":
                    event = meta.get("event")
                    if event in ("odds", "locked-odds") and isinstance(body, dict):
                        quotes, levels = n_oo.quotes_from_sse(str(event), body, recv_ns)
                elif provider == "oddspapi":
                    channel = meta.get("channel")
                    if channel == "odds" and isinstance(body, dict):
                        quotes, levels = n_op.quotes(body, recv_ns, meta.get("ts"))
                    elif channel == "bookmakers" and isinstance(body, dict):
                        n_op.note_bookmakers(str(body.get("fixtureId") or ""), body.get("bookmakers") or {})
                    elif channel == "fixtures" and isinstance(body, dict) and body.get("fixtureId"):
                        fixtures.add_oddspapi(body)
                elif provider == "sharpsports":
                    rows = body if isinstance(body, list) else [body]
                    for row in rows:
                        if isinstance(row, dict) and row.get("markets"):
                            quotes.extend(n_ss.quotes(row, recv_ns))
                if quotes:
                    q_rows = [q.row() for q in quotes]
                    stats.quotes += len(q_rows)
                    yield "quotes", q_rows
                if levels:
                    lv_rows = [lv.row() for lv in levels]
                    stats.levels += len(lv_rows)
                    yield "order_book_levels", lv_rows
            except Exception as e:  # noqa: BLE001
                stats.normalization_errors += 1
                log.warning("replay normalization failed", provider=provider, error=str(e)[:200], meta=meta)
        stats.unknown_books = sum(books.unknown.values())

    return _gen(), stats


def replay(
    root: str,
    since: datetime,
    until: datetime,
    providers: set[str] | None = None,
    markets_json: str | None = None,
) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    it, _stats = replay_with_stats(root, since, until, providers, markets_json)
    return it


def write_parquet(out: str, batches: Iterator[tuple[str, list[dict[str, Any]]]]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    part_no = {"quotes": 0, "order_book_levels": 0}
    for table, rows in batches:
        if not rows:
            continue
        if table == "quotes":
            rows = _jsonify_extra(rows)
        by_dt: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_dt.setdefault(_dt_from_ns(int(row["recv_ns"])), []).append(row)
        for dt, grouped in by_dt.items():
            part_no[table] += 1
            out_dir = os.path.join(out, table, f"dt={dt}")
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, f"part-{part_no[table]}.parquet")
            pq.write_table(pa.Table.from_pylist(grouped), out_path)


def write_duckdb(out: str, batches: Iterator[tuple[str, list[dict[str, Any]]]]) -> str:
    import duckdb

    db_path = out if out.endswith(".duckdb") else os.path.join(out, "replay.duckdb")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = duckdb.connect(db_path)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS quotes (
            recv_ns BIGINT, provider VARCHAR, book_id VARCHAR, provider_book VARCHAR, fixture_id VARCHAR,
            provider_fixture_id VARCHAR, market VARCHAR, period VARCHAR, selection VARCHAR, line DOUBLE,
            price_dec DOUBLE, price_us INTEGER, is_main BOOLEAN, active BOOLEAN, limit_max DOUBLE,
            source_ts_ms BIGINT, gateway_ts_ms BIGINT, provider_market VARCHAR, provider_selection VARCHAR,
            provider_odd_id VARCHAR, player_id VARCHAR, team_id VARCHAR, event_kind VARCHAR, grouping_key VARCHAR, extra VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS order_book_levels (
            recv_ns BIGINT, provider VARCHAR, book_id VARCHAR, fixture_id VARCHAR, market VARCHAR, period VARCHAR,
            selection VARCHAR, venue_market_id VARCHAR, side VARCHAR, level INTEGER, price DOUBLE, size DOUBLE,
            source_ts_ms BIGINT, provider_odd_id VARCHAR
        )
        """
    )
    q_cols = [
        "recv_ns",
        "provider",
        "book_id",
        "provider_book",
        "fixture_id",
        "provider_fixture_id",
        "market",
        "period",
        "selection",
        "line",
        "price_dec",
        "price_us",
        "is_main",
        "active",
        "limit_max",
        "source_ts_ms",
        "gateway_ts_ms",
        "provider_market",
        "provider_selection",
        "provider_odd_id",
        "player_id",
        "team_id",
        "event_kind",
        "grouping_key",
        "extra",
    ]
    lv_cols = [
        "recv_ns",
        "provider",
        "book_id",
        "fixture_id",
        "market",
        "period",
        "selection",
        "venue_market_id",
        "side",
        "level",
        "price",
        "size",
        "source_ts_ms",
        "provider_odd_id",
    ]
    for table, rows in batches:
        if not rows:
            continue
        if table == "quotes":
            rows = _jsonify_extra(rows)
            vals = [tuple(r.get(c) for c in q_cols) for r in rows]
            con.executemany(f"INSERT INTO quotes ({','.join(q_cols)}) VALUES ({','.join(['?'] * len(q_cols))})", vals)
        elif table == "order_book_levels":
            vals = [tuple(r.get(c) for c in lv_cols) for r in rows]
            con.executemany(f"INSERT INTO order_book_levels ({','.join(lv_cols)}) VALUES ({','.join(['?'] * len(lv_cols))})", vals)
    con.close()
    return db_path
