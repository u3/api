import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

from u3ingest.sinks.gcs import GcsArchiveSync


class FakeBlob:
    def __init__(self, bucket, name: str):
        self.bucket = bucket
        self.name = name
        self.size = None
        self.crc32c = None
        self.upload_calls = 0

    def exists(self) -> bool:
        return self.name in self.bucket.objects

    def reload(self) -> None:
        if self.exists():
            self.size, self.crc32c = GcsArchiveSync._file_size_crc32c(Path(self.bucket.object_paths[self.name]))

    def upload_from_filename(self, filename: str) -> None:
        self.upload_calls += 1
        data = Path(filename).read_bytes()
        self.bucket.objects[self.name] = data
        self.bucket.object_paths[self.name] = filename
        self.size, self.crc32c = GcsArchiveSync._file_size_crc32c(Path(filename))


class FakeBucket:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.object_paths: dict[str, str] = {}
        self._blobs: dict[str, FakeBlob] = {}

    def blob(self, name: str) -> FakeBlob:
        if name not in self._blobs:
            self._blobs[name] = FakeBlob(self, name)
        return self._blobs[name]


class FakeClient:
    def __init__(self, bucket: FakeBucket):
        self._bucket = bucket

    def bucket(self, _name: str) -> FakeBucket:
        return self._bucket


def _write_raw(root: Path, rel: str, payload: dict) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as f:
        f.write(json.dumps(payload).encode() + b"\n")
    return path


async def test_gcs_sync_idempotent_skip_same_object(tmp_path):
    rel = "prov/stream/dt=2020-01-01/hour=00/stream-1.jsonl.gz"
    local_path = _write_raw(tmp_path, rel, {"a": 1})
    bucket = FakeBucket()
    obj = f"raw/{rel}"
    bucket.objects[obj] = local_path.read_bytes()
    bucket.object_paths[obj] = str(local_path)
    syncer = GcsArchiveSync(str(tmp_path), "bucket", client=FakeClient(bucket))

    counts = await syncer.sync_once()

    assert counts["uploaded"] == 0
    assert counts["skipped_same"] == 1
    assert bucket.blob(obj).upload_calls == 0


async def test_gcs_sync_skips_current_hour_by_default(tmp_path):
    now = datetime.now(UTC)
    current_rel = f"prov/stream/dt={now:%Y-%m-%d}/hour={now:%H}/stream-1.jsonl.gz"
    old_rel = "prov/stream/dt=2020-01-01/hour=00/stream-2.jsonl.gz"
    _write_raw(tmp_path, current_rel, {"x": 1})
    _write_raw(tmp_path, old_rel, {"y": 1})
    bucket = FakeBucket()
    syncer = GcsArchiveSync(str(tmp_path), "bucket", client=FakeClient(bucket))

    counts = await syncer.sync_once()

    assert counts["uploaded"] == 1
    assert counts["skipped_current"] == 1
    assert f"raw/{old_rel}" in bucket.objects
    assert f"raw/{current_rel}" not in bucket.objects


async def test_gcs_sync_delete_after_upload(tmp_path):
    rel = "prov/stream/dt=2020-01-01/hour=00/stream-3.jsonl.gz"
    local_path = _write_raw(tmp_path, rel, {"z": 1})
    bucket = FakeBucket()
    syncer = GcsArchiveSync(str(tmp_path), "bucket", client=FakeClient(bucket))

    counts = await syncer.sync_once(delete_after_upload=True)

    assert counts["uploaded"] == 1
    assert counts["deleted"] == 1
    assert not local_path.exists()


async def test_gcs_sync_writes_manifest_rows(tmp_path):
    rel1 = "prov/stream/dt=2020-01-01/hour=00/stream-4.jsonl.gz"
    rel2 = "prov/stream/dt=2020-01-01/hour=01/stream-5.jsonl.gz"
    p1 = _write_raw(tmp_path, rel1, {"a": 1})
    p2 = _write_raw(tmp_path, rel2, {"b": 2})
    syncer = GcsArchiveSync(str(tmp_path), "bucket", client=FakeClient(FakeBucket()))

    counts = await syncer.sync_once()

    manifest = (tmp_path / ".gcs_manifest.jsonl").read_text().splitlines()
    rows = [json.loads(line) for line in manifest]
    assert counts["uploaded"] == 2
    assert len(rows) == 2
    assert rows[0]["object"] == f"raw/{rel1}"
    assert rows[1]["object"] == f"raw/{rel2}"
    assert rows[0]["path"] == str(p1)
    assert rows[1]["path"] == str(p2)
    assert all({"path", "object", "size", "crc32c", "uploaded_at"} <= row.keys() for row in rows)
