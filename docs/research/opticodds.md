# OpticOdds v3 — Definitive Ingestion Spec (provider: `opticodds`)

**Vendor:** OpticOdds (OddsJam's B2B data product; CDN and affiliate tags still say `oddsjam`) · **API version:** v3 (OpenAPI 3.0.0, `info.version: 3.0.0`)
**Docs host:** `developer.opticodds.com` (`/llms.txt` index; append `.md` to any page URL for markdown) · **Discussion board:** `opticodds.readme.io/discuss` · **Status page:** `https://status.opticodds.com/`
**REST base:** `https://api.opticodds.com/api/v3` · **Streams:** same base, `/stream/...` (Server-Sent Events) · **MCP:** `https://api.opticodds.com/mcp` (Bearer auth) · **RabbitMQ (Copilot / results queues):** `v3-rmq.opticodds.com:5672` vhost `api` (alt host `copilot-rmq.opticodds.com`)
**Self-description (verbatim, getting-started guide):** *"odds from 100+ sportsbooks across 25+ sports"* / SGP guide: *"Processing speed: 1M+ odds per second"* / MCP guide claims *"200+ sportsbooks"*. Live `/sportsbooks` returns **229** ids.

Legend used throughout:
- **[DOC]** = stated in the documentation / embedded OpenAPI blocks.
- **[LIVE]** = observed with our trial key during the probe (2026-09-03T07:22–07:40Z, 171 requests, all raw bodies saved; plus SSE latency/replay runs at ~07:34Z and the cross-provider join at 10:45Z).
- **[LIVE≠DOC]** = live behaviour contradicts the docs.
- **[UNKNOWN]** = not determinable from docs or probe; do not code assumptions.

Reader coverage: every documentation page was read start-to-end by eight reader passes (core, entities-a/b, odds-stream, prediction-markets, results-a/b, copilot-trading). Sections below cite the doc page (`docs__*.md` / `reference__*.md` / `changelog__*.md`) where wording matters.

---

# 1. Product & access summary

## 1.1 What we have (observed entitlements)

| Dimension | Observed value | Evidence |
|---|---|---|
| Plan / key | Trial key, **no Copilot**. `GET /copilot/versions` → `{"data":[]}`; `GET /copilot/fixtures?league=nfl` → `400 {"error":"copilot_version_id is required"}`; `GET /copilot/fixtures/odds?fixture_id=…` → 200 with the fixture wrapper, `odds: []`, `updated_at: "0001-01-01T00:00:00Z"`; `GET /stream/copilot/{sport}/odds` → `connected` + `ping` only. **Not 403** — Copilot endpoints answer but are empty. | [LIVE] |
| Core REST | **Fully entitled, zero 403s across 171 probes.** `/sports`, `/sports/active`, `/leagues`, `/leagues/active`, `/sportsbooks`, `/sportsbooks/active`, `/sportsbooks/last-polled`, `/markets`, `/markets/active`, `/market-types`, `/teams`, `/players`, `/fixtures`, `/fixtures/active`, `/fixtures/odds`, `/fixtures/odds/historical` (incl. `include_timeseries` and `include_locked`), `/futures`, `/futures/odds`, `/grader/odds`, `/fixtures/results`, `/fixtures/player-results`, `/fixtures/player-results/last-x`, `/injuries`, `/injuries/predictions`, `POST /parlay/odds` all 200. | [LIVE] |
| Non-200s seen | 16 × `400` (validation only, bodies in §1.6), 1 × `405` (`GET /parlay/odds`), `401` only for missing/bogus key. | [LIVE] |
| Sports | `GET /sports` → **41** ids (incl. `politics`, `entertainment`, `olympics`, `ebasketball`, `efootball`, `winter_sports`); `GET /sports/active` → **24** with odds now (politics/entertainment NOT active). | [LIVE] |
| Leagues | `GET /leagues` → **1,554** rows (612 KB, no pagination); `GET /leagues/active` → **354** (soccer 246, hockey 16, basketball 14, handball 10, tennis 9, esports 9, cricket 9, golf 7, baseball 5, football 3 …). | [LIVE] |
| Sportsbooks | `GET /sportsbooks` → **229** (186 `is_active`, 114 `is_onshore`). Exchanges / prediction markets present: `kalshi`, `polymarket`, `polymarket_usa_`, `novig`, `prophet_x`, `sporttrade` (inactive), `betfair_exchange`, `betfair_exchange_lay_`, `betfair_exchange_australia_`, `betfair_exchange_australia_lay_`, `matchbook_exchange`, `smarkets` (inactive), `sx_bet`, `limitless_exchange`, `betdex`, `crypto_com`, `robinhood`, `fanatics_markets`, `gemini_exchange`, `opinion_labs`, `tailgate_exchange` (inactive), `draftkings_predictions`, `underdog_predictions`, `opticodds_ai` (inactive), `opticodds_ai_dfs` (inactive). Sharp books: `pinnacle` (is_onshore false, active), `ps3838` (inactive), `circa_sports`, `circa_vegas`, `betonline`, `bookmaker`. | [LIVE] |
| Deep links | `deep_link {android, desktop, ios}` populated on **every** REST odd without any flag (DraftKings, Caesars, FanDuel, bet365, BetMGM, Pinnacle, Polymarket, Kalshi, Novig, Betfair, Fliff, BetOnline …) → the doc-described *"Deep Link Information"* key permission is ON. Streams carry `deep_link: null` unless `include_deep_link=true`. | [LIVE] |
| Exchange depth | `order_book [[price,size],…]`, `limits.max`, `source_ids` returned for Polymarket, Kalshi, Novig, Prophet X, Betfair Exchange; `exclude_fees=true` accepted. | [LIVE] |
| Historical odds | `/fixtures/odds/historical` entitled **including `include_timeseries`** (docs: *"you will need a separate permission on your key"*) and `include_locked`. Own rate bucket `x-ratelimit-limit: 50` / 15 s (docs say 10). | [LIVE] |
| Non-sport prediction markets | `/prediction-markets/categories`, `/canonical-events/ids`, `/canonical-events`, `/stream/prediction-markets` all 200 (docs: *"Access to these endpoints is enabled per API key. If you receive a 403…"*). Served by a **different backend** (no `x-ratelimit-*` headers, `x-latency-*` headers instead, `content-type: application/json; charset=utf-8`). | [LIVE] |
| Kalshi sports odds | Entitled. MLB fixtures returned 262 and 305 Kalshi odds at 07:36Z after returning 0 at 07:23Z (the `last-polled` timestamp for Kalshi was 1,595 s old at 07:24Z — a stale poller, not a permission gap). Kalshi had **no** NFL game odds and **no** EPL odds at probe time but 475 NFL futures odds. Polymarket had NFL/MLB/EPL game odds but 0 NFL futures. | [LIVE] |
| SSE streams | `/stream/odds/{sport}`, `/stream/results/{sport}`, `/stream/futures/{sport}`, `/stream/prediction-markets` all 200 `text/event-stream`. | [LIVE] |
| RabbitMQ results queue | `GET /fixtures/results/queue/status` → one **disabled** queue `{"id":32605,"queue_name":"<RAW_API_KEY>_fres_fa933ea9c274e1e8","enabled":false,"sports":[],"leagues":[]}`. **Security: `queue_name` embeds the raw API key** — treat the response as a secret; never log it. RabbitMQ credentials are provisioned by the sales rep, we have none. | [LIVE] |
| Parlay / SGP pricer | `POST /parlay/odds` priced DraftKings (+242 SGP, +343 cross-game), FanDuel (+210), Caesars (+374 cross-game; SGP call returned `"Error with response. Try again later."`), Novig (+376; SGP call `"Missing odds for entries."`). Same PM backend (no rate-limit headers, 0.16–2.1 s). | [LIVE] |
| RotoWire, OpenOdds partners | Separate add-ons (*"Your OpticOdds API Key will not work with RotoWire"*). Not ours. | [DOC] |
| MCP | Same key, `Authorization: Bearer`. Research tool only. | [DOC] |

> **Practical consequence:** we get the complete public v3 surface — all sports, all 229 books incl. Kalshi/Polymarket/Novig/Prophet X/Betfair with depth, historical ticks, non-sport Kalshi↔Polymarket order books, grader, results, SGP pricer — but **no Copilot** (no consensus/devig engine, no RabbitMQ push, no Copilot snapshots) and **no push-queue for results**. Everything real-time is SSE.

## 1.2 Auth

| Item | Value |
|---|---|
| Header (recommended) | `X-Api-Key: <key>` — every OpenAPI block: `securitySchemes.Header = apiKey in header, name X-Api-Key`. [DOC]+[LIVE] |
| Query param | `?key=<key>` — `securitySchemes.QueryParam = apiKey in query, name key`. Required for browser `EventSource` (cannot set headers); the PM doc explicitly warns *"keys in URLs leak into server logs, browser history, and proxies"*. [DOC] |
| Top-level `security` | `[{Header: []}, {QueryParam: []}]` → either mechanism satisfies every endpoint. [DOC] |
| MCP | `Authorization: Bearer <key>` on `https://api.opticodds.com/mcp`; local `npx -y opticodds-mcp` with env `OPTICODDS_API_KEY`. [DOC] |
| RabbitMQ | username = API key, password from sales rep. [DOC] |
| No key | `HTTP 401 {"error":"API key is required"}` (PM doc spells it `"API key is required."`). [LIVE] |
| Bad key | `HTTP 401 {"error":"Invalid or inactive API key"}`. [LIVE] |
| Env / ops | `OPTICODDS_API_KEY` (strip whitespace: `K="$(printf '%s' "$OPTICODDS_API_KEY" \| tr -d '[:space:]')"`). Redact to `***` in every log line; the key also appears inside `queue_name` (§1.1) and in stream URLs when `key=` is used. |

## 1.3 Base URLs and backends

| Purpose | URL / host | Notes |
|---|---|---|
| REST + SSE | `https://api.opticodds.com/api/v3` | HTTP/2 behind Cloudflare (`server: cloudflare`, `cf-ray`, `cf-cache-status: DYNAMIC`) and a Google front-end (`via: 1.1 google`). [LIVE] |
| Core backend | same host | `content-type: application/json`; `x-ratelimit-limit/remaining/reset` present. [LIVE] |
| Prediction-market / parlay backend | same host, paths `/prediction-markets/*`, `/stream/prediction-markets`, `POST /parlay/odds` | `content-type: application/json; charset=utf-8`; **no** rate-limit headers; `x-latency-start`, `x-latency-end`, `x-latency-time`, `x-latency-proxy-*` headers (e.g. `x-latency-time: 1.94298` on the SGP call). [LIVE] |
| Copilot RabbitMQ | `amqp://<USER>:<PASS>@v3-rmq.opticodds.com:5672/api` (also `copilot-rmq.opticodds.com`) | Copilot only; max **20** simultaneous connections per Copilot account. [DOC] |
| MCP | `https://api.opticodds.com/mcp` | Tools: `get_sports, get_leagues, get_fixtures, get_odds, get_markets, get_sportsbooks, get_player_props, get_injuries, get_results, get_line_history, find_best_price, find_outliers, compare_lines, compare_futures_lines, grade_bet, grade_futures_bet`. [DOC] |
| CDN | `https://cdn.opticodds.com/team-logos/<sport>/<base_id>.png`, `/player-logos/<sport>/<base_id>.png`, `/sportsbook-logos/<id>.jpg`; fallback `https://cdn.oddsjam.com/team-logos/unknown.jpg`; older examples `https://a.espncdn.com/i/teamlogos/...` | Logo host is not stable. [DOC]+[LIVE] |

Stream path form: the 2026 guides and every live capture use **`/stream/odds/{sport}`**, `/stream/results/{sport}`, `/stream/futures/{sport}`, `/stream/prediction-markets` (no sport). The v2→v3 migration page's `/stream/{sport}/odds` and the PM-makers guide's bare `/stream/odds` are stale — **[LIVE resolves]**.

## 1.4 Rate limits — exact numbers

Doc wording (docs__api-faq.md, 2025-10, repeated in the 2026-06 getting-started guide and SSE guide): *"The following rate limits apply for every 15s window, the limit resets after the 15s are completed: Historical Odds: 10 requests every 15 seconds. Streaming endpoints (new connections): 250 requests every 15 seconds. All other endpoints: 2500 requests every 15 seconds."* An older FAQ copy says *"push feed, which supports up to 6,000 requests per minute, compared to the stream endpoint's limit of 250 requests per minute"* — superseded.

| Bucket | Doc limit | **Live headers on our key** | Endpoints |
|---|---|---|---|
| Standard | 2,500 / 15 s | **`x-ratelimit-limit: 8000`** per 15 s | every core REST endpoint incl. `/fixtures/odds`, `/futures/odds`, `/grader/odds`, results, injuries, copilot stubs |
| Historical | 10 / 15 s | **`x-ratelimit-limit: 50`** per 15 s (separate counter: `remaining` counted down 49→45 independently of the standard bucket) | `/fixtures/odds/historical` only |
| Streaming (new connections) | 250 / 15 s | not exposed as headers on SSE responses (none present) | each `GET /stream/...` connect; *"Reconnections count as new requests"*; *"Once connected, the long-lived connection does not consume additional rate limit."* [DOC] |
| PM REST + parlay | none stated | **no headers at all** | `/prediction-markets/*`, `POST /parlay/odds` |

Header semantics [LIVE]: `x-ratelimit-limit` (window size), `x-ratelimit-remaining`, `x-ratelimit-reset` = **Unix seconds** at the end of the current window; observed reset values are multiples of 15 (`1788420135`, `1788420270`, `1788420285`, `1788420300`, `1788420330`, `1788420345`, `1788420375`, `1788420390`, `1788420540`, `1788420750`, `1788420765`, `1788420780`, `1788421005`, `1788421020`, `1788421035`, `1788421050`, `1788421065`) → fixed 15-second wall-clock windows, not sliding. 429 body/`Retry-After` semantics are **not documented and were not triggered** [UNKNOWN]. Doc guidance on 429: *"stop all new connection attempts immediately, wait at least 15 seconds, then resume with backoff"*; historical: *"Queue your historical requests with a 1.5-second delay between each, and batch by fixture"* (that pacing assumed 10/15 s; with 50/15 s use ≤3 req/s).

Other hard caps [DOC]+[LIVE]:
- **≤5 `sportsbook` per request** on `/fixtures/odds`, `/fixtures/odds/historical`, `/futures/odds`, `/sportsbooks/last-polled`, `/markets/active`, streams: 6 books → `400 {"error":"maximum 5 sportsbooks allowed"}`.
- **≤5 `fixture_id` per `/fixtures/odds` call**; `/fixtures/odds/historical` takes exactly **one** `fixture_id`; `/futures/odds` ≤5 `future_id`; `/prediction-markets/canonical-events` ≤25 `canonical_id`.
- `/fixtures/odds` has **no league-wide mode**: `?sport=baseball&league=mlb&sportsbook=draftkings` → `400 {"error":"you must provide at least one of fixture_id, player_id, or team_id"}` [LIVE≠DOC — the SSE guide's "hydrate" example passes `sport`/`league`/`is_live` and is wrong].
- Streams: *"Group up to 10 leagues per connection"* (odds/futures) but *"make a separate connection for each league"* (results). Copilot RabbitMQ: 20 connections.

## 1.5 Pagination

Two envelopes are documented; live returns a third, richer one.

| Shape | Where | Example |
|---|---|---|
| **Live** `{cursor, data, has_more, page}` | `/fixtures`, `/fixtures/active`, `/teams`, `/players`, `/injuries`, `/injuries/predictions`, `/market-types` | page 1 of `/fixtures?league=mlb`: `{"cursor":"eyJpZCI6IjIwMjYwOTA3MjQxNDg5NDUiLCJzZCI6IjIwMjYtMDktMDdUMTc6MzU6MDBaIn0","data":[…100…],"has_more":true,"page":1}` → cursor decodes to `{"id":"2026090724148945","sd":"2026-09-07T17:35:00Z"}` (last row id + sort key). `/players` cursor decodes to `{"id":"CACD48747877","n":"Amari Gainer"}`; `/injuries` to `{"id":"baseball:mlb:3E6E20548BDBAE16","ua":"2026-06-02T22:16:22.178152Z"}`. **Page 2 responses omit the `cursor` key** (`{data, has_more, page}`). |
| Doc `{data, page, has_more}` | reference__common-issues.md; changelog *"Switching from total_pages to has_more … to improve performance and decrease latency"* | |
| Doc `{data, page, total_pages, has_more}` (OpenAPI `required`) | fixtures/teams/players/tournaments/injuries-predictions schemas | `total_pages` was **never returned live**. |
| Unpaginated `{data:[…]}` | `/sports*`, `/leagues*`, `/sportsbooks*`, `/markets*`, `/conferences`, `/divisions`, `/fixtures/odds`, `/fixtures/odds/historical`, `/futures*`, `/fixtures/results*`, `/fixtures/player-results*`, `/tournaments/results`, PM endpoints | `/leagues` = 1,554 rows / 612 KB in one body. |

Rules: request with `page=<n>` (1-based, typed `string`, default `1`); page size is **100** (server-fixed, undocumented); loop while `has_more == true`, fall back to `page < total_pages` if `has_more` is absent (legacy). No cursor query parameter is documented — the cursor is informational; `page=2` worked. `/injuries` **is** paginated live (`has_more: true`, 100 rows) although the doc lists no pagination [LIVE≠DOC]. Never assume unpaginated endpoints are small: `/fixtures/odds` bodies reached **4.99 MB** (3 fixtures × 5 books), `/futures/odds?league=nfl` 2.45 MB, `/fixtures/odds/historical` 1.86 MB (one fixture, one book, all markets).

## 1.6 Error formats

One shape for the core backend, plus three special cases. HTTP status is real (not always 200).

```json
{"error": "<human readable message>"}          // core REST, HTTP 400 / 401
```

Observed messages [LIVE]:

| HTTP | Endpoint | `error` |
|---|---|---|
| 401 | any | `API key is required` / `Invalid or inactive API key` |
| 400 | `GET /sportsbooks/active` | `you must provide at least one of sport, league, or fixture_id` |
| 400 | `GET /sportsbooks/last-polled` | `either league or at least 1 fixture_id must be provided` |
| 400 | `GET /fixtures/odds` (6 books) | `maximum 5 sportsbooks allowed` |
| 400 | `GET /fixtures/odds` (no book) | `sportsbook is required` |
| 400 | `GET /fixtures/odds?league=…` | `you must provide at least one of fixture_id, player_id, or team_id` |
| 400 | `GET /fixtures/active?is_live=true` | `you must provide at least one of sport, league, id, numerical_id, team_id, or tournament_id to filter by` |
| 400 | `GET /fixtures?league=mlb&status=bogus` | `invalid status: bogus` |
| 400 | `GET /fixtures/results?league=mlb&lookback_num=2` | `either fixture_id or team_id must be provided` |
| 400 | `GET /fixtures/results/head-to-head?fixture_id=…` | `team1_id and team2_id are required` |
| 400 | `GET /tournaments/results?league=atp` | `tournament_id is required` |
| 400 | `GET /markets/settleable?sport=baseball` | `leagues is required` |
| 400 | `GET /grader/futures?future_id=…&name=…` | `sport is required` |
| 400 | `GET /fixtures/odds/historical?…&include_timeseries=true` (no market) | `market is required when include_timeseries is true` |
| 400 | `GET /copilot/fixtures?league=nfl` | `copilot_version_id is required` |
| 400 | `POST /parlay/odds` (bad body) | pydantic-style string: `('entries', 0, 'market'): Field required; ('entries', 0, 'fixture_id'): Field required; ('entries', 0, 'name'): Field required; …` |
| 405 | `GET /parlay/odds` | body `Method not allowed`, `text/html` |
| 400 | `GET /stream/odds/{sport}` without `sportsbook` | **`text/plain`** body `At least 1 sportsbook must be provided.` |
| 400 | `GET /stream/prediction-markets?category=bogus` | `text/plain; charset=utf-8` but JSON text: `{"error": "Invalid \`category\`. Valid categories are: politics, economics, finance, crypto, tech, culture, climate, health, geopolitics, companies, other"}` |

Documented-but-not-observed shapes: grader errors `{"message": "...", "code": N}` with codes 100–109 / 201–218 (§3.11); PM `400 {"error":"The category parameter is required."}`, `{"error":"The canonical_id parameter is required."}`; PM `403 Forbidden`. Silent failures: an **unknown sportsbook id is ignored** (`sportsbook=notabook` → 200 with the fixture wrapper and `odds: []`); a wrong id in a 5-book list simply drops that book (`circa`, `prophetx` — correct ids are `circa_sports`, `prophet_x`).

## 1.7 Request conventions

- Multi-value params are **repeated keys** (`explode: true`): `sportsbook=draftkings&sportsbook=pinnacle`. Comma-joined values are not accepted (PM doc: *"not comma-delimited values"*).
- `sportsbook`, `league`, `sport`, `market` accept **id or display name** (`sportsbook=Kalshi`, `sportsbook=Circa%20Sports`, `market=Point%20Spread`, `league=NFL`/`nfl`) [LIVE]. Grader requires the **market label** (`Moneyline`, not `moneyline`).
- URL-encode `+` as `%2B` (`Player Passing + Rushing Yards`) and spaces as `%20`.
- Boolean flags are typed `string`; send `true`/`false` (`True` also appears in doc examples).
- Dates: ISO 8601 `YYYY-MM-DDTHH:MM:SSZ`; date-only `start_date=YYYY-MM-DD` = that calendar day **in EST** [DOC], worked live (`start_date=2026-09-02` → 18 completed MLB games).
- Responses are `{"data": …}` wrapped except pagination fields; `data` is an array everywhere except `/grader/odds`, `/grader/futures` (object) and `POST /parlay/odds` (object keyed by sportsbook name).

---

# 2. Complete endpoint catalogue

Column "Live" = probe status with our key. Rate bucket: **S** = standard (8000/15 s live), **H** = historical (50/15 s live), **C** = streaming connect (250/15 s doc), **P** = PM/parlay backend (no headers).

## 2.1 Discovery / common (tag `Common`)

| Method · path | Purpose | Params (type, req) | Pagination | Bucket | Live |
|---|---|---|---|---|---|
| `GET /sports` | all sports ever supported + `main_markets` | none | no | S | 200, 41 rows |
| `GET /sports/active` | sports with fixtures that currently have odds | none | no | S | 200, 24 rows |
| `GET /leagues` | all leagues | `sport` (array[str], opt) | no | S | 200, 1,554 rows, 612 KB |
| `GET /leagues/active` | leagues with fixtures that have odds now | `sport` (array[str]), `fixture_status` (str, opt; values = fixture status enum) | no | S | 200, 354 rows |
| `GET /sportsbooks` | all books ever supported (`is_active` tells current) | none | no | S | 200, 229 rows |
| `GET /sportsbooks/active` | books that currently have odds for the scope | `sport` (str), `league` (str), `fixture_id` (str) — **≥1 required live** | no | S | 200 (`?sport=baseball` 182, `?league=mlb` 181, `?league=nfl` 150, `?sport=basketball` 132, `?league=england_-_premier_league` 166, `?fixture_id=2026090338F181AF` 174, `?sport=politics` 0, `?league=politics` 0); bare → 400 |
| `GET /sportsbooks/last-polled` | last time ≥1 valid odd was received per book | `league` (str), `fixture_id` (array ≤5), `sportsbook` (array ≤5), `sport` (str, OpenAPI only) — league or fixture_id required | no | S | 200 (`?league=mlb` 212 books; per-fixture works) |
| `GET /markets` | all markets ever supported; coverage matrix | `sport` (str), `league` (str), `sportsbook` (str), `markets_only` (str, default **true**) | no | S | 200 (`?sport=baseball` 342 rows, each with `market_type_id`, `sports: null` because `markets_only` defaulted true) |
| `GET /markets/active` | markets currently offered for fixture × books | `fixture_id` (array, **req**), `sportsbook` (array ≤5, **req**) | no | S | 200 (MLB fixture × 5 books: 67; NFL: 103; EPL × bet365/pinnacle/betfair/kalshi/polymarket: 78; Kalshi-only MLB: 19; Kalshi-only NFL: 0) |
| `GET /markets/settleable` | markets the grader can settle per league | `league` (array, **req**; name or id) | no | S | `?sport=baseball` → 400 `leagues is required` (league form not re-tested) |
| `GET /market-types` | structural market templates | none | **yes** (live `{cursor,data,has_more,page}`) | S | 200, 43 rows (ids 1–44, no 17) |
| `GET /conferences` | conference names + leagues | `sport` (str), `league` (str) — ≥1 required | no | S | not probed [DOC] |
| `GET /divisions` | division names + leagues | same | no | S | not probed [DOC] |

## 2.2 Squads (tag `Squads`)

| Method · path | Purpose | Params | Pagination | Bucket | Live |
|---|---|---|---|---|---|
| `GET /teams` | active teams (inactive fetchable by `id`) | `sport[]`, `league[]`, `id[]`, `numerical_id[]`, `page`, `include_statsperform_id` (default false), `base_id[]`, `division[]`, `conference[]` — ≥1 of sport/league/id | yes | S | 200 (`?league=mlb&include_statsperform_id=true` → 33 rows, `has_more:false`, `cursor:null`) |
| `GET /players` | active players (inactive by `id`) | `sport[]`, `league[]`, `id[]`, `numerical_id[]`, `page`, `include_statsperform_id`, `base_id[]`, `team_id[]`, `team_base_id[]` | yes | S | 200 (`?league=nfl` 100/page, `page=2` ok) |
| `GET /squads?team_id=…` | rosters (getting-started guide only) | `team_id` | ? | S | not probed [UNKNOWN] |

## 2.3 Fixtures (tag `Fixtures`)

| Method · path | Purpose | Params | Pagination | Bucket | Live |
|---|---|---|---|---|---|
| `GET /fixtures` | all fixtures past/future, odds or not; default window *"fixtures from 3 days ago"* | `sport[]`, `league[]`, `id[]`, `numerical_id[]`, `page`, `include_statsperform_id`, `division[]`, `conference[]`, `start_date_before`, `start_date_after`, `start_date`, `updated_since`, `team_id[]`, `include_starting_lineups`, `season_year`, `season_week`, `season_type`, `status[]`, `is_live`, `tournament_id`, `sportsbook` (undocumented), `copilot_version_id` — **≥1 of sport/league/id/numerical_id/team_id/tournament_id** | yes | S | 200. Default `?league=mlb` returned completed games from ~Aug 31 through Sep 7 (100/page, `has_more`). `start_date=2026-07-05` (60 d back) 22 rows with `result`; `start_date=2025-09-01` (1 y) 12 rows with legacy ids `mlb:2DACEC7C8AE9`; `start_date_after/before + status=completed` 37 rows; `status=live` (tennis) 11 rows with `result.in_play_data`; `id=…&include_starting_lineups=true` ok (`lineups: null` pre-game); `updated_since=2026-09-02T00:00:00Z` (NFL) → **0 rows** [UNKNOWN semantics]. |
| `GET /fixtures/active` | fixtures not completed that *"have or have had odds"* | identical to `/fixtures` | yes | S | 200 (`?league=mlb` 82; `?sport=baseball` 100+ with statuses `live/delayed/unplayed`; `?league=mlb&sportsbook=kalshi` 41; `&sportsbook=pinnacle` 7; `?league=nfl&sportsbook=polymarket` 79; `?is_live=true` alone → 400) |
| `GET /tournaments` | tournaments (doc: golf only; tennis fixtures now carry `tournament`) | `sport[]`, `league[]`, `id[]`, `numerical_id[]`, `page`, `include_statsperform_id`, `start_date_before`, `start_date_after`, `season_year`, `include_tee_times` | yes (`total_pages` in doc example) | S | not probed; tennis support [UNKNOWN] |

## 2.4 Odds (tags `Odds`, `Futures`)

| Method · path | Purpose | Params | Pagination | Bucket | Live |
|---|---|---|---|---|---|
| `GET /fixtures/odds` | current odds snapshot; *"We only return odds that are available, if an odd is not returned then it is for all intents and purposes suspended."* | `sportsbook[]` (**req**, ≤5), `fixture_id[]` (≤5), `player_id[]`, `team_id[]`, `market[]`, `is_main` (str), `odds_format` (`AMERICAN` default, `DECIMAL`, `PROBABILITY`, `MALAY`, `HONG_KONG`, `INDONESIAN`), `exclude_fees` (default false), `include_deep_link` (accepted, redundant) — ≥1 of fixture_id/player_id/team_id | no | S | 200. Sizes: 3 MLB fixtures × DK/FD/BetMGM/Caesars/bet365 = **4.99 MB** (DK 811–1,401 odds per fixture, Caesars 328–485, FD 245–760, bet365 ~20, BetMGM 8); NFL × DK/FD/BetMGM/Caesars/Pinnacle = 2,881 odds / 2.3 MB / 104 markets; `team_id=EFED0277C4BD&is_main=true` → 16 fixtures; `player_id=D1F45CEF3017` → 6 fixtures; `is_main=true&odds_format=DECIMAL` ok. |
| `GET /fixtures/odds/historical` | pre-match price history per fixture: OLV/CLV per odd, optional tick `entries` | `fixture_id` (**req**, single), `sportsbook[]` (**req**, ≤5), `market[]`, `is_main`, `odds_format`, `include_timeseries` (default false; **requires `market`**), `include_locked` (default false) | no | **H** | 200. See §5. |
| `GET /futures` | futures markets list | `league[]`, `tournament_id[]` (no `sport` in OpenAPI; guide shows `sport=`) | no | S | 200 (`?league=nfl` 71, `?league=mlb` 37) |
| `GET /futures/odds` | futures prices | `sportsbook[]` (**req**, ≤5), `league[]`, `future_id[]` (≤5), `player_id[]`, `team_id[]`, `future[]` (name or id), `name[]`, `is_main`, `odds_format` — ≥1 of league/future_id/future/player_id/team_id | no | S | 200 (`?league=nfl` × DK/FD/Pinnacle/Kalshi/Polymarket → 5,755 odds / 2.45 MB: DK 4,323, FD 1,400, Pinnacle 32, Kalshi 0 at that moment, Polymarket 0; × Kalshi+Polymarket at 07:28Z → 14 futures / 475 Kalshi odds; `future=Super%20Bowl%20Winner` filter ok) |

## 2.5 Results (tag `Results`) and results queue (tag `Queue`)

| Method · path | Purpose | Params | Pagination | Bucket | Live |
|---|---|---|---|---|---|
| `GET /fixtures/results` | scores, in-play state, team stats, market stats | `fixture_id[]`, `team_id[]`, `lookback_num` (str), `include_cancelled` (default false) — fixture_id or team_id required | no | S | 200 (current, 60 d and 1 y old fixtures all returned) |
| `GET /fixtures/results/head-to-head` | last N meetings of two teams | `team1_id` (**req**), `team2_id` (**req**), `lookback_num` (default 5) | no | S | 400 without team ids (not re-tested) |
| `GET /fixtures/player-results` | per-player box scores, live for some leagues | `fixture_id[]`, `player_id[]`, `team_id[]`, `status` | no | S | 200 (MLB: 35 players × 47 stat keys + `market_stats` + `is_starter`; 1 y old fixture ok) |
| `GET /fixtures/player-results/last-x` | one player's last X games as stat arrays | `player_id[]`, `team_id`, `season_year`, `earliest_date` (YYYY-MM-DD; *"either earliest_date or season_year not both"*), `lookback_num` | no | S | 200 (`?player_id=D1F45CEF3017&num_fixtures=3` returned ~100-game arrays — `num_fixtures` is not a real param; `lookback_num` untested) |
| `GET /tournaments/results` | golf leaderboard | `tournament_id` (**req**), `stage` (`rounds`/`playoff`/`summary`), `round_number` (1–4, stage=rounds), `player_id` | no | S | 400 without tournament_id |
| `GET /fixtures/results/queue/status` | RabbitMQ results queue(s) | `id` (str) | no | S | 200 (one disabled queue; **leaks key**) |
| `POST /fixtures/results/queue/start` | create/start queue | body `{sports:[…], leagues:[…]\|null, id:int\|null}` | — | S | not called |
| `POST /fixtures/results/queue/stop` | stop queue | body `{id:int}` | — | S | not called |

## 2.6 Grader (tag `Grader`)

| Method · path | Purpose | Params | Bucket | Live |
|---|---|---|---|---|
| `GET /grader/odds` | settle one selection | `fixture_id` (**req**), `market` (**req**, display label), `name` (**req**, selection display), `player_id`, `show_live_result` (OpenAPI name; prose says `show_live_results`), `void_substitutes`, `sport`/`league` (prose + example URL only) | S | 200: `{"data":{"fixture_id":"20260902FF9AD242","away_team_display":"Milwaukee Brewers","home_team_display":"Chicago Cubs","status":"Completed","away_score":9,"home_score":5,"player_score":null,"market":"Moneyline","name":"Chicago Cubs","result":"Lost"}}`; works 60 d back |
| `GET /grader/futures` | settle a golf/motorsport future | `sport` (**req**), `league` (**req**), `tournament_id` (**req**), `market` (**req**), `name` (**req**), `player_id`, `show_live_result` | S | 400 `sport is required` when called with `future_id` (golf-only per doc) |

## 2.7 Injuries (tag `Injuries`)

| Method · path | Purpose | Params | Pagination | Bucket | Live |
|---|---|---|---|---|---|
| `GET /injuries` | currently active injuries (NFL, NBA, NHL, MLB, NCAAF, NCAAB, EPL, La Liga, other top soccer) | `sport[]`, `league[]`, `team_id[]` — ≥1 sport/league | **yes live** (doc: none) | S | 200 (`?league=mlb` 100 rows `has_more:true`) |
| `GET /injuries/predictions` | with/without-player impact model (NFL) | `league`, `team_id[]`, `page` — league or team_id | yes | S | 200 |

## 2.8 Parlay / SGP pricer

| Method · path | Purpose | Query | Body | Bucket | Live |
|---|---|---|---|---|---|
| `POST /parlay/odds` | correlated parlay/SGP price per book (or `OpticOdds AI` consensus) | `odds_format` (default AMERICAN), `allow_missing_entries` (default false), `always_include_deep_link` (default false), `allow_negative_correlation` (default false) | `{"sportsbooks":["DraftKings","Caesars","Novig","FanDuel"],"entries":[{"market":"Moneyline","name":"Toronto Blue Jays","fixture_id":"202609038C03FC15"},{"market":"Total Runs","name":"Over 8","fixture_id":"202609038C03FC15"}]}` (`entries` minItems 2 in OpenAPI; guide says 1–50; optional `price_american`/`price_decimal` per entry, required with `OpticOdds AI`) | P | 200 in 2.1 s (SGP) / 0.16 s (cross-game); `GET` → 405 |

## 2.9 Non-sport prediction markets (Kalshi + Polymarket canonicalisation)

| Method · path | Purpose | Params | Bucket | Live |
|---|---|---|---|---|
| `GET /prediction-markets/categories` | category list | none | P | 200: `["politics","economics","finance","crypto","tech","culture","climate","health","geopolitics","companies","other"]` |
| `GET /prediction-markets/canonical-events/ids` | canonical event ids for a category (*"Only canonical events whose members span at least 2 platforms are returned"*) | `category` (**req**), `include_latencies` (prose only) | P | 200: politics **729** ids, crypto 3, economics 0, other 0; `include_latencies=true` adds `"latencies":{"total":0.06155…}` |
| `GET /prediction-markets/canonical-events` | per-platform event/market ids + confidence | `canonical_id[]` (**req**, ≤25 distinct; duplicates/blank ignored) | P | 200 (politics 5/5 matched kalshi+polymarket, confidence 0.82–1.0; crypto 3 with kalshi 0.7) |

## 2.10 Streams (SSE) — full protocol in §4

| Method · path | Purpose | Params | Bucket | Live |
|---|---|---|---|---|
| `GET /stream/odds/{sport}` | odds deltas + locks (+ fixture status) | path `sport` (**req**); `key`, `sportsbook[]` (**req**, ≤5), `league[]`, `fixture_id[]`, `market[]`, `is_main`, `is_live`, `odds_format`, `exclude_fees` (default false), `last_entry_id`, `include_fixture_updates` (default false), `include_deep_link` (default false) | C | 200 (baseball, soccer, football, politics; Kalshi-only variants) |
| `GET /stream/results/{sport}` | live scores/stats | path `sport`; `key`, `league[]`, `fixture_id[]` (no `last_entry_id` in OpenAPI) | C | 200 (tennis 11 events/30 s; baseball 0 events ×2; soccer 1 stale event) |
| `GET /stream/futures/{sport}` | futures deltas + locks | path `sport`; `key`, `sportsbook[]` (**req**), `league[]`, `market[]`, `future_id[]`, `tournament_id[]`, `player_id[]`, `team_id[]`, `is_main`, `is_live`, `odds_format`, `exclude_fees`, `include_deep_link`, `include_source_ids`, `include_limits` (all default false); `last_entry_id` used in the code example but absent from OpenAPI | C | 200 but **0 events** in 30 s (football ×2 incl. a 60 s run) and 30 s (baseball) |
| `GET /stream/prediction-markets` | full order-book snapshots for non-sport markets | `key`, `category` (**req**, exactly one, last wins), `platform[]` (`kalshi`/`polymarket`), `source_event_id[]`, `source_market_id[]`, `canonical_id[]` (last three OpenAPI-only) | P | 200 (politics 120 MB / 45 s; crypto 16.9 MB / 15 s; `platform=kalshi` 2.86 MB / 15 s) |
| `GET /stream/copilot/{sport}/odds` | Copilot odds (not licensed) | `key`, `league[]`, `fixture_id[]`, `market[]`, `is_main`, `is_live`, `odds_format`, `last_entry_id`, `include_fixture_updates`, `version_id` | C | 200, `connected` + `ping` only |

## 2.11 Copilot (documented, **not licensed**, all answer)

`GET /copilot/versions` (200 `{"data":[]}`), `GET /copilot/fixtures` (400 needs `copilot_version_id`), `GET /copilot/fixtures/odds` (200 empty odds; params `fixture_id[]`≤5, `player_id[]`, `team_id[]`, `market[]`, `is_main`, `settled`, `odds_format`, `version_id[]`), `GET /copilot/fixtures/odds/historical` (`id[]` ≤10, bucket H), `GET /copilot/grader/odds` (`id[]`), `GET`/`POST /copilot/parlay/odds`, `GET /copilot/snapshot/fixtures/odds` (returns only `{"data":{"success":bool}}`), `POST /copilot/queue/start|stop`, `GET /copilot/queue/status`, `GET /copilot/queue/remove-connections`, `POST /copilot/results/queue/start|stop`, `GET /copilot/results/queue/status`. Copilot odd ids are `<orgPrefix>:<version_id>:<odd_id>` (e.g. `1:-1:032B6289DB25:point_spread:los_angeles_rams_+2_5`, version `-1` = default). Recorded for shape parity only.

---

# 3. Data model & ID schemes

## 3.1 Hierarchy

```
Sport {id slug}                              e.g. baseball, politics
 └─ League {id slug, region, gender}         e.g. mlb, england_-_premier_league, united_states (politics)
     ├─ Team {id hex, base_id}               league-scoped ids; base_id links across leagues
     │    └─ Player {id hex, base_id, team}  league-scoped ids
     ├─ Tournament {id hex}                  golf; tennis fixtures carry tournament + tournament_stage
     ├─ Fixture {id, numerical_id, game_id}  = schedule + game (v2 "game_id" kept)
     │    ├─ Odd {id, sportsbook, market_id, normalized_selection, …}   (REST /fixtures/odds, SSE odds)
     │    ├─ HistoricalOdd {id, olv, clv, entries[]}                     (/fixtures/odds/historical)
     │    ├─ FixtureResult {scores, in_play, stats, market_stats, …}     (/fixtures/results, SSE fixture-results)
     │    └─ PlayerResult {player, team, stats[], market_stats, is_starter}
     └─ Future {id type_…-sport_…-league_…} └─ FutureOdd {id league:book:market:selection}
Sportsbook {id slug, name, is_onshore, is_active}     229 rows; exchanges & prediction markets are sportsbooks
Market {id slug, name, numerical_id, market_type_id}  MarketType {id int, name, selections[] templates}
PredictionCanonicalEvent {canonical_id 32-hex} └─ events[platform] └─ markets[] {canonical_market_id, source_market_id, question}
PredictionMarketSnapshot {market_id "<platform>:<source_market_id>", outcomes{yes,no}{bids[],asks[]}}
```

## 3.2 ID formats (with real examples)

| Entity / field | Format | Real examples | Notes |
|---|---|---|---|
| `fixture.id` | **opaque string**; current season = 16 chars `YYYYMMDD` + 8 hex; 2025 season = `<league_id>:<12 hex>`; docs also show bare 12 hex | `20260902FF9AD242`, `2026090338F181AF`, `20260910B2546DE0`, `2026090552B5D9A7`, `2026090724148945` (all digits), `mlb:2DACEC7C8AE9`, `england_-_premier_league:0DB083EFBDA2` (doc), `BCE4E01B8D3D` (doc) | Date prefix is the **UTC** start date. Never parse; store ≥64 chars. Both forms are accepted by `/fixtures?id=`, `/fixtures/odds/historical`, `/fixtures/results`. |
| `fixture.numerical_id` | int | `942194`, `594625`, `871030`, `170671` | |
| `fixture.game_id` | `<numA>-<numB>-<date-ish>[-<hour>]` — legacy v2 game id, opaque | `40548-37337-2026-09-02-16` (MLB, trailing = local start hour), `14818-80389-2026-08-31-15`, `37240-25327-26-36` (NFL: yy-week), `15727-24832-2026-34` (ATP: yyyy-week), `42573-28098-2026-09-04` (EPL) | `<numA>-<numB>` are numeric team ids (unordered pair in h2h examples). **`game_id` == SharpSports `oddsjamId`** (cross probe: MLB 37/40). Prefix of every odd id. |
| `team.id` / competitor `id` | 12 or 16 hex | `EDE73BDA9E4F` (Braves), `806CF8213D38` (Giants), `EFED0277C4BD` (Seahawks), `118E9A57A501` (Blue Jays), `F8ED4FE9C4698E9D` (tennis, 16) | League-scoped: Man City is `578E2130DC1B` (UCL) and `E69E55FFCF65` (EPL). `numerical_id` (19) and `base_id` (19) may or may not be equal (NFL: numerical_id 111 / base_id 109). Logo path uses `base_id`. |
| `player.id` | 12 or 16 chars, **not guaranteed hex** | `D1F45CEF3017` (Devers), `93BBC13219D279DD`, `EC22BC642DAF49A1`, `E6873E31B26461CF`, stream `9F39C732DBMMMBA2` (contains `M`) | League-scoped (Messi: `C7231134C08F` MLS, `7D915F8BDA8E` Copa America). In tennis `player.id == team.id`. |
| `tournament.id` | 16 hex (live), 12 hex (doc) | `DFFCED596D794AB9` (US Open ATP), `3E968E39E91C6071` (US Open WTA), `6DC5C0B16061152C`, `0D9C9CCC70BF` (doc golf) | |
| `injury.id` | `<sport_id>:<league_id>:<player_id>` | `baseball:mlb:F3AA22663947` | deterministic upsert key |
| `sport.id` / `league.id` | lowercase slug; `" - "` → `_-_`; dots/colons dropped; in-word hyphens kept | `soccer`, `usa_-_major_league_soccer`, `england_-_premier_league`, `atp_challenger`, `australia_-_a-league`, `cs_go`, `united_states` (politics) | Typos frozen (`philippines_-_phillipine_cup`). League ids are globally unique but not sport-prefixed (`england_-_super_league` = rugby league). Numeric ids: sport `baseball`=3, `football`=9, `soccer`=21, `tennis`=25, `entertainment`=32; league `mlb`=346, `nfl`=367, `england_-_premier_league`=165, `atp_challenger`=21, `united_states`=520. Docs show `nfl` as 9 and 367 on different pages — never key on `league.numerical_id`. |
| `sportsbook.id` | lowercase slug; parenthesised qualifier → `_qualifier_` **with trailing underscore** | `draftkings`, `betfair_exchange_lay_`, `polymarket_usa_`, `prizepicks_5_or_6_pick_flex_`, `caesars_pennsylvania_`, `crypto_com`, `mise-o-jeu` | Display `name` used in `Odd.sportsbook` (`"Betfair Exchange"`), slug in odd ids. |
| `market.id` / `market_id` | snake slug; keeps `+`, `-`, `/`→`_`; `(incl OT)` → `_incl_ot_` | `moneyline`, `run_line`, `total_runs`, `player_hits`, `player_points_+_rebounds_+_assists`, `2nd_quarter_moneyline_3-way`, `4th_quarter_moneyline_incl_ot_`, `player_home_runs_yes_no`, `7th_inning_moneyline_3-way` | `numerical_id` is a global index (moneyline 953, point_spread 1172, total_points 1358, run_line 1245, total_runs 1367, puck_line 1174, goal_spread 933, game_spread 929). |
| `market_type.id` | int 1–44 | `7` = `moneyline`, `20` = `spread`, `31` = `total`, `15` = `player_total`, `34` = `yes_no` | `selections` are templates: `["{away_team_name} {points}", "{home_team_name} {points}"]`. |
| **Odd `id`** (REST, SSE, historical) | `<game_id>:<sportsbook_id>:<market_id>:<normalized_selection>[_<over\|under\|yes\|no>][_<points with . → _>]` | `36707-80389-2026-09-03-09:draftkings:player_hits:rafael_devers_over_2_5`, `81005-66793-2026-09-03-10:pinnacle:1st_half_correct_score:toronto_blue_jays_3_2`, `36707-80389-2026-09-03-09:kalshi:player_bases:oneil_cruz_under_4_5`, `76765-38548-2026-09-03-18:kalshi:run_line:oakland_athletics_+2_5`, `42573-28098-2026-09-04:betfair_exchange:first_goal_scorer:jack_clarke`, main-line historical `40548-37337-2026-09-02-16:draftkings:total_runs:over` | Docs: *"The ID that we return for each odd object is not guaranteed to be of any specific format and is subject to change."* Sportsbook segment is lowercase live (the `/fixtures/odds` doc example shows `BetMGM`). Sign kept for spreads (`_+2_5`, `_-2_5`). |
| Future `id` | `type_<market_id>-sport_<sport_id>-league_<league_id>` | `type_afc_south_winner-sport_football-league_nfl`, `type_offensive_rookie_of_the_year_winner-sport_football-league_nfl`, doc `type_to_make_the_west_play-in_2024-sport_basketball-league_nba` | market slug may contain `-`; split on the `-sport_` / `-league_` anchors. |
| Future odd `id` | `<league_id>:<sportsbook_id>:<market_id>:<normalized_selection>[_<line>_<points>]` | `nfl:kalshi:offensive_rookie_of_the_year_winner:kenyon_sadiq`, `nfl:draftkings:regular_season_rushing_yards:rhamondre_stevenson_over_999_5` | |
| SSE `entry_id` / `id:` | `<epoch_ms>-<seq>` (Redis-stream style) | `1788420576710-0`, `1788421023850-1`, `1788420910334-1` | Empty string on PM bootstrap snapshots. |
| `grouping_key` | `default`, `default:<points>`, `<normalized_selection>:<points>`, `<normalized_selection>` | `default`, `default:8.5`, `default:2.5`, `rafael_devers:2.5`, `chicago_white_sox:3.5`, `brett_bateman`, `cal_raleigh` | pairs the two sides of a line (over/under, ±spread, yes/no). |
| PM `canonical_id`, `canonical_market_id` | 32 lowercase hex | `0084abc100ac5f34988afb271ce21392`, `98b1b58c0d7b50d5ac1484eb255baba6` | OpticOdds-internal. |
| PM `market_id` | `<platform>:<source_market_id>` | `kalshi:AMAZONFTC-29DEC31`, `kalshi:CONTROLH-2026-D`, `polymarket:897017` (doc) | cache key for snapshots. |
| Kalshi native ids | event ticker / market ticker | `KXHOUSERACE-IL11-26` / `KXHOUSERACE-IL11-26-D`; sports `KXMLBTB-26SEP031235SFPIT-PITOCRUZ15-5`, `KXMLBSPREAD-26SEP032140ATHSEA-SEA3`, `KXMLBHR-26SEP032140ATHSEA-SEACRALEIGH29-1` | `source_ids.selection_id` = `yes`/`no`. |
| Polymarket native ids | numeric event/market ids (canonical events); 77-digit CLOB token id (sports odds) | event `191455`, market `1283400`; `source_ids.selection_id = "44931878938656278363269178910047211874481075822738063439341755107592295768730"` | Sports odds give only `selection_id` (token); deep link carries `marketSlug`. |
| Betfair native ids | `{event_id, market_id, selection_id}` | `{"event_id":"36025366","market_id":"1.261950049","selection_id":"7017905"}` | |
| Novig native ids | UUIDv7-style `{event_id, market_id, selection_id}` | `01a06303-5e13-7530-93ec-1d2dcf22c702` / `01a06528-9dcd-7411-a5be-24bc0a78f851` / `01a06528-9dcd-7411-a5be-24ca3fc31383` | |
| Prophet X / BetOnline native ids | `{event_id, selection_id}` / `{event_id}` | `{"event_id":"19457","selection_id":"8b2d0fda17cc0edf64e3a37b2368d1e3"}`; `{"event_id":"491119366"}` | |
| StatsPerform ids | `source_ids.statsperform_id` string | team `"253"`, player `"1228903"`, fixture `"2986833"` (numeric strings live); doc shows `a2nwp4zx1mzcmk2e4dtcw5h5g`; tennis `""` | only with `include_statsperform_id=true`; `null` otherwise. |
| Rotation numbers | int | MLB `902/901` (home even / away odd), ATP `201008/8113`, EPL `810052/200081`, NFL doc `110/109` | 51 % of MLB, 91 % ATP/WTA, 17 % NFL page-1, 67 % NCAAF rows populated. |

## 3.3 Sport, League, Sportsbook, Market, MarketType

**`Sport`** (`/sports`, `/sports/active`): `id` str, `name` str, `numerical_id` int|null, `main_markets` [`BaseMarket`]|null. `BaseMarket = {id, name, numerical_id}`. Main markets are sport-specific: `moneyline` everywhere; spread = `point_spread` (basketball/football/…), `run_line` (baseball), `puck_line` (hockey), `goal_spread` (soccer), `game_spread` (tennis/table tennis), `set_handicap` (volleyball), `handicap` (golf); totals = `total_points` / `total_runs` / `total_goals` / `total_games` / `total_sets` / `total_rounds` (boxing, mma). `politics`, `esports`, `motorsports`, `olympics`, `athletics` list only `moneyline`.

**`League`** (`/leagues`, `/leagues/active`): `id`, `name`, `numerical_id`, `sport` (`Sport` incl. `main_markets`), `region` (UPPER_SNAKE, e.g. `UNITED_STATES`, `INTERNATIONAL`, `CHINESE_TAIPEI`), `region_code` (alpha-3-ish, `USA`, `INT`), `gender` (`men`|`women`|`mixed`|null). Politics leagues: `ireland`, `united_kingdom`, `united_states`; entertainment: `academy_awards`, `major_league_eating`, `preakness_stakes` (all `numerical_id` present except `preakness_stakes: null`).

**`Sportsbook`** (`/sportsbooks*`): `id`, `name`, `logo`, `is_onshore` bool, `is_active` bool — all five required. `is_onshore` ≈ regulated/onshore-ish but not strict (Pinnacle `false`, Sportsbet/Neds `false`, Kalshi/Polymarket `true`). `/sportsbooks/active` can still contain `is_active:false` rows in the doc example — filter client-side.

**`SportsbooksLastPolled`** (`/sportsbooks/last-polled`): `{league: {id,name,numerical_id}, fixture_id: str|null, sportsbooks: [{id, name, timestamp}]}` with `timestamp` = **Unix seconds int** (`1788420426`). One row per (league|fixture) queried.

**`Market`** (`/markets`): `id`, `name`, `numerical_id`, `market_type_id` int|null (FK to `/market-types`), `sports` [`MarketSport{id,name,numerical_id,leagues:[MarketLeague{id,name,numerical_id,sportsbooks:[{id,name}]}]}`]|null (`null` when `markets_only=true`, the live default). `/markets/active` and `/markets/settleable` return flat `BaseMarket` rows (settleable wrapped as `{league: BaseLeague, markets: [BaseMarket]}`).

**`MarketType`** (`/market-types`): `id` int, `name` str (`asian_handicap`, `moneyline_3way`, `player_total`, `spread`, `total`, `yes_no`, `correct_score`, `method_of_victory`, `run_count`, `heads_or_tails`, `color`, `period`, …), `selections` [str] templates, `notes` str|null.

## 3.4 `Fixture` (exact fields, `/fixtures`, `/fixtures/active`)

Live row (`/fixtures?league=mlb&include_statsperform_id=true`), 39 keys in this order:

| Field | Type | Example / semantics |
|---|---|---|
| `id` | str | `20260831B2BB37AB` |
| `numerical_id` | int|null | `942194` |
| `sport` | `{id,name,numerical_id}` | `{"id":"baseball","name":"Baseball","numerical_id":3}` |
| `league` | `{id,name,numerical_id}` | `{"id":"mlb","name":"MLB","numerical_id":346}` |
| `tournament` | `{id,name,numerical_id,start_date,end_date}`|null | ATP: `{"id":"DFFCED596D794AB9","name":"US Open, New York, USA","numerical_id":20486,"start_date":"2026-08-23T00:00:00Z","end_date":"2026-09-13T00:00:00Z"}` |
| `tournament_stage` | str|null | `"Round of 128"`, `"Qualification"` |
| `game_id` | str|null | `14818-80389-2026-08-31-15` |
| `start_date` | ISO `Z` | `2026-08-31T22:05:00Z` (stream payloads use `+00:00`) |
| `updated_at` | ISO `Z` µs|null | `2026-08-30T18:46:26.370305Z`; Copilot stub `0001-01-01T00:00:00Z` |
| `status` | enum | `unplayed`, `live`, `completed`, `cancelled`, `delayed` seen live; doc adds `half`, `suspended` |
| `is_live` | bool | may be `true` on a `completed` fixture (doc h2h example) — trust `status` |
| `has_odds` | bool | `true` even on cancelled placeholder fixtures |
| `home_competitors` / `away_competitors` | [`Competitor`] | `[{"id":"EDE73BDA9E4F","numerical_id":19,"base_id":19,"name":"Atlanta Braves","abbreviation":"ATL","logo":"https://cdn.opticodds.com/team-logos/baseball/19.png"}]`; `abbreviation` may be `""` (tennis); golf round-prop fixtures have empty arrays |
| `home_team_display` / `away_team_display` | str|null | `"Atlanta Braves"`; golf: `away_team_display ∈ {Round 1..4}` |
| `home_starter` / `away_starter` | str|null | `"Bryce Elder"` (probable pitcher / goalie) |
| `home_starter_id` / `away_starter_id` | str|null | `"B13DA8B7B12C"` |
| `home_record` / `away_record` | str|null | `"82-56"` |
| `home_seed` / `away_seed` | str|null | |
| `home_rotation_number` / `away_rotation_number` | int|null | `902` / `901` |
| `venue_name`, `venue_location` | str|null | `"Truist Park"`, `"Atlanta, GA, USA"`; tennis `"Court 6"` |
| `venue_neutral` | bool | |
| `broadcast` | str|null | `"NSBA \| BRVN"`, `""` |
| `season_type` | str|null | `"Regular Season"`, `"Playoffs"`, tennis `"US Open, New York, USA"`, esports free text |
| `season_year` | **str**|null | `"2026"` (season start year label) |
| `season_week` | **str**|null | `"36"`, `"22"`, tennis `"round of 128"`, `"playoffs"` |
| `extra` | `{level, sub_league, num_periods, match_format, detailed_stats, online}`|null | esports only |
| `result` | `{scores: {home: Score, away: Score}, in_play_data: {period, period_number, clock, last_play}}`|null | completed MLB: `in_play_data {"period":"9","period_number":null,"clock":null,"last_play":null}`; live tennis: `{"period":"3",…}`; `null` when unplayed |
| `lineups` | `{home: [LineupPlayer], away: [...]}`|null | only with `include_starting_lineups=true`; `null` pre-lineup. `LineupPlayer = {player_id, player_name, player_team, player_position, player_batting_throwing, is_substitute}` |
| `weather`, `weather_temp` | str|null | |
| `source_ids` | `{statsperform_id: str}`|null | `{"statsperform_id":"2986833"}`; `{"statsperform_id":""}` (ATP); `null` without the flag |

`Score = {total: number|null, periods: {period_1: n, …}|null, aggregate: number|null}`. Period keys: baseball innings `period_1..period_9` (+ extras), basketball/football quarters + `period_5` = OT, soccer `period_1/2` halves, `period_3` ET, `period_4` pens, tennis sets. **`season_year`/`season_week` are strings.** `updated_at` exists on every row (sync key for `updated_since`, though the probe's `updated_since` call returned nothing — see §9).

## 3.5 `Team` and `Player`

**`Team`** (`/teams`): `id`, `name`, `numerical_id`, `base_id`, `is_active`, `city`, `mascot`, `nickname`, `abbreviation`, `division` (`"West Division"`), `conference` (`"NL"`), `logo`, `source_ids` (`{"statsperform_id":"253"}` or `{}`), `sport`, `league`. Example: `{"id":"9CAFB55230E8","name":"Arizona Diamondbacks","numerical_id":18,"base_id":18,…}`.

**`Player`** (`/players`): `id`, `numerical_id` (`1725101`), `is_active`, `name`, `first_name`, `last_name`, `age` (int; live sample shows `2` — treat as unreliable), `height` (inches, `69`), `weight` (lbs, `195`), `experience` int|null, `number` int|null, `position` (`"CB"`, `"RP"`, `"1B"`), `logo` (`/player-logos/football/4857.png` = base_id), `base_id` (`4857`), `source_ids` (`{"statsperform_id":"1228903"}`), `sport`, `league`, `team` `{id,name,numerical_id,base_id}` (`{"id":"43412DC9CDCA","name":"Detroit Lions","numerical_id":93,"base_id":91}`).

`BasePlayer` (embedded in results/injuries) = `{id, name, position, number, numerical_id, base_id}`; `BaseTeam` = `{id, name, numerical_id, base_id}`.

## 3.6 Odd objects — REST `FixtureOdd`, SSE stream record, unification

### REST `/fixtures/odds` → `{"data":[FixtureWithOdds]}`

Fixture wrapper keys (19): `id, numerical_id, game_id, start_date, home_competitors, away_competitors, home_team_display, away_team_display, status, is_live, season_type, season_year, season_week, venue_name, venue_location, venue_neutral, sport, league, tournament` (+ `odds[]`; OpenAPI adds `tournament_stage`, `detailed_stats`).

`FixtureOdd` (19 keys, exact, from `36707-80389-2026-09-03-09:draftkings:player_hits:rafael_devers_over_2_5`):

| Field | Type | Example | Semantics |
|---|---|---|---|
| `id` | str | see §3.2 | opaque cache key; rebuild composite keys for history |
| `sportsbook` | str (display) | `"DraftKings"`, `"Betfair Exchange"` | no `sportsbook_id` on REST; take slug from `id` segment 2 |
| `market` | str (display) | `"Player Hits"`, `"1st Half Correct Score"` | |
| `market_id` | str | `player_hits` | |
| `name` | str | `"Rafael Devers Over 2.5"`, `"Toronto Blue Jays 3:2"`, `"Over 8.5"` | full selection display; the `name` accepted by the grader |
| `price` | number | `1200`, `-123`, `-10421` (American default); `1.075`, `2.39` with `odds_format=DECIMAL` | see fee note below |
| `points` | number|null | `2.5`, `8.5`, `-2.5`, `null` | line |
| `selection` | str | `"Rafael Devers"`, `"Toronto Blue Jays"`, `""` (totals) | |
| `normalized_selection` | str | `rafael_devers`, `""` | cross-book match key |
| `selection_line` | str|null | `over`, `under`, `yes`, `no`, `3:2` (correct score), `null` | |
| `timestamp` | float epoch s | `1788420167.231546` | last **change** of price/points at OpticOdds |
| `grouping_key` | str|null | `rafael_devers:2.5`, `default:8.5`, `default` | |
| `is_main` | bool | | main vs alternate line |
| `player_id` | str|null | `D1F45CEF3017` | |
| `team_id` | str|null | `118E9A57A501` | |
| `limits` | `{max: number}`|null | `{"max":12300}` (BetOnline), `{"max":250}` (Pinnacle correct score), `{"max":106.92}` (Polymarket = top-of-book size) | `null` for DK/FD/Caesars/bet365/BetMGM/Fliff/Circa |
| `order_book` | `[[price,size],…]`|null | Polymarket `[[156,25.35],[150,1840.53],[144,2770.53],…]` (10 levels), Kalshi up to 10 levels, Novig `[[614,294]]` | one-sided (back) book in the requested odds format |
| `source_ids` | object|null | see §3.2 | native routing ids (exchanges + BetOnline `event_id`) |
| `deep_link` | `{android, desktop, ios}`|null | DK `dksb://sb/addbet/0QA366296068%232270347905_13L84240Q11373763416Q20`, Polymarket `…?via=oddsjam&…&marketSlug=mlb-sf-pit-2026-09-03-tb-spencer-horwitz-2pt5&outcomeIndex=1`, Kalshi `…?marketTicker=KXMLBTB-…&orderSide=no`, Pinnacle `https://www.pinnacle.com/en/baseball/mlb/toronto-blue-jays-vs-cleveland-guardians/1634922658/#all` | present by default on REST; `null` for Pinnacle on the EPL fixture |

Per-book field availability observed [LIVE]:

| Book | `limits.max` | `order_book` | `source_ids` | `deep_link` | Notes |
|---|---|---|---|---|---|
| DraftKings, FanDuel, Caesars, bet365, BetMGM, Fliff, Circa Sports | null | null | null | yes | Circa `deep_link` present; no limits |
| Pinnacle | yes (NFL mains 1,000–15,850; MLB correct score 250; EPL total 4,200) | null | null | yes/null | true stake limits |
| BetOnline | yes (1,620–23,000) | null | `{event_id}` | yes | |
| Polymarket | = top-of-book size (25.35–18,912) | 1–10 levels | `{selection_id: <clobTokenId>}` | yes (`via=oddsjam`) | `price` is **fee-adjusted** (`-10421` vs book `-9900`; `148` vs book `156`) unless `exclude_fees=true` |
| Kalshi | = top size (46.5–932.76) | up to 10 levels | `{market_id: <ticker>, selection_id: yes\|no}` | yes | with `exclude_fees=true&odds_format=DECIMAL`, `price 1.075 == order_book[0][0]` |
| Novig | = top size (46–294) | 1 level | `{event_id, market_id, selection_id}` uuids | `novigapp://…?referralCode=ODDSJAM` | `price == order_book[0][0]` (vig-free) |
| Betfair Exchange | = available liquidity (3.77–650.72) | **null** (no depth on `betfair_exchange`; lay side is the separate book `betfair_exchange_lay_`) | `{event_id, market_id, selection_id}` | yes | |
| Prophet X | yes (38.46) | 1 level | `{event_id, selection_id}` | yes | |

### SSE `odds` / `locked-odds` record (27 keys, exact, from the baseball stream)

`team_id, limits, source_ids, selection_points, order_book, selection, normalized_selection, selection_line, points, deep_link, game_id, grouping_key, name, market, market_id, sportsbook, sport, id, fixture_id, sportsbook_id, league, league_id, price, is_main, is_live, timestamp, player_id` — key order varies per record. Adds vs REST: `fixture_id` (`20260902FF9AD242`), `game_id`, `sport` (`baseball`), `league` (display `MLB`), `league_id` (`mlb`), `sportsbook_id` (`polymarket`), `selection_points` (duplicate of `points`), `is_live` (per odd). `deep_link` is `null` unless `include_deep_link=true`. Docs additionally mention `normalized_selection` (present) and, in older prose, `limits.max_stake` (never observed; accept both). Doc examples show `player_id: ""`/`team_id: ""` — live uses `null`; treat `""`/`null`/absent identically.

### Unification table

| Field | REST `/fixtures/odds` | SSE `odds`/`locked-odds` | `/fixtures/odds/historical` | `/futures/odds` | SSE `futures` odds[] |
|---|---|---|---|---|---|
| id | ✓ | ✓ | ✓ | ✓ | ✓ |
| sportsbook / sportsbook_id | name | name + id | name | name | group `sportsbook{id,name}` |
| market / market_id | ✓/✓ | ✓/✓ | ✓/✓ | ✓/✓ | group |
| name, selection, normalized_selection | ✓ | ✓ | ✓ | ✓ | ✓ |
| selection_line | over/under/yes/no/`3:2`/null | same | ✓ | ✓ | ✓ |
| points / selection_points | points | both | only inside olv/clv/entries | points | points |
| price / timestamp | ✓ float s | ✓ float s | entries[].timestamp **int s** | ✓ float s | ✓ |
| is_main | ✓ | ✓ | ✓ | ✓ | ✓ |
| is_live | fixture wrapper | per odd | wrapper | – | group |
| grouping_key | ✓ | ✓ | – | – | ✓ nullable |
| player_id / team_id | ✓ | ✓ | ✓ | ✓ | ✓ |
| limits / order_book / source_ids | by book | by book (default) | – (`deep_link_info` only) | – | only with `include_*` flags |
| deep_link | default | flag | `deep_link_info` | – | flag |
| fixture_id / game_id / sport / league | wrapper | flat | wrapper | group | group objects |

## 3.7 `FixtureHistoricalOdd` (`/fixtures/odds/historical`)

Wrapper (19 keys): `id, numerical_id, sport, league, tournament, game_id, home_competitors, away_competitors, home_team_display, away_team_display, start_date, is_live, status, season_type, season_year, season_week, venue_name, venue_location, venue_neutral` + `odds[]`.

Odd (15 keys): `id, sportsbook, market, market_id, name, selection, normalized_selection, selection_line, points, player_id, team_id, is_main, olv, clv, entries` (+ OpenAPI `deep_link_info`).

- `olv` / `clv`: `{price: number|null, points: number|null}` — opening / closing line value. `clv` is `null` until ~2 days after the game (§5).
- `entries`: `[{timestamp: int epoch s, price: number, points: number|null, locked: bool}]`, `[]` unless `include_timeseries=true`; e.g. `{"timestamp":1788286434,"price":134,"points":null,"locked":false}` … 18 entries ending `{"timestamp":1788383898,"price":130,…}`. `olv == entries[0]`, `clv == last pre-close entry` when set.
- With `is_main=true` the main-line rows are **point-less**: id `…:total_runs:over`, `name: "over"` (lowercase), `olv {"price":-117,"points":8}`; alternates keep points in the id (`…:total_runs:under_9_5`).
- `include_locked=true` accepted; 0 of 446 Pinnacle Total Runs entries were `locked: true` in the sample [UNKNOWN whether locks are ever emitted].

## 3.8 Futures entities

**`Future`** (`/futures`): `id`, `name` (`"AFC South Winner"`), `sport`, `league`, `tournament` (`BaseTournament`|null), `future_type` (`TEAM`|`PLAYER`|`UNKNOWN`|null), `start_date` (`2027-01-10T11:30:00Z`; sometimes creation-like `2026-11-26T07:28:48.934746Z`).

**`FutureWithOdds`** (`/futures/odds`): same + `odds[]` of **`FutureOdd`** (14 keys): `id, sportsbook, market, name, price, timestamp, is_main, selection, normalized_selection, market_id, selection_line, player_id, team_id, points` — e.g. `{"id":"nfl:kalshi:offensive_rookie_of_the_year_winner:kenyon_sadiq","sportsbook":"Kalshi","market":"Offensive Rookie Of The Year Winner","name":"Kenyon Sadiq","price":9207,"timestamp":1788420529.417125,"is_main":true,"selection":"Kenyon Sadiq","normalized_selection":"kenyon_sadiq","market_id":"offensive_rookie_of_the_year_winner","selection_line":null,"player_id":"E6873E31B26461CF","team_id":null,"points":null}`. No `grouping_key`, `limits`, `order_book`, `source_ids`, `deep_link` on REST futures.

**SSE `futures`/`locked-futures`** payload: `{entry_id, type, data: [FutureGroup]}`, `FutureGroup = {id (future id), sport{id,name}, league{id,name}, sportsbook{id,name}, market, market_id, future_type, tournament|null, is_live, start_date, odds: [{id, name, selection, normalized_selection, grouping_key|null, is_main, selection_line, player_id, team_id, timestamp, price, points, deep_link?, source_ids?, limits?}]}` — *"The selections that changed in this delta."* [DOC; no live events captured].

## 3.9 Results entities

**`FixtureResult`** (`/fixtures/results`, 12 keys): `sport, league, fixture (BaseFixture), scores, in_play, events, stats, market_stats, sub_scores, extra, retirement_info, last_checked_at`.

- `BaseFixture`: `id, numerical_id, game_id, start_date, home_competitors, away_competitors, home_team_display, away_team_display, status, is_live, season_type, season_year, season_week, venue_name, venue_location, venue_neutral, tournament, tournament_stage`.
- `in_play` (`InplayData`, 18 keys): `period` (str, `"9"`), `period_number` (int), `clock` (str|null; soccer stream showed `"75714"`), `last_play`, `time_min`, `time_sec`, `balls`, `outs`, `strikes`, `runners {first,second,third: {player_id,player_name,team_id}|null}`, `batter`, `pitcher`, `possession` (`"away"`), `down`, `distance_to_go`, `field_position`, `game_score {home:"0", away:"3"}` (tennis points), `is_clock_stopped` (bool).
- `events`: `[TimelineEvent]` — soccer only today: `event_type` (`goal|yellow_card|red_card|substitution`), `period` (`1H, HALF, 2H, END-REG, ET 1H, HALF-ET, ET 2H, END-ET, PENS, END-PENS`), `period_number`, `clock` (`"90+3"`), `seconds_elapsed`, `team` (`home|away`), `player {id,name}`, `goal_type` (`goal|penalty|header|own_goal`), `assists [{id,name}]`, `player_in`, `player_out`. Absent keys are meaningful (omitted, not null). `[]` for other sports.
- `stats`: `{home: [{period: "all"|"period_N", stats: {...}}], away: [...]}` — MLB team has 70 keys (`air_outs, assists, at_bats, … runs_batted_in, … wild_pitches`); values may be strings for combined stats (`"1-4"`). Legacy keys on older fixtures (`rbi`, `starter`, `pitch_count`).
- `market_stats`: `{home: {...}, away: {...}}` pre-computed market keys — MLB: `1st_3_innings_team_total, 1st_7_innings_team_total, 1st_half_team_total, 1st_inning_team_total … 9th_inning_team_total, team_total, team_total_bases, …`; tennis stream: `{"home":{"team_total":0},"away":{"team_total":0}}`. Keys contain `+` (`player_points_+_rebounds_+_assists`).
- `sub_scores`: `[{period, scores: [{home, away, description}]}]`|null. `extra`: `{decision, decision_method, duration, toss_decision, attendance, capacity}`. `retirement_info`: `{winner, winner_team_id, walkover}`|null. `last_checked_at`: ISO µs `Z` (`2026-09-03T07:25:06.944629Z` — still polled ~8 h after completion).

**`FixturePlayerResults`** (`/fixtures/player-results`): `{sport, league, fixture, results: [PlayerResult]}`; `PlayerResult = {player: BasePlayer, team: BaseTeam|null, status ("completed"|"live"), stats: [{period, stats{}}], market_stats {player_outs, player_pitches_thrown, player_strikeouts, …}, is_starter bool}`. MLB pitcher stats keys include `blown_saves, holds, losses, wins, innings_pitched, pitches, strikes, balls, batters_faced …`.

**`/fixtures/player-results/last-x`** live shape (differs from OpenAPI): `{sport, league, player, team, stats: {stat_key: [per-game values…]}, market_stats: {player_bases: [5,4,4,…], …}, is_starter: [true, …]}` — arrays without per-game fixture ids/dates.

**`TournamentResult`** (`/tournaments/results`): `{id: "golf_pga_0d9c9ccc70bf_summary", numerical_id, sport, league, tournament: TournamentExtended, leaderboard: [{tied, score, rounds: [{pars, thru, score, bogeys, eagles, birdies, strokes, sequence, holes_in_one, other_scores, double_bogeys, double_eagles, triple_bogeys_or_worse}], playoffs, position, player_id, player_name, player_status}], round, stages}` [DOC].

## 3.10 Grader, Injury, Parlay

**`Grader`** (`/grader/odds`, object): `fixture_id, away_team_display, home_team_display, status ("Completed"), away_score, home_score, player_score (number|null), market, name, result, dead_heat_reduction (int|null)`. `result ∈ {Won, Lost, Refunded, Pending, Half Won, Half Lost}`. `FutureGrader` (`/grader/futures`): `tournament_id, tournament_name, status, market, name, result, dead_heat_reduction (number|null)`.

Grader error codes [DOC]: 100 Game not found · 101 Sport not supported · 102 League not supported · 103 Bet type not supported · 104 Game is still live · 105 Tournament not found · 106 Tournament is still live · 107 Game has not started · 108 Game has not completed · 109 Game has been canceled · 201 Score data not found · 202 Incomplete score data · 203 Unsupported bet period · 204 Unsupported spread · 205 Team not in spread · 206 Unsupported over/under · 207 Team not in over/under · 208 Unsupported both teams to score · 209 Unsupported moneyline · 210 Unsupported bet type · 211 Unsupported player name format · 212 Unknown player · 213 Incomplete player data · 214 Unsupported player over/under · 215 Unsupported go the distance · 216 Unsupported total rounds · 217 Tournament leaderboard not found · 218 Match ended in retirement. Payload `{"message": …, "code": N}`.

**`Injury`** (`/injuries`): `id ("baseball:mlb:F3AA22663947"), player: BasePlayer, team: BaseTeam, status, type, sport, league`. Live `status` values: `il_60-day`, `il_7-day`, `out`, `suspended` (doc examples: `Day-To-Day`, `10-Day IL`, `Out`, `Paternity` — casing differs [LIVE≠DOC]); `type` free text (`Personal`, `Knee`, `Illness`, …). No timestamps.

**`InjuryPrediction`** (`/injuries/predictions`): `player, team, data {predicted_status ("healthy"), total_games, games_with_player, games_without_player, wins_with_player, wins_without_player, win_rate_with_player, win_rate_without_player, win_rate_improvement, point_diff_with_player, point_diff_without_player, point_diff_improvement, point_diff_with_player_on_wins, point_diff_with_player_on_losses, point_diff_without_player_on_wins, point_diff_without_player_on_losses, player_impact_score}, sport, league`.

**Parlay response** `{"data": {<Sportsbook name>: {error: str|null, missing_entries: [Leg]|null, legs: [Leg]|null, price: number|null, deep_link_urls: {desktop, ios|mobile}|null}}}`, `Leg = {fixture_id, market, name, price}`. Live: `"DraftKings": {"error":null,"missing_entries":null,"legs":[{"fixture_id":"202609038C03FC15","market":"Moneyline","name":"Toronto Blue Jays","price":-112.0},{…"Total Runs","Over 8",-105.0}],"price":242.0,"deep_link_urls":{"desktop":"https://sportsbook.draftkings.com/event/34608985?outcomes=0ML86128749_3+0OU86128749O800_1","ios":"…"}}`; `"Novig": {"error":"Missing odds for entries.","missing_entries":[{…"Over 8","price":null}],…}`. Doc gotcha: requested `Bwin` came back keyed `"Blue Book"`; `OpticOdds AI` legs may carry sport-prefixed fixture ids (`mlb:3D5E0C0B1E12`).

## 3.11 Prediction-market entities (non-sport)

**`PredictionCanonicalEventData`**: `canonical_id, title ("IL-11 House Election Winner"), description (multi-line resolution text), category ("politics"), events: [{platform ("kalshi"|"polymarket"), source_event_id ("KXHOUSERACE-IL11-26" / "191455"), confidence (0.92 / 1.0; nullable), markets: [{canonical_market_id, source_market_id ("KXHOUSERACE-IL11-26-D" / "1283400"), question ("Will Democratic win the House race for IL-11? — Bill Foster")}]}]`. `question` **is present live** (doc examples omit it). Join Kalshi↔Polymarket on `canonical_market_id` (Polymarket market order differs from Kalshi's).

**`PredictionMarketStreamSnapshot`** (SSE `snapshot`): `{type: "snapshot", entry_id: "" | "<ms>-<seq>", data: {market_id, platform, source_market_id, source_event_id, outcomes: {yes: Quote, no: Quote} (doc: keyed by clobTokenId for Polymarket), timestamp_ns (int), category, canonical_id ("" when unmatched)}}`; `Quote = {token_id, best_bid, best_ask, spread, last_trade_price, tick_size, bids: [{price,size}] desc, asks: [{price,size}] asc}`. Live Kalshi example: `market_id "kalshi:AMAZONFTC-29DEC31"`, yes `best_bid 0.42 / best_ask 0.48 / spread 0.06`, 19 bid levels down to `{price:0.001,size:23110}`, `last_trade_price 0`, `tick_size 0`, `timestamp_ns 1788418892752000000`. `0` means "not available" for `best_bid/best_ask/last_trade_price/tick_size`.

## 3.12 Enumerations

| Enum | Values | Source |
|---|---|---|
| Fixture `status` | `unplayed`, `live`, `half`, `completed`, `cancelled`, `suspended`, `delayed` [DOC]; live: `unplayed`, `live`, `completed`, `cancelled`, `delayed` (`status=bogus` → 400) | fixtures-lifecycle page; probe |
| Grader `status` | `Completed` (Title case) | |
| Grader `result` | `Won`, `Lost`, `Refunded`, `Pending`, `Half Won`, `Half Lost` (no Void/Push) | settlement rules |
| `future_type` | `TEAM`, `PLAYER`, `UNKNOWN`, `null` | live |
| `odds_format` | `AMERICAN` (default), `DECIMAL`, `PROBABILITY`, `MALAY`, `HONG_KONG`, `INDONESIAN` | |
| `selection_line` | `over`, `under`, `yes`, `no`, correct-score `"3:2"`, `null` | live |
| Injury `status` | `il_60-day`, `il_7-day`, `out`, `suspended` (MLB live); other leagues [UNKNOWN] | |
| PM `category` | `politics, economics, finance, crypto, tech, culture, climate, health, geopolitics, companies, other` | live |
| PM `platform` | `kalshi`, `polymarket` | |
| SSE event names | `connected`, `ping`, `odds`, `locked-odds`, `fixture-status`, `fixture-results`, `futures`, `locked-futures`, `snapshot`, Copilot `copilot-odds`/`copilot-locked-odds`/`copilot-settled-odds` | |
| Cancellation reasons (lifecycle) | `never_started`, `teams_change`, `start_date_change` | settlement page (field not observed) |

## 3.13 Timestamps & clock semantics

| Field | Format | Clock meaning |
|---|---|---|
| Odd `timestamp` (REST, SSE, futures) | float Unix **seconds** (`1788420167.231546`) | when OpticOdds last detected a price/points change for that selection (*"we only update /fixtures/odds when we notice a change in price or in points"*) |
| Historical `entries[].timestamp` | **int** Unix seconds (`1788286434`) | change detection time |
| `/sportsbooks/last-polled` `timestamp` | int Unix seconds (`1788420426`) | last poll that returned ≥1 valid odd for the scope |
| `x-ratelimit-reset` | int Unix seconds, multiple of 15 | window end |
| `start_date`, `updated_at`, `last_checked_at`, tournament dates | ISO 8601; REST uses `Z` (`2026-08-31T22:05:00Z`, `2026-09-03T07:25:06.944629Z`), stream payloads use `+00:00` (`2026-09-03T06:35:00+00:00`) | UTC. FAQ warns *"The timezone may be UTC (±0) or UTC-5"* — always parse the offset. |
| SSE `ping` data | `2026-09-03T07:29:41Z` (1 s granularity; doc also shows `2023-02-22 16:30:08.952760`) | server wall clock, every 5 s; measured local−server offset ≈ +0.7 s |
| SSE `entry_id` | `<epoch_ms>-<seq>` | server enqueue time in ms |
| `fixture-status.timestamp` | float seconds (`1724871720.2406485`) | |
| PM `timestamp_ns` | int nanoseconds (`1788418892752000000`, ms precision ×1e6) | book capture time; **Kalshi values are 0 or hour-rounded** (p90 2,046 s old) while Polymarket is fresh (median 0.3 s) |
| Copilot `settled_at` | naive ISO (`2025-09-14T23:24:22.012`) | assume UTC |
| Copilot stub `updated_at` | `0001-01-01T00:00:00Z` | sentinel for "never" |
| `season_year`/`season_week` | strings | labels, not dates |
| date-only `start_date` filter | `YYYY-MM-DD` interpreted in **EST** | |

---

# 4. Streaming (Server-Sent Events)

## 4.1 Protocol summary

- Plain HTTP GET, `Accept: text/event-stream`; response `HTTP/2 200`, `content-type: text/event-stream`, `cache-control: no-cache`, `vary: Accept-Encoding`, no `x-ratelimit-*` headers, no `content-encoding` (uncompressed) [LIVE]. No WebSockets, no webhooks (*"we provide a Server-Sent Events (SSE) streaming endpoint"*).
- Auth: `X-Api-Key` header or `?key=`. Missing `sportsbook` on `/stream/odds` → `HTTP 400 text/plain` `At least 1 sportsbook must be provided.`
- Wire frames (exact):

```
event: connected
retry: 5000
data: ok go

event: ping
retry: 5000
data: 2026-09-03T07:29:41Z

event: odds
id: 1788420576710-0
retry: 5000
data: {"entry_id":"1788420576710-0","type":"odds","data":[{...odd...},{...odd...}]}

event: locked-odds
id: 1788420577299-0
retry: 5000
data: {"entry_id":"1788420577299-0","type":"locked-odds","data":[{...odd...}]}
```

- Every event carries `retry: 5000` (client auto-reconnect delay 5 s). `ping` arrives **every 5 s** (observed 07:29:41, :46, :51 …) on every stream incl. idle ones; use it as the liveness watchdog (PM guide: *"If no ping or snapshot arrives for ~15 seconds, drop the connection and reconnect"*).
- Connect latency 0.33 s; first data event 1.0 s after connect (baseball). [LIVE]
- Each connect (including reconnects) counts against the streaming bucket (250 / 15 s [DOC]).

## 4.2 `GET /stream/odds/{sport}`

Params: path `sport` (id, e.g. `baseball`, `soccer`, `football`, `politics`); `sportsbook[]` (**required**, ≤5), `league[]` (default all leagues of the sport; *"up to 10 leagues per connection"*), `fixture_id[]`, `market[]` (names or ids), `is_main` (`true` main only / `false` alternates only / unset all), `is_live` (`true` live only / `false` pre-match only / unset both), `odds_format`, `exclude_fees` (default false), `last_entry_id`, `include_fixture_updates` (default false → `fixture-status` events), `include_deep_link` (default false). `include_source_ids` / `include_limits` are **not** parameters here — `source_ids`, `limits`, `order_book` are emitted by default for exchanges [LIVE].

Event types and payloads:

| event | `data` | Meaning (doc wording) | Observed |
|---|---|---|---|
| `odds` | `{entry_id, type:"odds", data:[Odd…]}` | *"Fired when an odd is posted for the first time or unsuspended with a new price."* / OpenAPI: *"If an odd gets changed or added."* | 691 events / 45 s baseball; batches of many odds sharing one `timestamp` (Polymarket player-bases batch, all `1788420576.6929715`) |
| `locked-odds` | same shape, `type:"locked-odds"` | *"Fired when an odd is suspended (temporarily unavailable) or taken off the board. The data format is identical to odds events — the last known price is included."* | 18 / 45 s baseball, 1 / 300-line soccer sample |
| `fixture-status` | `{entry_id, data:{fixture_id, game_id, sport, league, old_status, new_status, old_start_date, new_start_date, fixture:{id, game_id, home_team_display, away_team_display, start_date}, timestamp}}` — **`data` is an object, not an array**; OpenAPI nests `data.data` (doc bug) | status or start-time change; requires `include_fixture_updates=true` | **0 observed** in 45 s baseball + soccer captures with the flag on [UNKNOWN cadence] |
| `connected`, `ping` | `ok go` / ISO time | | every stream |

Odd record: the 27-key object of §3.6. Both `event`-line name and payload `type` identify the event; the `id:` line equals payload `entry_id`.

Main-line movement semantics (reference page, exact cases):
- **Case 1 — main moves, no alternates:** `locked-odds` for the old main (both sides) then `odds` for the new main. With `is_main=false` you receive nothing.
- **Case 2 — main moves, alternates exist:** only `odds` events with updated `is_main` flags; **no `locked-odds`** for the demoted line (*"they just changed roles"*). With `is_main=true` the old main *"simply disappears from your is_main=true view"*.
- Recommendation (doc): *"leave is_main unset and track the is_main flag on each selection in your local state."* Absence in REST = suspended; in the stream only `locked-odds` signals suspension.

Observed stream composition [LIVE, 07:30Z, low season]:

| Stream | Filters | Events/s | Records/s | Bytes/45 s | Notes |
|---|---|---|---|---|---|
| `/stream/odds/baseball` | DK, FD, Pinnacle, Polymarket, Novig, all leagues, `include_fixture_updates=true` | 15.8 | 223 | 8.1 MB | 81 % of records Polymarket; 49 % `is_live=true` |
| `/stream/odds/soccer` | Pinnacle, bet365, Betfair Exchange, Polymarket, DK, all leagues, `include_deep_link=true` | 313 | **1,544** | **67.8 MB** (≈1.5 MB/s) | one connection cannot be filtered below the sport without `league[]`/`market[]` |
| `/stream/odds/soccer` | same books, `is_main=true`, `market=Moneyline,Total Goals,Asian Handicap` (20 s) | 48 | 73 | – | filtering works |
| `/stream/odds/baseball` | `sportsbook=kalshi` only | events flowing (run line, HR yes/no, player props with 10-level books) | | | Kalshi delivers depth in-stream |
| `/stream/odds/football`, `/stream/odds/soccer` | `sportsbook=kalshi` only | 0 events / 12 s | | | no Kalshi NFL/EPL odds at the time |
| `/stream/odds/politics` | Kalshi + Polymarket | **0 events / 15 s** | | | non-sport PM content is not on the sports stream — use `/stream/prediction-markets` |

## 4.3 `GET /stream/results/{sport}`

Params: path `sport`; `league[]`, `fixture_id[]` (no `sportsbook`, no `last_entry_id` in OpenAPI). Doc best practice (differs from odds): *"we recommend making a separate connection for each league you are trying to subscribe to."*

Event `fixture-results`: `{entry_id, data: {fixture_id, sport, league (display name, e.g. "ATP Challenger"), is_live, status, score: FixtureResult (sport, league{id,name,numerical_id}, fixture, scores, in_play, events, stats, market_stats, sub_scores, extra, retirement_info), player_results: [PlayerResult]}}`. Live tennis example: `entry_id "1788420802097-0"`, `in_play {"period":"1","period_number":1,"game_score":{"home":"0","away":"3"},"possession":"away","is_clock_stopped":false,…}`, `market_stats {"home":{"team_total":0},"away":{"team_total":0}}`, 2 stat periods (`all`, `period_1`) with tennis keys (`aces`, `double_faults`, `break_points_won`, `max_games_in_a_row`, `max_points_in_a_row`, …), `player_results[].market_stats` (`player_aces`, `player_games_won`, `1st_set_player_aces`, `player_aces_+_double_faults`, …). `start_date` uses `+00:00`.

Observed: tennis 11 `fixture-results` / 30 s (11 live matches); baseball 0 events in 2 × 30 s (no live games at 07:30Z); soccer emitted **one stale event** for fixture `2026071228D5BE8F` (status `unplayed`, start `2026-07-12T17:45:00+00:00`, `in_play.period "0"`, `clock "75714"`, `is_clock_stopped true`) — filter results events by `status`/`start_date` sanity, never trust them as "live".

## 4.4 `GET /stream/futures/{sport}`

Params in §2.10; `include_limits`, `include_source_ids`, `include_deep_link` accepted. Events `futures` / `locked-futures` with `FutureGroup` deltas (§3.8). **Live: 0 data events** in 30 s (football, DK/FD/Pinnacle/Caesars/Polymarket), 60 s (football, DK/FD/Caesars/BetMGM/Novig) and 30 s (baseball, DK/FD/Caesars/BetMGM/Kalshi) — futures move rarely; poll `/futures/odds` instead (§10). Whether `last_entry_id` is honoured is moot (see §4.6).

## 4.5 `GET /stream/prediction-markets`

Params: `category` (**required, exactly one; a repeated key keeps the last value**), `platform[]` (`kalshi`|`polymarket`; live `platform=kalshi` filter works), `source_event_id[]`, `source_market_id[]`, `canonical_id[]` (OpenAPI only, untested). Invalid category → HTTP 400 with the JSON list of valid categories (§1.6).

Lifecycle [DOC]+[LIVE]: `connected` → **bootstrap**: one `snapshot` per market matching the filters, with `entry_id: ""` and **no `id:` line** (2,018 bootstrap snapshots in 15 s on `category=politics&platform=kalshi`; the retained 300-line captures are bootstrap-only) → steady state: one `snapshot` every time a market's book changes → `ping` every 5 s. The probe's full 45 s politics run (120 MB, not retained on disk) reported **933 snapshots/s**, `entry_id` empty on 3.5 % (politics) / 45 % (crypto) of events (post-bootstrap events therefore do carry `<ms>-<seq>` ids, matching the OpenAPI example `1756155000456-0`), per-market inter-arrival median 0.9 s (p90 13 s), only 2.7 % of consecutive same-market snapshots identical (effectively change-driven), `canonical_id` populated on 95 % of politics snapshots (641 / 2,018 in the retained Kalshi-only bootstrap; 0 / 74 in crypto). **[LIVE≠DOC]**: the Aug-26 reference says *"The stream's canonical_id field is not populated"* — it usually is, but do not depend on it: keep the REST `canonical-events` join.

Payload (§3.11). Semantics [DOC]: *"The payload is the complete current order book for one market — it replaces any prior state you hold for that market_id"*; *"This stream has no replay. entry_id is empty and there is no last_entry_id parameter"*; *"Field order within objects is not guaranteed"*; *"a busy category can emit thousands of snapshots per second"*. Prices are `0–1` dollars per contract (≈ probability), `yes`/`no` books mirror each other (`no.best_bid = 1 − yes.best_ask`). Sizes are contracts (fractional). No `exclude_fees` / `odds_format` on this stream.

Observed sizes: politics 120.7 MB / 45 s; crypto 16.9 MB / 15 s (514 snapshots/s); Kalshi-only politics 2.86 MB / 15 s (134/s). One Kalshi politics book had 19 bid + 18 ask levels.

## 4.6 Ordering, cursor, resume, replay — **`last_entry_id` replay does not work**

Docs (SSE guide, verbatim): *"Every odds, locked-odds, and fixture-status event includes an entry_id. This is a monotonically increasing identifier. When you reconnect, pass the last entry_id you processed … The server will replay any events you missed since that ID, then continue streaming live updates. This gives you exactly-once delivery — no gaps, no duplicates."* Replay window length is not documented.

Live tests [LIVE≠DOC], all on `/stream/odds/{sport}` with identical filters:

| Test | Gap | `last_entry_id` passed | First event after reconnect | Result |
|---|---|---|---|---|
| baseball, 5 books (45 s run) | resume opened ≈53 s after the original stream's first event | `1788420576710-0` (= 07:29:36.7Z, first id of the original stream) | `1788420630242-0` (= 07:30:30.2Z, i.e. the connect time; nothing from the intervening 53 s) | no replay |
| soccer main lines, resume A→B | 6 s | A's last id | B.first − A.last = **6,491 ms** | no replay |
| soccer, resume C | 2 s | bogus `0-0` | accepted, stream starts at "now" | no error, no replay |
| soccer, resume D | – | id 10 minutes old | accepted, starts at "now" | no replay |
| baseball Polymarket/Novig/Pinnacle, replay A→B | 2 s | `1788421068004-0` | `1788421078952-0` (+10,948 ms) | no replay |

Additional ordering facts: `entry_id` was strictly increasing on the baseball and PM streams, but the soccer stream produced **2 out-of-order and 2 duplicate ids** in 45 s → dedupe on `entry_id` (and on odd `id`+`timestamp`), never assume monotonic. A reconnect therefore always creates a gap; the only recovery is REST re-hydration (§10).

## 4.7 Heartbeat, disconnect, close semantics

- Heartbeat: `ping` every 5 s with server time; treat >15 s silence as dead. Doc client examples catch `requests.exceptions.ChunkedEncodingError` and reconnect with exponential backoff 1 s → 60 s cap (`sseclient-py`, not `sseclient`; Node `eventsource`).
- No documented server-side idle timeout, max connection lifetime, or close reason; none was hit in ≤60 s captures [UNKNOWN].
- Errors are HTTP-level at connect time (400 text/plain or JSON); once connected there is no in-band error event documented.
- The doc's `retry: 5000` implies ≥5 s before auto-reconnect; the streaming rate bucket (250 / 15 s) bounds reconnect storms — *"If you're consistently above 200/15s, restructure"*; *"stagger startup (20+ streams)"*.

## 4.8 Compression

None observed (`vary: Accept-Encoding` but no `content-encoding` on SSE; the probe client did not send `Accept-Encoding`). Whether the edge gzips SSE when asked is [UNKNOWN] — test with `Accept-Encoding: gzip`; plan capacity for the raw sizes above (soccer all-leagues ≈ 1.5 MB/s).

## 4.9 Connection budgeting (doc guidance + live)

| Constraint | Value |
|---|---|
| books per odds/futures stream | ≤5 (`sportsbook[]`) |
| leagues per odds/futures stream | ≤10 recommended |
| results streams | one per league recommended |
| PM streams | one per category (11 categories), optional `platform` split |
| new connections | 250 / 15 s incl. reconnects |
| Copilot RabbitMQ | 20 connections (n/a) |

Example topology for our universe (§10): per sport × 5-book bundles × ≤10 leagues; e.g. baseball (mlb, kbo, npb, cpbl, mexico_-_lmb) × {DK, FD, Pinnacle, Polymarket, Novig} + {Kalshi, Caesars, BetMGM, bet365, Betfair Exchange} + {Circa Sports, BetOnline, Prophet X, Fliff, Betfair Exchange (Lay)} = 3 connections per sport-bundle.

---

# 5. Historical data

## 5.1 Endpoints, depth, retention

| Data | Endpoint | Doc statement | Observed depth [LIVE] |
|---|---|---|---|
| Pre-match odds ticks (`entries`) | `GET /fixtures/odds/historical … include_timeseries=true` (requires `market`) | *"This data is available only from the time odds are posted by the sportsbook up until just before the fixture start time. Historical data is retained on a rolling 2-month basis."* | present at 2.3 d (82 entries), 2.4 d (186), 33 d (1,135 across DK/Pinnacle/Polymarket/Novig/Betfair), 36 d (28), 43 d (21), **57 d (24 entries)**; **empty at 60 d** (`202607045BEA733B`, 2026-07-05) and 94 d → retention edge between 57 and 60 days |
| Opening / closing line (`olv`/`clv`) | same endpoint (no timeseries needed) | not stated | present at 60 d, 94 d and **1 year** (`mlb:2DACEC7C8AE9`, 2025-09-01: DK ML olv `102`, clv `-109`) |
| CLV availability lag | | not stated | `clv: null` ~8 h after a completed game (`20260902FF9AD242`, start 2026-09-02T23:40Z, probed 07:25Z; olv present for DK/FD/Pinnacle); **populated by ~2.3 days** (`202609011B4EAE85`) |
| Fixtures (schedule + result) | `GET /fixtures?start_date=…` | *"supports all fixtures from the past"* | 60 d (22 rows with `result`), 94 d (6), 1 y (12, legacy ids) |
| Results / player results | `GET /fixtures/results`, `/fixtures/player-results` | | 60 d and 1 y old fixtures returned (`results_2025`, `player_results_2025`) |
| Grader | `GET /grader/odds` | | works on 60 d old fixture |
| Non-sport PM order books | none | *"No historical/backfill endpoint for non-sport order books is documented"* | must be recorded from the stream |
| Copilot audit trail | `/copilot/fixtures/odds/historical` (≤10 ids, newest first, events `copilot-odds`/`copilot-locked-odds`/`copilot-settled-odds`) | | n/a (no Copilot) |

## 5.2 Granularity and coverage of the timeseries

- Entries are **change-detections per odd**, not a sampled grid: DK + Pinnacle MLB moneyline = 117 entries over 4 odds (DK 18/19, Pinnacle 39/41), **minimum gap 1 s, median 358 s**; Betfair/Novig/Polymarket produce 86–239 entries per selection on a single MLB ML; Polymarket's first entry 6.45 days before start (`1784985871` vs start `1785543300`); DK's last entry **274 s after** `start_date` (`1785543574`) — "just before the fixture start time" is approximate; entries do not continue in-play.
- `olv` = first entry; `clv` = last entry before close once the closing job runs. For Polymarket the opening `olv` was `-3403` (an illiquid first quote) — use size-aware openers from the tape rather than `olv` for exchanges.
- Main-line rows (`is_main=true`) drop the points from the id and carry them inside `olv`/`clv`/`entries[].points` — the row `…:total_runs:over` can change points over time (doc: *"the name field might not correspond to a name that was returned from the /fixtures/odds endpoint since the bet points could change"*).
- `include_locked=true` returned 0 locked entries in 446 — lock history may not be retained on this key [UNKNOWN].
- Volumes: one fixture × DraftKings, no market filter = 4,180 odds / 1.86 MB / 1.0 s; `is_main=true` = 1,636 odds / 0.7 MB; single market with timeseries ≤ 80 KB. The historical bucket (50 / 15 s) allows ≈ 3.3 fixture-market pulls per second.

## 5.3 What must be recorded ourselves

In-play price history, exchange depth history, `locked-odds` history, non-sport PM books, per-book poll staleness — none of these are retrievable retroactively. The SSE tape is the only source; archive raw events (§10).

---

# 6. Cross-provider identifiers present

| Field (location) | Refers to | Real example | Coverage / notes |
|---|---|---|---|
| `Fixture.id` | OddsPapi `fixtures[].externalProviders.opticoddsId` | OpticOdds `2026090552B5D9A7` ↔ OddsPapi `id1000001772221244` (Ipswich–Liverpool) | Cross probe 2026-09-03: MLB 40/40, EPL 8/8, NCAAF 114/125 matched; start times identical. 2,593 of 19,954 OddsPapi fixtures carried an `opticoddsId`. |
| `Fixture.game_id` | SharpSports `events[].oddsjamId` | `36707-80389-2026-09-03-09` | MLB 37/40 exact; WNBA/MLS SharpSports ids exist (`33857-26091-2026-09-24`) but no OpticOdds fixtures in window. |
| `source_ids.statsperform_id` (fixtures, teams, players; `include_statsperform_id=true`) | Stats Perform / Opta | fixture `"2986833"`, team `"253"`, player `"1228903"` | MLB/NFL/EPL/MLS/WNBA 100 %, NCAAF 86–94 %, tennis `""`. Soccer stat keys (`total_scoring_att`, `ppda`, `big_chance_created`) confirm Opta provenance. |
| `home_rotation_number` / `away_rotation_number` | US rotation numbers (Don Best / Vegas) | MLB `902/901`, EPL `810052/200081`, ATP `201008/8113` | OddsPapi carries `participant1RotNr`/`participant2RotNr` (`792/793` for the same EPL game — **different numbering scheme**, not joinable directly). |
| Odd `source_ids` (Kalshi) | Kalshi market ticker + side | `{"market_id":"KXMLBTB-26SEP031235SFPIT-PITOCRUZ15-5","selection_id":"no"}` | order routing |
| Odd `source_ids` (Polymarket) | CLOB token id | `{"selection_id":"44931878938656278363269178910047211874481075822738063439341755107592295768730"}` | condition id not given; deep link has `marketSlug` |
| Odd `source_ids` (Betfair) | Betfair event / market / runner | `{"event_id":"36025366","market_id":"1.261950049","selection_id":"7017905"}` | |
| Odd `source_ids` (Novig, Prophet X, BetOnline) | native ids | Novig uuids; Prophet X `{"event_id":"19457","selection_id":"8b2d…"}`; BetOnline `{"event_id":"491119366"}` | |
| `deep_link` URLs | book-native event ids | DraftKings event `34608984`, Pinnacle event `1634922658`, Fliff `412083_c_p_203_prematch`, Kalshi ticker, Betfair event `36025366` | Pinnacle event id family matches OddsPapi `externalProviders.pinnacleId` (`1634444777` for the EPL game) — candidate secondary join [UNKNOWN, not verified on the same fixture] |
| PM `events[].source_event_id`, `markets[].source_market_id` | Kalshi tickers / Polymarket numeric ids | `KXHOUSERACE-IL11-26` / `KXHOUSERACE-IL11-26-D`; `191455` / `1283400` | non-sport only |
| `canonical_id`, `canonical_market_id` | OpticOdds-internal cross-platform ids | `0084abc100ac5f34988afb271ce21392` | |
| `extra.source` (results queue messages) | upstream score vendor | `"sofascore"` | Copilot/queue payload only [DOC] |
| Logo URLs | `cdn.oddsjam.com`, `a.espncdn.com` | | OddsJam lineage |
| Sportsbook ids ↔ other providers | see cross probe | `pinnacle`↔OddsPapi `pinnacle`; `circa_sports`↔`circasports`; `betonline`↔`betonline.ag`; `bookmaker`↔`bookmaker.eu`; `prophet_x`↔`prophetx`; SharpSports abbr `kalshi:kl, polymarket:pm, draftkings:dk, fanduel:fd, betmgm:mg, betrivers:br, caesars:ca, fanatics:fn, fliff:fl, prizepicks:pp, sleeper:sl, sporttrade:st, thescore:bs, hardrock:hr, underdog:ud` | books in all three feeds: betmgm, betrivers, draftkings, fanduel, kalshi, polymarket |

No `sportradar`/`betradar`/`flashscore`/`theoddsapi` identifiers exist anywhere in OpticOdds.

---

# 7. Latency, freshness, and staleness semantics

## 7.1 The clocks on a quote

| Clock | Where | Meaning |
|---|---|---|
| `timestamp` (float s) on every odd | REST `/fixtures/odds`, SSE `odds`/`locked-odds`, futures | *"When this price was last updated"* / stream guide: *"Unix timestamp of when this price was posted"* / last-polled page: *"we only update /fixtures/odds when we notice a change in price or in points"* → **time OpticOdds detected the change**, not the book's own change time. |
| SSE `entry_id` prefix (ms) | stream events | server enqueue time; ≥ odd `timestamp`. |
| SSE `ping` data | stream | server wall clock every 5 s (1 s granularity) → clock-offset estimate (measured ≈ +0.7 s local−server). |
| `/sportsbooks/last-polled` `timestamp` | REST | *"the last time our systems checked for odds update … this is not the same as the timestamp field on the /fixtures/odds endpoint … returns the timestamps we received at least 1 valid odd from the sportsbook"* → **scraper liveness per (league or fixture, book)**. |
| `last_checked_at` | `/fixtures/results` | last time the score record was refreshed (`2026-09-03T07:25:06.944629Z`, ~8 h post-game). |
| `updated_at` | fixtures | last fixture-metadata change. |
| PM `timestamp_ns` | `/stream/prediction-markets` | book capture time; reliable for Polymarket (median 0.3 s old), **unusable for Kalshi** (0 / hour-rounded, p90 2,046 s). |
| Our `recv_ns` | ingestion | arrival time; the only clock we control. |

## 7.2 Observed numbers [LIVE, 2026-09-03 ~07:34Z]

| Metric | Baseball stream (DK, FD, Pinnacle, Polymarket, Novig) | Soccer stream (Pinnacle, bet365, Betfair Ex., Polymarket, DK; main lines) |
|---|---|---|
| `recv − odd.timestamp` p50 | **7 ms** | **32 ms** |
| p90 | 141 ms | 165 ms |
| p99 | 221 ms | 333 ms |
| events / records in 20 s | 555 / 4,989 | 958 / 1,469 |
| connect → first data | 0.33 s + 1.0 s | – |

Interpretation: OpticOdds delivers a change to us within tens of ms of *detecting* it. The unmeasured component is detection lag = book change → OpticOdds poll. Evidence on that component: per-league `last-polled` timestamps cluster within a ~36 s window in the doc example and *"most ~270 s old"* at league scope live for MLB; per-fixture `last-polled` for Kalshi was 12 s old at 07:36Z but 1,595 s old at 07:24Z; `sporttrade` last polled 101 days earlier and `betano_argentina_` 45 days earlier (dead pollers). REST odds bodies contained prices 2–12 s old at the newest and **5–14 h old** at the oldest — stale-but-still-offered lines are returned as-is (no stale flag), so age = `now − timestamp` must be computed by us.

Prediction-market stream: per-market inter-arrival median 0.9 s, p90 13 s; PM REST `include_latencies` reports server compute (`{"total": 0.0616}` s); PM/parlay backend exposes `x-latency-time` (SGP pricing 1.94 s).

REST latencies [LIVE]: discovery endpoints 0.15–0.24 s; `/fixtures/odds` 0.15–0.47 s (up to 3.7 s for a Kalshi/Polymarket-only call); `/fixtures/odds/historical` 0.2–2.5 s; `/futures?league=mlb` 1.9 s once; `/fixtures` 0.2–1.7 s.

## 7.3 Recommended per-quote latency estimator

```
detect_lag_upper  = odd.timestamp − last_polled[book, fixture].timestamp   (only meaningful if ≤ poll period; else book idle)
delivery_lag      = recv_ns/1e9 − odd.timestamp − clock_offset             (clock_offset from ping: recv − ping_time, median)
quote_age         = now − odd.timestamp                                   (for REST snapshots and for stale-line filtering)
book_liveness_age = now − last_polled[book, league|fixture].timestamp      (scraper dead if ≫ typical; MLB typical ≤ 5 min at league scope)
```
Flag a quote **stale** if `book_liveness_age` > 2× the book's typical poll gap or `quote_age` exceeds a market-specific threshold; flag **suspended** if absent from the latest REST snapshot or a `locked-odds` arrived after the last `odds` for that `id`. For exchanges compare `timestamp` against the PM stream/Polymarket book to detect a lagging sports poller (Polymarket sports odds arrive via polling, not via the CLOB websocket).

## 7.4 Doc language on freshness (verbatim)

- SSE guide: *"When an odd changes, a line gets suspended, or a game score updates, you receive the event within milliseconds."*
- *"Don't poll when you can stream … Switch to /stream/odds for anything requiring sub-minute freshness."*
- PM makers guide on `timestamp`: *"tells you when the exchange last updated. Use this to detect stale quotes."*
- Trading floor: manual re-activation of a fixture *"might take a minute for you to see the data in the API"* (Copilot).
- Grader: *"the default behavior for this endpoint is to wait until the game is completed before returning any results"*; `show_live_result` for provisional grades.

---

# 8. Edge-relevant facts for arbitrage / market making

## 8.1 Liquidity, limits, depth
1. `limits.max` = book max stake where available: **Pinnacle** NFL mains 1,000–15,850 (spread 5,550, ML 5,460, total 3,090/3,390), MLB correct score 250, EPL total 4,200; **BetOnline** 1,620–23,000; DK/FD/Caesars/bet365/BetMGM/Fliff/Circa expose nothing. Sizing input for soft-book legs is therefore only available for Pinnacle/BetOnline-class books.
2. Exchanges: `limits.max` = top-of-book size and `order_book` = one-sided ladder in the requested odds format — Polymarket up to 10 levels (`[[156,25.35],[150,1840.53],[144,2770.53],…]`), Kalshi up to 10 (`[[172,932.76],[164,3745.88],…]`), Novig 1 level, Prophet X 1 level, Betfair Exchange **no ladder** on the back book (`order_book: null`, `limits.max` = available at best). The lay side is a separate "sportsbook" (`betfair_exchange_lay_`, `betfair_exchange_australia_lay_`). For Kalshi/Polymarket the opposite side is the complementary selection (`selection_id: no`).
3. Non-sport PM stream gives **full two-sided depth** (bids + asks, up to ~19 levels, fractional sizes) for every Kalshi/Polymarket market in a category, refreshed on every change → cross-venue yes/no arb (`yes_ask_A + no_ask_B < 1`) and intra-venue (`yes_ask + no_ask < 1`) with executable size = min level size, joined on `canonical_market_id` (gate `confidence ≥ 0.95`).
4. **Fee semantics**: by default Polymarket/Kalshi `price` is fee-adjusted and can differ from `order_book[0][0]` (Polymarket `-10421` vs `-9900`; `148` vs `156`); with `exclude_fees=true` `price == order_book[0][0]` (Kalshi `1.075`). Doc: *"By default, OpticOdds includes fee adjustments in the returned odds … Always request raw prices and apply your own fee model."* Novig is vig-free (`614 == [[614,294]]`).

## 8.2 Sharp reference and line origin
5. Sharp books available with ids: `pinnacle` (active, `is_onshore:false`), `circa_sports`, `circa_vegas`, `betonline`, `bookmaker`, `betcris`, `ps3838` (inactive), plus exchanges. Pinnacle covered only 7 of 82 upcoming MLB fixtures and 2 of 3 probed same-day fixtures — coverage starts close to game time; poll `/fixtures/active?league=…&sportsbook=pinnacle` to know when.
6. `/markets` (with `markets_only=false`) yields the market × league × book coverage matrix; `/markets/active?fixture_id&sportsbook` (≤5 books) tells which markets a book is quoting **now** (MLB fixture: 67 across 5 books, 19 on Kalshi) — use it to prune subscriptions and to detect a book pulling a market.
7. `grouping_key` pairs both sides of a line (`default:8.5`, `rafael_devers:2.5`, `cal_raleigh`) → per-line devig; `normalized_selection` + `market_id` + `points` is the cross-book outcome key; `is_main` marks the consensus line per book.
8. The docs' own consensus recipe (Copilot, not licensed but reproducible): multiplicative devig per book → weighted average with mandatory/optional books and `minimum_providers ≥ 2` → re-apply vig → hysteresis `abs(old_p − new_p) ≥ min_difference` (probability points) → clamp/suspend outside [min, max]. Operators running Copilot publish prices that lag consensus by up to `min_difference` — exploitable.
9. SGP pricer returns correlated per-book prices: DK SGP (ML −112 & O8 −105) = **+242** vs independent +282; cross-game DK +343 = independent product exactly. `OpticOdds AI` sportsbook option gives a consensus SGP price (needs `price_american`/`price_decimal` per leg; `allow_negative_correlation` toggle).

## 8.3 Suspension / hard stops
10. REST: *"if an odd is not returned then it is for all intents and purposes suspended"* — no suspended flag; diff snapshots. Stream: `locked-odds` carries the last price (18 in 45 s of baseball; 1 in the soccer sample). Main-line promotion with alternates emits **no lock** — track `is_main` per selection.
11. Fixture status transitions (`fixture-status` events; enum incl. `delayed`, `suspended`, `half`) and `is_live` per odd (49 % of baseball stream records were in-play) let you split pre-match and in-play regimes; the PM makers guide: *"exchange order books often thin out and spreads widen"* on `is_live` transitions.
12. Poller death is silent: `sporttrade` (inactive, last poll 101 d), `betano_argentina_` (45 d), Kalshi 26 min stale at 07:24Z. Gate every arb leg on `/sportsbooks/last-polled` age (≤5 books, ≤5 fixtures per call; standard bucket).

## 8.4 Opening / closing / CLV
13. `/fixtures/odds/historical` gives `olv`/`clv` per odd for ≥1 year and change-level ticks for ~57 days (pre-match only, 1 s resolution, median 6 min apart on MLB ML). `clv` is filled ~2 days after the game (null at 8 h) — compute our own close from the tape for same-day CLV. Polymarket `olv` can be a nonsense first quote (`-3403`); use size-weighted openers.
14. Futures: `/futures/odds` per-selection `timestamp` differs within a market (each selection's own last change); Kalshi NFL futures (475 odds incl. Super Bowl Winner, MVP) vs DK/FD/Caesars/BetMGM/Novig/bet365 — long-dated cross-venue mispricing surface; futures streams are near-silent so poll.

## 8.5 Settlement timing & grading
15. Grader settles per fixture completion (*"A market settles once the fixture is marked completed"*), results `Won/Lost/Refunded/Half Won/Half Lost/Pending`; ties on 2-way = Refunded; 3-way spread push on the favoured side = **Lost**; tennis/badminton retirement → moneyline settles on the progressing player (many books void); soccer substitute who scores → **Refunded**; baseball has **no 5-inning official-game rule**, 48 h resume rule for started games, `start_date_change` cancels pre-live; delayed auto-cancel 24 h default / 36 h tennis / 120 h football; dead-heat reduction emitted only for golf/motorsport (`dead_heat_reduction` = tied count). These rules diverge from book house rules — model per book when using OpticOdds grading as settlement truth.
16. Golf `To Make The Cut` / `End Of Round N Leader` settle early (while live); NBA Summer League complete-only; MMA only Completed/Cancelled proceed.
17. `market_stats` (pre-computed `player_points_+_rebounds_+_assists`, `team_total_corners`, `1st_inning_team_total`, …) plus `is_starter`/`batting_order` in player results = direct prop settlement values and lineup confirmation; soccer `events[]` carry `seconds_elapsed` goal/card/sub timing for suspension-latency analytics.

## 8.6 Latency edges
18. Delivery p50 7–32 ms after OpticOdds detection; book-side detection lag is the unknown and varies by book (per-fixture `last-polled` 12 s for Kalshi vs minutes at league scope). Kalshi sports books arrive with 10-level depth in-stream; Polymarket sports depth via polling; non-sport PM via a change-driven snapshot firehose (933/s politics).
19. `/injuries` (paginated, no timestamps — diff polls), `/injuries/predictions` (impact model), `home_starter`/`lineups` on fixtures are the pre-game catalysts available on this key; RotoWire (not ours) is the vendor's recommended news feed.
20. Streams batch all lines of a book/market update into one event with one `timestamp` — the batch itself is a signal of a book-side repricing pass.

---

# 9. Gotchas, doc-vs-live contradictions, open questions

## 9.1 Resolved by the probe

| # | Topic | Doc says | Live | Status |
|---|---|---|---|---|
| 1 | Standard rate limit | 2,500 / 15 s | `x-ratelimit-limit: 8000` | **resolved** (plan on 8,000; keep a 2,400 safety default configurable) |
| 2 | Historical rate limit | 10 / 15 s | `x-ratelimit-limit: 50`, separate counter | resolved |
| 3 | `last_entry_id` replay | *"exactly-once delivery — no gaps, no duplicates"* | no replay in 5 tests; bogus/old ids accepted; soccer stream had duplicate + out-of-order ids | **resolved: do not rely on replay** |
| 4 | Stream path | `/stream/{sport}/odds` (migration page) vs `/stream/odds/{sport}` | `/stream/odds/{sport}` | resolved |
| 5 | `/fixtures/odds` league-wide hydrate (`sport`, `league`, `is_live` in SSE guide) | implied | 400, needs fixture_id/team_id/player_id | resolved: enumerate fixtures first |
| 6 | Deep links | permission-gated | always present on REST; streams need `include_deep_link=true` | resolved |
| 7 | `include_timeseries` | separate permission | entitled | resolved |
| 8 | `include_source_ids`/`include_limits` on `/stream/odds` | not parameters | `source_ids`, `limits`, `order_book` emitted by default for exchanges | resolved |
| 9 | Pagination envelope | `has_more` vs `total_pages` | `{cursor, data, has_more, page}`; page ≥2 drops `cursor`; 100/page; `total_pages` never seen | resolved |
| 10 | `/injuries` pagination | none | paginated (`has_more: true`) | resolved |
| 11 | Sportsbook casing in REST odd ids | `…:BetMGM:…` in example | lowercase slug (`…:betmgm:…`, `…:draftkings:…`) everywhere | resolved: still never join on raw id |
| 12 | `limits` key | `max` (OpenAPI) vs `max_stake` (prose) | `max` only | resolved (accept both) |
| 13 | PM `question` field | in schema, absent from examples | present | resolved |
| 14 | PM stream `canonical_id` | *"not populated"* | populated on most politics snapshots, none on crypto | resolved: optional |
| 15 | PM stream `entry_id` | always `""` (prose) vs `<ms>-<seq>` after bootstrap (OpenAPI) | `""` on bootstrap, ids afterwards (3.5 % / 45 % empty) | resolved |
| 16 | Politics via sports pipeline | PM-makers guide "coming soon" | `/sports/active` excludes politics; `/sportsbooks/active?sport=politics` empty; `/stream/odds/politics` silent | resolved: use `/prediction-markets/*` |
| 17 | Kalshi entitlement | – | yes; zeros were poller staleness | resolved |
| 18 | Fixture id format | 12/16 hex | `YYYYMMDD`+8 hex now, `league:12hex` for 2025, all-digit ids exist | resolved: opaque string |
| 19 | Fixture status filter values | 7 in lifecycle page, 4 in guide | `bogus` → 400; `unplayed/live/completed/cancelled/delayed` seen | mostly resolved (`half`, `suspended` unseen) |
| 20 | Historical retention | *"rolling 2-month basis"* | ticks 57 d yes / 60 d no; OLV/CLV ≥ 1 y | resolved |
| 21 | `exclude_fees` | *"raw exchange prices"* | accepted; `price == order_book[0][0]` only when set | resolved |
| 22 | Unknown sportsbook ids | – | silently ignored (`circa`, `prophetx`, `notabook`) | resolved: validate against `/sportsbooks` |
| 23 | Prose param `show_live_results` | | OpenAPI `show_live_result` | use OpenAPI name |
| 24 | Grader `sport`/`league` params | in example URL, not OpenAPI | `/grader/odds` works without them; `/grader/futures` demands `sport` | resolved |
| 25 | `/parlay/odds` verb | POST | GET → 405 | resolved |
| 26 | Parlay body | `sportsbooks[] + entries[{market,fixture_id,name}]` | confirmed (odd ids rejected) | resolved — note the repo's `OpticOddsClient.parlay_odds` still sends `{sportsbook, odds}` and must be changed |
| 27 | Injury status vocabulary | `Day-To-Day`, `60-Day IL` | `il_60-day`, `il_7-day`, `out`, `suspended` | resolved (lowercase snake) |
| 28 | Stream odd `player_id`/`team_id` empties | `""` | `null` | resolved (accept both) |
| 29 | `fixture-status` payload nesting | OpenAPI `data.data` | doc prose single-level; not observed live | parse both |

## 9.2 Remaining gotchas (behave defensively)

- **Security:** `/fixtures/results/queue/status` returns the raw API key inside `queue_name`; the key is also in stream URLs when `?key=` is used. Redact in logs, never persist raw.
- Ids are not hex: `player_id "9F39C732DBMMMBA2"`, all-digit fixture ids, `league:hex` fixture ids. Store opaque strings.
- `price` is American by default and can be extreme (`-10421`, `9207`, `100000`); Polymarket/Kalshi near-certain outcomes appear as `-9900`/`-10421`. Prefer `odds_format=PROBABILITY` or `DECIMAL` for quant pipelines, or convert carefully.
- Odd `selection_line` is overloaded: `over/under/yes/no` **and** correct-score `"3:2"`.
- `season_year`/`season_week`/`numerical_id` types drift (strings, ints, nulls); `sport.name` casing differs across endpoints (`baseball` vs `Baseball`) — join on `id`.
- `start_date` uses `Z` in REST and `+00:00` in streams; `timestamp` is float seconds in odds, int seconds in historical entries and last-polled, ns in PM.
- `is_live` may be `true` on `completed` fixtures; use `status`.
- Fixture `source_ids` is `null` without the flag, `{}` or `{"statsperform_id": ""}` with it.
- Cancelled placeholder fixtures (e.g. speculative Super Bowl pairings) keep `has_odds: true`; filter `status`.
- Team/player ids are league-scoped (`base_id` links across leagues, unreliable for tennis); tennis `player.id == team.id`.
- Golf round-prop fixtures have empty competitor arrays and `away_team_display ∈ {Round 1..4}`.
- League slugs collide across sports (`england_-_super_league` = rugby league, `spain_-_primera_division` = futsal); store `(sport_id, league_id)`.
- Sportsbook regional/state clones are distinct ids (`caesars_pennsylvania_`, `betrivers_new_york_`, `unibet_australia_`, DFS variants `prizepicks_5_or_6_pick_flex_`); the static docs list drifts from `/sportsbooks` — bootstrap from the live endpoint.
- `/sportsbooks/active` may include `is_active:false` rows (doc example) — filter client-side.
- `/leagues` is 612 KB unpaginated; `/fixtures/odds` bodies reach 5 MB; `/fixtures/odds/historical` 1.9 MB — stream-parse.
- Results stream can emit stale/`unplayed` fixtures; results REST `stats` values may be strings; MLB legacy stat keys (`rbi`, `starter`) on older fixtures; tennis `max_games_in_a_row` vs doc `max_games_in_row`.
- `/fixtures/player-results/last-x` live shape is stat→array dicts (no per-game fixture ids), unlike its OpenAPI schema.
- `market_stats` keys contain `+` and leading digits — quote them in SQL.
- PM stream: `category` repeated → last wins; `0` is a sentinel for `best_bid/best_ask/last_trade_price/tick_size`; outcome keys are `yes`/`no` live but the OpenAPI example uses clobTokenIds — parse generically; Polymarket prices reach 0.001 granularity at the extremes.
- Parlay response keys may not equal requested names (`Bwin` → `Blue Book`); Caesars intermittently errors; Novig reports `missing_entries`.
- Streams have no server-side filtering below `sportsbook`/`league`/`market`/`fixture_id`/`is_main`/`is_live`; soccer-all-leagues is ~1.5 MB/s.
- Copilot endpoints return 200 with empty data — a monitoring check that "sees data" must look at `odds.length`, not status.

## 9.3 Open questions [UNKNOWN]

1. 429 response shape / `Retry-After` on the core backend; whether the PM/parlay backend has any limit.
2. `updated_since` semantics: `/fixtures?league=nfl&updated_since=2026-09-02T00:00:00Z` returned 0 rows although NFL fixtures had `updated_at` values — clock/format mismatch or index lag? Re-test with a recent `updated_at` value and with `/fixtures/active`.
3. Whether `fixture-status` events fire on `/stream/odds` at all with our key (none in 90 s of captures) and whether they cover all seven statuses.
4. Server-side SSE idle timeout / max lifetime; behaviour under `Accept-Encoding: gzip`.
5. `include_locked` — are lock ticks ever retained (0 seen)?
6. `/tournaments?sport=tennis` support; `/squads`; `/conferences`, `/divisions`, `/fixtures/results/head-to-head`, `/tournaments/results`, `/markets/settleable?league=`, `/grader/futures` never exercised successfully.
7. `lookback_num` semantics on `/fixtures/results?team_id=` and on `/fixtures/player-results/last-x` (probe used a wrong param name).
8. Injury status vocabularies for non-MLB leagues; injury update cadence (no timestamps).
9. Exact Polymarket condition-id mapping (only the clobTokenId is exposed on sports odds; deep link has `marketSlug`).
10. Whether Pinnacle event ids in `deep_link` URLs equal OddsPapi `externalProviders.pinnacleId` for the same fixture (candidate secondary join).
11. `half`/`suspended` fixture statuses and `duplicate_of` / cancellation-reason fields mentioned by the settlement page — never observed in payloads.
12. `/stream/futures` `last_entry_id` support and its data cadence (0 events observed).
13. PM stream `canonical_id` population rules (95 % politics vs 0 % crypto) and the `canonical_id[]`/`source_market_id[]` stream filters.
14. Behaviour when >250 stream connects / 15 s are attempted (docs: 429; not tested).

---

# 10. Recommended ingestion strategy

## 10.1 Channels and what each is for

| Need | Channel | Cadence / budget |
|---|---|---|
| Dimension tables (sports, leagues, sportsbooks, markets, market types) | `GET /sports`, `/leagues`, `/sportsbooks`, `/markets?sport=…&markets_only=false`, `/market-types` | hourly (doc: *"cache discovery endpoints … refresh hourly"*); `/sports/active`, `/leagues/active`, `/sportsbooks/active?league=…` every 5 min to discover new leagues/books |
| Fixture universe | `GET /fixtures/active?league=…&include_statsperform_id=true` per league (+ `/fixtures?league=…&start_date_after=…&start_date_before=…` for the next 7 days and for backfill) | every 60 s per active league (100 rows/page, standard bucket); `include_starting_lineups=true` in the 3 h before start for lineup-supported leagues |
| Live prices (primary) | `GET /stream/odds/{sport}` per (sport, 5-book bundle, ≤10 leagues), `is_main` unset, `include_fixture_updates=true`, `exclude_fees=true`, default odds format left American (convert) or `odds_format=DECIMAL` uniformly | long-lived; reconnect with backoff 1→60 s; ≤200 connects / 15 s |
| Hydration and reconnect recovery | `GET /fixtures/odds?fixture_id=×5&sportsbook=×5&exclude_fees=true` for every fixture of the affected bundle | on start and **on every reconnect** (no replay); a full MLB hydrate = 82 fixtures × 3 bundles ≈ 50 calls |
| Stale-line / poller health | `GET /sportsbooks/last-polled?league=…` (all books) and `?fixture_id=…&sportsbook=…` for arb legs | league scope every 60 s per league; fixture scope on demand before acting |
| Market availability per book | `GET /markets/active?fixture_id=…&sportsbook=×5` | at fixture activation and every 15 min |
| Futures | `GET /futures?league=…` daily; `GET /futures/odds?league=…&sportsbook=×5` | every 2–5 min per league (2.4 MB per 5-book call); keep one `/stream/futures/{sport}` per sport as a change trigger |
| Non-sport prediction markets | `GET /prediction-markets/categories`, `/canonical-events/ids?category=…`, `/canonical-events?canonical_id=×25` → mapping table; `GET /stream/prediction-markets?category=…` (optionally `&platform=`) | mapping refresh every 15 min; one stream per non-empty category (politics, crypto now); dedicated reader thread + queue |
| Scores / in-play state | `GET /stream/results/{sport}` (one per league for busy leagues) + `GET /fixtures/results?fixture_id=…` every 60 s for live fixtures as a fallback | streams; poll |
| Settlement | `GET /grader/odds` per open position after `status == completed` (retry on `Pending`, honour codes 104/107/108); `/fixtures/player-results` for props | event-driven |
| Opening/closing lines & backfill | `GET /fixtures/odds/historical?fixture_id&sportsbook=×5&market=…&include_timeseries=true` | historical bucket 50 / 15 s → ≤3 req/s; run a nightly job for the previous day's fixtures (CLV appears ~2 d later — re-pull at T+3 d) and a one-off 57-day backfill of main markets |
| Injuries | `GET /injuries?league=…` (paginated), `/injuries/predictions?league=nfl` | every 5 min on game days; diff against previous snapshot to emit change events |
| SGP fair value | `POST /parlay/odds` with `sportsbooks: ["OpticOdds AI", …]` | on demand; ~2 s |

Do **not** poll `/fixtures/odds` as the price source (5 fixtures × 5 books per call, bodies up to 5 MB) — it is for hydration and consistency checks only.

## 10.2 Stream topology

- One connection per `(sport, book bundle of ≤5, league group of ≤10)`. Book bundles (ordered by importance): **A** `pinnacle, draftkings, fanduel, polymarket, kalshi`; **B** `novig, prophet_x, betfair_exchange, betfair_exchange_lay_, circa_sports`; **C** `caesars, betmgm, bet365, betonline, fliff`; extend with `bookmaker`, `circa_vegas`, `sporttrade`, `matchbook_exchange`, `draftkings_predictions`, `underdog_predictions`, `robinhood`, `fanatics_markets` as coverage appears in `/sportsbooks/active`.
- Validate every id against `/sportsbooks` before subscribing (bad ids are silently dropped).
- Soccer: always pass `league[]` (≤10) — the all-leagues stream is 1.5 MB/s; group leagues by liquidity tier.
- Keep `is_main` unset; filter locally. Pass `market[]` only for narrow consumers.
- Results: one `/stream/results/{sport}` per league for MLB/NBA/NFL/NHL/EPL; sport-wide for the long tail.
- PM: one `/stream/prediction-markets?category=politics`, one `?category=crypto`; add categories when `/canonical-events/ids` becomes non-empty.
- Total connects at start: ≈ (sports 6 × bundles 3 × league groups 1–3) + results 8 + PM 2 ≈ 40–70, staggered over ≥15 s.

## 10.3 Consumer state machine (per odds stream)

```
on connected            → mark bundle DIRTY (hydrate needed) unless first-ever connect already hydrated
on odds                 → for each odd: upsert state[id] = odd, unlocked; emit quote(kind=update); track is_main flips
on locked-odds          → state[id].locked = true; emit quote(kind=lock, price = last known)
on fixture-status       → update fixture status/start_date; on completed/cancelled drop fixture state
on ping                 → clock_offset sample; watchdog reset
on silence > 15 s or transport error → close, backoff, reconnect (new connect counts against 250/15 s)
on reconnect            → REST hydrate all fixtures of the bundle (5×5 per call); reconcile: ids present in REST but locked locally → unlock; ids in local state but absent in REST → mark suspended (kind=lock); emit a `reconnect_gap` marker with the gap length for downstream models
dedupe                  → drop events whose entry_id was already processed (soccer produced duplicates); order by (entry_id ms, seq) within a window
```

## 10.4 Storage

**Raw archive (immutable):** every SSE line batch and every REST body as received, gzip JSONL, object storage path `raw/opticodds/<channel>/<sport-or-category>/<yyyy>/<mm>/<dd>/<hh>/<connection_id>-<seq>.jsonl.gz`, with `recv_ns`, `url` (key redacted), `entry_id`, `event` per record. This is the only source for in-play history, depth history, locks and PM books.

**Normalized (ClickHouse):**
- `oo_quotes` — one row per odd per event: `recv_ns, event_kind (snapshot|update|lock), entry_id, odd_id, fixture_id, game_id, sport_id, league_id, sportsbook_id, market_id, market_name, name, selection, normalized_selection, selection_line, points, price_american, price_decimal, prob, is_main, is_live, grouping_key, player_id, team_id, limit_max, ts_src (Float64 s), deep_link_desktop, source_ids (JSON), exclude_fees (Bool)`; `ORDER BY (fixture_id, sportsbook_id, market_id, normalized_selection, selection_line, points, recv_ns)`, `PARTITION BY toDate(recv_ns)`.
- `oo_order_book_levels` — `recv_ns, odd_id, fixture_id, sportsbook_id, market_id, normalized_selection, selection_line, points, side ('back'), level, price, size, ts_src, native_market_id, native_selection_id`.
- `oo_pm_books` — `recv_ns, market_id (platform:source), platform, source_event_id, source_market_id, category, canonical_id, outcome (yes|no|token), best_bid, best_ask, spread, last_trade_price, tick_size, timestamp_ns, bids (Array(Tuple(Float64,Float64))), asks (…)`; `ORDER BY (market_id, recv_ns)`.
- `oo_fixtures` (ReplacingMergeTree on `updated_at`/`recv_ns`) with the full §3.4 field list + `source_ids.statsperform_id`, rotation numbers, `game_id`.
- `oo_hist_ticks` — from `/fixtures/odds/historical`: `fixture_id, odd_id, sportsbook_id, market_id, name, is_main, ts (UInt32), price, points, locked` + `oo_hist_olv_clv (fixture_id, odd_id, olv_price, olv_points, clv_price, clv_points, pulled_at)`.
- `oo_last_polled (recv_ns, scope_type, scope_id, sportsbook_id, ts)`; `oo_results`, `oo_player_results` (JSON stats + extracted `market_stats`), `oo_injuries` (with first_seen/last_seen), `oo_grades`.
- Dimension tables: `oo_sports, oo_leagues, oo_sportsbooks, oo_markets, oo_market_types, oo_teams, oo_players, oo_futures, oo_pm_canonical_events, oo_pm_canonical_markets`.

Canonical keys: fixture → `fixture.id` (join OddsPapi via `opticoddsId`, SharpSports via `game_id == oddsjamId`); outcome → `(fixture_id, market_id, normalized_selection, selection_line, points, player_id)`; never use the vendor odd `id` as a stable history key (docs say it may change) but keep it for cache/dedupe.

## 10.5 Failure and resume handling

- REST: token buckets 7,800 / 15 s standard, 48 / 15 s historical, 200 / 15 s stream connects (headroom); read `x-ratelimit-remaining`/`reset` and sleep to `reset` when `remaining < 50`; treat 429 as unknown-shape (back off 15 s). Retry 5xx/transport with jitter; never retry 400 (fix the request).
- Stream-parse large bodies; cap in-memory batches.
- Every reconnect → hydrate; every hydrate compares REST vs local state (absence = suspended).
- Stale-book gate: refuse to emit an "executable" quote if `last-polled` age for that (book, league) exceeds the learned p95 poll gap, or the odd's `timestamp` age exceeds a per-market threshold.
- Health monitors: events/s per stream vs historical baseline; `ping` gap; `entry_id` regressions/duplicates; Copilot-style "200 but empty" detection; poller-dead list from `/sportsbooks/last-polled?league=…`.
- Key hygiene: header auth for REST; query `key=` only where required (SSE via browser is not our case — use the header there too); scrub `queue_name`.
- Backfill order on first run: dimensions → fixtures (next 7 d + last 60 d) → historical OLV/CLV + ticks for the last 57 d of main markets (historical bucket-paced) → results/player-results for completed fixtures → then start streams + hydrate.

---

# Appendix A — Grader settlement rules by sport (docs__settlement-rules.md + per-sport pages, 2026-07)

General principles (verbatim-level): *"A market settles once the fixture is marked completed"*; cancelled → undetermined bets Refunded, determined markets settle; whole-number line landed on = Refunded (2-way), 3-way spread push on the favoured side = Lost; 2-way tie = Refunded; odd/even: 0 = even; full-game markets include OT/shootouts (aggregate score), period/quarter/half markets slice the period array and exclude OT unless the name says `(Incl. OT)`/`(Incl. ET)`; multi-player combos `(Combo)` sum stats, `(Either)` wins if either hits (Refunded only if both push), `(Each)` needs both; no parlay engine — legs graded independently; dead-heat reduction computed only for golf/motorsport (count emitted, consumer applies). Lifecycle: `Unplayed → Live → Completed`, or `Delayed / Suspended / Cancelled`; Delayed auto-cancels after **24 h** (36 h tennis, 120 h football); cancellation reasons `never_started`, `teams_change`, `start_date_change`; a fixture flagged `duplicate_of` another settles off the canonical fixture.

| Sport | Game / match rules | Player-prop rules | Retirement / DNF |
|---|---|---|---|
| Baseball | Extra innings count; whole-number push Refunded; game not started on the scheduled local day → void; started game suspended and resumed within 48 h stands, >48 h void unless determined; **no 5-inning official rule**; pre-live date move → `start_date_change` cancel | Non-starters **and substitutes voided** (official start flags); pitcher must start and throw ≥1 pitch; batter must start and record ≥1 PA; props only for MLB, MLB All-Star, WBC | – |
| Basketball | OT by period (quarters exclude OT); NCAA/Big3/FIBA 3x3 use halves; push Refunded; tie Refunded; NBA Summer League complete-only | Player who takes the court has action; period props need minutes in that period; substitutes voided **only** for `First Basket` / `First Basket Including FT` | – |
| Football (American) | Quarter/regulation exclude OT; **2nd-half and `(Incl. OT)` include OT**; 3-way spread favoured push = Lost; tie Refunded; 120 h delay window | Substitutes not voided; DNP → Refunded | – |
| Hockey | Full game incl. OT + shootout (shootout winner credited one goal); regulation/period markets exclude OT (3rd period excludes OT); 0 goals = even | Any time on ice = action; no minimum TOI; substitutes not voided | – |
| Soccer | Regulation = periods 1–2; `(Incl. ET)` adds ET but not pens; aggregate markets span both legs; Asian quarter lines → Half Won/Half Lost; 2-way tie Refunded | 90 min + stoppage unless market says ET; **all props void substitutes** (a scoring sub is Refunded); DNP Refunded | – |
| Tennis / Badminton / Squash | – | substitutes n/a; DNP Refunded | **Moneyline settles on the player who progresses**; unresolved set/game/props Refunded; grader code 218 "Match ended in retirement" |
| Golf | H2H: Stableford highest wins else lowest; WD/DQ/missed cut → player with more holes wins (both ≥1 hole); handicap markets need equal holes; player markets void if not all 18 holes | Futures from leaderboard: Winner; Top N (2–50) with dead-heat reduction; Top N (With Ties) no reduction; Finishing Position O/U; To Make The Cut (settles when cut final; WD Refunded); End Of Round N Leader (settles when round final, while live) | 3-balls Refunded on incomplete 18-hole data |
| Motorsports | DNS loses to any finisher; both DNS/DNF → more laps wins, equal → Refunded | Futures: Winner, Top N (± ties), Finishing/Starting Position O/U; DNS Refunded; DNF/DSQ grade on classified position | – |
| Aussie Rules | official statistics; DNP Refunded, subs not voided | | |
| MMA | only `Completed`/`Cancelled` proceed, else Pending | | no-contest Refunds the whole fixture |
| Esports | | | retirement: moneyline to winner; completed maps grade; unplayed maps Refunded |
| Table tennis / darts / snooker / boxing | settle on official result and available stats; no retirement voiding | | |
| Futsal / Pesäpallo | | all player props void substitutes | |

Grader `result` machine values (live): `Won`, `Lost`, `Refunded`, `Pending`, `Half Won`, `Half Lost` (Title case with space); `status` `Completed`.

# Appendix B — Market-stat key dictionary (docs__in-play-data-guide.md, 2026-04; statistics API guides 2026-03)

Stats appear as `stats: [{period: "all"|"period_N", stats: {...}}]` (team and player) and pre-computed `market_stats: {home:{…}, away:{…}}` / player `market_stats: {player_*: n}`. Market-stat keys use market naming (`+` and ordinal prefixes) and map 1:1 to `market_id`s (`team_total` ↔ `team_total`, `player_points_+_rebounds_+_assists` ↔ market `player_points_+_rebounds_+_assists`). Period keys: soccer `period_1/2` halves, `period_3` ET, `period_4` pens; baseball `period_1..9` (+ extra innings; literal key for 10+ [UNKNOWN]); basketball/football `period_1..4` + `period_5` OT (multi-OT keys [UNKNOWN]); tennis sets. Values are numbers (soccer/baseball players as floats), occasionally strings (`"1-4"` combined stats, cricket `batting_fow_type`). Legacy MLB keys on older fixtures: `pitch_count, pitching_balls, pitching_strikes, pitching_walks, rbi, starter, complete_game` (*"Contact your account manager for a full legacy key mapping"*).

| Sport | Team market stats | Player market stats |
|---|---|---|
| Soccer | `team_total, asian_team_total, 1st_half_team_total, 2nd_half_team_total, 1st_half_asian_team_total, 2nd_half_asian_team_total, team_total_shots, team_total_shots_on_target, team_total_corners, 1st_half_team_total_corners, 2nd_half_team_total_corners, team_total_cards, team_total_card_points, 1st_half_team_total_cards, 2nd_half_team_total_cards, 1st_half_team_total_yellow_cards, 2nd_half_team_total_yellow_cards, team_total_fouls, team_total_tackles, team_total_offsides` | `player_goals, player_assists, player_goals_+_assists, player_shots, player_shots_on_target, 1st_half_player_shots_on_target, player_shots_assisted, player_passes, player_passes_completed, player_passing_attempts, player_crosses, player_tackles, player_interceptions, player_clearances, player_fouls, player_fouls_drawn, player_cards, player_saves, player_goals_against, player_dribble_attempts` |
| Football | `team_total, 1st_half_team_total, 2nd_half_team_total, 1st_quarter_team_total, 2nd_quarter_team_total, 3rd_quarter_team_total, 4th_quarter_team_total` | `player_passing_yards, player_passing_attempts, player_passing_completions, player_passing_touchdowns, player_rushing_yards, player_rushing_attempts, player_rushing_touchdowns, player_longest_rush, player_receptions, player_receiving_yards, player_receiving_targets, player_receiving_touchdowns, player_longest_reception, player_rushing_+_receiving_yards, player_passing_+_rushing_yards, player_passing_+_rushing_+_receiving_touchdowns, player_touchdowns, player_tackles, player_assists, player_tackles_+_assists, player_sacks, player_interceptions, player_defensive_interceptions, player_sacks_taken, player_field_goals_made, player_extra_points_made, player_kicking_points, player_punts` |
| Basketball | `team_total, 1st_half_team_total, 2nd_half_team_total, 1st_quarter_team_total … 4th_quarter_team_total, team_total_rebounds, team_total_assists, team_total_blocks, team_total_steals, team_total_made_threes, team_total_consecutive_points` (NB raw team stat `team_total_rebounds` = uncredited team rebounds, a different number) | `player_points, player_rebounds, player_assists, player_blocks, player_steals, player_turnovers, player_fouls, player_made_threes, player_threes_attempted, player_made_two_pointers, player_two_pointers_attempted, player_field_goals_made, player_field_goals_attempted, player_free_throws_made, player_free_throws_attempted, player_offensive_rebounds, player_defensive_rebounds, player_points_+_rebounds, player_points_+_assists, player_rebounds_+_assists, player_steals_+_blocks, player_points_+_rebounds_+_assists, player_double_double, player_triple_double` (+ raw flags `first_basket, first_team_basket, first_basket_including_ft, first_team_basket_including_ft`) |
| Hockey | `team_total, team_total_reg_time, 1st_period_team_total, 2nd_period_team_total, 3rd_period_team_total, team_total_shots_on_goal, team_total_power_play_goals` | `player_goals, player_assists, player_points, player_hits, player_saves, player_shots_on_goal, player_blocked_shots, player_faceoffs_won, player_goals_against, player_plus_minus, player_time_on_ice (MM:SS), player_power_play_points` |
| Baseball | live MLB: `team_total, 1st_half_team_total (F5), 1st_3_innings_team_total, 1st_7_innings_team_total, 1st_inning_team_total … 9th_inning_team_total, team_total_bases, team_total_batting_…`; guide: `2nd_half_team_total, team_total_hits, team_total_strikeouts, team_total_home_runs, team_total_errors` | `player_hits, player_runs, player_rbis, player_runs_+_rbis, player_hits_+_runs_+_rbis, player_bases, player_doubles, player_triples, player_home_runs, player_walks, player_batting_walks, player_stolen_bases, player_batting_strikeouts, player_strikeouts (pitcher), player_earned_runs, player_hits_allowed, player_pitches_thrown, player_outs`; live sample: `player_earned_runs, player_hits_allowed, player_outs, player_pitches_thrown, player_strikeouts, player_walks`, batter `player_bases` |
| Tennis (live stream) | `team_total` | `player_aces, player_double_faults, player_aces_+_double_faults, player_sets_won, player_sets_lost, player_games_won, player_games_lost, player_break_points_won, 1st_set_player_aces, 1st_set_player_games_won, 1st_set_player_games_lost` |
| Cricket | `team_total, 1st_inning_team_total, team_total_fours, team_total_sixes, team_total_wides, team_total_run_outs` (+ dynamic `batting_runs_over_N`, `bowling_*_over_N` under `period_1`) | `player_runs, player_fours, player_sixes, player_wickets_taken, 1st_inning_player_runs, 1st_inning_player_fours, 1st_inning_player_sixes` |
| Aussie Rules | – | `player_goals, player_marks, player_tackles, player_disposals` |
| Rugby Union / League | `team_total, 1st_half_team_total, 2nd_half_team_total` | – |
| Golf | – | `player_strokes, player_pars, player_eagles, player_birdies_or_better, player_pars_or_better, player_bogeys_or_better, player_bogeys_or_worse, player_bounce_backs` (+ raw `strokes_hole_1..18`) |
| MMA / Darts / Boxing | raw only (`knockdowns, significant_strikes_landed …`; darts `one_hundred_eighties, three_darts_average …`; boxing `home_total, away_total`) | – |

Raw team-stat vocabularies (soccer Opta-style: `total_scoring_att, ontarget_scoring_att, big_chance_created, ppda, att_bx_centre, corner_taken, won_corners, possession_percentage, …`; MLB 70 keys listed in §3.9; NFL `offensive_yards, passing_yards, rushing_yards, sacks, interceptions, penalties, penalty_yards, time_of_possession …`; NBA `points, field_goals_made, … biggest_lead, lead_changes, max_points_in_a_row, first_basket`) are in the in-play guide; treat all as sparse `Map(String, Float64|String)`.

# Appendix C — Market types and settleable markets

`GET /market-types` (43 rows live; `selections` are templates with `{home_team_name}`, `{away_team_name}`, `{points}` placeholders):

`1 asian_handicap` (`["{away_team_name} {points}", "{home_team_name} {points}"]`), `2 asian_team_total`, `3 asian_total`, `4 double_chance`, `5 double_team_or_draw`, `6 correct_score`, `7 moneyline`, `8 moneyline_3way`, `9 moneyline_3way_and_total`, `10 moneyline_3way_and_yes_no`, `11 moneyline_and_total`, `12 moneyline_and_yes_no`, `13 odd_even`, `14 player_only`, `15 player_total`, `16 player_total_combo`, `18 player_golf_hole_score_qualifier`, `19 player_yes_no`, `20 spread`, `21 spread_3way`, `22 team_and_neither`, `23 team_and_period`, `24 team_and_player`, `25 team_odd_even`, `26 team_or_player`, `27 team_total`, `28 team_total_3way`, `29 team_total_exact`, `30 team_yes_no`, `31 total`, `32 total_3way`, `33 winning_margin_or_draw`, `34 yes_no`, `35 yes_no_and_total`, `36 heads_or_tails`, `37 run_count`, `38 method_of_victory`, `39 color`, `40 team_method_of_victory`, `41 total_exact`, `42 player_h2h_ml`, `43 player_h2h_spread`, `44 period`. (`17` absent.) `Market.market_type_id` links here (e.g. `1st_half_draw_no_bet` → `7`).

NBA settleable markets (`GET /markets/settleable?league=NBA`, doc example, 107 ids = `numerical_id`): `1st_3_quarters_moneyline=43, 1st_3_quarters_moneyline_3-way=44, 1st_3_quarters_point_spread=45, 1st_3_quarters_total_points=46, 1st_half_correct_score=77, 1st_half_double_chance=78, 1st_half_draw_no_bet=79, 1st_half_moneyline=83, 1st_half_moneyline_3-way=84, 1st_half_point_spread=105, 1st_half_team_total=128, 1st_half_team_total_3-way=129, 1st_half_team_total_odd_even=138, 1st_half_total_points=152, 1st_half_total_points_odd_even=153, 1st_quarter_double_chance=244, 1st_quarter_moneyline=246, 1st_quarter_moneyline_3-way=247, 1st_quarter_point_spread=256, 1st_quarter_team_total=267, 1st_quarter_team_total_odd_even=271, 1st_quarter_total_points=276, 1st_quarter_total_points_odd_even=277, 2nd_half_correct_score=318, 2nd_half_double_chance=319, 2nd_half_draw_no_bet=320, 2nd_half_moneyline=323, 2nd_half_moneyline_3-way=324, 2nd_half_point_spread=336, 2nd_half_team_total=359, 2nd_half_team_total_3-way=360, 2nd_half_team_total_odd_even=367, 2nd_half_total_points=379, 2nd_half_total_points_odd_even=380, 2nd_quarter_moneyline=455, 2nd_quarter_moneyline_3-way=456, 2nd_quarter_point_spread=458, 2nd_quarter_team_total=469, 2nd_quarter_team_total_odd_even=473, 2nd_quarter_total_points=478, 2nd_quarter_total_points_odd_even=479, 3rd_quarter_moneyline=578, 3rd_quarter_moneyline_3-way=579, 3rd_quarter_point_spread=581, 3rd_quarter_team_total=592, 3rd_quarter_team_total_odd_even=596, 3rd_quarter_total_points=601, 3rd_quarter_total_points_odd_even=602, 4th_quarter_moneyline=684, 4th_quarter_moneyline_3-way=685, 4th_quarter_moneyline_3-way_incl_ot_=686, 4th_quarter_moneyline_incl_ot_=687, 4th_quarter_point_spread=691, 4th_quarter_point_spread_incl_ot_=692, 4th_quarter_team_total=703, 4th_quarter_team_total_odd_even=707, 4th_quarter_total_points=712, 4th_quarter_total_points_incl_ot_=713, 4th_quarter_total_points_odd_even=714, correct_score=910, double_chance=912, draw_no_bet=915, first_team_to_score=924, halftime_fulltime=935, moneyline=953, moneyline_3-way=954, moneyline_reg_time=955, player_assists=966, player_blocks=984, player_defensive_rebounds=995, player_double_double=998, player_field_goals_attempted=1020, player_field_goals_made=1021, player_fouls=1032, player_free_throws_attempted=1035, player_free_throws_made=1036, player_made_two_pointers=1063, player_offensive_rebounds=1064, player_points=1095, player_points_+_assists=1096, player_points_+_rebounds=1097, player_points_+_rebounds_+_assists=1098, player_rebounds=1103, player_rebounds_+_assists=1104, player_steals=1145, player_steals_+_blocks=1146, player_threes_attempted=1157, player_triple_double=1166, player_turnovers=1168, player_two_pointers_attempted=1169, point_spread=1172, point_spread_3-way=1173, team_total=1261, team_total_3-way=1263, team_total_assists=1265, team_total_blocks=1267, team_total_consecutive_points=1270, team_total_made_threes=1282, team_total_odd_even=1283, team_total_rebounds=1289, team_total_steals=1301, total_points=1358, total_points_odd_even=1359, will_there_be_overtime=1401`. Note `moneyline` (953) vs `moneyline_reg_time` (955) vs `…_incl_ot_` — OT scoping is part of the market id and must be preserved when mapping to OddsPapi/SharpSports markets.

Live MLB active markets include `1st_half_run_line (126)`, `7th_inning_moneyline_3-way (830)`, `team_total_hits (1280)`, `player_home_runs_yes_no`, `player_bases`, `player_hits`, `total_runs_odd_even`, `correct_score`, `no_runs_first_inning`, `1st_inning_total_runs`; Kalshi MLB quotes 19 markets (`moneyline, run_line, total_runs`, player props incl. `player_bases`, `player_home_runs_yes_no`).

# Appendix D — Copilot / RabbitMQ message shapes (documented; not licensed — for shape parity only)

- Queue lifecycle: `POST /copilot/queue/start` `{is_live: bool, odds_format?, id?, version_id?}` → `{"data":[{"id":3,"queue_name":"AAAAAAA_2_cop_4HOEXAMPLEQUEUE","enabled":true,"is_live":false,"odds_format":"AMERICAN","num_consumers":null,"num_messages":null,"messages_per_second":null,"version":{"id":1,"name":"Default"}}]}`; auto-deleted after **10,000** unread messages (odds) / **1,500** unread (results queues, incl. our non-Copilot `/fixtures/results/queue/*`).
- Messages: `{"event":"ping","timestamp":"1743541426","data":"2024-08-28T18:57:49Z"}` (string timestamp); `{"event":"copilot-odds","timestamp":1743539407,"data":[{id "1:-1:202504014E28ECF5:moneyline:fairleigh_dickinson", fixture_id, game_id, odd_id, version_id -1, version "default", market, market_id, sport, sport_id, league, league_id, name, selection, normalized_selection, selection_line, points, price, is_main, is_live, grouping_key, player_id, team_id, timestamp}]}`; `copilot-locked-odds` same shape; `copilot-settled-odds` adds `settlement` (`Won`…) and `settled_at` (`"2025-04-01T21:01:19.793489"` naive) and drops price fields; `fixture-results` `{"event":"fixture-results","timestamp":1746109375,"data":{fixture_id, sport, league (display), is_live, score: FixtureResult, player_results: [PlayerResult], extra: {…, source: "sofascore", …}}}`. String sentinels `"None"` appear for `player_id`/`team_id`/`selection_line`/`points` in Copilot messages.
- `/copilot/fixtures/odds/historical` entries: `{timestamp, event ("copilot-odds"|"copilot-locked-odds"|"copilot-settled-odds"), price, is_main, settlement}` newest first — the model for our own event-sourced price ledger.
- Copilot pricing engine (docs__configurations.md / default-settings): consensus split with weights summing to 100 %, mandatory books, `minimum_providers` (recommend ≥2), proportional reweighting when a book is missing, `Average Odds` vs `Devig Odds` (multiplicative devig), default vig, `min_difference` hysteresis in probability points (`abs(old_price − new_price) >= min_difference`, +100 = 50 %), min–max odds range with `Keep Price in Range` (pin) or `Suspend` (→ `copilot-locked-odds`); override hierarchy Default Settings < Configuration < market override < fixture override (trading floor); versions/environments (`version_id -1` = default; Dev/Prod).

# Appendix E — Probe sample index (research scratchpad `samples/opticodds/`, referenced by name in this spec)

| Sample | Request | Use |
|---|---|---|
| `sports`, `sports_active`, `leagues_all`, `leagues_active`, `sportsbooks`, `market_types`, `markets_baseball` | discovery endpoints | dimension bootstrap shapes |
| `sbactive_{baseball,mlb,nfl,basketball,soccer,epl,politics,fixture_mlb}`, `sportsbooks_dk_fixture` (`?league=politics`) | `/sportsbooks/active` scopes | per-league book coverage |
| `last_polled_mlb`, `last_polled_nfl_dk`, `last_polled_nfl_fixture`, `last_polled_mlb_kalshilist` | `/sportsbooks/last-polled` | staleness semantics |
| `teams_mlb`, `players_nfl_p1/p2`, `injuries_mlb/nfl`, `injuries_predictions` | squads / injuries | pagination + ids |
| `fixtures_mlb`, `fixtures_mlb_p2`, `fixtures_mlb_sep02`, `fixtures_mlb_0705`, `fixtures_mlb_0601`, `fixtures_mlb_2025`, `fixtures_mlb_range`, `fixtures_mlb_2026-07-{08,15,22,29}`, `fixtures_mlb_0831`, `fixtures_mlb_0901`, `fixtures_{nfl,wnba,mls,epl,ncaaf,ncaaf_p2,tennis_atp,tennis_atp_challenger,tennis_atp_doubles,tennis_wta,tennis_wta_doubles}`, `fixtures_active_*`, `fixtures_status_live`, `fixtures_status_bogus`, `fixtures_by_id`, `fixtures_updated_since`, `fixtures_live_all` | `/fixtures`, `/fixtures/active` | fixture model, date filters, legacy ids |
| `markets_active_{mlb,nfl,epl,nfl_kalshi,mlb_kalshilist}`, `markets_settleable` | `/markets/active`, `/markets/settleable` | availability |
| `odds_mlb_b1/b2/b3`, `odds_mlb_main_dec`, `odds_mlb_6books`, `odds_mlb_exfees`, `odds_nfl_b1/b2`, `odds_epl_b1`, `odds_wnba_b1`, `odds_by_team`, `odds_by_player`, `odds_{nfl,epl,mlb}_kalshi_only`, `odds_nfl_kalshi_name`, `odds_nfl_polymarket_only`, `odds_nfl_circa_prophet`, `odds_league_mlb_dk/pin`, `odds_nfl_market_filter`, `odds_bad_book`, `odds_no_book`, `odds_nfl_kalshilist`, `odds_mlb_kalshilist`, `odds_mlb_kalshi_dec`, `odds_soccer_kalshi` | `/fixtures/odds` | odd model per book, limits, depth, fees |
| `hist_mlb_ml`, `hist_mlb_ml_ts`, `hist_mlb_main`, `hist_mlb_all_dk`, `hist_mlb_locked`, `hist_0705_ml_ts`, `hist_0601_ml_ts`, `hist_2025_ml`, `hist_0801_ml_ts`, `hist_0801_all_pin`, `hist_ts_2026-07-{08,22,29}`, `hist_ts_0831`, `hist_ts_0901` | `/fixtures/odds/historical` | retention / CLV timing |
| `futures_nfl`, `futures_mlb`, `futures_odds_nfl`, `futures_odds_nfl_b2`, `futures_odds_nfl_pm`, `futures_odds_nfl_pm_sb` | futures | |
| `results_mlb`, `results_0705`, `results_2025`, `results_mlb_lookback`, `player_results_mlb`, `player_results_2025`, `player_results_lastx`, `fixtures_h2h`, `tournaments_results`, `grader_mlb`, `grader_0705`, `grader_futures`, `results_queue_status` (redacted) | results / grader | |
| `parlay_sgp_post`, `parlay_cross_post`, `parlay_odds_post`, `parlay_get_form`, `_parlay_sgp`, `_parlay_cross`, `_parlay_body` | `POST /parlay/odds` | SGP pricer |
| `pm_categories`, `pm_ids_{politics,crypto,economics,other}`, `pm_canonical_{politics,crypto}` | non-sport PM REST | canonical mapping |
| `copilot_fixtures`, `copilot_versions`, `copilot_odds`, `stream_copilot` | Copilot stubs | entitlement proof |
| `stream_odds_baseball(.full)`, `stream_odds_soccer`, `stream_odds_baseball_resume(.full)`, `stream_odds_politics`, `stream_odds_baseball_kalshi`, `stream_odds_football_kalshi`, `stream_odds_soccer_kalshi`, `stream_replayA/B`, `stream_lat_baseball`, `stream_lat_soccer_main`, `stream_lat_resumeA-D`, `stream_bad_nobook` | `/stream/odds/{sport}` | event shapes, throughput, replay tests |
| `stream_results_{baseball,baseball2,tennis,soccer}(.full)` | `/stream/results/{sport}` | |
| `stream_futures_{football,football2,baseball}(.full)` | `/stream/futures/{sport}` | (pings only) |
| `stream_pm_politics`, `stream_pm_politics_kalshi(.full)`, `stream_pm_crypto`, `stream_lat_pm_crypto`, `stream_bad_cat` | `/stream/prediction-markets` | snapshot shapes |
| `badkey_sports`, `noauth_sports` | auth errors | |
| `*.headers` | raw response headers per sample | rate-limit / backend identification |

Tools: `oo_probe.sh` (REST/SSE capture with key redaction), `oo_sse_latency.py` (arrival-vs-timestamp percentiles, replay tests), `probe_narrative.py` (sample → structural narrative).
