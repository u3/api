> **Status: partial draft (Opus 5, cut at the output cap). A continuation pass is queued and will replace this note.**

# SharpSports — Definitive Engineering Spec (Ingestion Reference)

> Scope: everything our platform needs to ingest SharpSports: betPrices (live odds), historicData (OHLC line history + player/team stats + injuries + trends), betSync (linked-account bet flow), and the reference/taxonomy endpoints used for cross-provider mapping.
> Sources: full docs mirror (docs.sharpsports.io, all reference/docs/changelog pages incl. the U+FE0F-slug pages) + a live probe against our trial key set (two keys: a **public** key and a **private** key, env `SHARPSPORTS_API_KEY` and `SHARPSPORTS_API_SECRET`).
> Everything marked **[PROBE]** is observed behavior from the live run; **[DOC]** is documentation language; **[UNVERIFIED]** means neither confirmed nor contradicted.

---

## 1. Product & access summary

### 1.1 What SharpSports is (four products, one API surface)

| Product | What it gives us | Our entitlement (probe) |
|---|---|---|
| **betPrices** | Current odds from ~15 active books incl. Pinnacle, Kalshi, Polymarket(?), PrizePicks, Underdog, via `GET /prices`, `GET /marketSelections` (with per-book price ladders), `GET /marketOffers` | ✅ **Entitled** (private key). `/prices?league=MLB` returned 146 events / 17.5 MB. |
| **historicData** | OHLC line timeseries + per-book first/last/high/low summaries (`/prices/historic/*`), player/team game logs & aggregate stats, injuries, trends | ✅ **Entitled** (private key). All `/prices/historic/*`, `/players/{id}/historicData`, `/injuries`, `/marketSelections/{id}/metadata` returned 200. `/trends` returns `[]` (empty, see §9). |
| **betSync** | Linked bettor accounts, bet slips, refresh lifecycle, webhooks | ✅ **Entitled** (private key). `GET /betSlips` → 5 slips; `GET /bettors` → 3 bettors; `GET /bettorAccounts` → 5 accounts. Sandbox-style data. |
| **betPlace** | Deep links / betslip creation; also gates `bookIds` + `betPlaceLinks` on Price and `betPlaceAvailability`/`betPlaceUrls` on MarketSelection | ✅ **Partially observable**: `betPlaceAvailability` and `betPlaceUrls` ARE serialized on live MarketSelections **[PROBE]**. Whether `bookIds`/`betPlaceLinks` appear inside `/prices` must be re-checked per-sample (raw bodies contain them per doc gating; treat as present-if-key-exists). |
| **betContent / Pine AI** | AI articles, whitelabel chat | Not probed; `/articles` requires `league`+`dateCreated`; Pine provisioning is 403 for sandbox accounts **[DOC]**. |

### 1.2 Base URL, auth, key model

```
Base URL (sandbox AND live, identical):  https://api.sharpsports.io/v1
Auth header:                             Authorization: Token <key>
Content-Type (writes):                   application/json
```

* **Mode is selected by which key you send**, not by host. **[DOC]** Live mode requires a paid plan and gives you a *separate* pair of keys.
* **Two key kinds** and they are NOT interchangeable:
  * **Public API key** — reference/entity endpoints and client-side flows (`/books`, `/bookRegions`, `/sports`, `/leagues`, `/teams`, `/players`, `/segments`, `/metrics`, `/markets`, `/trades`, `POST /context*`, `POST .../refresh`, `PUT .../paused`, `PUT .../access`).
  * **Private API key** — everything price/odds/bet/historic related (`/events`, `/marketSelections`, `/marketOffers`, `/prices`, `/prices/historic/*`, `/injuries`, `/trends`, `/betSlips`, `/bettors`, `/players/{id}/historicData`, `/hooks/logs`, `POST /{platform}/auth`, Pine provisioning).
* **[PROBE] Observed enforcement is strict.** With the public key, 31 requests returned `403 {"detail":"Your private API key is required for this endpoint"}` — every `/events*`, `/prices*`, `/prices/historic/*`, `/marketSelections*`, `/injuries`, `/trends`, `/bettors`, `/players/{id}/historicData`. `/betSlips` with the public key returned a different message: `403 {"detail":"You do not have permission to perform this action."}`.
* **[PROBE] Interesting asymmetries with the public key** (these worked with the *public* key): `/books`, `/bookRegions`, `/sports`, `/leagues`, `/markets`, `/markets/{id}`, `/segments`, `/metrics`, `/teams`, `/teams/{id}`, `/teams/aggregateStats`, `/players`, `/players/{id}`, `/players/aggregateStats`, `/players/{id}/aggregateStats`, `/trades/{TEAM_}`, **and `/bettorAccounts`** (returned 5 accounts with the public key — the "product-required BetSync" banner is not enforced there).
* **[PROBE] Bearer auth does not work.** `Authorization: Bearer <key>` → 34-byte error body. Always use the literal `Token ` prefix.
* **[PROBE] No auth** → `{"detail": ...}` 58-byte error.
* **Key string formats** seen in docs: `public_sandbox_XXXXXXXXX`, `sk_test_…`, `sk_live_…`, and a 40-hex public key in the iOS SDK example. Do not parse keys; treat as opaque. **Never log the key** — redact to `***`.
* **Server**: `nginx/1.31.5` on all responses **[PROBE]**. No rate-limit headers of any kind observed (no `X-RateLimit-*`, no `Retry-After`).

### 1.3 Rate limits (exact numbers, all sources)

| Tier | Limit | Endpoints | Source |
|---|---|---|---|
| **General** | **50 requests/second** | "Unless otherwise specified in the other Rate Limiting sections, all endpoints" | `reference/general-rate-limiting` **[DOC]** |
| **Large List** | **20 requests/second** | `GET /betSlips`, `GET /bettorAccounts/{id}/betSlips`, `GET /bettors/{id}/betSlips`, **`GET /marketSelections`**, **`GET /bookRegions`** | `reference/large-list-rate-limiting` **[DOC]** |
| **Per-endpoint banner** | **50 requests/second** "due to real-time data intensity" | `GET /marketSelections`, `GET /bookRegions`, `GET /betSlips` | endpoint pages **[DOC]** — contradicts the 20 rps large-list page |
| **Marketing claim** | **100 requests/second with private key**, "Unlimited daily requests", "No additional charges for high volume" | betPrices quickstart, historicData quickstart **[DOC]** |
| **Refresh (betSync only)** | **1 request / 60 s per bettorAccount**; also 429 while `refreshInProgress`; a refresh "can take up to 2 minutes" | `reference/refresh-rate-limiting` **[DOC]** |

**429 body (exact):** `{"detail":"Request was throttled."}` **[DOC]**. Not observed in the probe (we never hit it), so **[UNVERIFIED]** whether a `Retry-After` header accompanies it.

**Implementation decision:** run a per-endpoint-class token bucket at the conservative documented figure:
* `/marketSelections`, `/bookRegions`, `/betSlips*` → **20 rps**
* everything else → **50 rps**
* refresh → **1 / 60 s / BACT_**

This is bandwidth-irrelevant anyway: `/prices` payloads are enormous (see §1.6) and single-request latency is the binding constraint, not RPS.

### 1.4 Pagination — two mutually exclusive response shapes ⚠️

This is the single most important structural gotcha. **[PROBE]**

| Request style | Response shape |
|---|---|
| No `pageSize`/`pageNum` (optionally `limit=N`) | **bare JSON array**: `[ {...}, {...} ]` |
| With **both** `pageSize` AND `pageNum` | **envelope object**: `{"objects": [ ... ], "totalPages": N}` |

Confirmed on: `/markets`, `/players`, `/events`, `/marketSelections`, `/injuries`.

Exceptions / variants:
* `/prices?eventId=` → **object** `{"eventId": ..., "markets": [...]}` (single event).
* `/prices?league=` or `?sport=` → **array** of `{"eventId","markets"}` objects.
* `/prices/historic/summary` and `/prices/historic/timeseries` → **object** `{"marketSelections": [...]}`; **with pagination** → `{"marketSelections": [...], "totalPages": N}` (note: NOT `objects`).
* `/players/{id}/historicData` → always a **bare array**; pagination params are silently ignored **[PROBE]** (`?pageSize=10&pageNum=1` returned the full 49-element array, identical 141019 B).

Rules:
* `pageNum` is **1-based** and **"must be used with pageSize"**. **[PROBE] Confirmed hard error:** `/prices/historic/summary?...&pageSize=100` (without pageNum) → `400 {"detail":"[ErrorDetail(string='Both pageNum and pageSize required for pagination', code='invalid')]"}`.
* `limit` is a **post-filter cap**, not a page size. `limit` defaults: `/events` 500, `/marketSelections` 500, `/marketOffers` 500, `/refreshResponses` 500, `/hooks/logs` 500 (param literally spelled **`limt`**), `/betSlips` 50.
* **[PROBE] `limit` can exceed 500**: `/events?...&limit=1000` returned **806** items; the same query without `limit` returned exactly **500**. So the implicit default cap is 500 and `limit` raises it.
* **[PROBE] `pageSize=1000` works**: `/markets?pageSize=1000&pageNum=1` → 1000 objects + `totalPages`.
* **[PROBE] Out-of-range page is not an error**: `/markets?pageSize=5&pageNum=99` → 200 with 5 objects (i.e. it clamps/wraps — do **not** rely on empty-page termination; use `totalPages`).
* No cursor/next-token anywhere. No total-count field except `totalPages`.

### 1.5 Error formats (all observed variants)

| Shape | Example | When |
|---|---|---|
| `{"detail": "<string>"}` | `{"detail":"Your private API key is required for this endpoint"}` (403) | auth/permission, throttling, business-rule limits |
| `{"detail": "<string>"}` | `{"detail":"Query would generate approximately 1440 windows, which exceeds the maximum allowed of 1000. Please use a larger rollup interval or smaller time range."}` (400) | timeseries window cap |
| `{"detail": "<string>"}` | `{"detail":"Query would return more than 2000 market selections. Please narrow the filter (e.g. tighter eventStartTime range, a more specific player/team, or set type/proposition), or split the request into multiple narrower queries."}` (400) | historic summary cardinality cap |
| `{"detail": "<string>"}` | `{"detail":"No offers found for market selection MRKT_00000000000000000000000000000000"}` (404) | timeseries/summary for unknown or price-less selection |
| `{"detail": "[ErrorDetail(string='...', code='invalid')]"}` | pagination misuse (400) | DRF serializer error leaked as a Python repr |
| **bare JSON string** | `"Invalid league"`, `"Invalid sport"`, `"Invalid query parameter: proposition"`, `"MarketSelection is not available"`, `"At least one of the following query parameters is required: ['eventId', 'sdioEventId', 'sportradarE…"` (400) | validation on `/markets`, `/trends`, `/prices`, `/marketSelections/{id}/historicData`, `/marketOffers` |
| **HTML** | `<!doctype html><html lang="en"><head><title>Not Found</title>…` (404) | malformed path id, e.g. `/marketSelections/MSEL_x/metadata` |
| `{"error":…,"message":…,"suggestion":…,"docs":"docs.sharpsports.io","help":…}` | documented 404 envelope on `/books` | **[DOC]** only, not observed |

**Parser must handle: object-with-`detail`, bare-string, and HTML.** Never `json.loads` blindly on non-2xx.

### 1.6 Observed payload sizes & latency (capacity planning) **[PROBE]**

| Request | Size | Latency |
|---|---|---|
| `/prices?league=MLB` (all books) | **17.5 MB**, 146 events | 2.06 s |
| `/prices?league=LGUE_mlb` (same, id form) | 17.55 MB, 146 events | 2.84 s |
| `/prices?sport=baseball&book=dk` | 4.58 MB, 16 events | 2.39 s |
| `/prices?league=EPL&book=dk,fd` | 4.46 MB, 20 events | 1.14 s |
| `/prices?league=MLB&book=pp,ud` (DFS) | 3.78 MB, 9 events | 5.34 s |
| `/prices?league=MLB&book=kl,pm` (prediction mkts) | 1.88 MB, 97 events | 6.87 s |
| `/prices?league=MLB&book=pn` (Pinnacle) | 0.34 MB, 10 events | 6.37 s |
| `/prices?eventId=<one MLB game>` | **1.67 MB**, 67 markets | 0.28 s |
| `/prices?eventId=…&book=dk` | 0.39 MB, 21 markets | 0.41 s |
| `/marketSelections?eventId=…&limit=500` | 1.05 MB, 500 selections | 5.26 s |
| `/marketOffers?eventId=…` | 0.53 MB, 361 offers | 2.13 s |
| `/marketSelections?league=LGUE_mlb&limit=5` | 11.6 kB | **21.9 s** (!) |
| `/marketSelections?league=LGUE_mlb&type=prop&limit=5` | 11.6 kB | **32.3 s** (!) |
| `/prices/historic/summary?eventId=…` (unpaged) | 0.73 MB, **761** selections | 13.3 s |
| `/prices/historic/summary?eventId=…&pageSize=100&pageNum=1` | 0.12 MB | 1.09 s |
| `/prices/historic/summary?player=PLYR_mahomes&2024 season&pageSize=100` | 0.18 MB | **97.7 s** |
| `/prices/historic/summary?team=…&1 month&proposition=spread` | 0.10 MB, 56 sels | **54.5 s** |
| `/prices/historic/summary?player=LeBron&full season&proposition=total&position=Over` | — | **TIMEOUT >120 s** (×2) |
| `/prices/historic/timeseries` (1 selection, various rollups) | 4–310 kB | 0.2–3.3 s |
| `/players/{PLYR}/historicData` (Mahomes, 49 games) | 141 kB | 0.83 s (public-key path 403; private 0.83 s) — but **14–24 s** when any query param was appended (see §9) |
| `/injuries?league=NFL` | 264 kB, 434 rows | 3.43 s |
| `/bookRegions` (all) | 379 kB, **1557** rows | 1.44 s |
| `/markets` (unpaged) | 225 kB, 500 rows | 1.29 s |
| `/events?league=LGUE_mlb&2-month range&limit=1000` | 544 kB, 806 events | 10.35 s |

**Conclusion:** per-league `/prices` snapshots are multi-MB and ~2–7 s. Per-event `/prices` is 0.3 s / 1.7 MB. `/marketSelections?league=` is pathologically slow (20–32 s) — **never use league-scoped marketSelections in the hot path**; always scope by `eventId`.

---

## 2. Complete endpoint catalogue

Notation: **Auth** = key kind required (Pub/Priv). **LS** = live status observed in the probe (✅ 200, ⛔ 403 w/ public key, 🚫 error, — not probed). All paths are relative to `https://api.sharpsports.io/v1`.

### 2.1 Prices (betPrices)

| Method | Path | Purpose | Params | Pagination | RL | LS |
|---|---|---|---|---|---|---|
| GET | `/prices` | Current prices, deeply nested. **One of `eventId`, `sport`, `league` is required.** | `eventId` (str, `EVNT_…`, comma-sep) · `sport` (str, `SPRT_…` id or name e.g. `baseball`) · `league` (str, `LGUE_…` id **or** abbr e.g. `MLB`/`mlb`/`EPL`) · `marketId` (str, `MKT_…`, comma-sep) · `book` (str, `BOOK_…` id **or** 2-char abbr, comma-sep e.g. `dk,fd`) | **none** | 50 rps (doc banner absent; quickstart says 100) | ✅ Priv / ⛔ Pub |
| GET | `/prices/historic/summary` | Aggregated per-book first/last/high/low price stats per marketSelection | **mode A:** `marketSelectionId` (`MRKT_…`) · **mode B:** `eventId` · **mode C:** `player` (`PLYR_…` or name) **or** `team` (`TEAM_…` or name) **+ `eventStartTimeStart` (ISO8601, required)**, `eventStartTimeEnd` (default now) · filters: `position` (e.g. `Over`), `type` (`straight`/`prop`), `proposition` · `pageNum` (int ≥1), `pageSize` (int, doc default 50 max 100 — **probe accepted 100**) | `pageNum`+`pageSize` (both or neither) → adds `totalPages` | 50 rps | ✅ Priv / ⛔ Pub |
| GET | `/prices/historic/timeseries` | OHLC windowed timeseries for ONE marketSelection | `marketSelectionId` (**required**) · `timeseriesStart` (ISO8601) · `timeseriesEnd` (ISO8601) · `rollup` ∈ `5m,15m,1h,4h,1d` (default `1h`) | none | 50 rps | ✅ Priv / ⛔ Pub |
| GET | `/prices/historic` | **Does not exist as a separate endpoint.** Guide docs describe it; probe → 403 with public key (i.e. routed) but the real paths are the two above. Treat `/prices/historic` as **legacy/alias — do not use**. | — | — | — | ⛔ (403 only; never got a 200) |

**Notes / probe findings for `/prices`:**
* **`proposition` is NOT a valid param.** `/prices?eventId=…&proposition=spread` → `400 "Invalid query parameter: proposition"` **[PROBE]** — resolves an open question; the quickstart is wrong.
* `league` accepts **both** `MLB` and `LGUE_mlb` and lowercase `mlb`; byte-identical result sets for `MLB` vs `LGUE_mlb` (17,524,046 vs 17,552,907 B — differ only by concurrent updates) **[PROBE]**.
* Unknown `marketId` → 200 with `{"eventId": …, "markets": []}` (no error) **[PROBE]**.
* Past events → 200 with `markets: []` (prices are **live-only**; no historical prices via `/prices`) **[PROBE]**, confirmed on NFL 2022/2023, NBA 2024/2026 events and on an EPL event.
* `/prices?league=mlb` returned `[]` in one probe pass and 146 events in another → **off-season/no-live-slate behavior is an empty array, not an error**. Handle `[]`.

### 2.2 MarketSelections / MarketOffers / Markets

| Method | Path | Purpose | Params | Pagination | RL | LS |
|---|---|---|---|---|---|---|
| GET | `/marketSelections` | List selections (one per side/outcome) with per-book price ladders + betPlace availability | `eventId` · `sport` · `league` · `market` (`MKT_` id or name) · `marketOffer` (`MKTO_`) · `type` ∈ `straight,prop` · `proposition` · `segment` (`SEGM_` id or name) · `position` (positionId or `Over`/`Under`) · `team` (props only) · `player` (props only) · `metric` (props only) · `line` (float) · `minOdds` (int, American) · `maxOdds` (int) · `prices` (bool, **default true**) · `lineAvailability` (bool) · `metadata` (bool) · `teamAggStats` · `filteredTeamAggStats` · `playerAggStats` · `filteredPlayerAggStats` (bools) · `future` (bool, default false) · `historic` (bool, default false) · `limit` (int, default 500, ordered by `timeCreated`) · `pageSize` · `pageNum` · cross-vendor: `sdioMarketId`, `sdioEventId`, `sportradarEventId`, `sportradarMarketId`, `oddsjamEventId`, `oddsjamMarketId`, `theOddsApiMarketId`, `theOddsApiEventId` | `limit` + `pageSize`/`pageNum` (→ `{"objects","totalPages"}`) | **20 rps** (large-list) | ✅ Priv / ⛔ Pub |
| GET | `/marketSelections/{marketSelectionId}` | One selection | `lineAvailability` (bool) · `line` (float — availability & betPlace urls for that line) · `prices` (bool, default true) | n/a | 50 rps | ✅ Priv |
| GET | `/marketSelections/{id}/historicData` | Per-selection game log vs a line + DVP/park/pitcher context + bestPrice | `line` (float, doc says **required**; **[PROBE] optional** — omitting returns the full log using bestPrice line) · `gamesBack` (int/str) · `location` ∈ `home,away` · `opponent` (`TEAM_`) · `gamesWithout` (`PLYR_` — games where that player was NOT on the roster) | none | 50 rps | ✅ Priv |
| GET | `/marketSelections/{id}/metadata` | Hit-rate splits L1..L20, season, vsOpponent, atLocationType, DVP, park factor, starting pitcher, consensusProjection, bestPrice, optional aggregate stats | `line` (str; doc **required**, probe accepts and also works with it) · `seasonType` ∈ `PRE,REG,POST` · `teamAggStats` · `filteredTeamAggStats` · `playerAggStats` · `filteredPlayerAggStats` (bools) · `gamesBack` (int) · guide-only: `teamAggStatsSeason`, `playerAggStatsSeason` (comma years) | none | 50 rps | ✅ Priv |
| GET | `/marketOffers` | Market×Event(×player/team) grouping objects | **At least one of `eventId`, `sdioEventId`, `sportradarEventId`, … is REQUIRED [PROBE]** · plus `proposition`, `segment`, `team`, `player`, `metric`, `sport`, `league`, `market`, `future`, `sdioMarketId`, `sportradarMarketId`, `oddsjamEventId`, `oddsjamMarketId`, `limit` (500), `pageSize`, `pageNum` | `limit`+`pageSize`/`pageNum` | 50 rps | ✅ Priv (with `eventId`) / 🚫 400 without an event-scoping param |
| GET | `/marketOffers/{marketOfferId}` | One offer (doc page filename is `marketselection-detail-copy`) | none | n/a | 50 rps | — |
| GET | `/markets` | Market **definitions** (taxonomy templates) | `name` · `type` ∈ `prop,straight` · `proposition` · `segment` · `metric` · `player` (bool) · `team` (bool) · `future` (bool) · `sport` · `league` · `sdioMarketId` · `sportradarId` · `oddsjamId` · `theOddsApiId` · `pageSize` · `pageNum` | `pageSize`/`pageNum` (**works, → `{"objects","totalPages"}`**); unpaged caps at 500 | 50 rps | ✅ **Pub** |
| GET | `/markets/{marketId}` | One market definition | none | n/a | 50 rps | ✅ **Pub** |

**Probe findings:**
* **`/markets?league=nfl` → `400 "Invalid league"`** but **`/markets?league=NFL`** and **`/markets?league=LGUE_nfl`** both → 223 markets, byte-identical (106,976 B). ⇒ **`/markets` league filter requires UPPERCASE abbr or the `LGUE_` id; lowercase abbr fails.** Contrast with `/prices` which accepts lowercase. **This is a real per-endpoint inconsistency.**
* Same for `/teams` and `/players`: `?league=nfl` → `[]` (silently empty, **not** an error); `?league=NFL` / `?league=LGUE_nfl` → 32 teams. `?league=nba` → `[]`; `?league=LGUE_nba` → 611 players. ⇒ **Always pass `LGUE_*` ids (or uppercase abbrs) for league filters. Lowercase silently returns empty.** This is a silent-data-loss trap.
* `/sports?name=basketball` → `[]` (name filter appears case-sensitive or expects the display name `Basketball`).
* `/markets?theOddsApiId=h2h` → 7 markets ⇒ The Odds API market-key reverse lookup works.
* `/marketSelections?theOddsApiEventId=none` → `[]` (no error).
* `/marketSelections?league=…` is **20–32 s** — avoid.
* `historic=true` is required to see selections of past events; without it → `[]`. And historic responses **omit** `betPlaceAvailability`/`betPlaceUrls` **[PROBE confirmed]**: past-event selections have 16 keys, live ones 18.
* `/marketSelections/{id}/historicData` on a past (unavailable) selection → `400 "MarketSelection is not available"`.
* Malformed selection id (`MSEL_x`) on `/historicData` and `/metadata` → **HTML 404**, not JSON.

### 2.3 Events

| Method | Path | Purpose | Params | Pagination | RL | LS |
|---|---|---|---|---|---|---|
| GET | `/events` | Event list | `sport` (`SPRT_` or name) · `league` (`LGUE_` or abbr) · `future` (bool, default false) · `upcoming` (bool, **default true**) · `startTimeStart`, `startTimeEnd` (`%Y-%m-%dT%H:%M:%S` or `%Y-%m-%d`) · `limit` (int, default 500, ordered by `startTime`) · `pageSize` · `pageNum` · `ascending` (bool, default true) · cross-vendor: `sportsdataioId`, `sportradarId`, `oddsjamId`, `theOddsApiId` | `limit` + `pageSize`/`pageNum` | 50 rps | ✅ Priv / ⛔ Pub |
| GET | `/events/{id}` | One event | none | n/a | 50 rps | ✅ Priv |

**Probe findings:**
* `league` accepts `LGUE_mlb`, `LGUE_nfl`, `LGUE_nba`, `LGUE_wnba`, and the bare abbr `EPL` — all 200.
* `upcoming=false` + `startTimeStart`/`startTimeEnd` retrieves **past** events; works back to at least **2022-09-11** (NFL), **2024-01-15** (NBA), **2019-04-01** (MLB), **2019-08-01** (EPL) — all returned 5 events for probe ranges. ⇒ **event history depth ≥ 2019**.
* `ascending=false` works.
* `sportradarId=5750e479-d408-4b22-806b-94fba622a3e3` → exactly 1 event ⇒ **Sportradar event-id reverse lookup is live and populated**.
* `theOddsApiId=x` → `[]` (no error), so lookups by TOA id work but need a real id.
* `future=true` → 20 NFL "events" (futures containers).
* `sport=SPRT_esports` → `[]`.
* Live Event object has **18 keys** including two fields never documented: **`seasonType`** and **`venue`**.

### 2.4 Reference entities

| Method | Path | Purpose | Params | Pagination | RL | LS |
|---|---|---|---|---|---|---|
| GET | `/books` | Sportsbook catalogue incl. **`oddsFeedActive`** (betPrices coverage flag) | `support` (bool → adds `sdkSupport`) · `name` · `abbr` · `status` ∈ `active,inactive,coming,unsupported` (**default `active`**) | none | 50 rps | ✅ **Pub** — 15 active, 0 inactive, 0 coming, 10 unsupported |
| GET | `/bookRegions` | Book × US-state/CA-province | `abbr` (2-char region) · `status` (default active) · `book` (id/abbr/name) · `support` (bool) | none | **20 rps** | ✅ **Pub** — **1557** rows |
| GET | `/bookRegions/{id}` | One | none | n/a | 50 | — |
| POST/DELETE | `/books/{id}/affiliateLink` | Set/clear affiliate link (propagates to regions) | body `{"affiliateLink": "<url>"}` | n/a | 50 | — |
| POST/DELETE | `/bookRegions/{id}/affiliateLink` | Region-level override | body `{"affiliateLink"}` | n/a | 50 | — |
| GET | `/sports` | Sports | `name` | none | 50 | ✅ **Pub** — **20** sports |
| GET | `/leagues` | Leagues | `sport` · `region` · `abbr` | none | 50 | ✅ **Pub** — **138** leagues (99 soccer) |
| GET | `/teams` | Teams | `sport` · `league` · `name` | none | 50 | ✅ **Pub** |
| GET | `/teams/{id}` | One team | none | n/a | 50 | ✅ **Pub** |
| GET | `/teams/aggregateStats` | Teams + seasonStats | `season` · `metrics` (comma) · `sport` · `league` · `name` · `pageSize` · `pageNum` · `limit` | pageNum/pageSize+limit | 50 | ✅ **Pub** |
| GET | `/teams/{id}/aggregateStats` | One team + seasonStats | `season` · `metrics` | n/a | 50 | — |
| GET | `/teams/{id}/historicData` | **UNDOCUMENTED but LIVE**: team game log | none observed | none | 50 | ✅ **[PROBE]** 16 games, 47 kB, `[{event,stats}]` |
| GET | `/players` | Players | `sport` · `league` · `team` · `name` (first/last/full, partial) · `isMajorLeague` ∈ `true,false,all` (**default true**, MLB) · `pageSize` · `pageNum` · `previousTeam` (bool) | pageSize/pageNum | 50 | ✅ **Pub** |
| GET | `/players/{id}` | One player | none | n/a | 50 | ✅ **Pub** |
| GET | `/players/aggregateStats` | Player list + seasonStats, with stat-threshold screening | `season` · `metrics` · `position` · `sport` · `league` · `team` · `name` · `previousTeam` · `pageSize` · `pageNum` · `limit` · `games_played_gte`/`games_played_lte` (**require `position`**) · **dynamic** `<metric>_<total|per_game>_<gte|lte>` (require `position`), e.g. `points_per_game_gte=20`, `passing_yards_total_gte=3000` | pageNum/pageSize+limit | 50 | ✅ **Pub** |
| GET | `/players/{id}/aggregateStats` | One player + seasonStats | `season` · `position` · `metrics` | n/a | 50 | ✅ **Pub** |
| GET | `/players/{id}/historicData` | Player game log (all seasons), array of `{event, stats[]}` | **docs: none**. **[PROBE]** `gamesBack` **works** (returned 5 of 223); `season`, `startDate`/`endDate`, `seasonType`, `pageSize`/`pageNum` are **accepted but ignored** except `seasonType=POST` which returned `[]` | none | 50 | ✅ Priv / ⛔ Pub |
| GET | `/segments` | Segments | `name` · `abbr` | none | 50 | ✅ **Pub** — **95** segments |
| GET | `/metrics` | Metrics | `name` | none | 50 | ✅ **Pub** — **278** metrics |
| GET | `/trades/{TEAM_id}` | Players who joined/left a team in the **last 30 days**; optional injuries | `injuries` (bool) · `pageSize` · `pageNum` (1-based, needs pageSize) · `limit` (post-filter) | pageNum/pageSize+limit | 50 | ✅ **Pub** — 72 players; with `injuries=true` **63** players and each gains an `injury` key |
| GET | `/injuries` | Injury designations per player-event (historical + upcoming) with `played` outcome | `player` (`PLYR_` or full name) · `team` (`TEAM_` or name) · `league` (abbr or `LGUE_`; **restricts to players CURRENTLY carrying a designation**) · `pageSize` · `pageNum` · `limit`; guide-only (unverified): `event`, `status`, `played` | pageNum/pageSize (→ `{"objects","totalPages"}`) + limit | 50 | ✅ Priv / ⛔ Pub |
| GET | `/trends` | Scored player-prop trends refreshed within 48 h whose selection is still available | `league` · `sport` · `pageSize` · `pageNum` · `limit` | pageNum/pageSize+limit | 50 | ✅ Priv but **always `[]`** in probe (NFL, MLB, no-filter); `?sport=basketball` → `400 "Invalid sport"` |

### 2.5 betSync (bettors / accounts / slips / refresh)

| Method | Path | Purpose | Params | Pagination | RL | LS |
|---|---|---|---|---|---|---|
| GET | `/betSlips` | **Account-wide** feed of all synced slips across all our bettors | `refreshResponse` (`RRES_`) · `book` (id/name/abbr) · `abbr` · `status` ∈ `pending,completed` · `limit` (default **50**, ordered by `timePlaced`) · `pageSize` · `pageNum` · `timePlacedStart/End` · `dateClosedStart/End` · `timeClosedStart/End` · `type` ∈ `single,parlay` · `adjustedAtRisk`/`adjustedOdds`/`adjustedLine` (bool) · `sport` · `league` · `eventStartTimeStart/End` · `betType` (`straight`/`prop`) · `segment` · `proposition` · `position` · `team` · `player` · `metric` · `outcome` ∈ `win,loss,push,void,cashout,halfwin,halfloss` | limit/pageSize/pageNum | **20 rps** (banner says 50) | ✅ Priv / ⛔ Pub (`"You do not have permission…"`) |
| GET | `/betSlips/{betSlipId}` | One slip | (OpenAPI lists vestigial list filters) | n/a | 50 | — |
| GET | `/bettors/{id}/betSlips` | Slips for one bettor (`id` = `BTTR_` **or** our `internalId`) | same as `/betSlips` minus `refreshResponse` | limit(50)/pageSize/pageNum | 20 | — |
| GET | `/bettorAccounts/{id}/betSlips` | Slips for one account | same as `/betSlips` | limit(50)/pageSize/pageNum | 20 | — |
| GET | `/bettors/{id}/betSlips/statistics` | Aggregates: total / by league / by book / by slipType(single,parlay,teaser,live,future) / timeSeries | `league` (comma) · `startTime` · `endTime` · `timezone` | n/a | 50 | — |
| GET | `/bettors/{id}/betSlips/summary` | yesterday / week / month / today / tomorrow rollups | `timezone` (e.g. `America/New_York`) | n/a | 50 | — |
| GET | `/bettors` | Bettor list | `limit` (ordered `timeCreated` desc) · `pageSize` · `pageNum` | limit/pageSize/pageNum | 50 | ✅ Priv (3 bettors) / ⛔ Pub |
| GET | `/bettors/{id}` | Bettor detail (+metadata) | `metadata` (bool) · `timePlacedStart/End` · `league` · `sport` · `type` · `adjusted*` | n/a | 50 | — |
| GET | `/bettors/{id}/metadata` | handle/unitSize/netProfit/winPercentage/totalAccounts | `timePlacedStart/End` · `timeClosedStart/End` · `league` · `sport` · `type` · `adjusted*` · `proposition` · `position` · `betType` · `refreshResponseId` · **`timeSeriesRollup`** (int days) | n/a | 50 | — |
| POST | `/bettors/{id}/refresh` | Refresh all accounts of a bettor (async) | `auth` (mobile SDK) · `extensionVersion` (chrome ext) · **`reverify=true`** (prose only, not in OpenAPI) | n/a | **1/60 s per BACT_** | — |
| GET | `/bettorAccounts` | Account list | `access`/`verified`/`isUnverifiable` (bool) · `limit` · `pageSize` · `pageNum` · `book` · `bookRegion` | limit/pageSize/pageNum | 50 | ✅ **both keys** (5 accounts) |
| GET | `/bettors/{id}/bettorAccounts` | Accounts of a bettor | none | n/a | 50 | — |
| GET | `/bettorAccounts/{id}/metadata` | handle/unitSize/netProfit/winPercentage/walletShare | same filter set as bettor metadata + `timeSeriesRollup` | n/a | 50 | — |
| POST | `/bettorAccounts/{id}/refresh` | Refresh one account | `auth` · `extensionVersion` · `reverify=true` | n/a | 1/60 s | — |
| PUT | `/bettorAccounts/{id}/paused` | Pause syncing | body `{"paused": bool}` (required) | n/a | 50 | — |
| PUT | `/bettorAccounts/{id}/access` | Revoke access (stops billing; **irreversible via API**) | body `{"access": bool}` (default false) | n/a | 50 | — |
| GET | `/refreshResponses` | Refresh results (embeds slips) | `requestId` · `status` (int) · `limit` (default **500**) · `pageSize` · `pageNum` · `timeCreatedStart/End` | limit/pageSize/pageNum | 50 | — |
| GET | `/bettors/{id}/refreshResponses` | " by bettor | same | same | 50 | — |
| GET | `/bettorAccounts/{id}/refreshResponses` | " by account | same | same | 50 | — |
| GET | `/refreshResponses/{id}` | One (referenced but page not mirrored) | — | n/a | 50 | — |

### 2.6 Contexts / SDK / webhooks / misc

| Method | Path | Purpose | Params | LS |
|---|---|---|---|---|
| POST | `/context` | betSync linking context → `{"cid": …}`; UI `https://ui.sharpsports.io/link/{cid}` | body: `internalId` (**required**, immutable per bettor) · `redirectUrl` · `uiMode` ∈ `dark,light,system` (default system) · `extensionAuthToken` · (quickstart also shows `webhookUrl`) | — (Pub) |
| POST | `/context/selection` | betPlace context (tail a slip or build a parlay link) | `internalId` (req) · `betSlip` (`SLIP_`) · `marketSelection` (`MRKT_`, comma-sep for parlay) · `bookAbbr` · `line` (float) | — (Pub) |
| POST | `/context/bestPrice` | bestPrice widget context → `https://ui.sharpsports.io/best-price/{cid}` | `internalId` (req) · `extensionAuthToken` · `uiMode` | — (Pub) |
| POST | `/{platform}/auth` | SDK auth token; `platform` ∈ `mobile,extension` | body `{"internalId"}` | — (Priv) |
| POST | `/mobile/auth` | (same as above, mobile) → `{"token": …}`; token per-internalId, **no TTL** | body `{"internalId"}` | — (Priv) |
| GET | `/hooks/logs` | Webhook delivery logs | **`limt`** (sic, int, default 500) · `pageSize` · `pageNum` · `status` (int) · `event` · `requestId` · `url` · `eventObject` · `timeCreatedStart/End` | — (Priv) |
| GET | `/articles` | betContent AI articles | `league` (**required**, abbr e.g. `NFL`) · `dateCreated` (**required**, `YYYY-MM-DD`) | — (Priv) |
| GET | `/articles/{id}` | Article detail (**only in quickstart sample code, not in reference**) | — | — |
| POST | `/pine/partner/provision-user` | Pine whitelabel user mgmt | `action` ∈ `provision,deprovision,update_limits` (default provision) · `email` (req) · `result_url` (req for provision) · `pro_monthly_chat_limit` · `lite_monthly_chat_limit` (nullable ints ≥0) | — (Priv; 403 for sandbox) |
| — | `ui.sharpsports.io/place/<MRKT_>/<bookabbr\|BOOK_>[?line=<line>]` | betPlace deep link (main or alt line) | — | — |
| — | `ui.sharpsports.io/place/parlay/<BOOK_>?marketSelection=a,b&line=x,,null` | Parlay deep link | — | — |

**Webhook events (push, betSync only):** `bettor.created`, `bettorAccount.verified`, `bettorAccount.unverified`, `bettorAccount.inaccessible`, `refreshResponse.created`. Headers `Hook-HMAC` (base64 HMAC-SHA256 of **raw** body) and `Hook-Subscription` (uuid). Must return 200 within **10 s**; process asynchronously afterwards. No timestamp/replay header. Secret + `hmac_digest` (`"sha256"`) come from the *list-subscriptions* endpoint (page not mirrored).

---

## 3. Data model & ID schemes

### 3.1 ID prefix table (all prefixes, real examples)

| Prefix | Entity | Suffix format | Real examples |
|---|---|---|---|
| `EVNT_` | Event | 32 lowercase hex (also 22-char base64url in one doc example) | `EVNT_533e7e58b7554f03bdc23d39183a25ec` (live MLB) · `EVNT_c4f434ec6ffa4c4e86740b082e41e5de` (NFL 2022) · `EVNT_902c72ff9ff549ddafe9b696c5188de3` (NFL 2023) · `EVNT_cb741a0b42024afebf3bb0f1e71db01d` (NBA 2024) · `EVNT_9f163242d6ef42fcad88dcdaf6573eae` (MLB 2025-08) · `EVNT_G6JvTtYoTriXos41COV2Qw` (doc) |
| `MKT_` | Market (definition/template) | 32 hex | `MKT_c279ec8a05bc4107a4a0d7f5c39efdab` (probe) · `MKT_384ab07bf6de489b9fe5616b6f35e92a` ("Player Prop Total Home Runs") · `MKT_66072c73020447638eeed55d0313c0db` ("Player Prop Total Passing Yards") · `MKT_c47dd1d1793240d083d88d3e4776fd48` ("Team Prop Total Touchdowns") |
| `MKTO_` | MarketOffer (Market×Event[×player/team]) | 32 hex | `MKTO_51d113568d6c483895a9d7e1d7dbadc0` · `MKTO_8ce00ee675054ae28589fe0ef5301560` |
| `MOFR_` | MarketOffer — **alternate prefix in the trends sample** | 32 hex | `MOFR_1234567890abcdef1234567890abcdef` |
| `MRKT_` | **MarketSelection** (a side/outcome) | 32 hex | `MRKT_7cd1e43612c34ab691fea9843d153c82` (prop, probe) · `MRKT_51d96e2856b145288d67a3e31efaf969` (straight, probe) · `MRKT_d41c74f69b9b47209fc329f09b14af96` (MLB 2025-08) · `MRKT_a0772b024d094d7d84a3a33f96b710f3` (NBA 2026) · `MRKT_497f0815d53a4ba487b80bc87624b2a7` (NFL 2022, no offers) |
| `MSEL_` | **DOES NOT EXIST** — appears only in the historic-endpoint docs as the alleged marketSelectionId prefix | — | `MSEL_x` → `404 {"detail":"No offers found for market selection MSEL_x"}` **[PROBE: resolved doc error; use `MRKT_`]** |
| `PRICE_` | Price object (only on `bestPrice`) | 32 hex | `PRICE_43421d95f1584dbfaecce7722d87066e` · `PRICE_4224b83af40744ee8f54a505a73f6c28` |
| `BOOK_` | Book | **opaque**: 32 hex OR 20–22-char base64url | `BOOK_nhLZ9l5DRs6w6KcE2n7vnw` (dk) · `BOOK_Rf7xRhS7TKQUl94Xkt5w` (fd) · `BOOK_pPg9ABaPSj2mL6qoMTKR1A` (mg) · `BOOK_IPBQaQQTCRxplZx7SYOA` (ca) · `BOOK_c81242f993894e67966b3ccfc4ba3a65` (bs) · `BOOK_yQb2mAZpRGGCqPSYu4hmmg` (pb) · `BOOK_88064cc6787c47ccbd4bbb036c7f55c5` (br) |
| `BSTA_` / `BRGN_` | BookRegion (both prefixes in the wild) | opaque | `BSTA_lqpNkqJjSSv5MwxCXSFbQ` · `BSTA_Okuj8vPwRPSMnYhROBE1Uw` · `BRGN_b28ee954c84f4668bd4b7763beb90a97` |
| `TEAM_` | Team | 32 hex | `TEAM_8bfd1dfe1a09451195d19c792ea18567` (KC Chiefs) · `TEAM_0bea24fff0ba45a6ba2f88b0217d224e` (Celtics) · `TEAM_4c55dc8e7a3b4b21b0509d93b49f8a33` (Lakers/Dolphins in different docs) · `TEAM_3091d5574798424ab85271e615dd5183` (D-backs) · `TEAM_7ab6eb241f3e440ab8c6d771fb0694a9` (Eagles) · `TEAM_a63ec49ed87c4be6909fe5cc016a82be` (Cowboys) |
| `PLYR_` | Player | 32 hex | `PLYR_9e93378b8a0440a1a79131e56bc2ca88` (Patrick Mahomes) · `PLYR_55eae5de659045bb85ec3e9bac905fb2` (LeBron James) · `PLYR_b17ad16784c84a01a8afcd0846e10357` (Ohtani) · `PLYR_0472337baea34f86bed7cc14d7e1fd34` (Harry Kane) · `PLYR_e741e812680d451e99f9ed3b6832647b` (NBA probe) · `PLYR_e9e9d0e0b70b4143b49b08ba2b16f406` (Dak Prescott) · `PLYR_fef8f29544ce487c91b23eff993abcd5` (Jayson Tatum) |
| `SPRT_` | Sport | **slug** | `SPRT_baseball`, `SPRT_basketball`, `SPRT_americanfootball`, `SPRT_soccer`, `SPRT_icehockey` |
| `LGUE_` | League | **slug for majors, 32 hex for others** | `LGUE_mlb`, `LGUE_nfl`, `LGUE_nba`, `LGUE_nhl`, `LGUE_ncaaf`, `LGUE_wnba` · `LGUE_542b6c4f1c7f4a0da7154747c76e7340` (EPL) · `LGUE_6f8a50498ff14a97ad58f47b184116c4` (Leagues Cup) |
| `SEGM_` | Segment | short code / slug | `SEGM_M` = "Match" (full game). 95 segments exist **[PROBE]**; `?abbr=1H` → 1 row. |
| `METR_` | Metric | slug, **inconsistent style** | `METR_points`, `METR_touchdowns`, `METR_passyds`, `METR_homeruns`, `METR_hitsrunsrbis`, `METR_freethrows`, `METR_assists` — **but also** `METR_passing_yards`, `METR_passing_touchdowns`, `METR_passing_attempts`, `METR_completions` (snake_case in player historicData). **Treat as fully opaque; resolve via `/metrics` (278 rows).** |
| `TRND_` | Trend | 32 hex | `TRND_3f1a7c8e4b2d4e9a8c1f5d6b7e8a9c0d` |
| `BTTR_` | Bettor | 32 hex OR 22-char base64 (**may contain `+`**) | `BTTR_e336bbc337e24ba99eb68b2b6d12a398` · `BTTR_Bz4xjCdtS4mlb42OHLJF0Q` · `BTTR_cahAECmtTe2l+Or9Ust5Ag` ⚠️ URL-encode path ids |
| `BACT_` | BettorAccount | 32 hex | `BACT_ad5e5125177b42d395013adf4d47fd17` |
| `SLIP_` | BetSlip | 32 hex | `SLIP_c27a9b53280e4658b9d8720ad6597268` |
| `BET_` | Bet (leg) | 32 hex | `BET_5d0b6e51f3c6433a834925fc6c996979` |
| `RRES_` | RefreshResponse | 32 hex | `RRES_3da71e46f7df447cbd01f99e177fe9e6` |
| `CTX_` | Context cid | opaque | `CTX_abc123xyz` (placeholder) |
| `VENU_` | Venue | opaque | `VENU_abc123` (guide only) |
| `PGME_` | PlayerGameData row | opaque | `PGME_abc123def456` (guide only; **not** in real responses) |
| (none) | Article | UUID with dashes | `31c87019-7c8e-49a9-943b-08d3d03007c2` |
| (none) | `requestId` | 32 hex **or** dashed UUID (differs by page) | `b0e1c265b19a494cab937ba0092370d6` / `73cea1a9-c636-4936-8b61-649b505a2f90` |
| (none) | webhook log `id` | **integer** (docs say string) | `49944914` |

### 3.2 Event

**[PROBE] Live shape — 18 keys** (`GET /events/{id}`, `GET /events`):

```json
{
  "id": "EVNT_533e7e58b7554f03bdc23d39183a25ec",
  "sportsdataioId": "<string numeric>",
  "sportradarId": "5750e479-d408-4b22-806b-94fba622a3e3",
  "oddsjamId": "24292-35183-2024-08-16-15",
  "theOddsApiId": "f042b623f0e70459103f5406f1ea75ee",
  "sport": "Baseball",
  "league": "MLB",
  "name": "Kansas City Royals @ Cincinnati Reds",
  "nameSpecial": null,
  "startTime": "2024-08-16T22:40:00Z",
  "startDate": "2024-08-16",
  "seasonType": "REG",
  "venue": { /* shape not captured in summary; NEW field, undocumented on the Event page */ },
  "sportId": "SPRT_baseball",
  "leagueId": "LGUE_mlb",
  "contestantAway": {"id": "TEAM_…", "fullName": "…"},
  "contestantHome": {"id": "TEAM_…", "fullName": "…"},
  "neutralVenue": false
}
```

| Field | Type | Semantics |
|---|---|---|
| `id` | string `EVNT_` | primary key |
| `sportsdataioId` | string (numeric) \| null | SportsData.io GameID, e.g. `"10072548"`, `"18658"`, `"19039"` |
| `sportradarId` | UUID string \| null | Sportradar match id, **no `sr:match:` prefix**. **[DOC]** "will be null unless you provide your API keys for this third party provider" — **[PROBE] it is populated for us** (reverse lookup worked), so either SharpSports supplies it globally now or the account has a Sportradar key configured. |
| `oddsjamId` | string \| null | OddsJam (=OpticOdds predecessor) game id. Formats seen: `"24292-35183-2024-08-16-15"` (`teamA-teamB-YYYY-MM-DD-HH`), `"13602-22677-24-02"` (`teamA-teamB-YY-WW` for NFL/NCAAF), `"16903-86230-2023-12-07"`, `"11434-17233-25-35"`, `"31138-72383-23-38"`, `"28014-42288-2020-07-07"`, `"77646-19370-2024-04-29"` |
| `theOddsApiId` | 32-hex string \| null | The Odds API event id, e.g. `"906a0faf52da9de59f381f82f7bf7116"`, `"f1bc532dff946d15cb85654b5c4b246e"`, `"f042b623f0e70459103f5406f1ea75ee"` |
| `sport` / `league` | string | **display name / abbr**, e.g. `"Baseball"` / `"MLB"`, `"Soccer"` / `"England - Premier League"` — NOT ids. Join on `sportId`/`leagueId`. |
| `name` | string | `"<away> @ <home>"` for home-advantage games; `"<A> vs. <B>"` for neutral; proper name for tournaments (`"The Masters 2023"`) |
| `nameSpecial` | string \| null | Alt name (e.g. `"SuperBowl 52"`). **Not** a reliable playoff flag (null on a wild-card game in the docs sample). |
| `startTime` | ISO-8601 **UTC with `Z`** | scheduled start |
| `startDate` | `YYYY-MM-DD` | scheduled date |
| `seasonType` | string | **[PROBE, undocumented on Event page]** `"REG"`; enum presumably `PRE`/`REG`/`POST` (matches the `seasonType` param enum on `/metadata`) |
| `venue` | object \| null | **[PROBE, undocumented]** venue info; `/metadata` venue is `{name, parkFactorPerc, parkFactorRank}` |
| `contestantAway` / `contestantHome` | `{id, fullName}` | `TEAM_` or `PLYR_` (individual sports) |
| `neutralVenue` | bool \| **null** | true/false/null — three-state |
| `endTime` | string \| null | **only in the MarketOffer-embedded Event** shape |

**No status/score/`timeUpdated` field on Event.** Liveness must be inferred from `startTime` vs now and from `Price.live`.

**Embedded-Event variants (be defensive — 3 different shapes):**
1. **Full** (`/events`, `/events/{id}`, `/marketSelections/{id}/historicData`.event, `/marketSelections/{id}/metadata`.event): 18 keys as above.
2. **MarketSelection-embedded** (`/marketSelections`): **16 keys** — `id, oddsjamId, theOddsApiId, sport, league, name, nameSpecial, startTime, startDate, seasonType, venue, sportId, leagueId, contestantAway, contestantHome, neutralVenue` — i.e. **`sportsdataioId` and `sportradarId` are dropped** **[PROBE]**.
3. **Player-historicData-embedded**: `{id, sport{id,name}, league{id,name,abbr}, name, nameSpecial, startTime, sportId, leagueId}` — no vendor ids, no contestants, no dates. Here `sport`/`league` are **objects**, not strings ⚠️.
4. **MarketOffer-embedded**: full-ish incl. `endTime`, but `sport`/`league` are **strings**.

### 3.3 Market (definition/template)

**[PROBE] Live shape — 15 keys**, confirmed identical on `/markets`, `/markets/{id}`, and embedded as `.market` in `/marketSelections/{id}/historicData` and `/metadata`:

```json
{
  "id": "MKT_384ab07bf6de489b9fe5616b6f35e92a",
  "name": "Player Prop Total Home Runs",
  "type": "prop",
  "proposition": "total",
  "player": true,
  "team": false,
  "future": false,
  "oddsjamId": "player_home_runs",
  "sportradarId": "sr:market:9003",
  "sportsdataioId": null,
  "theOddsApiId": "batter_home_runs",
  "sport":   {"id": "SPRT_baseball", "name": "Baseball"},
  "league":  {"id": "LGUE_mlb", "name": "Major League Baseball", "abbr": "MLB"},
  "segment": {"id": "SEGM_M", "name": "Match"},
  "metric":  {"id": "METR_homeruns", "name": "Home Runs"}
}
```

| Field | Type | Notes |
|---|---|---|
| `id` | `MKT_`+32hex | |
| `name` | string | The exact taxonomy string (see §3.9). Docs mislabel it "(hash)". |
| `type` | `"straight"` \| `"prop"` | straight = wager on the result of an event/segment |
| `proposition` | string | **closed enum for straights**: `spread`, `moneyline`, `total`, `3-way`. For props: those four **or free text** ("gatorade color poured on winning head coach"). |
| `player` / `team` / `future` | bool | player prop / team prop / future market |
| `oddsjamId` | string \| null | OddsJam market key: `moneyline`, `point_spread`, `player_home_runs`, `player_passing_yards`, `team_total_touchdowns` |
| `sportradarId` | string \| null | `sr:market:219` (ML), `sr:market:223` (spread), `sr:market:914` (player pass yds), `sr:market:9003` (batter HR) |
| `sportsdataioId` | string \| null | often null |
| `theOddsApiId` | string \| null | TOA market key: `h2h`, `player_pass_yds`, `batter_home_runs` |
| `sport`/`league`/`segment`/`metric` | objects | `{id,name}` / `{id,name,abbr}` / `{id,name}` / `{id,name}`. `metric` is populated for props (null/absent for straights **[UNVERIFIED]**). |

**Counts [PROBE]:** `/markets` total > 1000 (pageSize=1000 filled a page and `totalPages`>1); `?league=NFL` → 223; `?league=NBA&player=true` → 39; `?future=true` → 48; `?theOddsApiId=h2h` → 7.

### 3.4 MarketOffer

`MKTO_` (or `MOFR_`). Shape (doc, exact):

```json
{
  "id": "MKTO_8ce00ee675054ae28589fe0ef5301560",
  "market": { …full Market object (15 keys)… },
  "event":  { …Event, incl. endTime; sport/league as STRINGS… },
  "player": {"id":"PLYR_…","sportsdataioId":"10005741","oddsjamId":"B596D9D36B6E","sportradarId":"cf302aef-…","firstName":"Paul","lastName":"DeJong","sportId":"SPRT_baseball","fullName":"Paul DeJong"} | null,
  "team": { …Team… } | null,
  "sdioMarketId": null
}
```

**[PROBE] Live `/marketOffers?eventId=…` item keys: exactly `['id','market','event','player','team','sdioMarketId']`** — 361 offers on one MLB event.

`sdioMarketId` is the **per-offer** SportsData.io betting-market id (distinct from `market.sportsdataioId`, which is per market-type).

### 3.5 MarketSelection ⭐ (the pricing grain)

**[PROBE] Live shape — 18 keys (live selection) / 16 keys (historic selection):**

```
['id','type','event','segment','proposition','position','marketId','marketName',
 'marketOfferId','sportsdataio','sportradar','oddsjam','theOddsApi','segmentId',
 'positionId','propDetails',
 'betPlaceAvailability','betPlaceUrls']          ← last two ONLY when currently available
```

Two **new keys not in any doc page**: **`marketOfferId`** and **`theOddsApi`** (an object, sibling of `sportsdataio`/`sportradar`/`oddsjam`) **[PROBE]**.

With `?lineAvailability=true` a 19th key **`lineAvailability`** appears; with `?metadata=true` a **`metadata`** key appears. With `?prices=false`, the response still shows 18 keys in the probe summary — meaning **`prices` is not a top-level key in the live serialization at all**; per-book price ladders live under `prices` only when `prices=true` (default), and the probe's key list for `prices=false` vs default were identical (18 keys both) which suggests the ladder may be nested elsewhere or the summary truncated. ⚠️ **[OPEN]** — verify against the raw sample before coding the ladder path; the documented shape is:

```json
"prices": { "<bookAbbr>": [ {"line": 26.5, "odds": -110, "main": true}, ... ] | null }
"lineAvailability": { "<bookAbbr>": [ -6, -5.5, ... ] | null }
```

Full field list (doc + probe):

| Field | Type | Semantics |
|---|---|---|
| `id` | `MRKT_`+32hex | the pricing key |
| `type` | `"straight"` \| `"prop"` | (trends sample shows `"PlayerProp"` — inconsistent, that's the trends-embedded variant) |
| `event` | object (16-key variant) | see §3.2 |
| `segment` | string \| **null** | segment display name; **can be null while `segmentId` is set** |
| `segmentId` | `SEGM_…` | e.g. `SEGM_M` |
| `proposition` | string | `spread`/`moneyline`/`total`/`3-way` for straights; free text for props |
| `position` | string | `"Over"`, `"Under"`, a standardized team name, a player name, or other |
| `positionId` | `TEAM_`/`PLYR_` \| null | set when `position` is a standardized object |
| `marketId` | `MKT_…` | |
| `marketName` | string | e.g. `"Moneyline"`, `"Player Prop Total Points"` |
| `marketOfferId` | `MKTO_…` | **[PROBE, undocumented]** parent offer |
| `sportsdataio` | `{eventId, marketId}` | |
| `sportradar` | `{eventId, marketId}` | marketId like `"sr:market:219"` |
| `oddsjam` | `{eventId, marketId}` | marketId like `"moneyline"` |
| `theOddsApi` | object | **[PROBE, undocumented]** presumably `{eventId, marketId}` |
| `propDetails` | object \| null | only when `type=prop`: `{player, playerId, team, teamId, matchupSpecial, metricSpecial, metricSpecialId, future}` |
| `betPlaceAvailability` | `{abbr: bool}` | ~21 book keys; "whether SharpSports can create a link" ⇒ **proxy for "book currently offers this selection"** |
| `betPlaceUrls` | `{abbr: url\|null}` | `ui.sharpsports.io/place/<MRKT_>/<BOOK_>` |

`propDetails` fields:
* `player` (name), `playerId` (`PLYR_`), `team`, `teamId` (`TEAM_`)
* `matchupSpecial` — non-sanctioned matchup, e.g. `"Tiger Woods vs. Phil Mickelson"` within "The Masters"
* `metricSpecial` / `metricSpecialId` — e.g. `"Free Throws"` / `METR_freethrows`
* `future` (bool) — "props placed on an event without a defined, sanctioned matchup … All bets on the winner of a tournament, or other field based contest are considered futures"

**Selection cardinality:** ML/spread → 2 selections; 3-way → 3; totals/prop-totals → 2 (`Over`/`Under`); futures → one per contestant. **The line is NOT part of selection identity** — `(selection, book, line)` identifies a quote.

**[PROBE] Volume:** one live MLB game had **≥500** marketSelections (`limit=500` filled), `totalPages` on `pageSize=50` paging, and **761** selections in `/prices/historic/summary?eventId=`.

### 3.6 Price (nested inside `/prices`) ⭐

`/prices?eventId=…` → **object** `{"eventId": str, "markets": [...]}`.
`/prices?league=…|sport=…` → **array** of those objects.

Nesting (5 levels), exact doc shape + probe-confirmed key names:

```
{ "eventId": "EVNT_14368855fdbb4b14965536d04c50dcbb",
  "markets": [ {                                  // probe keys: ['id','name','marketOffers']
    "id": "MKT_945039fb0b3b49c18b27f69d98826ee6",
    "name": "Moneyline",
    "marketOffers": [ {
      "id": "MKTO_51d113568d6c483895a9d7e1d7dbadc0",
      "player": {"id":"PLYR_…","fullName":"…"} | null,
      "team":   {"id":"TEAM_…","fullName":"…"} | null,
      "marketSelections": [ {
        "id": "MRKT_3933288e631c4f188c30db34dd52774e",
        "position": "Arizona Diamondbacks",
        "positionId": "TEAM_3091d5574798424ab85271e615dd5183" | null,
        "books": [ {
          "id": "BOOK_nhLZ9l5DRs6w6KcE2n7vnw",
          "abbr": "dk",
          "name": "DraftKings",
          "prices": [ {
            "line": 0.0,                      // float; 0.0 for moneyline HERE
            "odds": -155,                     // int, AMERICAN
            "impliedProbability": 0.6078,     // float
            "main": true,                     // false => "alt" line
            "live": false,                    // true => updated since event began
            "marketOfferVolume": null,        // int|null, prediction-market books only
            "marketSelectionVolume": null,    // int|null, prediction-market books only
            "bookIds": {                      // 🔐 betPlace subscription
              "eventId": "30589142",
              "marketId": "30589142_moneyline",
              "selectionId": "30589142_ari"
            },
            "betPlaceLinks": {                // 🔐 betPlace subscription
              "desktop": "directlink", "iOS": "directlink", "android": "directlink"  // each string|null
            }
          } ]
        } ]
      } ]
    } ]
  } ] }
```

Field semantics (exact doc language where load-bearing):

| Field | Type | Doc language / semantics |
|---|---|---|
| `line` | float | "The line associated with the price." **`0.0` for moneyline in `/prices`; `null` for moneyline in `MarketSelection.prices`** — normalize both to "no line". |
| `odds` | int | American odds. |
| `impliedProbability` | float | "Represents the implied probability of the americanOdds on this price, **also equal to the share price for prediction markets**." |
| `main` | bool | "When `false`, this price represents an 'alt' line." |
| `live` | bool | "When `true`, this price represents a value that **has been updated since the event began**." |
| `marketOfferVolume` | int \| null | "trading volume associated with the marketOffer at this price (**currently only populated for prediction-market books**)" |
| `marketSelectionVolume` | int \| null | same, at selection level |
| `bookIds` | `{eventId, marketId, selectionId}` | "Sportsbook-native identifiers … Useful for cross-referencing odds back to a sportsbook's own data feed." 🔐 betPlace. |
| `betPlaceLinks` | `{desktop, iOS, android}` | 🔐 betPlace; values may be null. |

### 🔴 **CRITICAL: `/prices` has NO timestamp.**
There is **no `id`, no `timeUpdated`, no `timestamp`, no `lastChanged`** on the nested Price object — confirmed by the authoritative reference page and not contradicted by any probe sample. The quickstart's `{"id":"PRICE_…","timeUpdated":"2024-01-15T10:30:00Z","isMain":true}` shape is **fiction**. Consequences:
* Per-quote freshness must be stamped **client-side at fetch time**.
* The only in-band staleness signals are `live` (bool) and `main` (bool).
* Line-change timing can only be recovered post-hoc from `/prices/historic/timeseries` (5-minute floor).

### 3.7 Book

**[PROBE] Live shape — 14 keys** (`GET /books`):

```
['id','name','abbr','status','refreshCadenceActive','sdkRequired','pullBackToDate',
 'maxHistoryMonths','maxHistoryBets','historyDetail','oddsFeedActive',
 'backgroundRefresh','mobileOnly','betPlaceStatus']
```
`backgroundRefresh` is **[PROBE, undocumented]**. With `?support=true` an `sdkSupport` object is added (6160 B → 17042 B for 15 books).

| Field | Type | Notes |
|---|---|---|
| `id` | `BOOK_` opaque | never assume hex |
| `name` | string | |
| `abbr` | string | **2-char stable key** — use this, not `id`, as the book key |
| `status` | `active` \| `inactive` \| `coming` \| `unsupported` | active = "available for new links and refreshes"; inactive = "currently down for maintenance"; coming = "integration is in development"; unsupported = "integration is not currently offered". **Default filter is `status=active`.** |
| **`oddsFeedActive`** | bool | **"This field indicates whether 🏛️ Prices will be included for this book."** ⇒ **the betPrices coverage flag.** Filter on this to get the price universe. |
| `refreshCadenceActive` | bool | betSync auto-refresh |
| `sdkRequired` / `sdkSupport` / `backgroundRefresh` / `mobileOnly`(deprecated) | bool/obj | betSync linking mechanics |
| `pullBackToDate` (date) / `maxHistoryMonths` (int) / `maxHistoryBets` (int) / `historyDetail` (str) | | betSync bet-history depth per book |
| `betPlaceStatus` | `{webBrowser, iOS, android}` | values: `unsupported`, `inactive`, `betSlipCreation` ("will fill out the betSlip automatically"), `deeplink` ("deeplink to the correct page but not fill out the betslip") |

**[PROBE] Book universe: 15 active, 10 unsupported, 0 inactive, 0 coming.**

**Book abbr resolution — probe evidence for previously-unknown abbrs:**
| abbr | Book | Evidence |
|---|---|---|
| `dk` | DraftKings | doc + `/books?abbr=dk` → 1 |
| `fd` | FanDuel | doc |
| `mg` | BetMGM | doc |
| `ca` | Caesars | doc |
| `bs` | ESPN BET | doc |
| `br` | BetRivers | doc (`BOOK_88064cc6787c47ccbd4bbb036c7f55c5`) |
| **`pn`** | **Pinnacle** | **[PROBE]** `/prices?league=MLB&book=pn` → 200, 10 events, 341 kB ⇒ **Pinnacle is in our betPrices feed.** Resolves the open question. |
| **`kl`** | **Kalshi** | **[PROBE]** `/bookRegions?book=kl` → 64 regions; `/prices?league=MLB&book=kl,pm` → 97 events |
| **`pm`** | **Polymarket** (inferred) | **[PROBE]** accepted in `book=kl,pm`; prediction-market pair with Kalshi. **[UNVERIFIED name]** |
| `pp` | PrizePicks (DFS) | doc; `/prices?league=MLB&book=pp,ud` → 9 events, 3.78 MB |
| `ud` | Underdog (DFS) | doc |
| `hr`,`st`,`fl`,`bf`,`fb`,`pb`,`wb`,`bo`,`tb`,`sh`,`tf`,`pe`,`sl` | Hard Rock, Sporttrade, Fliff, BetFred, Fanatics, PointsBet?, WynnBet?, ?, theScore?, ?, ?, ?, ? | partly inferred; **resolve authoritatively via `GET /books` + `GET /books?status=unsupported`** |

**Action item for ingestion bootstrap:** persist the full `/books` and `/books?status=unsupported` responses and build the definitive `abbr → {id, name, oddsFeedActive, betPlaceStatus}` map from live data, not from docs.

### 3.8 BookRegion, League, Sport, Team, Player, Segment, Metric

**BookRegion** — **[PROBE] 8 keys**: `['id','book','name','abbr','status','country','sdkRequired','mobileOnly']`. `book` = `{id,name,abbr}`. `country` ∈ `"United States"`, `"Canada"`. **1557 rows total**; `?book=dk` → 65, `?book=kl` → 64. Note: the doc'd `sdkSupport` only appears with `?support=true`. **Regions are irrelevant to betPrices** (no region param on `/prices`).

**League** — **[PROBE] 8 keys**: `['id','sportsdataioId','sportradarId','region','name','abbr','sportId','oddsjamId']`. 138 leagues; 99 soccer. `?abbr=EPL` → 1. Example: `{"id":"LGUE_6f8a50498ff14a97ad58f47b184116c4","sportsdataioId":"49","sportradarId":null,"oddsjamId":null,"sportId":"SPRT_soccer","region":"N/C America","name":"Leagues Cup","abbr":"LEC"}`. **No `theOddsApiId` on League.**

**Sport** — **[PROBE] 2 keys**: `['id','name']`. **20 sports.**

**Team** — **[PROBE] 9 keys**: `['id','sportsdataioId','oddsjamId','sportradarId','locale','name','fullName','abbr','sportId']`. Example: `{"id":"TEAM_7ab6eb241f3e440ab8c6d771fb0694a9","sportsdataioId":"26","oddsjamId":"EDCC2866B795","sportradarId":"386bdbf9-9eea-4869-bb9a-274b0bc66e80","locale":"Philadelphia","name":"Eagles","fullName":"Philadelphia Eagles","abbr":"PHI","sportId":"SPRT_americanfootball"}`. With `aggregateStats` → 10 keys. Counts: NFL 32, MLB 30, EPL 27, WNBA 15.

**Player** — **[PROBE] 9 keys**: `['id','sportsdataioId','oddsjamId','sportradarId','firstName','lastName','sportId','fullName','currentTeams']`. `currentTeams` = array of `{id, fullName}` (**can be empty** = released/free agent; can have >1). With `?previousTeam=true` → **11 keys**, adding `previousTeam` and **`changeDate`** **[PROBE, undocumented]**. With aggregate stats → adds `aggregateStats`. `oddsjamId` is 12 uppercase hex (`4E18B0FEC4C5`, `944B6D4B694A`, `EDCC2866B795`). `/players?league=LGUE_nba` → 611.
Trends-embedded player also has `headshot` (`https://player-headshots-sharpsports.s3.us-west-2.amazonaws.com/<PLYR_id>.png`) and `position`.
Trades-with-injuries player gains an **`injury`** key.

**Segment** — **[PROBE] 3 keys**: `['id','name','abbr']`. **95 segments.** Only `SEGM_M`/"Match" documented; `?abbr=1H` → 1 row. **Enumerate at bootstrap.**

**Metric** — **[PROBE] 2 keys**: `['id','name']`. **278 metrics.** `?name=Points` → 1 row. **Enumerate at bootstrap.**

### 3.9 Market taxonomy (market_name grammar)

`Market.name` is the canonical string, and it encodes the whole taxonomy. Grammar derived from 434 documented rows:

```
market_name := [ SEGMENT_PREFIX " " ] CORE
CORE        := STRAIGHT
             | [ "Future " ] PROP_KIND " " PROP_TAIL
             | "Future " FUTURE_TAIL
STRAIGHT    := "Moneyline" | "Spread" | "Total" | "3-way"
PROP_KIND   := "Game Prop" | "Team Prop" | "Player Prop" | "Match Prop"   -- Match Prop = tennis only
PROP_TAIL   := "Total " METRIC | "Correct Score" | "Both Teams To Score" | "Winning Margin"
FUTURE_TAIL := "Winner " COMPETITION " " SEASON | "Leader after Round " N | "Top " N
SEGMENT_PREFIX := "1st Half"|"2nd Half"|"1st..4th Quarter"|"1st..3rd Period"
                | "1st..9th Inning"|"1st 3 Innings"|"1st 5 Innings"|"1st 7 Innings"
                | "Set 1"|"Set 2"
```
* Segment prefix goes **first**: `1st Quarter Player Prop Total Passing Yards`.
* **Exception (6 MLB Underdog rows):** segment is **infixed** and "Total" dropped: `Player Prop 1st Inning Hits`, `Player Prop 1st Inning Hits Allowed`, `Player Prop 1st 3 Innings Hits + Runs + RBIs`, `Player Prop 1st Inning Pitcher Strikeouts`, `Player Prop 1st Inning Runs`, `Player Prop 1st Inning Runs Allowed`. Your name parser must handle both placements.
* Combo metrics use `" + "`: `Hits + Runs + RBIs`, `Points + Rebounds + Assists`, `Passing + Rushing Yards`, `Rushing + Receiving Yards`, `Blocks + Steals`, `Assists + Rebounds`, `Points + Assists`, `Points + Rebounds`, `Tackles + Assists`, `Passing + Rushing Touchdowns`.
* **Metric words collide across sports** (`Assists` in NBA/NHL/NFL; `Points` in NBA/NHL; `Blocks` in NBA/NHL). **Key markets by `MKT_` id or `(sport, league, name)`, never by name alone.**
* Distinct-but-similar markets: `Player Prop Total Shots` vs `Player Prop Total Shots On Goal` (NHL); `Total Outs` vs `Total Pitcher Outs` (MLB); `Total Earned Runs` vs `Total Earned Runs Allowed` (MLB).
* **Futures names embed the season** (`2024`, `2024/25`, `2023/24`, `2025`) ⇒ a **new `MKT_` id per season**; the doc snapshot (2025-09-18) is stale by construction.
* Non-total prop propositions (Correct Score, BTTS, Winning Margin, all Futures) have **undocumented `proposition` literals** — resolve from live `/markets` data.

Documented row counts by sport: Baseball 123, Basketball 68, Football 146, Golf 13, Hockey 35, Soccer 25, Tennis 24 (10 dup). **Live `/markets` has >1000 rows**, so the doc tables are a lower bound.

Doc-only book coverage note: **Pinnacle appears on** full-game ML/spread/total in all 6 team sports + tennis; MLB 1st-inning ML/spread/total; NBA/WNBA & NFL/NCAAF 1st Half and 1st Quarter ML/spread/total; soccer 1st Half; team totals (MLB runs, NBA/NFL points incl. 1H/1Q, NHL & soccer goals); ~16 MLB/NFL player props. **Pinnacle is absent from every 3-way, game prop, NBA/NHL player prop and future.**

### 3.10 historicData objects

#### `/marketSelections/{id}/historicData` — **[PROBE] 16 keys**
```
['event','team','opponent','locationType','player','market','position',
 'DVP','dvpRank','dvpAvg','dvpPosition','consensusProjection','venue',
 'startingPitcher','gameStats','bestPrice']
```
Sub-shapes **[PROBE]**: `event` = full 18-key Event; `team`/`opponent` = full 9-key Team; `player` = 8-key Player (no `currentTeams`); `market` = full 15-key Market.

| Field | Type | Semantics |
|---|---|---|
| `locationType` | `"Home"` \| `"Away"` | for the **upcoming** game (capitalized) |
| `DVP` | float \| null | "opponent's defensive performance against this player's position. **Lower values indicate stronger defense**" |
| `dvpRank` | int \| null | "opponent's league ranking for defense against this position (**1 = best defense**)" |
| `dvpAvg` | float \| null | "League average for the statistical category being measured" |
| `dvpPosition` | string | `"PG"`,`"SF"`,`"QB"`,`"RB"` |
| `consensusProjection` | float \| null | "Consensus projection value for this market from various sportsbooks and prediction models" ⇒ **fair-value anchor** |
| `venue` | `{name, parkFactorRank, parkFactorPerc}` \| null | `parkFactorPerc` 100 = neutral, >100 hitter-friendly; `parkFactorRank` 1 = most hitter-friendly. Populated for NBA arenas too. |
| `startingPitcher` | object | MLB: `{id, firstName, lastName, hand: "L"\|"R"}`. **Non-MLB: object of EMPTY STRINGS with `hand: null`** (not null!) |
| `gameStats` | array | `[{season "2023-2024", location "home"/"away" (lowercase!), value float, date ISO, result "Over"/"Under", opponent{id,name,fullName}, dvpRank, venue{...}, position}]`. **Ordered newest-first.** `result` is "based on the current betting line". |
| `bestPrice` | object | `{line, price, book{id,name,abbr}}` on this page — **see §3.13 for the three competing shapes.** |

**[PROBE] `line` is optional**: `?line=0.5&gamesBack=10` → 5,921 B; no params → 147,457 B (full log). `?location=home&gamesBack=20` → 9,172 B.

#### `/marketSelections/{id}/metadata` — **[PROBE] 41 keys**
```
['event','team','opponent','locationType','player','market','position',
 'DVP','dvpRank','dvpAvg','dvpPosition','consensusProjection','venue','startingPitcher',
 'L1','L2','L3','L4','L5','L6','L7','L8','L9','L10','L11','L12','L13','L14','L15','L16',
 …'L20', 'season','vsOpponent','atLocationType', 'bestPrice', …]
```
**[PROBE] All 20 L-windows (L1…L20) are present**, plus `season`, `vsOpponent`, `atLocationType`, and (MLB) `vsStartingPitcher`, `vsStartingPitcherHand`, `atVenue`.

Stat-block shape: `{hits: int, hitPerc: float 0-100, stdev: float, mean: float, median: float [, count: int]}`.
Split-block shape: `{dataStartDate: ISO, currentSeason: "2024-2025", "<season>": {stat-block}, ..., all: {stat-block}}`.

### 🔴 **`hits` counts OVERS regardless of `position`.**
Doc: "Number of games where the player exceeded the betting line". Confirmed by the Dak Prescott sample: `position: "Under"`, `line: 237.5`, `L1: {hits: 0, mean: 133.0}` — 133 < 237.5 would be an *Under* hit, yet `hits=0`. **For an Under selection: `under_hits = count - hits`, `under_hitPerc = 100 - hitPerc`.**

With `playerAggStats=true` / `teamAggStats=true`, `player.aggregateStats` and `event.contestantHome/Away.aggregateStats` appear (**[PROBE]** `player` gains a 9th key `aggregateStats`; response 84.5 kB vs 9.0 kB filtered).

#### `/players/{id}/historicData` — **[PROBE] array of `{event, stats}`**
```json
[ { "event": {"id":"EVNT_…","sport":{"id":"SPRT_americanfootball","name":"American Football"},
              "league":{"id":"LGUE_nfl","name":"NFL","abbr":"NFL"},
              "name":"Dallas Cowboys @ Philadelphia Eagles","nameSpecial":null,
              "startTime":"2024-01-15T01:00:00Z","sportId":"SPRT_americanfootball","leagueId":"LGUE_nfl"},
    "stats": [ {"metric":{"id":"METR_passing_yards","name":"Passing Yards"},"value":312}, … ] } ]
```
"ordered chronologically by start time (**most recent first**)". **[PROBE] Observed counts:** Mahomes 49 games (141 kB), LeBron 223 (328 kB), Ohtani **477** (528 kB), an NBA player 213 (313 kB), Harry Kane (soccer) **0** ⇒ **soccer player game logs are empty**.

**`/teams/{id}/historicData` also exists and works** (undocumented) → 16 games for KC **[PROBE]**.

#### Injuries — **[PROBE] 5 keys**: `['player','team','status','event','played']`
* `player` = full 8-key Player; `team` = `{id,name,fullName,abbr}`; `event` = `{id,sport,league,name,nameSpecial,startTime[,sportId,leagueId]}`.
* **`status` is FREE TEXT** of form `"<Designation> - <description>"`: `"Questionable - Knee"`, `"Doubtful - …"`, `"Out - …"`, `"Probable - …"`, `"IR - …"`, and bare `"Day-To-Day"`. **The guide's uppercase enum (`OUT`/`DOUBTFUL`/…) and separate `description` field do not exist.** Parse by splitting on `" - "`.
* `played`: `true` = played despite the report, `false` = did not play due to injury, `null` = event hasn't happened / unknown.
* One row **per player-per-event** (Mahomes → 7 rows). `?league=NFL` → 434 rows (current designations only).

#### Trends — array of `TRND_` objects (**[PROBE] always empty for us**)
Documented shape: `{id, name ("Over 21.5 Points"), detail (LLM text, nullable — "Generated by the Pine insight service; may be null if generation failed"), confidence (0–100, blends hit rate + DVP rank + MLB park factor), player{…,headshot,position}, team{…,logo}, event{…}, marketSelection{id,type "PlayerProp",event,segment,proposition "Points",position "Over",metric,marketOffer MOFR_,market}, metadata{line (mode line across books), L5/L10/L15/L20 {hits,hitPerc}|null, hitChart [bool] last 15 **oldest-first**, hitChartPerc}}`. "Only trends whose underlying market selection is still available and whose data was refreshed in the last 48 hours are returned."

#### Aggregate stats
* **Team** `aggregateStats` / `seasonStats`: `{season "2024", stats{general{week, record "7-10", total_dvo