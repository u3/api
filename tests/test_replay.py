from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.test_normalize import OO_FX, OP_FX, OP_MARKETS, OP_ODDS, SS_EVENT, SS_PRICES
from u3ingest.cli import main
from u3ingest.replay import replay, write_duckdb, write_parquet


def _write_raw(root: Path, provider: str, stream: str, recv_ns: int, seq: int, meta: dict, body: object) -> None:
    dt = datetime.fromtimestamp(recv_ns / 1e9, tz=UTC)
    out = root / provider / stream / f"dt={dt:%Y-%m-%d}" / f"hour={dt:%H}" / f"{stream}-1.jsonl.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    rec = {"recv_ns": recv_ns, "provider": provider, "stream": stream, "seq": seq, "meta": meta, "body": body}
    with gzip.open(out, "ab") as fh:
        fh.write(json.dumps(rec).encode() + b"\n")


def _build_archive(root: Path) -> tuple[datetime, datetime, Path]:
    t0 = datetime(2026, 9, 5, 14, 0, tzinfo=UTC)
    ns0 = int(t0.timestamp() * 1e9)
    _write_raw(root, "bootstrap", "registries", ns0 + 1, 1, {"provider": "opticodds", "endpoint": "/fixtures/active"}, [OO_FX])
    _write_raw(root, "bootstrap", "registries", ns0 + 2, 2, {"provider": "oddspapi", "endpoint": "/fixtures"}, [OP_FX])
    _write_raw(root, "bootstrap", "registries", ns0 + 3, 3, {"provider": "sharpsports", "endpoint": "/events", "league": "EPL"}, [SS_EVENT])
    _write_raw(root, "opticodds", "sse-odds-soccer", ns0 + 10, 1, {"event": "odds"}, {"data": [OO_FX["odds"][0]]})
    _write_raw(root, "oddspapi", "ws-odds", ns0 + 20, 1, {"channel": "odds", "ts": 1788431742379}, OP_ODDS)
    _write_raw(root, "sharpsports", "prices-poll", ns0 + 30, 1, {"endpoint": "/prices", "league": "EPL"}, SS_PRICES)
    markets = root / "markets.json"
    markets.write_text(json.dumps(OP_MARKETS), encoding="utf-8")
    return t0 - timedelta(minutes=1), t0 + timedelta(minutes=10), markets


def test_replay_streaming_and_fixture_join(tmp_path: Path):
    since, until, markets = _build_archive(tmp_path)
    batches = list(replay(str(tmp_path), since, until, markets_json=str(markets)))
    quotes = [row for table, rows in batches if table == "quotes" for row in rows]
    levels = [row for table, rows in batches if table == "order_book_levels" for row in rows]
    assert len(quotes) == 6
    assert set(q["fixture_id"] for q in quotes) == {"2026090552B5D9A7"}
    assert len(levels) == 2


def test_replay_writers_and_cli(tmp_path: Path):
    pq = pytest.importorskip("pyarrow.parquet")
    duckdb = pytest.importorskip("duckdb")
    since, until, markets = _build_archive(tmp_path / "raw")
    out_parquet = tmp_path / "parquet_out"
    write_parquet(str(out_parquet), replay(str(tmp_path / "raw"), since, until, markets_json=str(markets)))
    q_files = sorted((out_parquet / "quotes").rglob("*.parquet"))
    lv_files = sorted((out_parquet / "order_book_levels").rglob("*.parquet"))
    assert q_files and lv_files
    assert pq.read_table(q_files[0]).num_rows > 0

    db_path = write_duckdb(str(tmp_path / "duckdb_out"), replay(str(tmp_path / "raw"), since, until, markets_json=str(markets)))
    con = duckdb.connect(db_path)
    assert con.execute("SELECT COUNT(*) FROM quotes").fetchone()[0] == 6
    assert con.execute("SELECT COUNT(*) FROM order_book_levels").fetchone()[0] == 2
    con.close()

    rc = main(
        [
            "replay",
            "--root",
            str(tmp_path / "raw"),
            "--since",
            since.isoformat(),
            "--until",
            until.isoformat(),
            "--providers",
            "opticodds,oddspapi,sharpsports",
            "--markets",
            str(markets),
            "--out",
            str(tmp_path / "cli_duckdb"),
            "--out-format",
            "duckdb",
        ]
    )
    assert rc == 0
