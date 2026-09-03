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
# 3. Data model & ID schemes

## 3.1 ID prefix table (all prefixes, real examples)

| Prefix | Entity | Suffix format | Real examples |
|---|---|---|---|
| `EVNT_` | Event | 32 lowercase hex (one doc example is 22-char base64url — treat as opaque) | `EVNT_533e7e58b7554f03bdc23d39183a25ec` (SF @ PIT 2026-09-03) · `EVNT_c4f434ec6ffa4c4e86740b082e41e5de` (NFL 2022-09-13) · `EVNT_cb741a0b42024afebf3bb0f1e71db01d` (NBA 2024-01-17) · `EVNT_9f163242d6ef42fcad88dcdaf6573eae` (MLB 2025-08-03) · `EVNT_add0d45e52c14ab1bc90976b26ff59e8` ("Super Bowl 2024/25" futures container) · `EVNT_G6JvTtYoTriXos41COV2Qw` (doc) |
| `MKT_` | Market (definition/template) | 32 hex | `MKT_945039fb0b3b49c18b27f69d98826ee6` (MLB Moneyline) · `MKT_2e8cad9c0dd14981b13355ded37b2811` (Player Prop Total Hits + Runs + RBIs) · `MKT_c279ec8a05bc4107a4a0d7f5c39efdab` (1st Half Player Prop Total Interceptions) · `MKT_091a1d75cd3643f499f9c2443ca00110` (NFL Moneyline) |
| `MKTO_` | MarketOffer (Market × Event [× player/team]) | 32 hex | `MKTO_83cdfa792a15435382cfdda1b8fe1881` · `MKTO_1c568fff39e54f129a6f91263dae0195` · `MKTO_7923320384ec4e5cae5166756fe6ffb0` |
| `MOFR_` | MarketOffer — **alternate prefix only in the trends doc sample** | 32 hex | `MOFR_1234567890abcdef1234567890abcdef` (never observed live) |
| `MRKT_` | **MarketSelection** (one side/outcome) — the pricing key | 32 hex | `MRKT_51d96e2856b145288d67a3e31efaf969` (SF ML) · `MRKT_7cd1e43612c34ab691fea9843d153c82` (Devers H+R+RBI Over) · `MRKT_d397f871383d43e8ab2c50e606cbd657` (MIN ML, NFL 2025-09-09) · `MRKT_a0772b024d094d7d84a3a33f96b710f3` (NBA 2026-04-04) · `MRKT_497f0815d53a4ba487b80bc87624b2a7` (NFL 2022, no price history) |
| `MSEL_` | **DOES NOT EXIST** — appears only in the historic-endpoint docs as the alleged prefix | — | `MSEL_x` → `404 {"detail":"No offers found for market selection MSEL_x"}` [LIVE: doc error; use `MRKT_`] |
| `PRICE_` | Price (only on `bestPrice`) | 32 hex | `PRICE_107af8b2975b411182cd06910a942ce1` · `PRICE_9382dde4d12c4b1e9a6c56e2abfe1ba8` [LIVE] |
| `BOOK_` | Book | **opaque**: 32 hex OR 20–22-char base64url | `BOOK_nhLZ9l5DRs6w6KcE2n7vnw` (dk) · `BOOK_Rf7xRhS7TKQUl94Xkt5w` (fd) · `BOOK_pPg9ABaPSj2mL6qoMTKR1A` (mg) · `BOOK_IPBQaQQTCRxplZx7SYOA` (ca) · `BOOK_9e939c6df6e54dde8b7d01abdbf65e0a` (kl) · `BOOK_ae54ed82802c445aa8dac91da2782010` (pm) · `BOOK_f6162b9d2dfc4403941994e7c045185d` (pn) · `BOOK_88064cc6787c47ccbd4bbb036c7f55c5` (br) |
| `BRGN_` / `BSTA_` | BookRegion (**both prefixes live**) | opaque | `BRGN_d9761788a0a34a8ca3ad449154017bc1` (Kalshi/Alabama) · `BRGN_030310933f2b4044b34bb80c0c69563c` · `BSTA_Okuj8vPwRPSMnYhROBE1Uw` |
| `TEAM_` | Team | 32 hex | `TEAM_8bfd1dfe1a09451195d19c792ea18567` (KC Chiefs) · `TEAM_1ca192c8818c464c893d0f13e3d89875` (SF Giants) · `TEAM_9fc4458cf19c48cebe8802a9b2ea69f4` (PIT Pirates) · `TEAM_a0eb40989b7144b9b3dbed5370b5382a` (LA Dodgers) · `TEAM_7ab6eb241f3e440ab8c6d771fb0694a9` (PHI Eagles) |
| `PLYR_` | Player | 32 hex | `PLYR_9e93378b8a0440a1a79131e56bc2ca88` (Patrick Mahomes) · `PLYR_55eae5de659045bb85ec3e9bac905fb2` (LeBron James) · `PLYR_b17ad16784c84a01a8afcd0846e10357` (Ohtani) · `PLYR_57e3df49b3854a839d72beca67ba929c` (Rafael Devers) · `PLYR_0472337baea34f86bed7cc14d7e1fd34` (Harry Kane) |
| `SPRT_` | Sport | **slug** | `SPRT_baseball`, `SPRT_basketball`, `SPRT_americanfootball`, `SPRT_icehockey`, `SPRT_soccer`, `SPRT_tennis`, `SPRT_mma`, `SPRT_golf`, `SPRT_auto`, `SPRT_esports` … (20 total, §3.8) |
| `LGUE_` | League | **slug for 45 leagues, 32 hex for 93** | `LGUE_mlb`, `LGUE_nfl`, `LGUE_nba`, `LGUE_nhl`, `LGUE_ncaaf`, `LGUE_ncaamb`, `LGUE_wnba`, `LGUE_ufc`, `LGUE_f1`, `LGUE_milb` · `LGUE_542b6c4f1c7f4a0da7154747c76e7340` (EPL) · `LGUE_6f8a50498ff14a97ad58f47b184116c4` (Leagues Cup) |
| `SEGM_` | Segment | short code | `SEGM_M` Match · `SEGM_1H` · `SEGM_1Q` · `SEGM_1P` · `SEGM_1I` · `SEGM_F5I` (1st 5 Innings) · `SEGM_S1` (Set 1) · `SEGM_S1G3` (Set 1 Game 3) · `SEGM_R1` (Round 1) — 95 total |
| `METR_` | Metric | slug, **inconsistent style** | `METR_points`, `METR_passyds`, `METR_hitsrunsrbis`, `METR_homeruns`, `METR_pitcherstrikeouts` (catalogue) — but also `METR_completionpercentage`, `METR_passingairconversionratio`, `METR_wrc_plus`, `METR_plateappearances` inside game logs / aggregate stats. **Opaque; resolve via `/metrics` (278) and stat `metric_id` fields.** |
| `TRND_` | Trend | 32 hex | `TRND_3f1a7c8e4b2d4e9a8c1f5d6b7e8a9c0d` (doc only; `/trends` always `[]` for us) |
| `BTTR_` | Bettor | 32 hex OR 22-char base64 (**may contain `+`**) | `BTTR_af11e9d3a85448398f44bed220982eb5` [LIVE] · `BTTR_cahAECmtTe2l+Or9Ust5Ag` (doc) ⚠️ URL-encode path ids |
| `BACT_` | BettorAccount | 32 hex | `BACT_34a7d49eafef49a99e88bb8c1534190b` (our Kalshi account) |
| `SLIP_` | BetSlip | 32 hex | `SLIP_f7224259952043318c128f39cc41d550` |
| `BET_` | Bet (leg) | 32 hex | `BET_cbdd981a133844b8b8c2ef31f38dec2c` |
| `RRES_` | RefreshResponse | 32 hex | `RRES_4363a8207dc84764922c78c9ab97a1dc` |
| `CTX_` / `VENU_` / `PGME_` | Context cid / Venue / PlayerGameData | placeholders in guides only | never observed live (Event `venue` is a plain string) |
| (none) | Article id / `requestId` / webhook log `id` | UUID / 32 hex or UUID / **integer** | `31c87019-7c8e-49a9-943b-08d3d03007c2` · `62d070a2d67e45a69ace866c6fe50b63` · `49944914` |

## 3.2 Event

**[LIVE] Full shape — 18 keys** (`GET /events`, `GET /events/{id}`, and embedded in `/marketOffers`, `/marketSelections/{id}/historicData|metadata`, `Bet.event`):

```json
{
  "id": "EVNT_533e7e58b7554f03bdc23d39183a25ec",
  "sportsdataioId": "10079387",
  "sportradarId": "5750e479-d408-4b22-806b-94fba622a3e3",
  "oddsjamId": "36707-80389-2026-09-03-09",
  "theOddsApiId": null,
  "sport": "Baseball",
  "league": "MLB",
  "name": "San Francisco Giants @ Pittsburgh Pirates",
  "nameSpecial": null,
  "startTime": "2026-09-03T16:35:00Z",
  "startDate": "2026-09-03",
  "seasonType": "REG",
  "venue": "PNC Park",
  "sportId": "SPRT_baseball",
  "leagueId": "LGUE_mlb",
  "contestantAway": {"id": "TEAM_1ca192c8818c464c893d0f13e3d89875", "fullName": "San Francisco Giants", "abbr": "SF"},
  "contestantHome": {"id": "TEAM_9fc4458cf19c48cebe8802a9b2ea69f4", "fullName": "Pittsburgh Pirates", "abbr": "PIT"},
  "neutralVenue": false
}
```

| Field | Type | Semantics / observed |
|---|---|---|
| `id` | `EVNT_` string | primary key |
| `sportsdataioId` | string (numeric) \| null | SportsData.io GameID: `"10079387"` (MLB), `"18021"` (NFL), `"20020111"` (NBA), `"62518"` (tennis), `"1230"` on all NFL futures containers. **806/806** populated on MLB Jul–Sep 2026 |
| `sportradarId` | UUID string \| null | Sportradar match id, no `sr:match:` prefix. **[DOC]** "null unless you provide your API keys for this third party provider" — **[LIVE] populated for us**: 803/806 MLB, 50/50 NFL, 50/50 EPL, 32/33 NBA 2026-04, 17/17 NBA 2024, **0/15** NBA 2026-27 preseason, null on tennis + futures |
| `oddsjamId` | string \| null | OddsJam (= OpticOdds legacy) game id. Formats: `"36707-80389-2026-09-03-09"` (`teamA-teamB-YYYY-MM-DD-HH`, MLB/NBA/NHL), `"74813-25327-22-37"` (`teamA-teamB-YY-WW`, NFL/NCAAF), `"14251-22796-2026-04-01"`. Fill: MLB 804/806, NFL 2023 15/15, **NFL 2026 0/50, EPL 0/50, NBA 2026-04 1/33, NBA 2024 0/17** |
| `theOddsApiId` | 32-hex string \| null | The Odds API event id (doc example `"906a0faf52da9de59f381f82f7bf7116"`). **[LIVE] null on every event sampled** (0/806 MLB, 0/50 NFL, 0/50 EPL, 0/33 NBA, 0/15 NFL 2023). Do not rely on it for joins today. |
| `sport` / `league` | string \| **null** | display name / abbr or long name (`"MLB"`, `"England - Premier League"`, `"France - Ligue 2"`); **`league` null** on 26 US Open tennis matches. Join on `sportId`/`leagueId` |
| `name` | string | `"<away> @ <home>"`; `"<A> vs. <B>"` neutral/individual (`"Kamaru Usman vs. Dricus Du Plessis"`); proper name for futures (`"Super Bowl 2024/25"`, `"MVP 2024/25"`) |
| `nameSpecial` | string \| null | e.g. `"US Open"`, `"UFC Fight Night"`; equals `name` on futures containers |
| `startTime` | ISO-8601 UTC `Z` \| **null** | null on 15 NBA 2026-27 preseason rows and 1 WNBA row — **nullable** |
| `startDate` | `YYYY-MM-DD` \| null | null on futures containers |
| `seasonType` | `"REG"` \| null | **undocumented**; enum presumably `PRE/REG/POST` (matches the `/metadata` param); null on 2022 NFL, futures, tennis |
| `venue` | **string** \| null | **undocumented**; stadium name (`"PNC Park"`, `"Target Field"`); 803/806 MLB populated, null on NFL/NBA/EPL samples |
| `contestantAway` / `contestantHome` | `{id, fullName, abbr}` \| null | `TEAM_` or `PLYR_`; **null** on futures and tennis rows |
| `neutralVenue` | bool \| null | three-state |
| `endTime` | — | documented on the MarketOffer-embedded Event; **absent live** (18 keys, no `endTime`) [LIVE≠DOC] |

**No status/score/`timeUpdated` on Event.** Liveness must be inferred from `startTime` vs now and `Price.live`.

**Embedded-Event variants (3 shapes — be defensive):**
1. **Full 18-key** — above.
2. **Selection-embedded 16-key** (`/marketSelections*`): drops `sportsdataioId` and `sportradarId`; keeps `oddsjamId`, `theOddsApiId`, `seasonType`, `venue`, contestants with `abbr` [LIVE].
3. **Mini 6-key** (`/players/{id}/historicData`, `/teams/{id}/historicData`, `/injuries`, `/trades?injuries=true`.`injury.nextEvent`, trends): `{id, sport, league, name, nameSpecial, startTime}` — `sport`/`league` are **strings**, no `sportId`/`leagueId` [LIVE≠DOC: the doc shows `{id,name}` objects plus `sportId`/`leagueId`].

## 3.3 Market (definition/template)

**[LIVE] 15 keys**, identical on `/markets`, `/markets/{id}` and embedded as `.market` in `/marketOffers`, `/marketSelections/{id}/historicData|metadata`:

```json
{"id": "MKT_2e8cad9c0dd14981b13355ded37b2811", "name": "Player Prop Total Hits + Runs + RBIs",
 "type": "prop", "proposition": "total", "player": true, "team": false, "future": false,
 "oddsjamId": null, "sportradarId": null, "sportsdataioId": null, "theOddsApiId": "batter_hits_runs_rbis",
 "sport": {"id": "SPRT_baseball", "name": "Baseball"},
 "league": {"id": "LGUE_mlb", "name": "Major League Baseball", "abbr": "MLB"},
 "segment": {"id": "SEGM_M", "name": "Match"},
 "metric": {"id": "METR_hitsrunsrbis", "name": "Hits + Runs + RBIs"}}
```

| Field | Type | Notes |
|---|---|---|
| `id` | `MKT_`+32hex | |
| `name` | string | canonical taxonomy string (§3.9); docs mislabel as "(hash)" |
| `type` | `"straight"` \| `"prop"` | |
| `proposition` | string | **[LIVE] values in the first 1 000 markets:** `total` 491, `3-way` 85, `first goal scorer` 83, `correct score` 79, `moneyline` 79, `both teams to score` 62, `spread` 58, `winning margin` 38, `winner` 6, `first 3pt field goal` 2, `first touchdown scorer` 2, `first scorer`, `longest completion`, `first field goal`, `fight to go the distance`, `longest rush`, `longest reception`, `top 3`, `top 20`, `top 40` (1 each). Straights are always `spread|moneyline|total|3-way` |
| `player` / `team` / `future` | bool | |
| `oddsjamId` | string \| null | OddsJam key: `moneyline`, `2nd_half_moneyline`, `team_total`, `player_passing_completions`, `1st_quarter_moneyline_3-way`, `player_rebounds_+_assists` — **36/1000 populated** |
| `sportradarId` | string \| null | `sr:market:1` (ML MLB/NHL/NCAAMB/NCAAF), `sr:market:219` (ML NFL/NBA), `sr:market:223` (spread), `sr:market:303`, `sr:market:7002`, `sr:market:914` — **16/1000** |
| `sportsdataioId` | string \| null | **0/1000** populated |
| `theOddsApiId` | string \| null | TOA market key: `h2h`, `h2h_h2`, `h2h_p3`, `totals`, `totals_q4`, `team_totals`, `outrights`, `player_points`, `player_pass_yds`, `batter_hits_runs_rbis`, `h2h_3_way_1st_5_innings`, `spreads_1st_3_innings` — **35/1000** |
| `sport` / `league` / `segment` / `metric` | objects | `{id,name}` / `{id,name,abbr}` / `{id,name}` / `{id,name}`. **`metric` null for 588/1000** (all straights and non-total props); **`segment` null 20/1000**; **`league` null** for golf/tennis futures |

**Counts [LIVE]:** `?pageSize=1000&pageNum=1` → 1 000 rows + `totalPages: 5` (≤ 5 000 definitions); first page: soccer 654, NFL 84, MLB 89, NHL 48; `?league=NFL` → 223; `?league=NBA&player=true` → 39; `?future=true` → 48; `?theOddsApiId=h2h` → 7.
**Futures naming [LIVE≠DOC]:** live futures markets have **generic names** — `Future Winner` (proposition `winner`), `Future Top 3|5|6|10|20|40`, `Future Leader after Round 1|2|3`, `Future Team Prop Total Wins`, `Future Player Prop Total Passing Yards` — the season/competition lives on the **Event** (`"Super Bowl 2024/25"`), not in `Market.name` as the doc taxonomy pages show.

## 3.4 MarketOffer

**[LIVE] 6 keys:** `['id','market','event','player','team','sdioMarketId']` — 361 offers on one MLB event.

```json
{"id": "MKTO_7923320384ec4e5cae5166756fe6ffb0",
 "market": { …15-key Market… },
 "event":  { …18-key Event (no endTime)… },
 "player": {"id":"PLYR_62b248e1a76149f897f631eb3db5e2c9","sportsdataioId":"10006272","oddsjamId":"4DD6693C6C83","sportradarId":"cafd29c0-91ac-4472-819c-c6dfb04bad71","firstName":"Brandon","lastName":"Lowe","sportId":"SPRT_baseball","fullName":"Brandon Lowe"} | null,
 "team":   {"id":"TEAM_9fc4458cf19c48cebe8802a9b2ea69f4","sportsdataioId":"10000004","oddsjamId":"98CE61698342","sportradarId":"481dfe7e-…","locale":"Pittsburgh","name":"Pirates","fullName":"Pittsburgh Pirates","abbr":"PIT","sportId":"SPRT_baseball"} | null,
 "sdioMarketId": "8680470" | null}
```
`sdioMarketId` = per-offer SportsData.io betting-market id (populated **160/361**), distinct from `market.sportsdataioId` (per market type, always null live). Embedded `player` is 8-key (no `currentTeams`); `team` is the full 9-key Team.

## 3.5 MarketSelection ⭐ (the pricing grain)

**[LIVE] 18 keys (live) / 16 keys (historic, drops the last two):**
```
['id','type','event','segment','proposition','position','marketId','marketName',
 'marketOfferId','sportsdataio','sportradar','oddsjam','theOddsApi','segmentId',
 'positionId','propDetails','betPlaceAvailability','betPlaceUrls']
```
`+ lineAvailability` with `?lineAvailability=true` (19 keys); `+ metadata` with `?metadata=true` (observed as `{}`).

```json
{"id": "MRKT_51d96e2856b145288d67a3e31efaf969", "type": "straight",
 "event": { …16-key Event… },
 "segment": null, "proposition": "moneyline", "position": "San Francisco Giants",
 "marketId": "MKT_945039fb0b3b49c18b27f69d98826ee6", "marketName": "Moneyline",
 "marketOfferId": "MKTO_83cdfa792a15435382cfdda1b8fe1881",
 "sportsdataio": {"eventId": "10079387", "marketId": "8680470"},
 "sportradar":   {"eventId": "5750e479-d408-4b22-806b-94fba622a3e3", "marketId": "sr:market:1"},
 "oddsjam":      {"eventId": "36707-80389-2026-09-03-09", "marketId": "moneyline"},
 "theOddsApi":   {"eventId": null, "marketId": "h2h"},
 "segmentId": "SEGM_M", "positionId": "TEAM_1ca192c8818c464c893d0f13e3d89875", "propDetails": null,
 "betPlaceAvailability": {"kl": true, "bo": false, "tb": false, "pm": true, "ca": true, "sh": false, "fb": false, "wb": false, "tf": false, "pe": false, "pb": false, "pn": false, "bs": false, "st": false, "fl": false, "fd": true, "sl": false, "br": true, "ud": false, "bf": false, "pp": false, "hr": true, "fn": false, "dk": true, "mg": true},
 "betPlaceUrls": {"kl": "ui.sharpsports.io/place/MRKT_51d96e2856b145288d67a3e31efaf969/BOOK_9e939c6df6e54dde8b7d01abdbf65e0a", "dk": "ui.sharpsports.io/place/MRKT_51d96e…/BOOK_nhLZ9l5DRs6w6KcE2n7vnw", "bo": null, …}}
```

| Field | Type | Semantics |
|---|---|---|
| `id` | `MRKT_`+32hex | the pricing key |
| `type` | `"straight"` \| `"prop"` | (trends doc shows `"PlayerProp"` — never observed) |
| `event` | 16-key Event | §3.2 variant 2 |
| `segment` | string \| **null** | display name; **null while `segmentId` = `SEGM_M`** (431/500); set for sub-segments (`"5th Inning"`, `"1st 5 Innings"`) |
| `segmentId` | `SEGM_…` | always set |
| `proposition` | string | one MLB event: `total` 443, `spread` 22, `correct score` 16, `moneyline` 8, `winning margin` 8, `3-way` 3 |
| `position` | string | **literals observed:** `Over`/`Under`; team `fullName` (`San Francisco Giants`); **`Draw`** (3-way, `positionId` null); correct score `"<Team fullName> 2-1"` / `"Draw 1-1"`; winning margin `"1"`, `"2"`, `"3"`, `"4+"`; futures: player/team fullName (`"Carlos Lagrange"`, `positionId` `PLYR_…`) |
| `positionId` | `TEAM_`/`PLYR_` \| null | set when position is a standardized object; **null for Over/Under, Draw, scores, margins** |
| `marketId` / `marketName` | `MKT_…` / string | |
| `marketOfferId` | `MKTO_…` | **undocumented** parent offer |
| `sportsdataio` | `{eventId, marketId}` | `{"10079387","8683280"}` |
| `sportradar` | `{eventId, marketId}` | `marketId` `"sr:market:1"`/`"sr:market:219"` for ML; null for props |
| `oddsjam` | `{eventId, marketId}` | `marketId` `"moneyline"`; null for most props |
| `theOddsApi` | `{eventId, marketId}` | **undocumented**; `eventId` **null everywhere**, `marketId` `"h2h"`, `"batter_hits_runs_rbis"` |
| `propDetails` | object \| null | **[LIVE] 7 keys:** `{future, player, playerId, team, teamId, metricSpecial, metricSpecialId}` — e.g. `{"future": false, "player": "Rafael Devers", "playerId": "PLYR_57e3…", "team": null, "teamId": null, "metricSpecial": "Hits + Runs + RBIs", "metricSpecialId": "METR_hitsrunsrbis"}`; team prop: `{"team": "San Francisco Giants", "teamId": "TEAM_1ca1…", "metricSpecial": "Runs", …}`. The documented `matchupSpecial` key was **absent** in all 500 sampled |
| `betPlaceAvailability` | `{abbr: bool}` | **25 keys** = every book incl. unsupported (`bf bo br bs ca dk fb fd fl fn hr kl mg pb pe pm pn pp sh sl st tb tf ud wb`). "whether SharpSports can create a link" ⇒ proxy for "book currently offers this selection" |
| `betPlaceUrls` | `{abbr: url\|null}` | `ui.sharpsports.io/place/<MRKT_>/<BOOK_>` |
| `lineAvailability` | `{abbr: [line…]\|null}` | opt-in; e.g. ML `{"kl":[0.0],"dk":[0.0],…,"pn":null}`; unordered |
| `prices` | — | **[LIVE≠DOC] never serialized** on list or detail (default `prices=true` per docs; `prices=false` identical). Per-book ladders exist **only in `/prices`**. Explicit `?prices=true` was not tried — **[UNKNOWN]** whether it re-enables the map |

**Selection cardinality:** ML/spread → 2; 3-way → 3; totals/prop-totals → 2 (`Over`/`Under`); Correct Score → up to 72 per offer; Winning Margin → 4 per side (2 offers × 4); futures → one per contestant. **The line is NOT part of selection identity** — `(selection, book, line)` identifies a quote.

**[LIVE] Volume:** one live MLB game had **703 selections / 67 markets / 2 888 prices** via `/prices`; `/marketSelections?eventId=…` filled `limit=500` and `pageSize=50` → `totalPages: 15`; `/prices/historic/summary?eventId=` → 761 selections.

## 3.6 Price (nested inside `/prices`) ⭐

`/prices?eventId=…` → **object** `{"eventId", "markets"}`; `/prices?league=…|sport=…` → **array** of those.

```
{ "eventId": "EVNT_533e7e58b7554f03bdc23d39183a25ec",
  "markets": [ {                                          // keys: id, name, marketOffers
    "id": "MKT_945039fb0b3b49c18b27f69d98826ee6", "name": "Moneyline",
    "marketOffers": [ {                                   // keys: id, player, team, marketSelections
      "id": "MKTO_83cdfa792a15435382cfdda1b8fe1881",
      "player": {"id":"PLYR_…","fullName":"…"} | null,   "team": {"id":"TEAM_…","fullName":"…"} | null,
      "marketSelections": [ {                             // keys: id, position, positionId, books
        "id": "MRKT_51d96e2856b145288d67a3e31efaf969", "position": "San Francisco Giants",
        "positionId": "TEAM_1ca192c8818c464c893d0f13e3d89875",
        "books": [ {                                      // keys: id, abbr, name, prices
          "id": "BOOK_88064cc6787c47ccbd4bbb036c7f55c5", "abbr": "br", "name": "BetRivers",
          "prices": [ {                                   // 10 keys, ALWAYS this set [LIVE]
            "line": 0.0, "odds": 138, "impliedProbability": 0.4202,
            "main": true, "live": false, "ev": null,
            "marketOfferVolume": null, "marketSelectionVolume": null,
            "bookIds": {"eventId": "1024787504", "marketId": "2687633615", "selectionId": "4321965256"},
            "betPlaceLinks": {"desktop": "https://region-abbreviation.betrivers.com/?page=sportsbook#event/1024787504?coupon=S%7C4321965256%7C0",
                              "iOS": "rsiri://?page=sportsbook#event/1024787504?coupon=S%7C4321965256%7C0", "android": null}
          } ] } ] } ] } ] } ] }
```

| Field | Type | Doc language / observed |
|---|---|---|
| `line` | float | "The line associated with the price." **`0.0` for moneyline / 3-way / futures** (never null in `/prices`). Spread line is from the `position`'s perspective: SF `-1.5` alt vs `+1.5` main, PIT `-1.5` main |
| `odds` | int | American. DFS books (`pp`, `ud`) are mostly `+100` (3 527 of 7 237 prices; also `-137`, `-119`, `-112` — Underdog/PrizePicks non-standard multipliers); Kalshi/Polymarket long shots `9900`, `199900`, `66567`; `-100` placeholders seen on Polymarket ML both sides with `impliedProbability 0.5` and null volume |
| `impliedProbability` | float | "implied probability of the americanOdds … **also equal to the share price for prediction markets**" (Kalshi `-117` → `0.5392`) |
| `main` | bool | `false` ⇒ alternate line. One MLB event: 1 459 of 2 888 prices were alts. **Max rungs per book on one selection:** ca 19, fd 19, dk 17, br 16, kl 11, hr 8, pp 6, pm 5, mg 2, ud 1 |
| `live` | bool | "updated since the event began". 0 `live` prices in all snapshots (07:2x–07:5x UTC, no games in play) — semantics unverified |
| **`ev`** | float \| null | **undocumented**; populated on Pinnacle prices (`-7.23`) and on `bestPrice` (`-4.67`, `-1.94`); null elsewhere. Presumably SharpSports' EV % vs their fair line — formula **[UNKNOWN]** |
| `marketOfferVolume` / `marketSelectionVolume` | int \| null | "currently only populated for prediction-market books". Kalshi ML: `36527/36527`; Polymarket futures: `164949458 / 6630579`; 2 729 of 3 151 kl+pm prices had volume. **Units [UNKNOWN]** (contracts vs cents) |
| `bookIds` | `{eventId, marketId, selectionId}` | sportsbook-native ids 🔐 betPlace. **Per-book formats [LIVE]:** br `"1024787504"/"2687633615"/"4321965256"`; **Kalshi** `"26SEP041905BOSBAL"/"KXMLBGAME"/"BOSY"` (ticker parts → `kxmlbgame-26sep041905bosbal-bos`); **Polymarket** `"947639"/"4059453"/"1"`; PrizePicks `"MLB_game_w99uVTzRiEf1cRPRSgEvdQfV"/"14445115"/"043fc6…"` (projection id); Pinnacle `"1634945554"/"1635468120"/"1635468121"`; doc: dk `"30589142"/"30589142_moneyline"/"30589142_ari"`, fd `"35492839"/"42.570304298"/"48009770"` |
| `betPlaceLinks` | `{desktop, iOS, android}` | strings \| null. Kalshi `https://kalshi.com/markets_by_ticker/kxmlbgame-26sep041905bosbal-bos?orderSide=yes`; Polymarket `https://polymarket.com/event/mlb-cin-lad-2026-09-07`; PrizePicks `https://app.prizepicks.com/board/?projections=14445115`; Pinnacle all null |

### 🔴 CRITICAL: `/prices` has NO timestamp.
The Price key set is exactly `{line, odds, impliedProbability, main, live, ev, marketOfferVolume, marketSelectionVolume, bookIds, betPlaceLinks}` on **2 888 of 2 888** prices [LIVE]. No `id`, no `timeUpdated`, no `timestamp`. The quickstart's `{"id":"PRICE_…","timeUpdated":…,"isMain":…}` shape is fiction. Consequences:
* Stamp `recv_ts` **client-side at fetch time** and treat it as the quote time.
* Only in-band staleness signals: `live` and `main`.
* Line-change timing can only be recovered post-hoc from `/prices/historic/timeseries` (5-minute floor; §5).

## 3.7 Book — definitive live catalogue

**[LIVE] 14 keys:** `['id','name','abbr','status','refreshCadenceActive','sdkRequired','pullBackToDate','maxHistoryMonths','maxHistoryBets','historyDetail','oddsFeedActive','backgroundRefresh','mobileOnly','betPlaceStatus']` (`backgroundRefresh` undocumented; `sdkSupport` added with `?support=true`).

| abbr | name (live) | id | status | **oddsFeedActive** | sdkRequired | cadence | betPlaceStatus (web/iOS/android) |
|---|---|---|---|---|---|---|---|
| `dk` | DraftKings | `BOOK_nhLZ9l5DRs6w6KcE2n7vnw` | active | **true** | true | false | betSlipCreation ×3 |
| `fd` | Fanduel | `BOOK_Rf7xRhS7TKQUl94Xkt5w` | active | **true** | true | false | betSlipCreation ×3 |
| `mg` | BetMGM | `BOOK_pPg9ABaPSj2mL6qoMTKR1A` | active | **true** | true (bgRefresh true) | false | betSlipCreation / betSlipCreation / inactive |
| `ca` | Caesars | `BOOK_IPBQaQQTCRxplZx7SYOA` | active | **true** | false | false | inactive / betSlipCreation / betSlipCreation |
| `bs` | **theScore** (docs: ESPN BET) | `BOOK_c81242f993894e67966b3ccfc4ba3a65` | active | **true** | false | false | unsupported / betSlipCreation / betSlipCreation |
| `br` | BetRivers | `BOOK_88064cc6787c47ccbd4bbb036c7f55c5` | active | **true** | true | false | betSlipCreation / betSlipCreation / unsupported |
| `hr` | HardRock | `BOOK_f9661d9af5764404a8d21233467511b1` | active | **true** | false | false | betSlipCreation ×3 |
| `kl` | **Kalshi** | `BOOK_9e939c6df6e54dde8b7d01abdbf65e0a` | active | **true** | false | false | betSlipCreation ×3 |
| `pm` | **Polymarket** | `BOOK_ae54ed82802c445aa8dac91da2782010` | active | **true** | true | **true** | deepLink / unsupported / unsupported |
| `pp` | PrizePicks (DFS) | `BOOK_818b3907cd4947e6ba2a3170e4df2856` | active | **true** | true | false | deepLink / unsupported / unsupported |
| `ud` | Underdog (DFS) | `BOOK_1aac80eb006640bd9722eb25ae73845a` | active | **true** | true | false | unsupported ×3 |
| `pn` | **Pinnacle** | `BOOK_f6162b9d2dfc4403941994e7c045185d` | **unsupported** | **true** | — | — | unsupported ×3 |
| `st` | Sporttrade (exchange) | `BOOK_74a5f65d2d5c48c3952f94f7dd758f63` | active | false | true | false | unsupported ×3 |
| `fl` | Fliff | `BOOK_79f420f246df4e2a8907373413eee3a5` | active | false | false | false | unsupported ×3 |
| `sl` | Sleeper | `BOOK_831307ef9710497aa6fc5544eb7fe528` | active | false | true | false | unsupported ×3 |
| `fn` | Fanatics | `BOOK_21ebdd613515404ba9e5a8cd3cc20d34` | active | false | true | false | unsupported ×3 |
| `bo` | Borgata | `BOOK_M8vwoV4NQPWELETLrBK8Yg` | unsupported | false | | | |
| `tb` | Test Book | `BOOK_b3fee420f26241918245bf07a254f992` | unsupported | false | | | |
| `sh` | SugarHouse | `BOOK_b3865cc1a43347c4ae54863a243ed187` | unsupported | false | | | |
| `fb` | FoxBet | `BOOK_YYX0syInRfa4FmU09xLg` | unsupported | false | | | |
| `wb` | WynnBet | `BOOK_cba8e90df3a9452a82c687e39afa6136` | unsupported | false | | | |
| `tf` | ThriveFantasy | `BOOK_288fb70dc7aa4e50868a7e2a968803a0` | unsupported | false | | | |
| `pe` | Prophet Exchange | `BOOK_0486650204584a98b585a05f5bfaaeee` | unsupported | false | | | |
| `pb` | PointsBet | `BOOK_yQb2mAZpRGGCqPSYu4hmmg` | unsupported | false | | | |
| `bf` | BetFred | `BOOK_a264fc209850488d957d9d465e3195c7` | unsupported | false | | | |

**betPrices universe = the 12 books with `oddsFeedActive: true`** (`dk fd mg ca bs br hr kl pm pp ud pn`) — exactly the 12 abbrs present in the 17.5 MB MLB snapshot (dk 6 900 prices, fd 4 941, pp 4 631, hr 3 390, ud 2 491, kl 2 378, ca 2 305, br 1 070, pm 777, pn 724, mg 174, bs 73). **Pinnacle is `status: unsupported` (no betSync/betPlace) but `oddsFeedActive: true` — always query `/books?status=unsupported` too** or the price universe will miss it.

Other fields: `status` ∈ `active|inactive|coming|unsupported` (default filter `active`); `refreshCadenceActive`, `sdkRequired`, `backgroundRefresh`, `mobileOnly` (deprecated), `pullBackToDate` (date, e.g. `2024-09-03` mg/hr, `2023-07-14` bs), `maxHistoryMonths` (24 mg/hr, 1 fl), `maxHistoryBets` (1000 fd/sl, 2000 br, 100 fn), `historyDetail` (`"All bets on a users account will be synced"`) are betSync mechanics. `betPlaceStatus` values: `unsupported`, `inactive`, `betSlipCreation`, `deepLink` (live casing; doc says `deeplink`). `sdkSupport` = `{webBrowserExtension, androidNative, iOSNative, reactNative, cordova}` each `{documentation, platforms:[{name, supported, minSdkVersions}]}`.

## 3.8 BookRegion, Sport, League, Team, Player, Segment, Metric

**BookRegion** — **[LIVE] 8 keys** `['id','book','name','abbr','status','country','sdkRequired','mobileOnly']`; `book` = `{id,name,abbr}`; `country` ∈ `United States`, `Canada`; id prefixes **both `BRGN_` and `BSTA_`** in the 1 557 rows. Irrelevant to betPrices (no region param on `/prices`).

**Sport** — **[LIVE] 2 keys, 20 rows:** `SPRT_americanfootball` Football · `SPRT_baseball` · `SPRT_basketball` · `SPRT_icehockey` Hockey · `SPRT_mma` · `SPRT_soccer` · `SPRT_tennis` · `SPRT_auto` · `SPRT_golf` · `SPRT_australianfootball` · `SPRT_badminton` · `SPRT_boxing` · `SPRT_cricket` · `SPRT_darts` · `SPRT_handball` · `SPRT_lacrosse` · `SPRT_rugby` · `SPRT_tabletennis` · `SPRT_volleyball` · `SPRT_esports`. `name` for `SPRT_americanfootball` is `"Football"` here but `"American Football"` in the historicData doc — key on `id`.

**League** — **[LIVE] 8 keys** `['id','sportsdataioId','sportradarId','region','name','abbr','sportId','oddsjamId']`; 138 rows: soccer 99, basketball 17, hockey 7, baseball 5, football 4, mma 2, auto 2, tabletennis 1, lacrosse 1. `sportradarId` populated on **24** (MLB `2fa448bc-…`, NFL `3c6d318a-…`, NBA `4353138d-…`, NHL `fd560107-…`, EPL **`sr:competition:17`** — mixed formats); `oddsjamId` **0/138**; `sportsdataioId` 93/138. Example: `{"id":"LGUE_542b6c4f1c7f4a0da7154747c76e7340","sportsdataioId":"1","sportradarId":"sr:competition:17","region":"England","name":"Premier League","abbr":"EPL","sportId":"SPRT_soccer","oddsjamId":null}`. No `theOddsApiId` on League.

Major league ids [LIVE] (use these literal `LGUE_` ids in filters):

| id | abbr | sportId | name | sportradarId | sportsdataioId |
|---|---|---|---|---|---|
| `LGUE_mlb` | MLB | `SPRT_baseball` | Major League Baseball | `2fa448bc-fc17-4d3d-be03-e60e080fdc26` | null |
| `LGUE_nfl` | NFL | `SPRT_americanfootball` | National Football League | `3c6d318a-6164-4290-9bbc-bf9bb21cc4b8` | null |
| `LGUE_nba` | NBA | `SPRT_basketball` | National Basketball Association | `4353138d-4c22-4396-95d8-5f587d2df25c` | null |
| `LGUE_nhl` | NHL | `SPRT_icehockey` | National Hockey League | `fd560107-a85b-4388-ab0d-655ad022aff7` | null |
| `LGUE_wnba` | WNBA | `SPRT_basketball` | Women's National Basketball Association | `59c24590-0adb-4b3d-80a8-10450f83f4a1` | null |
| `LGUE_ncaaf` | NCAAF | `SPRT_americanfootball` | NCAA Football | `26c1246a-2fc3-4b7e-8999-1685d3ab4676` | null |
| `LGUE_ncaamb` | NCAAMB | `SPRT_basketball` | NCAA Basketball (M) | `cd4268ee-07aa-4c4d-a435-ec44ad2c76cb` | null |
| `LGUE_ufc` | UFC | `SPRT_mma` | Ultimate Fighting Championship | null | null |
| `LGUE_f1` | F1 | `SPRT_auto` | Formula 1 | null | null |
| `LGUE_milb` | MiLB | `SPRT_baseball` | Minor League Baseball | null | null |
| `LGUE_cfl` | CFL | `SPRT_americanfootball` | Canadian Football League | null | null |
| `LGUE_542b6c4f1c7f4a0da7154747c76e7340` | EPL | `SPRT_soccer` | Premier League | `sr:competition:17` | `1` |
| `LGUE_269a3af26ac44fdaae9b3dfc80de46a2` | MLS | `SPRT_soccer` | MLS | `sr:competition:242` | `8` |
| `LGUE_4ac5000c24724c86b762c22797ac798f` | UCL | `SPRT_soccer` | UEFA Champions League | `sr:competition:7` | `3` |
| `LGUE_1c39c57216924f95af143817993fdd27` | ESP | `SPRT_soccer` | La Liga | `sr:competition:8` | `4` |
| `LGUE_6b1e1244362346c593eeafd0e5b069de` | DEB | `SPRT_soccer` | Bundesliga | `sr:competition:35` | `2` |
| `LGUE_9d41c0af03744e40b3af1cb41e052641` | ITSA | `SPRT_soccer` | Serie A | `sr:competition:23` | `6` |
| `LGUE_0773a98383ff47a7a99790be4a86036d` | FRL1 | `SPRT_soccer` | Ligue 1 | `sr:competition:34` | `13` |
| `LGUE_5fc9f1bdae4e4ea78d239034a2bb7749` | BRSA | `SPRT_soccer` | Série A | `sr:competition:325` | `15` |
| `LGUE_341ce1c5e4ec48fdacdf44812643d15a` | COPA | `SPRT_soccer` | Copa America | `sr:competition:133` | `10` |

**Team** — **[LIVE] 9 keys** `['id','sportsdataioId','oddsjamId','sportradarId','locale','name','fullName','abbr','sportId']`, e.g. `{"id":"TEAM_8bfd1dfe1a09451195d19c792ea18567","sportsdataioId":"16","oddsjamId":"2D71E5BA64A5","sportradarId":"6680d28d-d4d2-49f6-aace-5292d3ec02c2","locale":"Kansas City","name":"Chiefs","fullName":"Kansas City Chiefs","abbr":"KC","sportId":"SPRT_americanfootball"}`. Embedded as contestant: `{id, fullName, abbr}`. With aggregate stats → 10th key `aggregateStats` (**a list of per-season objects**, §3.12).

**Player** — **[LIVE] 9 keys** `['id','sportsdataioId','oddsjamId','sportradarId','firstName','lastName','sportId','fullName','currentTeams']`; `currentTeams` = `[{id, fullName, abbr}]` (can be empty; Harry Kane has 2: Bayern + England). `oddsjamId` 12 upper-hex (`B671C99CB711`) or **null** (soccer); `sportradarId` UUID for US sports but **`sr:player:108579`** for soccer. `?previousTeam=true` → 11 keys adding `previousTeam` `{id, fullName}` and **`changeDate`** (`"2025-11-24"`, undocumented). `/players?league=LGUE_nba` → 611; `?name=Mahomes` → 1. Trends doc adds `headshot`/`position`; `/trades?injuries=true` adds `injury`.

**Segment** — **[LIVE] 3 keys, 95 rows:** `SEGM_M` Match · `SEGM_1H/2H` · `SEGM_1P..3P` · `SEGM_1Q..4Q` · `SEGM_1I..9I` (innings) · `SEGM_F2I..F8I` ("1st N Innings") · `SEGM_S1..S5` (sets) · `SEGM_S1G1..S5G12` (set-game) · `SEGM_R1..R4` (golf rounds). `?abbr=1H` → 1.

**Metric** — **[LIVE] 2 keys, 278 rows**, e.g. `METR_aces`, `METR_assistsrebounds`, `METR_bases`, `METR_completions`, `METR_corners`, `METR_fantasypoints`, `METR_hitsrunsrbis`, `METR_passyds`, `METR_pitcherstrikeouts`, `METR_pointsreboundsassists`, `METR_shotsongoal`, `METR_wins`. Game-log / aggregate stats reference many more ids not in this list (`METR_yardsperattempt`, `METR_passingepa`, `METR_wrc_plus`, `METR_exitvelocity`) — treat the catalogue as a subset.

## 3.9 Market taxonomy (`Market.name` grammar)

Grammar derived from the 434 documented rows and confirmed on live names:
```
market_name := [ SEGMENT_PREFIX " " ] CORE
CORE        := "Moneyline" | "Spread" | "Total" | "3-way"
             | [ "Future " ] PROP_KIND " " PROP_TAIL
             | "Future Winner" | "Future Top " N | "Future Leader after Round " N     -- live: generic, no season
PROP_KIND   := "Game Prop" | "Team Prop" | "Player Prop" | "Match Prop"(tennis)
PROP_TAIL   := "Total " METRIC | "Correct Score" | "Both Teams To Score" | "Winning Margin"
             | "First Goal Scorer" | "First Scorer" | "First 3pt Field Goal" | "Longest Completion" | …
SEGMENT_PREFIX := "1st Half"|"2nd Half"|"1st..4th Quarter"|"1st..3rd Period"|"1st..9th Inning"
                | "1st 3 Innings"|"1st 5 Innings"|"1st 7 Innings"|"Set 1"|"Set 2"
```
* Segment prefix goes **first** (`1st Quarter Player Prop Total Passing Yards`). **Exception (6 MLB Underdog rows):** infixed, "Total" dropped: `Player Prop 1st Inning Hits`, `Player Prop 1st Inning Hits Allowed`, `Player Prop 1st 3 Innings Hits + Runs + RBIs`, `Player Prop 1st Inning Pitcher Strikeouts`, `Player Prop 1st Inning Runs`, `Player Prop 1st Inning Runs Allowed`.
* Combo metrics use `" + "`: `Hits + Runs + RBIs`, `Points + Rebounds + Assists`, `Passing + Rushing Yards`, `Rushing + Receiving Yards`, `Blocks + Steals`, `Assists + Rebounds`, `Tackles + Assists`, `Runs + RBIs` (live).
* **Metric words collide across sports** (`Assists`, `Points`, `Blocks`) and near-duplicates exist (`Shots` vs `Shots On Goal`, `Outs` vs `Pitcher Outs`, `Earned Runs` vs `Earned Runs Allowed`). **Key markets by `MKT_` id or `(sportId, leagueId, name)`, never by name alone.**
* Never parse the name to derive segment/metric — use `Market.segment.id` / `Market.metric.id` (both live).
* Doc-only book coverage: **Pinnacle** is listed on full-game ML/spread/total for all 6 team sports + tennis, MLB 1st-inning straights, NBA/WNBA & NFL/NCAAF 1st Half/1st Quarter straights, team totals, ~16 MLB/NFL player props; absent from every 3-way, game prop, NBA/NHL player prop and future. Live Pinnacle MLB snapshot: `Total`, `Spread`, `Team Prop Total Runs`, `Player Prop Total Bases/Home Runs/Pitcher Strikeouts`, `1st 5 Innings Total/Spread`, **`Future Winner`** (60 prices — so futures do exist at Pinnacle live), `Moneyline`, `1st Inning Moneyline`.

## 3.10 Historic price objects (`/prices/historic/summary` and `/timeseries`) ⭐

**[LIVE] One shape for both endpoints:**
```json
{"marketSelections": [ {
   "id": "MRKT_7cd1e43612c34ab691fea9843d153c82", "position": "Over", "positionId": null,
   "pricesTimeseries": [ {
      "windowStartTime": "2026-09-03T02:15:00.991000Z", "windowEndTime": "2026-09-03T07:30:09.792000Z",
      "consensus": {"open":  {"line": 6.5, "odds": 100,  "impliedProbability": 0.5},
                    "close": {"line": 1.5, "odds": -117, "impliedProbability": 0.5392}},
      "books": [ {"id": "BOOK_9e939c6df6e54dde8b7d01abdbf65e0a", "abbr": "kl", "name": "Kalshi",
                  "open":  {"line": 1.5, "odds": 104,  "impliedProbability": 0.4902, "marketOfferVolume": 58485,  "marketSelectionVolume": 23688},
                  "close": {"line": 1.5, "odds": -104, "impliedProbability": 0.5098, "marketOfferVolume": 257735, "marketSelectionVolume": 167894}},
                 {"id": "BOOK_nhLZ9l5DRs6w6KcE2n7vnw", "abbr": "dk", "name": "DraftKings",
                  "open":  {"line": 1.5, "odds": -108, "impliedProbability": 0.5192, "marketOfferVolume": null, "marketSelectionVolume": null},
                  "close": {"line": 1.5, "odds": -108, "impliedProbability": 0.5192, "marketOfferVolume": null, "marketSelectionVolume": null}} ] } ] } ],
 "totalPages": 4 }                                       // only when paginated
```

| Field | Type | Semantics |
|---|---|---|
| `marketSelections[].id/position/positionId` | | selection identity only (no event/market embedded — join to `/marketSelections?historic=true`) |
| `pricesTimeseries[]` | array | windows, **ascending** by `windowStartTime` [LIVE]; `[]` when the selection predates price history |
| `windowStartTime` / `windowEndTime` | ISO µs `Z` | window bounds; for summary = first offer → last offer |
| `consensus.open` / `consensus.close` | `{line, odds, impliedProbability}` | cross-book consensus at window open/close (method [UNKNOWN]; `-100/0.5` appears when only a placeholder book is present) |
| `books[].open` / `books[].close` | `{line, odds, impliedProbability, marketOfferVolume, marketSelectionVolume}` | per-book first/last quote in the window; only books with data in the window are listed (1–9 books observed) |

**[LIVE≠DOC]:** the docs describe OHLC "open, high, low, close offers with line value, price/odds, sportsbook, and exact timestamp" plus `bookCount`/`pricePointCount` and carry-forward. **Live has only `open`/`close`, no `high`/`low`, no per-offer timestamps, no counts; grep of every sample finds none.** "High/low by line value" therefore cannot be computed from the API beyond open/close. The quickstart's `openingLine/currentLine/avgLine/minLine/maxLine` and `timestamp/open/high/low/close` scalars are fiction.

**Window rules [LIVE]:**
- `summary?marketSelectionId=X` ≡ `timeseries?marketSelectionId=X` with no other params — **byte-identical** (verified on 2 selections): the full history split into **~11–15 equal-duration windows** (e.g. 11 × 11-day windows from 2025-05-15 for a 2025-09-09 NFL ML), i.e. the doc defaults ("1h", "event start − 24 h") are **not applied**.
- With `rollup`: `5m` windows start at the **first offer's exact ms** (`02:15:00.991`, `02:20:00.991`, …); `1h`/`4h`/`1d` windows are **calendar-aligned** (`02:00:00Z`, `12:00:00Z`, `00:00:00Z`; last `1d` window ends `23:59:59Z`).
- Windows with no data **are omitted** (gaps of 20 h observed in a 2 h-window series) — no carry-forward rows.
- Cap: **1 000 windows per query** → `400 "Query would generate approximately 1440 windows…"`. `rollup=1m` is rejected with the same window-count error (8 291 windows), so the enum is not validated separately.
- `timeseries` without a start/end on a selection **with no history** → **404** `No offers found…`; with explicit start/end → 200 with `pricesTimeseries: []`.
## 3.11 historicData & metadata objects (per MarketSelection)

### `/marketSelections/{id}/historicData` — **[LIVE] 16 keys**
```
['event','team','opponent','locationType','player','market','position',
 'DVP','dvpRank','dvpAvg','dvpPosition','consensusProjection','venue',
 'startingPitcher','gameStats','bestPrice']
```
Sub-shapes [LIVE]: `event` = 18-key Event; `team`/`opponent` = 9-key Team; `player` = 8-key Player (no `currentTeams`); `market` = 15-key Market.

| Field | Type | Semantics |
|---|---|---|
| `locationType` | `"Home"` \| `"Away"` | for the **upcoming** game (capitalised) |
| `DVP` / `dvpRank` / `dvpAvg` | float \| null / int \| null / float \| null | "Lower values indicate stronger defense", "1 = best defense" [DOC]; **all null for MLB** [LIVE] (DVP is NFL/NBA/NHL only per guide) |
| `dvpPosition` | string | `"1B"`, `"DH"`, `"QB"`, `"SF"` |
| `consensusProjection` | float \| null | "Consensus projection value for this market from various sportsbooks and prediction models" — `1.97` for Devers H+R+RBI ⇒ **fair-value anchor** |
| `venue` | `{name, parkFactorPerc, parkFactorRank}` \| null | **[LIVE≠DOC]** `parkFactorPerc` is a **signed integer % vs neutral** (`2`, `0`, `-4`), not the documented 100-based percentage; `parkFactorRank` 1 = most hitter-friendly (`5` PNC Park, `21` Oracle Park) |
| `startingPitcher` | object | MLB: **full 8-key Player + `hand`** (`{"id":"PLYR_64820b82…","firstName":"Lake","lastName":"Bachar",…,"hand":"R"}`). Non-MLB (doc sample): object of **empty strings** with `hand: null` — not null |
| `gameStats` | array | **newest-first**. Item keys [LIVE]: `['season','location','opponent','value','date','venue','line','result','dvpRank','position']` — `season` `"2026"` (single year live; doc shows `"2023-2024"`), `location` lowercase `home/away`, `opponent` `{id,name,fullName,abbr}`, `value` float, `date` ISO, `venue` `{name,parkFactorRank,parkFactorPerc}`, **`line`** (undocumented; the line the result was judged at), `result` `"Over"/"Under"`, `dvpRank` null (MLB), `position` |
| `bestPrice` | `{id: PRICE_, line, odds, ev, book{id,name,abbr}}` | **[LIVE] single shape** `{"id":"PRICE_107af8b2975b411182cd06910a942ce1","line":0.5,"odds":-274,"ev":-4.67,"book":{"id":"BOOK_nhLZ9l5DRs6w6KcE2n7vnw","name":"DraftKings","abbr":"dk"}}` — the doc's `{line, price, book}` and `{line, overOdds, underOdds, bookId}` variants were **not** observed |

**[LIVE] `line` optional:** `?line=0.5&gamesBack=10` → 10 games (5.9 kB); no params → **442 games** back to 2024-03-29 (147 kB) judged at the bestPrice line 1.5; `?location=home&gamesBack=20` → 20 home games.

### `/marketSelections/{id}/metadata` — **[LIVE] 41 keys**
```
event, team, opponent, locationType, player, market, position, DVP, dvpRank, dvpAvg, dvpPosition,
consensusProjection, venue, startingPitcher, L1, L2, …, L20, season, vsOpponent, atLocationType,
vsStartingPitcher, vsStartingPitcherHand, atVenue, bestPrice
```
- **All 20 windows `L1`…`L20` present**; stat block `{hits:int, hitPerc:float(0–100), stdev:float, mean:float, median:float}` (`stdev` may be int `0`).
- `season` adds **`count`**: `{"hits":97,"hitPerc":69.78,"stdev":2.15,"mean":2.12,"median":2.0,"count":139}`.
- Split blocks (`vsOpponent`, `atLocationType`, `vsStartingPitcher`, `vsStartingPitcherHand`, `atVenue` — the last three MLB only): `{dataStartDate: ISO, currentSeason: "2026", "<season>": {…,count}, …, all: {…,count}}`; season keys are single years live (`"2026"`, `"2025"`, `"2024"`), `"2024-2025"` spans in the NFL doc sample. `dataStartDate` observed `2024-03-29` (MLB atLocationType), `2023-09-11` (NFL doc) ⇒ per-player stat collection starts ~2023–24.
- `bestPrice` = same `PRICE_` shape as historicData.
- `playerAggStats=true` → `player.aggregateStats` (**list** of per-season objects, §3.12); `teamAggStats=true` → `event.contestantHome/Away.aggregateStats` (list). `filteredPlayerAggStats=true&gamesBack=10` → 9.0 kB vs 84.5 kB unfiltered.

### 🔴 `hits` counts OVERS regardless of `position`.
Doc: "Number of games where the player exceeded the betting line". Confirmed by the Dak Prescott doc sample (`position: "Under"`, line 237.5, `L1: {hits: 0, mean: 133.0}` — 133 < 237.5 is an Under hit, yet `hits = 0`). **For an Under selection: `under_hits = count − hits`, `under_hitPerc = 100 − hitPerc`.**

## 3.12 Game logs & aggregate stats

### `/players/{id}/historicData` and `/teams/{id}/historicData` — `[{event, stats[]}]`
```json
[{"event": {"id": "EVNT_2e672b0116064b49a50eefafd0216b2f", "sport": "Football", "league": "NFL",
            "name": "Los Angeles Chargers @ Kansas City Chiefs", "nameSpecial": null, "startTime": "2025-12-14T18:00:00Z"},
  "stats": [{"metric": {"id": "METR_yardsperattempt", "name": "Yards Per Attempt"}, "value": 6.75},
            {"metric": {"id": "METR_passyds", "name": "Passing Yards"}, "value": 204.0}, …]}]
```
- Ordered **most recent first** [DOC]+[LIVE]. `event` is the **6-key mini** shape (`sport`/`league` strings) [LIVE≠DOC].
- Metric sets vary by game: Mahomes 2025 games carry 47–48 metrics (EPA, air yards, PPR fantasy…), 2023 games only 12–14 ⇒ **do not assume a fixed column set**.
- Depth [LIVE]: NBA from **2023-01-13** (LeBron 223 games, another NBA player 213), NFL from **2023-09-08** (Mahomes 49), MLB from **2024-03-28** (Ohtani 477), **soccer 0** (Harry Kane), **team log = current season only** (KC 16 games 2025-09-06 … 2025-12-26).
- `gamesBack` works; `season`, `startDate/endDate`, pagination are ignored; `seasonType=POST` → `[]`; any query param slows the call to 14–24 s.

### Aggregate stats (`aggregateStats` / `seasonStats`) — **a LIST of per-season objects [LIVE≠DOC]**
Sport-specific shapes:

| Sport | Player object | Team object |
|---|---|---|
| NFL | `{season:"2025", team:{id,fullName,abbr}, position:"QB", games_played, games_started, stats:{counting_stats:{sacks, carries, targets, total_tds, receptions, completions, passing_tds, rushing_tds, interceptions, pass_attempts, passing_yards, receiving_tds, rushing_yards, fantasy_points, receiving_yards, scrimmage_yards, passing_air_yards, fantasy_points_ppr, receiving_air_yards, passing_yards_after_catch, receiving_yards_after_catch}, efficiency_stats:{…}}}`; each counting stat = `{total:{value, positional_rank}, per_game:{value, positional_rank}, metric_id:"METR_sackstaken", rank_type:"low_to_high"\|"high_to_low", metric_name, total_position_players:75}` (+ `redzone/inside_5/inside_10` splits per doc) | `{season:"2025", stats:{general:{total_dvoa, latest_week:18, latest_game_date:"2026-01-04", point_differential:{rank,value,rank_type}, strength_of_schedule}, offensive:{offense_dvoa, counting_stats:{tds, plays, yards, carries, receptions, passing_tds, rushing_tds, sacks_taken, pass_attempts, passing_yards, points_scored, rushing_yards}, efficiency_stats:{yards_per_play, …, third_down_conversion_rate, fourth_down_conversion_rate}}, defensive:{defense_dvoa, counting_stats:{sacks, qb_hits, tackles, tds_allowed, qb_pressures, interceptions, plays_allowed, yards_allowed, missed_tackles, points_allowed, carries_allowed, receptions_allowed}, efficiency_stats:{…}}, special_teams:{…}}}` |
| NBA | `stats:{general:{age, minutes}, offensive:{counting_stats, efficiency_stats}, defensive:{…}, rebounding:{…}}`, position e.g. `"Forward"` | (not sampled) |
| MLB | `stats:{batting:{H:{rank:43, value:132, metric_id:"METR_hits", rank_type:"high_to_low", value_away:66, value_vRHP:99, metric_name:"Hits", percentile_rank:92, qualified_players:515}, R, PA, AVG, OPS, RBI, wRC_plus, …}}` | `stats:{batting:{H,R,1B,2B,3B,AB,BB,CS,EV,HR,LA,PA,SB,SF,SO}, fielding:{A,E,DP,FP,PO,DRS,Inn,OAA,UZR,Defense,UZR_per_150}, pitching:{H,L,R,W,BB,BS,CG,ER,EV,HR,IP,QS,SO,SV,WP}}`, items `{rank, value, metric_id, rank_type, metric_name}`; `general: null` |

Keys are **snake_case** (`points_per_game`, `passing_yards`), not the guide's camelCase. The doc's `rank_total_players` appears live as `total_position_players`.

## 3.13 Injuries, trades, trends

**Injuries** — **[LIVE] 5 keys** `['player','team','status','event','played']`; `player` = 8-key Player; `team` = `{id,name,fullName,abbr}`; `event` = 6-key mini.
* `status` **[LIVE≠DOC]**: bare designation with **no " - description" suffix**: `"Injured Reserve"` (214 of 434 NFL), `"Questionable"` (178), `"Out"` (42), and **`null`** (row 0 of the unfiltered list). The doc's `"Questionable - Knee"` form and the guide's uppercase enum + `description` field were not observed. Parse defensively: `designation = status.split(" - ")[0] if status else None`.
* `played`: `true` played despite report, `false` did not play, `null` event not yet occurred / unknown. All 434 `league=NFL` rows (current designations) are `null`; Mahomes rows: IR games Dec-2025/Jan-2026 `false`, Aug/Sep-2026 `Questionable` → `null`.
* One row **per player-per-event** (Mahomes → 7); `league=` restricts to current designations; `pageSize/pageNum` → `{"objects","totalPages"}` (MLB `totalPages: 14` at 20/page).

**Trades** (`/trades/{TEAM_}`) — Player rows; `?injuries=true` adds `injury: {status: "Injured Reserve", nextEvent: {…6-key event…}} | null` (16 of 63 non-null for KC).

**Trends** — documented `TRND_` objects (`name`, `detail` (LLM text, nullable), `confidence` 0–100, `player{…,headshot,position}`, `team{…,logo}`, `event`, `marketSelection{id,type "PlayerProp",event,segment,proposition "Points",position,metric,marketOffer MOFR_,market}`, `metadata{line (mode line across books), L5/L10/L15/L20 {hits,hitPerc}|null, hitChart[bool] last 15 oldest-first, hitChartPerc}`); "Only trends whose underlying market selection is still available and whose data was refreshed in the last 48 hours are returned." **[LIVE] always `[]`** for us (no filter / NFL / MLB); `?sport=basketball` → `400 "Invalid sport"`.

## 3.14 betSync objects (live shapes)

**Bettor** — **[LIVE] 4 keys** `{id, internalId, betRefreshRequested, timeCreated}` (`metadata` only via `?metadata=true` / `/metadata`: `{handle, unitSize, netProfit, winPercentage, totalAccounts}` — cents).

**BettorAccount** — **[LIVE] 17 keys** `['id','bettor','book','bookRegion','verified','access','paused','betRefreshRequested','latestRefreshResponse','latestRefreshRequestId','balance','timeCreated','missingBets','isUnverifiable','timeUnverified','TFA','refreshInProgress']`; `bettor` = bare `BTTR_` string; `book` `{id,name,abbr}`; `bookRegion` `{id BRGN_, name, abbr, status, country, sdkRequired, mobileOnly}`; `latestRefreshResponse` `{id RRES_, timeCreated, status:200, detail, requestId, type:"verify"}`; `balance` int cents; **`timeUnverified`** undocumented. Refresh in progress ⇔ `latestRefreshRequestId != latestRefreshResponse.requestId` or `refreshInProgress`.

**BetSlip** — **[LIVE] 21 keys** `['id','bettor','book','bettorAccount','bookRef','timePlaced','type','subtype','oddsAmerican','atRisk','toWin','status','outcome','refreshResponse','incomplete','netProfit','dateClosed','timeClosed','typeSpecial','bets','adjusted']`. `type` `single|parlay`; `subtype` `round robin|teaser|null`; `status` `pending|completed`; `outcome` `win|loss|push|void|cashout|halfwin|halfloss|null`; money in **cents** (`atRisk 2035`, `netProfit -2035`); `toWin`/`oddsAmerican` **nullable** (Underdog parlay); `bookRef` = book's own ticket id (UUID for Underdog, `"638554742746688754"` BetMGM); `timeClosed` = pending→completed transition; `adjusted` `{odds, line, atRisk}` (null/bool/int).

**Bet** — **[LIVE] 23 keys** `['id','type','event','segment','proposition','segmentDetail','position','line','oddsAmerican','status','outcome','live','incomplete','bookDescription','marketSelection','autoGrade','segmentId','positionId','propDetails','sdioMarketId','sportradarMarketId','oddsjamMarketId','theOddsApiMarketId']` — `event` is the **full 18-key Event**; `marketSelection` is a bare `MRKT_` string (join key to betPrices); **`theOddsApiMarketId`** undocumented; `segmentDetail` ∈ `Including Overtime`, `Including Overtime and Shootouts`, `Including Extra Innings`, `Including Playoffs`, `Excluding …`; `live` = placed in-play; `autoGrade` = graded by SharpSports engine.

**RefreshResponse** — `{id RRES_, bettorAccount{id, bettor, book{id,name,abbr}}, timeCreated, status ∈ 200 (ok) | 202 (ok, slips omitted → fetch `/betSlips?refreshResponse=`) | 401 (handled login error) | 403 (access revoked) | 406 (bad OTP) | 424 (book maintenance) | 429 (rate limited) | 500 (<2 % unhandled), detail, requestId (32 hex), type ∈ manual|verify|reverify|cadence|system|grade, betSlips[]}`. Refresh request response = bucketed `BACT_` arrays: `refresh, unverified, noAccess, bookInactive, bookRegionInactive, rateLimited, isUnverifiable, paused, otpRequired, authParamRequired, extensionUpdateRequired` + `betRefreshRequested`, `requestId` (+ prose-only `cid`, `extensionDownloadUrl`, `backgroundRefreshRequired`).

**Webhook payloads** — `{"event":"refreshresponse.created","sender":"SampleApp","data":{"id":"RRES_…","timeCreated":…,"bettor":"BTTR_…","bettorAccount":"BACT_…","status":200,"detail":null,"type":"manual","requestId":"…","betSlips":[]}}`; `bettoraccount.unverified` data `{id, bettor, book:"wh" (abbr), region:"New Jersey"}`. Webhook log rows `{id:int, requestId:uuid, event, url, status, timeCreated, eventObject}`.

## 3.15 Timestamps, units, enums (summary)

| Item | Convention |
|---|---|
| All timestamps | ISO-8601 UTC with `Z`; sub-second (`.991000Z`) on historic windows and betSync `timeCreated`; whole seconds on `startTime`. Filters take `%Y-%m-%dT%H:%M:%S` or `%Y-%m-%d` (naive, treated as UTC — **[UNKNOWN]** officially) |
| Dates | `startDate`, `dateClosed`, `pullBackToDate`, `changeDate` = `YYYY-MM-DD` |
| Odds | American integers everywhere (`odds`, `oddsAmerican`, `minOdds/maxOdds`); `impliedProbability` float 0–1 |
| Lines | float; `0.0` for no-line markets in `/prices` and historic (`null` only in the MarketSelection doc sample and on `Bet.line`) |
| Money (betSync) | integer **cents** (`atRisk`, `toWin`, `netProfit`, `balance`, `handle`, `unitSize`) |
| `seasonType` | `PRE` \| `REG` \| `POST` (param enum); live value `REG`/null |
| `status` (Book/BookRegion) | `active` \| `inactive` \| `coming` \| `unsupported` |
| `type` (Market/Selection/Bet) | `straight` \| `prop` |
| `position` casing | `Over`/`Under`/`Draw` capitalised (guide's lowercase `over` is wrong) |
| `locationType` vs `gameStats.location` | `Home`/`Away` vs `home`/`away` |

---
# 4. Streaming

**There is no streaming channel for prices.** No WebSocket, SSE, or long-poll endpoint exists anywhere in the docs mirror or the OpenAPI blocks; the betPrices quickstart's "real-time updates" recipe is a **30-second poll of `GET /prices?eventId=`** ("Poll for odds changes", `interval=30`). No `updates every N seconds` statement exists for the backend feed. [DOC]

| Aspect | Value |
|---|---|
| Protocol | none (REST polling only) |
| Auth | n/a |
| Subscribe/filter model | n/a — emulate with `/prices?eventId=a,b,c&book=…&marketId=…` |
| Message types / payload | n/a |
| Ordering / cursor / resume / replay | n/a — every poll is a full snapshot; no sequence numbers, no ETag/`If-Modified-Since` observed |
| Heartbeat / close codes | n/a |
| Compression | responses are plain `application/json`; `content-length` present; gzip negotiation not tested [UNKNOWN] |
| Observed throughput | `/prices?eventId` 1.67 MB / 0.28 s (≈ 6 MB/s); `/prices?league=MLB` 17.5 MB / 2.1 s |

**The only push mechanism is betSync webhooks** (§2.6): `bettor.created`, `bettorAccount.verified|unverified|inaccessible`, `refreshResponse.created`. Delivery is HTTPS POST with `Hook-HMAC` (base64 HMAC-SHA256 over the **raw** body) and `Hook-Subscription` (uuid); respond 200 within 10 s; no replay/timestamp header (dedupe on `data.id`/`requestId`). The React-Native SDK depends on `@pusher/pusher-websocket-react-native` — Pusher is used inside SharpSports' own client SDKs, **not exposed to API consumers** [DOC].

---

# 5. Historical data

## 5.1 Endpoints

| Endpoint | Grain | Depth observed | Granularity | Limits |
|---|---|---|---|---|
| `GET /prices/historic/summary` | per selection: one window first→last offer, `consensus{open,close}` + `books[]{open,close}` | earliest `windowStartTime` seen **2024-08-16T23:21:47Z** (Mahomes 2024-season props); NFL 2023 season / NBA Jan-2024 / NFL 2022 → **all empty** | one window | mode C (player/team) capped at **2 000 selections** (400) and pathologically slow (50–98 s; 2× timeouts > 120 s); mode B (eventId) 761 selections/13 s unpaged |
| `GET /prices/historic/timeseries` | per selection, windows | same store as summary | `5m` · `15m` · `1h` · `4h` · `1d` (default = summary-style ~11 windows) | **≤ 1 000 windows / query**; one selection per call |
| `GET /events?upcoming=false` | events | ≥ **2015-09** (NFL), 2018-10 (NBA), 2019-04 (MLB), 2019-08 (EPL) | — | 500 default / `limit` up to ≥ 806 |
| `GET /marketSelections?historic=true` | selections of past events | as far as events exist (NFL 2022 selections returned) | — | 500 / paged |
| `GET /players/{id}/historicData` | player game log | NBA 2023-01 · NFL 2023-09 · MLB 2024-03 · soccer none | per game, all metrics | none (array) |
| `GET /teams/{id}/historicData` | team game log | **current season only** (16 KC games 2025) | per game | none |
| `GET /marketSelections/{id}/historicData` | game log vs line | 442 MLB games from 2024-03-29 | per game | `gamesBack` |
| `GET /marketSelections/{id}/metadata` | hit-rate splits | `dataStartDate` 2024-03-29 (MLB) / 2023-09-11 (NFL doc) | L1–L20, season, splits | — |
| `GET /injuries` | player-event rows | 2024-09-08 rows present (`played` backfilled) | per event | paged |
| `GET /prices` | — | **live only**: past events → `markets: []` | — | — |

## 5.2 Price-history depth per lead time [LIVE]

| Event | Sport | First window | Lead before start |
|---|---|---|---|
| MIN @ CHI 2025-09-09 (`MRKT_d397f871…`) | NFL | 2025-05-15T03:30Z | **~4 months** (schedule release) |
| DET @ PHI 2025-08-03 | MLB | 2025-08-02T18:00Z | ~1.2 days |
| SEA @ BAL 2026-06-11 / NYM @ CWS 2026-08-21 | MLB | 6–7 days before | ~1 week |
| MIA @ LAL 2025-11-03, and NBA Dec-25/Jan-26/Mar-26 | NBA | 2.3–6.3 days before | 2–7 days |
| SF @ PIT 2026-09-03 ML (`MRKT_51d96e28…`) | MLB | 2026-08-28T13:03Z | 6 days |
| Devers H+R+RBI Over (`MRKT_7cd1e436…`) | MLB prop | 2026-09-03T02:15Z (PrizePicks first) | 14 h |
| NFL 2025-09 KC spreads (team summary) | NFL | 2025-05-15T03:15Z | 4 months |
| Mahomes props 2025-09 … 2026-02 | NFL | 2025-05-15T17:03Z | season-long; 38 of 749 selections empty |
| Mahomes props 2024-09 … 2025-02 | NFL | **2024-08-16T23:21Z** | earliest data anywhere |
| Mahomes props 2023-09 … 2024-02 | NFL | — | **100/100 empty** |
| NBA 2024-01-17, NFL 2022-09-13, NFL 2023-09-12 | | — | **empty** (`timeseries` w/o range → 404) |

⇒ **Price history begins with the 2024 NFL season (Aug 2024); nothing earlier is retrievable.** Retention forward is unknown [UNKNOWN] — nothing suggests pruning within the 2024-08 … 2026-09 span observed.

## 5.3 What history contains (and doesn't)
- Per book, per window: `open` and `close` quote `{line, odds, impliedProbability}` + prediction-market volumes. **No high/low, no tick count, no per-tick timestamps** [LIVE≠DOC].
- Consensus open/close per window (cross-book; method undocumented).
- Windows omitted when no data; no carry-forward.
- Books appearing in history = the same 12 odds-feed books (incl. `pn`, `kl`, `pm`, `pp`, `ud`).
- **Closing line** = `close` of the last window before `event.startTime` (use `timeseriesEnd=startTime`); the summary's `close` may be **after** kickoff if in-play quotes exist (doc: `live` prices are stored; summary window ends at last offer).
- Historic **selection identity only** (`id`, `position`, `positionId`) — join to `/marketSelections?eventId=&historic=true` (16-key rows with vendor ids) for market/event context.

---

# 6. Cross-provider identifiers

Every field referencing another vendor, with live examples. **No OpticOdds v3 id, no OddsPapi id, no statsperform id, no rotation numbers, no Betradar-prefixed ids exist anywhere.**

| SharpSports object · field | Vendor | Format / example | Fill rate observed |
|---|---|---|---|
| `Event.oddsjamId` · `MarketSelection.oddsjam.eventId` · `MarketSelection.event.oddsjamId` | **OddsJam = OpticOdds legacy `game_id`** | `"36707-80389-2026-09-03-09"` (`homeTeamId-awayTeamId-YYYY-MM-DD-HH`, MLB/NBA/NHL), `"74813-25327-22-37"` (`-YY-WW`, NFL/NCAAF), `"16341-12806-23-37"` | MLB 804/806, NFL-2023 15/15, **NFL-2026 0/50, EPL 0/50, NBA-2024 0/17, NBA-2026-04 1/33** — populated mainly where OddsJam legacy ids existed; the 5-digit tokens are OddsJam team ids |
| `Market.oddsjamId` · `MarketSelection.oddsjam.marketId` · `Bet.oddsjamMarketId` | OddsJam market key | `moneyline`, `point_spread`, `team_total`, `2nd_half_moneyline`, `player_passing_completions`, `1st_quarter_moneyline_3-way`, `player_rebounds_+_assists` | 36/1000 markets; ML selections yes, props mostly null |
| `Team.oddsjamId`, `Player.oddsjamId` | OddsJam entity ids | 12 upper-hex `2D71E5BA64A5` (KC), `B671C99CB711` (Mahomes), `8E80F9DD4C5E` (LAD); 16-hex `A90E4D5A4489FA48` seen on a pitcher | US teams/players populated; soccer players null |
| `Event.sportradarId` · `MarketSelection.sportradar.eventId` · `/events?sportradarId=` | Sportradar match UUID (no `sr:match:` prefix) | `5750e479-d408-4b22-806b-94fba622a3e3` | MLB 803/806, NFL 50/50, EPL 50/50, NBA 2024 17/17; NBA-2026-27 preseason 0/15. Reverse lookup works |
| `Market.sportradarId` · `MarketSelection.sportradar.marketId` · `Bet.sportradarMarketId` | Sportradar market id | `sr:market:1` (ML MLB/NHL/NCAA), `sr:market:219` (ML NFL/NBA), `sr:market:223` (spread), `sr:market:303`, `sr:market:7002`, `sr:market:914` (player pass yds); Bet doc shows numeric `"1377060"` equal to `sdioMarketId` — inconsistent | 16/1000 markets |
| `League.sportradarId` | Sportradar competition | UUID (`2fa448bc-…` MLB) **or** `sr:competition:17` (EPL) | 24/138 |
| `Team.sportradarId`, `Player.sportradarId`, `startingPitcher.sportradarId` | Sportradar entity ids | UUID for US sports; **`sr:player:108579`** for soccer players | high for US sports |
| `Event.sportsdataioId` · `MarketSelection.sportsdataio.eventId` · `/events?sportsdataioId=` · `/marketSelections?sdioEventId=` | SportsData.io GameID | `"10079387"` (MLB), `"18021"` (NFL), `"20020111"` (NBA), `"62518"` (tennis), `"1230"` (futures containers, shared) | 806/806 |
| `MarketSelection.sportsdataio.marketId` · `MarketOffer.sdioMarketId` · `Bet.sdioMarketId` · `/marketSelections?sdioMarketId=` | SportsData.io BettingMarketID (per event-market) | `"8680470"`, `"8683280"` | 160/361 offers; selection-level populated |
| `Market.sportsdataioId` · `League.sportsdataioId` · `Team/Player.sportsdataioId` | SportsData.io ids | Market: **0/1000**; League `"1"` (EPL), 93/138; Team `"16"`; Player `"18890"` | |
| `Event.theOddsApiId` · `/events?theOddsApiId=` · `/marketSelections?theOddsApiEventId=` · `/marketOffers?theOddsApiEventId=` | The Odds API event id (32 hex, doc `"906a0faf52da9de59f381f82f7bf7116"`) | **null on 0/806 + 0/50 + 0/50 + 0/33 + 0/15 events sampled** | effectively unpopulated for us |
| `Market.theOddsApiId` · `MarketSelection.theOddsApi.marketId` · `Bet.theOddsApiMarketId` · `/markets?theOddsApiId=` · `/marketSelections?theOddsApiMarketId=` | The Odds API market key | `h2h`, `h2h_h2`, `h2h_p3`, `spreads_1st_3_innings`, `totals_q4`, `team_totals`, `outrights`, `player_points`, `player_pass_yds`, `batter_hits_runs_rbis`, `player_goal_scorer_first` | 35/1000 markets; ML/major props on selections |
| `Price.bookIds{eventId, marketId, selectionId}` | **Sportsbook-native ids** 🔐 | Kalshi ticker parts `26SEP041905BOSBAL` / `KXMLBGAME` / `BOSY`; Polymarket `947639` / `4059453` / `1`; PrizePicks `MLB_game_w99uVTzRiEf1cRPRSgEvdQfV` / projection `14445115`; Pinnacle `1634945554` / `1635468120` / `1635468121`; BetRivers `1024787504` / `2687633615` / `4321965256`; doc dk `30589142_moneyline`, fd `42.570304298` | 2888/2888 prices |
| `Price.betPlaceLinks` | native URLs | `kalshi.com/markets_by_ticker/kxmlbgame-26sep041905bosbal-bos?orderSide=yes`, `polymarket.com/event/mlb-cin-lad-2026-09-07`, `app.prizepicks.com/board/?projections=14445115` | |
| `BetSlip.bookRef` | book's ticket id | `638554742746688754` (BetMGM), UUID (Underdog) | |

**Mapping strategy implications:**
1. **SharpSports ↔ OpticOdds:** `Event.oddsjamId` is the OddsJam/OpticOdds *legacy* game id format (`teamA-teamB-date[-hour]` / `-YY-WW`). OpticOdds v3 fixture ids differ; verify whether v3 exposes the legacy id (open question tracked in the cross-provider notes). Market keys: `Market.oddsjamId` (`player_passing_yards`, `point_spread`) very likely equal OpticOdds market names — but only 36/1000 are populated, so build the map from **name/segment/metric**, not from ids.
2. **SharpSports ↔ OddsPapi:** no shared id. OddsPapi carries `externalProviders.opticoddsId` (established fact) → chain SharpSports → OddsJam legacy id → OpticOdds → OddsPapi only if OpticOdds exposes both. Otherwise fuzzy-match on `(sportId, startTime ±, contestant names)`.
3. **Sportradar UUID** is the densest hub on SharpSports (events, teams, players, leagues) — usable only if another feed exposes Sportradar ids (OpticOdds `source_ids` are statsperform, not Sportradar).
4. **The Odds API** ids exist only at market-key level for us; `Event.theOddsApiId` is null everywhere sampled.
5. **Kalshi/Polymarket native ids in `bookIds`** let us join SharpSports prediction-market quotes directly to Kalshi tickers (`KXMLBGAME-26SEP041905BOSBAL-BOS`) and Polymarket market ids — this is the most valuable bridge for the prediction-market leg.

---
# 7. Latency / freshness / staleness semantics

## 7.1 Exact doc language
- Price.`live`: *"When `true`, this price represents a value that has been updated since the event began."*
- Price.`main`: *"When `false`, this price represents an 'alt' line."*
- betPrices quickstart: *"Real-time odds from 20+ sportsbooks"* … *"Poll for odds changes"* (30 s example). No statement of backend refresh cadence, no "updated every N seconds", no per-book delay figures.
- Historic timeseries: *"When no price data exists in a time window, the last known values are carried forward … The `bookCount` and `pricePointCount` fields reflect actual data availability"* — **neither field nor the carry-forward behaviour is live** [LIVE≠DOC].
- Trends: *"data was refreshed in the last 48 hours"*.
- betSync: *"we rely on the sportsbooks for the bet status. You'll need to run frequent refreshes"*; refresh *"can take up to 2 minutes"*, SDK books *"30-60 seconds"*; `RefreshResponse.betSlips` *"represents the state of the betSlips at the time of this RefreshResponse event"*.

## 7.2 Observed numbers [LIVE]

| Measure | Value |
|---|---|
| `/prices?eventId=` round trip | 0.16–0.79 s (typ. 0.28 s for 1.7 MB) |
| `/prices?league=` round trip | 1.1–6.9 s |
| Quote timestamps in `/prices` | **none** — freshness unknowable from the payload |
| Finest recoverable line-change resolution | 5-minute windows (`rollup=5m`) in `/prices/historic/timeseries`, with open/close only |
| Historic window timestamps | µs precision on `windowStartTime/EndTime` (e.g. `2026-09-03T02:15:00.991000Z`) — these are **window bounds**, not quote times |
| Consensus vs book divergence within one summary window | e.g. SF ML: consensus open `-100` → close `139`; books open 125–144, close 134–153 |
| `/events` server time vs data | `date:` header present on every response — use it (not local clock) as `recv_ts` source to avoid clock skew |
| `/marketSelections?league=` | 22–32 s → useless for freshness |
| betSync bet visibility | minutes-scale (manual/cadence refresh ≥ 60 s apart, up to 2 min per refresh) |

## 7.3 Which fields to use for per-quote latency estimation
1. **`recv_ts`** = client wall-clock at response receipt (or the HTTP `date` header) — the only quote-time proxy; store it on every price row.
2. **`live`** — flags in-play-updated quotes; combined with `event.startTime` it tells whether a pre-match quote is stale after kickoff (`live=false` & `now > startTime` ⇒ possibly frozen).
3. **`main`** — alt lines are refreshed less predictably; prefer `main=true` for freshness-sensitive comparisons.
4. **`betPlaceAvailability[abbr]`** (MarketSelection) — false while a book has pulled the market; a cheap "suspended/off" proxy.
5. **Historic `books[].close` at `windowEndTime`** — post-hoc estimate of when a book last moved (5 m floor).
6. **Cross-book dispersion** within a snapshot (e.g. `pn` vs `dk` implied probabilities) — a stale book shows as an outlier vs consensus; there is no vendor-side staleness flag.

**No `suspended`, `status`, `timeUpdated`, `lastChanged`, or sequence field exists on any pricing object.** SharpSports is a **snapshot** feed with unknown internal cadence; treat every quote as "as of `recv_ts`, possibly older".

---

# 8. Edge-relevant facts for arbitrage / market making

| Topic | Fact | Source |
|---|---|---|
| **Sharp reference** | **Pinnacle (`pn`) prices are in the feed** (724 prices over 10 MLB events; ML, spread, total, F5 lines, team totals, selected player props, futures). `status: unsupported` hides it from the default `/books`; `ev` is populated on Pinnacle prices | [LIVE] |
| **Prediction markets on sports** | **Kalshi (`kl`) and Polymarket (`pm`)** quotes with `impliedProbability` = share price and `marketOfferVolume`/`marketSelectionVolume` (2 729 of 3 151 quotes carried volume); `bookIds` give the exact Kalshi ticker and Polymarket market id for direct execution | [LIVE] |
| **DFS pick'em** | PrizePicks/Underdog player-prop lines exposed as selections with odds mostly `+100` (changelog: "All odds are set at +100"); live also shows `-137/-119/-112` (non-standard multipliers). Some markets are DFS-only (`Total Fantasy Points`, `Total Walks`, 1st-inning Underdog props) | [DOC]+[LIVE] |
| **Alt-line ladders** | Full ladders per book via `main=false` prices: ca 19, fd 19, dk 17, br 16, kl 11, hr 8 rungs on one MLB selection → per-book implied distributions, middles, derivative pricing | [LIVE] |
| **Best-price primitives** | `minOdds/maxOdds` server-side line picking ("DFS books are excluded"); `bestPrice{line, odds, ev, book}` on historicData/metadata; `ev` (undocumented) on Price | [DOC]+[LIVE] |
| **Fair-value anchors** | `consensusProjection` per prop ("from various sportsbooks and prediction models"), historic `consensus{open,close}`, trends `metadata.line` = mode line across books | [DOC]+[LIVE] |
| **Opening / closing line & CLV** | `summary.books[].open` = first quote per book (up to 4 months pre-game for NFL, ~1 week NBA/MLB); `timeseries` with `timeseriesEnd=startTime` gives the closing quote per book; earliest data 2024-08 | [LIVE] |
| **Settlement timing (betSync)** | `BetSlip.timeClosed` = pending→completed transition; `Bet.outcome` incl. `void/cashout/halfwin/halfloss`; `autoGrade` marks SharpSports-graded results | [DOC] |
| **Executed prices** | Synced bets carry `oddsAmerican`, `line`, `timePlaced`, `book.abbr`, `live`, `adjusted{odds,line,atRisk}` and the `marketSelection` id → CLV per bettor/book vs our closing lines; bettor `metadata`/`statistics` (ROI by league/book/slipType incl. `live`) rank sharpness | [DOC] |
| **Availability / suspension** | `betPlaceAvailability{abbr:bool}` on every live selection (25 books) and `lineAvailability` ladders = "book currently offers this" flag; a book disappearing from `books[]` in `/prices` = pulled | [LIVE] |
| **In-play** | `live` flag per price; no book delay figures; polling only | [DOC] |
| **Limits / order-book depth** | **None.** No stake limits, no lay/back, no depth beyond prediction-market volumes. Use `bookIds` to hit Kalshi/Polymarket APIs for depth | [LIVE] |
| **Thin markets** | Single-book markets per the doc taxonomy (Caesars-only game props, Fanduel-only inning spreads, BetMGM-only NHL `Goals Allowed`/`Shutouts`, DraftKings-only correct-score segments) — stale-line candidates | [DOC] |
| **Info edges** | `/trades/{team}` (30-day roster moves) + `injuries=true`; `/injuries?league=` current designations; `gamesWithout=<PLYR_>` on/off splits; MLB `startingPitcher` + `hand`, park factors; NFL DVOA / EPA aggregates | [DOC]+[LIVE] |
| **Sandbox** | Sandbox refreshes generate graded slips on real markets → free settlement-pipeline testing | [DOC] |

---

# 9. Gotchas, doc-vs-live contradictions, and open questions

## 9.1 Resolved by the probe (doc-vs-live)

| # | Topic | Doc | Live | Status |
|---|---|---|---|---|
| 1 | `marketSelectionId` prefix on historic endpoints | `MSEL_*` | `MRKT_` (`MSEL_x` → 404) | ✅ resolved |
| 2 | `/prices` `proposition` filter | quickstart uses it | `400 "Invalid query parameter: proposition"` | ✅ not supported |
| 3 | Price timestamp | quickstart `timeUpdated`, `id PRICE_` | absent; 10-key Price | ✅ none |
| 4 | Price `ev` | undocumented | present on all prices (null/float) | ✅ new field |
| 5 | `bookIds`/`betPlaceLinks` gating | betPlace subscription | serialized for us on 100 % of prices | ✅ entitled |
| 6 | `bs` book name | ESPN BET | **theScore** | ✅ live name |
| 7 | Pinnacle abbr / feed | unknown | `pn`, `status: unsupported`, `oddsFeedActive: true`, prices returned | ✅ |
| 8 | Kalshi / Polymarket abbrs | unknown | `kl` / `pm`, both `oddsFeedActive: true` | ✅ |
| 9 | Historic response shape | OHLC + `bookCount`/`pricePointCount` + carry-forward; summary `first/last/high/low offers` | `consensus{open,close}` + `books[]{open,close}`, windows omitted when empty | ✅ **[LIVE≠DOC]** |
| 10 | Timeseries defaults | `rollup=1h`, start = event−24 h, end = event start | no-param call ≡ summary (~11 windows over full history) | ✅ **[LIVE≠DOC]** |
| 11 | Timeseries ordering | guide code assumes newest-first | **ascending** | ✅ |
| 12 | `historicData.line` required | OpenAPI required | optional (falls back to bestPrice line) | ✅ |
| 13 | `bestPrice` shape | 3 variants | one: `{id PRICE_, line, odds, ev, book{id,name,abbr}}` | ✅ |
| 14 | `hits` semantics for Under | ambiguous | counts Overs regardless of position | ✅ (doc sample) |
| 15 | Event `venue` | undocumented / guide object `{id VENU_, name, city}` | plain **string** or null | ✅ |
| 16 | Event `seasonType` | undocumented | `"REG"`/null | ✅ |
| 17 | `contestantAway/Home` | `{id, fullName}` | `{id, fullName, abbr}` | ✅ |
| 18 | Event `endTime` (MarketOffer embed) | documented | absent | ✅ |
| 19 | `/events` default order | `ascending` default true / "default is descending" | **descending** | ✅ desc |
| 20 | `/events` `upcoming` on futures | default true | futures with 2023–2025 startTimes returned | ✅ not applied |
| 21 | `Event.startTime` nullability | datetime | **null** on TBD preseason games | ✅ nullable |
| 22 | `Event.league` nullability | "or null" for non-sporting | null on tennis (US Open) | ✅ |
| 23 | `Event.theOddsApiId` | changelog "added" | null on every sampled event | ✅ unpopulated |
| 24 | `Event.sportradarId` | "null unless you provide your API keys" | populated (803/806 MLB) | ✅ populated |
| 25 | MarketSelection `prices` map | default `prices=true` | never serialized | ✅ **[LIVE≠DOC]** (explicit `prices=true` untested) |
| 26 | MarketSelection `theOddsApi`, `marketOfferId` | undocumented | present | ✅ |
| 27 | `propDetails.matchupSpecial` | documented | absent (7-key propDetails) | ✅ |
| 28 | `/marketOffers` required param | none | one of 5 event-id params (incl. `theOddsApiEventId`) | ✅ |
| 29 | League filter casing | "name or id" | `/markets` 400 on lowercase; `/teams`,`/players` silent `[]` | ✅ per-endpoint |
| 30 | `/players/{id}/historicData` params | none | `gamesBack` works; others ignored; `seasonType=POST` → `[]` | ✅ |
| 31 | Game-log `event` embed | `{id,sport{id,name},league{id,name,abbr},…,sportId,leagueId}` | 6-key mini with string `sport`/`league` | ✅ **[LIVE≠DOC]** |
| 32 | `aggregateStats` | object | **list** of per-season objects; MLB/NBA shapes differ from the NFL doc | ✅ |
| 33 | Injury `status` | `"Questionable - Knee"` / uppercase enum + `description` | bare `"Injured Reserve"`, `"Questionable"`, `"Out"`, or null | ✅ |
| 34 | Park factor | `parkFactorPerc` 100 = neutral / guide `1.12` | signed int `2`, `0`, `-4` | ✅ **[LIVE≠DOC]** |
| 35 | Futures market names | `Future Winner AL Central 2024` | generic `Future Winner`; season on the Event | ✅ |
| 36 | `Bet.theOddsApiMarketId`, `BettorAccount.timeUnverified`, `Book.backgroundRefresh`, `Player.changeDate` | undocumented | present | ✅ |
| 37 | `/teams/{id}/historicData` | undocumented | works (current season) | ✅ |
| 38 | Pagination misuse | — | `pageSize` without `pageNum` → 400 DRF repr | ✅ |
| 39 | `limit` > 500 | "max number … default 500" | honoured (806) | ✅ |
| 40 | Out-of-range `pageNum` | — | returns data (clamps) | ✅ |
| 41 | `/trends` | 48 h trends | always `[]`; `sport=basketball` → 400 | ✅ (empty for our account) |
| 42 | Auth errors | — | 401 bodies + `www-authenticate: Token`; Bearer rejected | ✅ |
| 43 | Rate-limit headers | none documented | none present | ✅ |
| 44 | `betPlaceStatus` value casing | `deeplink` | `deepLink` | ✅ |
| 45 | `theOddsApiEventId` on `/marketOffers` | not listed | accepted (in the required-param list) | ✅ |

## 9.2 Still-open questions [UNKNOWN]
1. **Backend refresh cadence per book** for `/prices` (no timestamp, no doc figure). Measure empirically by diffing consecutive snapshots.
2. **429 behaviour**: whether `Retry-After` accompanies `{"detail":"Request was throttled."}`; effective limit for `/prices` (50 vs 100 rps).
3. Does explicit `?prices=true` on `/marketSelections` re-enable the per-book ladder map? (never sent explicitly).
4. `Price.ev` definition (units, fair-line source) and why only Pinnacle/bestPrice carry it.
5. `marketOfferVolume`/`marketSelectionVolume` units (contracts, USD, cents?) for Kalshi vs Polymarket; meaning of Polymarket `-100/0.5` placeholder rows.
6. Historic `consensus` method (mean/median of which books?) and whether it includes DFS/prediction books.
7. Historic retention horizon going forward; whether in-play quotes are stored (summary `close` after kickoff).
8. `live` flag semantics under real in-play conditions (0 live prices observed).
9. Timezone of naive date filters (`%Y-%m-%d`) — assumed UTC.
10. Whether `season` on `/players/{id}/aggregateStats` means start year for NBA/NHL ("2025" = 2025-26?).
11. DVP direction (guide "rank 1 = easiest matchup" vs reference "1 = best defense"); all MLB samples null, no NFL/NBA sample captured.
12. Whether `Event.theOddsApiId` is ever populated (account-level entitlement vs data gap).
13. `/prices?league=` completeness for leagues with >500 events, and whether a size cap exists (no pagination).
14. Guide-only params (`home`, `away`, `pitcher`, `vsOpponent`, `winningMargin`, `teamAggStatsSeason`, injuries `event/status/played`) — untested.
15. `/refreshResponses/{id}`, `/bettors/{id}/betSlips/statistics|summary`, `/articles`, Pine — unprobed shapes.
16. `MOFR_` prefix (trends doc) vs `MKTO_` (live) — trends never returned data.

## 9.3 Coding rules distilled
- Key books by **`abbr`**, never `BOOK_` id format; bootstrap the universe from `/books` **and** `/books?status=unsupported`, filter `oddsFeedActive`.
- Always pass `LGUE_*` ids to `/markets`, `/teams`, `/players`; treat `[]` from a league-filtered call as suspicious.
- Always pass `ascending=true` (or handle desc) and explicit `startTimeStart/End` on `/events`; never assume `startTime`, `league`, `leagueId`, contestants are non-null.
- Never `json.loads` a non-2xx blindly; branch on `content-type`.
- Treat `MKTO_`/`MOFR_`, `BRGN_`/`BSTA_` as synonyms; URL-encode `BTTR_` ids.
- Parse historic windows as `open/close` only; do not expect `high/low/bookCount`.
- Stamp `recv_ts` on every price; compute Under hit-rates as complements.

---
# 10. Recommended ingestion strategy

## 10.1 Roles of each channel

| Need | Use | Not |
|---|---|---|
| Live odds snapshot (hot path) | `GET /prices?eventId=<a,b,c>` (0.3 s / 1.7 MB per event; comma-separated ids to batch) | `/prices?league=` (17.5 MB, 2–7 s) except as a periodic catch-all |
| Selection / vendor-id catalogue | `GET /marketSelections?eventId=&pageSize=100&pageNum=n` (or `limit=500` unpaged) | league-scoped `/marketSelections` (20–32 s) |
| Event discovery | `GET /events?league=LGUE_x&startTimeStart=&startTimeEnd=&ascending=true&limit=1000` per league | `upcoming=true&limit=N` (returns the *last* N) |
| Market/segment/metric/book taxonomy | `GET /markets?pageSize=1000&pageNum=1..totalPages`, `/segments`, `/metrics`, `/sports`, `/leagues`, `/books`, `/books?status=unsupported`, `/teams?league=LGUE_x`, `/players?league=LGUE_x&isMajorLeague=all` | — |
| Line history backfill | `GET /prices/historic/timeseries?marketSelectionId=&rollup=5m|15m&timeseriesStart=&timeseriesEnd=` (≤1 000 windows) and `…/summary?eventId=&pageSize=100&pageNum=n` | player/team summary mode (50–98 s, timeouts) |
| Fundamentals | `/marketSelections/{id}/metadata`, `/…/historicData`, `/players/{id}/historicData`, `/players/aggregateStats`, `/teams/aggregateStats`, `/injuries`, `/trades/{TEAM_}` | `/trends` (empty) |
| Our own executed bets / CLV | `GET /betSlips?timePlacedStart=…` + `refreshResponse.created` webhook | polling refreshes faster than 60 s |

## 10.2 Polling cadence within limits
Budget: 20 rps for `/marketSelections`, 50 rps everything else, no per-day cap. Bandwidth, not RPS, binds.

| Loop | Cadence | Calls | Notes |
|---|---|---|---|
| **L0 Bootstrap** (daily 06:00 UTC + on demand) | 1×/day | `/books` ×2, `/sports`, `/leagues`, `/segments`, `/metrics`, `/markets` ×5 pages, `/teams` + `/players` per tracked league | ~30 calls; persist raw |
| **L1 Event discovery** | every 15 min | `/events` per tracked league (`startTimeStart=today-1`, `startTimeEnd=today+7`, `ascending=true`, `limit=1000`) + `/events?league=…&future=true` daily | detect new `EVNT_`, `startTime` changes, null→set |
| **L2 Selection catalogue** | on new event + every 60 min per live-day event | `/marketSelections?eventId=&pageSize=100` (15 pages for a 703-selection game ≈ 20 s serial; parallel 5) | stores vendor ids, `betPlaceAvailability`; run `historic=true` variant after the event ends |
| **L3 Price snapshots (pre-match)** | every **60 s** per tracked event from T−24 h; every **15 s** from T−2 h | `/prices?eventId=` batched 3–5 ids per call | ~1.7 MB/event/call → 100 events @15 s ≈ 11 MB/s peak — throttle by size, spread starts |
| **L3' In-play** | every **5–10 s** per in-play event (`now > startTime`) | `/prices?eventId=` single | watch `live=true`; stop when `markets: []` |
| **L3'' Board catch-all** | every 5 min | `/prices?league=` per tracked league | reconciles missed events, futures containers |
| **L4 Historic backfill** | nightly, event-driven after final | `summary?eventId=&pageSize=100` (all pages) then `timeseries?rollup=5m` for selections we care about, windowed ≤1 000 | write windows idempotently |
| **L5 Fundamentals** | daily + T−3 h | `metadata` / `historicData` per tracked prop selection; `injuries?league=` hourly; `trades` daily | 1–2 s each; parallel ≤10 |
| **L6 betSync** | webhook-driven; `/betSlips?timePlacedStart=<last>` every 5 min as reconciliation | | |

## 10.3 Backfill plan
1. **Events:** `/events?league=LGUE_x&upcoming=false&startTimeStart=2024-08-01&startTimeEnd=…&ascending=true&limit=1000` in monthly slices (806 rows / 10 s per 2-month MLB slice) for every tracked league; earlier than 2024-08 only for event metadata (prices are empty).
2. **Selections:** per event `/marketSelections?eventId=&historic=true&pageSize=100` (16-key rows).
3. **Prices:** per event `/prices/historic/summary?eventId=&pageSize=100&pageNum=n` (1–4 s/page; 98 s outliers on some past events — set a 150 s timeout, retry once, then defer); for straight markets and headline props additionally `timeseries?rollup=15m` (≤1 000 windows ≈ 10 days) with explicit `[first_open − 1 h, startTime + 4 h]`.
4. **Game logs:** `/players/{id}/historicData` for rostered players of tracked leagues (~600 NBA, ~2 000 NFL, ~1 000 MLB calls; 1–10 s each; run overnight at ≤5 concurrent).
5. Stop conditions: `pricesTimeseries: []` for all selections of an event ⇒ mark "no history"; 404 on timeseries ⇒ same.

## 10.4 What to store raw vs normalized

| Raw (append-only, compressed JSON, partitioned by day) | Normalized (columnar) |
|---|---|
| Every `/prices` body with `recv_ts`, request URL, `date` header | `quote(recv_ts, event_id, market_id, offer_id, selection_id, book_abbr, line, odds, implied_prob, main, live, ev, offer_vol, sel_vol, book_event_id, book_market_id, book_selection_id)` — one row per price; dedupe consecutive identical rows per `(selection, book, line)` to store changes only |
| `/marketSelections` pages (live and historic) | `selection(id, event_id, market_id, offer_id, type, proposition, segment_id, position, position_id, player_id, team_id, metric_id, sdio_event_id, sdio_market_id, sr_event_id, sr_market_id, oj_event_id, oj_market_id, toa_market_id, first_seen, last_seen)` + `selection_availability(recv_ts, selection_id, book_abbr, available)` |
| `/events`, `/markets`, `/books`, `/leagues`, `/teams`, `/players`, `/segments`, `/metrics` snapshots | slowly-changing dimension tables keyed by SharpSports id with `valid_from/valid_to`; keep all vendor-id columns |
| Historic summary/timeseries bodies | `line_window(selection_id, book_abbr\|'consensus', window_start, window_end, open_line, open_odds, open_ip, close_line, close_odds, close_ip, open_offer_vol, close_offer_vol, open_sel_vol, close_sel_vol, rollup)` |
| metadata/historicData bodies | `prop_context(selection_id, asof, line, consensus_projection, dvp, dvp_rank, dvp_avg, park_perc, park_rank, sp_id, sp_hand, L1..L20 hits/hitPerc/mean/median/stdev, season_*, best_price_*)`; `game_log(player_id\|team_id, event_id, start_time, metric_id, value)` |
| injuries / trades | `injury(player_id, event_id, team_id, status, played, asof)` |
| betSync slips + webhooks | `bet(slip_id, bet_id, bettor_id, account_id, book_abbr, selection_id, event_id, odds, line, time_placed, time_closed, outcome, live, adjusted_*)` |

Never normalize away: `bookIds`, `betPlaceLinks`, `ev`, `propDetails`, the 16/18-key `event` embeds (they carry `oddsjamId`/`theOddsApiId` even when the parent lacks them).

## 10.5 Failure / resume handling
- **HTTP client:** 120 s timeout for `/prices/historic/summary` and `/marketSelections?league=`, 30 s elsewhere; retry 5xx/timeouts with jittered backoff (1, 2, 4, 8 s, max 4); **do not retry 400/403/404**; on 429 (`{"detail":"Request was throttled."}`) back off ≥1 s and halve the bucket for 60 s (no `Retry-After` observed).
- **Content-type guard:** parse JSON only when `content-type: application/json`; log HTML/str bodies as `provider_error`.
- **Idempotency:** price rows keyed by `(recv_ts, selection_id, book_abbr, line)`; windows keyed by `(selection_id, book, window_start, rollup)`; upsert dimensions.
- **Resume:** each loop persists its high-water mark (`last_recv_ts` per event for L3; `last pageNum` per event for L2/L4; `timePlacedStart` for L6). Snapshots are stateless — a restart simply re-polls; nothing is lost except the gap.
- **Drift detection:** assert Price key set == the 10 known keys, MarketSelection 18/16 keys, Event 18 keys; alert on new keys (SharpSports adds fields silently: `ev`, `theOddsApi`, `venue`, `seasonType`, `changeDate`, `timeUnverified` all appeared undocumented).
- **Empty-array policy:** `[]` from `/prices?league=` or `/events` is valid (off-season); alert only if a *known live* event returns `markets: []` before its `startTime + 4 h`.
- **Book universe check:** daily diff of `/books` (+unsupported) `oddsFeedActive` set vs the abbrs seen in the last snapshot; alert on new abbr (e.g. a book being added like Pinnacle was).
- **Webhooks:** verify `Hook-HMAC` over the raw body with the subscription secret; ack 200 in <10 s; enqueue; dedupe on `data.id`; reconcile with `/refreshResponses?timeCreatedStart=` hourly.
- **Secrets:** never log `Authorization`; store `SHARPSPORTS_API_SECRET` only in the secret manager; the public key can be used for L0 reference pulls to keep the private key's traffic separable.
