"""ClickHouse sink: batched async inserts (clickhouse-connect over HTTPS). Rows are dicts from Quote.row()/OrderBookLevel.row()."""
from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

from u3ingest.util import dumps

log = structlog.get_logger()


class ClickHouseSink:
    def __init__(self, url: str, database: str = "u3", *, batch: int = 5000, flush_every: float = 1.0) -> None:
        from urllib.parse import urlparse

        import clickhouse_connect  # optional dependency

        u = urlparse(url)
        self.client = clickhouse_connect.get_client(host=u.hostname, port=u.port or 8443, username=u.username or "default", password=u.password or "",
                                                    secure=u.scheme == "https", database=database, settings={"async_insert": 1, "wait_for_async_insert": 0})
        self.batch, self.flush_every = batch, flush_every
        self._buf: dict[str, list[dict[str, Any]]] = {}
        self._task: asyncio.Task | None = None
        self.inserted = 0

    def apply_schema(self, path: str = "schemas/clickhouse.sql") -> None:
        for stmt in open(path).read().split(";"):
            if stmt.strip() and not stmt.strip().startswith("--"):
                self.client.command(stmt)

    async def write(self, table: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        buf = self._buf.setdefault(table, [])
        buf.extend(rows)
        if len(buf) >= self.batch:
            await self.flush(table)

    async def flush(self, table: str | None = None) -> None:
        for t in [table] if table else list(self._buf):
            rows, self._buf[t] = self._buf.get(t, []), []
            if not rows:
                continue
            cols = list(rows[0].keys())
            data = [[dumps(r[c]).decode() if isinstance(r[c], (dict, list)) else r[c] for c in cols] for r in rows]
            t0 = time.monotonic()
            await asyncio.to_thread(self.client.insert, t, data, column_names=cols)
            self.inserted += len(rows)
            log.debug("clickhouse insert", table=t, rows=len(rows), ms=round((time.monotonic() - t0) * 1000))

    async def start(self) -> None:
        async def loop() -> None:
            while True:
                await asyncio.sleep(self.flush_every)
                try:
                    await self.flush()
                except Exception as e:  # noqa: BLE001
                    log.error("clickhouse flush failed", error=str(e)[:200])
        self._task = asyncio.create_task(loop())

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
        await self.flush()
