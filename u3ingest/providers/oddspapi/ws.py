"""OddsPapi v5 WebSocket gateway client (see docs/research/oddspapi.md §4).

Protocol: connect wss://v5.oddspapi.io/ws, first frame within 10 s must be
  {"type":"login","apiKey":..., "channels":[...], "sportIds":[...], "tournamentIds":[...], "fixtureIds":[...], "bookmakers":[...],
   "lang":"en", "receiveType":"json|binary|zstd|zstd-dict", "serverEpoch":..., "lastSeenId":{channel: entryId}}
Replies: login_ok (echoes effective filters, receiveType, resume.replayChannels, serverEpoch), error, snapshot_required
(reason server_restarted|resume_window_exceeded|client_backpressure → re-snapshot listed channels via REST; stream keeps
flowing), resume_complete, reconnect (server_upgrade → reconnect now), dict (zstd dictionaries). Data frames:
{"channel","type":"UPDATE","payload","ts","entryId":"<ms>-<seq>"}. Close codes: 4000 login, 4001 key revoked,
4002 backpressure, 4003 too many connections (max 5 per key group). Odds frames can exceed 1 MiB uncompressed.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import structlog
import websockets

from u3ingest.util import dumps, loads

log = structlog.get_logger()


@dataclass(slots=True)
class WsMessage:
    channel: str
    type: str
    payload: Any
    ts: int | None
    entry_id: str | None
    recv_ns: int
    raw_len: int


@dataclass(slots=True)
class WsControl:
    """login_ok / snapshot_required / resume_complete / reconnect / error / dict / disconnected."""
    type: str
    data: dict[str, Any]
    recv_ns: int = field(default_factory=time.time_ns)


class OddsPapiWS:
    def __init__(self, api_key: str, url: str = "wss://v5.oddspapi.io/ws", *, channels: Sequence[str] = ("odds",), sport_ids: Sequence[int] | None = None,
                 tournament_ids: Sequence[int] | None = None, fixture_ids: Sequence[str] | None = None, bookmakers: Sequence[str] | None = None,
                 receive_type: str = "json", lang: str = "en", idle_timeout: float = 45.0, max_size: int = 16 * 1024 * 1024,
                 proxy: Any = True) -> None:
        self.api_key, self.url = api_key, url
        self.filters: dict[str, Any] = {"channels": list(channels), "lang": lang, "receiveType": receive_type}
        for k, v in (("sportIds", sport_ids), ("tournamentIds", tournament_ids), ("fixtureIds", fixture_ids), ("bookmakers", bookmakers)):
            if v:
                self.filters[k] = list(v)
        self.idle_timeout, self.max_size, self.proxy = idle_timeout, max_size, proxy
        self.server_epoch: Any = None
        self.last_seen: dict[str, str] = {}
        self.replay_channels: set[str] = set()
        self.effective_receive_type = receive_type
        self._dicts: dict[str, Any] = {}
        self._zstd = None
        self.stats = {"messages": 0, "bytes": 0, "reconnects": 0, "snapshot_required": 0}

    def _login(self) -> dict[str, Any]:
        msg = {"type": "login", "apiKey": self.api_key, **self.filters}
        if self.server_epoch is not None and self.last_seen:
            msg["serverEpoch"] = self.server_epoch
            msg["lastSeenId"] = {c: eid for c, eid in self.last_seen.items() if not self.replay_channels or c in self.replay_channels}
        return msg

    def _decode(self, frame: bytes | str) -> dict[str, Any] | None:
        if isinstance(frame, str):
            return loads(frame)
        if self.effective_receive_type in ("zstd", "zstd-dict"):
            import zstandard  # lazy

            if self._zstd is None:
                self._zstd = zstandard.ZstdDecompressor()
            data = self._zstd.decompress(frame, max_output_size=self.max_size) if self.effective_receive_type == "zstd" else self._decode_dict(frame)
            return loads(data)
        if self.effective_receive_type == "binary":
            import msgpack  # lazy

            return msgpack.unpackb(frame, raw=False)
        return loads(frame)

    def _decode_dict(self, frame: bytes) -> bytes:
        import zstandard

        # zstd-dict frames embed dictId in the zstd frame header; try every dictionary we have been sent.
        for d in self._dicts.values():
            try:
                return zstandard.ZstdDecompressor(dict_data=d).decompress(frame, max_output_size=self.max_size)
            except zstandard.ZstdError:
                continue
        return zstandard.ZstdDecompressor().decompress(frame, max_output_size=self.max_size)

    async def messages(self) -> AsyncIterator[WsMessage | WsControl]:
        attempt = 0
        while True:
            attempt += 1
            try:
                async with websockets.connect(self.url, proxy=self.proxy, open_timeout=15, max_size=self.max_size, ping_interval=20, ping_timeout=20) as ws:
                    await ws.send(dumps(self._login()))
                    attempt_ok = False
                    while True:
                        try:
                            frame = await asyncio.wait_for(ws.recv(), timeout=self.idle_timeout)
                        except TimeoutError:
                            raise ConnectionError(f"idle > {self.idle_timeout}s") from None
                        recv_ns = time.time_ns()
                        raw_len = len(frame)
                        try:
                            msg = self._decode(frame)
                        except Exception as e:  # noqa: BLE001
                            log.warning("undecodable frame", error=str(e)[:120], size=raw_len)
                            continue
                        if not isinstance(msg, dict):
                            continue
                        t = msg.get("type")
                        ch = msg.get("channel")
                        if ch and t == "UPDATE" or (ch and "payload" in msg):
                            self.stats["messages"] += 1
                            self.stats["bytes"] += raw_len
                            eid = msg.get("entryId")
                            if eid:
                                self.last_seen[ch] = eid
                            if not attempt_ok:
                                attempt_ok, attempt = True, 0
                            yield WsMessage(ch, t or "UPDATE", msg.get("payload"), msg.get("ts"), eid, recv_ns, raw_len)
                            continue
                        # control frames
                        if t == "login_ok":
                            self.server_epoch = msg.get("serverEpoch", self.server_epoch)
                            self.effective_receive_type = msg.get("receiveType", self.effective_receive_type)
                            self.replay_channels = set((msg.get("resume") or {}).get("replayChannels") or [])
                            yield WsControl("login_ok", msg, recv_ns)
                        elif t == "dict":
                            import zstandard

                            did = str(msg.get("dictId") or msg.get("id"))
                            b = msg.get("dictionary") or msg.get("data")
                            if isinstance(b, str):
                                import base64

                                b = base64.b64decode(b)
                            if b:
                                self._dicts[did] = zstandard.ZstdCompressionDict(b)
                        elif t == "snapshot_required":
                            self.stats["snapshot_required"] += 1
                            for c in msg.get("channels") or []:
                                self.last_seen.pop(c, None)
                            self.server_epoch = msg.get("serverEpoch", self.server_epoch)
                            yield WsControl("snapshot_required", msg, recv_ns)
                        elif t == "resume_complete":
                            yield WsControl("resume_complete", msg, recv_ns)
                        elif t == "reconnect":
                            yield WsControl("reconnect", msg, recv_ns)
                            raise ConnectionError(f"server asked to reconnect: {msg.get('reason')}")
                        elif t == "error":
                            yield WsControl("error", msg, recv_ns)
                            code = str(msg.get("code") or msg.get("reason") or "")
                            if "login" in code or "auth" in code or "apiKey" in str(msg):
                                raise PermissionError(f"login rejected: {msg}")
                        else:
                            yield WsControl(t or "unknown", msg, recv_ns)
            except PermissionError:
                raise
            except (TimeoutError, websockets.ConnectionClosed, ConnectionError, OSError) as e:
                self.stats["reconnects"] += 1
                code = getattr(e, "code", None)
                if code in (4000, 4001):
                    raise PermissionError(f"gateway closed with {code}: {e}") from e
                delay = min(30.0, 0.5 * (2 ** min(attempt, 6)))
                yield WsControl("disconnected", {"error": str(e)[:200], "code": code, "retry_in": delay})
                await asyncio.sleep(delay)
