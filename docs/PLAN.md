# u3 — Integration & Ingestion Plan (sports + prediction-market trading data platform)

**Status:** definitive plan for step one (ingestion foundation) and the phases it must serve. Written 2026-09-03 against the live probes and provider specs in `docs/research/`, the current `u3ingest` implementation, and the external research briefs. Where a research brief disagrees with our own probes, the probe wins.

**Citation keys used below**
- `[OP §n]` — `docs/research/oddspapi.md` section n (complete, live-probed).
- `[OO §n]` — `docs/research/opticodds.md` section n (sections 1–3 landed at the time of writing; §4+ pending). `[OO-probe #n]` — OpticOdds live-probe findings (171 probes), item n; `[OO-sum <group>]` — reader summaries (`oo-core`, `oo-odds-stream`, `oo-prediction-markets`, `oo-results-a/b`, `oo-entities-a/b`, `oo-copilot-trading`) for material not yet in the spec.
- `[SS §n]` — `docs/research/sharpsports.md` section n (sections 1–2 landed; §3+ pending). `[SS-sum <group>]` — reader summaries (`ss-betprices`, `ss-historicdata`, `ss-core`, `ss-market-taxonomy`, `ss-betsync-rest`, `ss-missing`) for data-model material.
- `[XJ]` — cross-provider live join probe (`cross.md`, 2026-09-03T10:45Z). `docs/research/cross-provider-mapping.md` had not been generated; §3 of this plan is the interim statement and must be reconciled when it lands.
- `[CODE path]` — current implementation on branch `claude/arbitrage-api-integration-plan-pphn75`; `[PR #3/#4/#5]` — open Copilot PRs (GCS archive sync, replay to Parquet/DuckDB, pricing library).
- `[R1-gpt]`, `[R1-pplx]` (infrastructure), `[R2-gpt]`, `[R2-gem]`, `[R2-opus]`, `[R2-pplx]` (methodology/edges), `[R3-gem]`, `[R3-pplx]` (vendor landscape) — external web-grounded briefs.

---

## 0. Executive summary

We are building the data spine of a small proprietary trading operation across sportsbooks, sports prediction markets (Kalshi, Polymarket, Novig, ProphetX, Betfair) and non-sport prediction markets. Step one is done in prototype form; this document turns it into a production-shaped, budget-bounded system and sets up the fair-value, edge-detection and execution phases that consume it.

**What we have proven (Phase 0, this week).** A Python asyncio pipeline (`u3ingest`) that bootstraps fixture/market/book registries from all three vendors, joins fixtures across vendors, streams OpticOdds SSE and the OddsPapi WebSocket, polls SharpSports, archives every raw payload to gzip JSONL partitioned by provider/stream/hour, normalizes to one canonical `Quote`/`OrderBookLevel` model, and batch-inserts into ClickHouse. A 75 s live run on baseball + soccer produced 381,188 canonical quotes, 1,311,005 order-book levels and 105,128 raw messages (52 MB gz) with zero normalization errors `[CODE docs/research/README.md]`. Three Copilot PRs add GCS archive sync `[PR #3]`, replay of the raw archive into Parquet/DuckDB `[PR #4]`, and a devig/consensus/board pricing library `[PR #5]`.

**The ten decisions that shape everything else** (full rationale in §10):
1. **OddsPapi WS is the primary real-time sportsbook feed; OpticOdds is primary for breadth, prediction-market order books, DFS pick'em, futures, results/grading and non-sport markets; SharpSports is primary for stats/historic context and DFS +100 lines, never for real-time pricing** (its `/prices` carries no timestamp `[SS-sum ss-betprices]`).
2. **Python asyncio stays the hot-path runtime** through Phase 2, behind an explicit benchmark gate (≥ 40k normalized rows/s sustained, p99 < 10 ms in-process) that, if failed, carves out only the decode/normalize stage into Rust — not a rewrite.
3. **Raw archive first**: GCS is the source of truth; ClickHouse and BigQuery are rebuildable from it (`u3-ingest replay` `[PR #4]`).
4. **One on-demand `e2-standard-2` VM in `us-east4`** runs all long-lived socket consumers; no Cloud Run, no GKE, no Cloud NAT, no Kafka `[R1-gpt §1.3, §1.4]`. Batch/backfill on the same VM off-peak, or a Spot VM.
5. **ClickHouse = hot tick store (≤ 45-day TTL) and the board's analytical mirror; BigQuery = research warehouse over Parquet in GCS (free tier + GCP credit); Snowflake = optional 30-day sprint for SharpSports stats joins, not always-on** `[R1-gpt §3]`.
6. **Coalesce before you ship**: Polymarket alone is 81–87 % of both vendors' sports-odds message volume `[OO-probe #6][OP §4.10]`; we archive raw but insert only change-level, top-N-level rows to ClickHouse and cap egress at ≈ $20/month.
7. **Trial-credit budget**: ≈ $76–104/month on GCP → ≈ $280 over 90 days; ClickHouse Cloud trial consumed in month 2; Snowflake trial optional in month 3.
8. **Canonical fixture id = OpticOdds fixture id**, joined to OddsPapi via `externalProviders.opticoddsId` (100 % on MLB/EPL, 91 % NCAAF `[XJ]`) and to SharpSports via `oddsjamId == OpticOdds game_id` (37/40 MLB `[XJ][OO §3.2]`) with team+time fallback.
9. **Three clocks on every quote** (`source_ts_ms`, `gateway_ts_ms`, `recv_ns`) so latency attribution and per-book lag are measurable from day one `[OP §7.1]`.
10. **Edges are prioritized by durability, not headline size**: sportsbook-vs-Kalshi/Polymarket arbitrage and prediction-market market-making (structural, scalable) come before soft-book edges (high ROI, account-mortal).

**Phased roadmap.** Phase 0 (done): ingestion MVP. Phase 1 (weeks 2–4): cloud deployment, resilience (zstd-dict WS, reconciliation sweeps, SSE re-hydration), settlement/CLV/backfill workers, warehouse, observability. Phase 2 (weeks 5–8): fair-value engine, edge detectors, alerting, paper-trading ledger, CLV loop. Phase 3 (weeks 9–12+): execution adapters (Kalshi/Polymarket first), risk engine, market-making pilot.

**Corrections to the current code surfaced by this plan** (all Phase 1, week 2): remove `novig` from the OddsPapi bookmaker filter (not entitled `[OP §1.1]`); verify the OpticOdds MLS league id (`usa_-_major_league_soccer` per `[OO §3.2]`; `mls` returned 0 fixtures in the join probe `[XJ]`); pass `ascending=true` to SharpSports `/events` (default sort is descending `[SS §2.3]`); default OddsPapi `receiveType` to `zstd-dict`; add `league=` filters to OpticOdds SSE; replace league-wide SharpSports polling.

---

## 1. Architecture

### 1.1 Components and topology

```
                     vendors (public internet, all TLS/443)
  OddsPapi WS  ─┐    OddsPapi REST      OpticOdds SSE ─┐   OpticOdds REST    SharpSports REST
  (zstd-dict)   │    (?apiKey=)         (/stream/*)     │   (X-Api-Key)       (Token, private key)
                ▼                                       ▼
 ┌──────────────────────────── GCE e2-standard-2, us-east4, on-demand ───────────────────────────┐
 │  systemd units (one Python process each, uvloop + orjson):                                     │
 │   u3-op-ws     OddsPapi conn#1 odds+bookmakers │ conn#3 fixtures+scores+clocks │ conn#4 aux     │
 │   u3-oo-sse    OpticOdds /stream/odds/{sport} × book-groups │ /stream/results │ /stream/pm      │
 │   u3-ss-poll   SharpSports /prices (targeted) │ /injuries │ /events                              │
 │   u3-batch     scheduler: REST sweeps, settlement, CLV, futures, injuries, backfills            │
 │   u3-sync      GCS archive sync (PR #3), every 5 min, crc32c-verified, manifest                 │
 │   u3-board     (Phase 2) in-memory book + fair value + detectors; Redis Streams IPC             │
 │   alloy        Grafana Agent → Grafana Cloud Free (metrics); journald → Cloud Logging (sampled) │
 │                                                                                                 │
 │   local disk: raw JSONL spool (data/raw/…, ≤ 48 h), Redis (Phase 2), SQLite cursors             │
 └───────────┬───────────────────────────┬───────────────────────────────┬───────────────────────┘
             │ raw archive               │ coalesced rows (native TLS 9440)│ Parquet (PR #4 replay)
             ▼                           ▼                                  ▼
   GCS bucket u3-raw               ClickHouse (Cloud trial month 2;        BigQuery datasets
   raw/<provider>/<stream>/        self-hosted fallback)                    u3_raw (external tables)
   dt=/hour=/*.jsonl.zst           db u3: quotes, order_book_levels,        u3_marts (CLV, settlement,
   lifecycle: Nearline 30 d,       fixture_xref, quotes_latest MV,          stats joins, backtests)
   Coldline 180 d, never delete    settlements, clv, book_status, ...       Snowflake (optional sprint)
```

**Languages/runtimes.** Python 3.11+, `asyncio` with `uvloop`, `orjson`, `httpx`, `websockets`, `zstandard`, `msgpack`, `clickhouse-connect` `[CODE pyproject.toml]`. No second language until the benchmark gate in §1.5 fails. SQL (ClickHouse, BigQuery). Bash/systemd for ops; a `deploy/` directory with `gcloud` scripts (no Terraform until there is more than one VM).

**Message flow (hot path).**
1. Socket reader decodes a frame (zstd-dict → JSON for OddsPapi; SSE text for OpticOdds) and stamps `recv_ns` `[CODE providers/oddspapi/ws.py, providers/opticodds/sse.py]`.
2. The raw payload is appended to the `RawArchive` buffer **before** normalization; normalization errors never drop raw data `[CODE sinks/raw.py, pipeline.py]`.
3. Normalizer resolves book id (`BookRegistry`), canonical fixture id (`FixtureRegistry`), market/period/selection/line keys (`canonical/markets.py`) and emits `Quote` and `OrderBookLevel` rows carrying `source_ts_ms`, `gateway_ts_ms`, `recv_ns` `[CODE canonical/models.py]`.
4. Rows pass through the **coalescer** (§1.4, §1.8, Phase 1) and then to the ClickHouse sink (batched async inserts, 5,000 rows or 1 s) `[CODE sinks/clickhouse.py]`.
5. (Phase 2) The same rows update the in-process `Board` (latest quote per `(fixture, market, period, line, selection, book)`) `[PR #5 u3ingest/pricing/board.py]` and are published on Redis Streams for detectors.

**Batch path.** `u3-batch` runs scheduled REST jobs (§2.4, §4) under the vendor rate limiters already implemented (`SlidingWindowLimiter`: OpticOdds 2,400/15 s standard, 10/15 s historical, 240/15 s stream connects; OddsPapi 9/1 s odds and 190/60 s other; SharpSports 45/1 s and 18/1 s large-list `[CODE util.py, providers/*/rest.py]`), archives every body, and writes settlement/CLV/dimension tables. Backfills run as one-shot CLI commands.

### 1.2 What runs where, and what we turn off

| Workload | Runs on | Why | Turned off / deferred |
|---|---|---|---|
| WS/SSE consumers, raw spool, coalescer, ClickHouse inserts | GCE `e2-standard-2` (2 vCPU/8 GiB), on-demand, external IPv4, egress-only firewall, IAP SSH | Long-lived sockets need a stable process, no request timeouts, fixed IP `[R1-gpt §1.3]`; Cloud Run WebSockets are requests with timeouts `[R1-gpt §1.3]` | Cloud Run, GKE Autopilot, Cloud NAT (charges per GiB processed `[R1-gpt §1.4]`), Spot for the only live consumer |
| REST sweeps, settlement/CLV workers, backfills | same VM, `u3-batch` (nice 10); large backfills on a Spot `e2-standard-2` (~$29/mo) only when needed `[R1-gpt §1.2]` | Batch is bursty; Spot preemption is harmless for idempotent jobs | — |
| Raw archive | GCS Standard → Nearline at 30 d → Coldline at 180 d (lifecycle rule) | Immutable source of truth, cheap | Deleting raw data (never) |
| Hot tick store + board mirror | ClickHouse Cloud (GCP `us-east1`, Basic 1×8 GiB) during the 30-day/$300 trial in **month 2**; self-hosted single-node ClickHouse in Docker on the VM with 7-day TTL before/after | Cloud trial covers exactly one month of 24/7 ingest (≈ $186/mo list `[R1-gpt §2.1]`); `us-east4` is not a ClickHouse GCP region `[R1-gpt §2.3]` | Idle scaling (unusable under continuous ingest `[R1-gpt §2.2]`); paid ClickHouse before the economics are validated |
| Research warehouse | BigQuery: external tables over Parquet produced by `u3-ingest replay` `[PR #4]`, plus native mart tables | Same $300 credit, permanent free tier (10 GiB storage, 1 TiB queries/mo) `[R1-pplx §3]` | BigQuery streaming inserts of raw ticks (cost + small-file behaviour `[R1-gpt §3.3]`) |
| SharpSports stats/historic joins | BigQuery by default; Snowflake $400/30-day trial as an optional month-3 research sprint | Snowflake has no free tier; sandbox cannot reach it (cert-pinned) | Snowpipe Streaming; any always-on Snowflake warehouse |
| Metrics/alerting | Grafana Cloud Free (10k series, 14-day retention) `[R1-gpt §5.4]` | Zero cost, hosted alerting | Self-hosted Prometheus/Grafana; per-market metric labels (cardinality) |
| Non-sport prediction-market streams | one category (`politics`) archived continuously; others on demand | 933 snapshots/s, 120 MB/45 s for politics alone `[OO-probe #6][OO §2.10]` | All 11 categories 24/7 |
| Sportsbook front-end scraping (SOAX) | nothing | Not in step one (brief) | Deferred to Phase 3 validation only |

### 1.3 Monthly cost within trial credits

Prices are planning numbers; obtain a dated Cloud Pricing Calculator quote before launch `[R1-gpt §1.2]`.

| Item | Month 1 | Month 2 (ClickHouse trial) | Month 3 | Source / assumption |
|---|---|---|---|---|
| GCE `e2-standard-2` on-demand, `us-east4` | $55 | $55 | $55 | $48.91 in us-central1, "roughly $53–57" in us-east4 `[R1-gpt §1.2]` |
| 50 GiB `pd-balanced` boot+spool | $5 | $5 | $5 | ~$0.10/GiB-mo |
| Static external IP (in use) | $3 | $3 | $3 | ~$0.004/h |
| GCS raw archive (Standard, then Nearline) | $8 (0.4 TB) | $16 (0.8 TB) | $22 (1.2 TB, 0.4 TB Nearline) | ≤ 15 GB/day compressed after the §1.4 caps (52 MB/75 s observed for 2 sports and 3 vendors `[CODE README]` ≈ 60 GB/day uncapped — the caps are mandatory) |
| BigQuery | $0–5 | $5 | $10 | free tier 1 TiB queries; marts < 10 GiB initially |
| Egress to ClickHouse Cloud (`us-east4` → `us-east1` public endpoint) | $0 (self-hosted) | $20 | $0–5 | ≤ 8 GB/day compressed native inserts; co-locate in `us-east1` if the RTT probe (§7, week 2) shows < 5 ms penalty and use PSC `[R1-gpt §1.4]` |
| Cloud Logging | $0 | $0 | $0 | sampled; < 50 GiB free |
| **GCP total** | **≈ $76** | **≈ $104** | **≈ $100** | **≈ $280 of $300** |
| ClickHouse Cloud | $0 (self-host) | $0 (trial, ≈ $186 list) | $0 (self-host) or decide to pay | `[R1-gpt §2.1]` |
| Snowflake | $0 | $0 | $0 (trial sprint, ≤ $400 credits) | `[R1-gpt §3.1]` |
| Grafana Cloud | $0 | $0 | $0 | free tier |

Budget kill-switches, in order: (1) stop non-sport PM category streams; (2) narrow OpticOdds SSE to the target leagues only (`league=` param, already supported `[CODE providers/opticodds/sse.py]`); (3) lifecycle raw to Nearline at 14 d; (4) drop SharpSports league-wide `/prices` polling to 10-minute cadence; (5) pause ClickHouse inserts (raw archive continues; ClickHouse is rebuildable).

### 1.4 Volume controls (mandatory before cloud deployment)

Observed uncapped rates: OpticOdds SSE baseball (5 books) 223 records/s of which 81 % Polymarket, soccer (5 books, all leagues) 1,544 records/s `[OO-probe #6]`; OddsPapi WS unfiltered sports 10/11/13 ≈ 500 msg/s, 87 % Polymarket, 27 msg/s with the sharp/US book filter `[OP §4.10]`; DraftKings emits 433k ticks per MLB game (median 563 ms gap, re-confirmation churn) vs Pinnacle 25k `[OP §5.2]`; a single `/fixtures/odds` call for 3 fixtures × 5 books returns 4.99 MB with 811–1,401 DraftKings odds per fixture `[OO §2.4]`.

Controls:
1. **Raw archive**: keep everything, but switch the archive codec from gzip(3) to zstd(3) (≈ 30–40 % smaller for JSON) and add a per-stream `dedupe_identical` option that drops a record whose body hash equals the previous record for the same `provider_odd_id` within 2 s (re-confirmation churn is still counted in `stream_health`).
2. **ClickHouse `quotes`**: insert only rows where `(price_dec, line, active, limit_max, is_main)` changed versus the in-memory last state, or ≥ 60 s since the last insert for that key (heartbeat row, `event_kind='heartbeat'`).
3. **ClickHouse `order_book_levels`**: top 3 levels per side, and at most 1 snapshot/s per `(book, venue_market_id, selection)`; deeper ladders stay in raw. Kalshi and Polymarket show up to 10 levels, Novig 1, Betfair Exchange none (lay side is a separate book) `[OO §3.6]`.
4. **Non-sport PM stream**: replace-not-patch snapshots `[OO-sum oo-prediction-markets]` are coalesced to ≤ 1/s per market for ClickHouse; raw keeps all.
5. **Scope filters**: OpticOdds SSE `league=` limited to the trading universe (MLB, NBA, WNBA, NCAAB, NFL, NCAAF, NHL, EPL, MLS); OddsPapi WS `sportIds` 10–15 with `bookmakers` = the universe books (§2.1).

### 1.5 Runtime decision and benchmark gate

Research briefs recommend Go or Rust for a 5–20k rows/s consumer and say Python+uvloop "may handle 5k–20k simple messages/sec" but must be load-tested `[R1-gpt §5.1][R1-pplx §5]`. Our prototype already sustained ≈ 5k quotes/s + 17k levels/s end-to-end (parse → normalize → archive → ClickHouse rows) in this sandbox with zero errors `[CODE README]`. Decision: keep Python, add the acceptance benchmark from `[R1-gpt §5.1]` as a CI job that replays a captured 10-minute corpus through the exact decode/normalize/coalesce path (`u3-ingest replay` `[PR #4]`) and asserts ≥ 40k rows/s, p99 < 10 ms per message, no RSS growth over the run. If the gate fails after profiling (orjson, slots dataclasses, avoiding `asdict`), the decode+normalize stage for the OddsPapi `odds` channel is rewritten as a small Rust extension (PyO3); everything else stays Python.

### 1.6 Process inventory (systemd units on the VM)

| Unit | Command | CPU/RSS budget | Restart policy | Watchdog condition |
|---|---|---|---|---|
| `u3-op-ws.service` | `u3-ingest run --only oddspapi-ws --connections odds,fixtures,aux` | 0.6 vCPU / 1.5 GiB | `Restart=always`, `RestartSec=2` | last data frame age < 30 s on conn #1 during a live slate |
| `u3-oo-sse.service` | `u3-ingest run --only opticodds-sse --plan deploy/oo_streams.yaml` | 0.6 vCPU / 1.5 GiB | same | ≥ 1 event/min on every configured stream with active fixtures |
| `u3-ss-poll.service` | `u3-ingest run --only sharpsports --plan deploy/ss_poll.yaml` | 0.1 vCPU / 0.5 GiB | same | last successful `/prices` < 5 min |
| `u3-batch.service` | `u3-ingest batch --schedule deploy/batch.yaml` | 0.3 vCPU / 1 GiB (nice 10) | same | scheduler heartbeat < 2 min |
| `u3-sync.service` | `u3-ingest archive-sync --every 300` `[PR #3]` | 0.1 vCPU / 0.3 GiB | same | newest uploaded object per stream < 2 h old |
| `u3-board.service` (Phase 2) | `u3-board --redis localhost:6379` | 0.4 vCPU / 1 GiB | same | detector loop age < 5 s |
| `redis.service` (Phase 2) | `redis-server --maxmemory 512mb --maxmemory-policy allkeys-lru` | 0.1 vCPU / 0.5 GiB | same | ping |
| `clickhouse` (self-hosted months 1/3, Docker) | `clickhouse-server` with `max_server_memory_usage=3G` | 0.5 vCPU / 3 GiB | Docker restart | `SELECT 1` |
| `alloy.service` | Grafana Alloy scraping `:9100` (node) and `:91xx` (u3 exporters) | 0.05 vCPU / 0.2 GiB | same | remote-write success |

The `e2-standard-2` (2 vCPU / 8 GiB) fits months 1 and 3 with self-hosted ClickHouse only because inserts are coalesced and TTL is 7 days; if RSS exceeds 6.5 GiB, move ClickHouse to a Spot `e2-standard-2` or start the Cloud trial early.

### 1.7 Storage layout and retention

**GCS (`gs://u3-raw`)** — `raw/<provider>/<stream>/dt=YYYY-MM-DD/hour=HH/<stream>-<process_start_ms>.jsonl.zst` (current layout with gzip `[CODE sinks/raw.py]`; zstd from Phase 1). Streams: `oddspapi/ws-odds`, `oddspapi/ws-fixtures`, `oddspapi/ws-aux`, `oddspapi/rest-<endpoint>`, `opticodds/sse-odds-<sport>-<group>`, `opticodds/sse-results-<league>`, `opticodds/sse-pm-<category>`, `opticodds/rest-<endpoint>`, `sharpsports/prices-<scope>`, `sharpsports/rest-<endpoint>`, `bootstrap/registries`. Each hour also gets `manifest.json` (rows, bytes, sha256, min/max `recv_ns`). Lifecycle: Nearline at 30 d, Coldline at 180 d, no deletion. `gs://u3-parquet/<table>/dt=…/part-N.parquet` from nightly replay `[PR #4]`.

**ClickHouse (`u3`)** — existing: `quotes` (MergeTree, `PARTITION BY toDate(recv_ts)`, `ORDER BY (fixture_id, market, period, selection, book_id, recv_ns)`), `order_book_levels`, `fixture_xref` (ReplacingMergeTree), `quotes_latest` (MV, ReplacingMergeTree keyed by `(fixture_id, market, period, selection, line, book_id)`), `quote_latency` (view) `[CODE schemas/clickhouse.sql]`. Retention changes: `quotes` TTL 400 d → **45 d** on Cloud (7 d self-hosted), `order_book_levels` 180 d → **14 d**. Planned tables (DDL in §4.8): `settlements`, `clv`, `book_status`, `fixture_scores`, `fixture_clock`, `fixture_status`, `pm_book_snapshots`, `injuries`, `stream_health`, `mapping_unresolved`, `dim_market`, `dim_book`, `signals` (Phase 2), `orders`/`fills` (Phase 3).

**BigQuery** — dataset `u3_raw`: external tables over `gs://u3-parquet/{quotes,order_book_levels}`; dataset `u3_marts`: `dim_fixture`, `dim_book`, `dim_market`, `settlement`, `clv`, `book_lag_daily`, `player_game_log`, `injury_history`, `signals` (Phase 2). Partition by `dt`, cluster by `fixture_id, market`.

**Snowflake (optional)** — schema `SS_HISTORIC` for SharpSports player/team logs and OHLC if a month-3 research sprint needs Snowflake-specific features; otherwise BigQuery.

### 1.8 Coalescer specification

```python
class Coalescer:
    """Sits between normalizers and the ClickHouse sink. Raw archive is untouched."""
    HEARTBEAT_NS = 60_000_000_000          # emit a row at least every 60 s per key
    LEVEL_MAX = 3                          # top-N ladder levels per side
    LEVEL_MIN_GAP_NS = 1_000_000_000       # ≤ 1 snapshot/s per (book, venue_market_id, selection)

    def quote(self, q: Quote) -> Quote | None:
        key = (q.book_id, q.fixture_id, q.market, q.period, q.selection, q.line)
        last = self.state.get(key)
        sig = (q.price_dec, q.active, q.limit_max, q.is_main, q.event_kind == "lock")
        if last and last.sig == sig and q.recv_ns - last.recv_ns < self.HEARTBEAT_NS:
            self.metrics.coalesced_quotes += 1
            return None
        self.state[key] = Last(sig, q.recv_ns)
        if last and last.sig == sig:
            q.event_kind = "heartbeat"
        return q

    def levels(self, rows: list[OrderBookLevel]) -> list[OrderBookLevel]:
        out = []
        for (book, vmid, sel, side), ladder in group(rows):
            k = (book, vmid, sel, side)
            if self.last_levels.get(k, 0) + self.LEVEL_MIN_GAP_NS > ladder[0].recv_ns:
                continue
            self.last_levels[k] = ladder[0].recv_ns
            out += ladder[: self.LEVEL_MAX]
        return out
```
The `Board` (Phase 2) consumes **uncoalesced** rows in-process so trading state is never delayed by the coalescer; only ClickHouse and Redis publication are coalesced.

---

## 2. Feed usage matrix

### 2.1 Universe

Books priced against in Phase 1–2 ("universe books"): pinnacle, draftkings, fanduel, betmgm, caesars, betrivers, kalshi, polymarket, novig (OpticOdds only), prophetx, circa (`circa_sports` / `circasports`), betonline, bookmaker, betfair_exchange (+lay), prizepicks/underdog (DFS, OpticOdds + SharpSports). Present in all three vendors: betmgm, betrivers, draftkings, fanduel, kalshi, polymarket `[XJ]`. Sporttrade is `inactive` in OpticOdds `[OO §1.1]` and reportedly exited US sports betting in June 2026 `[R2-gpt §2.2]` — not modelled as an execution venue.

Leagues: MLB, NBA, WNBA, NCAAB, NFL, NCAAF, NHL, EPL, MLS (OpticOdds ids `mlb`, `nba`, `wnba`, `ncaab`, `nfl`, `ncaaf`, `nhl`, `england_-_premier_league`, `usa_-_major_league_soccer` `[OO §3.2]`; OddsPapi tournament ids 109, 132, 486, —, 31, —, 234, 17, 242 `[OP §3.2]`; SharpSports `LGUE_mlb`, `LGUE_nba`, `LGUE_wnba`, `LGUE_ncaaf`, `LGUE_nfl`, `LGUE_nhl`, EPL `LGUE_542b6c4f…` `[SS-sum ss-core]`; NCAAB is not a valid SharpSports league `[XJ]`).

**Fix required:** `novig` is in `DEFAULT_BOOKS_ODDSPAPI` but is not among OddsPapi's 31 entitled slugs `[OP §1.1][CODE pipeline.py]` — remove it (unknown slugs are silently dropped on REST `[OP §2.1]`; assert the `login_ok.bookmakers` echo on WS `[OP §10.2]`).

### 2.2 Matrix

| # | Data class | Primary provider / channel | Secondary / cross-check | Cadence | Rate-limit budget | Storage target |
|---|---|---|---|---|---|---|
| 1 | Fixture spine + cross-vendor ids | OddsPapi `GET /fixtures?sportId&startTimeFrom&startTimeTo` (7-day windows, back 400 d/forward 30 d) + WS `fixtures` channel `[OP §10.3, §10.4]` | OpticOdds `/fixtures/active?league` (+`include_statsperform_id`, 100/page `[OO §1.5]`) `[CODE pipeline.bootstrap]`; SharpSports `/events?league&startTimeStart&startTimeEnd&ascending=true` `[SS §2.3]` | forward window every 5 min; bootstrap at start | OP 6 calls/5 min of 200/min; OO 9 leagues × ≤ 3 pages per 5 min of 8,000/15 s `[OO §1.4]`; SS 9 calls/5 min of 50/s `[SS §1.4]` | `u3.fixture_xref` `[CODE schemas/clickhouse.sql]`; BQ `u3_marts.dim_fixture` |
| 2 | Pre-match sportsbook odds, main + alt lines | OddsPapi WS `odds`+`bookmakers`, `receiveType=zstd-dict`, `sportIds 10–15`, universe books (conn #1) `[OP §10.2]` | OpticOdds SSE `/stream/odds/{sport}?sportsbook×5&league×≤10` per book-group `[OO §2.10]`; OddsPapi REST `/fixtures/odds/main?fixtureIds≤50&since` reconciliation sweep `[OP §10.3]` | WS push (10²–10³ msg/s uncapped); sweep every 60 s | OP odds bucket 10/s: sweep ≈ 2/s, on-demand snapshots ≤ 3/s, ≥ 3/s headroom `[OP §10.3]`; OO SSE connects 250/15 s `[OO §1.4]` | raw GCS; `u3.quotes` (coalesced); `u3.quotes_latest` MV |
| 3 | Player props | OpticOdds SSE (229 books, props on most; `player_id`, `grouping_key`) `[OO §3.6]` | OddsPapi (19 of 31 books with `playerProps:true`; 2,835 prop quotes on one EPL fixture) `[OP §1.1, §8.3]`; SharpSports `/prices?eventId&book` for US books `[SS §2.1]` | SSE push; OP WS push | included in #2 | `u3.quotes` (market `player:*`, `player_id`) |
| 4 | In-play odds | OddsPapi WS (`access.live:true`; Pinnacle `maxDelayLiveInSec` 2 s, Betfair 1 s) `[OP §7.1]` | OpticOdds SSE `is_live` per record (49 % of baseball stream) `[OO §3.6][OO-probe entitlements]` | push | included in #2 | `u3.quotes` (`extra.is_live`, status from #10) |
| 5 | Sports prediction-market order books (Kalshi, Polymarket, Novig, ProphetX, Betfair, SX) | OpticOdds SSE/REST `order_book [[price,size]]` (Kalshi/Polymarket up to 10 levels), `limits.max` (= top-of-book size), `source_ids` (Kalshi ticker + yes/no, Polymarket clobTokenId, Novig uuids, Betfair ids), `exclude_fees=true` (Polymarket `price` is fee-adjusted by default) `[OO §3.6]` | OddsPapi `meta` ladders for `polymarket`, `kalshi`, `betfair-ex`, `sx.bet` with USD notional per rung (`limit = size × cents`) `[OP §3.6, §8.1]` | push | included in #2 | `u3.order_book_levels` (top-3, ≤ 1/s), raw full depth |
| 6 | Non-sport prediction markets (politics, crypto, …) | OpticOdds `/stream/prediction-markets?category=` (one category per connection; full two-sided depth per snapshot; `canonical_id` on 95 % of politics snapshots) + REST `/prediction-markets/canonical-events` (≤ 25 ids/call; `question` present live) `[OO §2.9, §2.10, §3.11][OO-probe #9]` | none — OddsPapi sportIds 69–78 not entitled `[OP §1.1]` | push (politics 933 snapshots/s) | separate backend, no rate-limit headers `[OO §1.3]` | raw GCS; `u3.pm_book_snapshots` (≤ 1/s per market) |
| 7 | Futures / outrights | OpticOdds REST `/futures/odds?league&sportsbook×5` (NFL × 5 books = 5,755 odds / 2.45 MB) — the SSE futures stream emitted 0 events in 30–60 s windows `[OO §2.4, §2.10]` | OddsPapi futures **metadata only** (`/futures`, WS `futures`); prices not entitled (403 `channel_not_allowed`) `[OP §2.4]` | poll every 15 min per league × 3 book-groups | ≈ 30 calls/15 min of 8,000/15 s | `u3.quotes` (`market=future:<slug>`), raw |
| 8 | Sharp anchor (Pinnacle) | OddsPapi `pinnacle` with per-side `limit` (19,354 fav / 3,000 dog), `bookmakerChangedAt`, native `bookmakerMarketId` `[OP §8.1, §8.2]` | OpticOdds `pinnacle` (`limits.max` 1,000–15,850 on NFL mains) `[OO §3.6]`; SharpSports `pn` (main markets only) `[SS §1.1][SS-sum ss-market-taxonomy]` | push | — | `u3.quotes`; cross-provider latency view (Phase 1) |
| 9 | Book health / staleness | OddsPapi WS `bookmakers` (`staleOdds`, `suspended`, `hasOdds`, `participantsRotated`) + `GET /bookmakers` every 60 s (`lastOddsAt`, `staleOddsSince`, `staleThresholdSec`, `maxDelay*`) `[OP §7.2, §10.3]` | OpticOdds `/sportsbooks/last-polled?league` every 60 s (Unix-seconds timestamps; Kalshi poller was 1,595 s stale at 07:24Z) `[OO §1.1, §3.3]`; SSE `locked-odds` | 60 s | OP 1/min of 200/min; OO 9/min | `u3.book_status`; `u3.stream_health` |
| 10 | Scores, clock, in-play state | OddsPapi WS `fixtures`+`scores`+`clocks` (conn #3) `[OP §10.2]` | OpticOdds `/stream/results/{sport}?league=` — one connection per league `[OO §1.4]` (`in_play` period/clock/runners/down-distance `[OO §3.9]`) | push | 1 SSE connection per in-season league | `u3.fixture_scores`, `u3.fixture_clock` |
| 11 | Results, grading, settlement | OddsPapi `/fixtures/settlement?fixtureId` (bookmaker-independent WIN/LOSE/PUSH/HALFWIN/HALFLOSS/CANCELLED/UNDECIDED; ≥ 1 y retention; 4–9 s latency; player props not graded) `[OP §3.9, §5.2, §8.6]` | OpticOdds `/grader/odds` (Won/Lost/Refunded/Pending/Half Won/Half Lost; market label + selection `name`) `[OO §2.6, §3.10]`, `/fixtures/results` (`market_stats`), `/fixtures/player-results` `[OO §3.9]` | `trueEndTime`+15 min then 30 m/2 h/6 h/24 h retries; concurrency ≤ 3 | OP ≤ 40 fixtures/min; OO grader ≤ 100/min | `u3.settlements` (transition history), BQ `u3_marts.settlement` |
| 12 | Opening / closing lines, CLV | OddsPapi `/fixtures/odds/clv?fixtureId` at `trueStartTime`+30 min and `trueEndTime`+6 h (`clv` null pregame; 17–39 % null post-match → fallback chain) `[OP §8.5]` | OpticOdds `/fixtures/odds/historical` `olv`/`clv` (`clv` null until ~2 days after the game) `[OO §3.7]`; **our own** T−60 s / T−5 s freeze snapshots `[OP §10.3]`; SharpSports `/prices/historic/summary` (first/last per book) `[SS §2.1]` | per fixture | OP 200/min; OO historical 50/15 s `[OO §1.4]` | `u3.clv`; BQ `u3_marts.clv` |
| 13 | Tick-history backfill (pre-season, research) | OddsPapi `/fixtures/odds/historical?fixtureId&bookmaker=pinnacle` (always) + `oddsIds=` main lines across ≤ 8 books (selective); ≈ 220–230 d retention `[OP §5.2, §10.4]` | OpticOdds `include_timeseries=true` (requires `market`; change-level `entries`, retained 57–60 d) `[OO §2.4, §3.7][OO-probe #4]`; SharpSports `/prices/historic/timeseries` rollup 5 m–1 d (≤ 1,000 windows) `[SS §2.1]` | one-off + nightly for yesterday's fixtures | OP 200/min but 6–96 MB bodies → stream-parse, concurrency 2; OO 50/15 s | ClickHouse `u3.quotes` with `event_kind='history'`; BQ |
| 14 | Injuries, lineups, news | OpticOdds `/injuries?league` diff-polled every 60 s (paginated live; statuses `il_60-day`, `il_7-day`, `out`, `suspended`; no timestamps) + `/fixtures?include_starting_lineups=true` 2 h before start `[OO §2.7, §3.10, §3.4]` | SharpSports `/injuries?league` (free-text status, `played` outcome flag; historical) `[SS §2.4]`; OddsPapi WS `injuries`/`lineups` (silent so far) `[OP §9.4]` | 60 s / 2 h | OO 9/min | `u3.injuries` (diffs), BQ |
| 15 | Player/team stats, DVP, park factors, projections | SharpSports `/players/{id}/historicData` (Ohtani 477 games; soccer empty), `/marketSelections/{id}/metadata` (L1–L20 hit rates — `hits` counts overs regardless of side), `/teams|players/aggregateStats`, `consensusProjection` `[SS §2.2, §2.4][SS-sum ss-historicdata]` | OpticOdds `/fixtures/player-results` (`market_stats` map 1:1 to prop markets) `[OO §3.9]` | nightly batch; pre-game T−3 h for slate | SS 50/s (historic summary queries 13–98 s, some time out — never in hot path `[SS §1.7]`) | BQ `u3_marts.player_game_log`, `dim_player`; Snowflake sprint |
| 16 | DFS pick'em lines | OpticOdds sportsbook ids per payout structure (`prizepicks`, `prizepicks_5_or_6_pick_flex_`, `underdog_fantasy_2_pick_`, `draftkings_pick_6_`, `dabble_*`, `betr_picks`, …) `[OO §3.2][OO-sum oo-entities-a]` | SharpSports `/prices?league&book=pp,ud` (all odds fixed +100; 3.78 MB / 5.3 s per league) `[SS §1.7][SS-sum ss-core]` | SSE push; SS every 120 s per league | SS 9 calls/2 min | `u3.quotes` (book_id `prizepicks`, `underdog`) |
| 17 | Public/sharp flow (betSync) | SharpSports `/betSlips` (only our linked bettors; refresh 1/60 s per account; minutes-scale) `[SS §2.5]` | — | Phase 3 | 20/s | BQ `u3_marts.bet_slips` |
| 18 | FX for limit normalization | OddsPapi WS `currencies` (≈ 0.18/s) + `GET /currencies` hourly (USD base; `Bookmaker.limitCurrency`) `[OP §3.11, §7.2]` | — | hourly | negligible | `u3.dim_currency` |
| 19 | Reference catalogues | OddsPapi `/markets?sportId` × 6 (4,902 markets for basketball), `/bookmakers`, `/tournaments`, `/participants`, `/players` `[OP §10.4]`; OpticOdds `/sportsbooks` (229), `/markets`, `/market-types` (43), `/leagues/active` (354) `[OO §2.1]`; SharpSports `/books` (12 odds-feed books), `/markets`, `/segments` (95), `/metrics` (278) `[SS §1.1, §2.4]` | — | daily + on unknown id | trivial | `u3.dim_*` (SCD-2), repo YAML for overrides |

### 2.3 Stream subscription plans (exact)

**OddsPapi WebSocket (5-connection cap `[OP §1.4]`)**

| Conn | `login` frame (apiKey redacted) | Purpose | Notes |
|---|---|---|---|
| #1 odds | `{"type":"login","apiKey":"***","clientName":"u3-op-odds","lang":"en","receiveType":"zstd-dict","channels":["odds","bookmakers"],"sportIds":[10,11,12,13,14,15],"bookmakers":["pinnacle","draftkings","fanduel","betmgm","caesars","betrivers","kalshi","polymarket","prophetx","circasports","betonline.ag","bookmaker.eu","betfair-ex","sx.bet"]}` | the money feed | `bookmakers` gating drops envelopes with no matching keys `[OP §4.2]`; verify with the `login_ok.bookmakers` echo that a 14-slug filter is accepted (the probe used 5) |
| #2 odds shadow (Phase 2) | identical to #1, second process | failover across `reconnect` releases; dedupe by `(oddsId, changedAt)` | optional until capital is live `[OP §10.2]` |
| #3 anchor | `{"type":"login",…,"receiveType":"zstd","channels":["fixtures","scores","clocks"],"sportIds":[10,11,12,13,14,15]}` | fixture dimension, `trueStartTime`/`trueEndTime`, scores, clock | `fixtures` is ~30× chattier than `scores` — keep it off #1 `[OP §4.10]` |
| #4 aux | `{"type":"login",…,"receiveType":"json","channels":["currencies","futures","bookmakersFutures","events","stats","injuries","lineups"],"sportIds":[10,11,12,13,14,15]}` | schema discovery; FX | six of these channels never emitted during the probe `[OP §4.10]` |
| #5 spare | — | reconnect overlap (connect-new-before-close-old), console, debugging | never used in steady state `[OP §10.2]` |

**OpticOdds SSE (≤ 5 books and ≤ 10 leagues per odds connection; results = one connection per league; 250 connects/15 s `[OO §1.4]`)**

| Stream | Sport → leagues | Book group (≤ 5) | Params | Conns |
|---|---|---|---|---|
| `/stream/odds/baseball` | `mlb` | G1 `pinnacle,draftkings,fanduel,betmgm,caesars` · G2 `kalshi,polymarket,novig,prophet_x,betfair_exchange` · G3 `circa_sports,betonline,bookmaker,betrivers,betfair_exchange_lay_` · G4 `prizepicks,underdog_fantasy_2_pick_,prizepicks_5_or_6_pick_flex_,draftkings_pick_6_,fliff` | `include_fixture_updates=true&exclude_fees=true` (raw exchange prices; fee model applied by us) | 4 |
| `/stream/odds/basketball` | `nba,wnba,ncaab` | G1–G4 | same | 4 |
| `/stream/odds/football` | `nfl,ncaaf` | G1–G4 | same | 4 |
| `/stream/odds/hockey` | `nhl` | G1–G4 | same | 4 |
| `/stream/odds/soccer` | `england_-_premier_league,usa_-_major_league_soccer` | G1–G4 | same | 4 |
| `/stream/results/{sport}` | one per in-season league (≤ 9) | — | `league=<id>` | ≤ 9 |
| `/stream/prediction-markets` | — | — | `category=politics` (default); others on demand | 1 |
| `/stream/futures/{sport}` | — | — | not used (silent); poll `/futures/odds` instead `[OO §2.10]` | 0 |

≈ 30 steady-state connections; a full reconnect storm costs 30 of the 250/15 s connect budget. Every connection is archived under its own stream name so replay can rebuild per group.

**SharpSports (no streaming; polling plan)** — see §2.4.

### 2.4 `u3-batch` schedule (cron, UTC)

| Job | Vendor / endpoint | Cron | Budget | Output |
|---|---|---|---|---|
| `op.fixtures.forward` | `GET /fixtures?sportId=S&startTimeFrom=now&startTimeTo=now+14d` × 6 | `*/5 * * * *` | 6/5 min of 200/min | `fixture_xref`, `map_fixture_external` |
| `op.fixtures.live` | `GET /fixtures/live?sportId=S` × 6 | `* * * * *` | 6/min | status/live set |
| `op.bookmakers.health` | `GET /bookmakers` | `* * * * *` | 1/min | `book_status`, `dim_book` |
| `op.sweep.main` | `GET /fixtures/odds/main?fixtureIds≤50&since=<cursor>` sharded over in-window fixtures | continuous loop, ≈ 2 req/s | odds bucket 10/s | reconciliation, inactive removals |
| `op.freeze` | `GET /fixtures/odds?fixtureId=…` at T−60 s and T−5 s | event-driven | ≤ 1/s | `quotes` `event_kind='freeze'` |
| `op.markets` | `GET /markets?sportId=S` × 6 | `15 3 * * *` + on unknown `marketId` | trivial | `dim_market`, `dim_outcome` |
| `op.currencies` | `GET /currencies` | `0 * * * *` | 1/h | `dim_currency` |
| `op.mapping` | `GET /fixtures/mapping?bookmaker=<slug>&fixtureIds=<batch>` for 8 execution books | on fixture discovery | 8 calls/batch | `map_fixture_bookmaker` |
| `op.settlement` | `GET /fixtures/settlement?fixtureId` | `trueEndTime`+15 m, retries 30 m/2 h/6 h/24 h | concurrency 3 (4–9 s each) | `settlements` |
| `op.clv` | `GET /fixtures/odds/clv?fixtureId` | `trueStartTime`+30 m, `trueEndTime`+6 h | 200/min | `clv` |
| `oo.fixtures.active` | `GET /fixtures/active?league=L&include_statsperform_id=true` × 9 | `*/5 * * * *` | ≤ 27 calls/5 min | `fixture_xref` |
| `oo.last_polled` | `GET /sportsbooks/last-polled?league=L` × 9 | `* * * * *` | 9/min | `book_status` |
| `oo.injuries` | `GET /injuries?league=L` × 9 (paginated) | `* * * * *` | ≤ 27/min | `injuries` (diffs) |
| `oo.lineups` | `GET /fixtures?id=…&include_starting_lineups=true` | T−2 h, T−30 m | event-driven | `fixture_lineups` |
| `oo.futures` | `GET /futures/odds?league=L&sportsbook×5` × 3 groups × 9 leagues | `*/15 * * * *` | 27/15 min | `quotes` (`future:*`) |
| `oo.rehydrate` | `GET /fixtures/odds?fixture_id×5&sportsbook×5` for fixtures active in the last 10 min | on SSE reconnect | ≤ 8,000/15 s | `quotes` `event_kind='snapshot'` |
| `oo.grader` | `GET /grader/odds?fixture_id&market&name` for traded selections; `GET /fixtures/results`, `/fixtures/player-results` | completion + 2 h; nightly | ≤ 100/min | `settlements` (provider `opticodds`), `fixture_stats` |
| `oo.pm.canonical` | `GET /prediction-markets/canonical-events/ids?category` → `/canonical-events?canonical_id×25` | `30 * * * *` | PM backend | `dim_pm_canonical` |
| `oo.historical` | `GET /fixtures/odds/historical?fixture_id&sportsbook×5&market=…&include_timeseries=true` for yesterday's traded fixtures | `0 9 * * *` | 50/15 s | `quotes` `event_kind='history'`, `clv` |
| `ss.prices.event` | `GET /prices?eventId=<id>` for fixtures in T−2 h … T+4 h | every 60 s per event | 50/s | `quotes` |
| `ss.prices.dfs` | `GET /prices?league=L&book=pp,ud` × 9 | `*/2 * * * *` | 9/2 min | `quotes` |
| `ss.prices.pinnacle` | `GET /prices?league=L&book=pn` × 9 | `*/5 * * * *` | 9/5 min | cross-check |
| `ss.events` | `GET /events?league=L&startTimeStart&startTimeEnd&ascending=true` × 9 | `*/10 * * * *` | 9/10 min | `fixture_xref` |
| `ss.injuries` | `GET /injuries?league=L` × 9 | `*/5 * * * *` | 9/5 min | `injuries` |
| `ss.historic.nightly` | `/players/{id}/historicData`, `/marketSelections/{id}/metadata` (T−3 h), `/prices/historic/summary?eventId` + `/timeseries` for yesterday | `0 8 * * *` + T−3 h | paged, concurrency 2 | BQ `player_game_log`, `clv` (SS) |
| `ss.reference` | `/books`, `/books?status=unsupported`, `/markets` (paged), `/segments`, `/metrics`, `/leagues`, `/teams`, `/players` | `0 4 * * *` | trivial | `dim_*` |
| `sync.parquet` | `u3-ingest replay --since <yesterday> --until <today> --out gs://u3-parquet --out-format parquet` `[PR #4]` | `30 6 * * *` | local CPU | BigQuery external tables |
| `qa.mapping_report` | ClickHouse queries (§6.3) | `0 7 * * *` | — | `mapping_unresolved`, Slack digest |
| `ops.retention_probe` | OddsPapi CLV watermark; OpticOdds timeseries watermark | `0 5 * * 1` | trivial | SLO §6.4 |

---

## 3. Canonical model & mapping strategy (summary)

The full identity-resolution design belongs in `docs/research/cross-provider-mapping.md` (pending); this section states what is implemented and the QA loops.

**Canonical records** `[CODE u3ingest/canonical/models.py]`:
- `Quote(recv_ns, provider, book_id, provider_book, fixture_id, provider_fixture_id, market, period, selection, line, price_dec, price_us, is_main, active, limit_max, source_ts_ms, gateway_ts_ms, provider_market, provider_selection, provider_odd_id, player_id, team_id, event_kind, grouping_key, extra)`. Identity of a tradeable outcome across providers = `(book_id, fixture_id, market, period, selection, line)`.
- `OrderBookLevel(recv_ns, provider, book_id, fixture_id, market, period, selection, venue_market_id, side back|lay|bid|ask, level, price, size, source_ts_ms, provider_odd_id)`.
- `FixtureRef` with `opticodds_id`, `opticodds_game_id`, `oddspapi_id`, `sharpsports_id`, `betradar_id`, `pinnacle_id`, `statsperform_id`, `sportradar_id`, `the_odds_api_id`, rotation numbers.

**Market keys** `[CODE canonical/markets.py]`: `moneyline | 3way | spread | total | team_total | player:<metric> | team_prop:<metric> | other:<slug>`; periods `full | reg | 1h | 2h | 1q..4q | 1p..3p | f5i | 1i | set1..`; selections `home | away | draw | over | under | yes | no | team:<id> | player:<id>[:over|under]`. OddsPapi is mapped from its frozen `marketType/period/handicap` catalogue (line lives in `Market.handicap`, one `marketId` per line `[OP §3.13]`); OpticOdds from `market` display names/`market_id` slugs (`run_line`, `total_runs`, `player_hits`, `4th_quarter_moneyline_incl_ot_` `[OO §3.2]`); SharpSports from the `Market.name` grammar (`[1st Half ] Player Prop Total <metric>`) `[SS-sum ss-market-taxonomy]`. `participantsRotated` flips home/away and spread sign for that book `[OP §3.4][CODE providers/oddspapi/normalize.py]`.

**Books** `[CODE mapping/registry.py]`: canonical slug → per-provider aliases (e.g. `pinnacle` ⇐ OpticOdds `pinnacle|ps3838|ps4848`, OddsPapi `pinnacle`, SharpSports `pn`). Unknown books are kept as `<provider>:<slug>` and counted in `BookRegistry.unknown`. OpticOdds regional/product clones (`caesars_pennsylvania_`, `betrivers_new_york_`, `prizepicks_5_or_6_pick_flex_`) `[OO §3.2]` map to the base book with a `variant` attribute (Phase 1 schema addition).

**Fixtures** — resolution order `[CODE mapping/registry.py][XJ]`:
1. OddsPapi `externalProviders.opticoddsId == OpticOdds fixture.id` — exact; MLB 40/40, EPL 8/8, NCAAF 114/125; start times identical. Coverage of `opticoddsId` across all OddsPapi fixtures is only 2,593 of 19,954 because OddsPapi carries far more (non-US, lower-tier) fixtures than OpticOdds prices `[XJ]`.
2. SharpSports `event.oddsjamId == OpticOdds fixture.game_id` — MLB 37/40 `[XJ]`; `game_id` is the legacy v2 id and the prefix of every OpticOdds odd id `[OO §3.2]`.
3. Normalized team names + start time within ± 15 min in the same league — EPL 8/8, NCAAF 73/87, MLB 3/40 `[XJ]`.
4. Planned: rotation numbers (`participant1RotNr` ↔ `home_rotation_number`; OpticOdds populates 51 % MLB, 91 % ATP/WTA, 67 % NCAAF rows `[OO §3.2]`) as a fourth key for US sports `[OP §6.2]`; Sportradar/Betradar ids only with a verified crosswalk (SharpSports `sportradarId` is a UUID, OddsPapi `betradarId` an int — different namespaces).
5. Canonical id = OpticOdds id when known, else `<provider>:<id>`, re-keyed when a later join succeeds (`FixtureRegistry._index`).

**Players/teams**: OpticOdds ids are league-scoped (`base_id` links across leagues) `[OO §3.2]`; SharpSports `Player.oddsjamId` is a 12-hex OddsJam id `[SS-sum ss-core]` — test whether it equals OpticOdds `player.id` (Phase 1 QA job); OddsPapi `playerId` ints join only by name + team + sport until proven otherwise `[OP §3.11]`.

**QA loops (Phase 1 deliverables):**
- `u3.mapping_unresolved` table fed from `FixtureRegistry.unresolved` and `BookRegistry.unknown` every 60 s; nightly `mapping-report` job lists the `other:*` market tail by volume, unknown books, unresolved fixtures per league with candidate matches, and coverage ratios (§6.3). Threshold alerts: `opticoddsId` join < 95 % for MLB/NFL/EPL, SharpSports join < 90 % for MLB.
- `mapping/overrides.yaml` in the repo (book aliases, market aliases, forced fixture pairs) hot-reloaded by the pipeline; every override carries an `evidence` note and expiry.
- Contract tests on real samples (`tests/test_normalize.py`) extended with one golden fixture per league per provider; CI fails on any canonical-key regression.
- Duplicate-fixture detector: two canonical ids with the same `(league, home, away, start ± 15 min)` → merge candidate in the report.
- Cross-provider price sanity: for the six books present in all three vendors, `|price_dec_OP − price_dec_OO| > 3 %` on the same canonical key for > 2 min → mapping bug alert (also catches `participantsRotated` and line-sign errors).
- Fee-basis sanity: OpticOdds Polymarket/Kalshi prices with `exclude_fees=true` must equal `order_book[0][0]` `[OO §3.6]`; any drift flags a parameter regression.

---

## 4. Ingestion services spec (per connector)

Legend: ✅ implemented (Phase 0), 🔶 partially, ⬜ planned (Phase 1 unless noted).

### 4.1 OddsPapi WebSocket (`u3-op-ws`)

| Aspect | Spec |
|---|---|
| Protocol | `wss://v5.oddspapi.io/ws`; first frame `login` within 10 s; login-only subscriptions (any filter change = new connection); max 5 concurrent connections; control frames JSON text, data frames per negotiated `receiveType` `[OP §4.1–4.2]` ✅ client `[CODE providers/oddspapi/ws.py]` |
| Subscription plan | §2.3 table. 🔶 today: one connection, `odds,bookmakers,fixtures`, `json` `[CODE pipeline.run_oddspapi_ws]` → ⬜ split into three connections and default `zstd-dict` (the `dict` frame handling exists ✅) |
| Resume/replay | persist `serverEpoch` + `lastSeenId[channel]` to SQLite every 250 ms; on reconnect send cursors only for channels in `login_ok.resume.replayChannels` and only if `now − ts(entryId) < resumeWindowMs − 5 s` (60 s window observed) `[OP §4.6]`; `odds` may not be replayable → treat every odds reconnect as `snapshot_required` ✅ cursor tracking in memory; ⬜ persistence + age rule |
| `snapshot_required` / `reconnect` | non-fatal; keep consuming, buffer, run REST `/fixtures/odds/main?fixtureIds≤50` for in-window fixtures, apply baseline, drain buffered updates with `changedAt ≥ snapshot_ts` `[OP §4.5–4.6, §10.6]`; on `reconnect` open the spare slot first ✅ detection/logging; ⬜ automatic REST snapshot |
| Backfill | fixture spine 400 d back in 7-day windows (≈ 372 calls); settlement for all finished fixtures (≥ 1 y); CLV for fixtures ≤ 220 d; Pinnacle tick history always, other books via `oddsIds` for main lines `[OP §10.4]` ⬜ `u3-ingest backfill oddspapi --phase spine|settlement|clv|ticks` |
| Raw archival | every frame (decoded JSON + `recv_ns`, `channel`, `ts`, `entryId`, `raw_len`, control frames) → `raw/oddspapi/ws-odds/dt=/hour=/…` ✅ `[CODE sinks/raw.py]`; ⬜ zstd codec, per-connection stream names (`ws-odds`, `ws-fixtures`, `ws-aux`) |
| Normalization | `OddsPapiNormalizer.quotes` joins `outcomeId → marketId → handicap`, resolves `participantsRotated`, emits ladders from `meta.back/lay` ✅; ⬜ `betfair-ex` `availableToBack/availableToLay` and `sx.bet` shapes (`limit = size × cents`) `[OP §3.6]`; ⬜ `limit` currency normalization via `limitCurrency` |
| Sinks | raw → GCS; coalesced `u3.quotes`, `u3.order_book_levels`; `u3.book_status` from `bookmakers`; `u3.fixture_scores`/`u3.fixture_clock` from conn #3 ⬜ |
| Observability | per connection: msgs/s, bytes/s, decode p50/p99, `recv − ts` p50/p99 (108 ms observed from the sandbox `[OP §7.1]`), `entryId` gap count, reconnects, close codes, `snapshot_required` count, per-book `staleOdds` minutes; assert `login_ok` echo (channels, bookmakers, `access`, `resume`) equals the request and alert on drift `[OP §10.2, §10.7]` 🔶 counters in `ws.stats` → ⬜ Prometheus |
| Failure modes | 4000 client bug (fail fast), 4001 key revoked (stop, page), 4002 backpressure (switch to zstd-dict, narrow filters, move parse off socket task), 4003 too many connections (serialize connects with jitter), 1006/1011 reconnect with 1/2/5/10 s jittered backoff, 1009 raise `max_size` (16 MiB set) `[OP §4.9, §10.6]` ✅ backoff/close-code handling; ⬜ paging |

### 4.2 OddsPapi REST (`u3-batch`)

| Aspect | Spec |
|---|---|
| Protocol | `https://v5.oddspapi.io/en`, `?apiKey=` (key in URL → redact everywhere; never persist raw URLs) `[OP §1.2, §9.3]`; browser-like UA required (Cloudflare 1010) ✅ `[CODE providers/oddspapi/rest.py]`; no pagination, bodies up to 95.6 MB → stream-parse history endpoints ⬜ (`ijson`) |
| Poll plan | §2.4 rows `op.*`. Odds bucket (10/s, shared by `/fixtures/odds`, `/fixtures/odds/main`): sweep ≈ 2 req/s (`since` also returns inactive odds → correct removals), deep snapshot on `snapshot_required`/divergence, pre-kick freeze `[OP §10.3]`. 200/min-per-endpoint bucket for the rest ✅ limiters; 🔶 bootstrap only → ⬜ scheduler |
| Resume/replay | idempotent jobs keyed by `(endpoint, params, window)`; `since` cursor per sweep persisted in SQLite ⬜ |
| Backfill | see §4.1; settlement first (cheapest, deepest ground truth) `[OP §10.4]` ⬜ |
| Raw archival | every body with redacted URL, status, `x-ratelimit-*`, `cf-ray`, latency, size → `raw/oddspapi/rest-<endpoint>/…` ✅ (bootstrap) / ⬜ (all jobs) |
| Normalization | same normalizer with `kind='snapshot'`; CLV → `u3.clv`; settlement → `u3.settlements` as transition history keyed `(fixtureId, marketId, outcomeId, playerId, observed_at)` `[OP §10.5]` ⬜ |
| Sinks | ClickHouse + BQ marts (daily Parquet export) ⬜ |
| Observability | per job: calls, 429s, `Retry-After` honoured, body bytes, latency (settlement 4–9 s), divergence rate of sweep vs stream (< 0.1 % target) `[OP §10.7]` ⬜ |
| Failure modes | 429 → honour `Retry-After`, halve concurrency for a window; 503 `rate_limiter_error` → back off 5 s ×3 then degrade to WS-only; 403 `channel_not_allowed`/`bookmaker_not_allowed`/`sport_not_allowed` → entitlement change: disable job, page; 400 `invalid_filters` → programming error, fail loudly; silent `[]` on entitled in-season sport → alarm `[OP §10.6]` ✅ retry/limiter; ⬜ classification + paging |

### 4.3 OpticOdds SSE (`u3-oo-sse`)

| Aspect | Spec |
|---|---|
| Protocol | `GET /stream/odds/{sport}?key=&sportsbook×≤5&league×≤10&include_fixture_updates=true&exclude_fees=true`, `/stream/results/{sport}?league=`, `/stream/prediction-markets?category=`; events `connected`, `ping` (5 s, server wall clock), `odds`, `locked-odds`, `fixture-status`, `fixture-results`, `snapshot`; payload `{data:[…], entry_id:"<ms>-<seq>"}`; SSE record has 27 keys incl. `fixture_id`, `sportsbook_id`, `league_id`, `is_live` `[OO §2.10, §3.6, §3.12][CODE providers/opticodds/sse.py]` ✅ |
| Subscription plan | §2.3 table (5 sports × 4 book groups + results per league + PM politics ≈ 30 connections). 🔶 today: one 5-book connection per sport, no `league=` filter (soccer all leagues = 1,544 rec/s `[OO-probe #6]`) → ⬜ book-groups + league filter, `exclude_fees=true` |
| Resume/replay | **`last_entry_id` replay does not work** (4 tests, all restarted at "now") `[OO-probe #7]`; `entry_id` can be out-of-order/duplicated on soccer → dedupe on odd `id` + `timestamp`; on every reconnect emit a `ReconnectMarker` ✅ and ⬜ re-hydrate affected fixtures via REST `/fixtures/odds?fixture_id×5&sportsbook×5` for fixtures active in the last 10 min (standard tier) |
| Backfill | `/fixtures/odds/historical?fixture_id&sportsbook×5&market=…&include_timeseries=true` (change-level `entries`, int-second timestamps, retained 57–60 d) for CLV/OLV research on traded leagues; ≤ 50/15 s `[OO §2.4, §3.7]` ⬜ |
| Raw archival | every event incl. `ping` (for clock offset; +0.7 s local-vs-server observed `[OO §3.13]`) and reconnect markers → `raw/opticodds/sse-odds-{sport}-{group}/…` ✅ (per sport) / ⬜ (per group) |
| Normalization | `OpticOddsNormalizer.quotes_from_sse` (`locked-odds` → `event_kind='lock'`, `active=False`), `order_book` → levels (`side='back'`), `source_ids.market_id` as `venue_market_id` ✅; ⬜ `fixture-status` → `u3.fixture_status`; ⬜ accept `limits.max` and `limits.max_stake`; ⬜ store `extra.fee_adjusted=false` when `exclude_fees=true`; ⬜ map `sportsbook_id` clones to base book + variant |
| Sinks | raw; coalesced ClickHouse; PM snapshots → `u3.pm_book_snapshots` ⬜ |
| Observability | events/s per connection, `recv − timestamp` p50/p99 (baseline 7 ms baseball / 32 ms soccer, p99 0.2–0.33 s `[OO-probe #6]`), reconnects, dup/out-of-order ids, `locked-odds` rate per book, ping gap ⬜ |
| Failure modes | idle > 20 s → reconnect with backoff (1→32 s) ✅; HTTP 429 → wait ≥ 15 s `[OO §1.4]`; ≥ 5 reconnects/min on one stream → alert; stream with 0 events for 10 min during a live slate → alert; PM category invalid → 4xx with the valid list `[OO §1.6]` |

### 4.4 OpticOdds REST (`u3-batch`)

| Aspect | Spec |
|---|---|
| Protocol | `X-Api-Key` header; standard 8,000/15 s observed (docs 2,500), historical 50/15 s (docs 10), windows are fixed 15 s wall-clock, 429 semantics untested `[OO §1.4]`; limiters keep the documented figures `[CODE providers/opticodds/rest.py]` ✅; pagination `{cursor,data,has_more,page}` with page size 100 `[OO §1.5]` ✅ |
| Poll plan | §2.4 rows `oo.*` 🔶 |
| Resume/replay | idempotent; `updated_since` returned 0 rows in tests — do not rely on it `[OO §2.3]` |
| Raw archival | all bodies ✅/⬜ as above; **`/fixtures/results/queue/status` output is secret (echoes the API key in `queue_name`)** — never archive unredacted `[OO §1.1]` |
| Normalization | `quotes_from_fixture_rows` ✅; grader/results → `u3.settlements` (provider `opticodds`), `market_stats` → `u3.fixture_stats` ⬜; injuries diffs keyed by `injury.id = <sport>:<league>:<player_id>` `[OO §3.2]` ⬜ |
| Failure modes | 400 validation bodies (`maximum 5 sportsbooks allowed`, `you must provide at least one of fixture_id, player_id, or team_id`) are programming errors `[OO §1.6]`; unknown sportsbook ids are silently ignored → validate against `/sportsbooks` at bootstrap `[OO §1.6]` ⬜ |

### 4.5 SharpSports REST (`u3-ss-poll` + `u3-batch`)

| Aspect | Spec |
|---|---|
| Protocol | `https://api.sharpsports.io/v1`, `Authorization: Token <private key>` for `/events`, `/prices`, historic (Bearer → 401); 50 rps general, 20 rps large-list; 429 `{"detail":"Request was throttled."}`; no rate-limit headers `[SS §1.2–1.4]` ✅ `[CODE providers/sharpsports/rest.py]` |
| Poll plan | **redesign**: today `/prices?league=` for every universe league every 30 s (17.5 MB, 2–7 s per call `[SS §1.7]`) 🔶 → ⬜ §2.4 rows `ss.*`: per-event `/prices?eventId` (1.67 MB, 0.28 s) inside T−2 h…T+4 h, DFS books every 2 min, Pinnacle cross-check every 5 min; never `/marketSelections?league=` (20–32 s) `[SS §1.7]` |
| Resume/replay | stateless snapshots; `recv_ns` is the only timestamp (`/prices` carries none `[SS-sum ss-betprices]`) |
| Backfill | `historicData` batch: `/players/{id}/historicData` for rostered players of traded leagues (nightly; 0.8–10.7 s each, 14–24 s with any query param `[SS §1.7]`), `/marketSelections/{id}/metadata` for tonight's prop selections (T−3 h), `/prices/historic/summary?eventId&pageSize=100&pageNum=n` + `/timeseries` for yesterday's events (1–4 s per page; player/team-scoped summaries take 55–98 s or time out — avoid) `[SS §1.7, §2.1]` ⬜ |
| Raw archival | ✅ `raw/sharpsports/prices-poll/…`; ⬜ per-job streams |
| Normalization | `SharpSportsNormalizer.quotes` (American → decimal, `main`, `live`, `impliedProbability`, `market_selection_id` in `extra`) ✅; ⬜ `bookIds` (sportsbook-native event/market/selection ids, present on every price `[SS §1.1]`) into `extra` as a book-native crosswalk; ⬜ historic OHLC → `u3.quotes` (`event_kind='ohlc'`); player logs → BQ |
| Observability | bytes and latency per call (binding constraint), events count per league vs OpticOdds (join coverage), 429 count ⬜ |
| Failure modes | 403 "private API key is required" → key mix-up; bare-string 400 (`"Invalid league"`, `"Invalid query parameter: proposition"`) and HTML 404 bodies → parse defensively `[SS §1.6]`; league filters are case-sensitive on `/markets`, `/teams`, `/players` (use `LGUE_*`) `[SS §2.2]`; `/events` default order is descending → always `ascending=true` `[SS §2.3]`; empty `[]` off-slate is normal `[SS §2.1]` |

### 4.6 Sinks

| Sink | Spec |
|---|---|
| Raw archive | `RawArchive` per (provider, stream); `{"recv_ns","provider","stream","seq","meta","body"}` lines; hourly files; flush 2 s / 5,000 records ✅ `[CODE sinks/raw.py]`. ⬜ zstd, fsync on hour roll, `manifest.json` per hour (row count, sha256, min/max `recv_ns`) as the archive commit `[R1-gpt §5.3]` |
| GCS sync | `GcsArchiveSync.sync_once`: skips the current hour, uploads closed files, verifies size + crc32c, appends `.gcs_manifest.jsonl`, optional delete-after-upload; CLI `u3-ingest archive-sync --every 300` `[PR #3]` ✅ (PR). ⬜ stream the crc32c instead of `read_bytes()`; alert if the newest object per stream is > 2 h old |
| ClickHouse | `ClickHouseSink` batched inserts (`async_insert=1`, `wait_for_async_insert=0`) ✅ `[CODE sinks/clickhouse.py]`; ⬜ native TLS 9440 with LZ4, `insert_deduplication_token = sha1(provider, stream, hour, seq_range)` so replays are idempotent `[R1-gpt §2.4]`; ⬜ coalescer in front; ⬜ TTLs (§1.7) |
| Replay → Parquet/DuckDB | `u3-ingest replay --root --since --until --out --out-format parquet|duckdb` merges files by `recv_ns`, re-registers bootstrap registries, re-normalizes `[PR #4]` ✅ (PR). ⬜ nightly job to `gs://u3-parquet`; ⬜ Arrow batch inserts instead of `executemany` for DuckDB |
| BigQuery | external tables over Parquet; marts by scheduled queries ⬜ |
| Board / Redis (Phase 2) | in-process `Board.ingest` `[PR #5]`; Redis Streams `quotes:<sport>` for detectors ⬜ |

### 4.7 Operations, secrets, deployment

- Secrets in a `.env` on the VM with mode 600, loaded by `pydantic-settings` (whitespace-stripped) `[CODE config.py]`; long-term: Secret Manager + startup fetch. Keys never logged (`OddsPapiWS` already strips `apiKey` from `login_ok` logs `[CODE cli.py]`); add a structlog processor that redacts `apiKey=`, `key=` and `Token ` patterns everywhere.
- systemd units per §1.6 with `Restart=always`, `RestartSec=2`, `MemoryMax` per consumer; watchdog via `sd_notify` tied to "last message age".
- CI: ruff + pytest already scaffolded; replace the placeholder workflow with `pip install -e .[dev,clickhouse,research] && pytest` and the replay benchmark (§1.5).
- Deployment: `deploy/vm.sh` (create VM, disk, static IP, firewall egress-only, IAP), `deploy/units/*.service`, `deploy/oo_streams.yaml`, `deploy/ss_poll.yaml`, `deploy/batch.yaml`, `deploy/env.example`. Redeploy = `git pull && pip install -e . && systemctl restart 'u3-*'`.

### 4.8 Planned ClickHouse DDL (Phase 1)

```sql
-- book/fixture health from OddsPapi `bookmakers` channel + /bookmakers, OpticOdds last-polled
CREATE TABLE IF NOT EXISTS u3.book_status (
    recv_ns UInt64, recv_ts DateTime64(3) MATERIALIZED toDateTime64(recv_ns / 1e9, 3),
    provider LowCardinality(String), book_id LowCardinality(String), fixture_id String,
    has_odds Nullable(Bool), stale Nullable(Bool), suspended Nullable(Bool), rotated Nullable(Bool),
    last_odds_ms Nullable(Int64), stale_since_ms Nullable(Int64), max_delay_live_s Nullable(Float32),
    max_delay_pregame_s Nullable(Float32), limit_currency LowCardinality(String), extra String CODEC(ZSTD(3))
) ENGINE = MergeTree PARTITION BY toDate(recv_ts) ORDER BY (provider, book_id, fixture_id, recv_ns)
TTL toDate(recv_ts) + INTERVAL 90 DAY;

-- settlement/grading as a transition history (never overwrite; latest = argMax(observed_ns))
CREATE TABLE IF NOT EXISTS u3.settlements (
    observed_ns UInt64, provider LowCardinality(String), fixture_id String, provider_fixture_id String,
    market LowCardinality(String), period LowCardinality(String), selection String, line_key String,
    line Nullable(Float64), player_id String DEFAULT '', provider_market_id String, provider_outcome_id String,
    status LowCardinality(String),           -- OP: WIN LOSE PUSH HALFWIN HALFLOSS CANCELLED UNDECIDED · OO: Won Lost Refunded Pending Half Won Half Lost
    margin Nullable(Float64), home_score Nullable(Int32), away_score Nullable(Int32), reason Nullable(String),
    extra String CODEC(ZSTD(3))
) ENGINE = MergeTree PARTITION BY toYYYYMM(toDateTime(observed_ns / 1e9))
ORDER BY (fixture_id, market, period, selection, line_key, player_id, provider, observed_ns);

-- opening/closing lines from three sources plus our own freeze snapshots
CREATE TABLE IF NOT EXISTS u3.clv (
    observed_ns UInt64, source LowCardinality(String),   -- oddspapi_clv | opticodds_hist | sharpsports_summary | freeze_t60 | freeze_t5
    fixture_id String, book_id LowCardinality(String), market LowCardinality(String), period LowCardinality(String),
    selection String, line_key String, line Nullable(Float64), player_id String DEFAULT '',
    olv_price_dec Nullable(Float64), olv_ts_ms Nullable(Int64), clv_price_dec Nullable(Float64), clv_ts_ms Nullable(Int64),
    clv_active Nullable(Bool), clv_is_null Bool, start_ts_ms Nullable(Int64), true_start_ts_ms Nullable(Int64)
) ENGINE = ReplacingMergeTree(observed_ns)
ORDER BY (fixture_id, market, period, selection, line_key, player_id, book_id, source);

CREATE TABLE IF NOT EXISTS u3.fixture_scores (
    recv_ns UInt64, provider LowCardinality(String), fixture_id String, period LowCardinality(String),
    home Int32, away Int32, source_ts_ms Nullable(Int64)
) ENGINE = ReplacingMergeTree(recv_ns) ORDER BY (fixture_id, provider, period);

CREATE TABLE IF NOT EXISTS u3.fixture_clock (
    recv_ns UInt64, provider LowCardinality(String), fixture_id String, current_period Nullable(String),
    current_time Nullable(String), remaining_time Nullable(String), stopped Nullable(Bool)
) ENGINE = MergeTree PARTITION BY toDate(toDateTime(recv_ns / 1e9)) ORDER BY (fixture_id, recv_ns)
TTL toDate(toDateTime(recv_ns / 1e9)) + INTERVAL 30 DAY;

CREATE TABLE IF NOT EXISTS u3.fixture_status (
    recv_ns UInt64, provider LowCardinality(String), fixture_id String, status LowCardinality(String),
    start_ts_ms Nullable(Int64), true_start_ts_ms Nullable(Int64), true_end_ts_ms Nullable(Int64), reason Nullable(String)
) ENGINE = ReplacingMergeTree(recv_ns) ORDER BY (fixture_id, provider);

-- non-sport prediction-market books (coalesced to <= 1/s per market; raw keeps every snapshot)
CREATE TABLE IF NOT EXISTS u3.pm_book_snapshots (
    recv_ns UInt64, platform LowCardinality(String), market_id String, canonical_id String, category LowCardinality(String),
    yes_bid Nullable(Float64), yes_ask Nullable(Float64), no_bid Nullable(Float64), no_ask Nullable(Float64),
    yes_bids Array(Tuple(Float64, Float64)), yes_asks Array(Tuple(Float64, Float64)),
    last_trade Nullable(Float64), source_ts_ns Nullable(Int64)
) ENGINE = MergeTree PARTITION BY toDate(toDateTime(recv_ns / 1e9)) ORDER BY (platform, market_id, recv_ns)
TTL toDate(toDateTime(recv_ns / 1e9)) + INTERVAL 14 DAY;

CREATE TABLE IF NOT EXISTS u3.injuries (
    recv_ns UInt64, provider LowCardinality(String), league LowCardinality(String), player_id String, team_id Nullable(String),
    status String, type Nullable(String), played Nullable(Bool), fixture_id Nullable(String), change LowCardinality(String)  -- added|updated|removed
) ENGINE = MergeTree ORDER BY (league, player_id, recv_ns);

CREATE TABLE IF NOT EXISTS u3.stream_health (
    minute DateTime, provider LowCardinality(String), stream LowCardinality(String), conn_id String,
    msgs UInt32, bytes UInt64, coalesced UInt32, reconnects UInt16, gaps UInt16,
    lat_recv_minus_src_p50_ms Float32, lat_recv_minus_src_p99_ms Float32, decode_p99_ms Float32
) ENGINE = MergeTree ORDER BY (provider, stream, minute) TTL minute + INTERVAL 90 DAY;

CREATE TABLE IF NOT EXISTS u3.mapping_unresolved (
    observed_ns UInt64, kind LowCardinality(String),      -- fixture | book | market
    provider LowCardinality(String), provider_key String, league LowCardinality(String), hint String, count UInt32
) ENGINE = ReplacingMergeTree(observed_ns) ORDER BY (kind, provider, provider_key);

-- Phase 2
CREATE TABLE IF NOT EXISTS u3.signals (
    signal_id UUID, ts_ns UInt64, edge LowCardinality(String), fixture_id String, market LowCardinality(String), period LowCardinality(String),
    selection String, line_key String, book_id LowCardinality(String), price_dec Float64, fair_p Float64, method LowCardinality(String),
    ev Float64, fee_est Float64, settlement_mismatch_score Float32, quote_age_ms UInt32, constituents String CODEC(ZSTD(3))
) ENGINE = MergeTree PARTITION BY toDate(toDateTime(ts_ns / 1e9)) ORDER BY (edge, fixture_id, ts_ns);
```

### 4.9 Reference numbers for capacity planning

| Quantity | Value | Source |
|---|---|---|
| OpticOdds SSE, baseball, 5 books | 15.8 events/s = 223 records/s; 81 % Polymarket; 49 % `is_live` | `[OO-probe #6]` |
| OpticOdds SSE, soccer, 5 books, all leagues | 313 events/s = 1,544 records/s; 67.8 MB / 45 s | `[OO-probe #6]` |
| OpticOdds PM stream, politics | 933 snapshots/s; 120 MB / 45 s; crypto 514/s | `[OO-probe #6][OO §2.10]` |
| OpticOdds SSE delivery latency | p50 7 ms (baseball) / 32 ms (soccer); p99 0.2–0.33 s | `[OO-probe #6]` |
| OpticOdds REST `/fixtures/odds` | 3 fixtures × 5 books = 4.99 MB; DK 811–1,401 odds/fixture | `[OO §2.4]` |
| OddsPapi WS, unfiltered sports 10/11/13 | ≈ 500 msg/s (87 % Polymarket); 27 msg/s with sharp/US filter | `[OP §4.10]` |
| OddsPapi WS frame size | json 2,412 B avg; zstd 679 B; zstd-dict 444 B; msgpack 2,657 B | `[OP §4.8]` |
| OddsPapi WS latency | `recv − changedAt` p50 79 ms (p90 138); `recv − bookmakerChangedAt` p50 142 ms | `[OP §7.1]` |
| OddsPapi tick history | Pinnacle 25k ticks / 6 MB per MLB game; DK 433k / 95.6 MB | `[OP §5.2]` |
| SharpSports `/prices` | league 17.5 MB / 2–7 s; event 1.67 MB / 0.28 s; DFS 3.78 MB / 5.3 s | `[SS §1.7]` |
| Prototype throughput (sandbox) | 381,188 quotes + 1,311,005 levels + 105,128 raw msgs in 75 s; 52 MB gz | `[CODE README]` |

### 4.10 Runbooks (Phase 1 deliverable, `docs/runbooks/`)

1. **Reconnect storm** (alert: > 5 reconnects/min on any stream): check vendor status pages; verify egress; if OddsPapi 4002, switch remaining json connections to zstd-dict and narrow `sportIds`; if OpticOdds 429, pause new connects 15 s and stagger reconnects with 2 s jitter `[OO §1.4]`.
2. **Entitlement change** (alert: 403 on a previously-working endpoint or `login_ok` echo drift): freeze the affected job, capture the body, open a vendor ticket with `cf-ray`/`connId` `[OP §1.4, §4.3]`; do not retry in a loop.
3. **ClickHouse unavailable**: consumers keep archiving (raw is primary); coalescer buffers up to 5 min then drops to `stream_health` counters; after recovery run `u3-ingest replay --since <gap>` into ClickHouse with dedup tokens.
4. **GCS sync backlog** (alert: newest object > 2 h): check `.gcs_manifest.jsonl` failures, ADC credentials, disk space; local spool holds 48 h.
5. **Key rotation**: create new key in the vendor console; write to `.env.new`; `systemctl reload` reads both (`*_API_KEY` and `*_API_KEY_NEXT`) — connectors try NEXT on 401; revoke old key after 24 h; confirm no `queue_name` or URL with the old key remains in any archive (`grep` over the day's raw files before upload).
6. **Volume spike** (alert: GCS growth > 15 GB/day or ClickHouse inserts > 5k rows/s): apply §1.3 kill-switches in order.

---

## 5. Edge inventory (prioritized)

Sizing uses underwriting ranges from the briefs (they disagree by up to an order of magnitude; the ranges below are the intersection we consider credible, before taxes and account attrition) and our own data facts. "Latency budget" = quote-in to decision-out inside our process; vendor latency (≈ 0.1–0.5 s) sits on top.

| # | Edge | Mechanism | Data needs (our feeds) | Latency budget | Expected net edge / capacity | Main risks | What ingestion must provide |
|---|---|---|---|---|---|---|---|
| 1 | **Sportsbook ↔ Kalshi/Polymarket arbitrage (pregame)** | Buy YES at PM price c + fee f, back the complement at a book at decimal d; strict arb iff `c + f + 1/d < 1` `[R2-gpt §2.1]`; fire the slow (sportsbook) leg first `[R2-opus §2.2]` | PM depth + `source_ids` (matrix #5), same-`outcomeId` PM quotes from OddsPapi with USD notional per rung `[OP §8.8]`, sportsbook quotes + limits (#2, #8), fee schedules, contract rule text | seconds pregame; < 500 ms for the PM leg once automated | 0.25–2 % on genuinely equivalent contracts `[R2-gpt]`; 1.5–4 % gross per gemini/opus — haircut for settlement jump risk; capacity bounded by book depth (hundreds of contracts at a price `[R2-opus §2.2]`) | Settlement-rule mismatch (NFL abandoned < 55 min settles at last price on Kalshi; ties push at books; Polymarket UMA disputes) `[R2-opus §2.2]`; partial fills; capital lock-up | exact contract mapping (canonical key + `venue_market_id`), fee-inclusive and raw prices (`exclude_fees`), depth timeline, settlement outcomes from both sides (#11) to measure realized basis |
| 2 | **Prediction-market market making (Kalshi, Polymarket, Novig)** | Quote around a reservation price `r = p_fair − λ·I` with fee/rebate-adjusted bid/ask `[R2-gpt §3.1]`; Avellaneda-Stoikov with binary terminal collapse `[R2-gem §3.2]` | Pinnacle-anchored fair value (edge #4) at ≤ 500 ms age, PM full depth and trades, own fills, fee tiers, resolution metadata | 10–50 ms internal; cancel path is the critical latency | 0.5–3 % per filled unit; the most scalable family (Kalshi $1.2 B/day record in June 2026 `[R2-opus §0]`) | Adverse selection (filled only when the reference moved), inventory concentration, resolution risk, venue/legal availability by state `[R2-opus §0]` | continuous Pinnacle/consensus stream with staleness flags (`staleOdds`, `maxDelay*`), PM book snapshots with sequence, our order/fill ledger (Phase 3) |
| 3 | **Slow-book latency arb using per-book observed delays** | Reference moves at Pinnacle/exchanges; hit the stale quote at a copier book before it reprices; retail books reportedly lag leaders by 0.8–4.5 s `[R2-gem §2.2]` (unverified — measure) | per-book lag distribution from `bookmakerChangedAt`/`changedAt`/`recv_ns` `[OP §7.1]`, OpticOdds `timestamp` + `/sportsbooks/last-polled` cadence, `locked-odds`, leader-follower model per market/time-to-start `[R2-gpt §1.1]` | < 100 ms internal; end-to-end 1–5 s window | 2.5–6 % per unit `[R2-gem]`, capacity near zero at retail books after limiting; pre-game steam-following is the durable subset | Account limitation is the true cost of capital `[R2-opus §2.1]`; rejected/repriced quotes have zero capacity `[R2-gpt §5.2]`; ToS on automated placement | tick ledger with three clocks, per-book acceptance telemetry (Phase 3), `u3.book_lag` view (§6.2) |
| 4 | **Pinnacle-anchored fair value → +EV on soft books and PMs** | Devig (multiplicative for tight two-ways, power/Shin for lopsided/multiway) `[R2-gpt §1.2]`, uncertainty-weighted logit consensus with copy-cluster penalties `[R2-gpt §1.3]`, then EV = p·d − 1 after fees | Pinnacle + Circa + BetOnline/Bookmaker + exchanges (#8, #2), limits as liquidity weights, freshness | seconds–minutes pregame | 1–3 % CLV on primary markets for professionals `[R2-opus §2.7]`; capacity limited by books | Fake steam/head-fakes `[R2-opus §1.4]`; devig-method dispersion (20–40 bp is noise) `[R2-gpt §1.2]` | `Board` + `fair_value` `[PR #5]` fed by uncoalesced quotes; per-book weights table; stored constituents per fair value (provenance, as Copilot does `[OO-sum oo-copilot-trading]`) |
| 5 | **Player props vs DFS pick'em (PrizePicks / Underdog at fixed +100)** | Pick'em legs are hidden-price parlays: PrizePicks flat leg ≈ −119 (54.34 % BE), Underdog 4-flex ≈ −107 (51.69 %), 2-pick power 3× ≈ 57.7 % `[R2-opus §2.5]`; compare devigged prop probability at the pick'em line; positive correlation across legs is unpriced by the apps | OpticOdds DFS payout-structure ids + SharpSports `pp`/`ud` +100 lines (#16), alt-line ladders (`lineAvailability`, OpticOdds alternates) to fit distributions, injuries/lineups (#14), player logs/DVP (#15) | minutes pregame; seconds around lineup news | 1–8 % per entry, very low capacity `[R2-gpt]`; tier-2 sports softer `[R2-opus §2.5]` | Payout-table changes, demotion to Flex after ~55 % win rate over 200+ entries, DNP void rules `[R2-opus §2.5]` | canonical `player:<metric>` keys across all three vendors, `player_id` crosswalk (OpticOdds ↔ SharpSports `PLYR_` via `oddsjamId`), line ladders stored with `is_main` |
| 6 | **CLV capture (process metric, not an edge)** | `CLV_EV = d_bet · p_close − 1` against a devigged close; like-for-like lines `[R2-gpt §5.1]` | our freeze snapshots (T−60 s/T−5 s), OddsPapi `clv`/`olv`, OpticOdds `olv`/`clv`, SharpSports historic summary (#12) | none | sustained +1–3 % CLV over 1,000+ bets = evidence of edge `[R2-opus §2.7]` | wrong benchmark, self-impact on close, props without sharp close | `u3.clv` with sources side by side; `event_kind='freeze'` rows |
| 7 | **Middles / scalps** | Hold both sides across key numbers; +EV iff P(middle) × payout > carry `[R2-gpt §2.4]` | alt-line ladders per book, margin distributions from settlement history (#11, #13) | minutes–days | modest, variance-heavy, limit-bound | push-probability error | full alt-line capture (already: `is_main=false` rows) |
| 8 | **Correlated parlay / SGP mispricing** | Compare book SGP prices (dispersion of 50–100 points across books) with a joint model; OpticOdds SGP pricer (DK +242 vs FD +210 on the same two MLB legs) as a reference `[R2-opus §2.6][OO §2.8, §3.10]` | `/parlay/odds` per book, prop ladders, results for joint calibration | seconds–minutes | several % when the model is right; narrow, high-attrition | books limit correlated-SGP winners | on-demand parlay pricing archived; joint-outcome results (`player-results`, `market_stats`) |
| 9 | **Promo / boost harvesting** | EV of boosts/promos after rollover on one legitimate account; run as a separate P&L with account cost amortized `[R2-opus §2.6]` | promo terms (manual), fair value (#4) | low | high ROI on promo capital, tiny capacity, self-terminating | terms changes, limiting | none beyond fair value; manual workflow |
| 10 | **Steam / line-origin detection** (research product feeding #3 and #4) | Leader–follower regression `Δp_j,t = α + Σ β_jk Δp_k,t−ℓ` by sport/market/time-to-start; steam event = leader move ≥ x ticks and ≥ m independent clusters follow within 30–90 s; fakeability index = followers ÷ limit at origin `[R2-gpt §1.4][R2-opus §1.4–1.5]` | tick ledger with limits at every tick, `bookmakerChangedAt`, news timestamps (#14) | offline | improves #3/#4 weights | public steam alerts are already-priced `[R2-gpt §1.4]` | `limit_max` on every quote row; injuries/lineups diffs with `recv_ns` |
| 11 | **In-play modeled edge** (Phase 3+) | Own real-time fair price from game state vs book lag `[R2-opus §2.4]`; on PMs only 5.2 % of live game time is tradable under depth/spread/age filters `[R2-opus §2.4]` | scores/clock/in-play (#10), live odds (#4), PM depth | sub-second | unknown until post-acceptance data exists `[R2-gpt §2]` | rejections, bet delays, voids | `u3.fixture_clock`, results stream `in_play`, quote-age filters in backtests |

### 5.1 Worked examples (the arithmetic detectors must implement)

**(a) Sportsbook ↔ Kalshi arbitrage, fee-aware.** Kalshi YES for team A at `c = 0.62` (contract price, raw book, `exclude_fees=true`); taker fee `f = 0.07 × 0.62 × 0.38 = 0.0165` per contract `[R2-opus §2.2]`; sportsbook price on team B (complement, no draw) `+185` → `d = 2.85`, `1/d = 0.3509`. Total cost per $1 payout = `0.62 + 0.0165 + 0.3509 = 0.9874` → gross 1.26 %. Then subtract: settlement-mismatch haircut (probability of a discretionary/last-price settlement × expected adverse move, e.g. 0.3 % × 40 % = 0.12 %), capital lock-up to resolution, and the sportsbook stake cap (`limit_max`) and Kalshi depth at 0.62 (`order_book` levels) → net ≈ 1.0 % on the smaller of the two capacities. Using the real Ipswich–Liverpool board `[XJ]` (Kalshi Liverpool −200, FanDuel Ipswich +460, Draw +370): `1/1.50 + 1/5.60 + 1/4.70 = 1.058` → no arb; the detector must also test all three-way combinations and the draw-no-bet equivalents.

**(b) DFS pick'em screen.** Pinnacle prop Over 24.5 at −145 / Under +118 → multiplicative devig `p_over = 0.592/(0.592+0.459) = 0.563`; PrizePicks flat-leg break-even 0.5434 → +1.9 pts; Underdog 4-flex break-even 0.5169 → +4.6 pts `[R2-opus §2.5]`. Require the SharpSports `pp`/`ud` line to be identical (24.5), the OpticOdds `prizepicks*` payout id to match the entry type, and no injury/lineup change since the Pinnacle print; report EV per structure, never a single number.

**(c) Per-book lag.** For each Pinnacle print at `t0 = bookmakerChangedAt` `[OP §7.1]`, find the first follower print in the same direction within 120 s; store `Δ_book = follower.bookmakerChangedAt − t0` (or `changedAt` when the book has no own timestamp). A book whose p50 Δ is > 2 s for a market family with limits ≥ $1k is a latency-arb candidate; a book with p50 < 0.5 s is a copier to down-weight in consensus.

**(d) CLV.** Bet taken at 2.10 on a spread −3.5; freeze snapshot at T−5 s shows Pinnacle −3.5 at 1.95/1.95 → devig `p_close = 0.5`; `CLV_EV = 2.10 × 0.5 − 1 = +5.0 %`. If the closing line is −3 instead of −3.5, apply the half-point valuation from the settlement-margin distribution before comparing.

**Non-goals for edges** (all phases): courtsiding/in-venue relay, multi-accounting/beards, geolocation or KYC evasion, automated placement on retail books that prohibit it. Research briefs that describe such tactics `[R2-gem §4]` are recorded as risks (§8), not plans.

---

## 6. Measurement & research loop

### 6.1 CLV pipeline
- Every candidate signal (Phase 2) and every order (Phase 3) is written to `u3.signals` / `u3.orders` with the canonical key, price taken, fair value and method used, fee estimate, and `recv_ns` of the triggering quote.
- Closing benchmarks joined per canonical key from (a) our own freeze rows (T−60 s / T−5 s, `event_kind='freeze'`), (b) OddsPapi `clv` with the fallback chain `clv → last tick ≤ trueStartTime → olv` `[OP §8.5]`, (c) OpticOdds historical `olv`/`clv` (populated ~2 days after the game `[OO §3.7]`), (d) SharpSports historic summary `last` per book `[SS §2.1]`. Devig the close with the same method as the signal; report CLV in probability points and EV terms; separate spreads/totals by like-for-like line with a half-point valuation model.
- Weekly report: % beating close, mean CLV by league/market/book/time-to-start, calibration curve (decile slope 1.00 ± 0.02 `[R2-gem §5.2]`), Brier score, realized vs expected P&L once trading.

### 6.2 Latency attribution
- Quote-level: `book→gateway = changedAt − bookmakerChangedAt` (≈ 360 ms Pinnacle), `gateway→emit = ts − changedAt` (≈ 100 ms), `emit→us = recv − ts` (108 ms from the sandbox) `[OP §7.1]`; OpticOdds `recv − timestamp` (p50 7–32 ms) with the `ping` clock-offset correction `[OO §3.13][OO-probe #6]`; SharpSports `recv` only.
- Per-book lag view `u3.book_lag` (sketch):
```sql
WITH leader AS (
  SELECT fixture_id, market, period, selection, line, recv_ns AS t0, price_dec,
         lagInFrame(price_dec) OVER w AS prev_price
  FROM u3.quotes WHERE provider = 'oddspapi' AND book_id = 'pinnacle' AND event_kind = 'update'
  WINDOW w AS (PARTITION BY fixture_id, market, period, selection, line ORDER BY recv_ns)
), moves AS (SELECT * FROM leader WHERE prev_price IS NOT NULL AND price_dec != prev_price)
SELECT f.book_id, m.market, quantile(0.5)((f.recv_ns - m.t0) / 1e6) AS p50_ms, quantile(0.9)((f.recv_ns - m.t0) / 1e6) AS p90_ms, count() AS n
FROM moves m
ASOF JOIN u3.quotes f ON f.fixture_id = m.fixture_id AND f.market = m.market AND f.period = m.period
   AND f.selection = m.selection AND f.line = m.line AND f.book_id != 'pinnacle' AND f.recv_ns > m.t0
WHERE (f.price_dec - m.prev_price) * (m.price_dec - m.prev_price) > 0 AND f.recv_ns - m.t0 < 120e9
GROUP BY f.book_id, m.market;
```
  This is the empirical replacement for the anecdotal "which books lag" lists `[R2-gpt §5.2]`.
- Order-level (Phase 3): `T_signal → T_receive → T_model → T_decision → T_send → T_ack → T_fill` decomposition `[R2-gpt §5.2]`.
- Existing view `u3.quote_latency` (p50/p99 of `recv − source_ts` per provider × book × minute) `[CODE schemas/clickhouse.sql]` is the day-one SLI.

### 6.3 Mapping coverage
- Nightly `mapping-report`: fixtures per league with all three ids; `opticoddsId` join rate (target ≥ 95 % MLB/NFL/EPL, ≥ 85 % NCAAF `[XJ]`); SharpSports join rate (≥ 90 % MLB); books resolved vs `unknown`; markets in `other:*` by quote volume (target < 2 % of volume); duplicate canonical fixtures (target 0); cross-provider price disagreement > 3 % lasting > 2 min (target 0 per day); OpticOdds ↔ SharpSports player-id equality rate (`oddsjamId`).

### 6.4 Data-quality SLOs (alert rules in Grafana Cloud)

| SLI | Target | Alert rule (PromQL/ClickHouse sketch) |
|---|---|---|
| Quote freshness p99 (`recv − changedAt`) per book, in-play | < `1000 × maxDelayLiveInSec` `[OP §10.7]` | `histogram_quantile(0.99, rate(u3_quote_age_ms_bucket{provider="oddspapi"}[5m])) > on(book) u3_book_max_delay_live_ms` |
| Edge transport (`recv − ts`) p99 | < 500 ms | `histogram_quantile(0.99, rate(u3_transport_ms_bucket[5m])) > 500` for 5 m |
| Stream liveness | last message age < 30 s per connection during a live slate | `time() - u3_last_msg_ts{stream=~"odds.*"} > 30 and on() u3_live_fixtures > 0` |
| Reconciliation divergence | < 0.1 % of keys per sweep | `u3_sweep_divergent / u3_sweep_keys > 0.001` |
| Archive completeness | closed file per active stream per hour; GCS object ≤ 2 h later | `time() - u3_gcs_newest_object_ts{stream} > 7200` |
| Settlement completeness | > 99 % finished fixtures with 0 `UNDECIDED` (excl. `REQUIRES_NON_SCORE_STATS`) within 24 h `[OP §10.7]` | ClickHouse nightly query → gauge |
| CLV coverage | ≥ 80 % of traded keys with a non-null close from ≥ 2 sources | nightly query → gauge |
| History retention watermark | oldest fixture with non-empty OddsPapi CLV ≈ 220 d; OpticOdds timeseries ≈ 57 d `[OP §10.7][OO-probe #4]` | weekly probe job |
| Entitlement drift | `login_ok` echo and `/bookmakers` count unchanged; any 403 on a previously-working endpoint pages | `increase(u3_http_status{code="403"}[10m]) > 0` |
| Budget | GCS growth ≤ 15 GB/day; GCP spend ≤ $100/month | billing export → BigQuery scheduled query |
| Coalescer health | coalesced fraction 60–95 % (too low = churn leaking; too high = state bug) | `u3_coalesced_total / u3_rows_total` |

### 6.5 Research loop
- Weekly: replay the last 7 days to Parquet (`u3-ingest replay`) → BigQuery; notebooks for CLV, book lag, steam detection, PM basis; results feed `weights.yaml` (book weights per league/market/time bucket) consumed by the fair-value engine.
- Monthly: re-run the mapping and entitlement probes (`tools/research/cross_join.py`, probe scripts) and diff against the specs; update `docs/research/*.md`.

---

## 7. Phased roadmap

### Phase 0 — Ingestion MVP (done, this week)
Delivered: provider clients with rate limiters and retries; OpticOdds SSE and OddsPapi WS clients (zstd/msgpack decode, resume cursors, control-frame handling); SharpSports client; canonical model, market/selection keys, book and fixture registries; normalizers for all three; raw archive; ClickHouse sink and schema (`u3.quotes`, `u3.order_book_levels`, `u3.fixture_xref`, `quotes_latest` MV, `quote_latency` view); `u3-ingest archive|snapshot|run` CLI; tests (SSE parser, limiter, archive round-trip, WS resume/snapshot_required, normalizers, registry joins); research tooling and specs; 75 s live verification `[CODE]`. Open PRs: GCS sync `[PR #3]`, replay to Parquet/DuckDB `[PR #4]`, pricing library `[PR #5]`.

### Phase 1 — Cloud deployment + resilience + warehouse (weeks 2–4)

| Week | Deliverables | Exit check |
|---|---|---|
| 2 | Merge PRs #3–#5 (review notes: PR #3 reads whole files for crc32c — stream it; PR #4 DuckDB `executemany` — use Arrow; PR #5 `Board` keys on `line` incl. `None` — fine). Code fixes from §0 (novig, MLS id, `ascending=true`, zstd-dict default, SSE league filters). `deploy/` scripts; VM up; 24 h RTT probe `us-east4` vs `us-east1` `[R1-gpt §4]`; self-hosted ClickHouse in Docker; all units running with raw archive + GCS sync; structlog redaction; rotate OpticOdds key, revoke the pasted Perplexity key | 48 h of continuous archive with no gaps; GCS objects verified |
| 3 | OddsPapi three-connection plan, cursor persistence, `snapshot_required`/`reconnect` automation, `/fixtures/odds/main?since` sweep, `/bookmakers` health; OpticOdds book-group × league plan, REST re-hydration, `fixture-status`, PM politics stream, futures poll, injuries diff, last-polled; SharpSports targeted polling; coalescer + volume caps; hourly manifests; Prometheus exporters + Grafana dashboards + §6.4 alerts | SLOs green 3 days; GCS ≤ 15 GB/day |
| 4 | Settlement, CLV, freeze workers and tables (§4.8); backfills (spine 400 d, settlement ≥ 1 y for MLB/NFL/NBA/NHL/EPL, CLV 220 d, Pinnacle ticks MLB+NFL, OpticOdds OLV/CLV, SharpSports player logs); nightly replay → Parquet → BigQuery external tables + marts; mapping-report job; benchmark gate in CI; runbooks; ClickHouse Cloud trial DDL/loader rehearsal | 7 consecutive days SLOs green; mapping targets met (MLB, EPL; NFL from week 1 of season); gate passing |

Month 2 starts the ClickHouse Cloud trial with the caps in place.

### Phase 2 — Fair value + edge detection + alerting (weeks 5–8)

| Week | Deliverables |
|---|---|
| 5 | `u3-board` service on Redis Streams; staleness gating (`staleOdds`, `maxDelay*`, quote age, `locked-odds`); fair-value engine on `[PR #5]` with per-league/market devig method chosen by backtest, `weights.yaml`, copy-cluster penalty, stored constituents |
| 6 | Fee-schedule table (Kalshi `0.07·C·p(1−p)`; Polymarket sports curve + rebate share; Polymarket US 0.30 % / 0.20 %; Novig live `0.03·C·p(1−p)`; ProphetX 1 % `[R2-opus §2.2]`) refreshed from live venue objects; settlement-rule registry per venue/sport (OT, abandonment, ties, DNP) with mismatch score; detector #1 (PM basis) and #4 (+EV vs consensus) |
| 7 | Detector #5 (DFS pick'em with correlation flags) and #3 (stale-quote candidates from `u3.book_lag`); Slack alerting with dedup/quiet hours; `u3.signals` ledger; paper-trading P&L with CLV |
| 8 | Steam/line-origin research report; weekly CLV report automated; go/no-go per edge family; Phase 3 design review |

### Phase 3 — Execution + risk (weeks 9–12+)
Deliverables: Kalshi and Polymarket execution adapters (native APIs; RSA-PSS / L2 HMAC auth `[R3-gem §4]`) behind a common order interface; order/fill ledger with the seven-timestamp decomposition; risk engine (per-market, per-event, per-venue and correlated exposure caps; max quote age; cancel-backlog limit; kill switch on `staleOdds`, settlement disputes, venue/legal state changes); market-making pilot on Kalshi in 1–2 liquid leagues at minimal size; sportsbook legs via deep links (`deep_link` on every OpticOdds REST odd `[OO §1.1]`, SharpSports betPlace `bookIds`/`betPlaceLinks` `[SS §1.1]`) as a human-click workflow, not automated placement; optional SOAX-based validation of retail quote acceptance (read-only). Exit: realized P&L, fill rates and latency attribution reported for 4 weeks; decision on scaling capital.

### Explicit non-goals (all phases)
Kafka/PubSub, Kubernetes, multi-region HA, a Rust/Go rewrite before the gate fails, OpticOdds Copilot (not licensed `[OO §1.1]`), OddsPapi/55-tech ABP automated bet placing on retail books `[R3-gem §5]`, non-sport PM trading before Phase 3, any account-evasion tooling.

---

## 8. Risks & mitigations

| Risk | Evidence | Mitigation |
|---|---|---|
| Vendor ToS / licensing: data redistribution, automated betting | OpticOdds enterprise licence; OddsPapi positioned as data-only with ABP separate; SharpSports betPlace is deep-link only `[R3-gem §5][R3-pplx §5]`; Swish v. OddsJam/OpticOdds litigation over scraped book data `[R3-gem §5]` | No redistribution of feeds; execution only on venues whose terms permit API trading (Kalshi, Polymarket); retail legs by human click; contract/indemnification questions in §9 |
| Trial-credit cliffs | ClickHouse 30 d, Snowflake 30 d, GCP 90 d `[R1-gpt §1.1, §2.1, §3.1]` | Raw archive is provider-independent; ClickHouse DDL + loaders scripted; self-hosted ClickHouse tested before the trial; budget alerts at 70/90 % |
| Data volume blow-up | Polymarket 81–87 % of odds messages; soccer all-leagues 1,544 rec/s; DK 433k ticks/game `[OO-probe #6][OP §5.2]` | §1.4 caps; budget kill-switches (§1.3); coalescing is measured (`coalesced_rows_total`) |
| Vendor outage or per-book feed loss | OpticOdds latency incidents on its status page `[R3-pplx §1]`; OddsPapi `staleOdds`, `reconnect` releases `[OP §4.5]`; Kalshi poller 1,595 s stale during the probe `[OO §1.1]` | Dual-vendor coverage for the six common books; `staleOdds`/`last-polled` gating; hard stops in the board; alerts on liveness |
| Replay/resume limitations | OpticOdds `last_entry_id` replay does not work `[OO-probe #7]`; OddsPapi `odds` may not be replayable, 60 s window `[OP §4.6]` | REST re-baseline on every reconnect; reconciliation sweeps; our own archive is the ledger |
| Key exposure & rotation | `/fixtures/results/queue/status` echoes the raw OpticOdds key `[OO §1.1]`; OddsPapi key travels in URLs `[OP §9.3]`; OpticOdds `?key=` in stream URLs `[OO §1.2]`; a Perplexity key was pasted in chat | Rotate OpticOdds key now and after every probe session that touched the queue endpoint; treat that endpoint's output as secret; redaction processor; revoke the Perplexity key; quarterly rotation runbook (§4.10) with dual-key overlap |
| Entitlement drift | OddsPapi 403s are precise but `[]`/silent drops also occur `[OP §1.6, §9.2]`; OpticOdds unknown sportsbook ids silently ignored `[OO §1.6]` | Assert echoes and counts; 403 on a previously-working endpoint pages |
| Schema drift | OddsPapi breaking changes ~quarterly; 5 undocumented `Bookmaker` fields `[OP §9.3]`; OpticOdds `limits.max` vs `max_stake`, pagination envelope changes `[OO §1.5, §3.6]` | Raw-first archive; lenient parsers; unknown-key counters; contract tests on live samples |
| Mapping errors → false arbs | name mismatches (OpticOdds "Ipswich Town FC" vs OddsPapi "Ipswich Town") `[XJ]`; `participantsRotated`; league-scoped OpticOdds team/player ids `[OO §3.2]` | Exact-id joins first; cross-provider price sanity alert (§3); manual override file |
| Settlement mismatch | Kalshi last-price settlement on abandoned games, ties, DNP; OpticOdds grader deviates from house rules (tennis retirement code 218, soccer substitute goalscorer refunded) `[R2-opus §2.2][OO §3.10][OO-sum oo-results-b]` | Settlement-rule registry with mismatch score; haircut EV by jump risk; store both vendors' grades |
| Stale quotes traded | OpticOdds REST returns stale-but-available prices as-is (5–14 h old observed) and omits suspended ones `[OO-probe entitlements][OO §2.4]`; SharpSports has no timestamps `[SS-sum ss-betprices]` | Quote-age gating everywhere; SharpSports never used for pricing decisions |
| Fee basis confusion | Polymarket `price` fee-adjusted by default (`-10421` vs book `-9900`) `[OO §3.6]` | `exclude_fees=true` on all OpticOdds exchange pulls; fee model applied by us; QA check that price == `order_book[0][0]` |
| Account limits / capacity | soft-book capacity is operator-controlled and perishable `[R2-gpt §4]` | Prioritize PM/exchange edges; treat soft-book edges as capped side lines |
| Legal/regulatory volatility of PMs | Third vs Ninth Circuit split, state injunctions `[R2-opus §0]`; Sporttrade reportedly exited US sports betting June 2026 `[R2-gpt §2.2]` and is `inactive` at OpticOdds `[OO §1.1]` | Venue availability as a risk input; no dependence on a single venue |
| Small team / bus factor | two people | One VM, one language, one CLI; runbooks (§4.10); everything rebuildable from GCS |

---

## 9. Open questions for vendors

**OddsPapi (contact@55-tech.com)** `[OP §9.4]`
1. Region binding: is `oddspapi-us1` fixed for our key; regional hostnames; recommended GCP region.
2. `resumeWindowMs` on our key and whether `odds` ever appears in `replayChannels`.
3. Header-based REST auth to keep keys out of URLs.
4. Units/types of `staleThresholdSec`, `lastOddsAt`, `staleOddsSince`, `availableSports`; semantics of login `live`/`pregame`, envelope `v`/`seq`, `resume.serverCursors`.
5. Hard cap on `/fixtures/odds/main?tournamentId` (100 fixtures?), max ids per `fixtureIds`/`oddsIds`, and whether the WS `bookmakers` filter has a length cap.
6. Settlement latency after `trueEndTime`; are grade transitions pushed on any channel; plans for player-prop settlement.
7. Commercial: sports 16–81, prediction-market topics 69–78, `futures/odds*`, > 5 bookmakers per query, > 5 WS connections; SLA and status-page subscription.

**OpticOdds**
1. `last_entry_id` replay: documented but non-functional on our key — expected behaviour and retention window; `entry_id` monotonicity on soccer.
2. Are the observed 8,000/15 s standard and 50/15 s historical limits contractual; 429 body/`Retry-After` semantics; any per-key concurrent SSE connection cap beyond 250 connects/15 s `[OO §1.4]`.
3. Which `limits` key (`max` vs `max_stake`) is emitted on streams; confirm `exclude_fees` semantics per exchange and on the PM stream.
4. PM stream: Polymarket id form for CLOB routing (numeric vs condition id + clobTokenIds) `[OO §3.2]`; when `entry_id`/`canonical_id` are populated; Kalshi `timestamp_ns` quality `[OO §3.13]`.
5. Historical: retention of `include_timeseries` (57–60 d observed) and `olv`/`clv`; CLV population timing; whether `locked` entries are ever emitted `[OO §3.7]`.
6. Security: `/fixtures/results/queue/status` echoes the API key — fix and confirm rotation procedure `[OO §1.1]`.
7. Coverage: Kalshi NFL/EPL game markets, Novig/ProphetX poll cadence (prophet_x 2.5 h stale observed), Sporttrade status; `updated_since` semantics `[OO §2.3]`; RotoWire add-on terms; Copilot pricing (not required).

**SharpSports**
1. Any timestamp or version on `/prices` prices; backend refresh cadence per book; live-mode latency claims (sub-100 ms) vs observed 2–7 s league calls `[SS §1.7]`.
2. Authoritative rate limits for `/prices` (100 vs 50 rps) and `/marketSelections` (50 vs 20) `[SS §1.4]`.
3. `oddsjamId` format guarantee and equivalence to OpticOdds v3 `game_id` (37/40 MLB matched; NFL uses `teamA-teamB-YY-WW`).
4. Performance of `/prices/historic/summary` by player/team (55–98 s, timeouts) and `/marketSelections?league=` (20–32 s); retention depth of OHLC `[SS §1.7]`.
5. Confirm the 12 odds-feed books and abbrs (`pm` Polymarket, `hr`, `st`, `fl`, `fn`, …) `[SS §1.1]`; Sporttrade status.
6. betSync: access to population-level flow statistics (not only our linked bettors); terms for research use.

**Venues (for Phase 3)**: Kalshi API tier and PrivateLink availability; Polymarket US vs international access and fee flags; Novig/ProphetX market-maker API programmes.

---

## 10. Decision log

| # | Decision | Alternatives considered | Why |
|---|---|---|---|
| 1 | **Python asyncio (uvloop, orjson) for the hot path through Phase 2, with a benchmark gate** | Go service (recommended by `[R1-gpt §5.1][R1-pplx §5]`), Rust, Python for adapters only | The prototype already exceeds the stated 5–20k rows/s range end-to-end in this sandbox `[CODE README]`; two-person team; vendor latency (0.1–0.5 s) dominates in-process time; the gate (§1.5) protects the decision and confines any rewrite to the decode stage |
| 2 | **OddsPapi WS as primary real-time sportsbook feed; OpticOdds SSE as breadth/PM/DFS/futures/results primary and cross-check** | OpticOdds SSE as primary; either alone | OddsPapi: 31 books in one connection, resume cursors, zstd-dict (7–9× smaller), three timestamps per quote, per-side limits, frozen ids across books, `staleOdds` gating `[OP §4, §7, §8]`; OpticOdds: 229 books incl. DFS payout ids and exchanges with `order_book`/`source_ids`, non-sport PMs, grader/results, deep links `[OO §1.1, §3.6]`, but no working replay `[OO-probe #7]` and 5 books per stream. Both are archived; the six common books give a continuous cross-check |
| 3 | **Raw archive first; ClickHouse/BigQuery derived** | Normalize-first with raw sampling | Vendors change shapes quarterly `[OP §9.3]`; OddsPapi history evaporates at ~220 d `[OP §5.2]`, OpticOdds timeseries at ~60 d `[OO-probe #4]`; replay exists `[PR #4]`; "GCS is the source of truth; ClickHouse is rebuildable" `[R1-gpt §5.3]` |
| 4 | **ClickHouse = hot tick store/board mirror; BigQuery = research warehouse; Snowflake = optional sprint** | Snowflake as main warehouse; ClickHouse for everything; BigQuery streaming | Credit fit: BigQuery shares the GCP $300 and has a permanent free tier; ClickHouse Cloud is ~$186/mo after its 30-day trial `[R1-gpt §2.1, §3]`; Snowflake has no free tier and is unreachable from this sandbox; tick queries want ClickHouse, stats joins want a warehouse |
| 5 | **Single on-demand GCE VM (`e2-standard-2`), no Cloud Run/GKE/NAT** | Cloud Run min-instances; GKE Autopilot; Spot primary | Long-lived sockets, fixed IP, local spool, predictable cost; Cloud Run WebSockets are timeout-bound requests; NAT bills per GiB `[R1-gpt §1.3–1.4]`; Spot preemption on the only consumer is unacceptable |
| 6 | **Region `us-east4` for the collector (confirm with a 24 h RTT probe; `us-east1` if ClickHouse PSC/egress matters more)** | `us-central1` (ClickHouse region) | OddsPapi serves us from `oddspapi-us1` with Cloudflare `-IAD` `[OP §7.3]`; OpticOdds `cf-ray` also `-IAD` `[OO-probe]`; Kalshi is AWS us-east `[R1-pplx §4]`; ClickHouse Cloud has no `us-east4` `[R1-gpt §2.3]` → egress budget in §1.3 |
| 7 | **Coalesce before ClickHouse; archive everything** | Insert every tick; sample the archive | 81–87 % Polymarket churn and DK re-confirmations `[OO-probe #6][OP §5.2]`; egress and storage budgets; research needs the raw ledger, trading needs the latest state |
| 8 | **Canonical fixture id = OpticOdds id; join OddsPapi via `opticoddsId`, SharpSports via `oddsjamId`, then team+time** | OddsPapi id as canonical; Betradar id | OpticOdds id is present on both other vendors' records (`opticoddsId` `[OP §6.1]`, `oddsjamId == game_id` `[XJ][OO §3.2]`); reverse mapping through OddsPapi is not entitled (`bookmaker=opticodds` → 403 `[OP §9.1]`) |
| 9 | **Canonical quote identity `(book, fixture, market, period, selection, line)` with provider ids retained** | Provider-native ids only | Enables cross-provider comparison and dedup; OddsPapi's frozen `outcomeId` and OpticOdds `grouping_key`/`normalized_selection` are kept in `provider_odd_id`/`grouping_key` for exact grouping `[CODE canonical/models.py][OO §3.6]` |
| 10 | **SharpSports for stats/historic/DFS lines only, never for real-time pricing** | Use `/prices` as a third real-time source | No timestamps on prices `[SS-sum ss-betprices]`; 2–7 s league payloads `[SS §1.7]`; but unique game logs, DVP, park factors, injuries with `played`, OHLC, `consensusProjection`, `bookIds` `[SS §1.1][SS-sum ss-historicdata]` |
| 11 | **Three clocks on every quote row** | Receive time only | Latency attribution and per-book lag are core research products `[OP §7.1][R2-gpt §5.2]` |
| 12 | **In-process board in Phase 1; Redis Streams IPC in Phase 2; no Kafka/PubSub** | Kafka, Pub/Sub, ZeroMQ | One VM, one team; Redis gives replayable streams and a last-state cache at zero cost; Kafka adds ops without benefit at this scale |
| 13 | **Fee schedules and settlement rules as versioned data, refreshed from venues** | Hard-coded constants | Fees changed in 2026 (Polymarket sports rate and rebate share) `[R2-opus §2.2]`; settlement discretion is the dominant PM arb risk |
| 14 | **`exclude_fees=true` on every OpticOdds exchange pull; fees modelled by us** | Take vendor fee-adjusted prices | Vendor adjustment is opaque and differs by book (`-10421` vs `-9900`) `[OO §3.6]`; our fee table is versioned and venue-specific |
| 15 | **No direct sportsbook scraping in step one; SOAX reserved for Phase 3 validation** | Scrape books for latency ground truth now | Brief scope; ToS/CFAA exposure `[R3-gem §5]`; vendor feeds already give per-book timestamps |
| 16 | **Secrets: `.env` (600) now, Secret Manager later; rotate OpticOdds key after probes; redact keys in all logs** | Leave as is | Queue-status endpoint echoes the key `[OO §1.1]`; OddsPapi key in URLs `[OP §9.3]`; Perplexity key exposure |
| 17 | **ClickHouse Cloud trial consumed in month 2, self-hosted single node before/after** | Start the trial immediately | Month 1 is deployment and volume-cap work; the trial should cover a full in-season month with the caps in place; a 30-day trial cannot span 90 days `[R1-gpt §2.1]` |
| 18 | **Edge priority: PM arbitrage and market making first, soft-book edges as capped side lines** | Latency arb and promos first (highest per-unit ROI) | Structural edges scale and are not account-mortal; soft-book edges self-terminate `[R2-opus §0, §2.1][R2-gpt §4]` |
| 19 | **Prediction-market non-sport streams limited to one category by default** | All categories | 933 snapshots/s and 120 MB/45 s for politics alone `[OO-probe #6]`; no execution venue for non-sport markets in Phases 1–2 |
| 20 | **OpticOdds results streams one connection per league, futures by REST poll** | One results stream per sport; futures SSE | Vendor guidance is one league per results connection `[OO §1.4]`; futures SSE produced 0 events in 30–60 s windows while REST returned 5,755 NFL odds `[OO §2.4, §2.10]` |

---

## 11. Appendices

### 11.1 Volume model (per stream, after caps)

| Stream | Observed uncapped | Cap policy | Rows/s to ClickHouse (est.) | Raw GB/day (zstd, est.) |
|---|---|---|---|---|
| OddsPapi `odds` (14 universe books, 6 sports) | 27–500 msg/s, 2–59 oddsIds/msg | change-only + 60 s heartbeat | 400–1,500 | 2–6 |
| OddsPapi `fixtures/scores/clocks` | 738 fixtures msgs / 23 scores per capture window | as-is (small) | < 50 | 0.3 |
| OpticOdds `odds` × 20 connections | 223 (baseball) – 1,544 (soccer all leagues) rec/s per connection | league filter + change-only + 60 s heartbeat; ladders top-3, ≤ 1/s | 500–2,000 | 3–6 |
| OpticOdds results × ≤ 9 | 11 events/30 s (tennis) | as-is | < 20 | 0.1 |
| OpticOdds PM politics | 933 snapshots/s | ≤ 1/s per market | 100–300 | 1–2 |
| SharpSports targeted polls | 1.67 MB per event-minute, 3.78 MB per DFS league call | store diffs only | 100–300 | 0.5–1 |
| **Total** | | | **≈ 1.2–4k rows/s** | **≈ 7–15 GB/day** |

### 11.2 Identifier glossary

| Concept | OpticOdds | OddsPapi | SharpSports |
|---|---|---|---|
| Fixture | `id` (`20260902FF9AD242`), `game_id` (`40548-37337-2026-09-02-16`) `[OO §3.2]` | `fixtureId` (`id1300010963302451`) `[OP §3.2]` | `EVNT_…`, `oddsjamId` (= OpticOdds `game_id`), `sportradarId`, `theOddsApiId` `[SS-sum ss-core]` |
| Book | slug (`draftkings`, `betfair_exchange_lay_`) `[OO §3.2]` | slug (`betfair-ex`, `betonline.ag`) `[OP §3.2]` | 2-char abbr (`dk`, `pn`, `kl`, `pm`, `pp`, `ud`) `[SS §1.1]` |
| Market | `market_id` slug (`run_line`) + `market_type_id` `[OO §3.2]` | frozen int `marketId` (= lowest `outcomeId`), one per line `[OP §3.13]` | `MKT_…` + `name` grammar `[SS-sum ss-market-taxonomy]` |
| Selection | `normalized_selection` + `selection_line` + `points`; odd `id` `[OO §3.6]` | `outcomeId` + `playerId`; `oddsId = fixture:book:outcome:player` `[OP §3.2]` | `MRKT_…` marketSelection + `line` per price `[SS-sum ss-betprices]` |
| Player | league-scoped hex `id`, `base_id` `[OO §3.2]` | int `playerId` `[OP §3.11]` | `PLYR_…`, `oddsjamId` (12 hex), `sportradarId` |
| Venue-native ids | `source_ids` (Kalshi ticker + yes/no, Polymarket token, Novig uuid, Betfair ids) `[OO §3.6]` | `bookmakerMarketId`, `bookmakerOutcomeId`, `bookmakerFixtureId` `[OP §6.2]` | `bookIds {eventId, marketId, selectionId}` `[SS §1.1]` |
| Timestamps | odd `timestamp` float s; `entry_id` ms; PM `timestamp_ns` `[OO §3.13]` | `bookmakerChangedAt`, `changedAt`, `ts` ms; `startTime` s `[OP §3.14]` | none on prices; ISO on events |

### 11.3 Repository layout after Phase 1

```
u3ingest/            providers/{oddspapi,opticodds,sharpsports}  canonical/  mapping/  sinks/  pricing/  replay.py
                     coalesce.py  batch/{scheduler.py, jobs/*.py}  metrics.py  board/ (Phase 2)
schemas/             clickhouse.sql (existing + §4.8)  bigquery/*.sql
deploy/              vm.sh  units/*.service  oo_streams.yaml  ss_poll.yaml  batch.yaml  env.example
mapping/             overrides.yaml  weights.yaml (Phase 2)  fees.yaml (Phase 2)  settlement_rules.yaml (Phase 2)
docs/                PLAN.md  research/{oddspapi,opticodds,sharpsports,cross-provider-mapping}.md  runbooks/*.md
tools/research/      probes and synthesis scripts (unchanged)
tests/               test_core.py  test_normalize.py  test_gcs.py  test_replay.py  test_pricing.py  test_coalesce.py  bench_replay.py
```

### 11.4 Reconciliation checklist when pending documents land
- `docs/research/opticodds.md` §4–§10: confirm SSE protocol details (ping cadence, `last_entry_id` conclusion, results-per-league rule), historical retention numbers, latency figures and the vendor's own recommended ingestion strategy; update §2.3, §4.3, §4.9 citations from `[OO-probe]`/`[OO-sum]` to `[OO §n]`.
- `docs/research/sharpsports.md` §3+: confirm the `/prices` no-timestamp statement, `Market.name` grammar, historicData shapes and the `hits`-counts-overs rule; update `[SS-sum]` citations.
- `docs/research/cross-provider-mapping.md`: replace §3 of this plan's interim mapping statement with a reference; adopt its canonical schema names if they differ from `u3ingest/canonical/models.py`.
