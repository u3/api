import asyncio
import gzip
import json
import time

import pytest

from u3ingest.providers.opticodds.sse import parse_sse
from u3ingest.sinks.raw import RawArchive
from u3ingest.util import SlidingWindowLimiter


async def _lines(text: str):
    for ln in text.split("\n"):
        yield ln


async def test_sse_parser_events_and_ids():
    text = "event: connected\ndata: ok go\n\nevent: ping\ndata: {\"timestamp\": 1.5}\n\nid: 1788-3\nevent: odds\ndata: {\"data\": [{\"id\": \"x\"}], \"entry_id\": \"1788-3\"}\n\n"
    evs = [e async for e in parse_sse(_lines(text))]
    assert [e.event for e in evs] == ["connected", "ping", "odds"]
    assert evs[0].data == "ok go"
    assert evs[2].id == "1788-3" and evs[2].data["entry_id"] == "1788-3" and evs[2].data["data"][0]["id"] == "x"


async def test_sliding_window_limiter_enforces_rate():
    lim = SlidingWindowLimiter(3, 0.2)
    t0 = time.monotonic()
    for _ in range(6):
        await lim.acquire()
    assert time.monotonic() - t0 >= 0.2 - 0.01


async def test_raw_archive_roundtrip(tmp_path):
    arch = RawArchive(str(tmp_path), "prov", "stream")
    await arch.write({"a": 1}, meta={"k": "v"})
    await arch.write([1, 2, 3])
    await arch.close()
    files = list(tmp_path.rglob("*.jsonl.gz"))
    assert len(files) == 1 and "dt=" in str(files[0]) and "hour=" in str(files[0])
    rows = [json.loads(line) for line in gzip.open(files[0]).read().decode().splitlines()]
    assert rows[0]["body"] == {"a": 1} and rows[0]["meta"] == {"k": "v"} and rows[1]["seq"] == 2 and rows[0]["provider"] == "prov"


async def test_oddspapi_ws_login_resume_and_snapshot_required():
    websockets = pytest.importorskip("websockets")
    from u3ingest.providers.oddspapi.ws import OddsPapiWS, WsControl, WsMessage

    logins = []

    async def handler(ws):
        login = json.loads(await ws.recv())
        logins.append(login)
        await ws.send(json.dumps({"type": "login_ok", "serverEpoch": "E1", "receiveType": "json", "channels": login["channels"], "resume": {"replayChannels": ["odds"]}}))
        if login.get("lastSeenId"):
            await ws.send(json.dumps({"type": "resume_complete"}))
            await ws.send(json.dumps({"type": "snapshot_required", "reason": "resume_window_exceeded", "channels": ["odds"], "serverEpoch": "E2"}))
            await ws.send(json.dumps({"channel": "odds", "type": "UPDATE", "payload": {"fixtureId": "f2"}, "ts": 2, "entryId": "2000-1"}))
            await asyncio.sleep(0.3)
            return
        await ws.send(json.dumps({"channel": "odds", "type": "UPDATE", "payload": {"fixtureId": "f1"}, "ts": 1, "entryId": "1000-1"}))
        await ws.close(code=1011)

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = OddsPapiWS("k", f"ws://127.0.0.1:{port}/ws", channels=["odds"], sport_ids=[11], proxy=None, idle_timeout=2)
        seen = []
        async for m in client.messages():
            seen.append(m)
            if isinstance(m, WsMessage) and m.payload.get("fixtureId") == "f2":
                break
        types = [m.type if isinstance(m, WsControl) else f"msg:{m.entry_id}" for m in seen]
        assert types[:2] == ["login_ok", "msg:1000-1"]
        assert "disconnected" in types and "resume_complete" in types and "snapshot_required" in types and types[-1] == "msg:2000-1"
        assert logins[0].get("lastSeenId") is None and logins[1]["lastSeenId"] == {"odds": "1000-1"} and logins[1]["serverEpoch"] == "E1"
        assert client.last_seen == {"odds": "2000-1"} and client.server_epoch == "E2"
