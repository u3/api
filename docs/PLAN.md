# u3 — Integration & Ingestion Plan (sports + prediction-market trading data platform)

**Status:** definitive plan for step one (ingestion foundation) and the phases it must serve. Written 2026-09-03 against the live probes and provider specs in `docs/research/`, the current `u3ingest` implementation, and the external research briefs. Where a research brief disagrees with our own probes, the probe wins.

**Citation keys used below**
- `[OP §n]` — `docs/research/oddspapi.md` section n (live-probed spec).
- `[SS §n]` — `docs/research/sharpsports.md` section n (partial draft; continuation queued).
- `[OO-probe #n]` — OpticOdds live-probe findings (171 probes), item n; `[OO-sum <group>]` — reader summaries `oo-core`, `oo-odds-stream`, `oo-prediction-markets`, `oo-results-a/b`, `oo-entities-a/b`, `oo-copilot-trading`. `docs/research/opticodds.md` had not been generated at the time of writing; reconcile this plan against it when it lands.
- `[XJ]` — cross-provider live join probe (`cross.md`, 2026-09-03T10:45Z).
- `[CODE path]` — current implementation on branch `claude/arbitrage-api-integration-plan-pphn75`; `[PR #3/#4/#5]` — open Copilot PRs (GCS archive sync, replay to Parquet/DuckDB, pricing library).
- `[R1-gpt]`, `[R1-pplx]` (infrastructure), `[R2-gpt]`, `[R2-gem]`, `[R2-opus]`, `[R2-pplx]` (methodology/edges), `[R3-gem]`, `[R3-pplx]` (vendor landscape) — external web-grounded briefs.

---

## 0. Executive summary

We are building the data spine of a small proprietary trading operation across sportsbooks, sports prediction markets (Kalshi, Polymarket, Novig, ProphetX, Betfair) and non-sport prediction markets. Step one is done in prototype form and this document turns it into a production-shaped, budget-bounded system and sets up the fair-value, edge-detection and execution phases that consume it.

**What we have proven (Phase 0, this week).** A Python asyncio pipeline (`u3ingest`) that bootstraps fixture/market/book registries from all three vendors, joins fixtures across vendors, streams OpticOdds SSE and the OddsPapi WebSocket, polls SharpSports, archives every raw payload to gzip JSONL partitioned by provider/stream/hour, normalizes to one canonical `Quote`/`OrderBookLevel` model, and batch-inserts into ClickHouse. A 75 s live run on baseball + soccer produced 381,188 canonical quotes, 1,311,005 order-book levels and 105,128 raw messages (52 MB gz) with zero normalization errors `[CODE docs/research/README.md]`. Three Copilot PRs add GCS archive sync `[PR #3]`, replay of the raw archive into Parquet/DuckDB `[PR #4]`, and a devig/consensus/board pricing library `[PR #5]`.

**The ten decisions that shape everything else** (full rationale in §10):
1. **OddsPapi WS is the primary real-time sportsbook feed; OpticOdds is primary for breadth, prediction-market order books, DFS pick'em, futures, results/grading and non-sport markets; SharpSports is primary for stats/historic context and DFS +100 lines, never for real-time odds** (its `/prices` carries no timestamp `[SS §3.6]`).
2. **Python asyncio stays the hot-path runtime** through Phase 2, behind an explicit benchmark gate (≥40k normalized rows/s sustained, p99 < 10 ms in-process) that, if failed, carves out only the decode/normalize stage into Rust — not a rewrite.
3. **Raw archive first**: GCS is the source of truth; ClickHouse and BigQuery are rebuildable from it (`u3-ingest replay` `[PR #4]`).
4. **One on-demand `e2-standard-2` VM in `us-east4`** runs all long-lived socket consumers; no Cloud Run, no GKE, no Cloud NAT, no Kafka `[R1-gpt §1.3, §1.4]`. Batch/backfill on the same VM off-peak, or a Spot VM.
5. **ClickHouse = hot tick store (≤45-day TTL) and the board's analytical mirror; BigQuery = research warehouse over Parquet in GCS (free tier + GCP credit); Snowflake = optional 30-day sprint for SharpSports stats joins, not always-on** `[R1-gpt §3]`.
6. **Coalesce before you ship**: Polymarket alone is 81–87 % of both vendors' sports-odds message volume `[OO-probe #6][OP §4.10 probe]`; we archive raw but insert only change-level, top-N-level rows to ClickHouse and cap egress at ~$20/month.
7. **Trial-credit budget**: ≈ $95/month on GCP (VM + disk + GCS + BigQuery + egress) → ≈ $285 over 90 days; ClickHouse Cloud trial consumed in month 2; Snowflake trial optional in month 3.
8. **Canonical fixture id = OpticOdds fixture id**, joined to OddsPapi via `externalProviders.opticoddsId` (100 % on MLB/EPL, 91 % NCAAF `[XJ]`) and to SharpSports via `oddsjamId == OpticOdds game_id` (37/40 MLB) with team+time fallback `[XJ]`.
9. **Three clocks on every quote** (`source_ts_ms`, `gateway_ts_ms`, `recv_ns`) so latency attribution and per-book lag are measurable from day one `[OP §7.1]`.
10. **Edges are prioritized by durability, not headline size**: sportsbook-vs-Kalshi/Polymarket arbitrage and prediction-market market-making (structural, scalable) come before soft-book edges (high ROI, account-mortal).

**Phased roadmap.** Phase 0 (done): ingestion MVP. Phase 1 (weeks 2–4): cloud deployment, resilience (zstd-dict WS, reconciliation sweeps, SSE re-hydration), settlement/CLV/backfill workers, warehouse, observability. Phase 2 (weeks 5–8): fair-value engine, edge detectors, alerting, paper-trading ledger, CLV loop. Phase 3 (weeks 9–12+): execution adapters (Kalshi/Polymarket first), risk engine, market-making pilot.

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
 │   local disk: raw JSONL.gz spool (data/raw/…, ≤48 h), Redis (Phase 2), SQLite cursors           │
 └───────────┬───────────────────────────┬───────────────────────────────┬───────────────────────┘
             │ raw archive               │ coalesced rows (native TLS 9440)│ Parquet (PR #4 replay)
             ▼                           ▼                                  ▼
   GCS bucket u3-raw               ClickHouse (Cloud trial month 2;        BigQuery datasets
   raw/<provider>/<stream>/        self-hosted fallback)                    u3_raw (external tables)
   dt=/hour=/*.jsonl.gz            db u3: quotes, order_book_levels,        u3_marts (CLV, settlement,
   lifecycle: Nearline 30 d,       fixture_xref, quotes_latest MV,          stats joins, backtests)
   Coldline 180 d, never delete    settlements, clv, book_status, ...       Snowflake (optional sprint)
```

**Languages/runtimes.** Python 3.11+, `asyncio` with `uvloop`, `orjson`, `httpx`, `websockets`, `zstandard`, `msgpack`, `clickhouse-connect` `[CODE pyproject.toml]`. No second language until the benchmark gate in §1.5 fails. SQL (ClickHouse, BigQuery). Bash/systemd for ops; a single `deploy/` directory with `gcloud` scripts (no Terraform until there is more than one VM).

**Message flow (hot path).**
1. Socket reader decodes a frame (zstd-dict → JSON for OddsPapi; SSE text for OpticOdds) and stamps `recv_ns` `[CODE providers/oddspapi/ws.py, providers/opticodds/sse.py]`.
2. The raw payload is appended to the `RawArchive` buffer **before** normalization; normalization errors never drop raw data `[CODE sinks/raw.py, pipeline.py]`.
3. Normalizer resolves book id (`BookRegistry`), canonical fixture id (`FixtureRegistry`), market/period/selection/line keys (`canonical/markets.py`) and emits `Quote` and `OrderBookLevel` rows carrying `source_ts_ms`, `gateway_ts_ms`, `recv_ns` `[CODE canonical/models.py]`.
4. Rows pass through the **coalescer** (§1.4, Phase 1) and then to the ClickHouse sink (batched async inserts, 5,000 rows or 1 s) `[CODE sinks/clickhouse.py]`.
5. (Phase 2) The same rows update the in-process `Board` (latest quote per `(fixture, market, period, line, selection, book)`) `[PR #5 u3ingest/pricing/board.py]` and are published on Redis Streams for detectors.

**Batch path.** `u3-batch` runs scheduled REST jobs (§4) under the vendor rate limiters already implemented (`SlidingWindowLimiter`: OpticOdds 2,400/15 s standard, 10/15 s historical, 240/15 s stream connects; OddsPapi 9/1 s odds and 190/60 s other; SharpSports 45/1 s and 18/1 s large-list `[CODE util.py, providers/*/rest.py]`), archives every body, and writes settlement/CLV/dimension tables. Backfills run as one-shot CLI commands.

### 1.2 What runs where, and what we turn off

| Workload | Runs on | Why | Turned off / deferred |
|---|---|---|---|
| WS/SSE consumers, raw spool, coalescer, ClickHouse inserts | GCE `e2-standard-2` (2 vCPU/8 GiB), on-demand, external IPv4, egress-only firewall, IAP SSH | Long-lived sockets need a stable process, no request timeouts, fixed IP `[R1-gpt §1.3]`; Cloud Run WebSockets are requests with timeouts `[R1-gpt §1.3]` | Cloud Run, GKE Autopilot, Cloud NAT (charges per GiB processed `[R1-gpt §1.4]`), Spot for the only live consumer |
| REST sweeps, settlement/CLV workers, backfills | same VM, `u3-batch` (nice 10); large backfills on a Spot `e2-standard-2` (~$29/mo) only when needed `[R1-gpt §1.2]` | Batch is bursty; Spot preemption is harmless for idempotent jobs | — |
| Raw archive | GCS Standard → Nearline at 30 d → Coldline at 180 d (lifecycle rule) | Immutable source of truth, cheap | Deleting raw data (never) |
| Hot tick store + board mirror | ClickHouse Cloud (GCP `us-east1`, Basic 1×8 GiB) during the 30-day/$300 trial in **month 2**; self-hosted single-node ClickHouse in Docker on the VM with 7-day TTL before/after | Cloud trial covers exactly one month of 24/7 ingest (≈$186/mo list `[R1-gpt §2.1]`); `us-east4` is not a ClickHouse GCP region `[R1-gpt §2.3]` | Idle scaling (unusable under continuous ingest `[R1-gpt §2.2]`); paid ClickHouse before the economics are validated |
| Research warehouse | BigQuery: external tables over Parquet produced by `u3-ingest replay` `[PR #4]`, plus native mart tables | Same $300 credit, permanent free tier (10 GiB storage, 1 TiB queries/mo) `[R1-pplx §3]` | BigQuery streaming inserts of raw ticks (cost + small-file behaviour `[R1-gpt §3.3]`) |
| SharpSports stats/historic joins | BigQuery by default; Snowflake $400/30-day trial as an optional month-3 research sprint | Snowflake has no free tier; sandbox cannot reach it (cert-pinned) | Snowpipe Streaming; any always-on Snowflake warehouse |
| Metrics/alerting | Grafana Cloud Free (10k series, 14-day retention) `[R1-gpt §5.4]` | Zero cost, hosted alerting | Self-hosted Prometheus/Grafana; per-market metric labels (cardinality) |
| Non-sport prediction-market streams | one category (`politics`) archived continuously; others on demand | 933 snapshots/s, 120 MB/45 s for politics alone `[OO-probe #6]` | All 11 categories 24/7 |
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
| Egress to ClickHouse Cloud (`us-east4` → `us-east1` public endpoint) | $0 (self-hosted) | $20 | $0–5 | ≤ 8 GB/day compressed native inserts; co-locate in `us-east1` if RTT probe (§7 Phase 1) shows < 5 ms penalty and use PSC `[R1-gpt §1.4]` |
| Cloud Logging | $0 | $0 | $0 | sampled; < 50 GiB free |
| **GCP total** | **≈ $76** | **≈ $104** | **≈ $100** | **≈ $280 of $300** |
| ClickHouse Cloud | $0 (self-host) | $0 (trial, ≈ $186 list) | $0 (self-host) or decide to pay | `[R1-gpt §2.1]` |
| Snowflake | $0 | $0 | $0 (trial sprint, ≤ $400 credits) | `[R1-gpt §3.1]` |
| Grafana Cloud | $0 | $0 | $0 | free tier |

Budget kill-switches, in order: (1) stop non-sport PM category streams; (2) narrow OpticOdds SSE to the target leagues only (`league=` param, already supported `[CODE providers/opticodds/sse.py]`); (3) lifecycle raw to Nearline at 14 d; (4) drop SharpSports league-wide `/prices` polling to 10-minute cadence; (5) pause ClickHouse inserts (raw archive continues; ClickHouse is rebuildable).

### 1.4 Volume controls (mandatory before cloud deployment)

Observed uncapped rates: OpticOdds SSE baseball (5 books) 223 records/s of which 81 % Polymarket, soccer (5 books, all leagues) 1,544 records/s `[OO-probe #6]`; OddsPapi WS unfiltered sports 10/11/13 ≈ 500 msg/s, 87 % Polymarket, 27 msg/s with the sharp/US book filter `[OP probe summary]`; DraftKings emits 433k ticks per MLB game (median 563 ms gap, re-confirmation churn) vs Pinnacle 25k `[OP §5.2]`.

Controls:
1. **Raw archive**: keep everything, but switch the archive codec from gzip(3) to zstd(3) (≈ 30–40 % smaller for JSON) and add a per-stream `dedupe_identical` option that drops a record whose body hash equals the previous record for the same `provider_odd_id` within 2 s (re-confirmation churn is still counted in `stream_health`).
2. **ClickHouse `quotes`**: insert only rows where `(price_dec, line, active, limit_max, is_main)` changed versus the in-memory last state, or ≥ 60 s since the last insert for that key (heartbeat row, `event_kind='heartbeat'`).
3. **ClickHouse `order_book_levels`**: top 3 levels per side, and at most 1 snapshot/s per `(book, venue_market_id, selection)`; deeper ladders stay in raw. Kalshi shows up to 7 levels, Polymarket 3+, Novig 1 `[OO-probe entitlements]`.
4. **Non-sport PM stream**: replace-not-patch snapshots `[OO-sum oo-prediction-markets]` are coalesced to ≤ 1/s per market for ClickHouse; raw keeps all.
5. **Scope filters**: OpticOdds SSE `league=` limited to the trading universe (MLB, NBA, WNBA, NCAAB, NFL, NCAAF, NHL, EPL, MLS); OddsPapi WS `sportIds` 10–15 with `bookmakers` = the 12 books we price against (§2.3).

### 1.5 Runtime decision and benchmark gate

Research briefs recommend Go or Rust for a 5–20k rows/s consumer and say Python+uvloop "may handle 5k–20k simple messages/sec" but must be load-tested `[R1-gpt §5.1][R1-pplx §5]`. Our prototype already sustained ≈ 5k quotes/s + 17k levels/s end-to-end (parse → normalize → archive → ClickHouse rows) in this sandbox with zero errors `[CODE README]`. Decision: keep Python, add the acceptance benchmark from `[R1-gpt §5.1]` as a CI job that replays a captured 10-minute corpus through the exact decode/normalize/coalesce path (`u3-ingest replay` `[PR #4]`) and asserts ≥ 40k rows/s, p99 < 10 ms per message, no RSS growth over the run. If the gate fails after profiling (orjson, slots dataclasses, avoiding `asdict`), the decode+normalize stage for the OddsPapi `odds` channel is rewritten as a small Rust extension (PyO3); everything else stays Python.

---

## 2. Feed usage matrix

Books priced against in Phase 1–2 ("universe books"): pinnacle, draftkings, fanduel, betmgm, caesars, betrivers, kalshi, polymarket, novig (OpticOdds only), prophetx, circa (`circa_sports` / `circasports`), betonline, bookmaker, betfair_exchange (+lay), prizepicks/underdog (DFS, OpticOdds + SharpSports). Present in all three vendors: betmgm, betrivers, draftkings, fanduel, kalshi, polymarket `[XJ]`. **Fix required:** `novig` is in `DEFAULT_BOOKS_ODDSPAPI` but is not among OddsPapi's 31 entitled slugs `[OP §1.1][CODE pipeline.py]` — remove it from the OddsPapi filter (unknown slugs are silently dropped on REST `[OP §2.1]`; assert the `login_ok.bookmakers` echo on WS `[OP §10.2]`).

| # | Data class | Primary provider / channel | Secondary / cross-check | Cadence | Rate-limit budget | Storage target |
|---|---|---|---|---|---|---|
| 1 | Fixture spine + cross-vendor ids | OddsPapi `GET /fixtures?sportId&startTimeFrom&startTimeTo` (7-day windows, back 400 d/forward 30 d) + WS `fixtures` channel `[OP §10.3, §10.4]` | OpticOdds `/fixtures/active?league` (+`include_statsperform_id`) `[CODE pipeline.bootstrap]`; SharpSports `/events?league&upcoming` `[SS §2.3]` | forward window every 5 min; bootstrap at start | OP 6 calls/5 min of 200/min; OO 9 leagues × pages of 100 per 5 min of 8,000/15 s `[OO-probe #2]`; SS 9 calls/5 min of 50/s | `u3.fixture_xref` (ReplacingMergeTree) `[CODE schemas/clickhouse.sql]`; BQ `u3_marts.dim_fixture` |
| 2 | Pre-match sportsbook odds, main + alt lines | OddsPapi WS `odds`+`bookmakers`, `receiveType=zstd-dict`, `sportIds 10–15`, 12 universe books (conn #1) `[OP §10.2]` | OpticOdds SSE `/stream/odds/{sport}?sportsbook×5&league×≤10` per book-group; OddsPapi REST `/fixtures/odds/main?fixtureIds≤50&since` reconciliation sweep `[OP §10.3]` | WS push (10²–10³ msg/s uncapped); sweep every 60 s | OP odds bucket 10/s: sweep ≈ 2/s, on-demand snapshots ≤ 3/s, ≥ 3/s headroom `[OP §10.3]`; OO SSE connects 250/15 s | raw GCS; `u3.quotes` (coalesced); `u3.quotes_latest` MV |
| 3 | Player props | OpticOdds SSE (229 books, props on most; `player_id`, `grouping_key`) `[OO-sum oo-odds-stream]` | OddsPapi (19 of 31 books with `playerProps:true`; 2,835 prop quotes on one EPL fixture) `[OP §1.1, §8.3]`; SharpSports `/prices?eventId&book` for US books | SSE push; OP WS push | included in #2 | `u3.quotes` (market `player:*`, `player_id`) |
| 4 | In-play odds | OddsPapi WS (`access.live:true`; Pinnacle `maxDelayLiveInSec` 2 s, Betfair 1 s) `[OP §7.1]` | OpticOdds SSE `is_live` records (49 % of baseball stream) `[OO-probe entitlements]` | push | included in #2 | `u3.quotes` (`extra.is_live`, `status` from #10) |
| 5 | Sports prediction-market order books (Kalshi, Polymarket, Novig, ProphetX, Betfair, SX) | OpticOdds SSE/REST `order_book [[price,size]]`, `limits.max` (top-of-book liquidity), `source_ids` (Kalshi ticker+yes/no, Polymarket token, Novig uuid, Betfair ids), `exclude_fees=true` `[OO-probe #3][OO-sum oo-prediction-markets]` | OddsPapi `meta` ladders for `polymarket`, `kalshi`, `betfair-ex`, `sx.bet` with USD notional per rung (`limit = size × cents`) `[OP §3.6, §8.1]` | push | included in #2 | `u3.order_book_levels` (top-3, ≤1/s), raw full depth |
| 6 | Non-sport prediction markets (politics, crypto, …) | OpticOdds `/stream/prediction-markets?category=` (one category per connection; full two-sided depth per snapshot; `canonical_id` on 95 % of politics snapshots) + REST `/prediction-markets/canonical-events` `[OO-probe #6, #9]` | none — OddsPapi sportIds 69–78 not entitled `[OP §1.1]` | push (politics 933 snapshots/s) | separate backend, no rate-limit headers `[OO-probe #2]` | raw GCS; `u3.pm_book_snapshots` (≤1/s per market) |
| 7 | Futures / outrights | OpticOdds REST `/futures/odds?league&sportsbook×5` (43–71 futures per league; 2.4 MB per 5-book call) — the SSE futures stream emitted 0 events in 30–60 s windows `[OO-probe entitlements; OO-sum probe]` | OddsPapi futures **metadata only** (`/futures`, WS `futures`); prices not entitled (403 `channel_not_allowed`) `[OP §2.4]` | poll every 15 min per league × 3 book-groups | ≈ 30 calls/15 min of 8,000/15 s | `u3.quotes` (`market=future:<slug>`), raw |
| 8 | Sharp anchor (Pinnacle) | OddsPapi `pinnacle` with per-side `limit` (19,354 fav / 3,000 dog), `bookmakerChangedAt`, native `bookmakerMarketId` `[OP §8.1, §8.2]` | OpticOdds `pinnacle` (`limits.max` 1,300–15,850 on NFL mains) `[OO-probe #3]`; SharpSports `pn` (main markets only, no 3-way/props) `[SS §3.9]` | push | — | `u3.quotes`; latency cross-check view `u3.pinnacle_xprov` (Phase 1) |
| 9 | Book health / staleness | OddsPapi WS `bookmakers` (`staleOdds`, `suspended`, `hasOdds`, `participantsRotated`) + `GET /bookmakers` every 60 s (`lastOddsAt`, `staleOddsSince`, `staleThresholdSec`, `maxDelay*`) `[OP §7.2, §10.3]` | OpticOdds `/sportsbooks/last-polled?league` every 60 s (prophet_x seen 2.5 h stale) `[OO-sum oo-entities-a]`; SSE `locked-odds` events | 60 s | OP 1/min of 200/min; OO 9/min | `u3.book_status`; `u3.stream_health` |
| 10 | Scores, clock, in-play state | OddsPapi WS `fixtures`+`scores`+`clocks` (conn #3) `[OP §10.2]` | OpticOdds `/stream/results/{sport}` (`in_play` period/clock/base-runners/down-distance) `[OO-sum oo-results-a]` | push | 1 SSE connection per sport in season | `u3.fixture_scores`, `u3.fixture_clock` |
| 11 | Results, grading, settlement | OddsPapi `/fixtures/settlement?fixtureId` (bookmaker-independent WIN/LOSE/PUSH/HALFWIN/HALFLOSS/CANCELLED/UNDECIDED; ≥ 1 y retention; 4–9 s latency; player props not graded) `[OP §3.9, §5.2, §8.6]` | OpticOdds `/grader/odds`, `/fixtures/results`, `/fixtures/player-results` (Won/Lost/Refunded/Half Won/Half Lost/Pending; house-rule divergences documented) `[OO-sum oo-results-a/b]` | `trueEndTime`+15 min then 30 m/2 h/6 h/24 h retries; concurrency ≤ 3 | OP ≤ 40 fixtures/min; OO grader ≤ 100/min | `u3.settlements` (transition history), BQ `u3_marts.settlement` |
| 12 | Opening / closing lines, CLV | OddsPapi `/fixtures/odds/clv?fixtureId` at `trueStartTime`+30 min and `trueEndTime`+6 h (`clv` null pregame; 17–39 % null post-match → fallback to last tick ≤ start → `olv`) `[OP §8.5]` | OpticOdds `/fixtures/odds/historical` OLV/CLV (retained ≥ 1 y; CLV null ~8 h after end, populated by ~2.3 d) `[OO-probe #4]`; **our own** T−60 s / T−5 s freeze snapshots from the WS stream `[OP §10.3]`; SharpSports `/prices/historic/summary` (first/last/high/low per book) `[SS §2.1]` | per fixture | OP 200/min; OO historical 50/15 s `[OO-probe #2]` | `u3.clv`; BQ `u3_marts.clv` |
| 13 | Tick-history backfill (pre-season, research) | OddsPapi `/fixtures/odds/historical?fixtureId&bookmaker=pinnacle` (always) + `oddsIds=` main lines across ≤ 8 books (selective); ≈ 220–230 d retention `[OP §5.2, §10.4]` | OpticOdds `include_timeseries` (change-level, ≥ 1 s gap, retained 57–60 d) `[OO-probe #4]`; SharpSports `/prices/historic/timeseries` OHLC 5 m–1 d (≤ 1,000 windows/call) `[SS §2.1]` | one-off + nightly for yesterday's fixtures | OP 200/min but 6–96 MB bodies → stream-parse, concurrency 2; OO 50/15 s | ClickHouse `u3.quotes` with `event_kind='history'`; BQ |
| 14 | Injuries, lineups, news | OpticOdds `/injuries?league` diff-polled every 60 s (no timestamps in payload) + `/fixtures?include_starting_lineups=true` 2 h before start `[OO-sum oo-results-a, oo-entities-b]` | SharpSports `/injuries?league` (free-text status, `played` outcome flag; historical) `[SS §2.4]`; OddsPapi WS `injuries`/`lineups` (silent so far) `[OP §9.4]` | 60 s / 2 h | OO 9/min | `u3.injuries` (diffs), BQ |
| 15 | Player/team stats, DVP, park factors, projections | SharpSports `/players/{id}/historicData` (Ohtani 477 games; soccer empty), `/marketSelections/{id}/metadata` (L1–L20 hit rates — `hits` counts overs regardless of side), `/teams|players/aggregateStats`, `consensusProjection` `[SS §3.10]` | OpticOdds `/fixtures/player-results` (`market_stats` map 1:1 to prop markets) `[OO-sum oo-results-b]` | nightly batch; pre-game T−3 h for slate | SS 50/s (historic summary queries can take 13–98 s — never in hot path `[SS §1.6]`) | BQ `u3_marts.player_game_log`, `dim_player`; Snowflake sprint |
| 16 | DFS pick'em lines | OpticOdds sportsbook ids per payout structure (`prizepicks`, `prizepicks_5_or_6_pick_flex_`, `underdog_fantasy_2_pick_`, `dabble_*`, `betr_picks`, …) `[OO-sum oo-entities-a]` | SharpSports `/prices?league&book=pp,ud` (all odds fixed +100) `[SS §1.6][ss-core]` | SSE push; SS every 120 s per league | SS 9 calls/2 min | `u3.quotes` (book_id `prizepicks`, `underdog`) |
| 17 | Public/sharp flow (betSync) | SharpSports `/betSlips` (only our linked bettors; refresh 1/60 s per account; minutes-scale) `[SS §2.5]` | — | Phase 3 | 20/s | BQ `u3_marts.bet_slips` |
| 18 | FX for limit normalization | OddsPapi WS `currencies` (≈ 0.18/s) + `GET /currencies` hourly (USD base; `Bookmaker.limitCurrency`) `[OP §3.11, §7.2]` | — | hourly | negligible | `u3.dim_currency` |
| 19 | Reference catalogues | OddsPapi `/markets?sportId` × 6 (4,902 markets for basketball), `/bookmakers`, `/tournaments`, `/participants`, `/players` `[OP §10.4]`; OpticOdds `/sportsbooks`, `/markets`, `/market-types`, `/leagues/active`; SharpSports `/books`, `/markets`, `/segments`, `/metrics` `[SS §2.2, §2.4]` | — | daily + on unknown id | trivial | `u3.dim_*` (SCD-2), repo YAML for overrides |

---

## 3. Canonical model & mapping strategy (summary)

The full identity-resolution design lives in `docs/research/cross-provider-mapping.md` (in progress); this section states what is implemented and the QA loops.

**Canonical records** `[CODE u3ingest/canonical/models.py]`:
- `Quote(recv_ns, provider, book_id, provider_book, fixture_id, provider_fixture_id, market, period, selection, line, price_dec, price_us, is_main, active, limit_max, source_ts_ms, gateway_ts_ms, provider_market, provider_selection, provider_odd_id, player_id, team_id, event_kind, grouping_key, extra)`. Identity of a tradeable outcome across providers = `(book_id, fixture_id, market, period, selection, line)`.
- `OrderBookLevel(recv_ns, provider, book_id, fixture_id, market, period, selection, venue_market_id, side back|lay|bid|ask, level, price, size, source_ts_ms, provider_odd_id)`.
- `FixtureRef` with `opticodds_id`, `opticodds_game_id`, `oddspapi_id`, `sharpsports_id`, `betradar_id`, `pinnacle_id`, `statsperform_id`, `sportradar_id`, `the_odds_api_id`, rotation numbers.

**Market keys** `[CODE canonical/markets.py]`: `moneyline | 3way | spread | total | team_total | player:<metric> | team_prop:<metric> | other:<slug>`; periods `full | reg | 1h | 2h | 1q..4q | 1p..3p | f5i | 1i | set1..`; selections `home | away | draw | over | under | yes | no | team:<id> | player:<id>[:over|under]`. OddsPapi is mapped from its frozen `marketType/period/handicap` catalogue (line lives in `Market.handicap`, one `marketId` per line `[OP §3.13]`); OpticOdds and SharpSports from display-name grammar (`split_period`, `_ALIAS`, `_PROP_METRIC`). `participantsRotated` flips home/away and spread sign for that book `[OP §3.4][CODE providers/oddspapi/normalize.py]`.

**Books** `[CODE mapping/registry.py]`: canonical slug → per-provider aliases (e.g. `pinnacle` ⇐ OpticOdds `pinnacle|ps3838|ps4848`, OddsPapi `pinnacle`, SharpSports `pn`). Unknown books are kept as `<provider>:<slug>` and counted in `BookRegistry.unknown`.

**Fixtures** — resolution order `[CODE mapping/registry.py][XJ]`:
1. OddsPapi `externalProviders.opticoddsId == OpticOdds fixture.id` — exact; MLB 40/40, EPL 8/8, NCAAF 114/125; start times identical. Coverage of `opticoddsId` across all OddsPapi fixtures is only 2,593 of 19,954 because OddsPapi carries far more (non-US, lower-tier) fixtures than OpticOdds prices `[XJ]`.
2. SharpSports `event.oddsjamId == OpticOdds fixture.game_id` — MLB 37/40 `[XJ]`.
3. Normalized team names + start time within ±15 min in the same league — EPL 8/8, NCAAF 73/87, MLB 3/40 `[XJ]`.
4. Planned: rotation numbers (`participant1RotNr` ↔ `home_rotation_number`) as a fourth key for US sports `[OP §6.2]`; Sportradar/Betradar ids where both sides carry them (SharpSports `sportradarId` UUID vs OddsPapi `betradarId` int — different namespaces, do not equate without a verified crosswalk).
5. Canonical id = OpticOdds id when known, else `<provider>:<id>`, re-keyed when a later join succeeds (`FixtureRegistry._index`).

**QA loops (Phase 1 deliverables):**
- `u3.mapping_unresolved` table fed from `FixtureRegistry.unresolved` and `BookRegistry.unknown` every 60 s; nightly `mapping-report` job lists the `other:*` market tail by volume, unknown books, unresolved fixtures per league with candidate matches, and coverage ratios (§6.3). Threshold alerts: `opticoddsId` join < 95 % for MLB/NFL/EPL, SharpSports join < 90 % for MLB.
- `mapping/overrides.yaml` in the repo (book aliases, market aliases, forced fixture pairs) hot-reloaded by the pipeline; every override carries an `evidence` note and expiry.
- Contract tests on real samples (`tests/test_normalize.py`) extended with one golden fixture per league per provider; CI fails on any canonical-key regression.
- Duplicate-fixture detector: two canonical ids with the same `(league, home, away, start ± 15 min)` → merge candidate in the report.
- Cross-provider price sanity: for the six books present in all three vendors, `|price_dec_OP − price_dec_OO| > 3 %` on the same canonical key for > 2 min → mapping bug alert (also catches `participantsRotated` and line-sign errors).

---

## 4. Ingestion services spec (per connector)

Legend: ✅ implemented (Phase 0), 🔶 partially, ⬜ planned (Phase 1 unless noted).

### 4.1 OddsPapi WebSocket (`u3-op-ws`)

| Aspect | Spec |
|---|---|
| Protocol | `wss://v5.oddspapi.io/ws`; first frame `login` within 10 s; login-only subscriptions (any filter change = new connection); max 5 concurrent connections; control frames JSON text, data frames per negotiated `receiveType` `[OP §4.1–4.2]` ✅ client `[CODE providers/oddspapi/ws.py]` |
| Subscription plan | conn #1 `odds`+`bookmakers`, `sportIds [10,11,12,13,14,15]`, `bookmakers` = universe books, `receiveType=zstd-dict` (320–470 B frames vs 14–20 KB JSON) `[OP §4.8, §10.2]`; conn #3 `fixtures`+`scores`+`clocks` (`zstd`); conn #4 `currencies,futures,bookmakersFutures,events,stats,injuries,lineups` (`json`; schema discovery); conn #2 shadow odds (Phase 2, second process); #5 spare for reconnect overlap. 🔶 today: one connection, `odds,bookmakers,fixtures`, `json` `[CODE pipeline.run_oddspapi_ws]` → ⬜ split into three connections and default `zstd-dict` (the `dict` frame handling exists ✅) |
| Resume/replay | persist `serverEpoch` + `lastSeenId[channel]` to SQLite every 250 ms; on reconnect send cursors only for channels in `login_ok.resume.replayChannels` and only if `now − ts(entryId) < resumeWindowMs − 5 s` (60 s window observed) `[OP §4.6]`; `odds` may not be replayable → treat every odds reconnect as `snapshot_required` ✅ cursor tracking in memory; ⬜ persistence + age rule |
| `snapshot_required` / `reconnect` | non-fatal; keep consuming, buffer, run REST `/fixtures/odds/main?fixtureIds≤50` for in-window fixtures, apply baseline, drain buffered updates with `changedAt ≥ snapshot_ts` `[OP §4.5–4.6, §10.6]`; on `reconnect` open the spare slot first ✅ detection/logging; ⬜ automatic REST snapshot |
| Backfill | fixture spine 400 d back in 7-day windows (≈ 372 calls); settlement for all finished fixtures (≥ 1 y); CLV for fixtures ≤ 220 d; Pinnacle tick history always, other books via `oddsIds` for main lines `[OP §10.4]` ⬜ `u3-ingest backfill oddspapi --phase spine|settlement|clv|ticks` |
| Raw archival | every frame (decoded JSON + `recv_ns`, `channel`, `ts`, `entryId`, `raw_len`, control frames) → `raw/oddspapi/ws-odds/dt=/hour=/…jsonl.gz` ✅ `[CODE sinks/raw.py]`; ⬜ zstd codec, per-connection stream names (`ws-odds`, `ws-fixtures`, `ws-aux`) |
| Normalization | `OddsPapiNormalizer.quotes` joins `outcomeId → marketId → handicap`, resolves `participantsRotated`, emits ladders from `meta.back/lay` ✅; ⬜ `betfair-ex` `availableToBack/availableToLay` and `sx.bet` shapes (`limit = size × cents`) `[OP §3.6]`; ⬜ `limit` currency normalization via `limitCurrency` |
| Sinks | raw → GCS; coalesced `u3.quotes`, `u3.order_book_levels`; `u3.book_status` from `bookmakers`; `u3.fixture_scores`/`u3.fixture_clock` from conn #3 ⬜ |
| Observability | per connection: msgs/s, bytes/s, decode p50/p99, `recv − ts` p50/p99 (108 ms observed from the sandbox `[OP §7.1]`), `entryId` gap count, reconnects, close codes, `snapshot_required` count, per-book `staleOdds` minutes; assert `login_ok` echo (channels, bookmakers, `access`, `resume`) equals the request and alert on drift `[OP §10.2, §10.7]` 🔶 counters in `ws.stats` → ⬜ Prometheus |
| Failure modes | 4000 client bug (fail fast), 4001 key revoked (stop, page), 4002 backpressure (switch to zstd-dict, narrow filters, move parse off socket task), 4003 too many connections (serialize connects with jitter), 1006/1011 reconnect with 1/2/5/10 s jittered backoff, 1009 raise `max_size` (16 MiB set) `[OP §4.9, §10.6]` ✅ backoff/close-code handling; ⬜ paging |

### 4.2 OddsPapi REST (`u3-batch`)

| Aspect | Spec |
|---|---|
| Protocol | `https://v5.oddspapi.io/en`, `?apiKey=` (key in URL → redact everywhere; never persist raw URLs) `[OP §1.2, §9.3]`; browser-like UA required (Cloudflare 1010) ✅ `[CODE providers/oddspapi/rest.py]`; no pagination, bodies up to 95.6 MB → stream-parse history endpoints ⬜ (`ijson`) |
| Poll plan | odds bucket (10/s, shared by `/fixtures/odds`, `/fixtures/odds/main`): reconciliation sweep `/fixtures/odds/main?fixtureIds≤50&since=<last>` ≈ 2 req/s covering all in-window fixtures every 60 s (`since` also returns inactive odds → correct removals), deep snapshot `/fixtures/odds?fixtureId` on `snapshot_required`/divergence, pre-kick freeze at T−60 s and T−5 s `[OP §10.3]`. 200/min-per-endpoint bucket: `/fixtures` forward window every 5 min × 6 sports, `/fixtures/live?sportId` every 60 s, `/bookmakers` every 60 s, `/markets?sportId` daily (+ on unknown `marketId`), `/currencies` hourly, `/fixtures/mapping?bookmaker=<slug>&fixtureIds` for 8 execution books on discovery, settlement and CLV per fixture on schedule `[OP §10.3]` ✅ limiters; 🔶 bootstrap only → ⬜ scheduler |
| Resume/replay | idempotent jobs keyed by `(endpoint, params, window)`; `since` cursor per sweep persisted in SQLite ⬜ |
| Backfill | see §4.1 backfill; settlement is the cheapest, deepest ground truth (≥ 1 y) — run it first for traded leagues `[OP §10.4]` ⬜ |
| Raw archival | every body with redacted URL, status, `x-ratelimit-*`, `cf-ray`, latency, size → `raw/oddspapi/rest-<endpoint>/…` ✅ (bootstrap) / ⬜ (all jobs) |
| Normalization | same normalizer with `kind='snapshot'`; CLV → `u3.clv` (`olv/clv` price, `changedAt`, `active`, null flag); settlement → `u3.settlements` as transition history keyed `(fixtureId, marketId, outcomeId, playerId, observed_at)` `[OP §10.5]` ⬜ |
| Sinks | ClickHouse + BQ marts (daily Parquet export) ⬜ |
| Observability | per job: calls, 429s, `Retry-After` honoured, body bytes, latency (settlement 4–9 s), divergence rate of sweep vs stream (< 0.1 % target) `[OP §10.7]` ⬜ |
| Failure modes | 429 → honour `Retry-After`, halve concurrency for a window; 503 `rate_limiter_error` → back off 5 s ×3 then degrade to WS-only; 403 `channel_not_allowed`/`bookmaker_not_allowed`/`sport_not_allowed` → entitlement change: disable job, page; 400 `invalid_filters` → programming error, fail loudly; silent `[]` on entitled in-season sport → alarm `[OP §10.6]` ✅ retry/limiter; ⬜ classification + paging |

### 4.3 OpticOdds SSE (`u3-oo-sse`)

| Aspect | Spec |
|---|---|
| Protocol | `GET /stream/odds/{sport}?key=&sportsbook×≤5&league×≤10&include_fixture_updates=true`, `/stream/results/{sport}`, `/stream/futures/{sport}`, `/stream/prediction-markets?category=`; events `connected`, `ping` (~5 s, server time), `odds`, `locked-odds`, `fixture-status`, `fixture-results`, `futures`/`locked-futures`, `snapshot`; payload `{data:[…], entry_id:"<ms>-<seq>"}` `[OO-sum oo-odds-stream][CODE providers/opticodds/sse.py]` ✅ |
| Subscription plan | per sport × book-group (≤ 5 books): group A `pinnacle, draftkings, fanduel, betmgm, caesars`; group B `kalshi, polymarket, novig, prophet_x, betfair_exchange`; group C `circa_sports, betonline, bookmaker, betrivers, prizepicks`; group D (props/DFS) `underdog_fantasy_2_pick_, prizepicks_5_or_6_pick_flex_, draftkings_pick_6_, fliff, sleeper`; `league=` limited to the universe; results stream one per in-season sport; PM stream `politics` only by default. Budget: ≈ 25 connections; reconnect storms bounded by the 250/15 s connect limit ✅ `[CODE OpticOddsSSE.limiter]`. 🔶 today: one 5-book connection per sport, no `league=` filter (soccer all leagues = 1,544 rec/s `[OO-probe #6]`) → ⬜ book-groups + league filter |
| Resume/replay | **`last_entry_id` replay does not work** (4 tests, all restarted at "now") `[OO-probe #7]`; `entry_id` can be out-of-order/duplicated on soccer → dedupe on odd `id` + `timestamp`; on every reconnect emit a `ReconnectMarker` ✅ and ⬜ re-hydrate affected fixtures via REST `/fixtures/odds?fixture_id×5&sportsbook×5` for fixtures active in the last 10 min (standard tier) |
| Backfill | `/fixtures/odds/historical?fixture_id&sportsbook×5&include_timeseries=true` (change-level, 57–60 d) for CLV/OLV research on traded leagues; ≤ 50/15 s `[OO-probe #4]` ⬜ |
| Raw archival | every event incl. `ping` (for clock offset; +0.7 s local-vs-server observed `[OO-sum probe]`) and reconnect markers → `raw/opticodds/sse-odds-{sport}/…` ✅ |
| Normalization | `OpticOddsNormalizer.quotes_from_sse` (`locked-odds` → `event_kind='lock'`, `active=False`), `order_book` → levels (`side='back'`), `source_ids.market_id` as `venue_market_id` ✅; ⬜ `fixture-status` → `u3.fixture_status`; ⬜ `limits.max` vs `limits.max_stake` both accepted; ⬜ `exclude_fees` toggle stored in `extra.fee_adjusted` |
| Sinks | raw; coalesced ClickHouse; PM snapshots → `u3.pm_book_snapshots` ⬜ |
| Observability | events/s per connection, `recv − timestamp` p50/p99 (baseline 7 ms baseball / 32 ms soccer, p99 0.2–0.33 s `[OO-probe #6]`), reconnects, dup/out-of-order ids, `locked-odds` rate per book, ping gap ⬜ |
| Failure modes | idle > 20 s → reconnect with backoff (1→32 s) ✅; HTTP 429 → wait ≥ 15 s; ≥ 5 reconnects/min on one stream → alert; stream with 0 events for 10 min during a live slate → alert; PM category invalid → 4xx with the valid list `[OO-sum oo-prediction-markets]` |

### 4.4 OpticOdds REST (`u3-batch`)

| Aspect | Spec |
|---|---|
| Protocol | `X-Api-Key` header; standard 8,000/15 s observed (docs 2,500), historical 50/15 s (docs 10) — limiters keep the documented figures as defaults `[OO-probe #2][CODE providers/opticodds/rest.py]` ✅ |
| Poll plan | `/fixtures/active?league` every 5 min (registry); `/fixtures/odds` only for re-hydration and T−60 s freeze; `/futures/odds?league&sportsbook×5` every 15 min; `/injuries?league` every 60 s (diff); `/sportsbooks/last-polled?league` every 60 s; `/grader/odds` and `/fixtures/results` after completion; `/fixtures/player-results` nightly; `/prediction-markets/canonical-events/ids?category` + `/canonical-events?canonical_id×≤25` hourly; `/parlay/odds` on demand (Phase 2 SGP fair value) `[OO-sum oo-core, oo-results-a]` 🔶 |
| Resume/replay | idempotent; `updated_since` returned 0 rows in tests — do not rely on it `[OO-probe #11]` |
| Raw archival | all bodies ✅/⬜ as above; **`/fixtures/results/queue/status` output is secret (echoes the API key in `queue_name`)** — never archive unredacted `[OO-probe #11]` |
| Normalization | `quotes_from_fixture_rows` ✅; grader/results → `u3.settlements` (provider `opticodds`), `market_stats` → `u3.fixture_stats` ⬜ |
| Failure modes | 400 validation bodies (e.g. > 5 ids, league-wide `/fixtures/odds`) are programming errors; unknown sportsbook ids are silently ignored → validate against `/sportsbooks` at bootstrap `[OO-probe #8]` ⬜ |

### 4.5 SharpSports REST (`u3-ss-poll` + `u3-batch`)

| Aspect | Spec |
|---|---|
| Protocol | `https://api.sharpsports.io/v1`, `Authorization: Token <private key>` for `/events`, `/prices`, historic; 50 rps general, 20 rps large-list; 429 `{"detail":"Request was throttled."}` `[SS §1.2–1.3]` ✅ `[CODE providers/sharpsports/rest.py]` |
| Poll plan | **redesign**: today `/prices?league=` for every universe league every 30 s (17.5 MB, 2–7 s per call `[SS §1.6]`) 🔶 → ⬜ (a) `/prices?league&book=pp,ud` every 120 s (DFS lines, 3.8 MB); (b) `/prices?eventId=<id>` for fixtures inside T−2 h…T+4 h every 60 s (1.7 MB, 0.28 s); (c) `/prices?league&book=pn` every 300 s as a Pinnacle cross-check; `/events?league&startTimeStart/End` every 10 min; `/injuries?league` every 5 min; `/books`, `/markets`, `/segments`, `/metrics` daily; never `/marketSelections?league=` (20–32 s) `[SS §1.6]` |
| Resume/replay | stateless snapshots; `recv_ns` is the only timestamp (`/prices` carries none `[SS §3.6]`) |
| Backfill | `historicData` batch: `/players/{id}/historicData` for rostered players of traded leagues (nightly), `/marketSelections/{id}/metadata` for tonight's prop selections (T−3 h), `/prices/historic/summary?eventId` + `/timeseries` for yesterday's events (paged `pageSize=100`; summary calls 1–13 s) `[SS §1.6, §2.1]` ⬜ |
| Raw archival | ✅ `raw/sharpsports/prices-poll/…`; ⬜ per-job streams |
| Normalization | `SharpSportsNormalizer.quotes` (American → decimal, `main`, `live`, `impliedProbability`, `market_selection_id` in `extra`) ✅; ⬜ historic OHLC → `u3.quotes` (`event_kind='ohlc'`) ; player logs → BQ |
| Observability | bytes and latency per call (binding constraint), events count per league vs OpticOdds (join coverage), 429 count ⬜ |
| Failure modes | 403 "private API key is required" → key mix-up; bare-string 400 (`"Invalid league"`) and HTML 404 bodies → parse defensively `[SS §1.5]`; league filters are case-sensitive on `/markets`, `/teams`, `/players` (use `LGUE_*`) `[SS §2.2]`; empty `[]` off-slate is normal |

### 4.6 Sinks

| Sink | Spec |
|---|---|
| Raw archive | `RawArchive` per (provider, stream); `{"recv_ns","provider","stream","seq","meta","body"}` lines; hourly files `<stream>-<process_start_ms>.jsonl.gz`; flush 2 s / 5,000 records ✅ `[CODE sinks/raw.py]`. ⬜ zstd, fsync on hour roll, `manifest.json` per hour (row count, sha256, min/max `recv_ns`) as the archive commit `[R1-gpt §5.3]` |
| GCS sync | `GcsArchiveSync.sync_once`: skips the current hour, uploads closed files, verifies size + crc32c, appends `.gcs_manifest.jsonl`, optional delete-after-upload; CLI `u3-ingest archive-sync --every 300` `[PR #3]` ✅ (PR). ⬜ alert if the newest object per stream is > 2 h old |
| ClickHouse | `ClickHouseSink` batched inserts (`async_insert=1`, `wait_for_async_insert=0`) ✅ `[CODE sinks/clickhouse.py]`; ⬜ native TLS 9440 with LZ4, `insert_deduplication_token = sha1(provider, stream, hour, seq_range)` so replays are idempotent `[R1-gpt §2.4]`; ⬜ coalescer in front; ⬜ TTLs: `quotes` 45 d (schema currently 400 d — lower it on Cloud), `order_book_levels` 14 d, `pm_book_snapshots` 14 d, dimensions/settlement/CLV no TTL |
| Replay → Parquet/DuckDB | `u3-ingest replay --root --since --until --out --out-format parquet|duckdb` merges files by `recv_ns`, re-registers bootstrap registries, re-normalizes `[PR #4]` ✅ (PR). ⬜ nightly job writes `gs://u3-parquet/quotes/dt=…` and `order_book_levels/dt=…` for BigQuery external tables |
| BigQuery | external tables over Parquet; marts by scheduled queries ⬜ |
| Board / Redis (Phase 2) | in-process `Board.ingest` `[PR #5]`; Redis Streams `quotes:<sport>` for detectors ⬜ |

### 4.7 Operations, secrets, deployment

- Secrets in a `.env` on the VM with mode 600, loaded by `pydantic-settings` (whitespace-stripped) `[CODE config.py]`; long-term: Secret Manager + startup fetch. Keys never logged (`OddsPapiWS` already strips `apiKey` from `login_ok` logs `[CODE cli.py]`); add a structlog processor that redacts `apiKey=`, `key=` and `Token ` patterns everywhere.
- systemd units with `Restart=always`, `RestartSec=2`, `MemoryMax=2G` per consumer; watchdog via `sd_notify` tied to "last message age < 60 s".
- CI: ruff + pytest already scaffolded; replace the placeholder workflow with `pip install -e .[dev,clickhouse,research] && pytest` and the replay benchmark (§1.5).
- Deployment: `deploy/vm.sh` (create VM, disk, static IP, firewall egress-only, IAP), `deploy/units/*.service`, `deploy/env.example`. One command to redeploy: `git pull && pip install -e . && systemctl restart 'u3-*'`.

---

## 5. Edge inventory (prioritized)

Sizing uses underwriting ranges from the briefs (they disagree by up to an order of magnitude; the ranges below are the intersection we consider credible, before taxes and account attrition) and our own data facts. "Latency budget" = quote-in to decision-out inside our process; vendor latency (≈ 0.1–0.5 s) sits on top.

| # | Edge | Mechanism | Data needs (our feeds) | Latency budget | Expected net edge / capacity | Main risks | What ingestion must provide |
|---|---|---|---|---|---|---|---|
| 1 | **Sportsbook ↔ Kalshi/Polymarket arbitrage (pregame)** | Buy YES at PM price c + fee f, back the complement at a book at decimal d; strict arb iff `c + f + 1/d < 1` `[R2-gpt §2.1]`; fire the slow (sportsbook) leg first `[R2-opus §2.2]` | PM depth + `source_ids` (OpticOdds #5), same-`outcomeId` PM quotes from OddsPapi with USD notional per rung `[OP §8.8]`, sportsbook quotes + limits (#2, #8), fee schedules, contract rule text | seconds pregame; < 500 ms for the PM leg once automated | 0.25–2 % on genuinely equivalent contracts `[R2-gpt]`; 1.5–4 % gross per gemini/opus — haircut for settlement jump risk; capacity bounded by book depth (hundreds of contracts at a price `[R2-opus §2.2]`) | Settlement-rule mismatch (NFL abandoned < 55 min settles at last price on Kalshi; ties push at books; Polymarket UMA disputes) `[R2-opus §2.2]`; partial fills; capital lock-up | exact contract mapping (canonical key + `venue_market_id`), fee-inclusive and raw prices (`exclude_fees`), depth timeline, settlement outcomes from both sides (#11) to measure realized basis |
| 2 | **Prediction-market market making (Kalshi, Polymarket, Novig)** | Quote around a reservation price `r = p_fair − λ·I` with fee/rebate-adjusted bid/ask `[R2-gpt §3.1]`; Avellaneda-Stoikov with binary terminal collapse `[R2-gem §3.2]` | Pinnacle-anchored fair value (edge #4) at ≤ 500 ms age, PM full depth and trades, own fills, fee tiers, resolution metadata | 10–50 ms internal; cancel path is the critical latency | 0.5–3 % per filled unit; the most scalable family (Kalshi $1.2 B/day record in June 2026 `[R2-opus §0]`) | Adverse selection (filled only when the reference moved), inventory concentration, resolution risk, venue/legal availability by state `[R2-opus §0]` | continuous Pinnacle/consensus stream with staleness flags (`staleOdds`, `maxDelay*`), PM book snapshots with sequence, our order/fill ledger (Phase 3) |
| 3 | **Slow-book latency arb using per-book observed delays** | Reference moves at Pinnacle/exchanges; hit the stale quote at a copier book before it reprices; retail books lag leaders by ~0.8–4.5 s per `[R2-gem §2.2]` (unverified — measure) | per-book lag distribution from `bookmakerChangedAt`/`changedAt`/`recv_ns` `[OP §7.1]`, OpticOdds `timestamp` + `/sportsbooks/last-polled` cadence, `locked-odds`, leader-follower model per market/time-to-start `[R2-gpt §1.1]` | < 100 ms internal; end-to-end 1–5 s window | 2.5–6 % per unit `[R2-gem]`, capacity near zero at retail books after limiting; pre-game steam-following is the durable subset | Account limitation is the true cost of capital `[R2-opus §2.1]`; rejected/repriced quotes have zero capacity `[R2-gpt §5.2]`; ToS on automated placement | tick ledger with three clocks, per-book acceptance telemetry (Phase 3), `u3.book_lag` view (§6.2) |
| 4 | **Pinnacle-anchored fair value → +EV on soft books and PMs** | Devig (multiplicative for tight two-ways, power/Shin for lopsided/multiway) `[R2-gpt §1.2]`, uncertainty-weighted logit consensus with copy-cluster penalties `[R2-gpt §1.3]`, then EV = p·d − 1 after fees | Pinnacle + Circa + BetOnline/Bookmaker + exchanges (#8, #2), limits as liquidity weights, freshness | seconds–minutes pregame | 1–3 % CLV on primary markets for professionals `[R2-opus §2.7]`; capacity limited by books | Fake steam/head-fakes `[R2-opus §1.4]`; devig-method dispersion (20–40 bp is noise) `[R2-gpt §1.2]` | `Board` + `fair_value` `[PR #5]` fed by coalesced quotes; per-book weights table; stored constituents per fair value (provenance, as Copilot does `[OO-sum oo-copilot-trading]`) |
| 5 | **Player props vs DFS pick'em (PrizePicks / Underdog at fixed +100)** | Pick'em legs are hidden-price parlays: PrizePicks flat leg ≈ −119 (54.34 % BE), Underdog 4-flex ≈ −107 (51.69 %), 2-pick power 3× ≈ 57.7 % `[R2-opus §2.5]`; compare devigged prop probability at the pick'em line, exploit positive correlation across legs (apps don't apply correlation matrices) | OpticOdds DFS payout-structure ids + SharpSports `pp`/`ud` +100 lines (#16), alt-line ladders (`lineAvailability`, OpticOdds alternates) to fit distributions, injuries/lineups (#14), player logs/DVP (#15) | minutes pregame; seconds around lineup news | 1–8 % per entry, very low capacity `[R2-gpt]`; tier-2 sports softer `[R2-opus §2.5]` | Payout-table changes, demotion to Flex after ~55 % win rate over 200+ entries, DNP void rules `[R2-opus §2.5]` | canonical `player:<metric>` keys across all three vendors, `player_id` crosswalk (OpticOdds ↔ SharpSports `PLYR_` via `oddsjamId` 12-hex on Player `[SS §3.8]`), line ladders stored with `is_main` |
| 6 | **CLV capture (process metric, not an edge)** | `CLV_EV = d_bet · p_close − 1` against a devigged close; like-for-like lines `[R2-gpt §5.1]` | our freeze snapshots (T−60 s/T−5 s), OddsPapi `clv`/`olv`, OpticOdds OLV/CLV, SharpSports historic summary (#12) | none | sustained +1–3 % CLV over 1,000+ bets = evidence of edge `[R2-opus §2.7]` | wrong benchmark, self-impact on close, props without sharp close | `u3.clv` with three sources side by side; `event_kind='freeze'` rows |
| 7 | **Middles / scalps** | Hold both sides across key numbers; +EV iff P(middle) × payout > carry `[R2-gpt §2.4]` | alt-line ladders per book, margin distributions from settlement history (#11, #13) | minutes–days | modest, variance-heavy, limit-bound | push-probability error | full alt-line capture (already: `is_main=false` rows) |
| 8 | **Correlated parlay / SGP mispricing** | Compare book SGP prices (dispersion of 50–100 points across books) with a joint model; OpticOdds AI SGP pricer as a reference `[R2-opus §2.6][OO-probe #10]` | `/parlay/odds` per book, prop ladders, results for joint calibration | seconds–minutes | several % when the model is right; narrow, high-attrition | books limit correlated-SGP winners | on-demand parlay pricing archived; joint-outcome results (`player-results`, `market_stats`) |
| 9 | **Promo / boost harvesting** | EV of boosts/promos after rollover on one legitimate account; run as a separate P&L with account cost amortized `[R2-opus §2.6]` | promo terms (manual), fair value (#4) | low | high ROI on promo capital, tiny capacity, self-terminating | terms changes, limiting | none beyond fair value; manual workflow |
| 10 | **Steam / line-origin detection** (research product feeding #3 and #4) | Leader–follower regression `Δp_j,t = α + Σ β_jk Δp_k,t−ℓ` by sport/market/time-to-start; steam event = leader move ≥ x ticks and ≥ m independent clusters follow within 30–90 s; fakeability index = followers ÷ limit at origin `[R2-gpt §1.4][R2-opus §1.4–1.5]` | tick ledger with limits at every tick, `bookmakerChangedAt`, news timestamps (#14) | offline | improves #3/#4 weights | public steam alerts are already-priced `[R2-gpt §1.4]` | `limit_max` on every quote row; injuries/lineups diffs with `recv_ns` |
| 11 | **In-play modeled edge** (Phase 3+) | Own real-time fair price from game state vs book lag `[R2-opus §2.4]`; on PMs only 5.2 % of live game time is tradable under depth/spread/age filters `[R2-opus §2.4]` | scores/clock/in-play (#10), live odds (#4), PM depth | sub-second | unknown until post-acceptance data exists `[R2-gpt §2]` | rejections, bet delays, voids | `u3.fixture_clock`, results stream `in_play`, quote-age filters in backtests |

**Non-goals for edges** (all phases): courtsiding/in-venue relay, multi-accounting/beards, geolocation or KYC evasion, automated placement on retail books that prohibit it. Research briefs that describe such tactics `[R2-gem §4]` are recorded as risks (§8), not plans.

---

## 6. Measurement & research loop

### 6.1 CLV pipeline
- Every candidate signal (Phase 2) and every order (Phase 3) is written to `u3.signals` / `u3.orders` with the canonical key, price taken, fair value and method used, fee estimate, and `recv_ns` of the triggering quote.
- Closing benchmarks joined per canonical key from (a) our own freeze rows (T−60 s / T−5 s, `event_kind='freeze'`), (b) OddsPapi `clv` with the fallback chain `clv → last tick ≤ trueStartTime → olv` `[OP §8.5]`, (c) OpticOdds historical OLV/CLV `[OO-probe #4]`, (d) SharpSports historic summary `last` per book. Devig the close with the same method as the signal; report CLV in probability points and EV terms; separate spreads/totals by like-for-like line with a half-point valuation model.
- Weekly report: % beating close, mean CLV by league/market/book/time-to-start, calibration curve (decile slope 1.00 ± 0.02 `[R2-gem §5.2]`), Brier score, realized vs expected P&L once trading.

### 6.2 Latency attribution
- Quote-level: `book→gateway = changedAt − bookmakerChangedAt` (≈ 360 ms Pinnacle), `gateway→emit = ts − changedAt` (≈ 100 ms), `emit→us = recv − ts` (108 ms from the sandbox) `[OP §7.1]`; OpticOdds `recv − timestamp` (p50 7–32 ms) with the `ping` clock-offset correction `[OO-probe #6]`; SharpSports `recv` only.
- Per-book lag view `u3.book_lag`: for each canonical key movement at the leader (Pinnacle/exchange), time until each follower book prints a move in the same direction; percentiles by book × league × pregame/live. This is the empirical replacement for the anecdotal "which books lag" lists `[R2-gpt §5.2]`.
- Order-level (Phase 3): `T_signal → T_receive → T_model → T_decision → T_send → T_ack → T_fill` decomposition `[R2-gpt §5.2]`.
- Existing view `u3.quote_latency` (p50/p99 of `recv − source_ts` per provider × book × minute) `[CODE schemas/clickhouse.sql]` is the day-one SLI.

### 6.3 Mapping coverage
- Nightly `mapping-report`: fixtures per league with all three ids; `opticoddsId` join rate (target ≥ 95 % MLB/NFL/EPL, ≥ 85 % NCAAF `[XJ]`); SharpSports join rate (≥ 90 % MLB); books resolved vs `unknown`; markets in `other:*` by quote volume (target < 2 % of volume); duplicate canonical fixtures (target 0); cross-provider price disagreement > 3 % lasting > 2 min (target 0 per day).

### 6.4 Data-quality SLOs (alerts in Grafana Cloud)

| SLI | Target | Source |
|---|---|---|
| Quote freshness p99 (`recv − changedAt`) per book, in-play | < `1000 × maxDelayLiveInSec` `[OP §10.7]` | `u3.quote_latency` |
| Edge transport (`recv − ts`) p99 | < 500 ms | stream_health |
| Stream liveness | last message age < 30 s per connection during a live slate | Prometheus gauge |
| Reconciliation divergence (sweep corrects stream) | < 0.1 % of keys per sweep | batch job |
| Archive completeness | every hour has a closed file per active stream and a GCS object ≤ 2 h later | `u3-sync` manifest |
| Settlement completeness | > 99 % of finished fixtures with 0 `UNDECIDED` (excl. `REQUIRES_NON_SCORE_STATS`) within 24 h `[OP §10.7]` | `u3.settlements` |
| CLV coverage | ≥ 80 % of traded keys with a non-null close from ≥ 2 sources | `u3.clv` |
| History retention watermark | oldest fixture with non-empty OddsPapi CLV ≈ 220 d; alarm if it shortens `[OP §10.7]` | weekly probe |
| Entitlement drift | `login_ok` echo and `/bookmakers` count unchanged; any 403 on a previously-working endpoint pages | batch |
| Budget | GCS growth ≤ 15 GB/day; GCP spend ≤ $100/month (billing export → BQ) | billing export |

### 6.5 Research loop
- Weekly: replay the last 7 days to Parquet (`u3-ingest replay`) → BigQuery; notebooks for CLV, book lag, steam detection, PM basis; results feed `weights.yaml` (book weights per league/market/time bucket) consumed by the fair-value engine.
- Monthly: re-run the mapping and entitlement probes (`tools/research/cross_join.py`, probe scripts) and diff against the specs; update `docs/research/*.md`.

---

## 7. Phased roadmap

### Phase 0 — Ingestion MVP (done, this week)
Delivered: provider clients with rate limiters and retries; OpticOdds SSE and OddsPapi WS clients (zstd/msgpack decode, resume cursors, control-frame handling); SharpSports client; canonical model, market/selection keys, book and fixture registries; normalizers for all three; raw archive; ClickHouse sink and schema (`u3.quotes`, `u3.order_book_levels`, `u3.fixture_xref`, `quotes_latest` MV, `quote_latency` view); `u3-ingest archive|snapshot|run` CLI; tests (SSE parser, limiter, archive round-trip, WS resume/snapshot_required, normalizers, registry joins); research tooling and specs; 75 s live verification `[CODE]`. Open PRs: GCS sync `[PR #3]`, replay to Parquet/DuckDB `[PR #4]`, pricing library `[PR #5]`.

### Phase 1 — Cloud deployment + resilience + warehouse (weeks 2–4)
Deliverables:
1. Merge PRs #3–#5 (review: PR #3 reads whole files into memory for crc32c — stream it; PR #4 `write_duckdb` uses `executemany` — batch via Arrow; PR #5 `Board` keys on `line` including `None` — fine).
2. VM + systemd deployment (`deploy/`), 24 h RTT probe `us-east4` vs `us-east1` to OddsPapi/OpticOdds/Kalshi endpoints `[R1-gpt §4]`, region decision recorded.
3. OddsPapi: three-connection plan, `zstd-dict` default, cursor persistence, automatic `snapshot_required`/`reconnect` handling with REST re-baseline, `/fixtures/odds/main?since` sweep every 60 s, `/bookmakers` 60 s health, `login_ok` echo assertions; remove `novig` from the OddsPapi filter.
4. OpticOdds: book-group × league-filtered SSE plan, REST re-hydration on reconnect, `fixture-status` capture, PM `politics` stream + hourly canonical-events REST, futures poll, injuries diff-poll, last-polled poll.
5. SharpSports: targeted polling redesign (§4.5), nightly historicData batch for traded leagues.
6. Coalescer + volume caps (§1.4); zstd raw codec; hourly manifests; GCS lifecycle; archive-completeness alert.
7. Settlement, CLV, freeze-snapshot workers; `u3.settlements`, `u3.clv`, `u3.book_status`, `u3.fixture_scores`, `u3.fixture_clock`, `u3.injuries`, `u3.stream_health`, `u3.mapping_unresolved` tables; TTLs set.
8. Backfills: OddsPapi spine (400 d), settlement (≥ 1 y for MLB/NFL/NBA/NHL/EPL), CLV (220 d), Pinnacle ticks for MLB + NFL; OpticOdds OLV/CLV for the same; SharpSports player logs.
9. Observability: Prometheus exporter in every process (`metrics_port` exists in settings but is unused `[CODE config.py]`), Grafana Cloud dashboards + the §6.4 alerts; structlog redaction processor.
10. Warehouse: nightly replay → Parquet → BigQuery external tables; marts `dim_fixture`, `dim_book`, `settlement`, `clv`, `player_game_log`; billing export.
11. ClickHouse Cloud trial started at the beginning of month 2 with DDL + loader scripts; self-hosted fallback tested first.
12. Security: rotate the OpticOdds key (probe outputs echoed it), revoke the Perplexity key that was pasted in chat, confirm SharpSports key pair, document rotation runbook (§8).
Exit criteria: 7 consecutive days with all §6.4 SLOs green; benchmark gate (§1.5) passing in CI; mapping coverage targets met for MLB and EPL (in season) and NFL (from week 1 of the season).

### Phase 2 — Fair value + edge detection + alerting (weeks 5–8)
Deliverables: `u3-board` service (Redis Streams consumer) holding the latest state per canonical key with staleness gating (`staleOdds`, `maxDelay*`, quote age); fair-value engine on `[PR #5]` (per-league/market devig method from backtests, weights from `weights.yaml`, copy-cluster penalty, stored constituents); detectors for edges #1 (fee- and settlement-aware PM basis), #4 (+EV vs consensus), #5 (DFS pick'em screen with correlation flags), #3 (stale-quote candidates using `u3.book_lag`); fee-schedule table versioned in repo (Kalshi `0.07·C·p(1−p)`, Polymarket sports curve and rebate share, Polymarket US 0.30 %/0.20 %, Novig live `0.03·C·p(1−p)`, ProphetX 1 % `[R2-opus §2.2]` — refreshed from live venue objects, never hard-coded in code paths); settlement-rule registry per venue/sport (OT, abandonment, ties, DNP) with a mismatch score per pair; Slack alerting with dedup and quiet hours; `u3.signals` ledger; paper-trading P&L with CLV; weekly research report. Exit: 4 weeks of signals with measured CLV and hit rates by edge family; go/no-go per family.

### Phase 3 — Execution + risk (weeks 9–12+)
Deliverables: Kalshi and Polymarket execution adapters (native APIs; RSA-PSS / L2 HMAC auth `[R3-gem §4]`) behind a common order interface; order/fill ledger with the seven-timestamp decomposition; risk engine (per-market, per-event, per-venue and correlated exposure caps; max quote age; cancel-backlog limit; kill switch on `staleOdds`, settlement disputes, venue/legal state changes); market-making pilot on Kalshi in 1–2 liquid leagues at minimal size; sportsbook legs via deep links (`deep_link` on OpticOdds odds, SharpSports betPlace) as a human-click workflow, not automated placement; optional SOAX-based validation of retail quote acceptance (read-only). Exit: realized P&L, fill rates and latency attribution reported for 4 weeks; decision on scaling capital.

### Explicit non-goals (all phases)
Kafka/PubSub, Kubernetes, multi-region HA, a Rust/Go rewrite before the gate fails, OpticOdds Copilot (not licensed `[OO-probe #10]`), OddsPapi/55-tech ABP automated bet placing on retail books `[R3-gem §5]`, non-sport PM trading before Phase 3, any account-evasion tooling.

---

## 8. Risks & mitigations

| Risk | Evidence | Mitigation |
|---|---|---|
| Vendor ToS / licensing: data redistribution, automated betting | OpticOdds enterprise licence; OddsPapi positioned as data-only with ABP separate; SharpSports betPlace is deep-link only `[R3-gem §5][R3-pplx §5]`; Swish v. OddsJam/OpticOdds litigation over scraped book data `[R3-gem §5]` | No redistribution of feeds; execution only on venues whose terms permit API trading (Kalshi, Polymarket); retail legs by human click; keep contracts and indemnification questions in §9 |
| Trial-credit cliffs | ClickHouse 30 d, Snowflake 30 d, GCP 90 d `[R1-gpt §1.1, §2.1, §3.1]` | Raw archive is provider-independent; ClickHouse DDL + loaders scripted; self-hosted ClickHouse tested before the trial; budget alerts at 70/90 % |
| Data volume blow-up | Polymarket 81–87 % of odds messages; soccer all-leagues 1,544 rec/s; DK 433k ticks/game `[OO-probe #6][OP §5.2]` | §1.4 caps; budget kill-switches (§1.3); coalescing is measured (`coalesced_rows_total`) |
| Vendor outage or per-book feed loss | OpticOdds latency incidents on its status page `[R3-pplx §1]`; OddsPapi `staleOdds`, `reconnect` releases `[OP §4.5]`; Kalshi 30-minute stale poll observed `[OO-probe #5]` | Dual-vendor coverage for the six common books; `staleOdds`/`last-polled` gating; hard stops in the board; alerts on liveness |
| Replay/resume limitations | OpticOdds `last_entry_id` replay does not work `[OO-probe #7]`; OddsPapi `odds` may not be replayable, 60 s window `[OP §4.6]` | REST re-baseline on every reconnect; reconciliation sweeps; our own archive is the ledger |
| Key exposure & rotation | `/fixtures/results/queue/status` echoes the raw OpticOdds key `[OO-probe #11]`; OddsPapi key travels in URLs `[OP §9.3]`; a Perplexity key was pasted in chat | Rotate OpticOdds key now and after every probe session that touched the queue endpoint; treat that endpoint's output as secret; redaction processor; revoke the Perplexity key; quarterly rotation runbook (`.env` swap + `systemctl restart`) with dual-key overlap where vendors allow |
| Entitlement drift | OddsPapi 403s are precise but `[]`/silent drops also occur `[OP §1.6, §9.2]`; OpticOdds unknown sportsbook ids silently ignored `[OO-probe #8]` | Assert echoes and counts; 403 on a previously-working endpoint pages |
| Schema drift | OddsPapi breaking changes ~quarterly; 5 undocumented `Bookmaker` fields `[OP §9.3]`; OpticOdds `limits.max` vs `max_stake` `[OO-sum oo-odds-stream]` | Raw-first archive; lenient parsers; unknown-key counters; contract tests on live samples |
| Mapping errors → false arbs | name mismatches (OpticOdds "Ipswich Town FC" vs OddsPapi "Ipswich Town") `[XJ]`; `participantsRotated` | Exact-id joins first; cross-provider price sanity alert (§3); manual override file |
| Settlement mismatch | Kalshi last-price settlement on abandoned games, ties, DNP; OpticOdds grader deviates from house rules (tennis retirement, soccer sub goalscorer) `[R2-opus §2.2][OO-sum oo-results-b]` | Settlement-rule registry with mismatch score; haircut EV by jump risk; store both vendors' grades |
| Stale quotes traded | quotes 5–14 h old are returned as-is by OpticOdds REST `[OO-probe entitlements]`; SharpSports has no timestamps `[SS §3.6]` | Quote-age gating everywhere; SharpSports never used for pricing decisions |
| Account limits / capacity | soft-book capacity is operator-controlled and perishable `[R2-gpt §4]` | Prioritize PM/exchange edges; treat soft-book edges as capped side lines |
| Legal/regulatory volatility of PMs | Third vs Ninth Circuit split, state injunctions `[R2-opus §0]`; Sporttrade reportedly exited US sports betting June 2026 `[R2-gpt §2.2]` while both data vendors still list it | Venue availability as a risk input; no dependence on a single venue; confirm Sporttrade status before modelling it as executable |
| Small team / bus factor | two people | One VM, one language, one CLI; runbooks in `docs/runbooks/` (Phase 1); everything rebuildable from GCS |

---

## 9. Open questions for vendors

**OddsPapi (contact@55-tech.com)** `[OP §9.4]`
1. Region binding: is `oddspapi-us1` fixed for our key; regional hostnames; recommended GCP region.
2. `resumeWindowMs` on our key and whether `odds` ever appears in `replayChannels`.
3. Header-based REST auth to keep keys out of URLs.
4. Units/types of `staleThresholdSec`, `lastOddsAt`, `staleOddsSince`, `availableSports`; semantics of login `live`/`pregame`, envelope `v`/`seq`, `resume.serverCursors`.
5. Hard cap on `/fixtures/odds/main?tournamentId` (100 fixtures?) and max ids per `fixtureIds`/`oddsIds`.
6. Settlement latency after `trueEndTime`; are grade transitions pushed on any channel; plans for player-prop settlement.
7. Commercial: sports 16–81, prediction-market topics 69–78, `futures/odds*`, > 5 bookmakers per query, > 5 WS connections; SLA and status-page subscription.

**OpticOdds** `[OO-sum open questions]`
1. `last_entry_id` replay: documented but non-functional on our key — expected behaviour and retention window; `entry_id` monotonicity on soccer.
2. Are the observed 8,000/15 s standard and 50/15 s historical limits contractual; any per-key concurrent SSE connection cap beyond 250 connects/15 s.
3. Which `limits` key (`max` vs `max_stake`) is emitted on streams; are stream prices fee-adjusted by default for exchanges; `exclude_fees` on the PM stream.
4. PM stream: Polymarket id form (numeric vs condition id + clobTokenIds) for CLOB routing; when `entry_id`/`canonical_id` are populated; Kalshi `timestamp_ns` quality.
5. Historical: retention of `include_timeseries` (57–60 d observed) and OLV/CLV; CLV population timing.
6. Security: `/fixtures/results/queue/status` echoes the API key — fix and confirm rotation procedure.
7. Coverage: Kalshi NFL/EPL game markets, Novig/ProphetX/Sporttrade status and poll cadence (prophet_x 2.5 h stale observed); RotoWire add-on terms; Copilot pricing (not required).

**SharpSports**
1. Any timestamp or version on `/prices` prices; backend refresh cadence per book; live-mode latency claims (sub-100 ms) vs observed 2–7 s league calls.
2. Authoritative rate limits for `/prices` (100 vs 50 rps) and `/marketSelections` (50 vs 20).
3. `oddsjamId` format guarantee and equivalence to OpticOdds v3 `game_id` (37/40 MLB matched; NFL uses `teamA-teamB-YY-WW`).
4. Performance of `/prices/historic/summary` by player/team (13–98 s, timeouts) and `/marketSelections?league=` (20–32 s); retention depth of OHLC.
5. Confirm book abbrs (`pm` Polymarket, `hr`, `st`, `fl`, `fn`, …) and `oddsFeedActive` list; Sporttrade status.
6. betSync: access to population-level flow statistics (not only our linked bettors); terms for research use.

**Venues (for Phase 3)**: Kalshi API tier and PrivateLink availability; Polymarket US vs international access and fee flags; Novig/ProphetX market-maker API programmes.

---

## 10. Decision log

| # | Decision | Alternatives considered | Why |
|---|---|---|---|
| 1 | **Python asyncio (uvloop, orjson) for the hot path through Phase 2, with a benchmark gate** | Go service (recommended by `[R1-gpt §5.1][R1-pplx §5]`), Rust, Python for adapters only | The prototype already exceeds the stated 5–20k rows/s range end-to-end in this sandbox `[CODE README]`; two-person team; vendor latency (0.1–0.5 s) dominates in-process time; the gate (§1.5) protects the decision and confines any rewrite to the decode stage |
| 2 | **OddsPapi WS as primary real-time sportsbook feed; OpticOdds SSE as breadth/PM/DFS/futures/results primary and cross-check** | OpticOdds SSE as primary; either alone | OddsPapi: 31 books in one connection, resume cursors, zstd-dict (7–9× smaller), three timestamps per quote, per-side limits, frozen ids across books, `staleOdds` gating `[OP §4, §7, §8]`; OpticOdds: 229 books incl. DFS payout ids and exchanges with `order_book`/`source_ids`, non-sport PMs, grader/results, but no working replay `[OO-probe #7]` and 5 books per stream. Both are archived; the six common books give a continuous cross-check |
| 3 | **Raw archive first; ClickHouse/BigQuery derived** | Normalize-first with raw sampling | Vendors change shapes quarterly `[OP §9.3]`; OddsPapi history evaporates at ~220 d `[OP §5.2]`, OpticOdds timeseries at ~60 d `[OO-probe #4]`; replay exists `[PR #4]`; "GCS is the source of truth; ClickHouse is rebuildable" `[R1-gpt §5.3]` |
| 4 | **ClickHouse = hot tick store/board mirror; BigQuery = research warehouse; Snowflake = optional sprint** | Snowflake as main warehouse; ClickHouse for everything; BigQuery streaming | Credit fit: BigQuery shares the GCP $300 and has a permanent free tier; ClickHouse Cloud is ~$186/mo after its 30-day trial `[R1-gpt §2.1, §3]`; Snowflake has no free tier and is unreachable from this sandbox; tick queries want ClickHouse, stats joins want a warehouse |
| 5 | **Single on-demand GCE VM (`e2-standard-2`), no Cloud Run/GKE/NAT** | Cloud Run min-instances; GKE Autopilot; Spot primary | Long-lived sockets, fixed IP, local spool, predictable cost; Cloud Run WebSockets are timeout-bound requests; NAT bills per GiB `[R1-gpt §1.3–1.4]`; Spot preemption on the only consumer is unacceptable |
| 6 | **Region `us-east4` for the collector (confirm with a 24 h RTT probe; `us-east1` if ClickHouse PSC/egress matters more)** | `us-central1` (ClickHouse region) | OddsPapi serves us from `oddspapi-us1` with Cloudflare `-IAD` `[OP §7.3]`; Kalshi is AWS us-east `[R1-pplx §4]`; ClickHouse Cloud has no `us-east4` `[R1-gpt §2.3]` → egress budget in §1.3 |
| 7 | **Coalesce before ClickHouse; archive everything** | Insert every tick; sample the archive | 81–87 % Polymarket churn and DK re-confirmations `[OO-probe #6][OP §5.2]`; egress and storage budgets; research needs the raw ledger, trading needs the latest state |
| 8 | **Canonical fixture id = OpticOdds id; join OddsPapi via `opticoddsId`, SharpSports via `oddsjamId`, then team+time** | OddsPapi id as canonical; Betradar id | OpticOdds id is present on both other vendors' records (`opticoddsId` `[OP §6.1]`, `oddsjamId == game_id` `[XJ]`); reverse mapping through OddsPapi is not entitled (`bookmaker=opticodds` → 403 `[OP §9.1]`) |
| 9 | **Canonical quote identity `(book, fixture, market, period, selection, line)` with provider ids retained** | Provider-native ids only | Enables cross-provider comparison and dedup; OddsPapi's frozen `outcomeId` and OpticOdds `grouping_key` are kept in `provider_odd_id`/`grouping_key` for exact grouping `[CODE canonical/models.py]` |
| 10 | **SharpSports for stats/historic/DFS lines only, never for real-time pricing** | Use `/prices` as a third real-time source | No timestamps on prices `[SS §3.6]`; 2–7 s league payloads `[SS §1.6]`; but unique game logs, DVP, park factors, injuries with `played`, OHLC, `consensusProjection` `[SS §3.10]` |
| 11 | **Three clocks on every quote row** | Receive time only | Latency attribution and per-book lag are core research products `[OP §7.1][R2-gpt §5.2]` |
| 12 | **In-process board in Phase 1; Redis Streams IPC in Phase 2; no Kafka/PubSub** | Kafka, Pub/Sub, ZeroMQ | One VM, one team; Redis gives replayable streams and a last-state cache at zero cost; Kafka adds ops without benefit at this scale |
| 13 | **Fee schedules and settlement rules as versioned data, refreshed from venues** | Hard-coded constants | Fees changed in 2026 (Polymarket sports rate and rebate share) `[R2-opus §2.2]`; settlement discretion is the dominant PM arb risk |
| 14 | **No direct sportsbook scraping in step one; SOAX reserved for Phase 3 validation** | Scrape books for latency ground truth now | Brief scope; ToS/CFAA exposure `[R3-gem §5]`; vendor feeds already give per-book timestamps |
| 15 | **Secrets: `.env` (600) now, Secret Manager later; rotate OpticOdds key after probes; redact keys in all logs** | Leave as is | Queue-status endpoint echoes the key `[OO-probe #11]`; OddsPapi key in URLs `[OP §9.3]`; Perplexity key exposure |
| 16 | **ClickHouse Cloud trial consumed in month 2, self-hosted single node before/after** | Start the trial immediately | Month 1 is deployment and volume-cap work; the trial should cover a full in-season month with the caps in place; a 30-day trial cannot span 90 days `[R1-gpt §2.1]` |
| 17 | **Edge priority: PM arbitrage and market making first, soft-book edges as capped side lines** | Latency arb and promos first (highest per-unit ROI) | Structural edges scale and are not account-mortal; soft-book edges self-terminate `[R2-opus §0, §2.1][R2-gpt §4]` |
| 18 | **Prediction-market non-sport streams limited to one category by default** | All categories | 933 snapshots/s and 120 MB/45 s for politics alone `[OO-probe #6]`; no execution venue for non-sport markets in Phases 1–2 |
