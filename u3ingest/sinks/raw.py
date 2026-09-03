"""Raw immutable archive: every provider message is appended as one JSON line, gzip-compressed, partitioned by
provider/stream/UTC-hour. This is the source of truth for replay; normalized tables are derived from it.

Layout: <raw_dir>/<provider>/<stream>/dt=YYYY-MM-DD/hour=HH/<stream>-<process_start_ms>.jsonl.gz
Each line: {"recv_ns": int, "provider": str, "stream": str, "seq": int, "meta": {...}, "body": <provider payload>}
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime
from typing import Any

import structlog

from u3ingest.util import dumps, gz_open_append

log = structlog.get_logger()


class RawArchive:
    def __init__(self, root: str, provider: str, stream: str, flush_every: float = 2.0, max_buffer: int = 5000) -> None:
        self.root, self.provider, self.stream = root, provider, stream
        self.flush_every, self.max_buffer = flush_every, max_buffer
        self._buf: list[bytes] = []
        self._seq = 0
        self._start_ms = int(time.time() * 1000)
        self._fh = None
        self._fh_hour: str | None = None
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self.written = 0

    def _path(self, ts_ns: int) -> tuple[str, str]:
        dt = datetime.fromtimestamp(ts_ns / 1e9, tz=UTC)
        hour = dt.strftime("%Y-%m-%d/%H")
        path = os.path.join(self.root, self.provider, self.stream, f"dt={dt:%Y-%m-%d}", f"hour={dt:%H}",
                            f"{self.stream}-{self._start_ms}.jsonl.gz")
        return hour, path

    async def write(self, body: Any, meta: dict[str, Any] | None = None, recv_ns: int | None = None) -> int:
        ts = recv_ns or time.time_ns()
        self._seq += 1
        rec = {"recv_ns": ts, "provider": self.provider, "stream": self.stream, "seq": self._seq, "meta": meta or {}, "body": body}
        self._buf.append(dumps(rec) + b"\n")
        if len(self._buf) >= self.max_buffer:
            await self.flush()
        return self._seq

    async def flush(self) -> None:
        async with self._lock:
            if not self._buf:
                return
            buf, self._buf = self._buf, []
            hour, path = self._path(time.time_ns())
            if self._fh is None or hour != self._fh_hour:
                if self._fh:
                    self._fh.close()
                self._fh, self._fh_hour = gz_open_append(path), hour
            await asyncio.to_thread(self._fh.write, b"".join(buf))
            self.written += len(buf)

    async def start(self) -> None:
        async def loop() -> None:
            while True:
                await asyncio.sleep(self.flush_every)
                try:
                    await self.flush()
                except Exception as e:  # noqa: BLE001
                    log.error("raw flush failed", error=str(e))
        self._task = asyncio.create_task(loop())

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
        await self.flush()
        if self._fh:
            self._fh.close()
            self._fh = None
