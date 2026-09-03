# OddsPapi v5 — Definitive Ingestion Spec (provider: `oddspapi`)

**Vendor:** OddsPapi / 55-tech (contact@55-tech.com) · **API version:** 5.0.0 (OpenAPI 3.1.0, AsyncAPI 3.0.0)
**Docs host:** `docs.oddspapi.io` (`/llms.txt`, `/llms-full.txt`, `/api-reference/openapi.json`, `asyncapi.json`)
**Status page:** `https://oddspapi-v5.instatus.com`
**Self-description (verbatim):** *"High-performance odds API backed by Valkey + Supabase RPC discovery."* / *"B2B low-latency realtime sports odds API… WebSocket-first pipe delivering odds from 200+ bookmakers, with snapshots and resume/replay."*
**Explicitly NOT:** *"an official or licensed league-data provider — it aggregates bookmaker prices rather than licensing official stats."*

Legend used throughout:
- **[DOC]** = stated in the documentation / OpenAPI / AsyncAPI.
- **[LIVE]** = observed with our trial key during the probe (2026-09-03T07:10–07:55Z, region `oddspapi-us1`, client `reid`).
- **[LIVE≠DOC]** = live behaviour contradicts the docs.
- **[UNKNOWN]** = not determinable from docs or probe; do not code assumptions.

---

# 1. Product & access summary

## 1.1 What we have (observed entitlements)

| Dimension | Observed value | Evidence |
|---|---|---|
| Key identity | `userId: "reid"`, WS `region: "oddspapi-us1"` | [LIVE] `login_ok` |
| REST base | `https://v5.oddspapi.io/en` (language prefix is part of the path) | [DOC]+[LIVE] |
| WS base | `wss://v5.oddspapi.io/ws` | [DOC]+[LIVE] |
| Sports entitled | **6 only: 10 Soccer, 11 Basketball, 12 Tennis, 13 Baseball, 14 American Football, 15 Ice Hockey** | [LIVE] `GET /sports` → list[6]; `GET /sports?sportIds=10,69` → **403 `sport_not_allowed`, body `denied:[69]`** |
| Prediction-market topics (sportId 69–78) | **NOT entitled.** `GET /futures?sportId=69` → `[]` (silent empty, no error); `GET /futures?sportId=76` → `[]`; `GET /futures/live?sportId=69` → `[]` | [LIVE] |
| Bookmakers entitled | **31** in `GET /bookmakers`; 19 of them with `playerProps:true` | [LIVE] |
| Bookmaker slugs confirmed | `188bet`, `198bet`, `3et`, `4casters`, `ballybet`, `bet365`, `betfair-ex`, `betmgm`, `betonline.ag`, `betparx`, `betrivers`, `betus`, `bookmaker.eu`, `borgata`, `bovada.lv`, `caesars`, `draftkings`, `fanduel`, `kalshi`, `pinnacle`, `polymarket`, `sx.bet` (list truncated in capture; full set = 31 rows of `GET /bookmakers`) | [LIVE] WS `login_ok.bookmakers` echo + odds payloads |
| Data-provider slugs (`opticodds`, `betradar`, `flashscore`) | **403 `bookmaker_not_allowed`** on `/fixtures/mapping` and `/fixtures/odds/historical`; silently dropped by `GET /bookmakers?bookmakers=…` | [LIVE] — resolves the "can I bulk-reverse-map OpticOdds ids?" question: **no** |
| Channels allowed (REST "channel" = endpoint family) | 34 allowed channels enumerated in 403 bodies; **`futures/odds`, `futures/odds/clv`, `futures/odds/historical` are NOT allowed** | [LIVE] `GET /futures/odds…` → 403 `channel_not_allowed` with `requestedChannels`/`allowedChannels` |
| WS channels allowed | `bookmakers, bookmakersFutures, clocks, currencies, events, fixtures, futures, injuries, lineups, odds, scores, stats` (12). **`oddsFutures` absent** — consistent with the REST futures-odds denial | [LIVE] `login_ok.channels` on a login with `channels` omitted |
| WS access flags | `access: {"live": true, "pregame": true}` | [LIVE] |
| Practical consequence | **We get: full fixture odds (pregame + live) for 6 sports across 31 books incl. exchanges (`betfair-ex`, `sx.bet`) and prediction markets (`polymarket`, `kalshi`) mapped onto *sports fixtures*; futures metadata only (no futures prices); no non-sport prediction-market topics.** | [LIVE] |

> **Important asymmetry:** `polymarket` and `kalshi` appear as *bookmaker slugs on ordinary sports fixtures* (with full order-book depth in `meta`), which we **do** have. The *non-sport* prediction markets (Politics, Crypto, …) are modelled as **futures on sportId 69–78**, which we **do not** have. So prediction-market arbitrage on sports events is available today; election/crypto markets are not.

## 1.2 Auth

| Item | Value |
|---|---|
| REST scheme | `ApiKeyAuth` = **apiKey in query string**, param name `apiKey`. `security: [{ApiKeyAuth: []}]` globally. [DOC] |
| Header auth | **Not documented, not tested.** [UNKNOWN] — assume query-only. |
| Example | `curl 'https://v5.oddspapi.io/en/bookmakers?apiKey=***'` |
| WS auth | No URL/header auth. First WS text frame must be `{"type":"login","apiKey":"…"}` within **10 s**, else close **4000**. [DOC]+[LIVE] |
| Key format | `^[0-9a-fA-F]{32}$` (AsyncAPI `LoginRequest.apiKey` pattern). [DOC] |
| Ops rule | The key lands in URLs → **always redact to `***` in logs, metrics, exception traces, and stored raw request URLs.** Env: `ODDSPAPI_API_KEY`; strip whitespace: `K="$(printf '%s' "$ODDSPAPI_API_KEY" | tr -d '[:space:]')"`. |

## 1.3 Base URLs and language prefix

| Purpose | URL |
|---|---|
| REST | `https://v5.oddspapi.io/{lang}` — `lang ∈ {en, es, fr, pt, de, it, ru, zh}`. Use **`en`** for ingestion. |
| WS prod | `wss://v5.oddspapi.io/ws` |
| WS dev/staging | `ws://v5-dev.oddspapi.io/ws` (AsyncAPI `servers.de-ws`; spec uses key `dev` instead of `host` — spec typo) |
| WS console | `https://v5-console.oddspapi.io` |

- *"Translated fields (for example names) follow the prefix language when available. Identifiers (`sportId`, `fixtureId`, etc.) are language-independent."* [DOC]
- Probe: `GET /de/sports` returned the same 6 rows with translated `sportName`. [LIVE]
- **Never branch on any `*Name` string** (`statusName`, `sportName`, `marketName`, …).

## 1.4 Rate limits — exact numbers

**Model:** *"Rate limits are counted per `apiKey` and by endpoint."* [DOC] — **confirmed per-endpoint** by the probe: within one 60 s window, `/fixtures/mapping` counted down 199→192 over 8 calls while `/fixtures/settlement`, `/fixtures/odds/clv`, `/fixtures/odds/historical` each independently started at 199 in the same window. [LIVE — resolves open question]

| Bucket | Endpoints | Limit | Window | Observed headers |
|---|---|---|---|---|
| **Odds (high-frequency)** | `GET /fixtures/odds`, `GET /fixtures/odds/main`, `GET /futures/odds` | **10 requests / second** | 1 s (reset = now+1 s, e.g. `x-ratelimit-reset: 1788420282` then `…283`, `…284`) | `x-ratelimit-limit: 10`, `remaining: 9` / `8` |
| **Everything else** | metadata (`/bookmakers`, `/sports`, `/tournaments`, `/seasons`, `/participants`, `/players`, `/venues`, `/markets`, `/currencies`), `/fixtures`, `/fixtures/today`, `/fixtures/live`, `/fixtures/odds/clv`, `/fixtures/odds/historical`, `/fixtures/mapping`, `/fixtures/settlement`, `/futures`, `/futures/live`, `/futures/mapping`, `/futures/settlement`, `/media/*` | **200 requests / minute** | 60 s (reset aligned to :00/:60 boundaries, e.g. `1788420120`, `1788420180`) | `x-ratelimit-limit: 200` |

Headers on every rate-limited response [DOC]+[LIVE]:

| Header | Meaning |
|---|---|
| `X-RateLimit-Limit` | Requests allowed per window (per apiKey, per endpoint) |
| `X-RateLimit-Remaining` | Requests left in the current window |
| `X-RateLimit-Reset` | **Unix seconds** when the window resets |
| `Retry-After` | On 429 only: seconds to wait |

429 body variants:
```json
// errors.md (full) [DOC]
{"error":429,"message":"rate limit exceeded","code":"rate_limited",
 "limit":30,"windowSec":1,"retryAfterSec":1,"endpoint":"/fixtures/odds","method":"GET"}
// openapi ApiError example [DOC]
{"error":429,"message":"rate limit exceeded","reason":"rate_limited","retryAfterSec":1}
```
- **[LIVE≠DOC]** The doc's 429 example claims `limit:30, windowSec:1` for `/fixtures/odds`; live headers say **10/s**. Trust headers/body at runtime; hardcode 10/s as the planning number.
- Limiter outage: `503 {"error":503,"message":"rate limiter unavailable","code":"rate_limiter_error"}`. [DOC]
- A 40-request burst was captured (`burst40_results`, 40 entries with `i, code, t, headers, body`); the per-code distribution was not summarised in the narrative — **do not assume burst tolerance**; treat 10/s as hard and use a token bucket. [LIVE, partially observed]
- `cf-ray` present on every response ⇒ Cloudflare in front. Useful correlation id for support tickets (log it alongside `X-RateLimit-*`).

**WS limits** [DOC]:

| Limit | Value |
|---|---|
| Concurrent connections | **max 5 per apiKey group** → error `too_many_connections`, close **4003** |
| Login deadline | first frame must be `login` within **10 s** → close **4000** |
| Backpressure | slow consumer → close **4002** |
| Replay window | `resumeWindowMs` (doc example & live `login_ok`: buffered window; see §4.6) |
| Message rate | *"Not explicitly limited, but filters are recommended for performance"* |
| Outbound frame size | *"The gateway does not limit outbound frame size; uncompressed `odds` frames can exceed 1 MiB"* |

## 1.5 Pagination

**There is none.** No `limit`, `offset`, `page`, or cursor parameter exists on any REST endpoint in `openapi.json`. List endpoints return a **bare JSON array**; single-entity endpoints return a bare object. [DOC]+[LIVE]

Observed size/count caps and de-facto limits [LIVE]:

| Endpoint | Observation |
|---|---|
| `GET /fixtures/odds/main?tournamentId=109` | returned **100** fixtures while `GET /fixtures?tournamentId=109` returned **333** → **suspected hard cap of 100 fixtures per odds/main call** (verify; not documented) |
| `GET /fixtures/odds/main?fixtureIds=…` | **50 ids accepted** in one call (2.1 MB response) |
| `bookmakers=` query param | **max 5 slugs**: 6 slugs → `400` with `hint` "Only 5 bookmakers allowed" |
| `fixtureIds`, `oddsIds`, `marketIds`, `venueIds`, `participantIds`, `playerIds`, `seasonIds`, `tournamentIds` | multi-id accepted; **no documented maximum** [UNKNOWN] |
| Largest single bodies seen | `GET /fixtures/odds/historical?bookmaker=draftkings` → **95.6 MB**; `?bookmaker=pinnacle` → 13.3 MB; `GET /markets?sportId=12` (tournaments) 1.75 MB; `GET /fixtures/odds` full 2.96 MB; `/fixtures/odds/main?tournamentId=17` 5.12 MB |

⇒ **Streaming JSON parsing is mandatory** for `/fixtures/odds/historical` and `/fixtures/odds/main`; never `json.loads()` the whole body for history.

## 1.6 Error formats

Two shapes exist; **parse both**.

### A. Concrete API error (`Error` schema)
```
error   (required) integer  — HTTP status code (mirrors the real HTTP status)
message (required) string   — human-readable
code               string   — machine code  ← LIVE responses use `code`
reason             string   — machine code  ← openapi.json declares `reason`
details            any      — extra detail (array/object/string)
+ additionalProperties: true
```
- **[LIVE]** every error body observed used **`code`** (never `reason`). Implement `code = body.get("code") or body.get("reason")`.
- **[LIVE]** additional, undocumented context fields appear per error class:

| Error class | Extra fields observed |
|---|---|
| `bookmaker_not_allowed` (403) | `bookmaker` (the offending slug) |
| `channel_not_allowed` (403) | `requestedChannels: ["futures/odds"]`, `allowedChannels: [34 strings, item0 "bookmakers"]` |
| `sport_not_allowed` (403) | `denied: [69]` |
| bookmakers-too-many (400) | `hint: "Only 5 bookmakers allowed"` |
| 422 | `details: [{type, loc, msg, input}]` (note **`input`**, not in the doc'd `ValidationError`) |

### B. FastAPI validation wrapper (openapi 422 response)
```json
{"detail":[{"loc":["query","fixtureId"],"msg":"Field required","type":"missing"}]}
```
errors.md instead shows the flattened form `{"error":422,"message":"Validation error","code":"validation_error","details":[…]}`. **[LIVE]** the flattened form with `details[].input` was returned. Handle `details` **and** `detail`.

### Catalogue of codes (doc + live)

| HTTP | code | message | When | Seen live |
|---|---|---|---|---|
| 400 | `invalid_filters` | "Invalid filters." | wrong/missing lookup-mode combination | ✔ `/fixtures`, `/fixtures/today`, `/fixtures/live`, `/markets`, `/fixtures/odds/main`, `/fixtures/mapping`, `/futures/mapping` |
| 400 | *(bookmaker count)* | — + `hint:"Only 5 bookmakers allowed"` | >5 slugs in `bookmakers=` | ✔ |
| 400 | `missing_bookmaker` | — | `/fixtures/odds/historical` without `bookmaker` and without `oddsIds` | ✔ |
| 401 | `missing_api_key` | "missing apiKey" | no key | ✔ (`err_nokey`) |
| 401 | `invalid_api_key` | "invalid apiKey" | bad key | ✔ (`err_badkey`) |
| 403 | `channel_not_allowed` | "Access denied: apiKey is not allowed to access this endpoint." | endpoint/feature not entitled | ✔ futures/odds* |
| 403 | `bookmaker_not_allowed` | — | slug not entitled (incl. data-provider slugs) | ✔ `opticodds`, `betradar`, `flashscore` |
| 403 | `sport_not_allowed` | — + `denied:[…]` | sportId not entitled | ✔ `sportIds=69` |
| 404 | *(unspecified)* | — | declared on fixtures*, fixtures/odds*, mapping, settlement, futures, media | not observed |
| 422 | `validation_error` | "Validation error" | FastAPI validation | ✔ `/futures/settlement` (server bug, see §9) |
| 429 | `rate_limited` | "rate limit exceeded" | + `limit`,`windowSec`,`retryAfterSec`,`endpoint`,`method` | see burst sample |
| 501 | `not_implemented` | "Futures settlement is not available yet." | `/futures/settlement` per docs | **not reproduced** — live returns 422 |
| 503 | `rate_limiter_error` | "rate limiter unavailable" | limiter backend down | not observed |

**Silent-empty vs error:** entitlement gaps are inconsistent — `sportIds=69` on `/sports` gives **403**, but `sportId=69` on `/futures` gives **`[]` with HTTP 200**. Never infer "no data" from an empty array without checking entitlement. [LIVE]

---

# 2. Complete endpoint catalogue

All endpoints are **GET**, all under `/{lang}` (use `/en`), all authenticated with `?apiKey=`. All responses `application/json` except media (302/binary). Every schema has `additionalProperties: true` → tolerate unknown keys.

## 2.1 Common / metadata (tag `common`) — 200 req/min each

| # | Path | Purpose | Params (type, required) | Lookup rule | Live status |
|---|---|---|---|---|---|
| 1 | `/bookmakers` | Bookmaker catalogue **available to the key** = entitlement discovery | `bookmakers` string (comma/space list; `*`/`all` wildcard [DOC]); `playerProps` boolean | both optional | **200**, list[31]. `playerProps=true` → list[19]. `bookmakers=pinnacle,opticodds,188bet` → list[**1**] (only `pinnacle`; unknown/unentitled slugs silently dropped) |
| 2 | `/sports` | Sport list | `sportIds` string list | optional | **200** list[6] (10–15). `sportIds=10,69` → **403 `sport_not_allowed`, denied:[69]** |
| 3 | `/tournaments` | Tournaments | `sportId` int; `tournamentIds` string list | `sportId` **OR** `tournamentIds`; **if neither → defaults to `sportId=11`** [DOC] | **200**: s10→1772, s11→577, s12→**9714** (1.75 MB), s13→85, s14→29, s15→364. `tournamentIds=17,132,800042`→200 list[3] |
| 4 | `/seasons` | Seasons | `seasonIds` string list; `tournamentId` int | one of | **200**: t132→80, t17→33; `seasonIds=131631,130281`→2 |
| 5 | `/participants` | Teams / competitors | `participantIds` string list; `sportId` int; `playerId` int (reverse: player→team) | one of | **200**: sport11→**5882**; `participantIds=43,7,3421`→3 (cross-sport OK) |
| 6 | `/players` | Players (for props) | `playerIds` string list; `participantId` int; `sportId` int | one of | **200**: sport11→**13243**; `participantId=3421`→42 |
| 7 | `/venues` | Venues by id | `venueIds` string list **REQUIRED** | ids only (no listing) | **200** `venueIds=6054,12720`→2; no param → **400** |
| 8 | `/markets` | **Canonical market/outcome catalogue** | `marketIds` string list; `sportId` int; `outcomeIds` string list | exactly one **required** | **200**: sport11→**4902** markets (1.50 MB), sport10→**1122**; `marketIds=101,1010,111`→3; `outcomeIds=102,1011`→2; **no param → 400** |
| 9 | `/currencies` | FX table | `currency` string (case-insensitive) | optional | **200** list[**143**]; `currency=EUR`→1 |

## 2.2 Fixtures (tag `fixtures`) — 200 req/min each

| # | Path | Purpose | Params | Lookup rule (doc) | Live status |
|---|---|---|---|---|---|
| 10 | `/fixtures` | Fixture metadata | `fixtureIds` string list (fast path); `sportId` int; `tournamentId` int; `bookmakers` string list (*"If present (even empty), includes bookmaker META and filters by mapping"*); `startTimeFrom` int **epoch s**; `startTimeTo` int **epoch s** | `fixtureIds` OR filters. Description mentions `statusId` — **no such parameter is declared** | **200** with `tournamentId` / `sportId+range` / `fixtureIds`; **400 `invalid_filters`** with no params. `bookmakers` map came back `{}` even when requesting fixtures |
| 11 | `/fixtures/today` | Today's fixtures | `sportId` int; `tournamentId` int; `bookmakers` list | doc: **all optional** | **[LIVE≠DOC] 400 `invalid_filters`** with no params ("sportId or tournamentId required"). Works per sport: s10→330, s11→23, s12→400, s13→82, s14→53. `bookmakers` with 6 slugs → 400 + hint |
| 12 | `/fixtures/live` | Live fixtures (statusId 1) | `sportId`, `tournamentId`, `bookmakers` | doc: all optional | **[LIVE≠DOC] 400** with no params. s12→14 live tennis at 07:29Z; s10/s11/s13→`[]` |

**Day boundary of `/fixtures/today`: [UNKNOWN]** — no timezone documented; at 07:20 UTC it returned large lists for all sports, so it is not "next 24 h from now" in an obvious way. Prefer `/fixtures?startTimeFrom&startTimeTo` for deterministic windows.

## 2.3 Fixture odds (tag `fixtures/odds`)

| # | Path | Purpose | Params | Rate | Live status |
|---|---|---|---|---|---|
| 13 | `/fixtures/odds` | **All current odds for ONE fixture** (all markets, all books) | `fixtureId` string **REQUIRED**; `bookmakers` list (≤5); `since` int **epoch ms** (`changedAt >= since`); `marketActive` bool; `mainLine` bool | **10/s** | **200**. Live soccer fixture `id1000001772221240`: 27 books, **7494** quote entries incl. **2835 player props**, 2.96 MB, 405 ms. `mainLine=true` → 800 entries / 343 KB. `bookmakers=pinnacle,betfair-ex,polymarket` → 293/159/150 entries, 337 KB. `since=<now-10min>` → 345 entries / 238 KB. **Finished fixtures return `odds:{}`** |
| 14 | `/fixtures/odds/main` | **Main-line odds for MANY fixtures** | exactly one of `tournamentId` int (recommended) / `fixtureIds` string list; `bookmakers` list; `since` int ms (*"If provided, returns also inactive odds"*) | **10/s** | **200**: `tournamentId=17` → 30 fixtures, **11 678** main-line entries, 27 books, **5.12 MB**, 1.02 s. `tournamentId=109` → **100** fixtures, 2.36 MB (cap?). `fixtureIds=<50 MLB ids>` → 50 fixtures, 2.10 MB. `+bookmakers=pinnacle` → 175 entries / 218 KB. `+since` → 944 KB. No params → **400** |
| 15 | `/fixtures/odds/clv` | OLV/CLV pair per oddsId | `fixtureId` **REQUIRED**; `bookmakers` list; `oddsIds` string list | 200/min | **200**. Pregame fixture → **`olv` populated, `clv: null`**. Finished MLB `id1300010963302451` → 24 books / **11 149** oddsIds / 4.14 MB, `clv` null for ~17 %. Finished NBA `id1100013270504978` → 12 750 oddsIds, 4.24 MB, 5000 null `clv`. Filters `bookmakers`+`oddsIds` combine. `fixtureId=None` → `{"fixtureId":…,"odds":{},"bookmakers":{}}` (46 B, HTTP 200) |
| 16 | `/fixtures/odds/historical` | Full price change log | `fixtureId` **REQUIRED**; `bookmaker` string **singular** (*exactly ONE* if `oddsIds` absent); `oddsIds` string list | 200/min | **200**. `bookmaker=pinnacle` on finished MLB → 397 series / **25 068** ticks / 6.04 MB; `bookmaker=draftkings` same fixture → 1546 series / **433 296** ticks / **95.6 MB** / 4.4 s. `oddsIds` spanning 3 books works (1.31 MB). `bookmaker`+`oddsIds` = **intersection**. Missing both → **400 `missing_bookmaker`**. `bookmaker=opticodds` → **403 `bookmaker_not_allowed`** |

## 2.4 Futures (tags `futures`, `futures/odds`)

| # | Path | Purpose | Params | Rate | Live status |
|---|---|---|---|---|---|
| 17 | `/futures` | Future/outright metadata | `futureIds` list; `sportId` int; `tournamentId` int; `startTimeFrom`/`startTimeTo` int epoch s (inclusive); `bookmakers` list | 200/min | **200**: sport10→**719**, sport11→**252**; sport69/76→`[]`; `tournamentId=17`→`[]`; `tournamentId=132`→`[]`; `sportId=10&bookmakers=…`→`[]`. `bookmakers` map always `{}` |
| 18 | `/futures/live` | Live futures | `sportId`, `tournamentId`, `bookmakers` | 200/min | **200**: sport10→**361**, sport11→28, sport69→`[]` |
| 19 | `/futures/odds` | Latest futures prices | `futureId` **REQUIRED**; `bookmakers`; `since` ms; `mainLines` bool (default false); `includeFuture` bool (default false) | **10/s** | **403 `channel_not_allowed`** (`requestedChannels:["futures/odds"]`) — **NOT ENTITLED** |
| 20 | `/futures/odds/clv` | Futures OLV/CLV | `futureId` **REQUIRED**; `bookmakers`; `oddsIds` | 200/min | **403 `channel_not_allowed`** |
| 21 | `/futures/odds/historical` | Futures price log | `futureId` **REQUIRED**; `bookmakers` (**plural name, exactly ONE slug**); `oddsIds` | 200/min | **403 `channel_not_allowed`** |

## 2.5 Mapping (tag `mapping`) — 200 req/min

| # | Path | Purpose | Params | Live status |
|---|---|---|---|---|
| 22 | `/fixtures/mapping` | OddsPapi `fixtureId` ⇄ bookmaker-native event id | `bookmaker` string (**singular**, optional per doc); `fixtureIds` list; `bookmakerFixtureIds` list | **200** for entitled slugs; **400** if neither id list given; **403 `bookmaker_not_allowed`** for `opticodds`/`betradar`/`flashscore`. Real results for `fixtureIds=id1000001772221240`: `pinnacle` → `1634530286`; `draftkings` → `34572328`; `betfair-ex` → `35974451`; `polymarket` → `893106`; `kalshi` → `KXEPLGAME-26SEP05FULCRY` |
| 23 | `/futures/mapping` | `futureId` ⇄ bookmaker-native outright id | `bookmaker` **REQUIRED**; `futureIds` list; `bookmakerFutureIds` list | **200** but `bookmakerFutureId: null` for `pinnacle` + `futureIds=id110168821099751`; **400** if no id list |

## 2.6 Settlement (tag `settlement`) — 200 req/min

| # | Path | Purpose | Params | Live status |
|---|---|---|---|---|
| 24 | `/fixtures/settlement` | Provider-graded per-outcome results | `fixtureId` **REQUIRED**; `outcomeId` int; `playerId` int | **200**, but **slow: 4.2 s / 5.0 s / 8.6 s** observed. Finished MLB → **1652** rows (WIN/LOSE/PUSH/UNDECIDED); EPL 1 y ago → **2224** rows incl. **HALFWIN/HALFLOSS**; NBA → **10 131** rows / 1.66 MB. **Pregame fixture returns full row set with `status:"UNDECIDED"` and `reason:"MISSING_PERIODS"`.** `fixtureId=None` → `{"fixtureId":…,"settlements":[]}` |
| 25 | `/futures/settlement` | Futures grading | `futureId` **REQUIRED** | **[LIVE≠DOC]** doc says **501 `not_implemented`**; live returns **422** validation error whose `details` reference `args`/`kwargs` → **server-side bug**. Either way: unusable |

## 2.7 Media (tag `media`) — 200 req/min

| # | Path | Purpose | Param | Content | Live status |
|---|---|---|---|---|---|
| 26 | `/media/bookmakers/{slug}` | Bookmaker logo | `slug` (e.g. `pinnacle`) | 302 → asset; 200 `image/webp` | **200, 0 bytes** (redirect body empty; `Location` not captured) |
| 27 | `/media/categories/{category}` | Country/region flag | `category` (`de`,`usa`,`fr`) | 302 → `https://ASSET_HOST/categories/de.svg`; 200 `image/svg+xml` | **`{"error":…,"message":…}` 35 B** for `usa` |
| 28 | `/media/tournaments/{tournamentId}` | Tournament image | path string | 302; 200 `image/png` | **200, 0 bytes** |
| 29 | `/media/participants/{participantId}` | Team image | path string | 302; 200 `image/png` | **200, 0 bytes** |

Media is irrelevant to trading; if used, cache the redirect target, never hit the API per render. "Proxy mode" is mentioned in docs but undocumented. [UNKNOWN]

## 2.8 WebSocket (see §4 for full protocol)

| # | Endpoint | Purpose | Live status |
|---|---|---|---|
| 30 | `wss://v5.oddspapi.io/ws` | Realtime gateway; `login` frame defines channels+filters | **Works.** 12 channels entitled; `json`, `binary` (MessagePack), `zstd`, `zstd-dict` all negotiated successfully |

---

# 3. Data model & ID schemes

## 3.1 Hierarchy

```
Sport (sportId 10..81)
└── Tournament (tournamentId; belongs to exactly one sport)
    └── Season (seasonId; belongs to exactly one tournament)
        ├── Fixture  (single match)      → participants, per-period scores, clock, players
        └── Future   (outright / prediction market)
```
Coverage rule of thumb [DOC]: `sportId` **10–68** = fixtures **and** futures; **69–78** = prediction-market topics, **futures only**; **79–81** = racing, ante-post futures only. Our key: **10–15 only**.

Full documented sportId table (for reference; we are entitled to 10–15 only): 10 Soccer, 11 Basketball, 12 Tennis, 13 Baseball, 14 American Football, 15 Ice Hockey, 16 ESport Dota, 17 ESport CS, 18 ESport LoL, 19 Darts, 20 MMA, 21 Boxing, 22 Handball, 23 Volleyball, 24 Snooker, 25 Table Tennis, 26 Rugby, 27 Cricket, 28 Waterpolo, 29 Futsal, 30 Beach Volley, 31 Aussie Rules, 32 Field hockey, 33 Floorball, 34 Squash, 35 Basketball 3x3, 36 Beach Soccer, 37 Pesapallo, 38 Lacrosse, 39 Curling, 40 Padel, 41 Bandy, 42 Kabaddi, 43 Rink Hockey, 44 Soccer Specials, 45 Gaelic Football, 46 Netball, 47 Beach Handball, 48 Athletics, 49 Badminton, 50 Bowls, 51 Cross-Country, 52 Gaelic Hurling, 53 Softball, 54 eSoccer, 55 eBasketball, 56 ESport CoD, 57 ESport Overwatch, 58 ESport R6, 59 ESport Rocket League, 60 ESport SC, 61 ESport Valorant, 62 ESport AoV, 63 ESport KoG, 64 Judo, 65 ESport HoK, 66 Speedway, 67 Golf, 68 Cycling, 69 Politics, 70 Elections, 71 Economics, 72 Finance, 73 Technology, 74 Health, 75 Science, 76 Cryptocurrency, 77 Weather, 78 Culture, 79 Horse Racing, 80 Greyhound Racing, 81 Harness Racing.

## 3.2 ID formats (with real examples)

| Id | Type | Format | Real examples | Parse? |
|---|---|---|---|---|
| `sportId` | int | 2 digits, 10–81. **Also the first two digits of `marketId`, `outcomeId` and (after the provider slug) `fixtureId`** | 10, 11, 13, 14 | yes |
| `tournamentId` | int | variable; **zero-padded to 6 digits inside fixture/future ids** | 17 EPL, 31 NFL, 109 MLB, 132 NBA, 234 NHL, 242 MLS, 486 WNBA, 2591 US Open MS, 703 Primera Nacional, 800370 "2025 Predictions" | yes |
| `seasonId` | int | 6 digits for sports; **10 digits for prediction markets** | 131631 (NBA 25/26), 130281 (EPL 25/26), 119257 (NBA 24/25), 138218, 8815837922, 8847293156 | yes |
| `fixtureId` | **string** | `{providerSlug}{sportId}{tournamentId:06d}{nativeId}` | `id1100013270505056`, `id1400003160574219`, `id1000001770366972`, `id1000001772221240` (EPL live), `id1300010963302451` (MLB), `id1100013270504978` (NBA), `id1000070367118324` | **Treat as OPAQUE.** Docs: *"structured but should be treated as opaque in your logic."* Native suffix == `betradarId` in most examples but **not always** (NFL `id1400003160574217` has `betradarId 67432516` ≠ `60574217`) |
| `futureId` | **string** | `{providerSlug}{sportId}{tournamentId:06d}{seasonId}{marketId}` | `id100000171302811`, `pm6980037088158379224`, `id11000132131631` (**lacks the trailing marketId digit — doc inconsistency**), `id110168821099751`, `id100000281190131` | **OPAQUE** (variable-length seasonId makes positional parsing ambiguous) |
| provider slug prefix | string | `id` (Betradar-keyed upstream), `pm` (Polymarket-sourced), `ks` (Kalshi-sourced) | — | informational only |
| `marketId` | int | `{sportId}{increment}`; **equal to the lowest `outcomeId` of the market**; **one marketId per (marketType, period, handicap)** | 111 (NBA moneyline), 113 (NBA 1x2 regular time), 141 (NFL 1x2), 101 (soccer 1x2), 1010 (soccer totals 2.5), 1068 (soccer AH -0.5), 10122 (Euro handicap 6.0), 131830 (MLB player prop) | yes |
| `outcomeId` | int | frozen, fully decomposed selection (marketType→period→handicap→side); first 2 digits = sportId | 111/112, 113/114/115, 141/142, 14198, 101/102/103, 1011, 10132, 10360, 131831 | yes |
| `playerId` | int | `0` = "no player" (reserved) | 607468 "Jokic, Nikola", 607336, 2757987 (MLB prop) | yes |
| `participantId` | int | teams/competitors | 3421 NYK, 3423 ATL, 3429 SAS, 3414 POR, 3409 CHI, 3410 MIL, 4423 MIN Vikings, 4419 DET Lions, 53799, 3214, 5432 (Polymarket selection) | yes |
| `venueId` | int | — | 6054 Madison Square Garden, 6112 Frost Bank Center, 12720, 1234 Camp Nou, 5678 State Farm Arena | yes |
| **fixture `oddsId`** | string | `{fixtureId}:{bookmaker}:{outcomeId}:{playerId}` — **exactly 4 colon-separated segments, no trailing colon** (verified against openapi.json; the markdown YAML's trailing `:` is a YAML artefact) | `id1100013270505136:pinnacle:111:0`, `id1400003160574219:bet365:14198:0`, `id1000001772221240:sx.bet:1011:0`, `id1002746472055140:betfair-ex:10132:0`, `id1300010963302991:caesars:131831:2757987` | **PRIMARY KEY** — split on `:` |
| **selection key** (book-independent) | string | `{fixtureId}:{outcomeId}:{playerId}` | `id1400003160574219:141:0` | grading / cross-book join |
| **future `oddsId`** | string | `{futureId}:{bookmaker}:{participantId}` — 3 segments | `pm6980037088158379224:polymarket:5432` | n/a (not entitled) |
| bookmaker slug | string | lowercase, may contain `.` and `-` | `pinnacle`, `betfair-ex`, `bovada.lv`, `sx.bet`, `bookmaker.eu`, `betonline.ag` | key everywhere |

**Line values are NOT in the oddsId.** Each handicap/total line is its own `marketId`; the line value lives in `Market.handicap` from `GET /markets`. To know "Over 2.5" vs "Over 3.5" you must join `outcomeId → marketId → handicap`. **The market catalogue is mandatory reference data.**

## 3.3 `Fixture` (exact fields)

Required: `fixtureId, status, sport, tournament, season, venue, startTime, participants, scores, clock, externalProviders`. `additionalProperties: true`. Live responses contained exactly: `fixtureId, status, sport, tournament, season, venue, startTime, trueStartTime, trueEndTime, participants, scores, clock, expectedPeriods, periodLength, externalProviders, bookmakers` (16 keys).

| Field | Type | Notes / verbatim doc |
|---|---|---|
| `fixtureId` | string | see §3.2 |
| `status.live` | bool (req) | *"Convenience flag — true only while in play (`statusId` 1)"* |
| `status.statusId` | int (req) | *"`0` pregame, `1` live, `2` finished, `3` cancelled. Moves forward only — always branch on this ID."* |
| `status.statusName` | string (req) | translated: "Pre-Game", "Live", "Finished", "Postponed" (seen) — **never branch on it** |
| `sport.sportId` / `sport.sportName` | int / string (both req) | |
| `tournament.tournamentId` / `tournamentName` (req) / `categoryName` | int / string / string\|null | `categoryName` = country/region |
| `season.seasonId` / `seasonName` / `seasonRound` | int\|null / string\|null / int\|null | **all nullable** — NFL examples have `seasonId: null` |
| `venue.venueId` / `venueName` / `venueLocation` | int\|null / string\|null / string\|null | translated |
| `startTime` | int (req) | **epoch SECONDS (UTC)**; scheduled |
| `trueStartTime` | string\|null | *"Actual start time (ISO 8601), once known — may differ from the scheduled `startTime`"* e.g. `2026-04-21T00:09:08+00:00` |
| `trueEndTime` | string\|null | actual end, ISO 8601 e.g. `2025-12-25T21:09:09.345372+00:00` |
| `participants.participant1Id` | int (req) | **home / first-listed side** |
| `participants.participant1RotNr` | int\|null | US rotation number |
| `participants.participant1Name` / `1ShortName` / `1Abbr` | string\|null | e.g. "New York Knicks" / "New York" / "NYK" |
| `participants.participant2*` | same | **away / second-listed side** |
| `scores` | object (req) keyed by period | `{period: string, participant1Score: int, participant2Score: int, updatedAt: ISO µs}` (all required). `{}` when no scores |
| `clock` | object\|null | `{currentPeriod, currentTime "mm:ss", remainingTime "mm:ss", remainingTimeInPeriod, stopped bool}` — **all keys present with null values until populated**; often all-null even in play |
| `expectedPeriods` | int\|null | NBA 4, NFL 4, soccer 2 |
| `periodLength` | int\|null | minutes: NBA 12, NFL 15, soccer 45 |
| `externalProviders` | object (req), free-form | see §6 |
| `bookmakers` | object keyed by slug | `BookmakerFixtureMeta`; *"Contains only bookmakers that currently offer valid realtime odds for this fixture. Present on fixture and odds endpoints; omitted on CLV, historical-odds and settlement responses."* **[LIVE] was `{}` on every `/fixtures*` call** (populated on `/fixtures/odds*`) |

## 3.4 `BookmakerFixtureMeta`

Required: `bookmaker, hasOdds, staleOdds, suspended, participantsRotated, updatedAt`.

| Field | Type | Verbatim |
|---|---|---|
| `bookmaker` | string | slug |
| `bookmakerFixtureId` | string\|null | *"Native fixture identifier at the bookmaker."* e.g. pinnacle `"1628488896"`, stake `"46173997-xx-yy"`, draftkings `"33999242"` |
| `fixturePath` | string\|null | *"Path of the fixture page…"* — actually a **full URL**: `https://www.pinnacle.com/en/e/e/e/1628488896/#all`, `https://sportsbook.draftkings.com/event/33999242` |
| `hasOdds` | bool | *"True if the bookmaker currently publishes odds for this fixture."* |
| `staleOdds` | bool | **"Critical for trading: true if the connection to this bookmaker was lost or interrupted, so odds freshness can no longer be guaranteed."** |
| `staleOddsResponseCode` | int\|null | **DEPRECATED** — *"Rely on `staleOdds` instead."* |
| `suspended` | bool | *"True while the bookmaker has suspended betting on this fixture."* |
| `participantsRotated` | bool | *"True if the bookmaker lists the participants in the opposite order (participant 1/2 swapped) relative to OddsPapi."* |
| `meta` | object\|null | bookmaker-specific |
| `updatedAt` | string | ISO µs, when this meta last changed |

Gotcha: `hasOdds:false` entries **do** appear despite the "only books with valid realtime odds" wording (stake example, `odds:{}`). Trust the flags, not the presence.

## 3.5 `OddQuote` (fixture odds row) — exact fields

Map location: `odds[<bookmakerSlug>][<oddsId>]`. Required: `bookmaker, outcomeId, playerId, price, active, changedAt`.

| Field | Type | Verbatim / notes |
|---|---|---|
| `bookmaker` | string | slug |
| `outcomeId` | int | *"Frozen outcome identifier of the selection."* |
| `playerId` | int | *"Player the price refers to; `0` for non-player markets."* |
| `price` | number | **decimal odds** |
| `active` | bool | *"Whether this outcome is currently available at the bookmaker."* |
| `marketActive` | bool\|null | *"Whether the entire market is active at the bookmaker."* |
| `mainLine` | bool\|null | *"Whether this is the bookmaker's main line for the market type."* |
| `marketId` | int | *"Frozen market identifier the outcome belongs to."* |
| `bookmakerMarketId` | string\|null | native market id — Pinnacle `"line/4/487/1628488896/3565645414/0/moneyline"` (= `line/{sport}/{league}/{eventId}/{lineId}/{period}/{type}`), Polymarket `"1011497"` |
| `bookmakerOutcomeId` | string\|null | native selection id — `"home"`, `"away"`, Polymarket token id `"4937…"` |
| `bookmakerChangedAt` | int\|null (`"int"` in schema) | *"Bookmaker-provided change timestamp (epoch ms), when present."* |
| `priceFractional` | string\|null | `"11/71"`, `"5/2"`; **`""` (empty string) seen as placeholder in CLV rows** |
| `priceAmerican` | int\|null | `-645`, `477`, `-230`; **`0` seen as placeholder in CLV rows** |
| `meta` | any (`"json"` in schema) | *"Bookmaker-specific metadata (orderbooks, ladders, …)."* → §3.6 |
| `limit` | number\|null | *"Maximum accepted stake, when provided by the bookmaker."* Pinnacle 19354 / 3000 / 4594; Polymarket 4.71 |
| `betslip` | string\|null | *"Bookmaker betslip / deeplink token, when available."* |
| `changedAt` | int (req) | *"Gateway change timestamp (epoch ms, UTC) — always present; when the gateway accepted this update."* |

**Fields can be entirely ABSENT, not merely null** (Polymarket rows lacked `mainLine`, `priceFractional`, `bookmakerChangedAt`; live `caesars` row had only `outcomeId, playerId, price, active, changedAt, bookmaker, priceAmerican, marketId, bookmakerChangedAt, meta`). Parse leniently with `.get()`.

## 3.6 `meta` — order-book depth (bookmaker-specific, undocumented shapes) **[LIVE — high value]**

The docs only say *"orderbooks, ladders"*. The probe captured three distinct shapes:

| Bookmaker | `meta` shape (observed) | Example |
|---|---|---|
| `polymarket` | `{"lay":[{price,limit,cents,size},…], "back":[{price,limit,cents,size},…]}` | `lay:[{price:1.042, limit:144.0, cents:0.96, size:150.0},{price:1.041, limit:96.1, cents:…}]`; `back:[{price:1.02, limit:89.93, cents:0.98, size:91.77},{price:1.01, limit:527.12,…}]` |
| `betfair-ex` | `{"availableToBack":[{price,size},…]}` (presumably `availableToLay` symmetric) | `availableToBack:[{price:12.5,size:20.21},{price:11,size:5.12},{price:10.5,size:24.94}]` |
| `sx.bet` | `{"back":[{price,limit,cents},…]}` (no `size`) | `back:[{price:1.99, limit:286.299, cents:0.5025},{price:1.985, limit:220.981, cents:0.5038}]` |

**Derived semantics (arithmetic verified on 4 independent rows):**
- `cents` = **implied probability** = `1 / price` (1.02→0.98, 1.99→0.5025, 2.5→0.4, 1.042→0.96).
- `size` = **shares/contracts**; `limit` = **USD notional** = `size × cents` (2029×0.4 = 811.6 ✓; 150×0.96 = 144 ✓; 91.77×0.98 = 89.93 ✓; 5.0×0.98 = 4.9 ✓).
- ⇒ For prediction markets, `limit` is the **cash you can stake at that rung**; ladder depth is 2–3+ rungs deep.
- **Store `meta` verbatim as JSON**; normalize per-bookmaker with a small adapter registry keyed by slug. Ladder key names are *not* stable across books — never assume `back`/`lay`.

## 3.7 `PricePoint` / `ClvPair`

`odds[slug][oddsId] = {olv: PricePoint, clv: PricePoint}`; `olv`/`clv` required by schema, but **[LIVE] `clv` can be `null`** (pregame always; ~17–39 % of oddsIds on finished fixtures). `PricePoint` has the identical field set to `OddQuote`; `changedAt` = *"Gateway timestamp of this price point (epoch ms, UTC)"*.

- `olv` = *"Opening line value — the earliest recorded price point for the outcome."*
- `clv` = *"Closing line value — the last recorded price point before the fixture started."* ⇒ **the last CHANGE ≤ start, not a snapshot at start.** If a book pulled the line early, CLV is stale — always check `active` on the `clv` point.

## 3.8 `HistoricalOddsByBookmaker`

`odds[slug][oddsId][<changedAt-epoch-ms as STRING>] = OddQuote`. JSON object key order is **not** guaranteed → sort by `int(key)` client-side. Ticks are emitted on **any** update (price, `active`, `marketActive` toggles, re-confirmations) — two adjacent points with identical `price` are normal.

## 3.9 `SettlementItem`

`settlements: SettlementItem[]` under `FixtureSettlementResponse` (= Fixture + settlements; `bookmakers` map omitted). All fields nullable, none required.

| Field | Type | Notes |
|---|---|---|
| `marketId` | int\|null | frozen market graded |
| `marketType` | string\|null | e.g. `"1x2"` |
| `outcomeId` | int\|null | frozen outcome graded |
| `playerId` | int\|null | `0` for non-player |
| `status` | string\|null | **`WIN`, `LOSE`, `PUSH`, `HALFWIN`, `HALFLOSS`, `CANCELLED`, `UNDECIDED`** |
| `margin` | number\|null | serialized as float (`7.0`, `-7.0`); **signed from the graded outcome's perspective** |
| `team1Score` / `team2Score` | int\|null | final scores used for grading |
| `periods` | string[]\|null | period keys used, e.g. `["fulltime"]` |
| `reason` | string\|null | present on `CANCELLED`/`UNDECIDED` — **[LIVE] values seen: `MISSING_PERIODS` (pregame/not-yet-final), `REQUIRES_NON_SCORE_STATS` (corners/bookings markets)** |

Settlement is **bookmaker-independent** (OddsPapi's own grading against frozen outcome ids) → usable as ground truth for P&L across all books.

## 3.10 Futures entities (metadata only for us)

`FutureMeta` required: `futureId, status, sport, tournament, season, startTime, endTime, market, participants, externalProviders, bookmakers`.
- `startTime`/`endTime` = epoch **seconds**; *"Start/End of the betting window"*.
- `market` = `{marketId int|null, marketName string|null, marketType string|null}`. Documented future marketIds: **1 Winner, 2 Top Scorer, 3 Relegation, 4 Prediction ("Will X happen by date Y?"), 5 MVP**. `marketName`/`marketType`/`playerMarket`/`participantMarket` remain null per changelog 2026-04-09.
- `participants` = `[{participantId int (req), participantName string|null}]`; `[]` for yes/no prediction questions.
- **For prediction markets the question text lives in `season.seasonName`** (e.g. `"Macron out by...?"`).
- `bookmakers[slug]` = `BookmakerFutureMeta {bookmaker (req), bookmakerFutureId string|null, participantsRotated (req)}` — **no `hasOdds`/`staleOdds`/`suspended`/`updatedAt`** unlike fixtures. **[LIVE] always `{}`**.
- `FutureOddsRow` (not entitled, documented): required `oddsId, bookmaker`; plus `participantId, price, active, bookmakerOutcomeId, bookmakerChangedAt, priceFractional, priceAmerican, meta, limit, betslip, changedAt`. **No `outcomeId`/`marketId`/`marketActive`/`mainLine`.** Response shape is an **array** under `bookmakers[slug].odds[]`, unlike fixtures' map.

## 3.11 Reference/metadata entities

| Entity | Fields (live) |
|---|---|
| `Bookmaker` | **[LIVE key set, 18 fields]** `slug, bookmakerName, active, domain, websocketPregame, websocketLive, maxDelayPregameInSec, maxDelayLiveInSec, maxDelayPregameMainInSec, availableCountries, serverGroup (deprecated), price (deprecated), staleThresholdSec ★, availableSports ★, lastOddsAt ★, playerProps, staleOddsSince ★, limitCurrency ★` — ★ = **undocumented in openapi.json, present live**. `pinnacle` has `limitCurrency: "USD"`. Doc examples: `188bet` pregame 80 s / main 60 s / `websocketLive:false`; `1xbet` pregame 30 s / live 4 s / main 6 s. Types of `staleThresholdSec` (number?), `lastOddsAt`/`staleOddsSince` (ISO vs epoch?) **[UNKNOWN — inspect raw sample before typing]** |
| `Sport` | `sportId (req), slug (req; "will be renamed sportSlug"), sportName (req)` |
| `Tournament` | `tournamentId (req), sportId (req), tournamentSlug, categorySlug, tournamentName (req), categoryName` — **[LIVE] some rows additionally carry `categoryCountryCode`** (sport 11 sample) → key sets vary row-to-row |
| `Season` | `seasonId (req), tournamentId (req), sportId, seasonSlug, seasonName (req)` |
| `Participant` | `participantId (req), sportId, name ("will be renamed participantName"), participantShortName, participantMediumName, participantAbbr` — **no external ids** |
| `Player` | `playerId (req), playerName` — format **"Last, First"** (`"Jokic, Nikola"`). No team/position/sport on the object |
| `Venue` | `venueId (req), venueSlug (req), venueName, venueLocation` |
| `Market` | `marketId (req), sportId, marketType, period, marketLength, playerProp, handicap, marketName, marketNameShort, outcomes[{outcomeId (req), outcomeName}]` |
| `Currency` | `currency (req, ISO 4217), updatedAt (req, ISO), currencyValue (req)` — **units of that currency per 1 USD** (EUR 0.848627; BTC 1.153e-05). USD base is *inferred*, not stated |

## 3.12 Enumerations (frozen; new values appended only)

**`statusId`** — `0 pregame` (live=false), `1 live` (live=true), `2 finished`, `3 cancelled`. *"Status only ever moves forward (`0 → 1 → 2`, or any state → `3`); it never goes backwards."*

**`settlementStatus`** — `WIN` (full payout), `LOSE`, `PUSH` (void/tie on line, stake returned), `HALFWIN` (Asian quarter lines), `HALFLOSS`, `CANCELLED` (market voided), `UNDECIDED` (cannot grade yet).

**Period keys** (open vocabulary; interpret with `expectedPeriods` + `periodLength`):
- Whole-match: `result` (headline score incl. everything played), `fulltime` (regulation only), `overtime` (OT segment), `penalties` (**currently cumulative score after pens — will change to segment-only in a future release**).
- Numbered: `p1` … `p12` (half/quarter/set/map/inning/round; `p10`–`p12` = boxing rounds).
- Combined: `p1+p2`, `p3+p4`, `p1+p2+p3+p4+p5`, `fulltime+overtime`, `p3+p4+overtime`, `p4+overtime`, `p6+p7+p8+p9+overtime`.
- Sub-period: `p1g1` … `p5g13` (tennis game Y in set X; `g13` = tiebreak), `currentgame` (live rolling pointer).
- **Never hard-code an exhaustive list.**

**Open taxonomies (not enums):** `marketType` (`1x2`, `totals`, `spreads`, `spreads-european`, `bothteamsscore`, `drawnobet`, `oddeven`, `teamtotals-team1`, `moneyline`, `players-shots`, `winningmargin`, `outrights`, …), `eventType` (`goal`, `card_yellow`, `corner_taken`, `substitution`, `var`, …), `statType` (`score`, `corners`, `cards`, `aces`, …).

## 3.13 Market/outcome decomposition (the normalization layer)

`marketType → period → handicap (line) → side (outcome)` **[+ optional player carried separately in `playerId`]** — all baked into `outcomeId`.
- **Each distinct line value is its own `marketId`** (`0.0` for lineless markets).
- **All outcomes of a market share one `marketId`; the first `outcomeId` == `marketId`.**
- `marketLength` = number of outcomes = complete probability space (implied probs sum ≈ 1 before margin removal).
- Doc recommendation: *"If you perform arbitrage or pricing logic, always group odds by `marketId`."*

Worked soccer map (sportId 10):

| marketId | marketName | marketType | period | handicap | outcomeIds | outcomeNames |
|---|---|---|---|---|---|---|
| 101 | Full Time Result | `1x2` | fulltime | 0.0 | 101/102/103 | 1/X/2 |
| 104 | Both Teams To Score | `bothteamsscore` | fulltime | 0.0 | 104/105 | Yes/No |
| 106 | Over Under Full Time | `totals` | fulltime | 0.5 | 106/107 | Over/Under |
| 1010 | Over Under Full Time | `totals` | fulltime | 2.5 | 1010/1011 | Over/Under |
| 1068 | Asian Handicap | `spreads` | fulltime | -0.5 | 1068/1069 | 1/2 |
| 10122 | European Handicap | `spreads-european` | fulltime | 6.0 | 10122/10123/10124 | 1/X/2 |
| 10208 | First Half Result | `1x2` | p1 | 0.0 | 10208/10209/10210 | 1/X/2 |
| 10214 | Draw No Bet | `drawnobet` | fulltime | 0.0 | 10214/10215 | 1/2 |
| 10222 | Odd Even Full Time | `oddeven` | fulltime | 0.0 | 10222/10223 | Odd/Even |
| 10224 | Over Under Team 1 | `teamtotals-team1` | fulltime | 0.5 | 10224/10225 | Over/Under |

Basketball: `111` `moneyline`/`result` "Winner (incl. overtime)" → 111 "1", 112 "2"; `113` `1x2`/`fulltime` "Regular Time Result" → 113/114/115. NFL: `141` `1x2` → 141/142; `14198` seen in CLV. `handicap` sign is relative to participant 1 for spreads; totals use the line directly.

## 3.14 Timestamps & clock semantics

| Unit | Fields |
|---|---|
| **Epoch SECONDS (UTC)** | `startTime`, `endTime`, `startTimeFrom`, `startTimeTo`, `X-RateLimit-Reset` |
| **Epoch MILLISECONDS (UTC)** | `changedAt`, `bookmakerChangedAt`, `since` (all odds endpoints), historical map keys (as **strings**), WS envelope `ts`, the ts part of WS `entryId` |
| **ISO-8601 with offset** (often microseconds) | `trueStartTime`, `trueEndTime`, `scores.*.updatedAt` (`2026-04-21T00:59:42.287458+00:00`), `bookmakers.*.updatedAt`, `Currency.updatedAt`, `Bookmaker.lastOddsAt`? (unverified) |

Doc rule of thumb: *"schedule times are seconds, odds-update times are milliseconds."*

**Clock:** `clock` is an object whose keys are always present, values null until populated; **it is frequently all-null even for live fixtures** → determine liveness from `status.statusId == 1`, never from `clock`. `currentTime`/`remainingTime` are `"mm:ss"` strings (count-up vs count-down sport dependent); `stopped` bool.

---

# 4. Streaming (WebSocket gateway)

## 4.1 Protocol summary (AsyncAPI `info.description`, verbatim)

```
Flow:
1) Connect
2) First message MUST be {"type":"login","apiKey":"..."}
3) Server replies with {"type":"login_ok", ...} (or {"type":"error", ...})
4) Server streams UPDATE envelopes

Resume:
- Client may send serverEpoch + lastSeenId during login
- Server may send snapshot_required if replay is not possible

receiveType:
- json (default): server sends JSON text frames
- binary: server may send MessagePack for UPDATE frames (control frames may still be JSON)
- zstd: dictless zstd-compressed JSON data frames (dictId 0); control frames stay JSON
- zstd-dict: zstd with trained per-channel dictionaries pushed at connect as 'dict' control frames

Limits:
- Maximum 5 concurrent connections per apiKey.
```

**Universal framing rule: "Text frame → control (JSON). Binary frame → data."**
**Subscription model: login-only.** There is no subscribe/unsubscribe message. *"To change filters or channels, reconnect with a new `login`."* Every filter change costs one of the 5 connections.

## 4.2 `login` (client → server)

| Field | Type | Req | Default | Notes |
|---|---|---|---|---|
| `type` | const `"login"` | ✔ | — | |
| `apiKey` | string `^[0-9a-fA-F]{32}$` | ✔ | — | |
| `clientName` | string | | — | debug/metrics tag; echoed (live: `"reid"`) |
| `lang` | string | | — | translations (`en`,`de`,…) |
| `receiveType` | `json`\|`binary`\|`zstd`\|`zstd-dict` | | `json` | data-frame encoding |
| `channels` | ChannelName[] | | — | omit ⇒ **[LIVE] all 12 entitled channels are subscribed** (resolves open question) |
| `sportIds` | int[] | | — | restrict sports |
| `tournamentIds` | int[] | | — | restrict tournaments |
| `fixtureIds` | string[] | | — | exact fixtures (fixture-scoped channels only) |
| `futureIds` | string[] | | — | exact futures |
| `bookmakers` | string[] | | — | bookmaker-gated channels |
| `serverEpoch` | string (32 hex) | | — | for resume |
| `lastSeenId` | object `{channel: entryId}` | | — | per-channel cursor, e.g. `{"scores":"1766418736962-198"}` |
| `live` / `pregame` | bool | | — | **in AsyncAPI + examples but undocumented in prose**; entitlement comes from the key (`login_ok.access`). Semantics [UNKNOWN] — do not rely on them |
| `dicts` | — | | — | **REMOVED** 2026-05-25; ignored if sent |

Example (live-tested pattern):
```json
{"type":"login","apiKey":"***","clientName":"reid","lang":"en","receiveType":"zstd-dict",
 "channels":["odds","bookmakers"],"sportIds":[10,11,12,13,14,15],
 "bookmakers":["pinnacle","draftkings","fanduel","polymarket","kalshi"]}
```

**ChannelName enum (AsyncAPI):** `fixtures, futures, bookmakers, bookmakersFutures, odds, oddsFutures, scores, currencies, events, stats, injuries, lineups`. **`clocks` is missing from the enum** (added 2026-04-09, has a doc page, and was accepted live) → do not validate strictly.

**Channel scoping:**
- Fixture-scoped (payload has `fixtureId`): `fixtures`, `scores`, `odds`, `bookmakers`, `clocks`
- Future-scoped (payload has `futureId`): `futures`, `bookmakersFutures`, `oddsFutures`
- Global (filters ignored): `currencies`

**Bookmaker-gated channels:** `odds`, `bookmakers`, `oddsFutures`, `bookmakersFutures`. *"If the upstream message has no matching bookmaker keys, it's filtered out"* — the whole envelope is dropped.

## 4.3 `login_ok` (server → client) — live-observed shape

**[LIVE]** the real frame has an **undocumented `region` field**:
```json
{"type":"login_ok","region":"oddspapi-us1","connId":"9adc861e-46e8-434b-9161-379f4df1481b",
 "userId":"reid","clientName":"reid","lang":"en","receiveType":"json",
 "channels":["bookmakers","bookmakersFutures","clocks","currencies","events","fixtures",
             "futures","injuries","lineups","odds","scores","stats"],
 "sportIds":[10,11,12,13,14,15],"tournamentIds":null,
 "bookmakers":["188bet","198bet","3et","4casters","ballybet","bet365","betfair-ex","betmgm",
               "betonline.ag","betparx","betrivers","betus","bookmaker.eu","borgata","bovada.lv",
               "caesars", …],
 "fixtureIds":null,"futureIds":null,
 "access":{"live":true,"pregame":true},
 "resume":{"enabled":true, …}}
```
(`_t` and `_enc` keys visible in the capture are **probe-harness annotations**, not gateway fields.)

Schema fields (required: `type, connId, userId, channels, access, resume`):

| Field | Type | Notes |
|---|---|---|
| `region` | string | **[LIVE only]** `"oddspapi-us1"` — our key is served from a **US** region despite the docs' Central-Europe latency advice |
| `connId`, `userId` | string | log both for support tickets |
| `receiveType` | enum | **NEGOTIATED** — *"Always trust that echo to choose your decoder; never assume the mode you requested."* |
| `channels` | ChannelName[] | **effective** subscription |
| `sportIds`/`tournamentIds`/`fixtureIds`/`futureIds` | null \| array | `null` = no filter |
| `bookmakers` | string[] | effective (not nullable in schema) |
| `access` | `{live: bool, pregame: bool}` | *"determined by your `apiKey`, not client filters"* |
| `resume` | object | `enabled` bool, `serverEpoch` string, `resumeWindowMs` int, `replayChannels` ChannelName[], `serverCursors` {channel:int}, `serverEntryIds` {channel: string\|null} |

Doc `resume` example:
```json
{"resume":{"serverEpoch":"0804ab61513c4681a3afd8afc1fb2f75","resumeWindowMs":60000,
 "replayChannels":["fixtures","scores"],
 "serverEntryIds":{"fixtures":"1766414833582-2542","scores":"1766418736962-198"}}}
```
- `serverEpoch` *"identifies the current gateway session (changes on restart)"*.
- `resumeWindowMs` *"how long replayable data is buffered"* (doc example 60000).
- `replayChannels` = *"channels eligible for replay"* — **the doc example lists only `fixtures` and `scores` even though `odds` was requested** ⇒ **assume `odds` is NOT replayable** until proven otherwise. [UNKNOWN whether odds ever appears]
- `serverCursors` (int per channel) and `resume.enabled` are in AsyncAPI but never described. [UNKNOWN]

## 4.4 `UPDATE` envelope

| Field | Type | Notes |
|---|---|---|
| `channel` | ChannelName | |
| `type` | enum `["UPDATE"]` | *"currently always `UPDATE`"* |
| `payload` | object | channel-specific (§4.7) |
| `ts` | int | **epoch ms UTC** — gateway emit time |
| `entryId` | string | cursor, format `<ts_ms>-<seq>`; `seq` monotonic per channel |
| `v` | int\|null | AsyncAPI only, undocumented [UNKNOWN] |
| `seq` | `{p:int, o:int}`\|null | AsyncAPI only, undocumented (partition/offset?) [UNKNOWN] |

**[LIVE] real envelopes** (probe added `_recv_ms`, `_enc`, `_raw_len`):
```json
{"channel":"scores","type":"UPDATE",
 "payload":{"fixtureId":"id1200255972286208","scores":{"result":{"period":"result",
   "participant1Score":0,"participant2Score":1,"updatedAt":"2026-09-03T07:41:28.445213+00:00"}}},
 "ts":1788421288623,"entryId":"1788421288623-602821"}
```
Observed: `ts` == the ts part of `entryId`; `seq` counters are large and global-ish per channel (602821). **`entryId` gaps are normal** — *"entryId is a cursor, not a delivery guarantee"*; causes: upstream skips, gateway coalescing, reconnect without replay.

## 4.5 Control frames (always JSON text, in every `receiveType`)

| Frame | Shape | Semantics |
|---|---|---|
| `login_ok` | §4.3 | start processing after this |
| `error` | `{"type":"error","error":"<code>","message":"<text>"}` | **[LIVE]** returned for bad key, bad channel, bad bookmaker, then **0 data frames**. Known `error` values: `"first message must be login"`, `login_failed` (missing/invalid apiKey, no channels allowed/requested, bookmakers not allowed), `too_many_connections` |
| `snapshot_required` | `{"type":"snapshot_required","reason":"resume_window_exceeded","channels":["scores"],"serverEpoch":"…","resumeWindowMs":60000,"serverEntryIds":{"scores":"1766418738000-220"}}` | **NOT fatal — the stream keeps flowing.** `reason ∈ {server_restarted, resume_window_exceeded, client_backpressure}`. Signals client must re-fetch REST snapshots for the listed channels only. Clear `lastSeenId` for those channels. Note `serverEntryIds` is present in examples though absent from the AsyncAPI component schema |
| `resume_complete` | `{"type":"resume_complete","serverEpoch":"…"}` | Sent when replaying from `lastSeenId` succeeds |
| `reconnect` | `{"type":"reconnect","reason":"server_upgrade"}` | **NOT in AsyncAPI**, documented in prose. Precedes blue/green gateway deploys. Server streams for a few seconds grace, then drops the socket. Client must: (1) reconnect immediately without waiting for TCP close; (2) expect `snapshot_required: server_restarted` on the new replica because `serverEpoch` changes |
| `dict` | `{"type":"dict","channel":"odds","dictVersion":"odds-v1","dictId":740826216,"encoding":"base64","data":"<b64>"}` | **`zstd-dict` only.** Pushed after `login_ok`, before any data frame. One per channel with a trained dictionary (~32 KB). Decode data frames by matching their embedded `dict_id` to this `dictId` |

## 4.6 Resume & replay semantics

- Buffer duration: `resumeWindowMs` (typically 60 000 ms = 60 s).
- **Eligibility is cursor AGE, not disconnect duration:**
  $$\text{now\_ms} - \text{int}(\text{entryId}.\text{split}('-')[0]) > \text{resumeWindowMs} \implies \text{snapshot\_required}$$
- For quiet channels, every reconnect triggers `snapshot_required` if the last event was >60 s ago. Client rule: if `now_ms - last_seen_ts > resumeWindowMs`, do not bother sending `lastSeenId` for that channel — immediately trigger a REST snapshot.
- Only send `lastSeenId` for channels present in `replayChannels` from `login_ok.resume`.
- Persist: (1) `serverEpoch`; (2) `lastSeenId[channel] = entryId`.
- **Stream does not pause during `snapshot_required`:** buffer inbound WS updates in memory while REST fetch completes, apply REST snapshot as baseline, then drain buffered updates with `changedAt >= snapshot_ts`.

## 4.7 WS payload shapes by channel

### A. `fixtures`
Identical payload to REST `/fixtures` (§3.3): `fixtureId, status, sport, tournament, season, venue, startTime, trueStartTime, trueEndTime, participants, scores, clock, expectedPeriods, periodLength, externalProviders, bookmakers`.

### B. `odds` (bookmaker-gated)
- Tagline: *"aggregated from 200+ bookmakers. Decimal, fractional, American formats with orderbook depth."*
- Routing key: `payload.fixtureId`.
- Format:
  ```json
  {
    "fixtureId": "id1000001772221240",
    "odds": {
      "<bookmakerSlug>": {
        "<fixtureId>:<bookmakerSlug>:<outcomeId>:<playerId>": {
          "bookmaker": "sx.bet",
          "outcomeId": 1011,
          "playerId": 0,
          "price": 1.99,
          "active": true,
          "marketActive": true,
          "mainLine": true,
          "marketId": 1010,
          "bookmakerMarketId": "...",
          "bookmakerOutcomeId": "...",
          "bookmakerChangedAt": 1788421025400,
          "priceAmerican": -101,
          "priceFractional": "99/100",
          "limit": 286.299,
          "betslip": null,
          "meta": { "back": [{ "price": 1.99, "limit": 286.299, "cents": 0.5025 }] },
          "changedAt": 1788421025510
        }
      }
    }
  }
  ```
- **Delivery semantics (verbatim):** *"This channel is high throughput"*; *"Updates are latest-state only"*; *"The gateway may coalesce or drop intermediate updates under load"*; *"Do not assume tick-by-tick completeness"*; *"Treat every message as a state update, not a ledger."*

### C. `scores`
Routing key: `payload.fixtureId`. Payload: `fixtureId`, `scores: { <period>: { period, participant1Score, participant2Score, updatedAt } }`. Can emit partial period sets (e.g. only `result`). Contains no match status (get status from `fixtures`).

### D. `bookmakers`
Routing key: `payload.fixtureId`. Payload: `fixtureId`, `bookmakers: { <bookmakerSlug>: BookmakerFixtureMeta }`. Pre-filter for `odds`: if `bookmakers[slug].staleOdds == true` or `suspended == true` or `hasOdds == false`, do not quote or trade that bookmaker's prices.

### E. `clocks`
Routing key: `payload.fixtureId`. Payload: `fixtureId`, `clock: { currentPeriod, currentTime, remainingTime, remainingTimeInPeriod, stopped }`. High-frequency clock stream without the heavy fixture payload.

### F. `currencies`
Global, no `fixtureId`. Payload: `{ "<SYMBOL>": { currency, currencyValue, updatedAt } }`. USD reference base.

### G. `futures` & `bookmakersFutures`
`futures`: mirrors REST `FutureMeta` (§3.10). `bookmakersFutures`: mirrors `BookmakerFutureMeta` keyed by `futureId`.

## 4.8 Compression options & benchmarks

| `receiveType` | Data frame format | Control frame format | Observed on probe | Wire efficiency vs JSON | Notes |
|---|---|---|---|---|---|
| `json` | UTF-8 JSON text | JSON text | Confirmed working | 1.0× baseline | Frame size on `odds` can exceed 1 MiB |
| `binary` | MessagePack binary | JSON text | Confirmed working (`ws_odds_binary.jsonl`) | ~1.3–1.5× | Fast unpack, no dict state |
| `zstd` | Dictless zstd binary | JSON text | Confirmed working (`ws_odds_zstd.jsonl`, `_enc: "zstd(dict=0)"`) | ~5–6× | Embedded `dict_id == 0`. Direct decompress |
| `zstd-dict` | Trained zstd binary | JSON text + `dict` frame | Confirmed working (`ws_odds_zstd_dict.jsonl`, `dict=740826216`) | **~7–9×** | Raw frames observed at **320–470 bytes** vs 14–20 KB JSON |

**Decompression implementation rules:**
1. Zstd frames do not store decompressed size in header. Must specify buffer bound: `max_output_size = 64 * 1024 * 1024` (64 MiB).
2. Read header with `zstd.get_frame_parameters(frame).dict_id`.
3. If `dict_id == 0`, use dictless decompressor.
4. If `dict_id > 0`, look up pre-built `ZstdDecompressor` loaded from matching `dict` frame (`dict.dictId`).
5. Fallback: if gateway degrades to JSON, `login_ok.receiveType` will echo `"json"`. Dispatch decoder strictly on `login_ok.receiveType` and frame opcode (text vs binary).

---

# 5. Historical data

## 5.1 Endpoints, depth, and observed retention

OddsPapi provides historical tick feeds and line checkpoints exclusively via REST:

| Endpoint | Target | Time window controls | Observed depth on probe | Ticks / size |
|---|---|---|---|---|
| `GET /fixtures/odds/historical` | Change timeline for ONE fixture + ONE bookmaker (or explicit `oddsIds`) | **None.** No `from`, `to`, `startTimeFrom`, or limit parameters | **180 to 225 days back.** `clv_nba_225d` succeeded; `clv_nba_230d` empty. Aug-2025 EPL fixtures (1 year old) returned empty odds/history despite fixture meta being intact | Pinnacle: 25k–54k ticks (6–13 MB); DraftKings: 433k ticks (**95.6 MB** on single MLB game) |
| `GET /fixtures/odds/clv` | Earliest recorded (`olv`) vs last before kickoff (`clv`) per outcome | None. Fixture-scoped | Same as historical (~200–225 days). On fresh pregame: `olv` populated, `clv: null`. On finished: `clv` populated for ~60–83% of markets | Whole game snapshot: 11k–12.7k oddsIds (4.1–4.2 MB) |
| `GET /fixtures/settlement` | Provider grading per outcome | None. Fixture-scoped | **≥ 1 year.** EPL fixture from Aug-2025 returned **2224** settlement rows | 1.6k–10k rows (0.3–1.6 MB); latency **4.2–8.6 s** |

## 5.2 Granularity & tick density

From `hist_pinn_yday` and `hist_dk_yday` probe captures:
- **Pinnacle tick frequency:** Median inter-tick arrival $\Delta t \approx 22\text{ s}$ pregame; drops to sub-second in-play. 75% of recorded ticks occurred after `trueStartTime`.
- **DraftKings tick frequency:** Median inter-tick arrival $\Delta t \approx 563\text{ ms}$. 433 296 ticks across 1546 series. Extreme tick density reflecting algorithmic micro-adjustments and player prop recalculations.
- **Deduplication:** Multiple ticks appear at identical `price` values. Ticks capture updates to `active`, `marketActive`, `limit`, or gateway keepalive re-stamps.

---

# 6. Cross-provider identifiers present

OddsPapi acts as an identifier hub across vendors. These fields are populated in `Fixture.externalProviders`, `Fixture.participants`, and bookmaker mapping tables:

| Canonical external system | OddsPapi field path | Data type | Real observed example | Usage in our platform |
|---|---|---|---|---|
| **OpticOdds** | `externalProviders.opticoddsId` | `string` | `"20260421A1AB4678"`, `"20260903C7118D8C"` | **Primary join key** to OpticOdds fixtures (format: `YYYYMMDD` + 8 hex chars). Present on 84/100 MLB and 44/49 NFL fixtures checked |
| **Pinnacle** | `externalProviders.pinnacleId` | `int` | `1628730839`, `1634530286` | Direct join to Pinnacle event ID; matches `bookmakers.pinnacle.bookmakerFixtureId` and path segment inside `bookmakerMarketId` |
| **Sportradar / Betradar** | `externalProviders.betradarId` | `int` | `70505056`, `67118324`, `60574219` | Sportradar match id. Matches trailing numeric segment of `id...` fixtureIds in >95% of cases |
| **Genius Sports** | `externalProviders.betgeniusId` | `int` | `13808265`, `13767372` | Direct join to Betgenius fixture feed |
| **Flashscore** | `externalProviders.flashscoreId` | `string` | `"nTPkYS3K"`, `"ruuPcnS7"` | Web entity lookup / reference scraping |
| **Sofascore** | `externalProviders.sofascoreId` | `int` | `15935017`, `15275552` | Sofascore event ID |
| **Mollybet** | `externalProviders.mollybetId` | `string` | `"2026-04-21,29093,29096"` | Mollybet brokerage composite: `YYYY-MM-DD,homeId,awayId` |
| **Polymarket (Event)** | `bookmakers.polymarket.bookmakerFixtureId` | `string` | `"893106"` | Reverse-mapped event ID via `/fixtures/mapping` |
| **Polymarket (Market/Token)**| `OddQuote.bookmakerMarketId` / `bookmakerOutcomeId` | `string` | `"1011497"`, `"493729..."` | Polymarket condition/market ID and CLOB asset token ID |
| **Kalshi** | `bookmakers.kalshi.bookmakerFixtureId` | `string` | `"KXEPLGAME-26SEP05FULCRY"` | Kalshi market ticker symbol |
| **DraftKings** | `bookmakers.draftkings.bookmakerFixtureId` | `string` | `"34572328"` | DraftKings native event ID |
| **Betfair Exchange** | `bookmakers.betfair-ex.bookmakerFixtureId`| `string` | `"35974451"` | Betfair market/event ID |
| **US Rotation Numbers** | `participants.participant1RotNr`, `participant2RotNr` | `int` | `301` (SAS), `300` (POR); `303` (NYK), `302` (ATL) | Secondary join key to OpticOdds and US retail sportsbooks |

*Fields present in schema but null in all probe samples:* `oddinId`, `lsportsId`, `txoddsId`.

---

# 7. Latency, freshness, and staleness semantics

## 7.1 Freshness bounds & SLAs from `GET /bookmakers`

`GET /bookmakers` provides quantitative staleness thresholds per bookmaker:

| Slug | `websocketLive` | `websocketPregame` | `maxDelayLiveInSec` | `maxDelayPregameInSec` | `maxDelayPregameMainInSec` |
|---|---|---|---|---|---|
| `pinnacle` | `true` | `true` | **2.0 s** | 15.0 s | 5.0 s |
| `1xbet` | `true` | `true` | **4.0 s** | 30.0 s | 6.0 s |
| `draftkings` | `true` | `true` | **3.0 s** | 20.0 s | 5.0 s |
| `betfair-ex` | `true` | `true` | **1.0 s** | 10.0 s | 2.0 s |
| `188bet` | **`false`** | `true` | `null` | 80.0 s | 60.0 s |

**Trading gate rule:** If $t_{\text{now}} - \text{changedAt} > \text{maxDelay*InSec} \times 1000$, flag quote as **execution-stale** even if `staleOdds == false`. Books with `websocketLive: false` cannot be streamed in-play; they require REST polling against the 10 rps bucket.

## 7.2 Latency telemetry math

Every quote in REST and WS contains timestamps enabling multi-hop network and pipeline latency calculation:

$$\Delta t_{\text{gateway\_ingest}} = \text{changedAt} - \text{bookmakerChangedAt}$$
$$\Delta t_{\text{egress\_transit}} = \text{envelope.ts} - \text{changedAt}$$
$$\Delta t_{\text{client\_transit}} = t_{\text{client\_recv}} - \text{envelope.ts}$$
$$\Delta t_{\text{total\_age}} = t_{\text{client\_recv}} - \text{bookmakerChangedAt}$$

**Observed numbers on live probe:**
- Pinnacle live quote:
  - $\text{bookmakerChangedAt} = 1776717657043$
  - $\text{changedAt} = 1776717657402 \implies \Delta t_{\text{gateway\_ingest}} = \mathbf{359\text{ ms}}$
  - $\text{envelope.ts} = 1776717657500 \implies \Delta t_{\text{egress\_transit}} = \mathbf{98\text{ ms}}$
  - Ingestion to WS delivery delta: **457 ms**.
- Scraping vs API books: For retail sportsbooks (e.g. Bovada), `bookmakerChangedAt` is frequently null. For direct API/exchange integrations (Pinnacle, Betfair, Polymarket), both timestamps are reliably present.

## 7.3 Staleness flags

1. `BookmakerFixtureMeta.staleOdds` (**Boolean, Critical**): Doc quote: *"Critical for trading: true if the connection to this bookmaker was lost or interrupted, so odds freshness can no longer be guaranteed."* When `staleOdds == true`, immediately suppress arbitrage execution and cancel open quotes referencing this bookmaker.
2. `BookmakerFixtureMeta.suspended` (**Boolean**): True while the market is halted on the bookmaker's side (e.g. during VAR review, penalty kick, time-out).
3. `BookmakerFixtureMeta.participantsRotated` (**Boolean**): True when the bookmaker swaps home and away designations. Crucial for US sports where European-facing books invert participant order.

---

# 8. Edge-relevant facts for arbitrage & market making

1. **Deterministic line identification:** Because `marketId` is identical to the lowest `outcomeId`, and line values live permanently inside frozen `marketId` definitions, computing the overround across books requires no fuzzy text matching:
   $$\text{Overround}(M) = \sum_{o \in \text{outcomes}(M)} \frac{1}{\max_{b} \text{price}(o, b)}$$
2. **Sharp book limits exposed:** `OddQuote.limit` gives max allowable stake in base currency (Pinnacle provides exact limits per side: e.g. \$19,354 on homeay(raw))`; Python `msgpack.unpackb(raw, raw=False)`.

`dict` control frame (zstd-dict only):
```json
{"type":"dict","channel":"odds","dictVersion":"odds-v1","dictId":740826216,
 "encoding":"base64","data":"<base64 of the ~32 KB zstd dictionary>"}
```
- Base64-decode `data`; build a decoder **keyed by `dictId`**. *"Decoding is driven by the `dictId` embedded in each data frame, not by channel. The `channel`/`dictVersion` fields on the `dict` frame are informational."*
- Re-sent on **every** connection; no client cache, no `dicts` login field (removed 2026-05-25).
- Dictionaries exist for **`odds`, `fixtures`, `bookmakers`** (≈32 KB each). Channels without one (`scores`, `clocks`, …) send no `dict` frame; their frames carry `dictId = 0`. **[LIVE] exactly 3 `dict` frames** on an `odds`+`fixtures`+`bookmakers` subscription.
- Python: `pip install zstandard`; frames carry **no content size** ⇒ pass `max_output_size` (doc example 64 MiB); `zstd.get_frame_parameters(frame).dict_id` (0 = dictless); `zstd.ZstdCompressionDict(b64decode(data))`; `zstd.ZstdDecompressor(dict_data=d)`. Every data frame is one standalone zstd frame (magic `28 B5 2F FD`).

**Frame size:** *"The gateway does not limit outbound frame size; uncompressed `odds` frames can exceed 1 MiB."* → set client `max_size ≥ 4 MiB` (4194304) **or** use zstd, else your library closes with `1009`.

## 4.9 Close codes, backpressure, heartbeat

*"Codes in the `4000` range are sent deliberately by the gateway and always carry a reason string."*

| Code | Sent by | Meaning | Action |
|---|---|---|---|
| **4000** | gateway | *"Login problem: no `login` frame within 10 s, or first frame wasn't a valid login"* | fix client; do not retry blindly |
| **4001** | gateway | *"`api_key_revoked` — your key was disabled; reconnecting won't help, contact support"* | page a human, stop retrying |
| **4002** | gateway | *"Backpressure — your client isn't keeping up"* | switch to zstd, narrow filters, offload parsing to a queue |
| **4003** | gateway | *"Connection limit for your key group reached"* (max 5) | shard/serialize connects; exponential backoff |
| **1006** | your library | *"Connection dropped without a close handshake (network path died)"* | reconnect, short backoff |
| **1009** | your library | *"A frame exceeded your library's message-size limit"* | raise `max_size` |
| **1011** | network edge | *"Connection to the gateway was torn down mid-flight"* | reconnect; common right after `reconnect` during releases |

Backpressure symptoms: close `4002`, *"Skipped `odds` updates"*; also `client_backpressure` as a `snapshot_required` reason during replay.

**Heartbeat: no server-side heartbeat/ping message is documented anywhere.** [UNKNOWN whether the server sends WS pings or enforces an idle timeout.] Use transport-level RFC-6455 ping/pong (`ping_interval=20, ping_timeout=20`) as the reference client does; liveness signals available to us are the `ts`/`entryId` stream and per-bookmaker `staleOdds`. **[LIVE]** an idle-ish connection stayed up for **≥11 minutes** with only ~0.5 msg/s → no aggressive idle timeout at that level.

## 4.10 Observed throughput & sizing (probe, 2026-09-03 ~07:12–07:55 UTC, low season: no NBA/NFL, MLB + soccer + tennis live)

| Capture | Login | Messages | Composition | Notes |
|---|---|---|---|---|
| `ws_login_all` (no `channels`, no filters) | all 12 entitled | 40 captured | 1 `login_ok` + **39 `odds`** | firehose is ~100 % odds |
| `ws_bare_login` | default | 720 | **500 odds + 220 bookmakers** | 500-odds cap reached quickly; text frames 1–21 KB |
| `ws_odds_bb_sc` (`sportIds 10,11,13`) | odds | 2000 | 1999 odds | harness cap |
| `ws_odds_pinnacle_poly` (`bookmakers: draftkings,fanduel,kalshi,pinnacle,polymarket`) | odds | 2000 | 1999 odds | 5-book filter still saturates |
| `ws_odds_t17` (EPL only) | odds+bookmakers | 508 | 500 odds + 8 bookmakers | frames ~1 KB |
| `ws_odds_fixture` (single `fixtureIds`) | odds | **28** | 28 odds | ⇒ per-fixture rate ≈ **0.5–1 msg/s** on a live EPL match |
| `ws_fixtures_scores_clocks` | fixtures+scores+clocks | 762 | **738 fixtures + 23 scores + 0 clocks** | fixtures channel is high-volume |
| `ws_slow_channels_11min` | scores+currencies (+others) | 315 over ~11 min | 200 scores + 115 currencies | **scores ≈0.30/s, currencies ≈0.18/s** |
| `ws_odds_zstd` | odds, zstd | 500 | 500 odds | compressed frame **470 B** |
| `ws_odds_zstd_dict` | odds+fixtures+bookmakers, zstd-dict | 542 + 4 control | 500 odds + 5 fixtures + 37 bookmakers | compressed frame **320 B**; 3 `dict` frames |
| `ws_odds_binary` | odds, binary | 500 | 500 odds | msgpack frame **1 821 B** |

**Planning numbers (off-season floor; scale up 3–10× for a full US calendar):**
- All-sports, all-31-books `odds`: the harness hit its 500/2000-message caps in seconds ⇒ **order 10²–10³ msgs/s**, mean JSON frame ~2–5 KB ⇒ **multi-MB/s uncompressed**. With `zstd-dict` (~320–500 B/frame) that becomes **tens–hundreds of KB/s**. **Use `zstd-dict` for the odds connection — non-negotiable.**
- `fixtures` alone can exceed `scores` by ~30× in message count; do not co-locate it with odds on a size-constrained consumer if you can avoid it (but see the 5-connection cap).

---

# 5. Historical data

## 5.1 Endpoints and shapes

| Endpoint | Shape | Granularity |
|---|---|---|
| `/fixtures/odds/historical` | `odds[bookmakerSlug][oddsId][<changedAt-ms as string>] = OddQuote` | **every gateway-accepted change**, ms-stamped |
| `/fixtures/odds/clv` | `odds[bookmakerSlug][oddsId] = {olv: PricePoint, clv: PricePoint\|null}` | 2 points per oddsId |
| `/fixtures/settlement` | `settlements[]` per frozen `(marketId, outcomeId, playerId)` | terminal grade |
| `/futures/odds/historical`, `/futures/odds/clv` | same nesting under `{futureId, odds{…}, bookmakers{…}}` (untyped schemas) | **403 for us** |

No `from`/`to`, no granularity, no `limit`, no pagination on any history endpoint. Selection is by `fixtureId` + (`bookmaker` **xor** `oddsIds`).

## 5.2 Observed depth / retention **[LIVE — this resolves the biggest open question]**

Bisection across NBA/EPL/MLB fixtures (probe timestamp ≈ 1788420000 s ≈ 2026-09-03):

| Fixture age | `/fixtures` metadata | `/fixtures/odds/historical` | `/fixtures/odds/clv` | `/fixtures/settlement` |
|---|---|---|---|---|
| live / today | ✔ | ✔ (12 days of pre-kick ticks on a live EPL fixture: 307 series / 3 816 points) | `olv` ✔, `clv` **null** | rows present, all `UNDECIDED` / `MISSING_PERIODS` |
| yesterday (MLB `id1300010963302451`) | ✔ | ✔ **pinnacle 397 series / 25 068 ticks / 6.0 MB**; **draftkings 1 546 series / 433 296 ticks / 95.6 MB** | ✔ 24 books / 11 149 oddsIds / 4.1 MB (`clv` null ≈17 %) | ✔ 1 652 rows |
| ~200 d back (NBA) | ✔ 75 fixtures | ✔ 10.2 MB (pinnacle) | ✔ 241 KB | — |
| ~210 / 215 / 220 / 225 d back (NBA) | ✔ 21/26/22/22 fixtures | — | ✔ 372 KB / 347 KB / 187 KB / 399 KB | — |
| **~230 d back (NBA)** | ✔ 29 fixtures | — | **✖ 1 945 B = metadata only, `odds:{}`** | — |
| ~250 / 270 / 285 / 300 d back (NBA) | ✔ 28/33/28/68 fixtures | ✖ (300 d: 2 084 B, empty) | ✖ empty (1 948–2 084 B) | — |
| ~180 d back (EPL) | ✔ 21 fixtures | ✔ **pinnacle 7.7 MB** | ✔ 94.7 KB | — |
| ~1 y back (EPL `id1000001761300549`) | ✔ 10 fixtures | ✖ empty (1 570 B, pinnacle **and** draftkings) | ✖ empty | ✔ **2 224 rows incl. HALFWIN/HALFLOSS** |
| NBA 2025 playoff-era (`id1100013270504978`, ~5 mo) | ✔ | ✔ pinnacle 810 series / 54 736 ticks / 13.3 MB; draftkings 39.5 MB | ✔ 12 750 oddsIds / 4.2 MB | ✔ **10 131 rows** / 1.66 MB |

**Conclusions (all [LIVE]):**
1. **Odds history + CLV retention ≈ 220–230 days (~7 months).** Between the 225-day and 230-day NBA buckets, `clv` flips from populated to `odds:{}`. Same cliff for `historical`. **Plan a ~7-month rolling backfill; anything older must be captured by us and stored, or it is gone forever.**
2. **Fixture metadata retention ≥ 1 year** (EPL fixtures from Aug 2025 still resolve, with scores and `statusId 2`).
3. **Settlement retention ≥ 1 year** — settlements survive long after odds history expires (EPL 1 y ago: 2 224 graded rows while CLV/history were empty). ⇒ settlement is the cheap, durable ground-truth store.
4. **`clv` is null pregame and remains null for a minority of oddsIds post-match** (17 % MLB, ~39 % NBA) — those selections never changed price after their first print, or were pulled; always fall back to `olv` and to the last `historical` tick ≤ `startTime`.
5. **Tick density is enormous and book-dependent**: on one MLB game, `draftkings` produced **17× more ticks** than `pinnacle` (433 k vs 25 k) — median inter-tick gap **563 ms (DK)** vs **22 s (Pinnacle)**, ~**75 % of Pinnacle ticks in-play**. DK's stream is effectively a re-confirmation firehose; Pinnacle's is genuine price movement.
6. Per-fixture history volume: **6–96 MB per (fixture, bookmaker)**. A full-book backfill of one MLB slate (15 games × 24 books) is O(10 GB). **Backfill must be selective (see §10.4).**

## 5.3 Historical vs. stream (doc language)

*"The realtime WebSocket `odds` and `oddsFutures` channels deliver **latest state** — optimized for low-latency trading, they coalesce or drop intermediate updates under load and are not a tick ledger."* → **"Use the live stream to trade, and the REST history endpoints to measure."**

⇒ Backtests, CLV attribution and slippage studies **must** be built on `/fixtures/odds/historical`, never on captured WS frames alone (though our own WS capture is still valuable: it is *timestamped at our edge*, which the REST history is not).

---

# 6. Cross-provider identifiers present

## 6.1 Data-provider ids (`externalProviders`)

`externalProviders` is schema-wise a **free-form object** (`{type: object, additionalProperties: true}`) — the key set is **not declared** and **varies per response** (10 keys in some, 7 in others, `{}` in fixture-CLV/historical doc examples). Keys may be **absent** *or* **null**. Values are `int` for some providers, `string` for others ⇒ **store all as strings**.

| Field | Type | Present on | Refers to | Real examples |
|---|---|---|---|---|
| `opticoddsId` | **string** | Fixture, FutureMeta, WS `fixtures`/`futures` | **OpticOdds fixture id — our primary OddsPapi↔OpticOdds join key** | `"20260421A1AB4678"`, `"20260422A553CF52"`, `"2026011039A14E46"`, `"20251225B0C134B3"`, `"202604183517C8A7"`, **[LIVE] `"20260903C7118D8C"` (MLB today)** — format `YYYYMMDD` + 8 hex |
| `pinnacleId` | int | Fixture | Pinnacle event id; **equals `bookmakers.pinnacle.bookmakerFixtureId`** and is embedded in Pinnacle `bookmakerMarketId` | 1628730839, 1628488896, 1621898317, 1621042823, 1628328116 |
| `betradarId` | int | Fixture, FutureMeta | Sportradar/Betradar match id; usually == the native suffix of `fixtureId` (**not always**) | 70505056, 60574219, 67432516, 67118324 |
| `betgeniusId` | int | Fixture (examples; **absent from the WS field table**) | Genius Sports | 13808265, 13808312, 13767372, 12281950 |
| `flashscoreId` | string | Fixture, FutureMeta | Flashscore | `"nTPkYS3K"`, `"ruuPcnS7"`, `"hzkPCh9e"`, `"lWoCl15F"` |
| `sofascoreId` | int | Fixture, FutureMeta | Sofascore | 15935017, 15934995, 13897686, 15275552 |
| `mollybetId` | string | Fixture | Mollybet composite `YYYY-MM-DD,homeId,awayId` | `"2026-04-21,29093,29096"`, `"2025-12-25,10050390,21622"`, `"2026-04-21,10097858,10097878"` |
| `oddinId` | int\|null | Fixture | Oddin (esports) | null in all examples |
| `lsportsId` | int\|null | Fixture | LSports | null in all examples |
| `txoddsId` | int\|null | Fixture | TXOdds | null in all examples |
| `polymarketId` | string | FutureMeta | Polymarket market id; **equals `bookmakers.polymarket.bookmakerFutureId`** | `"16263"` |
| `kalshiId` | string\|null | FutureMeta | Kalshi market id | null in example |

**Not present anywhere:** `theOddsApiId` (SharpSports' cross-ref), Stats Perform / `statsperform` source ids (OpticOdds has those), any Sportradar **team** id. ⇒ OddsPapi↔SharpSports must be bridged **through** OpticOdds (SharpSports→theOddsApiId→? ) or by (rotation number, start time, participant abbr) matching. Participant objects carry **no** external ids at all — `participantAbbr` (CHI/MIL/NYK) is the only team-level cross-vendor hint.

## 6.2 Bookmaker-native ids (the second, richer mapping surface)

| Field | Location | Example (**[LIVE]** for fixture `id1000001772221240`, EPL 2026-09-05) |
|---|---|---|
| `bookmakers.<slug>.bookmakerFixtureId` / `FixtureMapping.bookmakerFixtureId` | fixture meta, `/fixtures/mapping`, WS `bookmakers` | `pinnacle` → **`1634530286`**; `draftkings` → **`34572328`**; `betfair-ex` → **`35974451`**; `polymarket` → **`893106`**; `kalshi` → **`KXEPLGAME-26SEP05FULCRY`** (ticker-style!) ; doc: stake `"46173997-xx-yy"`, draftkings `"33999242"` |
| `bookmakers.<slug>.fixturePath` | fixture meta, WS `bookmakers` | `https://www.pinnacle.com/en/e/e/e/1628488896/#all`, `https://sportsbook.draftkings.com/event/33999242` |
| `bookmakers.<slug>.bookmakerFutureId` / `FutureMapping.bookmakerFutureId` | future meta, `/futures/mapping` | polymarket `"16263"`, stake `"285431-nbl-new-zealand"`; **[LIVE] `null` for pinnacle on a live NBL future** |
| `OddQuote.bookmakerMarketId` | odds rows | Pinnacle `"line/4/487/1628488896/3565645414/0/moneyline"` = `line/{sportId}/{leagueId}/{eventId}/{lineId}/{periodNumber}/{marketType}`; Polymarket `"1011497"` |
| `OddQuote.bookmakerOutcomeId` | odds rows | `"home"` / `"away"` (Pinnacle); Polymarket ERC-1155 token id `"4937…"` |
| `OddQuote.betslip` | odds rows | bookmaker betslip / deeplink token |
| `participants.participant{1,2}RotNr` | Fixture | **303/302** (NYK/ATL), **301/300** (SAS/POR), 210458/210457 (Argentine soccer — clearly not US rotation numbers) → join key to OpticOdds rotation numbers for US books |
| `fixtureId`/`futureId` provider-slug prefix | id string | `id` (Betradar-keyed upstream), `pm` (Polymarket-sourced), `ks` (Kalshi-sourced) |

**`kalshi` `bookmakerFixtureId` is a Kalshi event ticker** (`KXEPLGAME-26SEP05FULCRY`) — directly usable against Kalshi's own API, and a very strong cross-check for our prediction-market side. **`polymarket` `bookmakerFixtureId` (`893106`) is a Polymarket market/event id** for the sports market.

**Practical mapping conclusion (resolved by probe):** we **cannot** ask OddsPapi to reverse-map an OpticOdds id (`bookmaker=opticodds` → **403**). The only path is: enumerate OddsPapi fixtures per (sport, window) and index `externalProviders.opticoddsId` ourselves.

---

# 7. Latency / freshness / staleness semantics

## 7.1 The three clocks on every quote

| Timestamp | Source | Doc language |
|---|---|---|
| `bookmakerChangedAt` (ms) | the bookmaker | *"Bookmaker-provided change timestamp (epoch ms), when present."* / *"reflects the bookmaker's own timestamp"* — **null/absent for scraped books** |
| `changedAt` (ms) | OddsPapi gateway | *"Gateway change timestamp (epoch ms, UTC) — always present; when the gateway accepted this update."* |
| WS envelope `ts` (ms) | OddsPapi gateway egress | *"UTC timestamp (milliseconds)"* — emit time; equals the ts part of `entryId` |

*"These values may differ — do not assume equality."*

**Per-quote latency decomposition (use exactly these):**

| Metric | Formula | Doc/observed value |
|---|---|---|
| Book → gateway ingest | `changedAt − bookmakerChangedAt` | **359 ms** (Pinnacle doc example: 1776717657402 − 1776717657043); WS Pinnacle example **~360 ms** |
| Gateway accept → emit | `ts − changedAt` | **~100 ms** (WS Pinnacle example: 1776717657500 − 1776717657402) |
| Emit → our ingest | `our_recv_ms − ts` | **must be measured by us** — the probe harness recorded `_recv_ms` per frame; e.g. `_recv_ms 1788421288731` vs `ts 1788421288623` ⇒ **108 ms** for a scores frame from `oddspapi-us1` to the probe host |
| End-to-end quote age | `our_recv_ms − (bookmakerChangedAt or changedAt)` | ~0.5 s for Pinnacle in the doc examples; our own number to be tracked as an SLI |
| REST snapshot staleness | `now_ms − changedAt` per quote | compare against `maxDelay*InSec` (§7.2) |

**Store all three timestamps on every quote row.** Without `bookmakerChangedAt` you cannot separate "the book moved late" from "we were slow".

## 7.2 Per-bookmaker freshness bounds (`GET /bookmakers`)

| Field | Doc language |
|---|---|
| `maxDelayPregameInSec` | *"Maximum expected refresh delay for pregame odds, in seconds — the freshness bound for this bookmaker."* |
| `maxDelayLiveInSec` | *"Maximum expected refresh delay for live odds, in seconds."* — **null when `websocketLive:false`** |
| `maxDelayPregameMainInSec` | *"Maximum expected refresh delay for pregame main lines, in seconds."* |
| `websocketPregame` / `websocketLive` | whether pregame / in-play odds for this book are streamed over WS (books with `websocketLive:false` are effectively pregame-only and/or REST-poll-only) |
| **`staleThresholdSec`** ★ | **[LIVE, undocumented]** — almost certainly the threshold the gateway itself uses to flip `staleOdds`; prefer it over hand-tuned constants once its unit is verified |
| **`lastOddsAt`** ★ | **[LIVE, undocumented]** — last time this book produced any odds. **A key-level heartbeat per bookmaker**: if `now − lastOddsAt` ≫ `maxDelay*`, the book is dark globally (not just per fixture) |
| **`staleOddsSince`** ★ | **[LIVE, undocumented]** — presumably when the current stale condition started; `null` when healthy |
| **`availableSports`** ★ | **[LIVE, undocumented]** — per-book sport coverage; use it to avoid polling books that never quote a sport |
| **`limitCurrency`** ★ | **[LIVE, undocumented]** — **resolves "what currency is `limit` in?"**: `pinnacle` → `"USD"`. Read it per book and normalize `limit` via `/currencies` (USD base) |

Doc-example bounds: `188bet` pregame **80 s**, main **60 s**, `websocketLive:false`, no live bound; `1xbet` pregame **30 s**, live **4 s**, main **6 s**.

**Gating rule to implement:**
```
tradeable(quote) :=
    quote.active
and (quote.marketActive is not False)
and bookmakers[bk].hasOdds
and not bookmakers[bk].staleOdds
and not bookmakers[bk].suspended
and (now_ms - quote.changedAt) <= 1000 * (live ? maxDelayLiveInSec : maxDelayPregameInSec)
and (staleThresholdSec is None or (now_ms - quote.changedAt) <= 1000*staleThresholdSec)
```

## 7.3 Stream freshness semantics

- `odds` is **latest-state, coalesced**: absence of a message ≠ price unchanged under load. Combine with (a) per-bookmaker `staleOdds`, (b) `now − changedAt` vs `maxDelay*`, (c) a periodic REST reconciliation snapshot (§10.3).
- `staleOdds` is the authoritative connectivity flag; `staleOddsResponseCode` is **deprecated** — ignore it.
- `scores[period].updatedAt` — *"Use `updatedAt` to detect stale scores."*
- `bookmakers[bk].updatedAt` — when the per-book meta last changed; **not** a price timestamp.
- Changelog 2025-12-12: *"Reduced WebSocket latency for `odds` and `scores`"* — no figures given.
- **Region reality check:** docs recommend *"Central Europe (recommended) and US East"*, colocation at *"Netcup, Hetzner"*, *"Austria (AT) via Netcup"* or *"AWS eu-west-1 (Ireland)"*; deprecated `serverGroup` values `at4`/`de4` corroborate AT/DE hosting. **[LIVE] our key is served by `region: "oddspapi-us1"`** and all Cloudflare rays were `-IAD` (Ashburn) ⇒ **deploy our collector in us-east (GCP `us-east4`/`us-east1`) for OddsPapi**, not Europe. Ask support to confirm the region binding before committing.

---

# 8. Edge-relevant facts for arbitrage / market making

## 8.1 Liquidity & sizing

| Signal | Where | Observed values |
|---|---|---|
| `limit` = *"Maximum accepted stake, when provided by the bookmaker"* | every fixture odds row (REST + WS) | Pinnacle **19 354** on a −645 favourite vs **3 000** on the +477 dog (asymmetric per side!); Pinnacle **4 594** on an NBA CLV point; Polymarket **4.71** |
| `limitCurrency` per book | `GET /bookmakers` **[LIVE]** | `pinnacle: "USD"` → normalize with `/currencies` (USD base; EUR 0.848627, BTC 1.153e-05) |
| Order-book ladders | `meta` on odds rows | **[LIVE]** `polymarket`: `back`/`lay` arrays of `{price, limit, cents, size}` 2–3+ rungs; `betfair-ex`: `availableToBack:[{price,size}]`; `sx.bet`: `back:[{price,limit,cents}]` — `cents = 1/price`, `limit = size × cents` (USD notional at that rung) |
| Depth-weighted execution | derived | For exchange/PM books, compute VWAP-to-size from the ladder instead of trusting the top-of-book `price` |

## 8.2 Sharp reference & line origin

- **Pinnacle is present** (`pinnacle`) with per-side `limit`, real `bookmakerChangedAt`, and a native `bookmakerMarketId` that embeds the Pinnacle event/line ids ⇒ usable as the sharp anchor and for cross-checking Pinnacle directly.
- **Exchanges**: `betfair-ex`, `sx.bet`. **Prediction markets**: `polymarket`, `kalshi` (with Kalshi **event tickers**). ⇒ true two-sided venues are in the same normalized schema as retail books — the core "Jane Street of sports" setup.
- **Retail/US books for +EV and steam detection**: `draftkings`, `fanduel`, `betmgm`, `caesars`, `betrivers`, `borgata`, `betparx`, `ballybet`, `bet365`, plus offshore `bovada.lv`, `betonline.ag`, `bookmaker.eu`, `betus`, `188bet`, `198bet`, `3et`, `4casters`.
- **Tick-rate signature as a book-behaviour prior [LIVE]:** Pinnacle 25 k ticks/game (median gap 22 s, 75 % in-play) = deliberate repricing; DraftKings 433 k ticks/game (median gap **563 ms**) = continuous micro-churn/re-confirmation. Use per-book tick statistics to weight "did the sharp move?" vs "noise".

## 8.3 Market completeness & normalization

- `outcomeId`/`marketId` are **frozen and identical across all bookmakers** ⇒ cross-book arbitrage grouping is exact: same `(outcomeId, playerId)` ⇒ same selection everywhere; **all outcomes of one `marketId`** = complete probability space (`marketLength`), implied probabilities sum ≈1 pre-margin.
- Doc recommendation (verbatim): *"If you perform arbitrage or pricing logic, always group odds by `marketId`."*
- **Each line is its own `marketId`** ⇒ alt-line surfaces come for free; `mainLine` flags the book's primary line for spread/total families.
- **Player props scale**: one live EPL fixture had **7 494** quotes across 27 books of which **2 835 were player props**; NBA market catalogue is **4 902 markets** for one sport. 19 of 31 books have `playerProps:true`.
- `participantsRotated` ⇒ flip sides **and the sign of spreads** for that book before comparing.

## 8.4 Suspension / hard stops

Hard-stop hierarchy (all must be checked):
1. `bookmakers[bk].staleOdds` → **"immediately pause any automated betting or arbitrage logic for this bookmaker"**.
2. `bookmakers[bk].suspended` → book has suspended betting on the fixture.
3. `bookmakers[bk].hasOdds == false` → no live prices (a book can be present with `hasOdds:false`).
4. `marketActive == false` → whole market down.
5. `active == false` → selection down. **Deactivations only reach you via `since` on `/fixtures/odds/main` ("returns also inactive odds") or via WS state updates** — a plain `/fixtures/odds` snapshot appears to omit inactive quotes (implied by docs; **not confirmed live**).
6. Bookmaker **absent** from the `bookmakers` map ⇒ assume no odds.

## 8.5 Opening / closing / CLV

- `olv` = *"the earliest recorded price point for the outcome"*; `clv` = *"the last recorded price point before the fixture started"* — i.e. **last change ≤ start**, not a kickoff snapshot. If a book pulled its line hours early, the "closing" price is that old print → **always inspect `clv.active` and `clv.changedAt` vs `startTime`/`trueStartTime`**.
- **[LIVE]** `clv` is `null` pregame and for 17–39 % of oddsIds post-match ⇒ implement fallback chain: `clv` → last `historical` tick with `changedAt ≤ startTime_ms` → `olv`.
- CLV placeholder junk in doc examples: `priceFractional: ""` and `priceAmerican: 0` — **treat `""` and `0` as missing**, recompute American/fractional from decimal `price` yourself.
- Full ms-resolution tick ledgers give proper CLV attribution, beat-the-close measurement and slippage curves — but **only for ~7 months back** (§5.2).

## 8.6 Settlement timing & grading

- Settlement is **provider-graded per frozen outcome** (bookmaker-independent) with `status`, signed `margin`, `team1Score`/`team2Score`, `periods[]`, `reason` ⇒ single source of truth for P&L across 31 books.
- **[LIVE] timing:** a **pregame** fixture already returns the full row set with `status:"UNDECIDED"`, `reason:"MISSING_PERIODS"`; a fixture from yesterday returns 1 652 fully graded rows. ⇒ **the settlement surface is created before kickoff and mutated to terminal grades afterwards; poll it as a state machine, and key on `(fixtureId, marketId, outcomeId, playerId)` with an `UNDECIDED → terminal` transition.** Exact latency after `trueEndTime` **[UNKNOWN]** — no fixture graded *during* the probe window; measure it in production.
- `reason: "REQUIRES_NON_SCORE_STATS"` ⇒ corners/bookings/player markets that OddsPapi cannot grade from scores alone stay `UNDECIDED` **permanently** (observed on a 1-year-old EPL fixture) ⇒ for those markets we need our own grading source. Budget for this: it affected a meaningful slice of a 2 224-row EPL settlement.
- `HALFWIN`/`HALFLOSS` appear on Asian quarter lines (observed in EPL) — model quarter-ball P&L properly.
- **Settlement calls are slow: 4.2 s / 5.0 s / 8.6 s** for 1.6k–10k rows ⇒ never call it in a hot path; async worker only.
- **Futures settlement is unusable** (doc: 501 `not_implemented`; live: 422 server bug).

## 8.7 In-play

- `access.live: true` ⇒ we have in-play. Live fixtures exist for sports where the calendar allows (tennis: 14 live at 07:29Z).
- Latency chain for in-play (§7.1): ~360 ms book→gateway + ~100 ms gateway→emit + our network. In-play arbitrage windows on retail books are typically 1–5 s; this feed is inside that, but **only if** we colocate near `oddspapi-us1` and use `zstd-dict` to avoid decode/backpressure lag.
- `clocks` channel gives high-frequency period/remaining-time state without the full fixture payload — useful for in-play model triggers (e.g. suspend on `stopped:true`). **[LIVE] no clock traffic observed** for the sports live at probe time; verify coverage per sport before depending on it.
- `trueStartTime`/`trueEndTime` give the actual in-play boundary (may differ materially from scheduled `startTime`) — use them, not `startTime`, for pre/in-play classification and CLV cutoffs.
- Books with `websocketLive:false` (e.g. doc's `188bet`) never stream in-play ⇒ don't expect live quotes from them; don't waste REST budget either.

## 8.8 Prediction-market ↔ sportsbook arbitrage (our best structural edge here)

`polymarket` and `kalshi` are exposed **as bookmakers on ordinary sports fixtures**, with:
- the **same frozen `outcomeId`** as DraftKings/Pinnacle for the same selection ⇒ no fuzzy matching needed;
- full ladders in `meta` with USD notional per rung;
- native ids (`893106`, `KXEPLGAME-26SEP05FULCRY`) for direct execution against the venues;
- `/fixtures/mapping` giving the reverse index.

⇒ **PM-vs-book arbitrage and PM market-making are directly implementable from this feed today**, and it does **not** depend on the futures entitlement we lack.

---

# 9. Gotchas, doc-vs-live contradictions, open questions

## 9.1 Resolved by the probe ✅

| # | Question / doc claim | Resolution |
|---|---|---|
| 1 | Is the 200/min limit per endpoint or shared? | **Per endpoint per apiKey** — separate counters observed in the same window |
| 2 | Real `/fixtures/odds` limit: 10/s (docs) or 30/s (429 example)? | **10/s** (`x-ratelimit-limit: 10`, 1 s windows) |
| 3 | Can we bulk reverse-map OpticOdds→OddsPapi via `/fixtures/mapping?bookmaker=opticodds`? | **No — 403 `bookmaker_not_allowed`** (same for `betradar`, `flashscore`). Must harvest `externalProviders.opticoddsId` from `/fixtures` |
| 4 | `/fixtures/today` & `/fixtures/live` "all params optional"? | **False — 400 `invalid_filters` without `sportId`/`tournamentId`** |
| 5 | Retention of odds history / CLV? | **≈220–230 days**; fixtures metadata ≥1 y; settlement ≥1 y |
| 6 | Is history every tick or sampled? In-play included? | **Every gateway-accepted change, in-play included** (75 % of Pinnacle ticks in-play; DK median gap 563 ms) |
| 7 | What's in `meta` for exchanges/PMs? | **Documented shapes now known** (`back`/`lay`/`availableToBack` with `price,size,limit,cents`; `cents=1/price`, `limit=size×cents`) |
| 8 | Currency of `limit`? | **`Bookmaker.limitCurrency`** (undocumented field) — `pinnacle: "USD"` |
| 9 | Does omitting WS `channels` subscribe to everything entitled? | **Yes** — 12 channels echoed |
| 10 | Is zstd actually enabled? | **Yes on `oddspapi-us1`** for both `zstd` and `zstd-dict`; `dictId 740826216` matches the doc |
| 11 | Are prediction-market topics (sportId 69+) available to us? | **No** — silent `[]` on `/futures`, **403 `sport_not_allowed`** on `/sports?sportIds=69` |
| 12 | Futures odds/CLV/history? | **No — 403 `channel_not_allowed`**; WS `oddsFutures` silently stripped |
| 13 | Max bookmakers per query? | **5** (400 + `hint:"Only 5 bookmakers allowed"`) |
| 14 | Machine-code field name: `code` or `reason`? | **Live always `code`**; openapi declares `reason` → parse both |
| 15 | Are there undocumented `Bookmaker` fields? | **Yes: `staleThresholdSec`, `availableSports`, `lastOddsAt`, `staleOddsSince`, `limitCurrency`** |
| 16 | `/futures/settlement` = 501? | **No — 422 with an `args`/`kwargs` validation payload (server bug)** |

## 9.2 Doc-vs-live contradictions (code defensively)

| Doc says | Live shows | Action |
|---|---|---|
| `/fixtures/today`, `/fixtures/live`: all filters optional | 400 without a sport/tournament | always pass `sportId` |
| 429 example: `/fixtures/odds` `limit:30, windowSec:1` | `limit:10` | read headers at runtime |
| `Error.reason` | `code` (+ extra `bookmaker`/`denied`/`requestedChannels`/`allowedChannels`/`hint` fields) | union parser |
| `ValidationError = {loc,msg,type}` | flattened `details[]` items also carry **`input`** | tolerate extra keys |
| `/futures/settlement` → 501 `not_implemented` | 422 server error | treat any non-200 as unusable |
| `bookmakers` map: *"Contains only bookmakers that currently offer valid realtime odds"* | entries with `hasOdds:false`; and **`{}` on all `/fixtures*` responses even though the doc says it's "present on fixture endpoints"** (it is only populated when the `bookmakers` param is supplied, and even then we saw `{}`) | trust `hasOdds`/`staleOdds`; get meta from `/fixtures/odds*` or the WS `bookmakers` channel |
| AsyncAPI `ChannelName` enum | `clocks` accepted though absent from enum; `reconnect`/`dict` frames absent from spec; `login_ok.region` absent from spec; `snapshot_required.serverEntryIds` in the example but not the schema | treat AsyncAPI as a loose guide |
| Docs' latency advice: colocate in Central Europe / AT | our key is served from **`oddspapi-us1`**, Cloudflare `-IAD` | colocate **us-east**; confirm with support |
| `/fixtures/odds/main?tournamentId=109` should cover the tournament | returned **100** fixtures vs 333 in `/fixtures` | suspect a 100-fixture cap; **shard by `fixtureIds` (≤50/call) for full coverage** |
| Fixture history "provider slug `id` ⇒ native suffix == betradarId" | true for NBA/MLB examples, **false** for NFL `id1400003160574217` (betradarId 67432516) | never parse `fixtureId` |
| Entitlement errors are 403 | `sportId=69` on `/futures` returns `[]` **200**; WS `sportIds:[69]` silently ignored; unknown bookmaker slugs silently dropped from `/bookmakers` | assert your requested filters against the response/`login_ok` echo |

## 9.3 Remaining gotchas (documented, still live)

1. **Auth is in the query string** — key leaks into logs, proxies, CDN traces (`cf-ray` implies Cloudflare sees the URL). Redact everywhere; never persist raw request URLs.
2. **Language prefix `/en` is part of the path**; all `*Name` fields are translated. Never branch on names.
3. **No pagination anywhere** and no documented list-size caps except the 5-bookmaker rule ⇒ responses up to **95.6 MB**. Stream-parse; set generous client timeouts (settlement 8.6 s, DK history 4.4 s observed).
4. **Mixed time units** (seconds for schedule, ms for odds, ISO µs for `updatedAt`) — a top source of bugs. Normalize at the edge to UTC ms integers + keep the raw.
5. **Response-shape asymmetries:** fixture odds = map `odds[slug][oddsId]`; futures odds = array `bookmakers[slug].odds[]` with `oddsId` inside the row; fixture CLV/historical/settlement **omit** `bookmakers` and may return `externalProviders: {}`; futures CLV/historical **include** `bookmakers`.
6. **Param-name inconsistencies:** `bookmaker` (singular) on `/fixtures/odds/historical` and `/fixtures/mapping`; `bookmakers` (plural but still exactly one) on `/futures/odds/historical`; `mainLine` (fixtures) vs `mainLines` (futures); `oddsIds` (plural, values are the `oddsId` strings).
7. **`/fixtures` description mentions a `statusId` filter that does not exist** as a parameter.
8. **`/tournaments` with no params silently defaults to `sportId=11`** — never rely on "all".
9. **Non-standard OpenAPI types** `"int"` and `"json"` on `changedAt`, `bookmakerChangedAt`, `meta` → codegen will choke; map to integer/any manually.
10. **Pending renames:** `Sport.slug → sportSlug`; `Participant.name → participantName`. **Deprecated:** `Bookmaker.serverGroup`, `Bookmaker.price`, `BookmakerFixtureMeta.staleOddsResponseCode`.
11. **`penalties` period key is currently cumulative** (score *after* pens) and *"will change in a future release to be segment-only"* — pin behaviour in tests.
12. **Open/append-only vocabularies:** period keys, `marketType`, `eventType`, `statType`, `statusName`, close-code `reason` values, `reconnect.reason` — never hard-code exhaustive lists; log-and-pass unknowns.
13. **`clock` is an all-null object, not `null`**, until populated; `scores` is `{}` when empty; `season`/`venue`/`RotNr`/`Abbr` are nullable.
14. **Odds rows may omit fields entirely** (not just null).
15. **WS: login-only subscriptions + max 5 connections** — every filter change burns a connection slot.
16. **`odds` may not be replayable** (`replayChannels` doc example excludes it) ⇒ post-disconnect odds recovery is a REST snapshot, always.
17. **Uncompressed odds frames >1 MiB** ⇒ `max_size ≥ 4 MiB` or `1009`.
18. **Breaking-change history to watch:** 2025-11-28 odds keys became bookmaker-scoped; 2026-04-09 fixture shape gained `venue`, `clock`, `seasonRound`, `participantNShortName` and futures `market.marketId` became `int|null`; 2026-05-25 `zstd` became dictless and dictionaries moved to `zstd-dict` (`dicts` login field removed). Expect more additive breakage; keep raw payloads.

## 9.4 Still open (needs a follow-up experiment or vendor question)

| # | Question | How to close it |
|---|---|---|
| 1 | Exact value of `resumeWindowMs` **on our key/region** and the actual contents of `replayChannels` (is `odds` ever replayable?) | read `login_ok.resume` from the saved `ws_*.control` samples; log it permanently at connect |
| 2 | Types/units of `staleThresholdSec`, `lastOddsAt`, `staleOddsSince`, `availableSports` | inspect `samples/oddspapi/bookmakers.json`; then ask support to document |
| 3 | Is there a hard **100-fixture cap** on `/fixtures/odds/main?tournamentId=`? | call with a 200-fixture tournament and compare against `/fixtures` count |
| 4 | Max ids per `fixtureIds`/`oddsIds` (50 proven, cap unknown) | binary-search 50→100→200 and watch for 400/truncation |
| 5 | Does `/fixtures/odds` **without** `since` omit `active:false` quotes? | compare `?since=0` vs no-`since` cardinality on one fixture |
| 6 | Semantics of WS login `live`/`pregame` booleans | send `live:true,pregame:false` and diff the traffic |
| 7 | Meaning of envelope `v`, `seq{p,o}`, `resume.serverCursors`, `resume.enabled` | vendor question |
| 8 | Server-side heartbeat / idle timeout | idle a connection with a `fixtureIds` filter on a dead fixture for 30+ min |
| 9 | Payload schemas for `events`, `stats`, `injuries`, `lineups`, `oddsFutures` | capture during a live US slate (they were silent at probe time) |
| 10 | Settlement latency after `trueEndTime`; whether grade transitions are pushed on any WS channel | poll a finishing fixture every 30 s from `trueEndTime` |
| 11 | Header-based REST auth (to keep keys out of URLs) | vendor question |
| 12 | Whether our region binding (`oddspapi-us1`) is fixed or negotiable; regional hostnames | vendor question |
| 13 | Cost/possibility of adding entitlements: sportIds 16–81, prediction-market topics 69–78, `futures/odds*` channels, >5 bookmakers per query, >5 WS connections | commercial conversation (contact@55-tech.com) |
| 14 | Whether `bookmakers=` (empty value) on `/fixtures` really "filters by mapping" | call `?sportId=13&bookmakers=` and diff counts |
| 15 | Media `Location` targets / "proxy mode" | low priority |

---

# 10. Recommended ingestion strategy

## 10.1 Design principles

1. **WS-first for state, REST for truth.** WS `odds` is the trading feed; REST `/fixtures/odds*` is the reconciliation and recovery path; REST `/fixtures/odds/historical|clv|settlement` is the measurement path.
2. **Store raw, normalize downstream.** Every WS frame and every REST body lands in GCS/ClickHouse raw (compressed) before any transformation. The vendor is actively adding fields (5 undocumented `Bookmaker` fields alone) and breaking shapes ~quarterly.
3. **The odds `oddsId` is the primary key.** `{fixtureId}:{bookmaker}:{outcomeId}:{playerId}` — docs: *"Use these `oddsId` strings as primary keys in your storage for clean dedup, updates, and reconciliation."*
4. **Retention is our moat.** Odds history evaporates at ~7 months; our own capture is permanent. Start capturing WS **now**, even before the analytics layer exists.
5. **Budget the 5 WS connections and the 10 rps odds bucket as scarce resources.**

## 10.2 Connection plan (5 WS connections max)

| # | Purpose | `login` | `receiveType` | Notes |
|---|---|---|---|---|
| **1** | **Odds — primary** | `channels:["odds","bookmakers"]`, `sportIds:[10,11,12,13,14,15]` | **`zstd-dict`** | The money feed. Co-locate `bookmakers` here so the gating flags arrive on the same ordered stream as the prices they gate. Expect 10²–10³ msg/s. |
| **2** | **Odds — shadow / failover** | identical to #1 | `zstd-dict` | Second process, different host/zone. De-dup by `(oddsId, changedAt)`. Gives seamless coverage across releases (`reconnect`) and lets us A/B decode latency. Optional at first; strongly recommended before going live with capital. |
| **3** | **Anchor + scores + clocks** | `channels:["fixtures","scores","clocks"]`, same `sportIds` | `zstd` (dict exists for `fixtures` only; `zstd-dict` also fine) | `fixtures` is chatty (738 msgs vs 23 scores in one window) — keep it off the odds socket. Drives the fixture dimension table, in-play state, `trueStartTime`/`trueEndTime`. |
| **4** | **Slow / auxiliary** | `channels:["currencies","futures","bookmakersFutures","events","stats","injuries","lineups"]` | `json` | Low volume (currencies ~1/6 s; the rest silent for us today). Cheap way to discover the undocumented schemas the moment they start flowing. |
| **5** | **Spare** | — | — | Reserved for reconnect overlap (connect-new-before-closing-old), ad-hoc debugging, and the console. **Never let steady-state usage reach 5** or releases will trip `4003`. |

Per-connection client requirements:
- `max_size = 4194304` (4 MiB), `ping_interval=20`, `ping_timeout=20`.
- Route on **frame type**: text ⇒ JSON control; binary ⇒ data (msgpack or zstd per `login_ok.receiveType`).
- Maintain `dictId → ZstdDecompressor` map from `dict` frames; pass `max_output_size = 64 MiB`.
- **Decode on the socket thread; parse/normalize on an async queue** (backpressure ⇒ close `4002`).
- Persist per-channel `entryId` and `serverEpoch` to Redis/local disk on every N messages or 250 ms, whichever first.
- Log at connect: `region`, `connId`, `userId`, `receiveType`, `channels`, `bookmakers`, `access`, `resume.resumeWindowMs`, `resume.replayChannels`. **Assert the echo matches the request** and alarm on drift (this is how we detect entitlement changes).

## 10.3 REST polling cadence (within limits)

**Odds bucket — 10 req/s shared by `/fixtures/odds`, `/fixtures/odds/main`, `/futures/odds`.** Implement a single global token bucket (10 tokens/s, burst 10) in front of all three. Budget:

| Job | Call | Cadence | Cost |
|---|---|---|---|
| **Reconciliation sweep (main lines)** | `/fixtures/odds/main?fixtureIds=<≤50>&since=<last_sweep_ms>` | rolling, ~2 req/s sustained | Covers all in-window fixtures every 30–60 s. `since` keeps payloads small (944 KB vs 2.4 MB observed) **and returns inactive odds** ⇒ correct removals. Shard by `fixtureIds` (≤50) rather than `tournamentId` to dodge the suspected 100-fixture cap. |
| **Deep snapshot on demand** | `/fixtures/odds?fixtureId=…` (optionally `bookmakers=` ≤5) | on `snapshot_required`, on new-fixture discovery, on any per-fixture divergence alarm | 1 call = full book incl. props (2.96 MB, ~400 ms). Reserve ~3 req/s headroom for bursts. |
| **Pre-kick freeze snapshot** | `/fixtures/odds?fixtureId=…` | T−60 s and T−5 s before each `startTime` | gives us our own CLV independent of the vendor's 7-month window |
| Headroom | — | keep ≥3 req/s free | for recovery storms |

**200 req/min bucket — per endpoint**, so each of these has its own 200/min:

| Job | Call | Cadence |
|---|---|---|
| Fixture discovery (forward) | `/fixtures?sportId=S&startTimeFrom=now&startTimeTo=now+14d` × 6 sports | **every 5 min** (6 calls → 72/hour, trivial) |
| Live set | `/fixtures/live?sportId=S` × 6 | **every 60 s** (6/min of 200) |
| Today | `/fixtures/today?sportId=S` × 6 | every 10 min (redundant with the range query; keep for cross-check) |
| Bookmaker health | `/bookmakers` | **every 60 s** — cheap (17 KB) and gives `lastOddsAt`, `staleOddsSince`, `staleThresholdSec`, `maxDelay*`, `limitCurrency`, `active` |
| Market catalogue | `/markets?sportId=S` × 6 | **daily** (+ on unknown `marketId` seen in a quote → `/markets?marketIds=…` immediately) |
| Tournaments / seasons / participants / players / venues | per lookup-mode | **daily** full refresh; on-demand by id for cache misses |
| Currencies | `/currencies` | hourly (WS `currencies` channel covers realtime) |
| Mapping harvest | `/fixtures/mapping?bookmaker=<slug>&fixtureIds=<batch>` | on fixture discovery, for the ~8 books we may execute on (Pinnacle, DK, FD, betfair-ex, sx.bet, polymarket, kalshi, betmgm) — 8 calls per fixture batch |
| Settlement | `/fixtures/settlement?fixtureId=…` | at `trueEndTime + 15 min`, then exponential retry (30 m, 2 h, 6 h, 24 h) until no `UNDECIDED` rows remain **or** all remaining have `reason ∈ {REQUIRES_NON_SCORE_STATS}`. **8.6 s worst case ⇒ async workers, concurrency ≤3** |
| CLV | `/fixtures/odds/clv?fixtureId=…` | once at `trueStartTime + 30 min` (post-kick, so `clv` is populated), then once at `trueEndTime + 6 h` as a late-fill retry |

Always honour `Retry-After` / `X-RateLimit-Reset` on 429; back off on 503 `rate_limiter_error`; log `cf-ray` with every non-200.

## 10.4 Backfill plan

**Phase 0 — reference data (minutes).** `/sports`, `/bookmakers` (+`playerProps=true`), `/tournaments` × 6 sports, `/seasons` per tournament of interest, `/markets` × 6 sports (**4 902 rows for basketball alone — this is the normalization backbone**), `/participants` × 6, `/players` × 6, `/venues` by id. Store as versioned dimension tables (SCD-2 on `marketId`, `outcomeId`, `handicap`, `marketType`, `period`).

**Phase 1 — fixture spine (hours).** For each sport 10–15, walk `/fixtures?sportId=S&startTimeFrom&startTimeTo` in **7-day windows** back **400 days** and forward **30 days**. Extract and index `externalProviders.*` (esp. `opticoddsId`), `participant*RotNr`, `startTime`/`trueStartTime`/`trueEndTime`, `statusId`. Cost: ~62 windows × 6 sports ≈ 372 calls ≈ 2 minutes of the 200/min budget. **This is the OddsPapi↔OpticOdds mapping table.**

**Phase 2 — settlement backfill (cheap, durable, deepest history).** For every fixture with `statusId == 2` in the spine, fetch `/fixtures/settlement`. ≥1 year deep. Rate: 200/min but 4–9 s latency ⇒ concurrency 3, ~30–40 fixtures/min. Prioritize the leagues we will trade (MLB, NFL, NBA, EPL, NHL, ATP/WTA majors).

**Phase 3 — CLV backfill (7-month window, high value/byte).** `/fixtures/odds/clv?fixtureId=…` for every finished fixture **within 220 days**. ~2 s, 0.2–4 MB per fixture. This gives OLV/CLV for **every book × every outcome** — the single best price-history artefact per byte. Do this **before** tick backfill.

**Phase 4 — tick backfill (selective!).** `/fixtures/odds/historical?fixtureId=…&bookmaker=…`. **Do NOT do this book-by-fixture across the board** (95.6 MB for one DK baseball game). Policy:
- **Always**: `bookmaker=pinnacle` for every finished fixture in the 220-day window in target leagues (6–13 MB each; sharp line path = the reference series).
- **Selectively**: `oddsIds=` restricted to main-line moneyline/spread/total outcomes across 3–8 books (a 3-book `oddsIds` call returned 1.31 MB vs 95.6 MB unrestricted). Build the `oddsIds` list from the CLV response (which enumerates every existing oddsId).
- **Never**: full-book DK/FanDuel history for props unless a specific research question funds the storage.
- Stream-parse into ClickHouse directly; do not materialize the JSON.

**Phase 5 — continuous capture.** From day 1, every WS frame is archived. After ~7 months our own archive strictly dominates the vendor's history window.

## 10.5 Storage layout

**Raw (immutable, GCS + ClickHouse `raw_*`):**

| Stream | Path / table | Partition | Notes |
|---|---|---|---|
| WS frames | `gs://…/oddspapi/ws/dt=YYYY-MM-DD/hh/ch=<channel>/*.jsonl.zst` | day/hour/channel | store the **decoded JSON** plus `_recv_ms` (our edge clock), `channel`, `ts`, `entryId`, `connId`, `region`, and the compressed `_raw_len`. Keep `_enc` so we can audit compression ratios. |
| REST bodies | `gs://…/oddspapi/rest/dt=…/endpoint=<name>/<sha256>.json.zst` | day/endpoint | store the **redacted** URL (`apiKey=***`), status, all `x-ratelimit-*`, `cf-ray`, latency ms, byte size |
| Tick history | ClickHouse `raw_oddspapi_hist` | month | streamed rows, not blobs |

**Normalized (ClickHouse; Snowflake for research marts):**

| Table | Key | Columns (essentials) |
|---|---|---|
| `dim_bookmaker` | `slug`, `valid_from` | `bookmakerName, active, domain, websocketPregame, websocketLive, playerProps, maxDelayPregameInSec, maxDelayLiveInSec, maxDelayPregameMainInSec, staleThresholdSec, limitCurrency, availableSports, availableCountries, lastOddsAt, staleOddsSince` |
| `dim_market` | `marketId`, `valid_from` | `sportId, marketType, period, handicap, marketLength, playerProp, marketName, marketNameShort` |
| `dim_outcome` | `outcomeId` | `marketId, outcomeName, sportId` |
| `dim_fixture` | `fixtureId` | `sportId, tournamentId, seasonId, venueId, startTime_ms, trueStartTime_ms, trueEndTime_ms, statusId, participant1Id, participant2Id, participant1RotNr, participant2RotNr, expectedPeriods, periodLength` |
| `map_fixture_external` | `fixtureId, provider` | `provider ∈ {opticodds, pinnacle, betradar, betgenius, flashscore, sofascore, mollybet, oddin, lsports, txodds}`, `external_id STRING`, `first_seen, last_seen` |
| `map_fixture_bookmaker` | `fixtureId, bookmaker` | `bookmakerFixtureId, fixturePath, participantsRotated, updatedAt` |
| `fact_quote` (state) | `oddsId` | `fixtureId, bookmaker, outcomeId, playerId, marketId, price, priceAmerican, active, marketActive, mainLine, limit, limitCurrency, bookmakerMarketId, bookmakerOutcomeId, betslip, bookmakerChangedAt_ms, changedAt_ms, envelope_ts_ms, recv_ms, meta JSON` — ReplacingMergeTree on `changedAt_ms` |
| `fact_quote_tick` (append) | `oddsId, changedAt_ms` | same, plus `src ∈ {ws, rest_snapshot, rest_history}` — this is the ledger we own |
| `fact_book_status` | `fixtureId, bookmaker, updatedAt` | `hasOdds, staleOdds, suspended, participantsRotated, meta` |
| `fact_score` | `fixtureId, period, updatedAt` | `participant1Score, participant2Score` |
| `fact_clock` | `fixtureId, recv_ms` | `currentPeriod, currentTime, remainingTime, remainingTimeInPeriod, stopped` |
| `fact_clv` | `oddsId` | `olv_price, olv_changedAt_ms, olv_active, clv_price, clv_changedAt_ms, clv_active, clv_is_null` |
| `fact_settlement` | `fixtureId, marketId, outcomeId, playerId, observed_at` | `status, margin, team1Score, team2Score, periods, reason` — keep the full transition history (`UNDECIDED → terminal`) |
| `fact_ladder` | `oddsId, changedAt_ms, side, rung` | `price, size, limit_usd, cents` — flattened from `meta` for `betfair-ex`, `sx.bet`, `polymarket`; **keep raw `meta` too** |
| `ops_stream_health` | `connId, minute` | msgs/s per channel, bytes, decode latency p50/p99, `ts→recv` p50/p99, `entryId` gap count, reconnects, close codes |

Normalization rules: keep `price` as decimal and recompute American/fractional ourselves (vendor placeholders `""`/`0`); convert every timestamp to **UTC ms int** while retaining the raw string; never drop unknown keys (spill to a `extra JSON` column).

## 10.6 Failure & resume handling

| Event | Detection | Action |
|---|---|---|
| `reconnect` frame | control frame | **immediately** open a new connection (use the spare slot), start consuming, then close the old one after its grace window drains. Expect a new `serverEpoch` ⇒ schedule a REST reconciliation sweep for the affected channels. |
| `snapshot_required` | control frame | for each listed channel: `/fixtures` (+`/fixtures/odds/main?fixtureIds=…&since=`… omitted for a full state rebuild) or per-fixture `/fixtures/odds`; **clear** those `lastSeenId`; keep consuming (the stream never stopped). |
| Close `4002` (backpressure) | close code | switch to `zstd-dict` if not already; narrow `sportIds`/`bookmakers`; move parsing off the socket thread; consider splitting odds across two connections by `sportIds`. |
| Close `4003` | close code | serialize connects with jitter; verify no leaked sockets; never exceed 4 steady-state. |
| Close `4001` | close code | **stop retrying**, page a human, contact support (key revoked). |
| Close `4000` | close code | client bug (login not first / >10 s / malformed) — fail fast in CI. |
| Close `1006`/`1011` | library/edge | reconnect with 1 s → 2 s → 5 s → 10 s jittered backoff; resume with cursor **only if** `now − ts(entryId) < resumeWindowMs − 5 000`, else snapshot. |
| Close `1009` | library | raise `max_size`; alarm (means an uncompressed >4 MiB frame). |
| REST 429 | status | honour `Retry-After`; halve the job's concurrency for one window; never retry-storm. |
| REST 503 `rate_limiter_error` | status | back off 5 s, retry up to 3×, then degrade to WS-only and alarm. |
| REST 403 `channel_not_allowed` / `bookmaker_not_allowed` / `sport_not_allowed` | status+code | **entitlement change** — do not retry; disable that job and page (this is how we'd notice a plan change). |
| REST 400 `invalid_filters` | status+code | programming error; fail the job loudly (never retry). |
| Silent empty array | 200 + `[]` | compare against expectation (e.g. entitled sport, in-season league). Alarm on "MLB in September returns 0 fixtures". |
| Divergence WS vs REST | reconciliation sweep | if a `(oddsId)` present in `/fixtures/odds/main` has a newer `changedAt` than our state by >2× `maxDelay*`, log a `stream_gap` event, upsert from REST, and count it as an SLI. Repeated gaps ⇒ suspect coalescing/backpressure. |
| Vendor release / schema drift | `login_ok` echo diff, unknown keys counter | alarm on any new/removed field in `login_ok`, `Bookmaker`, `OddQuote`, or `meta` shapes; the raw archive lets us backfill the new field once modelled. |

## 10.7 SLIs to publish from day one

| SLI | Definition | Target |
|---|---|---|
| Quote freshness p99 | `recv_ms − changedAt` per book | < `1000 × maxDelayLiveInSec` in-play |
| Vendor ingest latency p50/p99 | `changedAt − bookmakerChangedAt` per book | track; Pinnacle baseline ~360 ms |
| Edge transport latency p50/p99 | `recv_ms − ts` | ~100 ms observed from us-east; alarm >500 ms |
| Odds msg rate & bytes/s per channel | from `ops_stream_health` | capacity planning |
| `entryId` gap rate | non-contiguous `seq` per channel per minute | informational (gaps are normal) — alarm only on step changes |
| Stale-book minutes | Σ minutes with `staleOdds=true` per book | per-book reliability ranking; feeds trade gating |
| Reconciliation divergence rate | quotes corrected by REST sweep / total | < 0.1 % |
| Settlement completeness | % of finished fixtures with 0 `UNDECIDED` rows (excluding `REQUIRES_NON_SCORE_STATS`) | > 99 % within 24 h |
| CLV coverage | % of oddsIds with non-null `clv` | ~80 % expected (17–39 % null observed) |
| History retention watermark | oldest fixture with non-empty `/fixtures/odds/clv` | expect ~220 d; alarm if it shortens |

## 10.8 First-week execution order

1. Reference data loader + `dim_*` tables (Phase 0) — proves auth, entitlements, and the market catalogue.
2. Fixture spine + `map_fixture_external` (Phase 1) — **unblocks the OpticOdds↔OddsPapi join, which is the whole point of step one of the platform.**
3. WS connection #1 (`odds`+`bookmakers`, `zstd-dict`) with raw archiving and `ops_stream_health` — start accruing permanent history immediately.
4. WS connection #3 (`fixtures`+`scores`+`clocks`).
5. REST reconciliation sweep (`/fixtures/odds/main` + `since`) and the 60 s `/bookmakers` health poll.
6. Settlement + CLV workers (Phases 2–3).
7. Selective Pinnacle tick backfill (Phase 4) for the two leagues we intend to trade first.
8. Open the vendor conversation on: region binding, entitlement expansion (sports 16–81, futures odds, prediction-