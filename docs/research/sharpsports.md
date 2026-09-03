# SharpSports — Definitive Ingestion Spec (provider: `sharpsports`)

**Vendor:** SharpSports (sharpsports.io) · **API version:** v1 · **Docs host:** `docs.sharpsports.io` (`/llms.txt`; every page fetchable as markdown by appending `.md`; MCP at `https://docs.sharpsports.io/mcp`)
**Support:** support@sharpsports.io · Discord discord.gg/sharpsports · dashboard `https://app.sharpsports.io`
**Products (one API surface):** **betPrices** (live odds), **historicData** (line history + player/team stats + injuries + trends), **betSync** (linked-account bet sync), plus betPlace (deep links), betContent (AI articles) and Pine AI whitelabel.

Legend used throughout:
- **[DOC]** = stated in the documentation mirror (reference / docs / changelog pages, incl. the U+FE0F-slug pages).
- **[LIVE]** = observed with our keys during the probe (2026-09-03T07:21–07:50Z, `server: nginx/1.31.5`), raw bodies under `samples/sharpsports/`.
- **[LIVE≠DOC]** = live behaviour contradicts the docs.
- **[UNKNOWN]** = not determinable from docs or probe; do not code assumptions.

---

# 1. Product & access summary

## 1.1 What we have (observed entitlements)

| Product | What it gives us | Entitlement observed |
|---|---|---|
| **betPrices** | Current odds for 12 odds-feed books (incl. **Pinnacle `pn`, Kalshi `kl`, Polymarket `pm`, PrizePicks `pp`, Underdog `ud`**) via `GET /prices`; selection/offer/market catalogue via `GET /marketSelections`, `GET /marketOffers`, `GET /markets` | ✅ **[LIVE]** private key: `/prices?league=MLB` → 146 events / 17.5 MB; `/prices?league=MLB&book=pn` → 10 events (Pinnacle) |
| **historicData** | Open/close line+odds history per book per selection (`/prices/historic/summary`, `/prices/historic/timeseries`), player & team game logs, aggregate stats, hit-rate metadata, injuries, trends | ✅ **[LIVE]** all `/prices/historic/*`, `/players/{id}/historicData`, `/teams/{id}/historicData`, `/marketSelections/{id}/historicData|metadata`, `/injuries` → 200. `/trends` → `[]` always (see §9) |
| **betSync** | Bettors, bettorAccounts, betSlips, refresh lifecycle, webhooks | ✅ **[LIVE]** `/betSlips` → 5 slips, `/bettors` → 3, `/bettorAccounts` → 5 (our own sandbox-style linked accounts incl. a Kalshi account) |
| **betPlace** | Deep links; gates `bookIds` + `betPlaceLinks` on every Price and `betPlaceAvailability` + `betPlaceUrls` on every MarketSelection | ✅ **[LIVE]** `bookIds`/`betPlaceLinks` present on **2888/2888** prices of one MLB event; `betPlaceUrls` present on live selections |
| **betContent / Pine AI** | AI articles (`/articles`), whitelabel chat provisioning | Not probed. `/articles` requires `league`+`dateCreated`; Pine provisioning returns 403 for sandbox accounts [DOC] |

**Key identity [LIVE]:** two keys — env `SHARPSPORTS_API_KEY` (public) and `SHARPSPORTS_API_SECRET` (private). Bettors in our account: `BTTR_af11e9d3a85448398f44bed220982eb5`, `BTTR_79b2cb59f3654ee788cc2e6b9ec0ea79`, `BTTR_2d98cc0af1124c43a64adf2c661068fe` (internalIds `user_3F5X…`, …).

## 1.2 Auth — `Authorization: Token <key>`

| Item | Value |
|---|---|
| Scheme | OpenAPI `apiKey` in header `Authorization`, `x-bearer-format: token`. Send literally **`Authorization: Token <key>`** [DOC]+[LIVE] |
| Bearer | **Does not work.** `Authorization: Bearer <key>` → **401** `{"detail":"Error decoding token."}` [LIVE] |
| No auth | **401** `{"detail":"Authentication credentials were not provided."}` + response header `www-authenticate: Token` [LIVE] |
| Public key | Reference/entity endpoints and client-side flows: `/books`, `/bookRegions`, `/sports`, `/leagues`, `/teams*`, `/players*` (incl. `/aggregateStats`), `/segments`, `/metrics`, `/markets*`, `/trades/{id}`, `POST /context*`, `POST …/refresh`, `PUT …/paused`, `PUT …/access`, **and `/bettorAccounts`** (returned 5 accounts with the public key — the "BetSync product" banner is not enforced there) [LIVE] |
| **Private key required** | `/events*`, `/marketSelections*`, `/prices*`, `/prices/historic/*`, `/injuries`, `/trends`, `/bettors*`, `/players/{id}/historicData`, `/hooks/logs`, `POST /{platform}/auth`, Pine. **[LIVE] 31 public-key requests → `403 {"detail":"Your private API key is required for this endpoint"}`**; `/betSlips` with the public key → `403 {"detail":"You do not have permission to perform this action."}` |
| Key formats | Docs show `public_sandbox_XXXXXXXXX`, `sk_test_…`, `sk_live_…`, and a 40-hex public key in the iOS SDK example. Treat as opaque; **never log** (redact to `***`). Strip whitespace: `K="$(printf '%s' "$SHARPSPORTS_API_SECRET" \| tr -d '[:space:]')"` |
| Ops rule | The key is a header, never a URL param → safe to log URLs; still never log headers. |

## 1.3 Base URL, modes

```
Base URL (sandbox AND live, identical): https://api.sharpsports.io/v1
Content-Type (writes):                  application/json
```
- Mode is selected by **which key you send**, not by host. Live mode "requires signing up for a paid plan" and issues a separate key pair; live "Requires use of private and public api keys" [DOC].
- Sandbox: a test bettor/bettorAccount with representative bet history; "Every time a refresh is performed on a BettorAccount, a few random live BetSlips on real markets will be generated" → sandbox slips reference **real** events/selections [DOC].
- Sandbox test users: `gooduser/Test1`, `realuser/Test2`, `2FAuser/Test6` (code `123456`), `changepassworduser/Test5`, `errorloginuser/Test3` [DOC].

## 1.4 Rate limits — exact numbers (all sources)

| Tier | Limit | Endpoints | Source |
|---|---|---|---|
| **General** | **50 requests/second** — *"Unless otherwise specified in the other Rate Limiting sections, all endpoints are rate-limited to 50 requests per second."* | everything not listed below | `reference/general-rate-limiting` [DOC] |
| **Large List** | **20 requests/second** — *"Certain endpoints have the potential to return large datasets and are throttled more aggressively"* | `GET /betSlips`, `GET /bettorAccounts/{id}/betSlips`, `GET /bettors/{id}/betSlips`, **`GET /marketSelections`**, **`GET /bookRegions`** | `reference/large-list-rate-limiting` [DOC] |
| Per-endpoint banner | **50 requests/second** *"due to real-time data intensity"* | `GET /marketSelections`, `GET /bookRegions`, `GET /betSlips` | endpoint pages [DOC] — contradicts the 20 rps tier page |
| Marketing claim | **100 requests/second with private key**, *"Unlimited daily requests"*, *"No additional charges for high volume"* | betPrices + historicData quickstarts | [DOC] |
| **Refresh (betSync)** | **1 request / 60 s per bettorAccount**; refresh "can take up to 2 minutes"; 429 while `refreshInProgress` | `POST /bettors/{id}/refresh`, `POST /bettorAccounts/{id}/refresh` | `reference/refresh-rate-limiting` [DOC] |

- **429 body (exact):** `{"detail":"Request was throttled."}` [DOC]. **Not reproduced in the probe** (never throttled across ~350 requests incl. bursts). Whether a `Retry-After` header accompanies it: **[UNKNOWN]**.
- **No rate-limit headers of any kind** on any response (no `X-RateLimit-*`, no `Retry-After`) [LIVE] — client-side token buckets are the only control.
- Refresh throttling is *not* an HTTP 429: the refresh call returns a normal 200 bucketed response with the `BACT_` id under `rateLimited`, and a RefreshResponse with `status: 429`, `detail: "Rate Limiting - Refresh for a given bettorAccount must be at least 1 minute apart"` is created [DOC].

**Implementation decision:** token bucket per endpoint class at the conservative documented figure — `/marketSelections`, `/bookRegions`, `/betSlips*` → **20 rps**; everything else → **50 rps**; refresh → 1/60 s per `BACT_`. In practice per-request latency (§1.7), not RPS, is the binding constraint.

## 1.5 Pagination — two mutually exclusive response shapes ⚠️

| Request style | Response shape |
|---|---|
| No `pageSize`/`pageNum` (optionally `limit=N`) | **bare JSON array** `[ {...}, ... ]` |
| **both** `pageSize` AND `pageNum` | **envelope** `{"objects": [...], "totalPages": N}` |

Confirmed [LIVE] on `/markets`, `/players`, `/events`, `/marketSelections`, `/injuries`. Variants:
- `/prices?eventId=` → **object** `{"eventId","markets"}`; `/prices?league=|sport=` → **array** of those objects. No pagination params.
- `/prices/historic/summary` and `/prices/historic/timeseries` → **object** `{"marketSelections":[...]}`; paginated summary → `{"marketSelections":[...],"totalPages":N}` (**not** `objects`).
- `/players/{id}/historicData`, `/teams/{id}/historicData` → always a **bare array**; `pageSize/pageNum` silently ignored (`?pageSize=10&pageNum=1` returned the full 49-game array, 141 019 B identical) [LIVE].

Rules [DOC]+[LIVE]:
- `pageNum` is **1-based** and *"Must be used with pageSize"*. Hard error: `/prices/historic/summary?…&pageSize=100` alone → `400 {"detail":"[ErrorDetail(string='Both pageNum and pageSize required for pagination', code='invalid')]"}`.
- `limit` is a **post-filter cap**, not a page size. Defaults: `/events` 500, `/marketSelections` 500, `/marketOffers` 500, `/refreshResponses` 500, `/hooks/logs` 500 (param literally spelled **`limt`**), `/betSlips` 50.
- `limit` **can exceed 500**: `/events?…&limit=1000` → **806** rows; same query without `limit` → exactly **500** (implicit cap) [LIVE].
- `pageSize=1000` works (`/markets?pageSize=1000&pageNum=1` → 1000 objects, `totalPages: 5`) [LIVE].
- **Out-of-range page is not an error:** `/markets?pageSize=5&pageNum=99` → 200 with 5 objects. Never terminate on an empty page; drive by `totalPages` [LIVE].
- No cursor/next token; no total count other than `totalPages`.

## 1.6 Error formats (all observed variants)

| Shape | Example | When |
|---|---|---|
| `{"detail": "<string>"}` 401 | `Authentication credentials were not provided.` / `Error decoding token.` | missing / Bearer auth |
| `{"detail": "<string>"}` 403 | `Your private API key is required for this endpoint` / `You do not have permission to perform this action.` | wrong key kind |
| `{"detail": "<string>"}` 400 | `Query would generate approximately 1440 windows, which exceeds the maximum allowed of 1000. Please use a larger rollup interval or smaller time range.` | timeseries window cap |
| `{"detail": "<string>"}` 400 | `Query would return more than 2000 market selections. Please narrow the filter (e.g. tighter eventStartTime range, a more specific player/team, or set type/proposition), or split the request into multiple narrower queries.` | summary cardinality cap |
| `{"detail": "<string>"}` 404 | `No offers found for market selection MRKT_00000000000000000000000000000000` | timeseries on unknown / price-less selection (also for selections whose event predates price history) |
| `{"detail": "[ErrorDetail(string='…', code='invalid')]"}` 400 | pagination misuse | DRF serializer repr leaked |
| **bare JSON string** 400 | `"Invalid league"`, `"Invalid sport"`, `"Invalid query parameter: proposition"`, `"MarketSelection is not available"`, `"At least one of the following query parameters is required: ['eventId', 'sdioEventId', 'sportradarEventId', 'oddsjamEventId', 'theOddsApiEventId']"` | validation on `/markets`, `/trends`, `/prices`, `/marketSelections/{id}/historicData`, `/marketOffers` |
| **HTML** 404 `text/html` | `<!doctype html>…<title>Not Found</title>…` | malformed path id, e.g. `/marketSelections/MSEL_x/metadata` |
| `{"error","message","suggestion","docs","help"}` 404 | documented on `/books` | [DOC] only, never observed |
| `{"detail":"Request was throttled."}` 429 | | [DOC] only |

**Parser must handle: object-with-`detail`, bare string, and HTML.** Never `json.loads` blindly on non-2xx; check `content-type`.

## 1.7 Observed payload sizes & latency (capacity planning) [LIVE]

| Request | Size | Latency |
|---|---|---|
| `/prices?league=MLB` (12 books, 146 events incl. 18 futures containers, 29 854 prices) | **17.5 MB** | 2.06 s |
| `/prices?league=LGUE_mlb` (same, id form) | 17.55 MB | 2.84 s |
| `/prices?sport=baseball&book=dk` | 4.58 MB, 16 events | 2.39 s |
| `/prices?league=EPL&book=dk,fd` | 4.46 MB, 20 events | 1.14 s |
| `/prices?league=MLB&book=pp,ud` (DFS) | 3.78 MB, 9 events, 7 237 prices | 5.34 s |
| `/prices?league=MLB&book=kl,pm` (prediction markets) | 1.88 MB, 97 events, 3 151 prices | 6.87 s |
| `/prices?league=MLB&book=pn` (Pinnacle) | 0.34 MB, 10 events, 724 prices | 6.37 s |
| `/prices?eventId=<one MLB game>` (67 markets, 703 selections, 2 888 prices) | **1.67 MB** | **0.28 s** |
| `/prices?eventId=…&book=dk` | 0.39 MB, 21 markets | 0.41 s |
| `/marketSelections?eventId=…&limit=500` | 1.05 MB | 5.26 s |
| `/marketSelections?eventId=…&pageSize=50&pageNum=1` | 0.11 MB | 1.2–2.9 s |
| `/marketOffers?eventId=…` (361 offers) | 0.53 MB | 2.13 s |
| `/marketSelections?league=LGUE_mlb&limit=5` | 11.6 kB | **21.9 s** (!) ; with `type=prop` **32.3 s** |
| `/prices/historic/summary?eventId=…` (unpaged, 761 selections) | 0.73 MB | 13.3 s |
| `/prices/historic/summary?eventId=…&pageSize=100&pageNum=1` | 0.12 MB | 1.1 s (page 2: 4.0 s) |
| `/prices/historic/summary?eventId=<past NBA 2026 game>&pageSize=20&pageNum=1` | 27 kB | **98.2 s** |
| `/prices/historic/summary?player=<Mahomes>&2024 season&pageSize=100&pageNum=1` | 0.18 MB | **97.7 s** |
| `/prices/historic/summary?team=…&1 month&proposition=spread` | 0.10 MB, 56 sels | **54.5 s** |
| `/prices/historic/summary?player=<LeBron>&full season&proposition=total&position=Over` | — | **TIMEOUT > 120 s** (×2) |
| `/prices/historic/timeseries` (1 selection) | 4–310 kB | 0.2–3.3 s |
| `/players/{id}/historicData` (Mahomes 49 games / Ohtani 477 games) | 141 kB / 528 kB | 0.8 s / 10.7 s; **14–24 s** whenever any query param is appended |
| `/injuries?league=NFL` (434 rows) | 264 kB | 3.4 s |
| `/bookRegions` (1 557 rows) | 379 kB | 1.4 s |
| `/markets?pageSize=1000&pageNum=1` | 448 kB | 1.9 s |
| `/events?league=LGUE_mlb&2-month range&limit=1000` (806 rows) | 544 kB | 10.4 s |

**Conclusion:** per-league `/prices` is multi-MB and 2–7 s; per-event `/prices` is 0.3 s / 1.7 MB and is the hot-path primitive. Never use league-scoped `/marketSelections` or player/team-scoped historic summaries in any latency-sensitive path.

---

# 2. Complete endpoint catalogue

Notation: **Auth** = key kind (Pub/Priv). **RL** = documented rate tier. **LS** = live status in the probe (✅ 200 · ⛔ 403 with public key · 🚫 error · — not probed). All paths relative to `https://api.sharpsports.io/v1`. All list responses are bare arrays unless paged (§1.5).

## 2.1 Prices (betPrices) — Priv

| Method | Path | Purpose | Params (type · notes) | Pagination | RL | LS |
|---|---|---|---|---|---|---|
| GET | `/prices` | Current prices, 5-level nesting event→market→offer→selection→book→prices. **One of `eventId`, `sport`, `league` required.** | `eventId` (str, `EVNT_…`, comma-sep; acts as a filter when combined with sport/league) · `sport` (`SPRT_…` id **or** name e.g. `baseball`) · `league` (`LGUE_…` id **or** abbr `MLB`/`mlb`/`EPL`) · `marketId` (`MKT_…`, comma-sep) · `book` (`BOOK_…` id **or** 2-char abbr, comma-sep e.g. `dk,fd`) | none | 50 rps (quickstart: 100) | ✅ Priv / ⛔ Pub |
| GET | `/prices/historic/summary` | First/last (open/close) price per book per selection over the selection's whole history | **mode A** `marketSelectionId` (`MRKT_…`) · **mode B** `eventId` · **mode C** `player` (`PLYR_…` or name) **or** `team` (`TEAM_…` or name) **+ `eventStartTimeStart`** (ISO 8601, required) · `eventStartTimeEnd` (default now) · filters `position` (`Over`/`Under`/…) · `type` (`straight`/`prop`) · `proposition` · `pageNum` (int ≥1) · `pageSize` (doc default 50 max 100; probe accepted 100) | both-or-neither → `totalPages` | 50 rps | ✅ Priv / ⛔ Pub |
| GET | `/prices/historic/timeseries` | Windowed open/close series for ONE selection | `marketSelectionId` (**required**) · `timeseriesStart`, `timeseriesEnd` (ISO 8601) · `rollup` ∈ `5m,15m,1h,4h,1d` | none | 50 rps | ✅ Priv / ⛔ Pub |
| GET | `/prices/historic` | **Legacy path described in the historic-odds guide.** Routed (403 with public key) but never returned 200; the real endpoints are the two above. Do not use. | — | — | — | ⛔ only |

**Probe findings for `/prices`:**
- **`proposition` is NOT a valid param**: `/prices?eventId=…&proposition=spread` → `400 "Invalid query parameter: proposition"` [LIVE≠DOC quickstart]. Filter by `marketId` (resolve via `/markets`) or client-side.
- `league` accepts `MLB`, `mlb`, `LGUE_mlb` (byte-near-identical results) [LIVE].
- Unknown `marketId` → 200 `{"eventId":…,"markets":[]}`; past events → 200 with `markets: []` (prices are **live-only**; confirmed on NFL 2022/2023, NBA 2024/2026, EPL past) [LIVE].
- `/prices?league=mlb` returned `[]` in one pass and 146 events in another → an empty array means "no live slate", not an error.
- League-scoped snapshots **include futures container events** (18 of 146 MLB "events" carried only `Future Winner` / `Future Team Prop Total Wins` markets) [LIVE].

## 2.2 MarketSelections / MarketOffers / Markets

| Method | Path | Auth | Purpose | Params | Pagination | RL | LS |
|---|---|---|---|---|---|---|---|
| GET | `/marketSelections` | Priv | One row per side/outcome; vendor ids; betPlace availability; optional `lineAvailability`/`metadata` | `eventId` · `sport` · `league` · `market` (`MKT_` id or name) · `marketOffer` (`MKTO_`) · `type` ∈ `straight,prop` · `proposition` · `segment` (`SEGM_` id or name) · `position` (positionId or `Over`/`Under`) · `team`, `player`, `metric` (props only; id or name) · `line` (float) · `minOdds`, `maxOdds` (int American; server picks the qualifying line; "DFS books are excluded") · `prices` (bool, doc default true — **no effect observed**, §3.5) · `lineAvailability` (bool) · `metadata` (bool) · `teamAggStats`, `filteredTeamAggStats`, `playerAggStats`, `filteredPlayerAggStats` (bool) · `future` (bool, default false) · `historic` (bool, default false — required to see past-event selections) · `limit` (default 500, ordered by `timeCreated`) · `pageSize`, `pageNum` · vendor filters `sdioMarketId`, `sdioEventId`, `sportradarEventId`, `sportradarMarketId`, `oddsjamEventId`, `oddsjamMarketId`, `theOddsApiMarketId`, `theOddsApiEventId` | limit + pageSize/pageNum → `{"objects","totalPages"}` | **20 rps** | ✅ Priv / ⛔ Pub |
| GET | `/marketSelections/{marketSelectionId}` | Priv | One selection | `lineAvailability` (bool) · `line` (float) · `prices` (bool) | n/a | 50 | ✅ |
| GET | `/marketSelections/{id}/historicData` | Priv + historicData | Game log vs a line + DVP/park/pitcher context + bestPrice | `line` (float; doc **required**, **[LIVE] optional** — omitted → full log at bestPrice line) · `gamesBack` (int) · `location` ∈ `home,away` · `opponent` (`TEAM_`) · `gamesWithout` (`PLYR_` not on roster). Guide-only, unverified: `home`,`away`,`pitcher`,`vsOpponent`,`vsStartingPitcher`,`vsStartingPitcherHand`,`winningMargin`,`seasonType` | none | 50 | ✅ |
| GET | `/marketSelections/{id}/metadata` | Priv + historicData | L1…L20/season/split hit-rates, DVP, park factor, starting pitcher, consensusProjection, bestPrice, optional aggregate stats | `line` (doc required; works with it) · `seasonType` ∈ `PRE,REG,POST` · `teamAggStats`, `filteredTeamAggStats`, `playerAggStats`, `filteredPlayerAggStats` (bool) · `gamesBack` (int) · guide-only `teamAggStatsSeason`, `playerAggStatsSeason` | none | 50 | ✅ |
| GET | `/marketOffers` | Priv | Market × Event (× player/team) grouping rows | **one of `eventId`, `sdioEventId`, `sportradarEventId`, `oddsjamEventId`, `theOddsApiEventId` is REQUIRED [LIVE]** · `proposition` · `segment` · `team` · `player` · `metric` · `sport` · `league` · `market` · `future` · `sdioMarketId` · `sportradarMarketId` · `oddsjamMarketId` · `limit` (500) · `pageSize`, `pageNum` | limit + pageSize/pageNum | 50 | ✅ with `eventId` (361 offers) / 🚫 400 without |
| GET | `/marketOffers/{marketOfferId}` | Priv | One offer (doc page slug `marketselection-detail-copy`) | none | n/a | 50 | — |
| GET | `/markets` | **Pub** | Market **definitions** (templates) | `name` · `type` ∈ `prop,straight` · `proposition` · `segment` · `metric` · `player`, `team`, `future` (bool) · `sport` · `league` · `sdioMarketId` · `sportradarId` · `oddsjamId` · `theOddsApiId` · `pageSize`, `pageNum` | pageSize/pageNum works; unpaged caps at 500 | 50 | ✅ (`pageSize=1000` → `totalPages: 5`) |
| GET | `/markets/{marketId}` | **Pub** | One definition | none | n/a | 50 | ✅ |

**Probe findings:**
- **League filter casing is per-endpoint.** `/markets?league=nfl` → `400 "Invalid league"`; `/markets?league=NFL` and `?league=LGUE_nfl` → 223 markets (byte-identical). `/teams?league=nfl` and `/players?league=nba` → **`[]` silently**; `LGUE_nfl`/`NFL` → 32 teams, `LGUE_nba` → 611 players. **Always pass `LGUE_*` ids (or UPPERCASE abbr) to `/markets`, `/teams`, `/players`.** `/prices` and `/events` accept lowercase. Silent-empty is a data-loss trap.
- `/sports?name=basketball` → `[]` (filter is case-sensitive / expects `Basketball`).
- `/markets?theOddsApiId=h2h` → 7 markets (MLB/NFL/NHL/NBA/NCAAMB/WNBA/NCAAF Moneyline) ⇒ The Odds API market-key reverse lookup works.
- `/marketSelections?theOddsApiEventId=none` → `[]` (no error).
- `historic=true` is required for past events; historic rows omit `betPlaceAvailability`/`betPlaceUrls` (16 keys vs 18) [LIVE].
- `/marketSelections/{id}/historicData` on a past selection → `400 "MarketSelection is not available"`; malformed id (`MSEL_x`) → **HTML 404**.
- `metadata=true` on the list endpoint returned `"metadata": {}` (empty object) for the two prop selections sampled — pass `line` or use the detail endpoint [LIVE].
- `minOdds/maxOdds` and `line` filters return the normal 18-key rows (no ladder is attached) [LIVE].

## 2.3 Events — Priv

| Method | Path | Purpose | Params | Pagination | RL | LS |
|---|---|---|---|---|---|---|
| GET | `/events` | Event list | `sport` (`SPRT_` or name) · `league` (`LGUE_` or abbr, any case) · `future` (bool, default false) · `upcoming` (bool, **default true**) · `startTimeStart`, `startTimeEnd` (`%Y-%m-%dT%H:%M:%S` or `%Y-%m-%d`) · `limit` (default 500, ordered by `startTime`) · `pageSize`, `pageNum` · `ascending` (bool; doc "default true" **but live default order is DESCENDING**) · vendor lookups `sportsdataioId`, `sportradarId`, `oddsjamId`, `theOddsApiId` | limit + pageSize/pageNum | 50 | ✅ Priv / ⛔ Pub |
| GET | `/events/{id}` | One event | none | n/a | 50 | ✅ |

**Probe findings [LIVE]:**
- **Default sort is DESCENDING by `startTime`** in every list sampled (`sk_events_nfl_upcoming` 2027-01-10 → 2026-12-21; `sk_events_mlb_3d` 09-07 → 09-03; `sk_events_limit_cap` 09-01 → 07-01). Consequence: `upcoming=true&limit=50` on NFL returned the **last 50 games of the 2026 season (2026-12-21 … 2027-01-10)**, not the next 50 — this is what looked like "date filters ignored / 2027 events". Pass `ascending=true` explicitly.
- `startTimeStart/startTimeEnd` date-only values behaved as inclusive day bounds (`2026-09-03..2026-09-04` → 2026-09-03T23:00Z … 2026-09-04T23:40Z on page 1 of 2, sorted desc).
- `future=true` returns futures container events (`"Super Bowl 2024/25"`, `"MVP 2024/25"`, `"Defensive Player of the Year 2024/25"`, startTimes 2023-10-01 … 2025-02-09, `sportsdataioId: "1230"`, `contestantAway/Home: null`, `startDate: null`) **even though `upcoming` defaults to true** — `upcoming` is not applied to futures.
- `upcoming=false` + date range reaches back to **2015-09** (NFL), **2018-10** (NBA), **2019-04** (MLB), **2019-08** (EPL) — 5 events each ⇒ event history depth ≥ 2015.
- `sportradarId=5750e479-d408-4b22-806b-94fba622a3e3` → exactly 1 event ⇒ Sportradar reverse lookup works. `theOddsApiId=x` → `[]`.
- `sport=SPRT_esports` → `[]`. `startTime` **can be null** (15 NBA 2026-27 preseason events, all `startTime: null`); `league`/`leagueId`/contestants **can be null** (26 US Open tennis matches: `league: null`, `nameSpecial: "US Open"`).
- Live Event has **18 keys** incl. undocumented `seasonType` and `venue` (string).

## 2.4 Reference entities (Pub unless noted)

| Method | Path | Purpose | Params | Pagination | RL | LS |
|---|---|---|---|---|---|---|
| GET | `/books` | Sportsbook catalogue incl. **`oddsFeedActive`** | `support` (bool → adds `sdkSupport`) · `name` · `abbr` · `status` ∈ `active,inactive,coming,unsupported` (**default `active`**) | none | 50 | ✅ 15 active · 0 inactive · 0 coming · 10 unsupported |
| GET | `/bookRegions` | Book × US state / CA province | `abbr` (2-char region) · `status` (default active) · `book` (id/abbr/name) · `support` (bool) | none | **20** | ✅ **1 557** rows; `?book=dk` 65; `?book=kl` 64 |
| GET | `/bookRegions/{id}` | One | none | n/a | 50 | — |
| POST/DELETE | `/books/{id}/affiliateLink`, `/bookRegions/{id}/affiliateLink` (Priv) | Affiliate link mgmt | body `{"affiliateLink": url}` | n/a | 50 | — |
| GET | `/sports` | Sports | `name` (case-sensitive) | none | 50 | ✅ **20** |
| GET | `/leagues` | Leagues | `sport` · `region` · `abbr` | none | 50 | ✅ **138** (99 soccer); `?abbr=EPL` → 1 |
| GET | `/teams` | Teams | `sport` · `league` (**`LGUE_`/UPPER**) · `name` | none | 50 | ✅ NFL 32, MLB 30, EPL 27, WNBA 15 |
| GET | `/teams/{id}` | One team | none | n/a | 50 | ✅ |
| GET | `/teams/aggregateStats` | Teams + season stats | `season` · `metrics` (comma) · `sport` · `league` · `name` · `pageSize` · `pageNum` · `limit` | pageNum/pageSize + limit | 50 | ✅ |
| GET | `/teams/{id}/aggregateStats` | One team + season stats | `season` · `metrics` | n/a | 50 | — |
| GET | `/teams/{id}/historicData` | **UNDOCUMENTED, live**: team game log `[{event, stats[]}]` | none observed | none | 50 | ✅ 16 games (KC, 2025 season only) |
| GET | `/players` | Players | `sport` · `league` (`LGUE_`/UPPER) · `team` · `name` (first/last/full, partial) · `isMajorLeague` ∈ `true,false,all` (**default true**, MLB) · `pageSize`, `pageNum` · `previousTeam` (bool → adds `previousTeam`, `changeDate`) | pageSize/pageNum | 50 | ✅ |
| GET | `/players/{id}` | One player | none | n/a | 50 | ✅ |
| GET | `/players/aggregateStats` | Players + season stats with threshold screening | `season` · `metrics` · `position` · `sport` · `league` · `team` · `name` · `previousTeam` · `pageSize` · `pageNum` · `limit` · `games_played_gte/lte` (need `position`) · dynamic `<metric>_<total\|per_game>_<gte\|lte>` (need `position`) | pageNum/pageSize + limit | 50 | ✅ |
| GET | `/players/{id}/aggregateStats` | One player + season stats | `season` · `position` · `metrics` | n/a | 50 | ✅ |
| GET | `/players/{id}/historicData` (Priv + historicData) | Player game log, all seasons, `[{event, stats[]}]` | **docs: none.** [LIVE] `gamesBack` works (5 of 223); `season`, `startDate/endDate`, `pageSize/pageNum` accepted but **ignored**; `seasonType=POST` → `[]` | none | 50 | ✅ Priv / ⛔ Pub |
| GET | `/segments` | Segments | `name` · `abbr` | none | 50 | ✅ **95** |
| GET | `/metrics` | Metrics | `name` | none | 50 | ✅ **278** |
| GET | `/trades/{TEAM_id}` | Players who joined/left a team in the **last 30 days** | `injuries` (bool) · `pageSize` · `pageNum` · `limit` | pageNum/pageSize + limit | 50 | ✅ 72 players; `injuries=true` → 63 rows, each gains `injury` |
| GET | `/injuries` (Priv + historicData) | Player-event injury rows with `played` outcome | `player` (`PLYR_` or full name) · `team` (`TEAM_` or name) · `league` (abbr or `LGUE_`; **restricts to players currently carrying a designation**) · `pageSize` · `pageNum` · `limit`; guide-only unverified `event`, `status`, `played` | pageNum/pageSize → `{"objects","totalPages"}` + limit | 50 | ✅ NFL 434 rows; MLB paged `totalPages: 14` |
| GET | `/trends` (Priv + historicData) | Scored player-prop trends (48 h) | `league` · `sport` · `pageSize` · `pageNum` · `limit` | pageNum/pageSize + limit | 50 | ✅ but **always `[]`** (no filter, NFL, MLB); `?sport=basketball` → `400 "Invalid sport"` |

## 2.5 betSync (bettors / accounts / slips / refresh) — Priv unless noted

| Method | Path | Purpose | Params | Pagination | RL | LS |
|---|---|---|---|---|---|---|
| GET | `/betSlips` | **Account-wide** feed of all synced slips | `refreshResponse` (`RRES_`) · `book` · `abbr` · `status` ∈ `pending,completed` · `limit` (default **50**, ordered by `timePlaced`) · `pageSize` · `pageNum` · `timePlacedStart/End` · `dateClosedStart/End` · `timeClosedStart/End` · `type` ∈ `single,parlay` · `adjustedAtRisk`, `adjustedOdds`, `adjustedLine` (bool) · `sport` · `league` · `eventStartTimeStart/End` · `betType` (`straight`/`prop`) · `segment` · `proposition` · `position` · `team` · `player` · `metric` · `outcome` ∈ `win,loss,push,void,cashout,halfwin,halfloss` | limit/pageSize/pageNum | **20** | ✅ Priv (5) / ⛔ Pub |
| GET | `/betSlips/{betSlipId}` | One slip | (vestigial list filters in OpenAPI) | n/a | 50 | — |
| GET | `/bettors/{id}/betSlips` | Slips per bettor (`id` = `BTTR_` **or** our `internalId`) | as `/betSlips` minus `refreshResponse` | limit(50)/pageSize/pageNum | 20 | — |
| GET | `/bettorAccounts/{id}/betSlips` | Slips per account | as `/betSlips` | same | 20 | — |
| GET | `/bettors/{id}/betSlips/statistics` | Aggregates: total / by league / by book / by slipType (`single,parlay,teaser,live,future`) / `timeSeries` | `league` (comma) · `startTime` · `endTime` · `timezone` | n/a | 50 | — |
| GET | `/bettors/{id}/betSlips/summary` | yesterday/week/month/today/tomorrow rollups | `timezone` (e.g. `America/New_York`) | n/a | 50 | — |
| GET | `/bettors` | Bettor list | `limit` (ordered `timeCreated` desc) · `pageSize` · `pageNum` | limit/pageSize/pageNum | 50 | ✅ 3 bettors (4 keys each; no `metadata`) |
| GET | `/bettors/{id}` | Bettor detail | `metadata` (bool) · `timePlacedStart/End` · `league` · `sport` · `type` · `adjusted*` | n/a | 50 | — |
| GET | `/bettors/{id}/metadata` | handle/unitSize/netProfit/winPercentage/totalAccounts | `timePlacedStart/End` · `timeClosedStart/End` · `league` · `sport` · `type` · `adjusted*` · `proposition` · `position` · `betType` · `refreshResponseId` · `timeSeriesRollup` (int days) | n/a | 50 | — |
| POST | `/bettors/{id}/refresh` (**Pub**) | Refresh all accounts of a bettor (async) | `auth` (mobile SDK) · `extensionVersion` (chrome ext) · `reverify=true` (prose only) | n/a | 1/60 s per `BACT_` | — |
| GET | `/bettorAccounts` | Account list | `access`, `verified`, `isUnverifiable` (bool) · `limit` · `pageSize` · `pageNum` · `book` · `bookRegion` | limit/pageSize/pageNum | 50 | ✅ **both keys** (5) |
| GET | `/bettors/{id}/bettorAccounts` | Accounts of a bettor | none | n/a | 50 | — |
| GET | `/bettorAccounts/{id}/metadata` | handle/unitSize/netProfit/winPercentage/walletShare | as bettor metadata + `timeSeriesRollup` | n/a | 50 | — |
| POST | `/bettorAccounts/{id}/refresh` (**Pub**) | Refresh one account | `auth` · `extensionVersion` · `reverify=true` | n/a | 1/60 s | — |
| PUT | `/bettorAccounts/{id}/paused` (**Pub**) | Pause syncing | body `{"paused": bool}` | n/a | 50 | — |
| PUT | `/bettorAccounts/{id}/access` (**Pub**) | Revoke access (stops billing; **irreversible via API**) | body `{"access": bool}` | n/a | 50 | — |
| GET | `/refreshResponses`, `/bettors/{id}/refreshResponses`, `/bettorAccounts/{id}/refreshResponses` | Refresh results (embed slips) | `requestId` · `status` (int) · `limit` (default **500**) · `pageSize` · `pageNum` · `timeCreatedStart/End` | limit/pageSize/pageNum | 50 | — |
| GET | `/refreshResponses/{id}` | One (page not mirrored) | — | n/a | 50 | — |

## 2.6 Contexts / SDK / webhooks / misc

| Method | Path | Auth | Purpose | Params |
|---|---|---|---|---|
| POST | `/context` | Pub | betSync linking context → `{"cid": …}`; UI `https://ui.sharpsports.io/link/{cid}` | body `internalId` (**required**, immutable per bettor) · `redirectUrl` · `uiMode` ∈ `dark,light,system` · `extensionAuthToken` · (quickstart also shows `webhookUrl`) |
| POST | `/context/selection` | Pub | betPlace context (tail a slip / build a parlay link) | `internalId` (req) · `betSlip` (`SLIP_`) · `marketSelection` (`MRKT_`, comma-sep for parlay) · `bookAbbr` · `line` (float) |
| POST | `/context/bestPrice` | Pub | bestPrice widget → `https://ui.sharpsports.io/best-price/{cid}` | `internalId` (req) · `extensionAuthToken` · `uiMode` |
| POST | `/{platform}/auth` (`mobile`\|`extension`), `/mobile/auth` | Priv | SDK auth token `{"token": …}` (per internalId, **no TTL**) | body `{"internalId"}` |
| GET | `/hooks/logs` | Priv | Webhook delivery logs | **`limt`** (sic, default 500) · `pageSize` · `pageNum` · `status` (int) · `event` · `requestId` · `url` · `eventObject` · `timeCreatedStart/End` |
| GET | `/articles` | Priv | betContent AI articles | `league` (**required**, abbr) · `dateCreated` (**required**, `YYYY-MM-DD`) |
| GET | `/articles/{id}` | Priv | Article detail (quickstart only) | — |
| POST | `/pine/partner/provision-user` | Priv | Pine whitelabel user mgmt (403 for sandbox) | `action` ∈ `provision,deprovision,update_limits` · `email` (req) · `result_url` · `pro_monthly_chat_limit` · `lite_monthly_chat_limit` |
| — | `ui.sharpsports.io/place/<MRKT_>/<bookabbr\|BOOK_>[?line=<line>]` | — | betPlace deep link (main or alt line) | — |
| — | `ui.sharpsports.io/place/parlay/<BOOK_>?marketSelection=a,b&line=x,,null` | — | Parlay deep link | — |

**Webhooks (push, betSync only) [DOC]:** events `bettor.created`, `bettorAccount.verified`, `bettorAccount.unverified`, `bettorAccount.inaccessible`, `refreshResponse.created` (logged lowercased, e.g. `refreshresponse.created` — match case-insensitively). Payload `{"event": "<name>", "sender": "<app>", "data": {...}}` (quickstart shows `type`/`data` — treat discriminator as `event` **or** `type`). Headers `Hook-HMAC` (base64 HMAC-SHA256 of the **raw** body) and `Hook-Subscription` (uuid). Must return 200 within **10 s**; process asynchronously. No timestamp/replay header. Secret + `hmac_digest` (`"sha256"`) from the list-subscriptions endpoint (page not mirrored).

---
