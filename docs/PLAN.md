# u3 — Integration & Ingestion Plan (sports + prediction-market trading data platform)

**Status:** definitive plan for step one (ingestion foundation) and the phases it must serve. Written 2026-09-03 against the live probes and provider specs in `docs/research/`, the current `u3ingest` implementation, and the external research briefs. Where a research brief disagrees with our own probes, the probe wins.

**Citation keys used below**
- `[OP §n]` — `docs/research/oddspapi.md` section n (live-probed spec).
- `[OO §n]` — `docs/research/opticodds.md` section n (live-probed spec; App A = grader settlement rules, App C = market types).
- `[SS §n]` — `docs/research/sharpsports.md` section n (live-probed spec).
- `[XM §n]` — `docs/research/cross-provider-mapping.md` section n (identity resolution, canonical schema, mapping QA, numbered gaps in §5).
- `[XJ]` — cross-provider live join probe (`cross.md`, 2026-09-03T10:45Z).
- `[CODE path]` — implementation on branch `claude/arbitrage-api-integration-plan-pphn75`, which now includes the merged Copilot PRs #3 (GCS archive sync, `u3ingest/sinks/gcs.py`), #4 (replay to Parquet/DuckDB, `u3ingest/replay.py`) and #5 (pricing library, `u3ingest/pricing/`).
- `[R1-gpt]`, `[R1-pplx]` (infrastructure), `[R2-gpt]`, `[R2-gem]`, `[R2-opus]`, `[R2-pplx]` (methodology/edges), `[R3-gem]`, `[R3-pplx]` (vendor landscape) — external web-grounded briefs.

---

## 0. Executive summary

We are building the data spine of a small proprietary trading operation across sportsbooks, sports prediction markets (Kalshi, Polymarket, Novig, ProphetX, Betfair) and non-sport prediction markets. Step one is done in prototype form; this document turns it into a production-shaped, budget-bounded system and sets up the fair-value, edge-detection and execution phases that consume it.

**What we have proven (Phase 0, this week).** A Python asyncio pipeline (`u3ingest`) that bootstraps fixture/market/book registries from all three vendors, joins fixtures across vendors, streams OpticOdds SSE and the OddsPapi WebSocket, polls SharpSports, archives every raw payload to gzip JSONL partitioned by provider/stream/hour, normalizes to one canonical `Quote`/`OrderBookLevel` model, and batch-inserts into ClickHouse. A 75 s live run on baseball + soccer produced 381,188 canonical quotes, 1,311,005 order-book levels and 105,128 raw messages (52 MB gz) with zero normalization errors `[CODE docs/research/README.md]`. Merged since: GCS archive sync, replay of the raw archive into Parquet/DuckDB, and a devig/consensus/board pricing library `[CODE]`. Three definitive provider specs and a cross-provider mapping document exist `[OP][OO][SS][XM]`.

**The ten decisions that shape everything else** (full rationale in §10):
1. **OddsPapi WS is the primary real-time sportsbook feed; OpticOdds is primary for breadth, prediction-market order books, DFS pick'em, futures, results/grading and non-sport markets; SharpSports is primary for stats/historic context and DFS +100 lines, never for real-time pricing** (its `/prices` carries no timestamp `[SS §3.6]`).
2. **Python asyncio stays the hot-path runtime** through Phase 2, behind an explicit benchmark gate (≥ 40k normalized rows/s sustained, p99 < 10 ms in-process) that, if failed, carves out only the decode/normalize stage into Rust — not a rewrite.
3. **Raw archive first**: GCS is the source of truth; ClickHouse and BigQuery are rebuildable from it (`u3-ingest replay` `[CODE u3ingest/replay.py]`).
4. **One on-demand `e2-standard-2` VM in `us-east4`** runs all long-lived socket consumers; no Cloud Run, no GKE, no Cloud NAT, no Kafka `[R1-gpt §1.3, §1.4]`. Batch/backfill on the same VM off-peak, or a Spot VM.
5. **ClickHouse = hot tick store (≤ 45-day TTL) and the board's analytical mirror; BigQuery = research warehouse over Parquet in GCS (free tier + GCP credit); Snowflake = optional 30-day sprint for SharpSports stats joins, not always-on** `[R1-gpt §3]`.
6. **Coalesce before you ship**: Polymarket alone is 81–87 % of both vendors' sports-odds message volume `[OO §4.2][OP §4.10]`; we archive raw but insert only change-level, top-N-level rows to ClickHouse and cap egress at ≈ $20/month.
7. **Trial-credit budget**: ≈ $76–104/month on GCP → ≈ $280 over 90 days; ClickHouse Cloud trial consumed in month 2; Snowflake trial optional in month 3.
8. **Canonical fixture id = OpticOdds fixture id**, joined to OddsPapi via `externalProviders.opticoddsId` (100 % on MLB/EPL, 91 % NCAAF) and to SharpSports via `oddsjamId == OpticOdds game_id` (37/40 MLB, 100/100 NFL) with team+time fallback `[XM §1.3.2]`; teams join exactly via SharpSports `Team.oddsjamId == OpticOdds team id` (NFL 32/32, MLB 30/30) `[XM §1.4]`.
9. **Three clocks on every quote** (`source_ts_ms`, `gateway_ts_ms`, `recv_ns`) so latency attribution and per-book lag are measurable from day one `[OP §7.1][XM §2.6]`.
10. **Edges are prioritized by durability, not headline size**: sportsbook-vs-Kalshi/Polymarket arbitrage and prediction-market market-making (structural, scalable) come before soft-book edges (high ROI, account-mortal).

**Phased roadmap.** Phase 0 (done): ingestion MVP. Phase 1 (weeks 2–4): cloud deployment, resilience (zstd-dict WS, reconciliation sweeps, SSE re-hydration), the 24 mapping gaps, settlement/CLV/backfill workers, warehouse, observability. Phase 2 (weeks 5–8): fair-value engine, edge detectors, alerting, paper-trading ledger, CLV loop. Phase 3 (weeks 9–12+): execution adapters (Kalshi/Polymarket first), risk engine, market-making pilot.

**Code corrections surfaced by the specs** (scheduled in §7, Phase 1 week 2; some are in flight in the working tree): remove `novig`, `hardrock`, `thescore`, `sporttrade`, `prizepicks`, `underdog`, `fanatics` from the OddsPapi bookmaker filter and fix `betfair` → `betfair-ex` (`[XM §5 #1]`, not among the 31 entitled slugs `[OP §1.1]`); use OpticOdds league id `usa_-_major_league_soccer` (the probe key `mls` returned 0 fixtures `[XM §1.2]`); use SharpSports `LGUE_ncaamb` for NCAAB and pass `ascending=true` to `/events` (default sort is descending `[SS §2.3]`); default OddsPapi `receiveType` to `zstd-dict` `[OP §10.2]`; add `league=`, `exclude_fees=true` and `odds_format=DECIMAL` to OpticOdds SSE (fee-adjusted American prices and American-format ladders today `[OO §3.6][XM §5 #9]`); add `provider` to the `quotes_latest` key `[XM §5 #8]`; apply OddsPapi `staleOdds`/`suspended`/`hasOdds` gates `[XM §5 #11]`; map OddsPapi live period keys `result|fulltime|p1..pN` and OpticOdds `selection_line` yes/no `[XM §5 #4–7]`; replace league-wide SharpSports polling `[SS §10.2]`.

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
 │   u3-oo-sse    OpticOdds /stream/odds/{sport} × book-bundles │ /stream/results per league │ /pm │
 │   u3-ss-poll   SharpSports /prices per event (L3) │ DFS + Pinnacle league polls │ /events        │
 │   u3-batch     scheduler: REST sweeps, settlement, CLV, futures, injuries, backfills            │
 │   u3-sync      GCS archive sync, every 5 min, crc32c-verified, manifest                         │
 │   u3-board     (Phase 2) in-memory book + fair value + detectors; Redis Streams IPC             │
 │   alloy        Grafana Agent → Grafana Cloud Free (metrics); journald → Cloud Logging (sampled) │
 │                                                                                                 │
 │   local disk: raw JSONL spool (data/raw/…, ≤ 48 h), Redis (Phase 2), SQLite cursors             │
 └───────────┬───────────────────────────┬───────────────────────────────┬───────────────────────┘
             │ raw archive               │ coalesced rows (native TLS 9440)│ Parquet (replay)
             ▼                           ▼                                  ▼
   GCS bucket u3-raw               ClickHouse (Cloud trial month 2;        BigQuery datasets
   raw/<provider>/<stream>/        self-hosted fallback)                    u3_raw (external tables)
   dt=/hour=/*.jsonl.zst           db u3: quotes, order_book_levels,        u3_marts (CLV, settlement,
   lifecycle: Nearline 30 d,       fixture_xref, quotes_latest MV,          stats joins, backtests)
   Coldline 180 d, never delete    settlements, clv, book_xref, ...         Snowflake (optional sprint)
```

**Languages/runtimes.** Python 3.11+, `asyncio` with `uvloop`, `orjson`, `httpx`, `websockets`, `zstandard`, `msgpack`, `clickhouse-connect`, `pyarrow`/`duckdb` for research `[CODE pyproject.toml]`. No second language until the benchmark gate in §1.5 fails. SQL (ClickHouse, BigQuery). Bash/systemd for ops; a `deploy/` directory with `gcloud` scripts (no Terraform until there is more than one VM).

**Message flow (hot path).**
1. Socket reader decodes a frame (zstd-dict → JSON for OddsPapi; SSE text for OpticOdds) and stamps `recv_ns` `[CODE providers/oddspapi/ws.py, providers/opticodds/sse.py]`.
2. The raw payload is appended to the `RawArchive` buffer **before** normalization; normalization errors never drop raw data `[CODE sinks/raw.py, pipeline.py]`.
3. Normalizer resolves book id (`BookRegistry`), canonical fixture id (`FixtureRegistry`), market/period/selection/line keys (`canonical/markets.py`) and emits `Quote` and `OrderBookLevel` rows carrying `source_ts_ms`, `gateway_ts_ms`, `recv_ns` `[CODE canonical/models.py][XM §2.6–2.7]`.
4. Rows pass through the **coalescer** (§1.4, §1.8, Phase 1) and then to the ClickHouse sink (batched async inserts, 5,000 rows or 1 s) `[CODE sinks/clickhouse.py]`.
5. (Phase 2) The same rows update the in-process `Board` (latest quote per `(fixture, market, period, line, selection, book)`) `[CODE u3ingest/pricing/board.py]` and are published on Redis Streams for detectors.

**Batch path.** `u3-batch` runs scheduled REST jobs (§2.4, §4) under the vendor rate limiters already implemented (`SlidingWindowLimiter`: OpticOdds 2,400/15 s standard, 10/15 s historical, 240/15 s stream connects; OddsPapi 9/1 s odds and 190/60 s other; SharpSports 45/1 s and 18/1 s large-list `[CODE util.py, providers/*/rest.py]`), archives every body, and writes settlement/CLV/dimension tables. Backfills run as one-shot CLI commands.

### 1.2 What runs where, and what we turn off

| Workload | Runs on | Why | Turned off / deferred |
|---|---|---|---|
| WS/SSE consumers, raw spool, coalescer, ClickHouse inserts | GCE `e2-standard-2` (2 vCPU/8 GiB), on-demand, external IPv4, egress-only firewall, IAP SSH | Long-lived sockets need a stable process, no request timeouts, fixed IP `[R1-gpt §1.3]`; Cloud Run WebSockets are requests with timeouts `[R1-gpt §1.3]` | Cloud Run, GKE Autopilot, Cloud NAT (charges per GiB processed `[R1-gpt §1.4]`), Spot for the only live consumer |
| REST sweeps, settlement/CLV workers, backfills | same VM, `u3-batch` (nice 10); large backfills on a Spot `e2-standard-2` (~$29/mo) only when needed `[R1-gpt §1.2]` | Batch is bursty; Spot preemption is harmless for idempotent jobs | — |
| Raw archive | GCS Standard → Nearline at 30 d → Coldline at 180 d (lifecycle rule) | Immutable source of truth, cheap; in-play history, depth history, locks and non-sport books are retrievable from nowhere else `[OO §5.3]` | Deleting raw data (never) |
| Hot tick store + board mirror | ClickHouse Cloud (GCP `us-east1`, Basic 1×8 GiB) during the 30-day/$300 trial in **month 2**; self-hosted single-node ClickHouse in Docker on the VM with 7-day TTL before/after | Cloud trial covers exactly one month of 24/7 ingest (≈ $186/mo list `[R1-gpt §2.1]`); `us-east4` is not a ClickHouse GCP region `[R1-gpt §2.3]` | Idle scaling (unusable under continuous ingest `[R1-gpt §2.2]`); paid ClickHouse before the economics are validated |
| Research warehouse | BigQuery: external tables over Parquet produced by `u3-ingest replay` `[CODE replay.py]`, plus native mart tables | Same $300 credit, permanent free tier (10 GiB storage, 1 TiB queries/mo) `[R1-pplx §3]` | BigQuery streaming inserts of raw ticks (cost + small-file behaviour `[R1-gpt §3.3]`) |
| SharpSports stats/historic joins | BigQuery by default; Snowflake $400/30-day trial as an optional month-3 research sprint | Snowflake has no free tier; sandbox cannot reach it (cert-pinned) | Snowpipe Streaming; any always-on Snowflake warehouse |
| Metrics/alerting | Grafana Cloud Free (10k series, 14-day retention) `[R1-gpt §5.4]` | Zero cost, hosted alerting | Self-hosted Prometheus/Grafana; per-market metric labels (cardinality) |
| Non-sport prediction-market streams | `politics` and `crypto` (the only non-empty canonical categories `[OO §2.9]`) archived continuously; others when `/canonical-events/ids` becomes non-empty | politics 933 snapshots/s, 120 MB/45 s; crypto 514/s `[OO §4.5]` | All 11 categories 24/7 |
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

Observed uncapped rates: OpticOdds SSE baseball (5 books) 223 records/s of which 81 % Polymarket, soccer (5 books, all leagues) 1,544 records/s ≈ 1.5 MB/s `[OO §4.2]`; OddsPapi WS unfiltered sports 10/11/13 ≈ 500 msg/s, 87 % Polymarket, 27 msg/s with the sharp/US book filter `[OP §4.10]`; DraftKings emits 433k ticks per MLB game (median 563 ms gap, re-confirmation churn) vs Pinnacle 25k `[OP §5.2]`; a single `/fixtures/odds` call for 3 fixtures × 5 books returns 4.99 MB with 811–1,401 DraftKings odds per fixture `[OO §2.4]`.

Controls:
1. **Raw archive**: keep everything, but switch the archive codec from gzip(3) to zstd(3) (≈ 30–40 % smaller for JSON) and add a per-stream `dedupe_identical` option that drops a record whose body hash equals the previous record for the same `provider_odd_id` within 2 s (re-confirmation churn is still counted in `stream_health`).
2. **ClickHouse `quotes`**: insert only rows where `(price_dec, line, active, limit_max, is_main)` changed versus the in-memory last state, or ≥ 60 s since the last insert for that key (heartbeat row, `event_kind='heartbeat'`).
3. **ClickHouse `order_book_levels`**: top 3 levels per side, and at most 1 snapshot/s per `(book, venue_market_id, selection)`; deeper ladders stay in raw. Kalshi and Polymarket show up to 10 levels, Novig and Prophet X 1, Betfair Exchange none (lay side is the separate book `betfair_exchange_lay_`) `[OO §8.1]`.
4. **Non-sport PM stream**: replace-not-patch snapshots `[OO §4.5]` are coalesced to ≤ 1/s per market for ClickHouse; raw keeps all.
5. **Scope filters**: OpticOdds SSE `league=` limited to the trading universe (§2.1); OddsPapi WS `sportIds` 10–15 with `bookmakers` = the universe books.

### 1.5 Runtime decision and benchmark gate

Research briefs recommend Go or Rust for a 5–20k rows/s consumer and say Python+uvloop "may handle 5k–20k simple messages/sec" but must be load-tested `[R1-gpt §5.1][R1-pplx §5]`. Our prototype already sustained ≈ 5k quotes/s + 17k levels/s end-to-end (parse → normalize → archive → ClickHouse rows) in this sandbox with zero errors `[CODE README]`. Decision: keep Python, add the acceptance benchmark from `[R1-gpt §5.1]` as a CI job that replays a captured 10-minute corpus through the exact decode/normalize/coalesce path (`u3-ingest replay`) and asserts ≥ 40k rows/s, p99 < 10 ms per message, no RSS growth over the run. If the gate fails after profiling (orjson, slots dataclasses, avoiding `asdict`), the decode+normalize stage for the OddsPapi `odds` channel is rewritten as a small Rust extension (PyO3); everything else stays Python.

### 1.6 Process inventory (systemd units on the VM)

| Unit | Command | CPU/RSS budget | Restart policy | Watchdog condition |
|---|---|---|---|---|
| `u3-op-ws.service` | `u3-ingest run --only oddspapi-ws --connections odds,fixtures,aux` | 0.6 vCPU / 1.5 GiB | `Restart=always`, `RestartSec=2` | last data frame age < 30 s on conn #1 during a live slate |
| `u3-oo-sse.service` | `u3-ingest run --only opticodds-sse --plan deploy/oo_streams.yaml` | 0.6 vCPU / 1.5 GiB | same | `ping` seen ≤ 15 s ago on every stream `[OO §4.7]` |
| `u3-ss-poll.service` | `u3-ingest run --only sharpsports --plan deploy/ss_poll.yaml` | 0.1 vCPU / 0.5 GiB | same | last successful `/prices` < 5 min |
| `u3-batch.service` | `u3-ingest batch --schedule deploy/batch.yaml` | 0.3 vCPU / 1 GiB (nice 10) | same | scheduler heartbeat < 2 min |
| `u3-sync.service` | `u3-ingest archive-sync --every 300` `[CODE cli.py]` | 0.1 vCPU / 0.3 GiB | same | newest uploaded object per stream < 2 h old |
| `u3-board.service` (Phase 2) | `u3-board --redis localhost:6379` | 0.4 vCPU / 1 GiB | same | detector loop age < 5 s |
| `redis.service` (Phase 2) | `redis-server --maxmemory 512mb --maxmemory-policy allkeys-lru` | 0.1 vCPU / 0.5 GiB | same | ping |
| `clickhouse` (self-hosted months 1/3, Docker) | `clickhouse-server` with `max_server_memory_usage=3G` | 0.5 vCPU / 3 GiB | Docker restart | `SELECT 1` |
| `alloy.service` | Grafana Alloy scraping `:9100` (node) and `:91xx` (u3 exporters) | 0.05 vCPU / 0.2 GiB | same | remote-write success |

The `e2-standard-2` (2 vCPU / 8 GiB) fits months 1 and 3 with self-hosted ClickHouse only because inserts are coalesced and TTL is 7 days; if RSS exceeds 6.5 GiB, move ClickHouse to a Spot `e2-standard-2` or start the Cloud trial early.

### 1.7 Storage layout and retention

**GCS (`gs://u3-raw`)** — `raw/<provider>/<stream>/dt=YYYY-MM-DD/hour=HH/<stream>-<process_start_ms>.jsonl.zst` (current layout with gzip `[CODE sinks/raw.py][XM §3.2]`; zstd from Phase 1). Streams: `oddspapi/ws-odds`, `oddspapi/ws-fixtures`, `oddspapi/ws-aux`, `oddspapi/rest-<endpoint>`, `opticodds/sse-odds-<sport>-<bundle>`, `opticodds/sse-results-<league>`, `opticodds/sse-pm-<category>`, `opticodds/rest-<endpoint>`, `sharpsports/prices-<scope>`, `sharpsports/rest-<endpoint>`, `bootstrap/registries`. Each hour also gets `manifest.json` (rows, bytes, sha256, min/max `recv_ns`). Lifecycle: Nearline at 30 d, Coldline at 180 d, no deletion. `gs://u3-parquet/<table>/dt=…/part-N.parquet` from nightly replay.

**ClickHouse (`u3`)** — implemented: `quotes` (MergeTree, `PARTITION BY toDate(recv_ts)`, `ORDER BY (fixture_id, market, period, selection, book_id, recv_ns)`), `order_book_levels`, `fixture_xref` (ReplacingMergeTree), `quotes_latest` (MV), `quote_latency` (view) `[CODE schemas/clickhouse.sql][XM §3.1]`. Retention changes: `quotes` TTL 400 d → **45 d** on Cloud (7 d self-hosted), `order_book_levels` 180 d → **14 d** (`[XM §3.4]` suggests 60–90 d; we take the lower bound for the trial and rely on GCS). Planned tables follow the mapping doc's names `[XM §3.3]`: `sports`, `leagues`, `fixtures`, `teams`, `team_xref`, `players`, `player_xref`, `books`, `book_xref`, `markets`, `market_xref`, `quote_snapshots`, `book_status`, `results`, `settlements`, `clv`, `injuries`, `player_game_stats`, `team_game_stats`, `mapping_queue`, `mapping_metrics`; plus this plan's `stream_health`, `pm_books` and (Phase 2) `signals`, (Phase 3) `orders`/`fills`. DDL sketches for the ones ingestion writes first are in §4.8.

**BigQuery** — dataset `u3_raw`: external tables over `gs://u3-parquet/{quotes,order_book_levels}`; dataset `u3_marts`: `dim_fixture`, `dim_book`, `dim_market`, `settlement`, `clv`, `book_lag_daily`, `player_game_log`, `injury_history`, `signals` (Phase 2). Partition by `dt`, cluster by `fixture_id, market`.

**Snowflake (optional)** — schema `SS_HISTORIC` for SharpSports player/team logs and open/close windows if a month-3 research sprint needs Snowflake-specific features; otherwise BigQuery.

### 1.8 Coalescer specification

```python
class Coalescer:
    """Sits between normalizers and the ClickHouse sink. Raw archive is untouched."""
    HEARTBEAT_NS = 60_000_000_000          # emit a row at least every 60 s per key
    LEVEL_MAX = 3                          # top-N ladder levels per side
    LEVEL_MIN_GAP_NS = 1_000_000_000       # <= 1 snapshot/s per (book, venue_market_id, selection)

    def quote(self, q: Quote) -> Quote | None:
        key = (q.provider, q.book_id, q.fixture_id, q.market, q.period, q.selection, q.line)
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
The `Board` (Phase 2) consumes **uncoalesced** rows in-process so trading state is never delayed by the coalescer; only ClickHouse and Redis publication are coalesced. The key includes `provider` because the same book is quoted by up to three providers `[XM §3.4]`.

---

## 2. Feed usage matrix

### 2.1 Universe

Canonical books priced against in Phase 1–2 (ids per `[XM §1.6]`): `pinnacle`, `draftkings`, `fanduel`, `betmgm`, `caesars`, `betrivers`, `kalshi`, `polymarket`, `novig` (OpticOdds only), `prophetx`, `circa`, `betonline`, `bookmaker`, `betfair_exchange` + `betfair_exchange_lay`, `sx_bet` (OddsPapi/OpticOdds), `prizepicks`/`underdog` (DFS, OpticOdds + SharpSports). Present in all three vendors: betmgm, betrivers, draftkings, fanduel, kalshi, polymarket (plus Pinnacle via SharpSports `pn`, which is `status: unsupported` but `oddsFeedActive: true`) `[XM headline][SS §3.7]`. Sporttrade is `inactive` in OpticOdds (last poll 101 days old) `[OO §1.1, §8.3]` and reportedly exited US sports betting in June 2026 `[R2-gpt §2.2]` — not modelled as an execution venue.

Leagues (canonical = OpticOdds league id; OddsPapi tournament id; SharpSports `LGUE_` id) `[XM §1.2]`: `mlb`/109/`LGUE_mlb`; `nba`/132/`LGUE_nba`; `wnba`/486/`LGUE_wnba`; `ncaab`/—/`LGUE_ncaamb`; `nfl`/31/`LGUE_nfl`; `ncaaf`/—/`LGUE_ncaaf`; `nhl`/234/`LGUE_nhl`; `england_-_premier_league`/17/`LGUE_542b6c4f…`; `usa_-_major_league_soccer`/242/`LGUE_269a3af2…`.

### 2.2 Matrix

| # | Data class | Primary provider / channel | Secondary / cross-check | Cadence | Rate-limit budget | Storage target |
|---|---|---|---|---|---|---|
| 1 | Fixture spine + cross-vendor ids | OddsPapi `GET /fixtures?sportId&startTimeFrom&startTimeTo` (7-day windows, back 400 d/forward 30 d) + WS `fixtures` channel `[OP §10.3, §10.4]` | OpticOdds `/fixtures/active?league&include_statsperform_id=true` (100/page `[OO §1.5]`); SharpSports `/events?league=LGUE_x&startTimeStart&startTimeEnd&ascending=true&limit=1000` `[SS §10.1]` | forward window every 5 min; bootstrap at start | OP 6 calls/5 min of 200/min; OO ≤ 27 calls/5 min of 8,000/15 s `[OO §1.4]`; SS 9 calls/5 min of 50/s `[SS §1.4]` | `u3.fixture_xref` `[CODE]`, `fixtures`, `leagues` `[XM §3.3]`; BQ `dim_fixture` |
| 2 | Pre-match sportsbook odds, main + alt lines | OddsPapi WS `odds`+`bookmakers`, `receiveType=zstd-dict`, `sportIds 10–15`, universe books (conn #1) `[OP §10.2]` | OpticOdds SSE `/stream/odds/{sport}?sportsbook×5&league×≤10&odds_format=DECIMAL&exclude_fees=true&include_fixture_updates=true` per bundle `[OO §4.2]`; OddsPapi REST `/fixtures/odds/main?fixtureIds≤50&since` reconciliation sweep `[OP §10.3]` | WS push; sweep every 60 s | OP odds bucket 10/s: sweep ≈ 2/s, on-demand snapshots ≤ 3/s, ≥ 3/s headroom `[OP §10.3]`; OO SSE connects 250/15 s `[OO §1.4]` | raw GCS; `u3.quotes` (coalesced); `u3.quotes_latest` MV |
| 3 | Player props | OpticOdds SSE (229 books; `player_id`, `grouping_key`, `normalized_selection`) `[OO §3.6]` | OddsPapi (19 of 31 books with `playerProps:true`; 2,835 prop quotes on one EPL fixture) `[OP §1.1, §8.3]`; SharpSports `/prices?eventId` (703 selections / 2,888 prices per MLB game) `[SS §3.5]` | SSE push; OP WS push | included in #2 | `u3.quotes` (market `player:*`, `player_id`) + `player_xref` `[XM §1.5]` |
| 4 | In-play odds | OddsPapi WS (`access.live:true`; Pinnacle `maxDelayLiveInSec` 0.38 s, DraftKings 0.21 s `[XM §1.6]`) | OpticOdds SSE `is_live` per record (49 % of baseball stream) `[OO §4.2]` | push | included in #2 | `u3.quotes` (`extra.is_live`, status from #10) |
| 5 | Sports prediction-market order books (Kalshi, Polymarket, Novig, ProphetX, Betfair, SX) | OpticOdds SSE/REST `order_book [[price,size]]` (Kalshi/Polymarket up to 10 levels), `limits.max` (= top-of-book size), `source_ids` (Kalshi ticker + yes/no, Polymarket clobTokenId, Novig uuids, Betfair ids), `exclude_fees=true` (Polymarket `price` is fee-adjusted by default) `[OO §3.6, §8.1]` | OddsPapi `meta` ladders for `polymarket`, `kalshi`, `betfair-ex`, `sx.bet` with USD notional per rung (`limit = size × cents`) `[OP §3.6, §8.1][XM §2.5]` | push | included in #2 | `u3.order_book_levels` (top-3, ≤ 1/s), raw full depth |
| 6 | Non-sport prediction markets (politics, crypto, …) | OpticOdds `/stream/prediction-markets?category=` (one category per connection; bootstrap snapshot per market then change-driven; `canonical_id` on most politics snapshots) + REST `/prediction-markets/canonical-events/ids` → `/canonical-events?canonical_id×≤25` (`question` present live) `[OO §2.9, §4.5, §3.11]` | none — OddsPapi sportIds 69–78 not entitled `[OP §1.1]` | push (politics 933 snapshots/s) | PM backend, no rate-limit headers `[OO §1.3]` | raw GCS; `u3.order_book_levels` (`side` bid/ask, `fixture_id = pm:<platform>:<source_market_id>`) `[XM §1.7][CODE pm_snapshot_levels]`; `u3.pm_books` summary |
| 7 | Futures / outrights | OpticOdds REST `/futures/odds?league&sportsbook×5` (NFL × 5 books = 5,755 odds / 2.45 MB; Kalshi 475 NFL futures odds) — SSE futures emitted 0 events in 30–60 s windows `[OO §2.4, §4.4, §8.4]` | OddsPapi futures **metadata only** (`/futures`, WS `futures`); prices 403 `channel_not_allowed` `[OP §2.4]`; SharpSports `Future Winner` markets (Pinnacle 60 prices live) `[SS §3.9]` | poll every 15 min per league × 3 bundles | 27 calls/15 min of 8,000/15 s | `u3.quotes` (`market=future:<slug>`), raw |
| 8 | Sharp anchor (Pinnacle) | OddsPapi `pinnacle` with per-side `limit` (19,354 fav / 3,000 dog), `bookmakerChangedAt`, native `bookmakerMarketId` `[OP §8.1, §8.2]` | OpticOdds `pinnacle` (`limits.max` 1,000–15,850 on NFL mains; covered only 7/82 upcoming MLB fixtures — coverage starts near game time) `[OO §8.1, §8.2]`; SharpSports `pn` (main markets, `ev` field populated) `[SS §3.6, §8]` | push | — | `u3.quotes`; cross-provider latency view (Phase 1) |
| 9 | Book health / staleness | OddsPapi WS `bookmakers` (`staleOdds`, `suspended`, `hasOdds`, `participantsRotated`) + `GET /bookmakers` every 60 s (`lastOddsAt`, `staleOddsSince`, `staleThresholdSec`, `maxDelay*`) `[OP §7.2, §10.3]` | OpticOdds `/sportsbooks/last-polled?league` every 60 s (Unix-seconds; Kalshi poller 1,595 s stale at 07:24Z; dead pollers `sporttrade`, `betano_argentina_`) `[OO §7.2, §8.3]`; SSE `locked-odds` | 60 s | OP 1/min of 200/min; OO 9/min | `u3.book_status` `[XM §3.3]`; `u3.stream_health` |
| 10 | Scores, clock, in-play state | OddsPapi WS `fixtures`+`scores`+`clocks` (conn #3) `[OP §10.2]` | OpticOdds `/stream/results/{sport}?league=` — one connection per league; filter stale `unplayed` events by `status`/`start_date` `[OO §4.3]` | push | 1 SSE connection per in-season league | `u3.results` (`periods` + `in_play` JSON) `[XM §3.3]` |
| 11 | Results, grading, settlement | OddsPapi `/fixtures/settlement?fixtureId` (bookmaker-independent WIN/LOSE/PUSH/HALFWIN/HALFLOSS/CANCELLED/UNDECIDED; ≥ 1 y retention; 4–9 s latency; player props not graded) `[OP §3.9, §5.2, §8.6]` | OpticOdds `/grader/odds` (Won/Lost/Refunded/Pending/Half Won/Half Lost; market label + selection `name`; house-rule divergences in App A) `[OO §2.6, §3.10, App A]`, `/fixtures/results` (`market_stats`), `/fixtures/player-results` `[OO §3.9]` | `trueEndTime`+15 min then 30 m/2 h/6 h/24 h retries; concurrency ≤ 3 | OP ≤ 40 fixtures/min; OO grader ≤ 100/min | `u3.settlements` (transition history) `[XM §3.3]`, BQ `settlement` |
| 12 | Opening / closing lines, CLV | OddsPapi `/fixtures/odds/clv?fixtureId` at `trueStartTime`+30 min and `trueEndTime`+6 h (`clv` null pregame; 17–39 % null post-match → fallback chain) `[OP §8.5]` | OpticOdds `/fixtures/odds/historical` `olv`/`clv` (`clv` null ~8 h after the game, populated by ~2.3 d; exchange `olv` can be an illiquid first quote) `[OO §5.1, §5.2]`; **our own** T−60 s / T−5 s freeze snapshots `[OP §10.3]`; SharpSports `/prices/historic/summary` `books[].open/close` + `consensus` (history begins 2024-08) `[SS §3.10, §5.2]` | per fixture | OP 200/min; OO historical 50/15 s `[OO §1.4]` | `u3.clv` `[XM §3.3]`; BQ `clv` |
| 13 | Tick-history backfill (pre-season, research) | OddsPapi `/fixtures/odds/historical?fixtureId&bookmaker=pinnacle` (always) + `oddsIds=` main lines across ≤ 8 books (selective); ≈ 220–230 d retention `[OP §5.2, §10.4]` | OpticOdds `include_timeseries=true` (requires `market`; change-level `entries`, 1 s min gap, retained 57–60 d, pre-match only) `[OO §5.1, §5.2]`; SharpSports `/prices/historic/timeseries?rollup=5m|15m` (open/close per window only, ≤ 1,000 windows) `[SS §3.10]` | one-off + nightly for yesterday's fixtures | OP 200/min but 6–96 MB bodies → stream-parse, concurrency 2; OO 50/15 s ≈ 3.3 pulls/s | `u3.quotes` (`event_kind='history'`); BQ |
| 14 | Injuries, lineups, news | OpticOdds `/injuries?league` diff-polled every 60 s (paginated; statuses `il_60-day`, `il_7-day`, `out`, `suspended`; no timestamps; key `injury.id = <sport>:<league>:<player_id>`) + `/fixtures?include_starting_lineups=true` and `home_starter`/`away_starter` `[OO §2.7, §3.4, §3.10, §8.6]` | SharpSports `/injuries?league` (bare designation, `played` outcome flag; one row per player-event) `[SS §3.13]`; OddsPapi WS `injuries`/`lineups` (silent so far) `[OP §9.4]` | 60 s / T−2 h | OO 9/min | `u3.injuries` `[XM §3.3]`, BQ |
| 15 | Player/team stats, DVP, park factors, projections | SharpSports `/players/{id}/historicData` (NBA from 2023-01, NFL 2023-09, MLB 2024-03; soccer empty), `/marketSelections/{id}/metadata` (L1–L20 hit rates — `hits` counts overs regardless of side), `/teams|players/aggregateStats`, `consensusProjection`, park factor as signed % `[SS §3.11, §3.12, §5.1]` | OpticOdds `/fixtures/player-results` (`market_stats` map 1:1 to prop markets; `is_starter`, `batting_order`) `[OO §3.9, App B]` | nightly batch; pre-game T−3 h for slate | SS 50/s (player/team-scoped historic summaries take 55–98 s or time out — never in hot path `[SS §1.7]`) | BQ `player_game_log`, `dim_player`; `u3.player_game_stats` `[XM §3.3]` |
| 16 | DFS pick'em lines | OpticOdds sportsbook ids per payout structure (`prizepicks`, `prizepicks_5_or_6_pick_flex_`, `underdog_fantasy_2_pick_`, `draftkings_pick_6_`, `dabble_*`, `betr_picks_all_`) → parent book + `variant` `[XM §1.6]` | SharpSports `/prices?league&book=pp,ud` (mostly `+100`, also `-137/-119/-112`; 3.78 MB / 5.3 s per league) `[SS §3.6, §1.7]` | SSE push; SS every 2 min per league | SS 9 calls/2 min | `u3.quotes` (book_id `prizepicks`, `underdog`, never mixed with sportsbook quotes in the board) |
| 17 | Public/sharp flow (betSync) | SharpSports `/betSlips` (only our linked bettors incl. a Kalshi account; refresh 1/60 s per account; minutes-scale; `bookRef`, `adjusted{odds,line,atRisk}`) `[SS §1.1, §3.14]` | — | Phase 3 | 20/s | BQ `bet_slips` |
| 18 | FX for limit normalization | OddsPapi WS `currencies` (≈ 0.18/s) + `GET /currencies` hourly (USD base; `Bookmaker.limitCurrency` USD/EUR per book) `[OP §3.11, §7.2][XM §2.5]` | — | hourly | negligible | `u3.dim_currency`; `book_xref.limit_currency` |
| 19 | Reference catalogues | OddsPapi `/markets?sportId` × 6 (4,902 markets for basketball, 1,122 soccer), `/bookmakers`, `/tournaments`, `/participants`, `/players` `[OP §10.4]`; OpticOdds `/sportsbooks` (229), `/markets?markets_only=false` (coverage matrix), `/market-types` (43), `/leagues/active` (354) `[OO §2.1, §8.2, App C]`; SharpSports `/books` **and** `/books?status=unsupported`, `/markets?pageSize=1000` (≤ 5,000), `/segments` (95), `/metrics` (278), `/teams`, `/players?isMajorLeague=all` `[SS §3.7, §3.8, §9.3]` | — | daily + on unknown id | trivial | `sports`, `leagues`, `books`, `book_xref`, `markets`, `market_xref` `[XM §3.3]` |

### 2.3 Stream subscription plans (exact)

**OddsPapi WebSocket (5-connection cap `[OP §1.4]`)**

| Conn | `login` frame (apiKey redacted) | Purpose | Notes |
|---|---|---|---|
| #1 odds | `{"type":"login","apiKey":"***","clientName":"u3-op-odds","lang":"en","receiveType":"zstd-dict","channels":["odds","bookmakers"],"sportIds":[10,11,12,13,14,15],"bookmakers":["pinnacle","draftkings","fanduel","betmgm","caesars","betrivers","kalshi","polymarket","prophetx","circasports","betonline.ag","bookmaker.eu","betfair-ex","sx.bet"]}` | the money feed | `bookmakers` gating drops envelopes with no matching keys `[OP §4.2]`; verify with the `login_ok.bookmakers` echo that a 14-slug filter is accepted (the probe used 5) |
| #2 odds shadow (Phase 2) | identical to #1, second process | failover across `reconnect` releases; dedupe by `(oddsId, changedAt)` | optional until capital is live `[OP §10.2]` |
| #3 anchor | `{"type":"login",…,"receiveType":"zstd","channels":["fixtures","scores","clocks"],"sportIds":[10,11,12,13,14,15]}` | fixture dimension, `trueStartTime`/`trueEndTime`, scores, clock | `fixtures` is ~30× chattier than `scores` — keep it off #1 `[OP §4.10]` |
| #4 aux | `{"type":"login",…,"receiveType":"json","channels":["currencies","futures","bookmakersFutures","events","stats","injuries","lineups"],"sportIds":[10,11,12,13,14,15]}` | schema discovery; FX | six of these channels never emitted during the probe `[OP §4.10]` |
| #5 spare | — | reconnect overlap (connect-new-before-close-old), console, debugging | never used in steady state `[OP §10.2]` |

**OpticOdds SSE (≤ 5 books and ≤ 10 leagues per odds connection; results one per league; 250 connects/15 s `[OO §4.9]`)**

Bundles follow the spec's importance ordering `[OO §10.2]`, extended with the DFS ids we need for edge #5:

| Stream | Sport → leagues | Bundle (≤ 5 ids, validated against `/sportsbooks` `[OO §1.6]`) | Params | Conns |
|---|---|---|---|---|
| `/stream/odds/baseball` | `mlb` | **A** `pinnacle,draftkings,fanduel,polymarket,kalshi` · **B** `novig,prophet_x,betfair_exchange,betfair_exchange_lay_,circa_sports` · **C** `caesars,betmgm,bet365,betonline,betrivers` · **D** `prizepicks,prizepicks_5_or_6_pick_flex_,underdog_fantasy_2_pick_,draftkings_pick_6_,bookmaker` | `odds_format=DECIMAL&exclude_fees=true&include_fixture_updates=true` (`is_main` unset `[OO §4.2]`) | 4 |
| `/stream/odds/basketball` | `nba,wnba,ncaab` | A–D | same | 4 |
| `/stream/odds/football` | `nfl,ncaaf` | A–D | same | 4 |
| `/stream/odds/hockey` | `nhl` | A–D | same | 4 |
| `/stream/odds/soccer` | `england_-_premier_league,usa_-_major_league_soccer` | A–D | same (all-leagues soccer is 1.5 MB/s — never omit `league[]` `[OO §10.2]`) | 4 |
| `/stream/results/{sport}` | one per in-season league (≤ 9) | — | `league=<id>` | ≤ 9 |
| `/stream/prediction-markets` | — | — | `category=politics`, `category=crypto` | 2 |
| `/stream/futures/{sport}` | — | — | not used (silent); poll `/futures/odds` `[OO §4.4]` | 0 |

≈ 31 steady-state connections, staggered over ≥ 15 s at start `[OO §10.2]`; a full reconnect storm costs 31 of the 250/15 s connect budget. Every connection is archived under its own stream name so replay can rebuild per bundle.

**SharpSports (no streaming `[SS §4]`; polling loops per `[SS §10.2]`, sized for our budget)**

| Loop | Cadence | Call | Notes |
|---|---|---|---|
| L0 bootstrap | daily 04:00 UTC | `/books`, `/books?status=unsupported`, `/sports`, `/leagues`, `/segments`, `/metrics`, `/markets?pageSize=1000&pageNum=1..5`, `/teams?league=LGUE_x`, `/players?league=LGUE_x&isMajorLeague=all` | ~40 calls; persist raw; `oddsFeedActive` defines the price universe (12 books) `[SS §3.7]` |
| L1 events | every 15 min per league | `/events?league=LGUE_x&startTimeStart=today-1&startTimeEnd=today+7&ascending=true&limit=1000` (+ `future=true` daily) | detect new `EVNT_`, `startTime` changes; skip `startTime IS NULL` (futures containers) `[XM §5 #17]` |
| L2 selections | on new event; hourly on game day | `/marketSelections?eventId=&pageSize=100&pageNum=n` (15 pages for a 703-selection game); `historic=true` variant after the event | vendor ids (`oddsjam`, `sportradar`, `sportsdataio`), `betPlaceAvailability` |
| L3 prices | 60 s per event from T−24 h; 30 s from T−2 h; 15 s in-play (tracked events only) | `/prices?eventId=<a,b,c>` batched 3–5 ids (1.67 MB / 0.28 s each) `[SS §1.7]` | store `recv_ts` from the HTTP `date` header `[SS §7.2]`; diff-only rows to ClickHouse |
| L3' DFS | every 2 min per league | `/prices?league=LGUE_x&book=pp,ud` | +100 lines for edge #5 |
| L3'' catch-all | every 5 min per league | `/prices?league=LGUE_x` | reconciles missed events and futures containers; 17.5 MB / 2–7 s |
| L4 historic | nightly + event-driven after final | `/prices/historic/summary?eventId=&pageSize=100&pageNum=n`, then `timeseries?rollup=15m` for straights/headline props with explicit `[first_open−1 h, startTime+4 h]` | 150 s timeout, retry once, defer `[SS §10.3]` |
| L5 fundamentals | daily + T−3 h | `metadata` / `historicData` per tracked prop selection; `/injuries?league` hourly; `/trades/{TEAM_}?injuries=true` daily | ≤ 10 parallel |
| L6 betSync | webhook-driven + 5-min reconciliation | `/betSlips?timePlacedStart=<last>`; `refreshResponse.created` webhook (HMAC over raw body) | Phase 3 |

### 2.4 `u3-batch` schedule (cron, UTC)

| Job | Vendor / endpoint | Cron | Budget | Output |
|---|---|---|---|---|
| `op.fixtures.forward` | `GET /fixtures?sportId=S&startTimeFrom=now&startTimeTo=now+14d` × 6 | `*/5 * * * *` | 6/5 min of 200/min | `fixture_xref`, `fixtures` |
| `op.fixtures.live` | `GET /fixtures/live?sportId=S` × 6 | `* * * * *` | 6/min | status/live set |
| `op.bookmakers.health` | `GET /bookmakers` | `* * * * *` | 1/min | `book_status`, `book_xref` |
| `op.sweep.main` | `GET /fixtures/odds/main?fixtureIds≤50&since=<cursor>` sharded over in-window fixtures | continuous loop, ≈ 2 req/s | odds bucket 10/s | reconciliation, inactive removals |
| `op.freeze` | `GET /fixtures/odds?fixtureId=…` at T−60 s and T−5 s | event-driven | ≤ 1/s | `quotes` `event_kind='freeze'` |
| `op.markets` | `GET /markets?sportId=S` × 6 | `15 3 * * *` + on unknown `marketId` | trivial | `market_xref` |
| `op.currencies` | `GET /currencies` | `0 * * * *` | 1/h | `dim_currency` |
| `op.mapping` | `GET /fixtures/mapping?bookmaker=<slug>&fixtureIds=<batch>` for 8 execution books | on fixture discovery | 8 calls/batch | `fixture_xref` book-native ids |
| `op.settlement` | `GET /fixtures/settlement?fixtureId` | `trueEndTime`+15 m, retries 30 m/2 h/6 h/24 h | concurrency 3 (4–9 s each) | `settlements` |
| `op.clv` | `GET /fixtures/odds/clv?fixtureId` | `trueStartTime`+30 m, `trueEndTime`+6 h | 200/min | `clv` |
| `oo.fixtures.active` | `GET /fixtures/active?league=L&include_statsperform_id=true` × 9 | `*/5 * * * *` | ≤ 27 calls/5 min | `fixture_xref`, `fixtures` |
| `oo.last_polled` | `GET /sportsbooks/last-polled?league=L` × 9 | `* * * * *` | 9/min | `book_status` |
| `oo.injuries` | `GET /injuries?league=L` × 9 (paginated) | `* * * * *` | ≤ 27/min | `injuries` (diffs) |
| `oo.lineups` | `GET /fixtures?id=…&include_starting_lineups=true` | T−2 h, T−30 m | event-driven | `fixtures.lineups` |
| `oo.futures` | `GET /futures/odds?league=L&sportsbook×5` × 3 bundles × 9 leagues | `*/15 * * * *` | 27/15 min | `quotes` (`future:*`) |
| `oo.markets_active` | `GET /markets/active?fixture_id&sportsbook×5` | at activation + every 15 min | small | prune subscriptions; detect pulled markets `[OO §8.2]` |
| `oo.rehydrate` | `GET /fixtures/odds?fixture_id×5&sportsbook×5&odds_format=DECIMAL&exclude_fees=true` for fixtures active in the last 10 min | on SSE reconnect | ≤ 8,000/15 s (MLB full hydrate ≈ 50 calls `[OO §10.1]`) | `quotes` `event_kind='snapshot'` |
| `oo.grader` | `GET /grader/odds?fixture_id&market&name` for traded selections; `GET /fixtures/results`, `/fixtures/player-results` | completion + 2 h; nightly | ≤ 100/min | `settlements` (provider `opticodds`), `results` |
| `oo.pm.canonical` | `GET /prediction-markets/canonical-events/ids?category` → `/canonical-events?canonical_id×25` | `*/15 * * * *` | PM backend | `pm_canonical` |
| `oo.historical` | `GET /fixtures/odds/historical?fixture_id&sportsbook×5&market=…&include_timeseries=true` for yesterday's traded fixtures; re-pull at T+3 d for `clv` | `0 9 * * *` | 50/15 s | `quotes` `event_kind='history'`, `clv` |
| `ss.*` | loops L0–L6 of §2.3 | as listed | 50/s, 20/s large-list | `quotes`, `fixtures`, `injuries`, BQ |
| `sync.parquet` | `u3-ingest replay --since <yesterday> --until <today> --out gs://u3-parquet --out-format parquet` `[CODE replay.py]` | `30 6 * * *` | local CPU | BigQuery external tables |
| `qa.mapping_report` | ClickHouse queries (§6.3, `[XM §4.1]`) | `0 7 * * *` | — | `mapping_metrics`, `mapping_queue`, Slack digest |
| `ops.retention_probe` | OddsPapi CLV watermark; OpticOdds timeseries watermark | `0 5 * * 1` | trivial | SLO §6.4 |

---

## 3. Canonical model & mapping strategy (summary)

The full identity-resolution design is `docs/research/cross-provider-mapping.md` `[XM]`; this section states what is implemented, what the plan adopts from it, and the QA loops.

**Canonical records** `[CODE u3ingest/canonical/models.py][XM §3.1]`:
- `Quote(recv_ns, provider, book_id, provider_book, fixture_id, provider_fixture_id, market, period, selection, line, price_dec, price_us, is_main, active, limit_max, source_ts_ms, gateway_ts_ms, provider_market, provider_selection, provider_odd_id, player_id, team_id, event_kind, grouping_key, extra)`. Tradeable identity across providers = `(book_id, fixture_id, market, period, selection, line)` `[XM §1.8]`.
- `OrderBookLevel(recv_ns, provider, book_id, fixture_id, market, period, selection, venue_market_id, side back|lay|bid|ask, level, price, size, source_ts_ms, provider_odd_id)`.
- `FixtureRef` with `opticodds_id`, `opticodds_game_id`, `oddspapi_id`, `sharpsports_id`, `betradar_id`, `pinnacle_id`, `statsperform_id`, `sportradar_id`, `the_odds_api_id`, rotation numbers; the mapping doc adds `resolution_method` and `resolution_score` columns `[XM §3.3]`.
- Event kinds `snapshot | update | lock` (+ `heartbeat`, `freeze`, `history` from this plan) and the quote state machine (OpticOdds main-line promotion emits no lock; OddsPapi deactivation only via WS or `since`; SharpSports removal = key absent) `[XM §2.7]`.

**Market keys** `[CODE canonical/markets.py][XM §1.7]`: `moneyline | 3way | spread | total | team_total[:<metric>] | team_prop:<metric> | player:<metric> | other:<slug>`; periods `full | reg | 1h | 2h | 1q..4q | 1p..3p | 1i..9i | f3i | f5i | f7i | set1..set5 | ot`. OddsPapi is mapped from its frozen `marketType/period/handicap` catalogue (one `marketId` per line `[OP §3.13]`); OpticOdds from `market_id` slugs and `market_type_id` `[OO §3.2, App C]`; SharpSports from `Market.segment.id` / `metric.id` (never parse the name for segment/metric) `[SS §3.9]`. Verified metric crosswalk: SharpSports `Market.oddsjamId` equals the OpticOdds `market_id` slug wherever both exist (`player_passing_yards`, `player_home_runs`, `point_spread`) `[XM §1.7]`. `participantsRotated` flips home/away and spread sign for that book `[OP §3.4][CODE]`.

**Books** `[CODE mapping/registry.py][XM §1.6]`: canonical slug → per-provider aliases; regional/state clones and DFS payout variants map to the parent book with `book_xref.variant`; lay sides (`betfair_exchange_lay_`) and prediction-market spin-offs (`draftkings_predictions`, `underdog_predictions`, `fanatics_markets`) get their own ids; `polymarket_usa_` is folded into `polymarket` pending a price comparison; synthetic books (`opticodds_ai`) are `kind='model'` and excluded from arbitrage. The registry must be seeded from the three live catalogues (persisted under `bootstrap/registries`) rather than docs `[XM §5 #1–2]`.

**Fixtures** — resolution ladder `[XM §1.3.2]`:
1. OddsPapi `externalProviders.opticoddsId == OpticOdds fixture.id` — exact; MLB 40/40, EPL 8/8, NCAAF 114/125; 0 s start-time delta on every pair `[XJ]`. Coverage across all OddsPapi fixtures is 2,593 of 19,954 because OddsPapi lists far more (non-US) fixtures than OpticOdds prices; OddsPapi-only fixtures keep `oddspapi:<id>` ids forever `[XM §5 #16]`.
2. SharpSports `Event.oddsjamId == OpticOdds fixture.game_id` — exact; MLB 37/40, NFL 100/100 of the OpticOdds NFL sample `[XM headline]`. Fill is high for near-term MLB/NFL/WNBA/MLS events and zero for EPL and for late-season NFL rows (`upcoming=true&limit=50` returned the season's last 50 games) `[XM §1.3.3][SS §3.2]`.
3. Normalized team names + start time within ± 15 min in the same league, else team-pair only — EPL 8/8, NCAAF 73/87, MLB 3/40 `[XJ]`.
4. Rotation numbers as an unordered pair on the same day — US sports only; OpticOdds and OddsPapi use different schemes for EPL (810052/200081 vs 792/793) `[OO §6][XM §1.3.2]`. Not implemented.
5. Sportsbook-native ids (OddsPapi `pinnacleId`/`bookmakers.*.bookmakerFixtureId` vs SharpSports `Price.bookIds.eventId` vs OpticOdds `source_ids`/`deep_link` ids) — format-compatible candidates, unmeasured `[XM §1.3.2 step 5][OO §6]`.
6. Betradar (int) / Sportradar (UUID) / Stats Perform ids are different id spaces — reference columns only `[XM §1.3.2 step 6]`.

**Teams and players** `[XM §1.4–1.5]`: canonical team id = OpticOdds team id (league-scoped; `base_id` links across leagues); SharpSports `Team.oddsjamId == OpticOdds team id` NFL 32/32, MLB 30/30 (exact); OddsPapi `participantId` derived from id-joined fixtures (participants of a matched pair are the same two teams — no fuzzy names needed) `[XM §4.3]`. Canonical player id = OpticOdds player id; SharpSports via `Player.oddsjamId` (format-identical; coverage to be measured on full rosters); OddsPapi via `(sport, team_xref, normalized "Last, First")`. Today `quotes.player_id`/`team_id` carry provider-native ids, so cross-provider prop joins wait for `player_xref`/`team_xref` `[XM §5 #3]`.

**QA loops (Phase 1 deliverables, per `[XM §4]`):**
- `mapping_metrics` computed continuously: fixture resolution rate by provider/league, join-method mix, duplicate canonical ids, start-time consistency, book resolution, `other:` market share by volume (< 10 %), selection canonicalization (< 5 %), cross-provider key overlap and price agreement (same canonical key + book, two providers ≤ 5 s apart, `|Δprice_dec| > 0.02` → side/sign bug), freshness, stale-book minutes `[XM §4.1]`.
- `mapping_queue` rows for unresolved fixtures (with candidates by league, |Δstart| ≤ 6 h, token overlap ≥ 0.5), unknown books, unmapped markets/selections, unmatched teams/players; `status ∈ open|resolved|ignored`, `resolved_by` `[XM §4.2]`.
- Resolution procedures: nightly fixture re-run; catalogue-driven `book_xref` with variants; weekly `market_xref` load (OpticOdds `/markets` + `/market-types`, OddsPapi `/markets` × 6, SharpSports `/markets` paged) with auto-map by `oddsjamId` key → type table → name grammar; team/player xref derived from joined fixtures; every mapping change validated by `replay` over the affected day before promotion `[XM §4.3]`.
- `mapping/overrides.yaml` in the repo (book aliases, market aliases, forced fixture pairs) hot-reloaded; every override carries evidence and expiry. Contract tests on real samples (`tests/test_normalize.py`) extended with one golden fixture per league per provider.
- Alarms `[XM §4.4]`: `fixture_unresolved_ratio` > 10 % for a league where OpticOdds has odds; any `fixture_join_drift`; unknown quotes for an entitled book; `market_other_share` > 10 % or a new `other:` key above 1 %; cross-provider price disagreement > 1 % of comparable pairs; `quote_age_p99_ms` > 5,000 pregame / 2,000 live for streamed books; any streamed book stale > `staleThresholdSec`; catalogue drift.
- Fee-basis sanity: OpticOdds Polymarket/Kalshi prices with `exclude_fees=true` must equal `order_book[0][0]` `[OO §8.1]`; drift flags a parameter regression.

---

## 4. Ingestion services spec (per connector)

Legend: ✅ implemented (Phase 0 / merged PRs), 🔶 partially, ⬜ planned (Phase 1 unless noted).

### 4.1 OddsPapi WebSocket (`u3-op-ws`)

| Aspect | Spec |
|---|---|
| Protocol | `wss://v5.oddspapi.io/ws`; first frame `login` within 10 s; login-only subscriptions (any filter change = new connection); max 5 concurrent connections; control frames JSON text, data frames per negotiated `receiveType` `[OP §4.1–4.2]` ✅ client `[CODE providers/oddspapi/ws.py]` |
| Subscription plan | §2.3 table. 🔶 today: one connection, `odds,bookmakers,fixtures`, `json`, and a bookmaker list containing unentitled slugs `[CODE pipeline.run_oddspapi_ws][XM §5 #1]` → ⬜ split into three connections, default `zstd-dict` (the `dict` frame handling exists ✅), corrected slugs |
| Resume/replay | persist `serverEpoch` + `lastSeenId[channel]` to SQLite every 250 ms; on reconnect send cursors only for channels in `login_ok.resume.replayChannels` and only if `now − ts(entryId) < resumeWindowMs − 5 s` (60 s window observed; contiguous replay then `resume_complete` in ~8 s) `[OP §4.6]`; `odds` may not be replayable → treat every odds reconnect as `snapshot_required` ✅ cursor tracking in memory; ⬜ persistence + age rule |
| `snapshot_required` / `reconnect` | non-fatal; keep consuming, buffer, run REST `/fixtures/odds/main?fixtureIds≤50` for in-window fixtures, apply baseline, drain buffered updates with `changedAt ≥ snapshot_ts` `[OP §4.5–4.6, §10.6]`; on `reconnect` open the spare slot first ✅ detection/logging; ⬜ automatic REST snapshot |
| Backfill | fixture spine 400 d back in 7-day windows (≈ 372 calls); settlement for all finished fixtures (≥ 1 y); CLV for fixtures ≤ 220 d; Pinnacle tick history always, other books via `oddsIds` for main lines `[OP §10.4]` ⬜ `u3-ingest backfill oddspapi --phase spine|settlement|clv|ticks` |
| Raw archival | every frame (decoded JSON + `recv_ns`, `channel`, `ts`, `entryId`, `raw_len`, control frames without `apiKey`) → `raw/oddspapi/ws-odds/…` ✅ `[CODE sinks/raw.py][XM §3.2]`; ⬜ zstd codec, per-connection stream names |
| Normalization | `OddsPapiNormalizer.quotes` joins `outcomeId → marketId → handicap`, resolves `participantsRotated`, emits ladders from `meta.back/lay` ✅; ⬜ apply `staleOdds`/`suspended`/`hasOdds` gates as `active=false`/`lock` transitions `[XM §5 #11]`; ⬜ `betfair-ex` `availableToBack/availableToLay` and `sx.bet` shapes (`limit = size × cents`) `[XM §5 #10]`; ⬜ live period keys `result|fulltime|p1..pN` via `sportId` + `expectedPeriods`/`periodLength` `[XM §5 #5]`; ⬜ `limit` currency via `limitCurrency` + `/currencies` |
| Sinks | raw → GCS; coalesced `u3.quotes`, `u3.order_book_levels`; `u3.book_status` from `bookmakers`; `u3.results` from conn #3 ⬜ |
| Observability | per connection: msgs/s, bytes/s, decode p50/p99, `recv − ts` p50/p99 (108 ms observed `[OP §7.1]`), `entryId` gap count, reconnects, close codes, `snapshot_required` count, per-book `staleOdds` minutes; assert `login_ok` echo (channels, bookmakers, `access`, `resume`) equals the request and alert on drift `[OP §10.2, §10.7]` 🔶 counters in `ws.stats` → ⬜ Prometheus |
| Failure modes | 4000 client bug (fail fast), 4001 key revoked (stop, page), 4002 backpressure (switch to zstd-dict, narrow filters, move parse off socket task), 4003 too many connections (serialize connects with jitter), 1006/1011 reconnect with 1/2/5/10 s jittered backoff, 1009 raise `max_size` (16 MiB set) `[OP §4.9, §10.6]` ✅ backoff/close-code handling; ⬜ paging |

### 4.2 OddsPapi REST (`u3-batch`)

| Aspect | Spec |
|---|---|
| Protocol | `https://v5.oddspapi.io/en`, `?apiKey=` (key in URL → redact everywhere; never persist raw URLs) `[OP §1.2, §9.3]`; browser-like UA required ✅ `[CODE providers/oddspapi/rest.py]`; no pagination, bodies up to 95.6 MB → stream-parse history endpoints ⬜ (`ijson`) |
| Poll plan | §2.4 rows `op.*`. Odds bucket (10/s, shared by `/fixtures/odds`, `/fixtures/odds/main`): sweep ≈ 2 req/s (`since` also returns inactive odds → correct removals), deep snapshot on `snapshot_required`/divergence, pre-kick freeze `[OP §10.3]` ✅ limiters; 🔶 bootstrap only → ⬜ scheduler |
| Resume/replay | idempotent jobs keyed by `(endpoint, params, window)`; `since` cursor per sweep persisted in SQLite ⬜ |
| Backfill | see §4.1; settlement first (cheapest, deepest ground truth) `[OP §10.4]` ⬜ |
| Raw archival | every body with redacted URL, status, `x-ratelimit-*`, `cf-ray`, latency, size → `raw/oddspapi/rest-<endpoint>/…` ✅ (bootstrap) / ⬜ (all jobs) `[XM §3.2]` |
| Normalization | same normalizer with `kind='snapshot'`; CLV → `u3.clv`; settlement → `u3.settlements` as transition history with canonical `result` + `provider_result` `[XM §3.3]` ⬜ |
| Sinks | ClickHouse + BQ marts (daily Parquet export) ⬜ |
| Observability | per job: calls, 429s, `Retry-After` honoured, body bytes, latency (settlement 4–9 s), divergence rate of sweep vs stream (< 0.1 % target) `[OP §10.7]` ⬜ |
| Failure modes | 429 → honour `Retry-After`, halve concurrency for a window; 503 `rate_limiter_error` → back off 5 s ×3 then degrade to WS-only; 403 `channel_not_allowed`/`bookmaker_not_allowed`/`sport_not_allowed` → entitlement change: disable job, page; 400 `invalid_filters` → programming error, fail loudly; silent `[]` on entitled in-season sport → alarm `[OP §10.6]` ✅ retry/limiter; ⬜ classification + paging |

### 4.3 OpticOdds SSE (`u3-oo-sse`)

| Aspect | Spec |
|---|---|
| Protocol | plain HTTP GET, `Accept: text/event-stream`, no compression observed; every event carries `retry: 5000`; `ping` every 5 s on every stream (server wall clock; > 15 s silence = dead) `[OO §4.1, §4.7]`; `GET /stream/odds/{sport}` events `odds`, `locked-odds` (last price included), `fixture-status` (with `include_fixture_updates=true`; `data` is an object), `connected`, `ping` `[OO §4.2]`; 27-key odd record incl. `fixture_id`, `game_id`, `sportsbook_id`, `is_live`; `limits`, `order_book`, `source_ids` emitted by default for exchanges `[OO §3.6]` ✅ client `[CODE providers/opticodds/sse.py]` |
| Subscription plan | §2.3 (5 sports × 4 bundles + results per league + PM politics/crypto ≈ 31 connections), `is_main` unset and tracked locally (main-line promotion with alternates emits **no** lock `[OO §4.2]`). 🔶 today: one 5-book connection per sport, no `league=`, American fee-adjusted prices → ⬜ bundles, league filter, `odds_format=DECIMAL&exclude_fees=true` |
| Resume/replay | **`last_entry_id` replay does not work** (5 tests; bogus/old ids accepted; stream restarts at "now") and the soccer stream produced duplicate and out-of-order ids `[OO §4.6]` → dedupe on `entry_id` and odd `id`+`timestamp`; on every reconnect emit a `ReconnectMarker` ✅ and ⬜ hydrate all fixtures of the bundle via `/fixtures/odds?fixture_id×5&sportsbook×5`, reconcile (present in REST but locked locally → unlock; in local state but absent in REST → suspended), emit a `reconnect_gap` marker `[OO §10.3]` |
| Backfill | `/fixtures/odds/historical?fixture_id&sportsbook×5&market=…&include_timeseries=true` (change-level `entries`, int-second timestamps, retained 57–60 d, pre-match only; `olv`/`clv` ≥ 1 y) for traded leagues; ≤ 50/15 s `[OO §5.1, §5.2]` ⬜ |
| Raw archival | every event incl. `ping` (clock offset ≈ +0.7 s local−server `[OO §3.13]`) and reconnect markers → `raw/opticodds/sse-odds-{sport}-{bundle}/…` ✅ (per sport) / ⬜ (per bundle) |
| Normalization | `OpticOddsNormalizer.quotes_from_sse` (`locked-odds` → `event_kind='lock'`, `active=False`), `order_book` → levels, `source_ids.market_id` as `venue_market_id` ✅; ⬜ `selection_line` `yes|no|odd|even|exact|"3:1"` folded into `selection` `[XM §5 #4]`; ⬜ soccer `moneyline` with a `Draw` selection → `3way` `[XM §5 #6]`; ⬜ `_incl_ot_` / `(Incl. OT)` → `full` vs `reg` `[XM §5 #7]`; ⬜ resolve books on `sportsbook_id` and alias display names (`"Polymarket (USA)"`) `[XM §5 #2]`; ⬜ `fixture-status` → `fixtures.status`; ⬜ accept `limits.max` and `limits.max_stake` `[OO §9.1 #12]` |
| Sinks | raw; coalesced ClickHouse; PM snapshots → `order_book_levels` (bid/ask) + `pm_books` ⬜ |
| Observability | events/s per connection vs baseline, `recv − timestamp` p50/p99 (7 ms baseball / 32 ms soccer; p99 0.2–0.33 s `[OO §7.2]`), reconnects, dup/out-of-order ids, `locked-odds` rate per book, ping gap, "200 but empty" detection `[OO §10.5]` ⬜ |
| Failure modes | idle > 15 s → reconnect with backoff 1 → 60 s ✅ (20 s idle today); HTTP 429 → stop new connects ≥ 15 s `[OO §1.4]`; ≥ 5 reconnects/min on one stream → alert; stream with 0 events for 10 min during a live slate → alert; results stream stale `unplayed` events filtered by `status`/`start_date` `[OO §4.3]`; PM invalid category → 400 with the valid list `[OO §1.6]` |

### 4.4 OpticOdds REST (`u3-batch`)

| Aspect | Spec |
|---|---|
| Protocol | `X-Api-Key` header (never `?key=` — it leaks into logs `[OO §1.2]`); standard 8,000/15 s observed (docs 2,500), historical 50/15 s (docs 10), fixed 15 s wall-clock windows, 429 shape untested; ≤ 5 `sportsbook`, ≤ 5 `fixture_id`, no league-wide `/fixtures/odds` `[OO §1.4]`; limiters keep the documented figures with headroom `[CODE providers/opticodds/rest.py]` ✅; pagination `{cursor,data,has_more,page}` with page size 100 `[OO §1.5]` ✅ |
| Poll plan | §2.4 rows `oo.*`; `/fixtures/odds` is for hydration and consistency only, never the price source `[OO §10.1]` 🔶 |
| Resume/replay | idempotent; `updated_since` returned 0 rows — do not rely on it `[OO §9.3]` |
| Raw archival | all bodies ✅/⬜; **`/fixtures/results/queue/status` echoes the raw API key in `queue_name`** — never archive unredacted `[OO §1.1]` |
| Normalization | `quotes_from_fixture_rows` ✅ (request `odds_format=DECIMAL` so `order_book_levels.price` is decimal `[XM §5 #9]`); grader/results → `u3.settlements` (provider `opticodds`), `market_stats` → `u3.results` ⬜; injuries diffs keyed by `injury.id` ⬜; parlay pricer body fixed to `{sportsbooks, entries[{fixture_id, market, name}]}` ✅ `[CODE rest.py][OO §9.1 #26]` |
| Failure modes | 400 validation bodies (`maximum 5 sportsbooks allowed`, `you must provide at least one of fixture_id, player_id, or team_id`) are programming errors `[OO §1.6]`; unknown sportsbook ids are silently ignored → validate against `/sportsbooks` at bootstrap `[OO §9.1 #22]` ⬜; sleep to `x-ratelimit-reset` when `remaining < 50` `[OO §10.5]` ⬜ |

### 4.5 SharpSports REST (`u3-ss-poll` + `u3-batch`)

| Aspect | Spec |
|---|---|
| Protocol | `https://api.sharpsports.io/v1`, `Authorization: Token <private key>` for `/events`, `/prices`, historic, betSync (Bearer → 401); 50 rps general, 20 rps large-list; 429 `{"detail":"Request was throttled."}`; no rate-limit headers `[SS §1.2–1.4]` ✅ `[CODE providers/sharpsports/rest.py]` |
| Poll plan | loops L0–L6 (§2.3). 🔶 today: `/prices?league=` for every universe league every 30 s (17.5 MB, 2–7 s `[SS §1.7]`) → ⬜ per-event L3 (1.67 MB / 0.28 s), DFS and Pinnacle league polls, 5-min catch-all; never `/marketSelections?league=` (20–32 s) `[SS §10.1]` |
| Resume/replay | stateless snapshots; high-water marks per loop (`last_recv_ts` per event, `pageNum` per event, `timePlacedStart`) `[SS §10.5]` |
| Backfill | events monthly slices from 2024-08 (prices are empty before) `[SS §5.2, §10.3]`; selections `historic=true`; `summary?eventId` pages then `timeseries?rollup=15m` for straights/headline props; player logs for rostered players (NBA ~600, NFL ~2,000, MLB ~1,000 calls, ≤ 5 concurrent) ⬜ |
| Raw archival | ✅ `raw/sharpsports/prices-poll/…`; ⬜ per-loop streams with request URL and `date` header `[SS §10.4]` |
| Normalization | `SharpSportsNormalizer.quotes` (American → decimal, `main`, `live`, `impliedProbability`, `market_selection_id`) ✅; ⬜ moneyline/3-way `line 0.0 → NULL` `[XM §5 #23]`; ⬜ keep `bookIds` (Kalshi ticker parts, Polymarket market id, PrizePicks projection id), `betPlaceLinks`, `ev`, `marketOfferVolume/marketSelectionVolume` in `extra` `[SS §3.6, §10.4]`; ⬜ historic windows → `line_window` rows (open/close only, no OHLC `[SS §3.10]`); player logs → BQ; injuries `status` bare designation, `played` `[SS §3.13]` |
| Observability | bytes and latency per call (binding constraint), events per league vs OpticOdds (join coverage), 429 count, Price key-set drift (10 keys) `[SS §10.5]` ⬜ |
| Failure modes | 403 "private API key is required" → key mix-up; bare-string 400 and HTML 404 bodies → branch on `content-type` `[SS §1.6]`; league filters case-sensitive on `/markets`, `/teams`, `/players` (use `LGUE_*`) `[SS §2.2]`; `/events` default order descending → `ascending=true` `[SS §2.3]`; `[]` off-slate is normal; alert only if a known live event returns `markets: []` before `startTime + 4 h` `[SS §10.5]` |

### 4.6 Sinks

| Sink | Spec |
|---|---|
| Raw archive | `RawArchive` per (provider, stream); `{"recv_ns","provider","stream","seq","meta","body"}` lines; hourly files; flush 2 s / 5,000 records ✅ `[CODE sinks/raw.py]`. ⬜ zstd, fsync on hour roll, `manifest.json` per hour as the archive commit `[R1-gpt §5.3]` |
| GCS sync | `GcsArchiveSync.sync_once`: skips the current hour, uploads closed files, verifies size + crc32c, appends `.gcs_manifest.jsonl`, optional delete-after-upload; CLI `u3-ingest archive-sync --every 300` ✅ `[CODE sinks/gcs.py]`. ⬜ stream the crc32c instead of `read_bytes()`; alert if the newest object per stream is > 2 h old |
| ClickHouse | `ClickHouseSink` batched inserts (`async_insert=1`, `wait_for_async_insert=0`) ✅ `[CODE sinks/clickhouse.py]`; ⬜ native TLS 9440 with LZ4, `insert_deduplication_token = sha1(provider, stream, hour, seq_range)` so replays are idempotent `[R1-gpt §2.4]`; ⬜ coalescer in front; ⬜ TTLs (§1.7); ⬜ `provider` in the `quotes_latest` key `[XM §5 #8]` |
| Replay → Parquet/DuckDB | `u3-ingest replay --root --since --until --out --out-format parquet|duckdb` merges files by `recv_ns`, re-registers bootstrap registries, re-normalizes ✅ `[CODE replay.py]`. ⬜ nightly job to `gs://u3-parquet`; ⬜ Arrow batch inserts instead of `executemany` for DuckDB |
| BigQuery | external tables over Parquet; marts by scheduled queries ⬜ |
| Board / Redis (Phase 2) | in-process `Board.ingest` ✅ `[CODE pricing/board.py]`; Redis Streams `quotes:<sport>` for detectors ⬜ |

### 4.7 Operations, secrets, deployment

- Secrets in a `.env` on the VM with mode 600, loaded by `pydantic-settings` (whitespace-stripped) `[CODE config.py]`; long-term: Secret Manager + startup fetch. Keys never logged (`OddsPapiWS` already strips `apiKey` from `login_ok` logs `[CODE cli.py]`); add a structlog processor that redacts `apiKey=`, `key=`, `Authorization` and `queue_name` patterns everywhere; SharpSports public key for L0 reference pulls so private-key traffic is separable `[SS §10.5]`.
- systemd units per §1.6 with `Restart=always`, `RestartSec=2`, `MemoryMax` per consumer; watchdog via `sd_notify` tied to "last message age".
- CI: ruff + pytest already scaffolded; replace the placeholder workflow with `pip install -e .[dev,clickhouse,research] && pytest` and the replay benchmark (§1.5).
- Deployment: `deploy/vm.sh` (create VM, disk, static IP, firewall egress-only, IAP), `deploy/units/*.service`, `deploy/oo_streams.yaml`, `deploy/ss_poll.yaml`, `deploy/batch.yaml`, `deploy/env.example`. Redeploy = `git pull && pip install -e . && systemctl restart 'u3-*'`.

### 4.8 Planned ClickHouse DDL (Phase 1; names per `[XM §3.3]`)

```sql
-- per-(fixture, book) health from OddsPapi `bookmakers` channel + /bookmakers, OpticOdds last-polled
CREATE TABLE IF NOT EXISTS u3.book_status (
    recv_ns UInt64, recv_ts DateTime64(3) MATERIALIZED toDateTime64(recv_ns / 1e9, 3),
    provider LowCardinality(String), book_id LowCardinality(String), fixture_id Nullable(String),
    has_odds Nullable(Bool), stale_odds Nullable(Bool), suspended Nullable(Bool), participants_rotated Nullable(Bool),
    bookmaker_fixture_id Nullable(String), last_odds_at_ms Nullable(Int64), stale_odds_since_ms Nullable(Int64),
    polled_at_ms Nullable(Int64), updated_at_ms Nullable(Int64)
) ENGINE = MergeTree PARTITION BY toDate(recv_ts) ORDER BY (provider, book_id, recv_ns)
TTL toDate(recv_ts) + INTERVAL 90 DAY;

-- settlement/grading as a transition history (never overwrite; latest = argMax(recv_ns))
CREATE TABLE IF NOT EXISTS u3.settlements (
    recv_ns UInt64, fixture_id String, market LowCardinality(String), period LowCardinality(String), selection String,
    line_key String, line Nullable(Float64), provider LowCardinality(String),
    result LowCardinality(String),           -- canonical win|lose|push|half_win|half_lose|void|pending
    provider_result String,                  -- OP WIN..UNDECIDED · OO Won..Pending
    margin Nullable(Float64), home_score Nullable(Float32), away_score Nullable(Float32), periods Array(String),
    reason Nullable(String), oddspapi_market_id Nullable(Int64), oddspapi_outcome_id Nullable(Int64),
    oddspapi_player_id Nullable(Int64), dead_heat_reduction Nullable(Float32)
) ENGINE = MergeTree PARTITION BY toYYYYMM(toDateTime(recv_ns / 1e9))
ORDER BY (fixture_id, market, period, selection, line_key, provider, recv_ns);

-- opening/closing lines from every source plus our own freeze snapshots
CREATE TABLE IF NOT EXISTS u3.clv (
    recv_ns UInt64, source LowCardinality(String),   -- oddspapi_clv | opticodds_hist | sharpsports_window | freeze_t60 | freeze_t5
    fixture_id String, book_id LowCardinality(String), market LowCardinality(String), period LowCardinality(String),
    selection String, line_key String, line Nullable(Float64),
    olv_price_dec Nullable(Float64), olv_ts_ms Nullable(Int64), olv_line Nullable(Float64),
    clv_price_dec Nullable(Float64), clv_ts_ms Nullable(Int64), clv_line Nullable(Float64),
    clv_active Nullable(Bool), clv_is_null Bool, provider_odd_id String
) ENGINE = ReplacingMergeTree(recv_ns)
ORDER BY (fixture_id, book_id, market, period, selection, line_key, source);

CREATE TABLE IF NOT EXISTS u3.results (
    recv_ns UInt64, fixture_id String, provider LowCardinality(String), status LowCardinality(String),
    home_total Nullable(Float32), away_total Nullable(Float32),
    periods String CODEC(ZSTD(3)),           -- JSON: OO result.scores.*.periods / OP scores map
    in_play String CODEC(ZSTD(3)),           -- JSON: OO in_play_data / OP clock
    market_stats String CODEC(ZSTD(3)),      -- JSON: OO market_stats
    source_ts_ms Nullable(Int64)
) ENGINE = MergeTree PARTITION BY toDate(toDateTime(recv_ns / 1e9)) ORDER BY (fixture_id, provider, recv_ns)
TTL toDate(toDateTime(recv_ns / 1e9)) + INTERVAL 90 DAY;

CREATE TABLE IF NOT EXISTS u3.injuries (
    recv_ns UInt64, provider LowCardinality(String), sport LowCardinality(String), league LowCardinality(String),
    player_id String, team_id Nullable(String), status String, designation Nullable(String), description Nullable(String),
    fixture_id Nullable(String), played Nullable(Bool), change LowCardinality(String), source_ts_ms Nullable(Int64)
) ENGINE = MergeTree ORDER BY (sport, league, player_id, recv_ns);

-- non-sport prediction-market top-of-book summary (levels themselves go to order_book_levels)
CREATE TABLE IF NOT EXISTS u3.pm_books (
    recv_ns UInt64, platform LowCardinality(String), market_id String, canonical_id String, category LowCardinality(String),
    yes_bid Nullable(Float64), yes_ask Nullable(Float64), no_bid Nullable(Float64), no_ask Nullable(Float64),
    last_trade Nullable(Float64), depth_yes_bid Float64, depth_yes_ask Float64, source_ts_ns Nullable(Int64)
) ENGINE = MergeTree PARTITION BY toDate(toDateTime(recv_ns / 1e9)) ORDER BY (platform, market_id, recv_ns)
TTL toDate(toDateTime(recv_ns / 1e9)) + INTERVAL 14 DAY;

CREATE TABLE IF NOT EXISTS u3.stream_health (
    minute DateTime, provider LowCardinality(String), stream LowCardinality(String), conn_id String,
    msgs UInt32, bytes UInt64, coalesced UInt32, reconnects UInt16, gaps UInt16, dups UInt16,
    lat_recv_minus_src_p50_ms Float32, lat_recv_minus_src_p99_ms Float32, decode_p99_ms Float32
) ENGINE = MergeTree ORDER BY (provider, stream, minute) TTL minute + INTERVAL 90 DAY;

CREATE TABLE IF NOT EXISTS u3.mapping_queue (
    first_seen_ns UInt64, updated_ns UInt64, kind LowCardinality(String),   -- fixture|book|market|selection|team|player
    provider LowCardinality(String), provider_id String, league LowCardinality(String), home Nullable(String), away Nullable(String),
    start_time_ms Nullable(Int64), candidates String CODEC(ZSTD(3)), volume UInt32,
    status LowCardinality(String), resolved_to Nullable(String), resolved_by Nullable(String)
) ENGINE = ReplacingMergeTree(updated_ns) ORDER BY (kind, provider, provider_id);

-- Phase 2
CREATE TABLE IF NOT EXISTS u3.signals (
    signal_id UUID, ts_ns UInt64, edge LowCardinality(String), fixture_id String, market LowCardinality(String), period LowCardinality(String),
    selection String, line_key String, book_id LowCardinality(String), price_dec Float64, fair_p Float64, method LowCardinality(String),
    ev Float64, fee_est Float64, settlement_mismatch_score Float32, quote_age_ms UInt32, constituents String CODEC(ZSTD(3))
) ENGINE = MergeTree PARTITION BY toDate(toDateTime(ts_ns / 1e9)) ORDER BY (edge, fixture_id, ts_ns);
```
Dimension and xref tables (`sports`, `leagues`, `fixtures`, `teams`, `team_xref`, `players`, `player_xref`, `books`, `book_xref`, `markets`, `market_xref`) are taken verbatim from `[XM §3.3]`; `quotes_latest` gains `provider` in its key `[XM §3.4]`.

### 4.9 Reference numbers for capacity planning

| Quantity | Value | Source |
|---|---|---|
| OpticOdds SSE, baseball, 5 books | 15.8 events/s = 223 records/s; 81 % Polymarket; 49 % `is_live` | `[OO §4.2]` |
| OpticOdds SSE, soccer, 5 books, all leagues | 313 events/s = 1,544 records/s; 67.8 MB / 45 s; main lines + 3 markets: 73 records/s | `[OO §4.2]` |
| OpticOdds PM stream | politics 933 snapshots/s (120 MB / 45 s); crypto 514/s; Kalshi-only politics 134/s | `[OO §4.5]` |
| OpticOdds SSE delivery latency | p50 7 ms (baseball) / 32 ms (soccer); p99 221 / 333 ms; connect 0.33 s + 1.0 s to first data | `[OO §7.2]` |
| OpticOdds REST `/fixtures/odds` | 3 fixtures × 5 books = 4.99 MB; DK 811–1,401 odds/fixture; 0.15–0.47 s | `[OO §2.4, §7.2]` |
| OpticOdds historical bucket | 50 / 15 s ≈ 3.3 fixture-market pulls/s; one fixture × DK all markets 1.86 MB | `[OO §5.2]` |
| OddsPapi WS, unfiltered sports 10/11/13 | ≈ 500 msg/s (87 % Polymarket); 27 msg/s with sharp/US filter; ~0.5–1 msg/s per live EPL fixture | `[OP §4.10]` |
| OddsPapi WS frame size | json 2,412 B avg; zstd 679 B; zstd-dict 444 B; msgpack 2,657 B | `[OP §4.8]` |
| OddsPapi WS latency | `recv − changedAt` p50 79 ms (p90 138); `recv − bookmakerChangedAt` p50 142 ms; book→gateway ≈ 359 ms (Pinnacle) | `[OP §7.1]` |
| OddsPapi tick history | Pinnacle 25k ticks / 6 MB per MLB game; DK 433k / 95.6 MB | `[OP §5.2]` |
| SharpSports `/prices` | league 17.5 MB / 2–7 s (29,854 prices); event 1.67 MB / 0.28 s (2,888 prices); DFS 3.78 MB / 5.3 s | `[SS §1.7]` |
| SharpSports historic | summary by event 1–4 s per page of 100; player/team-scoped 55–98 s or timeout | `[SS §1.7]` |
| Prototype throughput (sandbox) | 381,188 quotes + 1,311,005 levels + 105,128 raw msgs in 75 s; 52 MB gz | `[CODE README]` |

### 4.10 Runbooks (Phase 1 deliverable, `docs/runbooks/`)

1. **Reconnect storm** (alert: > 5 reconnects/min on any stream): check vendor status pages (`status.opticodds.com`, `oddspapi-v5.instatus.com`); verify egress; if OddsPapi 4002, switch remaining json connections to zstd-dict and narrow `sportIds`; if OpticOdds 429, pause new connects 15 s and stagger reconnects with 2 s jitter `[OO §1.4, §4.7]`.
2. **Entitlement change** (alert: 403 on a previously-working endpoint or `login_ok` echo drift): freeze the affected job, capture the body, open a vendor ticket with `cf-ray`/`connId` `[OP §1.4, §4.3]`; do not retry in a loop.
3. **ClickHouse unavailable**: consumers keep archiving (raw is primary); coalescer buffers up to 5 min then drops to `stream_health` counters; after recovery run `u3-ingest replay --since <gap>` into ClickHouse with dedup tokens.
4. **GCS sync backlog** (alert: newest object > 2 h): check `.gcs_manifest.jsonl` failures, ADC credentials, disk space; local spool holds 48 h.
5. **Key rotation**: create new key in the vendor console; write `*_API_KEY_NEXT` to `.env`; `systemctl reload` — connectors try NEXT on 401; revoke old key after 24 h; before uploading the day's raw files, `grep` for the old key (`queue_name`, URLs) and redact.
6. **Volume spike** (alert: GCS growth > 15 GB/day or ClickHouse inserts > 5k rows/s): apply §1.3 kill-switches in order.
7. **Poller death** (alert: OpticOdds `last-polled` age for a universe book > 2× its typical gap, or OddsPapi `staleOdds` > `staleThresholdSec`): mark the book non-tradeable in the board, keep archiving, notify the vendor if > 30 min `[OO §8.3][OP §7.2]`.

---

## 5. Edge inventory (prioritized)

Sizing uses underwriting ranges from the briefs (they disagree by up to an order of magnitude; the ranges below are the intersection we consider credible, before taxes and account attrition) and our own data facts. "Latency budget" = quote-in to decision-out inside our process; vendor latency (≈ 0.1–0.5 s) sits on top.

| # | Edge | Mechanism | Data needs (our feeds) | Latency budget | Expected net edge / capacity | Main risks | What ingestion must provide |
|---|---|---|---|---|---|---|---|
| 1 | **Sportsbook ↔ Kalshi/Polymarket arbitrage (pregame)** | Buy YES at PM price c + fee f, back the complement at a book at decimal d; strict arb iff `c + f + 1/d < 1` `[R2-gpt §2.1]`; fire the slow (sportsbook) leg first `[R2-opus §2.2]` | PM depth + `source_ids` (matrix #5), same-`outcomeId` PM quotes from OddsPapi with USD notional per rung `[OP §8.8]`, sportsbook quotes + limits (#2, #8), fee schedules, contract rule text; SharpSports `bookIds` give the Kalshi ticker / Polymarket market id as a third confirmation `[SS §6]` | seconds pregame; < 500 ms for the PM leg once automated | 0.25–2 % on genuinely equivalent contracts `[R2-gpt]`; 1.5–4 % gross per gemini/opus — haircut for settlement jump risk; capacity bounded by book depth (hundreds of contracts at a price `[R2-opus §2.2]`) | Settlement-rule mismatch (NFL abandoned < 55 min settles at last price on Kalshi; ties push at books; Polymarket UMA disputes) `[R2-opus §2.2]`; partial fills; capital lock-up | exact contract mapping (canonical key + `venue_market_id`), raw prices (`exclude_fees`), depth timeline, settlement outcomes from both sides (#11) to measure realized basis |
| 2 | **Prediction-market market making (Kalshi, Polymarket, Novig)** | Quote around a reservation price `r = p_fair − λ·I` with fee/rebate-adjusted bid/ask `[R2-gpt §3.1]`; Avellaneda-Stoikov with binary terminal collapse `[R2-gem §3.2]` | Pinnacle-anchored fair value (edge #4) at ≤ 500 ms age, PM full depth and trades, own fills, fee tiers, resolution metadata | 10–50 ms internal; cancel path is the critical latency | 0.5–3 % per filled unit; the most scalable family (Kalshi $1.2 B/day record in June 2026 `[R2-opus §0]`) | Adverse selection (filled only when the reference moved), inventory concentration, resolution risk, venue/legal availability by state `[R2-opus §0]` | continuous Pinnacle/consensus stream with staleness flags (`staleOdds`, `maxDelay*`, `last-polled`), PM book snapshots with sequence, our order/fill ledger (Phase 3) |
| 3 | **Slow-book latency arb using per-book observed delays** | Reference moves at Pinnacle/exchanges; hit the stale quote at a copier book before it reprices; retail books reportedly lag leaders by 0.8–4.5 s `[R2-gem §2.2]` (unverified — measure) | per-book lag distribution from `bookmakerChangedAt`/`changedAt`/`recv_ns` `[OP §7.1]`, OpticOdds `timestamp` + `/sportsbooks/last-polled` cadence `[OO §7.3]`, `locked-odds`, leader-follower model per market/time-to-start `[R2-gpt §1.1]` | < 100 ms internal; end-to-end 1–5 s window | 2.5–6 % per unit `[R2-gem]`, capacity near zero at retail books after limiting; pre-game steam-following is the durable subset | Account limitation is the true cost of capital `[R2-opus §2.1]`; rejected/repriced quotes have zero capacity `[R2-gpt §5.2]`; ToS on automated placement | tick ledger with three clocks, per-book acceptance telemetry (Phase 3), `u3.book_lag` view (§6.2) |
| 4 | **Pinnacle-anchored fair value → +EV on soft books and PMs** | Devig (multiplicative for tight two-ways, power/Shin for lopsided/multiway) `[R2-gpt §1.2]`, uncertainty-weighted logit consensus with copy-cluster penalties `[R2-gpt §1.3]`, then EV = p·d − 1 after fees | Pinnacle + Circa + BetOnline/Bookmaker + exchanges (#8, #2), limits as liquidity weights, freshness | seconds–minutes pregame | 1–3 % CLV on primary markets for professionals `[R2-opus §2.7]`; capacity limited by books | Fake steam/head-fakes `[R2-opus §1.4]`; devig-method dispersion (20–40 bp is noise) `[R2-gpt §1.2]`; Pinnacle coverage starts close to game time `[OO §8.2]` | `Board` + `fair_value` `[CODE pricing/]` fed by uncoalesced quotes; per-book weights table; stored constituents per fair value (provenance, as Copilot does `[OO §8.2 #8]`) |
| 5 | **Player props vs DFS pick'em (PrizePicks / Underdog at fixed +100)** | Pick'em legs are hidden-price parlays: PrizePicks flat leg ≈ −119 (54.34 % BE), Underdog 4-flex ≈ −107 (51.69 %), 2-pick power 3× ≈ 57.7 % `[R2-opus §2.5]`; compare devigged prop probability at the pick'em line; positive correlation across legs is unpriced by the apps | OpticOdds DFS payout-structure ids + SharpSports `pp`/`ud` lines (#16), alt-line ladders (up to 19 rungs per book on one selection `[SS §3.6]`; OpticOdds alternates) to fit distributions, injuries/lineups (#14), player logs/DVP/`consensusProjection` (#15) | minutes pregame; seconds around lineup news | 1–8 % per entry, very low capacity `[R2-gpt]`; tier-2 sports softer `[R2-opus §2.5]` | Payout-table changes, demotion to Flex after ~55 % win rate over 200+ entries, DNP void rules `[R2-opus §2.5]` | canonical `player:<metric>` keys across all three vendors + `player_xref` (SharpSports `Player.oddsjamId` ↔ OpticOdds id `[XM §1.5]`), line ladders stored with `is_main` |
| 6 | **CLV capture (process metric, not an edge)** | `CLV_EV = d_bet · p_close − 1` against a devigged close; like-for-like lines `[R2-gpt §5.1]` | our freeze snapshots (T−60 s/T−5 s), OddsPapi `clv`/`olv`, OpticOdds `olv`/`clv`, SharpSports window `close` at `timeseriesEnd=startTime` (#12) `[SS §5.3]` | none | sustained +1–3 % CLV over 1,000+ bets = evidence of edge `[R2-opus §2.7]` | wrong benchmark, self-impact on close, props without sharp close, exchange `olv` junk `[OO §8.4]` | `u3.clv` with sources side by side; `event_kind='freeze'` rows |
| 7 | **Middles / scalps** | Hold both sides across key numbers; +EV iff P(middle) × payout > carry `[R2-gpt §2.4]` | alt-line ladders per book, margin distributions from settlement history (#11, #13) | minutes–days | modest, variance-heavy, limit-bound | push-probability error | full alt-line capture (already: `is_main=false` rows) |
| 8 | **Correlated parlay / SGP mispricing** | Compare book SGP prices (DK +242 vs independent +282 on the same two MLB legs) with a joint model; OpticOdds AI SGP pricer as a reference `[OO §8.2 #9][R2-opus §2.6]` | `/parlay/odds` per book, prop ladders, results for joint calibration | seconds–minutes | several % when the model is right; narrow, high-attrition | books limit correlated-SGP winners | on-demand parlay pricing archived; joint-outcome results (`player-results`, `market_stats`) |
| 9 | **Promo / boost harvesting** | EV of boosts/promos after rollover on one legitimate account; run as a separate P&L with account cost amortized `[R2-opus §2.6]` | promo terms (manual), fair value (#4) | low | high ROI on promo capital, tiny capacity, self-terminating | terms changes, limiting | none beyond fair value; manual workflow |
| 10 | **Steam / line-origin detection** (research product feeding #3 and #4) | Leader–follower regression `Δp_j,t = α + Σ β_jk Δp_k,t−ℓ` by sport/market/time-to-start; steam event = leader move ≥ x ticks and ≥ m independent clusters follow within 30–90 s; fakeability index = followers ÷ limit at origin `[R2-gpt §1.4][R2-opus §1.4–1.5]`; batched OpticOdds events mark a book-side repricing pass `[OO §8.6 #20]` | tick ledger with limits at every tick, `bookmakerChangedAt`, news timestamps (#14) | offline | improves #3/#4 weights | public steam alerts are already-priced `[R2-gpt §1.4]` | `limit_max` on every quote row; injuries/lineups diffs with `recv_ns` |
| 11 | **In-play modeled edge** (Phase 3+) | Own real-time fair price from game state vs book lag `[R2-opus §2.4]`; on PMs only 5.2 % of live game time is tradable under depth/spread/age filters `[R2-opus §2.4]` | scores/clock/in-play (#10), live odds (#4), PM depth | sub-second | unknown until post-acceptance data exists `[R2-gpt §2]` | rejections, bet delays, voids | `u3.results.in_play`, quote-age filters in backtests |

### 5.1 Worked examples (the arithmetic detectors must implement)

**(a) Sportsbook ↔ Kalshi arbitrage, fee-aware.** Kalshi YES for team A at `c = 0.62` (raw book, `exclude_fees=true`); taker fee `f = 0.07 × 0.62 × 0.38 = 0.0165` per contract `[R2-opus §2.2]`; sportsbook price on team B (complement, no draw) `+185` → `d = 2.85`, `1/d = 0.3509`. Total cost per $1 payout = `0.62 + 0.0165 + 0.3509 = 0.9874` → gross 1.26 %. Then subtract: settlement-mismatch haircut (probability of a discretionary/last-price settlement × expected adverse move, e.g. 0.3 % × 40 % = 0.12 %), capital lock-up to resolution, and the smaller of the sportsbook stake cap (`limit_max`) and Kalshi depth at 0.62 (`order_book` levels) → net ≈ 1.0 % on that capacity. Using the real Ipswich–Liverpool board `[XJ]` (Kalshi Liverpool −200, FanDuel Ipswich +460, Draw +370): `1/1.50 + 1/5.60 + 1/4.70 = 1.058` → no arb; the detector must also test the draw-no-bet and double-chance equivalents `[XM §1.7]`.

**(b) DFS pick'em screen.** Pinnacle prop Over 24.5 at −145 / Under +118 → multiplicative devig `p_over = 0.592/(0.592+0.459) = 0.563`; PrizePicks flat-leg break-even 0.5434 → +1.9 pts; Underdog 4-flex break-even 0.5169 → +4.6 pts `[R2-opus §2.5]`. Require the SharpSports `pp`/`ud` line to be identical (24.5) and its `odds` to be `+100` (non-standard multipliers `-137/-119/-112` exist `[SS §3.6]`), the OpticOdds `prizepicks*` payout id to match the entry type `[XM §1.6]`, and no injury/lineup change since the Pinnacle print; report EV per structure, never a single number.

**(c) Per-book lag.** For each Pinnacle print at `t0 = bookmakerChangedAt` `[OP §7.1]`, find the first follower print in the same direction within 120 s; store `Δ_book = follower.bookmakerChangedAt − t0` (or `changedAt` when the book has no own timestamp). A book whose p50 Δ is > 2 s for a market family with limits ≥ $1k is a latency-arb candidate; a book with p50 < 0.5 s is a copier to down-weight in consensus. OpticOdds `detect_lag_upper = odd.timestamp − last_polled[book].timestamp` bounds the vendor's own detection lag `[OO §7.3]`.

**(d) CLV.** Bet taken at 2.10 on a spread −3.5; freeze snapshot at T−5 s shows Pinnacle −3.5 at 1.95/1.95 → devig `p_close = 0.5`; `CLV_EV = 2.10 × 0.5 − 1 = +5.0 %`. If the closing line is −3 instead of −3.5, apply the half-point valuation from the settlement-margin distribution before comparing.

**Non-goals for edges** (all phases): courtsiding/in-venue relay, multi-accounting/beards, geolocation or KYC evasion, automated placement on retail books that prohibit it. Research briefs that describe such tactics `[R2-gem §4]` are recorded as risks (§8), not plans.

---

## 6. Measurement & research loop

### 6.1 CLV pipeline
- Every candidate signal (Phase 2) and every order (Phase 3) is written to `u3.signals` / `u3.orders` with the canonical key, price taken, fair value and method used, fee estimate, and `recv_ns` of the triggering quote.
- Closing benchmarks joined per canonical key from (a) our own freeze rows (T−60 s / T−5 s, `event_kind='freeze'`), (b) OddsPapi `clv` with the fallback chain `clv → last tick ≤ trueStartTime → olv` `[OP §8.5]`, (c) OpticOdds historical `olv`/`clv` (populated ~2.3 days after the game; re-pull at T+3 d `[OO §5.1]`), (d) SharpSports window `close` with `timeseriesEnd=startTime` (summary `close` may be after kickoff) `[SS §5.3]`. Devig the close with the same method as the signal; report CLV in probability points and EV terms; separate spreads/totals by like-for-like line with a half-point valuation model.
- Weekly report: % beating close, mean CLV by league/market/book/time-to-start, calibration curve (decile slope 1.00 ± 0.02 `[R2-gem §5.2]`), Brier score, realized vs expected P&L once trading.

### 6.2 Latency attribution
- Quote-level `[XM §2.6]`: OddsPapi `book→gateway = changedAt − bookmakerChangedAt` (≈ 359 ms Pinnacle), `gateway→emit = ts − changedAt` (≈ 100 ms), `emit→us = recv − ts` (108 ms from the sandbox) `[OP §7.1]`; OpticOdds `aggregator→emit = entry_id_ms − timestamp×1000`, `emit→us = recv − entry_id_ms` (p50 7–32 ms) with the `ping` clock-offset correction `[OO §7.2, §7.3]`; SharpSports `recv` only (from the HTTP `date` header).
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
- Existing view `u3.quote_latency` (p50/p99 of `recv − source_ts` per provider × book × minute) `[CODE schemas/clickhouse.sql]` is the day-one SLI; extend with `gateway_ts_ms` deltas `[XM §3.4]`.

### 6.3 Mapping coverage
- Nightly `qa.mapping_report` computes the `[XM §4.1]` metrics: fixtures per league with all three ids; `opticoddsId` join rate (target ≥ 95 % MLB/NFL/EPL, ≥ 85 % NCAAF); SharpSports join rate (≥ 90 % MLB/NFL near-term); books resolved vs `unknown`; markets in `other:*` by quote volume (< 10 %, every key > 1 % reviewed); duplicate canonical fixtures (0); cross-provider price disagreement (> 0.02 decimal on the same key/book within 5 s → < 1 % of pairs); OpticOdds ↔ SharpSports team (`Team.oddsjamId`) and player (`Player.oddsjamId`) equality rates.

### 6.4 Data-quality SLOs (alert rules in Grafana Cloud)

| SLI | Target | Alert rule (PromQL/ClickHouse sketch) |
|---|---|---|
| Quote freshness p99 (`recv − changedAt`) per book, in-play | < `1000 × maxDelayLiveInSec` `[OP §10.7]` | `histogram_quantile(0.99, rate(u3_quote_age_ms_bucket{provider="oddspapi"}[5m])) > on(book) u3_book_max_delay_live_ms` |
| Edge transport (`recv − ts` / `recv − entry_id_ms`) p99 | < 500 ms | `histogram_quantile(0.99, rate(u3_transport_ms_bucket[5m])) > 500` for 5 m |
| Stream liveness | last message age < 30 s (OddsPapi) / `ping` < 15 s (OpticOdds) during a live slate | `time() - u3_last_msg_ts{stream=~"odds.*"} > 30 and on() u3_live_fixtures > 0` |
| Reconciliation divergence | < 0.1 % of keys per sweep | `u3_sweep_divergent / u3_sweep_keys > 0.001` |
| Archive completeness | closed file per active stream per hour; GCS object ≤ 2 h later | `time() - u3_gcs_newest_object_ts{stream} > 7200` |
| Settlement completeness | > 99 % finished fixtures with 0 `UNDECIDED` (excl. `REQUIRES_NON_SCORE_STATS`) within 24 h `[OP §10.7]` | ClickHouse nightly query → gauge |
| CLV coverage | ≥ 80 % of traded keys with a non-null close from ≥ 2 sources | nightly query → gauge |
| History retention watermark | oldest fixture with non-empty OddsPapi CLV ≈ 220 d; OpticOdds timeseries ≈ 57 d `[OP §10.7][OO §5.1]` | weekly probe job |
| Entitlement drift | `login_ok` echo, `/bookmakers` count (31), `/books` `oddsFeedActive` set (12) unchanged; any 403 on a previously-working endpoint pages | `increase(u3_http_status{code="403"}[10m]) > 0` |
| Budget | GCS growth ≤ 15 GB/day; GCP spend ≤ $100/month | billing export → BigQuery scheduled query |
| Coalescer health | coalesced fraction 60–95 % (too low = churn leaking; too high = state bug) | `u3_coalesced_total / u3_rows_total` |
| Mapping | `[XM §4.4]` alarms (unresolved ratio, join drift, unknown books, `other:` share, price disagreement, stale-book minutes, catalogue drift) | nightly → gauges |

### 6.5 Research loop
- Weekly: replay the last 7 days to Parquet (`u3-ingest replay`) → BigQuery; notebooks for CLV, book lag, steam detection, PM basis; results feed `weights.yaml` (book weights per league/market/time bucket) consumed by the fair-value engine.
- Monthly: re-run the mapping and entitlement probes (`tools/research/cross_join.py`, probe scripts) and diff against the specs; update `docs/research/*.md` and the `[XM §5]` gap list.

---

## 7. Phased roadmap

### Phase 0 — Ingestion MVP (done, this week)
Delivered: provider clients with rate limiters and retries; OpticOdds SSE and OddsPapi WS clients (zstd/msgpack decode, resume cursors, control-frame handling); SharpSports client; canonical model, market/selection keys, book and fixture registries; normalizers for all three; raw archive; ClickHouse sink and schema (`u3.quotes`, `u3.order_book_levels`, `u3.fixture_xref`, `quotes_latest` MV, `quote_latency` view); `u3-ingest archive|snapshot|run|archive-sync|replay` CLI; GCS sync; replay to Parquet/DuckDB; pricing library (`devig` multiplicative/additive/power/shin, `consensus` with weights/mandatory/min-providers/hysteresis, `Board` with edges and staleness); tests; research tooling; four research documents; 75 s live verification `[CODE]`.

### Phase 1 — Cloud deployment + resilience + warehouse (weeks 2–4)

| Week | Deliverables | Exit check |
|---|---|---|
| 2 | Code corrections from §0 and `[XM §5]` gaps #1–#11, #23 (registry seeding from live catalogues, `betfair-ex`, MLS id, `LGUE_ncaamb`, `ascending=true`, zstd-dict default, SSE league filters + `DECIMAL` + `exclude_fees`, `quotes_latest` provider key, staleOdds gates, period/3-way/OT mapping, `selection_line` yes/no, SharpSports line NULL). `deploy/` scripts; VM up; 24 h RTT probe `us-east4` vs `us-east1` `[R1-gpt §4]`; self-hosted ClickHouse in Docker; all units running with raw archive + GCS sync; structlog redaction; rotate OpticOdds key, revoke the pasted Perplexity key | 48 h of continuous archive with no gaps; GCS objects verified |
| 3 | OddsPapi three-connection plan, cursor persistence, `snapshot_required`/`reconnect` automation, `/fixtures/odds/main?since` sweep, `/bookmakers` health; OpticOdds bundle × league plan, REST re-hydration + reconciliation, `fixture-status`, results per league, PM politics/crypto streams, futures poll, injuries diff, last-polled; SharpSports loops L0–L3''; coalescer + volume caps; hourly manifests; Prometheus exporters + Grafana dashboards + §6.4 alerts | SLOs green 3 days; GCS ≤ 15 GB/day |
| 4 | Settlement, CLV, freeze workers and tables (§4.8, `[XM §3.3]`); `team_xref`/`player_xref` derived from joined fixtures + SharpSports `oddsjamId`; `mapping_queue`/`mapping_metrics` + nightly report; backfills (OddsPapi spine 400 d, settlement ≥ 1 y for MLB/NFL/NBA/NHL/EPL, CLV 220 d, Pinnacle ticks MLB+NFL; OpticOdds OLV/CLV + 57-day main-market ticks; SharpSports events from 2024-08, player logs); nightly replay → Parquet → BigQuery external tables + marts; benchmark gate in CI; runbooks; ClickHouse Cloud trial DDL/loader rehearsal | 7 consecutive days SLOs green; mapping targets met (MLB, EPL; NFL from week 1 of season); gate passing |

Month 2 starts the ClickHouse Cloud trial with the caps in place.

### Phase 2 — Fair value + edge detection + alerting (weeks 5–8)

| Week | Deliverables |
|---|---|
| 5 | `u3-board` service on Redis Streams; staleness gating (`staleOdds`, `maxDelay*`, `last-polled` age, quote age, `locked-odds`, absence in latest REST snapshot `[OO §10.5][OP §7.2]`); fair-value engine on `[CODE pricing/]` with per-league/market devig method chosen by backtest, `weights.yaml`, copy-cluster penalty, stored constituents |
| 6 | Fee-schedule table (Kalshi `0.07·C·p(1−p)`; Polymarket sports curve + rebate share; Polymarket US 0.30 % / 0.20 %; Novig live `0.03·C·p(1−p)`; ProphetX 1 % `[R2-opus §2.2]`) refreshed from live venue objects; settlement-rule registry per venue/sport (OT, abandonment, ties, DNP; OpticOdds grader rules as one column `[OO App A]`) with mismatch score; detector #1 (PM basis) and #4 (+EV vs consensus) |
| 7 | Detector #5 (DFS pick'em with correlation flags) and #3 (stale-quote candidates from `u3.book_lag`); Slack alerting with dedup/quiet hours; `u3.signals` ledger; paper-trading P&L with CLV |
| 8 | Steam/line-origin research report; weekly CLV report automated; go/no-go per edge family; Phase 3 design review |

### Phase 3 — Execution + risk (weeks 9–12+)
Deliverables: Kalshi and Polymarket execution adapters (native APIs; RSA-PSS / L2 HMAC auth `[R3-gem §4]`) behind a common order interface; order/fill ledger with the seven-timestamp decomposition; risk engine (per-market, per-event, per-venue and correlated exposure caps; max quote age; cancel-backlog limit; kill switch on `staleOdds`, settlement disputes, venue/legal state changes); market-making pilot on Kalshi in 1–2 liquid leagues at minimal size; sportsbook legs via deep links (`deep_link` on every OpticOdds REST odd `[OO §1.1]`, SharpSports `betPlaceLinks`/`bookIds` `[SS §3.6]`) as a human-click workflow, not automated placement; optional SOAX-based validation of retail quote acceptance (read-only); betSync loop L6 for executed-price reconciliation. Exit: realized P&L, fill rates and latency attribution reported for 4 weeks; decision on scaling capital.

### Explicit non-goals (all phases)
Kafka/PubSub, Kubernetes, multi-region HA, a Rust/Go rewrite before the gate fails, OpticOdds Copilot (not licensed `[OO §1.1]`), OddsPapi/55-tech ABP automated bet placing on retail books `[R3-gem §5]`, non-sport PM trading before Phase 3, any account-evasion tooling.

---

## 8. Risks & mitigations

| Risk | Evidence | Mitigation |
|---|---|---|
| Vendor ToS / licensing: data redistribution, automated betting | OpticOdds enterprise licence; OddsPapi positioned as data-only with ABP separate; SharpSports betPlace is deep-link only `[R3-gem §5][R3-pplx §5]`; Swish v. OddsJam/OpticOdds litigation over scraped book data `[R3-gem §5]` | No redistribution of feeds; execution only on venues whose terms permit API trading (Kalshi, Polymarket); retail legs by human click; contract/indemnification questions in §9 |
| Trial-credit cliffs | ClickHouse 30 d, Snowflake 30 d, GCP 90 d `[R1-gpt §1.1, §2.1, §3.1]` | Raw archive is provider-independent; ClickHouse DDL + loaders scripted; self-hosted ClickHouse tested before the trial; budget alerts at 70/90 % |
| Data volume blow-up | Polymarket 81–87 % of odds messages; soccer all-leagues 1.5 MB/s; DK 433k ticks/game `[OO §4.2][OP §5.2]` | §1.4 caps; budget kill-switches (§1.3); coalescing is measured (`coalesced_rows_total`) |
| Vendor outage or per-book feed loss | OpticOdds latency incidents on its status page `[R3-pplx §1]`; OddsPapi `staleOdds`, `reconnect` releases `[OP §4.5]`; Kalshi poller 1,595 s stale, `sporttrade` 101 d dead `[OO §7.2, §8.3]` | Dual-vendor coverage for the six common books; `staleOdds`/`last-polled` gating; hard stops in the board; alerts on liveness; runbook 7 |
| Replay/resume limitations | OpticOdds `last_entry_id` replay does not work `[OO §4.6]`; OddsPapi `odds` may not be replayable, 60 s window `[OP §4.6]`; PM stream has no replay `[OO §4.5]` | REST re-baseline on every reconnect; reconciliation sweeps; our own archive is the ledger |
| Key exposure & rotation | `/fixtures/results/queue/status` echoes the raw OpticOdds key `[OO §1.1]`; OddsPapi key travels in URLs `[OP §9.3]`; OpticOdds `?key=` in stream URLs `[OO §1.2]`; a Perplexity key was pasted in chat | Rotate OpticOdds key now and after every probe session that touched the queue endpoint; treat that endpoint's output as secret; redaction processor; revoke the Perplexity key; rotation runbook (§4.10) with dual-key overlap |
| Entitlement drift | OddsPapi 403s are precise but `[]`/silent drops also occur `[OP §1.6, §9.2]`; OpticOdds unknown sportsbook ids silently ignored `[OO §1.6]`; SharpSports silently returns `[]` for lowercase league filters `[SS §2.2]` | Assert echoes and counts; 403 on a previously-working endpoint pages; league filters by `LGUE_*` id only |
| Schema drift | OddsPapi breaking changes ~quarterly; 5 undocumented `Bookmaker` fields `[OP §9.3]`; OpticOdds pagination envelope changes, `limits.max` vs `max_stake` `[OO §9.1]`; SharpSports added `ev`, `theOddsApi`, `venue`, `seasonType`, `changeDate` undocumented `[SS §10.5]` | Raw-first archive; lenient parsers; unknown-key counters; contract tests on live samples; key-set assertions |
| Mapping errors → false arbs | name mismatches (OpticOdds "Ipswich Town FC" vs OddsPapi "Ipswich Town") `[XM §1.3.2]`; `participantsRotated`; league-scoped OpticOdds team/player ids `[OO §3.2]`; three player-id spaces `[XM §5 #3]` | Exact-id joins first; `team_xref`/`player_xref`; cross-provider price sanity alert (§3); manual override file |
| Settlement mismatch | Kalshi last-price settlement on abandoned games, ties, DNP `[R2-opus §2.2]`; OpticOdds grader deviates from house rules (tennis retirement, soccer substitute goalscorer refunded, no MLB 5-inning rule) `[OO App A]` | Settlement-rule registry with mismatch score; haircut EV by jump risk; store both vendors' grades |
| Stale quotes traded | OpticOdds REST returns stale-but-available prices as-is (5–14 h old observed) and omits suspended ones `[OO §7.2, §8.3]`; SharpSports has no timestamps `[SS §3.6]` | Quote-age gating everywhere; SharpSports never used for pricing decisions |
| Fee basis confusion | Polymarket `price` fee-adjusted by default (`-10421` vs book `-9900`) `[OO §8.1]` | `exclude_fees=true` on all OpticOdds exchange pulls; fee model applied by us; QA check that price == `order_book[0][0]` |
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

**OpticOdds** `[OO §9.3]`
1. `last_entry_id` replay: documented but non-functional on our key — expected behaviour and retention window; `entry_id` monotonicity on soccer.
2. Are the observed 8,000/15 s standard and 50/15 s historical limits contractual; 429 body/`Retry-After` semantics; behaviour above 250 stream connects/15 s; SSE idle timeout / max lifetime; gzip on SSE.
3. `fixture-status` cadence on `/stream/odds` (none seen in 90 s) and the full status set; whether `locked` entries are ever retained in historical (`include_locked`).
4. PM stream: Polymarket condition-id mapping for CLOB routing (only clobTokenId exposed); `canonical_id` population rules (95 % politics, 0 % crypto); `canonical_id[]`/`source_market_id[]` stream filters.
5. `updated_since` semantics (0 rows returned); `lookback_num` on results/last-x; Pinnacle event ids in `deep_link` vs OddsPapi `pinnacleId` as a secondary join.
6. Security: `/fixtures/results/queue/status` echoes the API key — fix and confirm rotation procedure `[OO §1.1]`.
7. Coverage and cadence: Kalshi NFL/EPL game markets, Novig/ProphetX poll cadence (prophet_x 2.5 h stale), Sporttrade status; RotoWire add-on terms; Copilot pricing (not required).

**SharpSports** `[SS §9.2]`
1. Backend refresh cadence per book for `/prices` (no timestamp); live-mode latency claims (sub-100 ms) vs observed 0.28 s per event / 2–7 s per league.
2. 429 behaviour (`Retry-After`?) and the effective limit for `/prices` (100 vs 50 rps) and `/marketSelections` (50 vs 20).
3. `Price.ev` definition (units, fair-line source; populated only on Pinnacle and `bestPrice`); `marketOfferVolume`/`marketSelectionVolume` units; historic `consensus` method.
4. `oddsjamId` population rules (present for near-term MLB/NFL/WNBA/MLS, absent for EPL and late-season NFL) and guarantee of equivalence to OpticOdds `game_id`; whether `Event.theOddsApiId` is ever populated.
5. Does explicit `?prices=true` on `/marketSelections` re-enable the per-book ladder map; performance of player/team-scoped historic summaries (55–98 s, timeouts); historic retention horizon; are in-play quotes stored.
6. Confirm the 12 odds-feed books, Pinnacle's `unsupported` status, DVP direction, `live` semantics in-play; betSync population-level flow statistics and research terms.

**Venues (for Phase 3)**: Kalshi API tier and PrivateLink availability; Polymarket US vs international access and fee flags; Novig/ProphetX market-maker API programmes.

---

## 10. Decision log

| # | Decision | Alternatives considered | Why |
|---|---|---|---|
| 1 | **Python asyncio (uvloop, orjson) for the hot path through Phase 2, with a benchmark gate** | Go service (recommended by `[R1-gpt §5.1][R1-pplx §5]`), Rust, Python for adapters only | The prototype already exceeds the stated 5–20k rows/s range end-to-end in this sandbox `[CODE README]`; two-person team; vendor latency (0.1–0.5 s) dominates in-process time; the gate (§1.5) protects the decision and confines any rewrite to the decode stage |
| 2 | **OddsPapi WS as primary real-time sportsbook feed; OpticOdds SSE as breadth/PM/DFS/futures/results primary and cross-check** | OpticOdds SSE as primary; either alone | OddsPapi: 31 books in one connection, resume cursors, zstd-dict (7–9× smaller), three timestamps per quote, per-side limits, frozen ids across books, `staleOdds` gating `[OP §4, §7, §8]`; OpticOdds: 229 books incl. DFS payout ids and exchanges with `order_book`/`source_ids`, non-sport PMs, grader/results, deep links `[OO §1.1, §3.6]`, but no working replay `[OO §4.6]` and 5 books per stream. Both are archived; the six common books give a continuous cross-check |
| 3 | **Raw archive first; ClickHouse/BigQuery derived** | Normalize-first with raw sampling | Vendors change shapes quarterly `[OP §9.3]`; OddsPapi history evaporates at ~220 d `[OP §5.2]`, OpticOdds ticks at ~57 d `[OO §5.1]`, in-play/depth/lock/PM history exists nowhere else `[OO §5.3]`; replay exists `[CODE replay.py]`; "GCS is the source of truth; ClickHouse is rebuildable" `[R1-gpt §5.3]` |
| 4 | **ClickHouse = hot tick store/board mirror; BigQuery = research warehouse; Snowflake = optional sprint** | Snowflake as main warehouse; ClickHouse for everything; BigQuery streaming | Credit fit: BigQuery shares the GCP $300 and has a permanent free tier; ClickHouse Cloud is ~$186/mo after its 30-day trial `[R1-gpt §2.1, §3]`; Snowflake has no free tier and is unreachable from this sandbox; tick queries want ClickHouse, stats joins want a warehouse |
| 5 | **Single on-demand GCE VM (`e2-standard-2`), no Cloud Run/GKE/NAT** | Cloud Run min-instances; GKE Autopilot; Spot primary | Long-lived sockets, fixed IP, local spool, predictable cost; Cloud Run WebSockets are timeout-bound requests; NAT bills per GiB `[R1-gpt §1.3–1.4]`; Spot preemption on the only consumer is unacceptable |
| 6 | **Region `us-east4` for the collector (confirm with a 24 h RTT probe; `us-east1` if ClickHouse PSC/egress matters more)** | `us-central1` (ClickHouse region) | OddsPapi serves us from `oddspapi-us1` with Cloudflare `-IAD` `[OP §7.3]`; OpticOdds `cf-ray` also `-IAD` `[OO §1.3]`; Kalshi is AWS us-east `[R1-pplx §4]`; ClickHouse Cloud has no `us-east4` `[R1-gpt §2.3]` → egress budget in §1.3 |
| 7 | **Coalesce before ClickHouse; archive everything** | Insert every tick; sample the archive | 81–87 % Polymarket churn and DK re-confirmations `[OO §4.2][OP §5.2]`; egress and storage budgets; research needs the raw ledger, trading needs the latest state |
| 8 | **Canonical fixture id = OpticOdds id; join OddsPapi via `opticoddsId`, SharpSports via `oddsjamId`, then team+time; teams via `Team.oddsjamId`** | OddsPapi id as canonical; Betradar id | OpticOdds id is present on both other vendors' records `[XM §1.3.2]`; reverse mapping through OddsPapi is not entitled (`bookmaker=opticodds` → 403 `[OP §9.1]`); Betradar/Sportradar/Stats Perform are disjoint id spaces `[XM §1.3.2 step 6]` |
| 9 | **Canonical quote identity `(book, fixture, market, period, selection, line)` with provider ids retained; provider added to the latest-state key** | Provider-native ids only | Enables cross-provider comparison and dedup; OddsPapi's frozen `outcomeId` and OpticOdds `grouping_key`/`normalized_selection` are kept for exact grouping `[XM §1.8]`; the same book arrives from up to three providers `[XM §3.4]` |
| 10 | **SharpSports for stats/historic/DFS lines only, never for real-time pricing** | Use `/prices` as a third real-time source | No timestamps on prices, no streaming `[SS §3.6, §4]`; 2–7 s league payloads `[SS §1.7]`; but unique game logs, DVP, park factors, injuries with `played`, open/close windows, `consensusProjection`, `ev`, `bookIds` `[SS §3.11, §6, §8]` |
| 11 | **Three clocks on every quote row** | Receive time only | Latency attribution and per-book lag are core research products `[OP §7.1][OO §7.3][XM §2.6]` |
| 12 | **In-process board in Phase 1; Redis Streams IPC in Phase 2; no Kafka/PubSub** | Kafka, Pub/Sub, ZeroMQ | One VM, one team; Redis gives replayable streams and a last-state cache at zero cost; Kafka adds ops without benefit at this scale |
| 13 | **Fee schedules and settlement rules as versioned data, refreshed from venues** | Hard-coded constants | Fees changed in 2026 (Polymarket sports rate and rebate share) `[R2-opus §2.2]`; settlement discretion is the dominant PM arb risk; OpticOdds grader rules diverge from house rules `[OO App A]` |
| 14 | **`odds_format=DECIMAL` and `exclude_fees=true` on every OpticOdds odds pull and stream; fees modelled by us** | Take vendor fee-adjusted American prices | Vendor fee adjustment is opaque and differs by book (`-10421` vs `-9900`) `[OO §8.1]`; American extremes and American-format ladders complicate storage `[XM §5 #9]`; our fee table is versioned and venue-specific |
| 15 | **No direct sportsbook scraping in step one; SOAX reserved for Phase 3 validation** | Scrape books for latency ground truth now | Brief scope; ToS/CFAA exposure `[R3-gem §5]`; vendor feeds already give per-book timestamps and poll heartbeats |
| 16 | **Secrets: `.env` (600) now, Secret Manager later; rotate OpticOdds key after probes; redact keys in all logs** | Leave as is | Queue-status endpoint echoes the key `[OO §1.1]`; OddsPapi key in URLs `[OP §9.3]`; Perplexity key exposure |
| 17 | **ClickHouse Cloud trial consumed in month 2, self-hosted single node before/after** | Start the trial immediately | Month 1 is deployment and volume-cap work; the trial should cover a full in-season month with the caps in place; a 30-day trial cannot span 90 days `[R1-gpt §2.1]` |
| 18 | **Edge priority: PM arbitrage and market making first, soft-book edges as capped side lines** | Latency arb and promos first (highest per-unit ROI) | Structural edges scale and are not account-mortal; soft-book edges self-terminate `[R2-opus §0, §2.1][R2-gpt §4]` |
| 19 | **Prediction-market non-sport streams limited to the non-empty categories (politics, crypto)** | All 11 categories | 933 + 514 snapshots/s already `[OO §4.5]`; `/canonical-events/ids` is empty for the rest `[OO §2.9]`; no execution venue for non-sport markets in Phases 1–2 |
| 20 | **OpticOdds results streams one connection per league, futures by REST poll** | One results stream per sport; futures SSE | Vendor guidance is one league per results connection `[OO §4.3]`; futures SSE produced 0 events in 30–60 s windows while REST returned 5,755 NFL odds `[OO §4.4, §2.4]` |
| 21 | **Adopt the mapping doc's table names and gap list as the Phase 1 backlog** | Keep this plan's earlier ad-hoc names (`fixture_scores`, `mapping_unresolved`) | One vocabulary across research docs, schema and code `[XM §3.3, §4.2, §5]` |

---

## 11. Appendices

### 11.1 Volume model (per stream, after caps)

| Stream | Observed uncapped | Cap policy | Rows/s to ClickHouse (est.) | Raw GB/day (zstd, est.) |
|---|---|---|---|---|
| OddsPapi `odds` (14 universe books, 6 sports) | 27–500 msg/s, 2–59 oddsIds/msg `[OP §4.10]` | change-only + 60 s heartbeat | 400–1,500 | 2–6 |
| OddsPapi `fixtures/scores/clocks` | 738 fixtures msgs / 23 scores per capture window `[OP §4.10]` | as-is (small) | < 50 | 0.3 |
| OpticOdds `odds` × 20 connections | 223 (baseball) – 1,544 (soccer all leagues) rec/s per connection `[OO §4.2]` | league filter + change-only + 60 s heartbeat; ladders top-3, ≤ 1/s | 500–2,000 | 3–6 |
| OpticOdds results × ≤ 9 | 11 events/30 s (tennis) `[OO §4.3]` | as-is | < 20 | 0.1 |
| OpticOdds PM politics + crypto | 933 + 514 snapshots/s `[OO §4.5]` | ≤ 1/s per market | 150–400 | 1.5–3 |
| SharpSports targeted polls | 1.67 MB per event-poll, 3.78 MB per DFS league call `[SS §1.7]` | store diffs only | 100–300 | 0.5–1 |
| **Total** | | | **≈ 1.2–4k rows/s** | **≈ 7–16 GB/day** |

### 11.2 Identifier glossary

| Concept | OpticOdds | OddsPapi | SharpSports |
|---|---|---|---|
| Fixture | `id` (`20260902FF9AD242`, opaque), `game_id` (`40548-37337-2026-09-02-16`, legacy OddsJam) `[OO §3.2]` | `fixtureId` (`id1300010963302451`, opaque) `[OP §3.2]` | `EVNT_…`, `oddsjamId` (= OpticOdds `game_id`), `sportradarId` UUID, `sportsdataioId`, `theOddsApiId` (null) `[SS §3.2, §6]` |
| Team | league-scoped hex `id`, `base_id` `[OO §3.2]` | `participantId` int `[OP §3.11]` | `TEAM_…`, `oddsjamId` (= OpticOdds team id) `[XM §1.4]` |
| Player | league-scoped hex `id`, `base_id` `[OO §3.2]` | int `playerId` ("Last, First") `[OP §3.11]` | `PLYR_…`, `oddsjamId` (12/16 hex) `[XM §1.5]` |
| Book | slug (`draftkings`, `betfair_exchange_lay_`, `prizepicks_5_or_6_pick_flex_`) `[OO §3.2]` | slug (`betfair-ex`, `betonline.ag`) `[OP §3.2]` | 2-char abbr (`dk`, `pn`, `kl`, `pm`, `pp`, `ud`) `[SS §3.7]` |
| Market | `market_id` slug (`run_line`) + `market_type_id` `[OO §3.2, App C]` | frozen int `marketId` (= lowest `outcomeId`), one per line `[OP §3.13]` | `MKT_…` + `segment.id` + `metric.id`; `oddsjamId` = OpticOdds slug `[SS §3.3][XM §1.7]` |
| Selection | `normalized_selection` + `selection_line` + `points`; odd `id` (unstable) `[OO §3.6]` | `outcomeId` + `playerId`; `oddsId = fixture:book:outcome:player` `[OP §3.2]` | `MRKT_…` marketSelection + `line` per price `[SS §3.5]` |
| Venue-native ids | `source_ids` (Kalshi ticker + yes/no, Polymarket clobTokenId, Novig uuid, Betfair ids), `deep_link` `[OO §3.6, §6]` | `bookmakerMarketId`, `bookmakerOutcomeId`, `bookmakerFixtureId` `[OP §6.2]` | `Price.bookIds {eventId, marketId, selectionId}`, `betPlaceLinks` `[SS §3.6]` |
| Timestamps | odd `timestamp` float s; `entry_id` ms; PM `timestamp_ns` `[OO §3.13]` | `bookmakerChangedAt`, `changedAt`, `ts` ms; `startTime` s `[OP §3.14]` | none on prices; ISO on events/windows `[SS §3.15]` |

### 11.3 Provider fact sheet (quick reference)

| | OpticOdds v3 | OddsPapi v5 | SharpSports v1 |
|---|---|---|---|
| Base / auth | `https://api.opticodds.com/api/v3`, `X-Api-Key` `[OO §1.2]` | `https://v5.oddspapi.io/en`, `?apiKey=`; WS `wss://v5.oddspapi.io/ws` login frame `[OP §1.2]` | `https://api.sharpsports.io/v1`, `Authorization: Token` (private key for prices) `[SS §1.2]` |
| Entitlement | all public REST, all SSE, PM endpoints, historical incl. timeseries; no Copilot; 229 books `[OO §1.1]` | sports 10–15, 31 books, 12 WS channels, no futures odds, no PM topics `[OP §1.1]` | betPrices (12 odds-feed books), historicData, betSync, betPlace ids `[SS §1.1]` |
| Rate limits | 8,000/15 s standard, 50/15 s historical (observed), 250 connects/15 s; ≤ 5 books/≤ 5 fixtures per call `[OO §1.4]` | 10/s odds bucket, 200/min per endpoint; 5 WS connections; 5 bookmakers per query `[OP §1.4]` | 50 rps, 20 rps large-list; no headers `[SS §1.4]` |
| Real-time | SSE per sport × 5 books × ≤ 10 leagues; results per league; PM per category; no replay `[OO §4]` | WS zstd-dict, 60 s resume window, coalesced `odds` `[OP §4]` | none (poll) `[SS §4]` |
| Latency | delivery p50 7–32 ms after detection; detection lag unknown; last-polled heartbeat `[OO §7]` | book→gateway ≈ 359 ms, gateway→emit ≈ 100 ms, emit→us ≈ 108 ms `[OP §7.1]` | per-event poll 0.28 s; no quote timestamps `[SS §7]` |
| History | ticks 57–60 d pre-match; OLV/CLV ≥ 1 y (CLV ~2.3 d after) `[OO §5]` | ticks + CLV ≈ 220–230 d; settlement ≥ 1 y `[OP §5]` | open/close windows since 2024-08; player logs 2023/2024+ `[SS §5]` |
| Cross ids | `game_id` (= SS `oddsjamId`), `statsperform_id`, rotation numbers, `source_ids` `[OO §6]` | `opticoddsId`, `pinnacleId`, `betradarId`, `bookmakerFixtureId` `[OP §6]` | `oddsjamId` (event/team/player), `sportradarId`, `sportsdataioId`, `bookIds` `[SS §6]` |
| Settlement | grader Won/Lost/Refunded/Half; house-rule divergences `[OO App A]` | WIN/LOSE/PUSH/HALFWIN/HALFLOSS/CANCELLED/UNDECIDED; no player props `[OP §8.6]` | betSync outcomes on our own slips only `[SS §8]` |

### 11.4 Repository layout after Phase 1

```
u3ingest/            providers/{oddspapi,opticodds,sharpsports}  canonical/  mapping/  sinks/{raw,gcs,clickhouse}.py  pricing/  replay.py
                     coalesce.py  batch/{scheduler.py, jobs/*.py}  metrics.py  board/ (Phase 2)
schemas/             clickhouse.sql (existing + §4.8 + [XM §3.3])  bigquery/*.sql
deploy/              vm.sh  units/*.service  oo_streams.yaml  ss_poll.yaml  batch.yaml  env.example
mapping/             overrides.yaml  weights.yaml (Phase 2)  fees.yaml (Phase 2)  settlement_rules.yaml (Phase 2)
docs/                PLAN.md  research/{oddspapi,opticodds,sharpsports,cross-provider-mapping}.md  runbooks/*.md
tools/research/      probes and synthesis scripts (unchanged)
tests/               test_core.py  test_normalize.py  test_gcs.py  test_replay.py  test_pricing.py  test_coalesce.py  bench_replay.py
```
