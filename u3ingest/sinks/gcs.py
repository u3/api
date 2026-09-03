from __future__ import annotations

import asyncio
import base64
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()


def _crc32c_b64(data: bytes) -> str:
    poly = 0x82F63B78
    crc = 0xFFFFFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ poly if (crc & 1) else (crc >> 1)
    crc ^= 0xFFFFFFFF
    return base64.b64encode(int(crc).to_bytes(4, "big")).decode()


class GcsArchiveSync:
    def __init__(self, root: str, bucket: str, prefix: str = "raw", client: Any = None) -> None:
        self.root = Path(root)
        self.bucket_name = bucket
        self.prefix = prefix.strip("/")
        self._client = client
        self._bucket = None
        self._manifest = self.root / ".gcs_manifest.jsonl"

    def _ensure_adc_env(self) -> None:
        if os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or not os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON"):
            return
        fd, path = tempfile.mkstemp(prefix="u3-gcp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(os.environ["GOOGLE_APPLICATION_CREDENTIALS_JSON"])
            os.chmod(path, 0o600)
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path
        except Exception:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise

    def _get_bucket(self) -> Any:
        if self._bucket is not None:
            return self._bucket
        if self._client is None:
            self._ensure_adc_env()
            from google.cloud import storage  # optional dependency loaded lazily

            self._client = storage.Client()
        self._bucket = self._client.bucket(self.bucket_name)
        return self._bucket

    def _iter_raw_files(self) -> list[Path]:
        return sorted(p for p in self.root.rglob("*.jsonl.gz") if p.is_file())

    @staticmethod
    def _partition_hour(path: Path) -> datetime | None:
        dt = None
        hh = None
        for part in path.parts:
            if part.startswith("dt="):
                dt = part[3:]
            elif part.startswith("hour="):
                hh = part[5:]
        if not dt or hh is None:
            return None
        try:
            return datetime.strptime(f"{dt} {hh}", "%Y-%m-%d %H").replace(tzinfo=UTC)
        except ValueError:
            return None

    def _is_current_hour(self, path: Path, now: datetime) -> bool:
        part_hour = self._partition_hour(path)
        return part_hour is not None and part_hour == now.replace(minute=0, second=0, microsecond=0)

    def _object_name(self, path: Path) -> str:
        rel = path.relative_to(self.root).as_posix()
        return f"{self.prefix}/{rel}" if self.prefix else rel

    @staticmethod
    def _file_size_crc32c(path: Path) -> tuple[int, str]:
        data = path.read_bytes()
        return len(data), _crc32c_b64(data)

    @staticmethod
    def _transient_error(exc: BaseException) -> bool:
        if isinstance(exc, (ConnectionError, TimeoutError)):
            return True
        code = getattr(exc, "code", None)
        if code in {429, 500, 502, 503, 504}:
            return True
        return False

    async def _upload_with_retry(self, blob: Any, local_path: Path) -> None:
        delay = 0.5
        for i in range(5):
            try:
                await asyncio.to_thread(blob.upload_from_filename, str(local_path))
                return
            except Exception as e:  # noqa: BLE001
                if i == 4 or not self._transient_error(e):
                    raise
                log.warning("gcs upload retry", path=str(local_path), attempt=i + 1, delay=delay, error=str(e)[:200])
                await asyncio.sleep(delay)
                delay *= 2

    async def _append_manifest(self, row: dict[str, Any]) -> None:
        line = json.dumps(row, separators=(",", ":")) + "\n"

        def _append() -> None:
            self._manifest.parent.mkdir(parents=True, exist_ok=True)
            with self._manifest.open("a", encoding="utf-8") as f:
                f.write(line)

        await asyncio.to_thread(_append)

    async def sync_once(self, *, include_current: bool = False, delete_after_upload: bool = False) -> dict[str, int]:
        bucket = self._get_bucket()
        now = datetime.now(UTC)
        counts = {"uploaded": 0, "skipped_current": 0, "skipped_same": 0, "failed": 0, "deleted": 0}
        for path in self._iter_raw_files():
            if not include_current and self._is_current_hour(path, now):
                counts["skipped_current"] += 1
                log.info("gcs archive file", outcome="skipped_current_hour", path=str(path))
                continue
            obj = self._object_name(path)
            size, crc32c = self._file_size_crc32c(path)
            blob = bucket.blob(obj)
            try:
                exists = await asyncio.to_thread(blob.exists)
                if exists:
                    await asyncio.to_thread(blob.reload)
                if exists and int(getattr(blob, "size", -1)) == size and getattr(blob, "crc32c", None) == crc32c:
                    counts["skipped_same"] += 1
                    log.info("gcs archive file", outcome="skipped_same", path=str(path), object=obj, size=size)
                    continue
                await self._upload_with_retry(blob, path)
                await asyncio.to_thread(blob.reload)
                if int(getattr(blob, "size", -1)) != size or getattr(blob, "crc32c", None) != crc32c:
                    raise RuntimeError("uploaded object verification mismatch")
                uploaded_at = datetime.now(UTC).isoformat()
                await self._append_manifest({"path": str(path), "object": obj, "size": size, "crc32c": crc32c, "uploaded_at": uploaded_at})
                counts["uploaded"] += 1
                log.info("gcs archive file", outcome="uploaded", path=str(path), object=obj, size=size)
                if delete_after_upload:
                    await asyncio.to_thread(path.unlink)
                    counts["deleted"] += 1
                    log.info("gcs archive file", outcome="deleted_local", path=str(path), object=obj)
            except Exception as e:  # noqa: BLE001
                counts["failed"] += 1
                log.error("gcs archive file", outcome="failed", path=str(path), object=obj, error=str(e)[:200])
        return counts
