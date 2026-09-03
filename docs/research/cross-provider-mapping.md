# Cross-provider mapping and canonical data model

**Providers:** OpticOdds v3 (REST + SSE, incl. non-sport prediction markets; no Copilot) · OddsPapi v5 (REST + WebSocket) · SharpSports (betPrices, historicData, betSync).
**Purpose:** define how the three feeds are joined into one identity space (sports → leagues → fixtures → teams/players → books → markets → selections), what a price means in each feed, the canonical storage schema (what `schemas/clickhouse.sql` implements today vs. what is planned), the mapping-QA loop, and the known gaps.

Evidence legend used throughout:

| Tag | Meaning |
|---|---|
| **[DOC]** | stated in the provider documentation / OpenAPI / AsyncAPI (see `docs/research/oddspapi.md`, `docs/research/sharpsports.md`, reader notes) |
| **[LIVE]** | observed with our trial keys on 2026-09-03 (provider probes and the cross-provider join probe, samples under `samples/cross/`, `samples/<provider>/`) |
| **[CODE]** | what the current implementation does (`u3ingest/canonical/models.py`, `u3ingest/canonical/markets.py`, `u3ingest/mapping/registry.py`, `u3ingest/providers/*/normalize.py`, `schemas/clickhouse.sql`) |
| **[GAP]** | not implemented, contradictory, or unverified — see §5 |

Cross-provider join probe (2026-09-03T10:45Z, window now..+3 d) headline numbers **[LIVE]**:

| Join | Result |
|---|---|
| OddsPapi `externalProviders.opticoddsId` == OpticOdds `fixture.id` | MLB **40/40**, EPL **8/8**, NCAAF **114/125** (11 OpticOdds-only); start-time delta **0 s** on every matched pair; 162 matched pairs in `samples/cross/fixture_join.json` |
| SharpSports `event.oddsjamId` == OpticOdds `fixture.game_id` | MLB **37/40** (+3 via team+time); NFL: all **100/100** `game_id`s of the OpticOdds NFL sample appear as SharpSports `oddsjamId`s (`samples/opticodds/fixtures_nfl.json` vs `samples/cross/ss_events.json`) |
| SharpSports team+time fallback (±15 min) | EPL **8/8** (SharpSports EPL events carry no `oddsjamId`), NCAAF **73/87** (+6 by `oddsjamId`, 8 unmatched), MLB 3/40 |
| SharpSports `Team.oddsjamId` == OpticOdds competitor `id` | NFL **32/32**, MLB **30/30** (`samples/sharpsports/teams_NFL.json`, `teams_LGUE_mlb.json` vs OpticOdds fixtures) |
| Books present in all three feeds | `betmgm`, `betrivers`, `draftkings`, `fanduel`, `kalshi`, `polymarket` (plus Pinnacle via SharpSports `pn`, which is `status: unsupported` but `oddsFeedActive: true`) |

---

## 1. Identity resolution strategy

### 1.1 Sports

| Canonical `sport` (= OpticOdds `sport.id`) | OpticOdds `sport.id` / `numerical_id` | OddsPapi `sportId` / `slug` | SharpSports `sportId` / `name` |
|---|---|---|---|
| `baseball` | `baseball` / 3 | 13 Baseball | `SPRT_baseball` / "Baseball" |
| `basketball` | `basketball` / (varies by page) | 11 Basketball | `SPRT_basketball` / "Basketball" |
| `football` | `football` / 9 | 14 American Football | `SPRT_americanfootball` / "Football" **or** "American Football" (name unstable **[LIVE]**) |
| `soccer` | `soccer` / 21 | 10 Soccer | `SPRT_soccer` / "Soccer" |
| `hockey` | `hockey` | 15 Ice Hockey | `SPRT_icehockey` |
| `tennis` | `tennis` / 25 | 12 Tennis | (SharpSports tennis markets exist; `SPRT_` id not captured) |
| `politics`, `entertainment`, … | OpticOdds sport ids (non-sport prediction markets also via `/stream/prediction-markets` categories `politics, economics, finance, crypto, tech, culture, climate, health, geopolitics, companies, other`) | 69–78 (Politics … Culture) — **not entitled** (`403 sport_not_allowed`) | Event `league` "will be the associated governing body or null" **[DOC]**; not probed |

Rules **[CODE]**: `FixtureRef.sport` stores the OpticOdds slug when the fixture is OpticOdds-resolved; OddsPapi-only fixtures store `str(sport.sportId)` and SharpSports-only fixtures store `event.sport` (display string). **[GAP]** these three spellings must be collapsed by the planned `sports` dimension (§3.3) — today `fixture_xref.sport` is a mixed vocabulary.

Entitlement facts that bound the universe **[LIVE]**: OddsPapi key = sports 10–15 only, 31 bookmakers, no futures odds; OpticOdds key = everything probed (0× 403), 229 sportsbooks; SharpSports private key = betPrices + historicData + betSync, 15 active books.

### 1.2 Leagues / tournaments

| Canonical `league` (= OpticOdds `league.id`) | OpticOdds | OddsPapi `tournamentId` (`tournamentName`, `categoryName`) | SharpSports `leagueId` (`abbr`; `League.sportradarId`) |
|---|---|---|---|
| `mlb` | `mlb` (numerical_id 346) | 109 (MLB) | `LGUE_mlb` (`MLB`; `2fa448bc-…`) |
| `nba` | `nba` | 132 (NBA) | `LGUE_nba` (`NBA`; `4353138d-…`) |
| `wnba` | `wnba` | 486 (WNBA) | `LGUE_wnba` (`WNBA`) |
| `nfl` | `nfl` (numerical_id 9 **or** 367 depending on page **[DOC]**) | 31 (NFL) | `LGUE_nfl` (`NFL`; `3c6d318a-…`) |
| `ncaaf` | `ncaaf` | (not probed) | `LGUE_ncaaf` (`NCAAF`) |
| `ncaab` | `ncaab` | (not probed) | `LGUE_ncaamb` (`NCAAMB`) — `league=NCAAB` → `400 "Invalid league"` **[LIVE]** |
| `nhl` | `nhl` | 234 (NHL) | `LGUE_nhl` (`NHL`) |
| `england_-_premier_league` | `england_-_premier_league` (numerical_id 165 live, 21 in docs) | 17 (`Premier League`, category `England`) | `LGUE_542b6c4f1c7f4a0da7154747c76e7340` (`EPL`; `sr:competition:17`) |
| `usa_-_major_league_soccer` | `usa_-_major_league_soccer` **[DOC]** (cross probe used the key `mls`, 0 fixtures in window) | 242 (MLS) | `LGUE_269a3af26ac44fdaae9b3dfc80de46a2` (`MLS`; `sr:competition:242`) |

Facts and rules:

- OpticOdds league ids are globally unique slugs with frozen typos; **never regenerate from names**; several near-identical slugs belong to different sports (`spain_-_primera_division` is futsal) → always store `(sport, league)` together **[DOC]**.
- OddsPapi `tournamentId` is an integer that is also zero-padded into `fixtureId` (`id10` + `000017` + native id for EPL); `/tournaments` without params silently defaults to `sportId=11` **[LIVE]**.
- SharpSports `LGUE_` ids are slugs for US majors and 32-hex for others; league filters must use `LGUE_*` or the **uppercase** abbr (`league=nfl` → `[]` on `/teams`, `400` on `/markets`) **[LIVE]**. `League.oddsjamId` is `null` for every major league sampled; `League.sportradarId` is a UUID for US leagues but `sr:competition:<int>` for soccer.
- **[CODE]** `FixtureRegistry` keys the team-name index by `league` and falls back to a team-pair-only search when league keys differ across providers (`_fuzzy`). The pipeline `universe` maps each sport to `(opticodds league ids, oddspapi sportId, sharpsports league abbrs)`; there is no persisted league xref yet **[GAP]** → planned `leagues` table (§3.3).

### 1.3 Fixtures

#### 1.3.1 Native id formats

| Provider | Field | Format / examples **[LIVE]** | Notes |
|---|---|---|---|
| OpticOdds | `fixture.id` | 16 chars `YYYYMMDD` + 8 hex: `2026090552B5D9A7`, `20260903C7118D8C` (173/173 in the cross sample are 16 chars) | Docs also show legacy 12-hex (`BCE4E01B8D3D`) and `<league_id>:<12hex>` (`england_-_premier_league:0DB083EFBDA2`) — accept `[A-Za-z0-9_:-]{12,40}` |
| OpticOdds | `fixture.game_id` | `36707-80389-2026-09-03-09` (MLB: `<teamA>-<teamB>-<YYYY-MM-DD>-<HH>`), `37240-25327-26-36` (NFL: `<teamA>-<teamB>-<YY>-<WW>`), `42573-28098-2026-09-04` (EPL) | Opaque legacy OddsJam id; the **first segment of every odd `id`** (`42573-28098-2026-09-04:pinnacle:moneyline:ipswich_town_fc`); SSE odds carry both `fixture_id` and `game_id` |
| OpticOdds | `fixture.numerical_id` | int (`944216`, `594641`) | not used for joins |
| OpticOdds | `home_rotation_number` / `away_rotation_number` | MLB `952 / 951`, `958 / 957`; NFL `452 / 451`; null for EPL; 103/173 populated in the cross sample | pairs are consecutive; **do not assume parity** (docs say away=odd/home=even, OddsPapi EPL sample has home 792 / away 793) |
| OpticOdds | `source_ids.statsperform_id` | `"2986833"` (MLB), `"2978395"` (NFL) — only when `include_statsperform_id=true` (100/100 populated in `fixtures_mlb.json`; `null` in the cross sample which omitted the flag) | Opta/Stats Perform id; also on teams (`"253"`) and players (`"1228903"`) |
| OddsPapi | `fixtureId` | `id1000001772221244` = `id` + `10` + `000017` + `72221244`; treat as **opaque** (native suffix == `betradarId` in most but not all cases) | 19,954 fixtures fetched, all prefixed `id` |
| OddsPapi | `externalProviders.*` (non-null counts over 19,954 fixtures) | `betradarId` 19,954 · `flashscoreId` 6,774 · `pinnacleId` 3,100 · `opticoddsId` 2,593 · `sofascoreId` 1,346 · `lsportsId` 826 · `mollybetId` 787 · `betgeniusId` 648 · `oddinId` 0 · `txoddsId` 0 | keys may be **absent or null**; int and string values mixed → store as strings |
| OddsPapi | `participants.participant1RotNr` / `participant2RotNr` | EPL `792 / 793`; NBA docs `303 / 302` | participant1 = home / first-listed |
| OddsPapi | `bookmakers.<slug>.bookmakerFixtureId` (also `/fixtures/mapping`) | `pinnacle` `1634530286`, `draftkings` `34572328`, `betfair-ex` `35974451`, `polymarket` `893106`, `kalshi` `KXEPLGAME-26SEP05FULCRY`, `fliff` `202609060BD42598`, `198bet` `FBL-1995027`, `3et` `2602058`, `4casters` `6a953f189497f7c94de22cf1` | bookmaker-native event ids; `pinnacle` value == `externalProviders.pinnacleId` **[DOC]**. The `fliff` value has the OpticOdds 16-char id shape (unverified whether it equals `opticoddsId`) **[GAP]** |
| SharpSports | `Event.id` | `EVNT_b9615f005d8b4dcd970c97596436597a` (32 hex; docs also show 22-char base64url) | opaque |
| SharpSports | `Event.oddsjamId` | `36707-80389-2026-09-03-09`, `33857-26091-2026-09-24`, `16341-78014-26-41` | **== OpticOdds `game_id`** (same legacy OddsJam scheme); window fill rate: MLB 40/40, NFL 200/292, WNBA 30/34, MLS 10/15, NCAAF 6/87, EPL 0/8 |
| SharpSports | `Event.sportradarId` | `f7de7d97-2893-4ba7-9339-66399357ba91` (UUID, no `sr:match:` prefix) | MLB 40/40, NFL 272/292, NCAAF 87/87, EPL 8/8 filled; docs say null unless you supply a Sportradar key — populated for us **[LIVE]** |
| SharpSports | `Event.sportsdataioId` | `"10079449"`, `"7870"` | SportsData.io GameID |
| SharpSports | `Event.theOddsApiId` | `f042b623f0e70459103f5406f1ea75ee` (docs); **0/499 filled** in the window sample | The Odds API event id — **foreign reference only**, never a join key for us |
| SharpSports | `Event.contestantHome/Away` | `{id: TEAM_…, fullName, abbr}` (live has `abbr`; docs list only `id`,`fullName`) | futures "events" (`Southwest Division 2026/27`) have `startTime: null` and null contestants |

#### 1.3.2 Resolution order (canonical `fixture_id` = OpticOdds `fixture.id`)

| Step | Key | Precision | Coverage observed **[LIVE]** | Status |
|---|---|---|---|---|
| 1 | OddsPapi `externalProviders.opticoddsId` **==** OpticOdds `fixture.id` | exact | MLB 40/40, EPL 8/8, NCAAF 114/125 in window; bootstrap run: 149/1,223 baseball and 1,940/14,774 soccer OddsPapi fixtures carry an `opticoddsId` (OpticOdds only lists fixtures with odds; OddsPapi lists far more) | **[CODE]** `FixtureRegistry.add_oddspapi` |
| 2 | SharpSports `Event.oddsjamId` **==** OpticOdds `fixture.game_id` | exact | MLB 37/40; NFL 100/100 of the OpticOdds NFL sample | **[CODE]** `FixtureRegistry.add_sharpsports` (`by_game_id`) |
| 3 | normalized home/away names + start time within ±15 min, same league key, else team-pair only | fuzzy | EPL 8/8, NCAAF 73/87, MLB 3/40 | **[CODE]** `FixtureRegistry._fuzzy` (`norm_team` strips `fc|sc|cf|afc|the|club`, NFKD-folds, keeps `[a-z0-9]`) |
| 4 | Rotation numbers: OpticOdds `{home_rotation_number, away_rotation_number}` vs OddsPapi `{participant1RotNr, participant2RotNr}` as an **unordered pair** on the same calendar day | exact when both present | OpticOdds 103/173; OddsPapi present for EPL/NBA samples; OddsPapi Argentine soccer values like `210458/210457` are not US rotations **[DOC]** | **[GAP]** not implemented; planned as a tie-breaker between steps 1 and 3 |
| 5 | Sportsbook-native ids: OddsPapi `externalProviders.pinnacleId` / `bookmakers.pinnacle.bookmakerFixtureId` vs SharpSports `Price.bookIds.eventId` for book `pn` (`1634945554`); OddsPapi `bookmakers.kalshi.bookmakerFixtureId` vs OpticOdds `source_ids.market_id` ticker prefix vs SharpSports `bookIds` for `kl` (`eventId` `26SEP041905BOSBAL`, `marketId` `KXMLBGAME`, `selectionId` `BOSY`); OddsPapi `bookmakers.draftkings.bookmakerFixtureId` (`34572328`) vs SharpSports `bookIds.eventId` for `dk` (`30589142` style) | exact per book | format-compatible; not yet measured | **[GAP]** candidate keys, unverified |
| 6 | Betradar / Sportradar / Stats Perform | none | OddsPapi `betradarId` (int) and SharpSports `sportradarId` (UUID) are different id spaces; OpticOdds exposes only `statsperform_id`; no provider exposes both → **not joinable today** | **[GAP]** requires an external crosswalk |
| 7 | `theOddsApiId` | n/a | SharpSports only | foreign reference column only |
| fallback | unresolved fixtures keep a provider-scoped canonical id `oddspapi:<fixtureId>` / `sharpsports:<EVNT_…>` | — | every OddsPapi fixture without `opticoddsId` (3,855 in window) | **[CODE]** `FixtureRegistry.canonical_for` |

Edge cases to encode:

- **Name normalization differences** **[LIVE]**: OddsPapi `participant1Name` `Ipswich Town` vs OpticOdds `Ipswich Town FC` vs SharpSports `Ipswich Town FC`; OddsPapi `participant2Abbr` `LFC` vs OpticOdds `abbreviation` `LIV`. The probe's naive name comparison reported 162/162 mismatches before normalization; `norm_team` resolves the `FC` case, abbreviations must not be used as keys.
- **OpticOdds placeholder fixtures** **[DOC]**: pre-championship permutations exist with `status: cancelled` and `has_odds: true`, high 5-digit rotation numbers (`77711–77716`); prefer the fixture with the low "real" rotation numbers and `status != cancelled`.
- **Duplicate OddsPapi rows per OpticOdds id**: not observed in the window sample (162 distinct pairs) but must be asserted (§4.1).
- **Time base**: OpticOdds `start_date` ISO `Z`; OddsPapi `startTime` **epoch seconds** (+ `trueStartTime`/`trueEndTime` ISO); SharpSports `startTime` ISO `Z`. `FixtureRef.start_time_ms` is UTC ms **[CODE]**.
- **Status vocabularies**: OpticOdds `status` ∈ `unplayed|live|half|completed|cancelled|suspended|delayed`; OddsPapi `status.statusId` ∈ `0 pregame|1 live|2 finished|3 cancelled` (branch on the id, never `statusName`); SharpSports has **no** event status (infer from `startTime` and `Price.live`). `FixtureRef.status` stores the raw provider string **[CODE]** → planned canonical `fixture_status` enum (§3.3).

#### 1.3.3 Observed coverage by league (cross probe, window 2026-09-03T10:45Z … +3 d) **[LIVE]**

OpticOdds ↔ OddsPapi via `externalProviders.opticoddsId` (`samples/cross/fixture_join.json`):

| League (OpticOdds `league.id` / probe key) | OpticOdds fixtures | matched via `opticoddsId` | only in OpticOdds | notes |
|---|---|---|---|---|
| `nba`, `wnba`, `nfl`, `nhl`, `mls`, `ncaab` | 0 | 0 | 0 | off-season / no odds yet in the window |
| `mlb` | 40 | 40 | 0 | start-time delta 0 s on all pairs |
| `england_-_premier_league` | 8 | 8 | 0 | OddsPapi tournament 17 |
| `ncaaf` | 125 | 114 | 11 | the 11 OpticOdds-only fixtures had no `opticoddsId` on the OddsPapi side (OddsPapi still lists the game with `opticoddsId: null`) |
| OddsPapi fixtures in window with **no** `opticoddsId` | 3,855 of 4,017 | — | — | mostly non-US soccer/tennis (OddsPapi lists 19,954 upcoming fixtures for sports 10–15) |

SharpSports ↔ OpticOdds (`samples/cross/ss_join.json`, 129 resolved `EVNT_ → OpticOdds id` pairs):

| League (SharpSports `league` param) | SS events | `oddsjamId` filled | `theOddsApiId` filled | matched `oddsjamId == game_id` | matched team+time (±15 min) | unmatched | why |
|---|---|---|---|---|---|---|---|
| `NBA` (`upcoming=true`) | 15 | 0 | 0 | 0 | 0 | 15 | all are futures containers (`Southwest Division 2026/27`, `MVP 2026/27`) with `startTime: null` |
| `WNBA` (`upcoming=true`) | 34 | 30 | 0 | 0 | 0 | 34 | OpticOdds had no WNBA fixtures with odds in the window (games on 2026-09-24) |
| `NFL` (`upcoming=true`) | 292 | 200 | 0 | 0 | 0 | 292 | same (season starts 2026-09-10); the separate check against the OpticOdds NFL sample matched 100/100 `game_id`s |
| `MLB` | 40 | 40 | 0 | 37 | 3 | 0 | 3 `oddsjamId`s differed from OpticOdds `game_id` (hour suffix) but resolved by team+time |
| `NHL` (`upcoming=true`) | 8 | 0 | 0 | 0 | 0 | 8 | futures containers |
| `MLS` | 15 | 10 | 0 | 0 | 0 | 15 | OpticOdds `mls` key returned 0 (probe used the wrong league id; live id is `usa_-_major_league_soccer` **[DOC]**) |
| `EPL` | 8 | 0 | 0 | 0 | 8 | 0 | SharpSports EPL events carry no `oddsjamId` |
| `NCAAF` | 87 | 6 | 0 | 6 | 73 | 8 | e.g. `Louisiana-Monroe Warhawks @ Mississippi State Bulldogs`, `Sam Houston Bearkats @ Troy Trojans` — OpticOdds names differ or fixture missing |
| `NCAAB` | — | — | — | — | — | — | `400 "Invalid league"` for `NCAAB`/`ncaab`; SharpSports abbr is `NCAAMB` (`LGUE_ncaamb`) |

SharpSports vendor-id fill rates in the same sample (`sportsdataioId` / `sportradarId` / `oddsjamId`): NFL 290/272/200, NCAAF 87/87/6, MLB 40/40/40, WNBA 30/30/30, MLS 15/15/10, EPL 8/8/0, NBA 15/0/0, NHL 8/0/0. `theOddsApiId` 0 everywhere.

OddsPapi `externalProviders` non-null counts over all 19,954 upcoming fixtures (sports 10–15): `betradarId` 19,954 · `flashscoreId` 6,774 · `pinnacleId` 3,100 · `opticoddsId` 2,593 · `sofascoreId` 1,346 · `lsportsId` 826 · `mollybetId` 787 · `betgeniusId` 648. The probe run also confirmed `/fixtures/mapping?bookmaker=opticodds` → `403 bookmaker_not_allowed` (same for `betradar`, `flashscore`): the OpticOdds map can only be harvested from `/fixtures`.

### 1.4 Teams / participants

| Provider | Id | Cross-vendor ids on the object | Join to canonical |
|---|---|---|---|
| OpticOdds | `Competitor.id` 12-hex (`77CBFB371ED9` Ipswich, `98CE61698342` Pirates) or 16-hex; unique **per league** (Man City `E69E55FFCF65` EPL vs `578E2130DC1B` UCL); `base_id` int links across leagues (logo path `cdn.opticodds.com/team-logos/<sport>/<base_id>.png`); `numerical_id` | `source_ids.statsperform_id` (`"253"`) with `include_statsperform_id=true` | canonical `team_id` = OpticOdds team `id` (league-scoped) with `base_id` as the cross-league group key |
| OddsPapi | `participantId` int (`32` Ipswich, `44` Liverpool, `3421` NYK); fields `participantName`, `participantShortName`, `participantAbbr`, `participant{1,2}RotNr` | **none** | name + league + rotation-number match; result persisted in `team_xref` (planned) |
| SharpSports | `TEAM_9095865374204017a249dceb3b916636`; fields `locale`, `name`, `fullName`, `abbr`, `sportId` | `oddsjamId` (`AF456B375E7E`, `8E80F9DD4C5E`), `sportradarId` (UUID), `sportsdataioId` (`"1"`, `"10000001"`) | **`Team.oddsjamId` == OpticOdds team `id`: NFL 32/32, MLB 30/30 [LIVE]** — exact join |

**[CODE]** today: OpticOdds `home_competitors[0].id` / `away_competitors[0].id` are kept only in the normalizer's in-memory `_fx_ctx` (used by `canon_selection` to map team names → `home`/`away`); SharpSports `contestantHome.id` likewise. No team table is persisted **[GAP]**.

### 1.5 Players

| Provider | Id | Cross-vendor ids | Notes |
|---|---|---|---|
| OpticOdds | `player.id` 12-hex (`37115F112AA7`, `938CF19550D1`) or 16-hex (`93BBC13219D279DD`); league-scoped; `base_id`, `numerical_id`; odds carry `player_id` | `source_ids.statsperform_id` (`"1228903"`) | tennis: `player.id == team.id` **[DOC]** |
| OddsPapi | `playerId` int (`103335`, `607468`; `0` = no player); `playerName` **"Last, First"**; 4th segment of `oddsId` (`id1000001772221240:3et:102732:103335`) | **none** | name match only |
| SharpSports | `PLYR_1d959c528d9d4cad873dcd7f47780508`; `firstName`, `lastName`, `fullName`, `sportId`, `currentTeams[{id,fullName}]` | `oddsjamId` 12-hex (`4E18B0FEC4C5`) **or** 16-hex (`B5A9E6C0CB792387`), `sportradarId` UUID, `sportsdataioId` | `Player.oddsjamId` is format-identical to OpticOdds `player.id`; one exact match (`Andrew Armstrong`) found against a 200-player OpticOdds NFL sample **[LIVE]** — coverage must be measured on full rosters |

Canonical `player_id` = OpticOdds player `id`; SharpSports joins via `oddsjamId`; OddsPapi via `(sport, league/team, normalized name)` with the `team_xref` as a constraint. **[GAP]** no `players`/`player_xref` tables yet; quote rows carry the **provider's** player id in `quotes.player_id`, so cross-provider player-prop joins are currently impossible (§5).

### 1.6 Sportsbooks / bookmakers — normalized book registry

Sources: OpticOdds `GET /sportsbooks` (229 rows; fields `id, name, logo, is_onshore, is_active`; 43 inactive, 114 onshore) · OddsPapi `GET /bookmakers` (31 rows; `slug, bookmakerName, active, domain, websocketPregame, websocketLive, playerProps, maxDelayPregameInSec, maxDelayLiveInSec, maxDelayPregameMainInSec, availableCountries, staleThresholdSec, availableSports, lastOddsAt, staleOddsSince, limitCurrency` + deprecated `serverGroup, price`) · SharpSports `GET /books` (15 active + 10 unsupported; `id, name, abbr, status, oddsFeedActive, betPlaceStatus{webBrowser,iOS,android}, refreshCadenceActive, sdkRequired, backgroundRefresh, pullBackToDate, maxHistoryMonths, maxHistoryBets, historyDetail, mobileOnly`). All values below are **[LIVE]** 2026-09-03.

| Canonical `book_id` | Kind | OpticOdds `id` (`is_onshore`/`is_active`) | OddsPapi `slug` (`limitCurrency`; `maxDelay` pre/live/main s; `staleThresholdSec`) | SharpSports `abbr` (`name`; `status`; `oddsFeedActive`) | In `registry.BOOKS` |
|---|---|---|---|---|---|
| `pinnacle` | sharp book | `pinnacle` (F/T); `ps3838` (F/**F**), `ps4848` (F/**F**) = Pinnacle B2B brands | `pinnacle` (USD; 0.38/0.38/0.38; 240) | `pn` (Pinnacle; **unsupported**; **true**) | yes |
| `draftkings` | US retail | `draftkings` (T/T) | `draftkings` (—; 0.26/0.21/0.25; 240) | `dk` (DraftKings; active; true) | yes |
| `fanduel` | US retail | `fanduel` (T/T) | `fanduel` (—; 3.0/1.0/1.0; 240; `lastOddsAt` 2026-09-02T18:46Z = dark at probe time) | `fd` (Fanduel; active; true) | yes |
| `betmgm` | US retail | `betmgm` (T/T); `betmgm_uk_` separate | `betmgm` (—; 0.74/0.76/0.7; 240) | `mg` (BetMGM; active; true) | yes |
| `caesars` | US retail | `caesars` (T/T) | `caesars` (—; 2.21/0.19/2.45; 480; sports 11,13,14,15) | `ca` (Caesars; active; true) | yes |
| `betrivers` | US retail | `betrivers` (T/T); `betrivers_new_york_` separate | `betrivers` (—; 0.34/0.47/0.34; 240) | `br` (BetRivers; active; true) | yes |
| `fanatics` | US retail | `fanatics` (T/T); `fanatics_markets` is a separate prediction venue | — (registry lists `fanatics`, **not in the 31 entitled slugs**) | `fn` (Fanatics; active; **false**) | yes |
| `hardrock` | US retail | `hard_rock` (T/T) | — (registry lists `hardrock`, not live) | `hr` (HardRock; active; true) | yes |
| `thescore` | US retail (ESPN BET successor) | `thescore` (T/T); no `espn_bet` id exists | — | `bs` (theScore; active; true) — docs still call `bs` "ESPN BET" | yes |
| `fliff` | social book | `fliff` (T/T); `fliff_superstars` separate | `fliff` (—; 0.28/0.22/0.25; 240; `websocketLive: false`) | `fl` (Fliff; active; **false**) | yes |
| `sleeper` | DFS | `sleeper` (T/T) | — | `sl` (Sleeper; active; **false**) | yes |
| `borgata` | US retail | `borgata` (T/T) | `borgata` (—; 0.8/0.73/0.78; 240) | `bo` (Borgata; **unsupported**; false) | **no** |
| `betparx` | US retail | `betparx` (T/T) | `betparx` (—; 0.87/0.51/0.87; 300) | — | **no** |
| `bally_bet` | US retail | `bally_bet` (T/T) | `ballybet` (—; 0.27/0.55/0.27; 240) | — | **no** |
| `circa` | sharp book | `circa_sports` (T/T), `circa_vegas` (T/T) | `circasports` (USD; 0.31/0.35/0.31; 1020; `websocketLive: false`) | — | yes |
| `betonline` | offshore | `betonline` (F/T) | `betonline.ag` (—; 30/4/6; 600) | — | yes |
| `bookmaker` | offshore | `bookmaker` (F/T) | `bookmaker.eu` (—; 10/1/10; 4770) | — | yes |
| `bovada` | offshore | `bovada` (F/T) | `bovada.lv` (—; 30/4/6; 300) | — | **no** |
| `betus` | offshore | `betus` (F/T) | `betus` (—; 0.25/0.26/0.25; 600; `websocketLive: false`) | — | **no** |
| `bet365` | global retail | `bet365` (T/T) | `bet365` (—; 60/5/8; 240; `websocketLive: false`) | — | yes |
| `lowvig`, `heritage`, `bet105`, `sharp`, `betcris`, `jazz_sports`, `everygame`, `sbobet`, `saba_sports`, `marathonbet`, `prime_sports` | sharp/offshore | OpticOdds only (`lowvig` F/T, `heritage` F/T, `bet105` F/T, `sharp` F/T) | — | — | **no** |
| `kalshi` | prediction market (CFTC) | `kalshi` (T/T) | `kalshi` (USD; 0.12/0.12/0.12; 240; `playerProps: true`) | `kl` (Kalshi; active; true; betPlace `betSlipCreation`) | yes |
| `polymarket` | prediction market | `polymarket` (T/T) **and** `polymarket_usa_` (T/T, "Polymarket (USA) … maps Optic IDs") | `polymarket` (USD; 0.05/0.04/0.05; 240) | `pm` (Polymarket; active; true; betPlace `deepLink` web only) | yes (both OpticOdds ids) |
| `draftkings_predictions` | prediction market | `draftkings_predictions` (T/T) | — | — | yes |
| `robinhood`, `fanatics_markets`, `underdog_predictions`, `gemini_exchange`, `limitless_exchange`, `opinion_labs` | prediction markets | OpticOdds only (`robinhood` T/T, `fanatics_markets` T/T, `underdog_predictions` T/T, `gemini_exchange` F/T, `limitless_exchange` F/T, `opinion_labs` F/T) | — | — | **no** |
| `novig` | vig-free exchange | `novig` (T/T; "maps Optic IDs") | — (registry lists `novig`, not live) | — | yes |
| `prophetx` | US exchange | `prophet_x` (T/T) | `prophetx` (USD; 3.79/3.26/3.66; 300) | `pe` (Prophet Exchange; **unsupported**; false) | yes |
| `sporttrade` | US exchange | `sporttrade` (T/**F** — inactive at probe) | — (registry lists `sporttrade`, not live) | `st` (Sporttrade; active; **false**) | yes |
| `sx_bet` | crypto exchange | `sx_bet` (T/T) | `sx.bet` (USD; 0.09/0.09/0.09; 240) | — | **no** |
| `betfair_exchange` | exchange (back) | `betfair_exchange` (F/T); `betfair_exchange_australia_` | `betfair-ex` (EUR; 0.1/0.17/0.1; 240) — **registry maps `betfair`, wrong slug** | — | yes (slug wrong) |
| `betfair_exchange_lay` | exchange (lay) | `betfair_exchange_lay_` (F/T); `betfair_exchange_australia_lay_` | (lay side is inside `meta` of `betfair-ex`, presumably `availableToLay`) | — | yes |
| `betdex`, `matchbook_exchange`, `tailgate_exchange` | exchanges | `betdex` (F/T), `matchbook_exchange` (F/T), `tailgate_exchange` (F/**F**) | — | — | **no** |
| `4casters` | exchange | — | `4casters` ("4casters Exchange"; 17.63/18.48/14.95; 960; `websocketLive: false`) | — | **no** |
| `prizepicks` | DFS pick'em | `prizepicks` (T/T); `prizepicks_5_or_6_pick_flex_`, `prizepicks_demons_and_goblins_` are payout variants | — (registry lists `prizepicks`, not live) | `pp` (PrizePicks; active; true) | yes |
| `underdog` | DFS pick'em | `underdog_fantasy_2_pick_` (T/**F**), `underdog_fantasy_3_or_5_pick_`, `underdog_fantasy_4_pick_flex_`, `underdog_fantasy_multipliers_` | — (registry lists `underdog`, not live) | `ud` (Underdog; active; true) | yes (only the inactive 2-pick id) |
| `pointsbet` | (defunct US) | `pointsbet_australia_`, `pointsbet_ontario_` | — | `pb` (PointsBet; unsupported; false) | **no** |
| `3et`, `198bet`, `duel`, `kaiyun`, `paradisewager`, `punter.io`, `sharpbet`, `singbet`, `vertex` | OddsPapi-only (Asian/crypto) | (`duel` exists in OpticOdds) | `3et` (EUR), `198bet`, `duel`, `kaiyun`, `paradisewager` (USD), `punter.io` (EUR), `sharpbet` (EUR), `singbet`, `vertex` (USD) | — | **no** |
| SharpSports unsupported leftovers | — | — | — | `tb` Test Book, `sh` SugarHouse, `fb` FoxBet, `wb` WynnBet, `tf` ThriveFantasy, `bf` BetFred (all `oddsFeedActive: false`) | no |

Variant / clone handling (OpticOdds exposes many ids per brand; SharpSports one `abbr` per brand; OddsPapi one slug):

| Pattern | OpticOdds examples **[LIVE]** | Canonical treatment |
|---|---|---|
| State / country clones | `betrivers_new_york_`, `betmgm_uk_`, `betano_argentina_`, `unibet_united_kingdom_`, `pointsbet_ontario_`, `betfair_exchange_australia_` | parent `book_id` + `book_xref.variant` (`new_york`, `uk`, …); quotes keep `provider_book` so clones can be separated later |
| Lay side of an exchange | `betfair_exchange_lay_`, `betfair_exchange_australia_lay_` | **own** `book_id` (`betfair_exchange_lay`); prices are lay odds, not back odds |
| DFS payout variants | `draftkings_pick_2_`, `draftkings_pick_3_`, `draftkings_pick_6_`, `draftkings_pick_6_multipliers_`, `prizepicks_5_or_6_pick_flex_`, `prizepicks_demons_and_goblins_`, `underdog_fantasy_3_or_5_pick_`, `underdog_fantasy_4_pick_flex_`, `underdog_fantasy_multipliers_`, `dabble_3_or_5_pick_`, `betr_picks_all_` | parent `book_id` (`prizepicks`, `underdog`, `draftkings_dfs`) + `variant`; prices are pick'em lines (typically ±100/−137-style), never mix with sportsbook quotes in the board |
| Prediction-market spin-offs of a book | `draftkings_predictions`, `underdog_predictions`, `fanatics_markets`, `polymarket_usa_` | **own** `book_id` (different venue, different settlement) except `polymarket_usa_` which the registry currently folds into `polymarket` — revisit once its quotes are compared |
| Pinnacle brands | `pinnacle`, `ps3838`, `ps4848` (both PS ids `is_active: false` at probe time) | `pinnacle` with `variant` |
| Synthetic / model books | `oddsjam_algo_odds` (docs, inactive), `opticodds_ai`, `opticodds_ai_dfs`, `OpticOdds AI` parlay pricer | `book_id` `opticodds_ai`, `kind='model'`; exclude from arbitrage |
| SharpSports test rows | `tb` "Test Book" | ignore |

Registry rules:

- **[CODE]** `BookRegistry.resolve(provider, slug)` lowercases, then tries `normalize()` (`[^a-z0-9]+ → _`), and on miss returns `"<provider>:<normalized slug>"` and counts it in `BookRegistry.unknown[(provider, slug)]`. OpticOdds SSE carries `sportsbook` display names (`"Pinnacle"`, `"Prophet X"`) and `sportsbook_id` slugs (`prophet_x`); REST `/fixtures/odds` rows carry only `sportsbook` (display name) → the normalizer resolves on `sportsbook`, so `"Circa Sports"` → `circa_sports` via `normalize()`, but `"Polymarket (USA)"` → `polymarket_usa` ≠ `polymarket_usa_` **[GAP]**.
- **[GAP]** rows marked **no** above resolve to `oddspapi:sx_bet`, `opticodds:robinhood`, … today. Seed the registry from the three live catalogues (persisted `bootstrap/registries` archive) rather than from docs; the docs' static tables lag the live lists by months **[DOC]**.
- SharpSports book **coverage flag is `Book.oddsFeedActive`**, not `status` (Pinnacle is `unsupported` yet priced; Fliff/Sleeper/Fanatics/Sporttrade are `active` but unpriced) **[LIVE]**.
- OddsPapi exposes prediction markets and exchanges as ordinary bookmaker slugs on sports fixtures (`kalshi`, `polymarket`, `betfair-ex`, `sx.bet`, `prophetx`, `4casters`) with order-book ladders in `meta` **[LIVE]**; OpticOdds does the same via sportsbook ids (`order_book`, `source_ids`), plus a separate non-sport path (`/stream/prediction-markets`, platforms `kalshi|polymarket` only).

### 1.7 Markets — canonical taxonomy

Canonical market key **[CODE]** (`u3ingest/canonical/markets.py`): `moneyline | 3way | spread | total | team_total[:<metric>] | team_prop:<metric> | player:<metric> | other:<slug>`, paired with a canonical `period` ∈ `full | reg | 1h | 2h | 1q | 2q | 3q | 4q | 1p | 2p | 3p | 1i | f3i | f5i | f7i | set1 | set2 | ot | <raw>` (`CANON_PERIODS` in `models.py` lists `full, reg, 1h, 2h, 1q..4q, 1p..3p, f5i, 1i, set1..set3, ot`; `markets.py` additionally emits `f3i`, `f7i`).

How each provider names markets:

| Provider | Market identity | Period encoding | Line | Player / team subject | Alternate lines |
|---|---|---|---|---|---|
| OpticOdds | `market_id` snake slug + `market` display name (`moneyline`/"Moneyline", `point_spread`, `run_line`, `total_runs`, `total_goals`, `asian_handicap`, `team_total`, `player_passing_yards`, `player_bases`, `player_home_runs_yes_no`, `both_teams_to_score`, `correct_score`, `1st_half_winning_margin`); `market_type_id` → `GET /market-types` (43 types: `moneyline`(7), `moneyline_3way`(8), `spread`(20), `total`(31), `team_total`(27), `player_total`(15), `player_yes_no`(19), `yes_no`(34), `correct_score`(6), `asian_handicap`(1), `asian_total`(3), …) with selection templates (`"Over {points}"`, `"{home_team_name} {points}"`) | prefix in the slug: `1st_half_`, `2nd_half_`, `1st_quarter_`, `1st_period_`, `1st_inning_`, `1st_5_innings_`, `1st_7_innings_`, `2nd_set_`; suffix `_incl_ot_` / `(Incl. OT)` in names **[DOC]** | `points` (numeric, per selection, sign from the selection's view: `ipswich_town_fc_+1_5`), `selection_points` on SSE | `player_id`, `team_id` on the odd; `selection` = player/team name; `selection_line` ∈ `over|under|yes|no|odd|even|exact|"3:1"|"2+"|null` (55 distinct values in one EPL fixture **[LIVE]**) | every line is its own odd; `is_main` marks the book's main; `grouping_key` pairs sides (`default`, `default:2.5`, `brice_turang:2.5`, `ipswich_town_fc`) |
| OddsPapi | `marketId` int (== lowest `outcomeId`); `marketType` open vocabulary (`1x2, moneyline, spreads, spreads-european, totals, teamtotals-team1, teamtotals-team2, bothteamsscore, drawnobet, oddeven, correctscore, winningmargin, doublechance, firstgoal, lastgoal, totals-corners, spread-corners, totals-bookings, playertotals-tackles, playertotals-shots, playertotals-shotsongoal, playertotals-goals, playertotals-assists, toscore-team1, cleansheet-team1, wintonil-team1, …` — 1,122 markets for soccer, 4,902 for basketball); `marketName`/`marketNameShort` translated | `period` ∈ `result` (incl. OT), `fulltime` (regulation), `p1`, `p2`, … , `null` (cross-period markets such as `toscoreinbh-team1`) | `handicap` on the **market** (each line = separate `marketId`; `0.0` when lineless); spread sign is **for participant 1** (outcomes `'1'`/`'2'`) → flip for participant 2 **[CODE]** | `playerProp: true`; `playerId` in the `oddsId` (4th segment); `marketLength` = outcome count | one `marketId` per line; `mainLine` per quote (nullable/absent) |
| SharpSports | `Market.id` `MKT_…` + `Market.name` grammar `[SEGMENT] (Moneyline|Spread|Total|3-way | [Future ] Game Prop|Team Prop|Player Prop|Match Prop <tail>)`; `type` ∈ `straight|prop`; `proposition` ∈ `moneyline|spread|total|3-way` for straights (free text for props); `player|team|future` bools; `segment{id,name}`; `metric{id,name}`; cross-vendor `oddsjamId` (`moneyline`, `point_spread`, `player_home_runs`), `sportradarId` (`sr:market:1` live MLB moneyline; `sr:market:219`, `sr:market:223`, `sr:market:9003` in docs), `theOddsApiId` (`h2h`, `batter_home_runs`) | `segmentId` (95 segments **[LIVE]**: `SEGM_M`, `SEGM_1H`, `SEGM_2H`, `SEGM_1P..3P`, `SEGM_1Q..4Q`, `SEGM_1I..9I`, `SEGM_F2I..F8I`, `SEGM_S1..S5`, `SEGM_S1G1..S5G12`, `SEGM_R1..R4`); name prefix (`1st Half Spread`); 6 Underdog MLB names infix the segment (`Player Prop 1st Inning Hits`) | `Price.line` float per (selection, book, line); `0.0` = no line in `/prices`, `null` in `MarketSelection.prices` | `MarketOffer.player{id,fullName}` / `team{id,fullName}`; `MarketSelection.positionId` `TEAM_`/`PLYR_` or null; `propDetails{player,playerId,team,teamId,matchupSpecial,metricSpecial,metricSpecialId,future}` | all lines in `books[].prices[]` with `main` bool; `lineAvailability{abbr:[lines]}` |

Canonical taxonomy rows (each provider's naming for the same canonical market):

| Canonical `market` (`period`) | OpticOdds `market_id` | OddsPapi `marketType` (`period`) | SharpSports `Market.name` (`proposition`) | Line representation |
|---|---|---|---|---|
| `moneyline` (`full`) | `moneyline` (2-way; MLB/NFL/NBA/NHL) | `moneyline` (`result`), e.g. 111 → 111 `'1'`, 112 `'2'` | `Moneyline` (`moneyline`) | none |
| `3way` (`full`) | `moneyline` on soccer carries a `Draw` selection (Pinnacle/DK/FD/Kalshi in the EPL sample); `moneyline_3-way` suffix for period markets (`1st_half_moneyline_3-way`, `total_runs_3-way`) | `1x2` (`fulltime` 101 → `'1','X','2'`; basketball 113 = regulation) | `3-way` (`3-way`), positions team / `Draw` | none |
| `spread` (`full`) | `point_spread`, `run_line`, `puck_line`, `asian_handicap`, `goal_spread_3-way` | `spreads` (2-way, `handicap` for p1), `spreads-european` (3-way) | `Spread` (`spread`), position = team, `line` position-relative | OpticOdds `points` (per side), OddsPapi `handicap` (flip for side 2), SharpSports `line` (per side) |
| `total` (`full`) | `total_points`, `total_runs`, `total_goals`, `asian_total_goals` | `totals` (`handicap` = line; outcomes `Over`/`Under`) | `Total` (`total`), positions `Over`/`Under` | line value |
| `team_total` (`full`) | `team_total`, `team_total_hits`, `team_total_exact` (team via `team_id` / `selection`) | `teamtotals-team1` / `teamtotals-team2` | `Team Prop Total <Metric>` (`total`), `marketOffers[].team` | line value |
| period variants | `1st_half_moneyline`, `1st_quarter_point_spread`, `1st_inning_total_runs`, `1st_5_innings_run_line`, `2nd_set_moneyline` | `period` = `p1`, `p2`, … (`First Half Result` = `1x2`/`p1`) | `1st Half Moneyline`, `1st Quarter Spread`, `1st Inning Total`, `1st 5 Innings Total`, `Set 1 Moneyline` | as above |
| `player:<metric>` (`full`) | `player_passing_yards`, `player_bases`, `player_strikeouts`, `player_hits_+_runs_+_rbis`, `anytime_goal_scorer`, `player_home_runs_yes_no` | `playertotals-<metric>` (`playertotals-shots`, `playertotals-tackles`, …), `players-*`; `playerProp: true` | `Player Prop Total <Metric>` (`total`), `Player Prop First Goal Scorer` (positions `Yes`) | `points` / `handicap` / `line`; yes/no via `selection_line`, outcome names, position |
| `team_prop:<metric>` | `team_total_touchdowns`, `1st_inning_team_total_hits` | `teamtotals-corners-team1`, `toscore-team1`, `cleansheet-team1`, `wintonil-team1` | `Team Prop Total Corners`, `Team Prop Winning Margin` (positions `1`,`2`,`3`,`4+`) | line or none |
| `other:both_teams_to_score` | `both_teams_to_score` (`selection_line` `yes`/`no`) | `bothteamsscore` (104 `Yes`, 105 `No`) | `Game Prop Both Teams To Score` (positions `Yes`/`No`) | none |
| `other:correct_score` | `correct_score` (`selection` team, `selection_line` `"3:1"`) | `correctscore`, `exactscore` | `Game Prop Correct Score` (position `"Liverpool FC 3-1"`) | none |
| `other:double_chance`, `other:draw_no_bet` | `double_chance`, `draw_no_bet` | `doublechance`, `drawnobet` | (not in SharpSports taxonomy) | none |
| futures / outrights | `GET /futures` id `type_{market_id}-sport_{sport_id}-league_{league_id}`; futures odds id `{league_id}:{sportsbook_id}:{market_id}:{normalized_selection}` | `futureId` (`id100000171302811`, `pm6980037088158379224`); future `marketId` 1 Winner, 2 Top Scorer, 3 Relegation, 4 Prediction, 5 MVP — **odds not entitled** | `Future Winner <Competition> <Season>` (`Market.future: true`, new `MKT_` per season); futures events have `startTime: null` | none |
| prediction-market yes/no (non-sport) | `/stream/prediction-markets` `market_id` `<platform>:<source_market_id>` (`kalshi:AMAZONFTC-29DEC31`, `polymarket:897017`), `outcomes.{yes,no}` with `bids[]/asks[]` | sportIds 69–78 as futures with the question in `season.seasonName` — not entitled | — | contract price 0–1 |

Period mapping (canonical `period` per provider encoding):

| Canonical `period` | OpticOdds market slug prefix / name | OddsPapi `Market.period` (interpret with `sport.sportId`, `expectedPeriods`, `periodLength`) | SharpSports segment (`segmentId` / name prefix) | Sports |
|---|---|---|---|---|
| `full` (incl. OT) | no prefix; names may carry `(Incl. OT)` | `result` ("Winner (incl. overtime)", basketball 111) | `SEGM_M` / no prefix (`Bet.segmentDetail` `Including Overtime` only on bets) | all |
| `reg` (regulation) | `_regular_time` / "(Reg. Time)" names where offered | `fulltime` (basketball 113 "Regular Time Result"; soccer 101) | — | basketball, hockey, soccer |
| `1h` / `2h` | `1st_half_`, `2nd_half_` | `p1`, `p2` **for soccer** (soccer `expectedPeriods` 2, `periodLength` 45) | `SEGM_1H` / `SEGM_2H` (`1st Half …`) | soccer, basketball, football |
| `1q`..`4q` | `1st_quarter_` … `4th_quarter_` | `p1`..`p4` when `expectedPeriods` = 4 and `periodLength` = 12/15 | `SEGM_1Q`..`SEGM_4Q` | basketball, football |
| `1p`..`3p` | `1st_period_` … `3rd_period_` | `p1`..`p3` when `expectedPeriods` = 3, `periodLength` = 20 | `SEGM_1P`..`SEGM_3P` | hockey |
| `1i`..`9i`, `f3i`, `f5i`, `f7i` | `1st_inning_`, `1st_3_innings_`, `1st_5_innings_`, `1st_7_innings_` (`1st_half_` also used for baseball first-5) | `p1`.. (innings) and combined keys `p1+p2+p3+p4+p5` **[DOC]** | `SEGM_1I`..`SEGM_9I`, `SEGM_F2I`..`SEGM_F8I` | baseball |
| `set1`..`set5`, games | `1st_set_`, `2nd_set_` | `p1`.. (sets); `p1g1`..`p5g13` sub-periods | `SEGM_S1`..`SEGM_S5`, `SEGM_S1G1`..`SEGM_S5G12` | tennis |
| rounds | golf `end_of_round_n_leader` names | — | `SEGM_R1`..`SEGM_R4` | golf |
| `ot` | `overtime_` | `overtime`, `fulltime+overtime`, `p4+overtime` | — | hockey, basketball |

**[CODE]** `split_period` recognizes `1st/2nd half`, `1st..4th quarter`, `1st..3rd period`, `1st 5/3/7 innings`, `1st inning`, `1st/2nd set`, `(reg` and `regulation time`; OddsPapi periods go through `_OP_PERIOD` (see [GAP 5]).

Player-prop metric mapping (verified examples; the SharpSports `Market.oddsjamId` **equals the OpticOdds `market_id` slug** wherever both were observed):

| Canonical `player:<metric>` | OpticOdds `market_id` **[LIVE]** | SharpSports `Market.name` → `metric.id` (`Market.oddsjamId`) **[LIVE/DOC]** | OddsPapi `marketType` **[LIVE]** |
|---|---|---|---|
| `player:passing_yards` | `player_passing_yards` | `Player Prop Total Passing Yards` → `METR_passyds` (`player_passing_yards`) | — (NFL market catalogue not probed) |
| `player:home_runs` | `player_home_runs`; yes/no variant `player_home_runs_yes_no` | `Player Prop Total Home Runs` → `METR_homeruns` (`player_home_runs`; `sportradarId` `sr:market:9003`; `theOddsApiId` `batter_home_runs`) | — |
| `player:bases` | `player_bases` | `Player Prop Total Bases` → `METR_bases` | — |
| `player:strikeouts` (pitcher) | `player_strikeouts` | `Player Prop Total Pitcher Strikeouts` → `METR_pitcherstrikeouts` (SharpSports also has `METR_hitterstrikeouts` for `Player Prop Total Hitter Strikeouts`; OpticOdds `player_batting_strikeouts`) | — |
| `player:hits_runs_rbis` | `player_hits_+_runs_+_rbis` | `Player Prop Total Hits + Runs + RBIs` → `METR_hitsrunsrbis` | — |
| `player:rushing_receiving_yards` | `player_rushing_+_receiving_yards` | `Player Prop Total Rushing + Receiving Yards` → `METR_rushrecyds` | — |
| `player:receptions` / `player:touchdowns` | `player_receptions` / `player_touchdowns`, `anytime_touchdown_scorer`, `first_touchdown_scorer` | `METR_receptions` / `METR_touchdowns` | — |
| `player:shots` / `player:shots_on_goal` (soccer) | `player_shots`, `player_shots_on_target`, `player_outside_box_shots_on_target` | `Player Prop Total Shots` → `METR_shots`, `Player Prop Total Shots On Goal` → `METR_shotsongoal` | `playertotals-shots`, `playertotals-shotsongoal` |
| `player:tackles`, `player:saves`, `player:assists`, `player:goals` (soccer) | `player_tackles`, `player_saves`, `player_assists`, `anytime_goal_scorer` | `Player Prop Total Tackles` → `METR_tackles`, `METR_saves`, `METR_assists`, `Player Prop Total Goals` → `METR_goals`, `Player Prop First Goal Scorer` (position `Yes`) | `playertotals-tackles`, `playertotals-saves`, `playertotals-assists`, `playertotals-goals` |

`canon_market_from_name` slugs the metric text (`slug("Hits + Runs + RBIs")` → `hits_runs_rbis`), so OpticOdds `player_hits_+_runs_+_rbis` (via its display name "Player Hits + Runs + RBIs") and SharpSports `Player Prop Total Hits + Runs + RBIs` collapse to the same key; SharpSports `METR_*` ids are **not** derivable from names (`METR_passyds` vs `METR_passing_yards` both exist **[LIVE]**) and must be looked up from `GET /metrics` (278 rows).

Mapping functions **[CODE]**: `canon_market_from_name(name)` (OpticOdds `market`, SharpSports `Market.name`): `split_period` regexes → alias table (`moneyline|money line|winner|match winner → moneyline`, `1x2|3-way|3 way|3-way moneyline|moneyline 3-way → 3way`, `point spread|spread|run line|puck line|goal spread|game spread|asian handicap|handicap → spread`, `total|total points|total runs|total goals|total games|over/under|over under|asian total → total`, `team total|team total points|team total runs|team total goals → team_total`) → `player prop`/`batter`/`pitcher`/`goalie` regex → `player:<metric>`; `team prop … total` → `team_total:<metric>` else `team_prop:<metric>`; else `other:<slug>`. `canon_market_oddspapi(marketType, period, marketName)`: `_OP_TYPE` (`moneyline→moneyline, 1x2→3way, spreads→spread, totals→total, teamtotals-team1/2→team_total`), `_OP_PERIOD` (`result→full, regular-time→reg, 1st-half→1h, …`; **note the live period keys are `fulltime`, `p1`, `p2`, which are not in `_OP_PERIOD` and pass through raw [GAP]**), `players-*`/`playertotals-*` → `player:<slug>`, else fall back to the name mapper, else `other:<marketType>`.

**[GAP]** taxonomy items not yet canonicalized: OpticOdds `moneyline` on soccer is a 3-way market but maps to `moneyline` (the `draw` selection survives, so `(market, selection)` stays unambiguous, but the OddsPapi `1x2` twin lands on `3way` → the two feeds do not share a key for soccer match result); OddsPapi `spreads-european` → `spread` (3-way); OddsPapi `result` vs `fulltime` (OT inclusion) both need `full`/`reg` mapping; SharpSports `3-way` alias exists but `Moneyline` on soccer is 2-way (draw-no-bet-like) — verify.

### 1.8 Selections / outcomes — canonical outcome key

| Provider | How an outcome is keyed | Examples **[LIVE]** |
|---|---|---|
| OpticOdds | odd `id` = `{game_id}:{sportsbook_id}:{market_id}:{normalized_selection[_line_points]}` (REST rows use display-cased sportsbook in docs; live REST and SSE both lowercase); fields `selection`, `normalized_selection`, `selection_line`, `points`, `player_id`, `team_id`, `grouping_key`; docs: the id "is not guaranteed to be of any specific format" → build your own composite key | `42573-28098-2026-09-04:pinnacle:moneyline:ipswich_town_fc`; `…:kalshi:1st_half_total_goals:over_2_5` (`selection: ""`, `selection_line: "over"`, `points: 2.5`); `…:draftkings:player_outside_box_shots_on_target:abdul_fatawu_over_1_5` (`player_id: 37115F112AA7`); `…:draftkings:5th_inning_correct_score:st_louis_cardinals_4_3` (`selection_line: "4:3"`) |
| OddsPapi | `oddsId` = `{fixtureId}:{bookmaker}:{outcomeId}:{playerId}`; book-independent selection key `{fixtureId}:{outcomeId}:{playerId}`; `outcomeName` from `/markets` (`'1'`, `'X'`, `'2'`, `Over`, `Under`, `Yes`, `No`, `Odd`, `Even`, `No Goal`); `participantsRotated` per book flips 1/2 | `id1000001772221244:pinnacle:101030:0`, `id1000001772221240:3et:102732:103335` (player 103335); Kalshi rows add `meta.bookmakerLayOutcomeId` (`KXEPLTOTAL-26SEP04IPSLFC-3:no`) |
| SharpSports | `MarketSelection.id` `MRKT_…` = one side of a `MarketOffer` (`MKTO_…`) = `(event, market, segment, proposition, position[, player|team])`; the line is **not** part of identity — `(MRKT_, book abbr, line)` identifies a quote | `MRKT_3510f6e1371c414491926c4a84e2ed68` position `Ipswich Town FC` (`positionId TEAM_fa74…`); `Over`/`Under` (`positionId null`); `Draw`; `Yes`/`No`; `Liverpool FC 3-1`; `4+` |

Canonical selection key **[CODE]** (`canon_selection`): `home | away | draw | over | under | yes | no | team:<id> | player:<id>[:over|:under|:<slug>] | other:<slug>`.

| Canonical `selection` | OpticOdds derivation | OddsPapi derivation | SharpSports derivation |
|---|---|---|---|
| `home` / `away` | `team_id` == fixture `home_competitors[0].id` / `away_competitors[0].id`; else `selection` text == `home_team_display` / `away_team_display` (trailing `±n.n` stripped) | `outcomeName` `'1'` → `home`, `'2'` → `away`, swapped when `bookmakers[bk].participantsRotated` | `position` == `contestantHome.fullName` / `contestantAway.fullName`, or `positionId` == contestant `id` |
| `draw` | `selection` ∈ `Draw|X|Tie` | `outcomeName` `'X'` | `position` `Draw` |
| `over` / `under` | `selection_line` `over`/`under` (`selection` may be `""`) | `outcomeName` `Over`/`Under` | `position` `Over`/`Under` |
| `yes` / `no` | **[GAP]** `selection_line` `yes`/`no` is not consumed by the OpticOdds normalizer (falls through to `player:<id>:<slug(name)>` or `other:`) | `outcomeName` `Yes`/`No` | `position` `Yes`/`No` |
| `team:<id>:over` (team totals) | `team:<OpticOdds team_id>:over` | `team:home:over` / `team:away:over` (from `marketType` suffix `team1`/`team2`) | `team:<TEAM_id>:over` (from `marketOffers[].team.id`) — **three different id spaces [GAP]** |
| `player:<id>:over` (player props) | `player:<OpticOdds player_id>:over` | `player:<OddsPapi playerId>:over` | `player:<PLYR_id>:over` — **three id spaces [GAP]**; requires `player_xref` (§3.3) |
| `other:<slug>` | correct score, winning margin, race-to, etc. | `outcomeName` slug | `position` slug |

The canonical tradeable key is `(book_id, fixture_id, market, period, selection, line)` **[CODE]** (`quotes_latest` ORDER BY); `line` is `Nullable(Float64)` and is the handicap/total/prop threshold **as the selection sees it** (spread sign flipped for the away side; totals positive).

---

## 2. Price semantics

### 2.1 Price formats and conversions

| Provider | Native price field(s) | Format | Canonical mapping **[CODE]** |
|---|---|---|---|
| OpticOdds | `price` (number) | `odds_format` param: `AMERICAN` (observed default: `442`, `-217`, `-10421`), `DECIMAL`, `PROBABILITY`, `MALAY`, `HONG_KONG`, `INDONESIAN`; exchange/PM prices are **fee-adjusted by default**, `exclude_fees=true` for raw (`odds_mlb_exfees.json`) | `price_us = int(price)`, `price_dec = american_to_decimal(price)` |
| OddsPapi | `price` (decimal, required), `priceAmerican` (int, nullable), `priceFractional` (string, nullable); CLV rows may carry placeholders `priceAmerican: 0`, `priceFractional: ""` | decimal always present | `price_dec = price`, `price_us = priceAmerican or decimal_to_american(price)` |
| SharpSports | `odds` (int American), `impliedProbability` (float; "also equal to the share price for prediction markets") | American | `price_us = odds`, `price_dec = american_to_decimal(odds)`; `impliedProbability` kept in `extra.implied` |

`american_to_decimal` / `decimal_to_american` live in `models.py`; zero/≤1 inputs return `None`.

### 2.2 Lines

| Provider | Field | Semantics | Canonical `line` |
|---|---|---|---|
| OpticOdds | `points` (and `selection_points` on SSE) | per selection; spreads already signed for the named team (`+1_5` / `-1_5` in the id); totals positive | `line = points` |
| OddsPapi | `Market.handicap` (via `outcomeId → marketId`) | one value per market; spreads relative to participant 1 (`-0.5` with outcomes `'1'`/`'2'`); totals = threshold; `0.0` lineless | `line = handicap`, negated for `away` on `spread` |
| SharpSports | `Price.line` | per (selection, book, line); position-relative for spreads; `0.0` for lineless in `/prices`, `null` in `MarketSelection.prices` | `line = Price.line` (**[GAP]** `0.0` is stored as `0.0`, not `NULL`, for moneylines) |

### 2.3 Main line flags and alternates

| Provider | Flag | Semantics **[DOC]/[LIVE]** |
|---|---|---|
| OpticOdds | `is_main` (bool, required) | the book's main (most balanced) line; alternates `false`. **Main-line promotion emits no `locked-odds`** when alternates exist — leave `is_main` unset on the stream and track the flag per selection. In the EPL sample 1,965 `true` / 1,349 `false`. |
| OddsPapi | `mainLine` (bool, **nullable and often absent**) | "the bookmaker's main line for the market type"; in the EPL sample DraftKings 727/896 rows had no `mainLine`, FanDuel 361/566, Pinnacle 145/289, Kalshi 49/124 |
| SharpSports | `Price.main` (bool) | `false` ⇒ alt line; `lineAvailability` lists all lines per book |

Canonical: `quotes.is_main Nullable(Bool)` **[CODE]**.

### 2.4 Active / suspended / stale flags

| Provider | Signal | Where | Semantics |
|---|---|---|---|
| OpticOdds | `locked-odds` SSE event | stream | selection suspended/removed **with its last price**; REST `/fixtures/odds` simply omits suspended odds. `quotes.event_kind = 'lock'`, `active = false` **[CODE]** |
| OpticOdds | `fixture-status` SSE event (`include_fixture_updates=true`) | stream | `old_status → new_status` ∈ `live|half|unplayed|completed|cancelled|suspended|delayed` |
| OpticOdds | `GET /sportsbooks/last-polled` | REST | `{league{id,name,numerical_id}, fixture_id, sportsbooks[{id,name,timestamp (unix s)}]}` — per-book polling heartbeat (`sporttrade` timestamp 1779664780 vs `draftkings_predictions` 1788420267 ⇒ 100 days stale) |
| OddsPapi | `OddQuote.active` (required), `marketActive` (nullable/absent) | every quote | selection / whole-market availability; `quotes.active = active and marketActive is not False` **[CODE]** |
| OddsPapi | `BookmakerFixtureMeta.hasOdds`, `staleOdds` ("Critical for trading"), `suspended`, `participantsRotated`, `updatedAt` | `bookmakers` map on `/fixtures/odds*` and WS `bookmakers` channel | per (fixture, book) gate; **[CODE]** only `participantsRotated` is consumed (`OddsPapiNormalizer.rotated`); `staleOdds`/`suspended`/`hasOdds` are archived raw but not applied **[GAP]** |
| OddsPapi | `Bookmaker.staleThresholdSec`, `lastOddsAt`, `staleOddsSince`, `maxDelay*InSec`, `websocketLive` | `GET /bookmakers` | key-level per-book health; `staleThresholdSec` 240 for most, 4,770 `bookmaker.eu`, 24,048 `vertex` |
| SharpSports | `Price.live` (bool), `Price.main` | every price | `live` = "updated since the event began"; **no suspended flag, no timestamp**; absence of a book under a selection ⇒ not offered |
| SharpSports | `Book.oddsFeedActive`, `betPlaceAvailability{abbr:bool}` | catalogue / selection | coverage proxies |

Trading gate to implement (OddsPapi wording): `active ∧ marketActive≠false ∧ hasOdds ∧ ¬staleOdds ∧ ¬suspended ∧ (now − changedAt) ≤ 1000·maxDelay{Live|Pregame}InSec`.

### 2.5 Limits and order-book depth

| Provider | Field | Shape **[LIVE]** | Units | Canonical |
|---|---|---|---|---|
| OpticOdds | `limits` | `{"max": 4500}` (Pinnacle ML), `{"max": 360}` (Kalshi = top-of-book size), `{"max": 23000}` (BetOnline); docs prose also shows `{"max_stake": 1000}` | stake in the book's base currency (undocumented) | `quotes.limit_max = limits.max or limits.max_stake` **[CODE]** |
| OpticOdds | `order_book` | `[[price, size], …]` one-sided back ladder in the requested odds format, best first, worse deeper (Kalshi `[[424,360],[396,399.57],…,[-3476,246.38]]`; Polymarket `[[-9900,62.37]]`; Prophet X `[[1274,38.46]]`; Novig `[[-2400,192]]`) | size in the exchange's base currency (USD) | `order_book_levels` rows `side='back'`, `level=i`, `price=lvl[0]` (**note: stored in the native odds format, i.e. American here, although the column comment says decimal [GAP]**), `size=lvl[1]` |
| OpticOdds | `source_ids` | Kalshi `{market_id: "KXMLBHR-26SEP032140ATHSEA-SEACRALEIGH29-1", selection_id: "yes"}`; Polymarket `{selection_id: "<77-digit clobTokenId>"}`; Prophet X `{event_id, selection_id}`; Novig `{event_id, market_id, selection_id}` (UUIDs); BetOnline `{event_id}` | venue-native routing ids | `order_book_levels.venue_market_id = source_ids.market_id` (empty for Polymarket/Prophet X rows **[GAP]**); full object kept in `quotes.extra.source_ids` |
| OpticOdds (non-sport) | `outcomes.{yes,no}.{best_bid,best_ask,spread,last_trade_price,tick_size,bids[{price,size}],asks[{price,size}]}` | full two-sided book, prices 0–1 (0 = "not available" sentinel), sizes in contracts (fractional) | contracts | `OrderBookLevel(side='bid'|'ask', price=0..1)` via `pm_snapshot_levels` **[CODE]** |
| OddsPapi | `limit` (number, nullable) + `Bookmaker.limitCurrency` | Pinnacle `4104.54`… per side (`19354` on a −645 favourite vs `3000` on the dog in docs); Kalshi `4104.54`; null for DK/FD | `limitCurrency` USD (`pinnacle`, `kalshi`, `polymarket`, `circasports`, `sx.bet`, `paradisewager`, `vertex`), EUR (`3et`, `betfair-ex`, `punter.io`, `sharpbet`), null otherwise → normalize with `/currencies` (USD base, inferred) | `quotes.limit_max = limit` (currency not stored **[GAP]**) |
| OddsPapi | `meta` (free-form JSON) | `kalshi`/`polymarket`: `{back:[{price,limit,cents,size}], lay:[…], bookmakerLayOutcomeId}`; `betfair-ex`: `{availableToBack:[{price,size}]}`; `sx.bet`: `{back:[{price,limit,cents}]}`; `cents = 1/price`, `limit = size × cents` (USD notional) | decimal price; `size` contracts; `limit` USD | `order_book_levels` rows for `meta.back[]` / `meta.lay[]` only (`price`, `size or limit`) **[CODE]**; `availableToBack` not parsed **[GAP]** |
| SharpSports | — | no limits, no depth; `marketOfferVolume`/`marketSelectionVolume` (int, prediction-market books only: Kalshi `36527`) | contracts/volume | `quotes.limit_max = NULL`; volumes not stored **[GAP]** |

### 2.6 Timestamps, clocks, and per-quote latency

| Provider | Clock | Field | Unit | Meaning |
|---|---|---|---|---|
| OpticOdds | book/poll | `timestamp` on every odd | float seconds (`1788419283.5209184`); historical `entries[].timestamp` int seconds | "when the price was posted"; batch events share one timestamp |
| OpticOdds | stream | SSE `id:` / `entry_id` `<epoch_ms>-<seq>` (`1788420576710-0`) | ms | gateway emit order; **`last_entry_id` replay does not work** (four reconnect tests restarted at "now") **[LIVE]** |
| OpticOdds | server | `ping` event `data: 2026-09-03T07:29:41Z` every ~5 s (8 in a 3,581-line capture) | s | clock-drift reference |
| OpticOdds | PM stream | `timestamp_ns` (`1787680501517000000`, ms precision; Kalshi values unusable — 0/hour-rounded **[LIVE]**) | ns | book capture time |
| OddsPapi | book | `bookmakerChangedAt` | epoch ms | bookmaker's own change time; absent for scraped books (many DK/FD rows) |
| OddsPapi | gateway | `changedAt` (required) | epoch ms | gateway accept time; also the historical map key (as a string) |
| OddsPapi | egress | WS envelope `ts` (= ms prefix of `entryId`) | epoch ms | emit time |
| OddsPapi | schedule | `startTime` s; `trueStartTime`/`trueEndTime`/`scores.*.updatedAt`/`bookmakers.*.updatedAt` ISO µs | mixed | "schedule times are seconds, odds-update times are milliseconds" |
| SharpSports | — | **none on `/prices` or `MarketSelection.prices`** | — | stamp at receive; historic timeseries carries `windowStartTime`/`windowEndTime` ISO with `consensus{open,close}` and `books[{id,abbr,name,open{line,odds,impliedProbability,marketOfferVolume,marketSelectionVolume},close{…}}]` (`rollup` `5m|15m|1h|4h|1d`; observed keys from `msel_ts_5m.json`) |

Canonical columns **[CODE]**: `recv_ns` (our monotonic receive time, authoritative), `source_ts_ms` (OpticOdds `timestamp×1000`; OddsPapi `bookmakerChangedAt or changedAt`; SharpSports `NULL`), `gateway_ts_ms` (OddsPapi WS `ts` when known else `changedAt`; OpticOdds `NULL` **[GAP]** — the SSE `entry_id` ms prefix is not stored in `gateway_ts_ms`, only `provider_odd_id`).

Per-quote latency decomposition:

| Metric | OpticOdds | OddsPapi | SharpSports |
|---|---|---|---|
| Book → aggregator | not observable | `changedAt − bookmakerChangedAt` (Pinnacle ≈ 359 ms doc example) | — |
| Aggregator → emit | `entry_id_ms − timestamp×1000` | `ts − changedAt` (≈ 100 ms) | — |
| Emit → us | `recv_ns/1e6 − entry_id_ms` (p50 7 ms baseball / 32 ms soccer, p99 0.2–0.33 s **[LIVE]**) | `recv_ns/1e6 − ts` (≈ 108 ms from `oddspapi-us1` to the probe host) | poll latency: `/prices?eventId=` 0.28 s, `?league=MLB` 2–7 s |
| End-to-end quote age | `recv_ns/1e6 − timestamp×1000` | `recv_ns/1e6 − (bookmakerChangedAt or changedAt)` | `recv_ns − poll_start_ns` (+ unknown backend refresh cadence) |
| Implemented | `u3.quote_latency` view: `quantile(0.5/0.99)(recv_ns/1e6 − source_ts_ms)` per `provider, book_id, minute` where `source_ts_ms IS NOT NULL` **[CODE]** | same view | excluded (NULL) |

### 2.7 Event kinds and the quote state machine

| `quotes.event_kind` **[CODE]** | Produced by | Meaning | `active` |
|---|---|---|---|
| `snapshot` | OpticOdds REST `/fixtures/odds` (`quotes_from_fixture_rows`), SharpSports `/prices` poll, OddsPapi REST `/fixtures/odds*` when passed `kind='snapshot'` | full-state observation; absence of a previously seen key in a later snapshot means the book pulled it (must be inferred by the board, not stored) | `true` (OpticOdds/SharpSports), `active ∧ marketActive` (OddsPapi) |
| `update` | OpticOdds SSE `odds`, OddsPapi WS `odds` | latest-state delta; OddsPapi may coalesce ("Treat every message as a state update, not a ledger") | as above |
| `lock` | OpticOdds SSE `locked-odds` | suspension/removal with the last price | `false` |

State transitions the board must implement: OpticOdds main-line move without alternates = `lock(old)` + `update(new)`; with alternates = `update(new, is_main=true)` + `update(old, is_main=false)` and **no lock**; OddsPapi deactivation = `update(active=false)` (only visible on WS or on `/fixtures/odds/main?since=`); SharpSports removal = key absent from the next snapshot. Reconnects on either stream require a REST re-snapshot (OpticOdds replay is broken **[LIVE]**; OddsPapi `snapshot_required` control frames).

---

## 3. Canonical schema

### 3.1 Implemented today (`schemas/clickhouse.sql`, database `u3`)

**`u3.quotes`** — tick stream, one row per (provider, book, selection, line) observation. `ENGINE = MergeTree PARTITION BY toDate(recv_ts) ORDER BY (fixture_id, market, period, selection, book_id, recv_ns) TTL toDate(recv_ts) + INTERVAL 400 DAY SETTINGS index_granularity = 8192`.

| Column | Type | Source **[CODE]** |
|---|---|---|
| `recv_ns` | `UInt64` | our receive time |
| `recv_ts` | `DateTime64(3) MATERIALIZED toDateTime64(recv_ns / 1e9, 3)` | derived |
| `provider` | `LowCardinality(String)` | `opticodds` / `oddspapi` / `sharpsports` |
| `book_id` | `LowCardinality(String)` | `BookRegistry.resolve` |
| `provider_book` | `LowCardinality(String)` | OpticOdds `sportsbook` (display name), OddsPapi slug, SharpSports `abbr` |
| `fixture_id` | `String` | canonical (OpticOdds id or `<provider>:<id>`) |
| `provider_fixture_id` | `String` | OpticOdds `fixture_id`/`id`, OddsPapi `fixtureId`, SharpSports `eventId` |
| `market` | `LowCardinality(String)` | canonical market key |
| `period` | `LowCardinality(String)` | canonical period |
| `selection` | `String` | canonical selection key |
| `line` | `Nullable(Float64)` | §2.2 |
| `price_dec` | `Nullable(Float64)` | §2.1 |
| `price_us` | `Nullable(Int32)` | §2.1 |
| `is_main` | `Nullable(Bool)` | `is_main` / `mainLine` / `main` |
| `active` | `Bool` | OpticOdds `event != locked-odds`; OddsPapi `active ∧ marketActive`; SharpSports always `true` |
| `limit_max` | `Nullable(Float64)` | `limits.max|max_stake` / `limit` / NULL |
| `source_ts_ms` | `Nullable(Int64)` | §2.6 |
| `gateway_ts_ms` | `Nullable(Int64)` | §2.6 |
| `provider_market` | `String` | OpticOdds `market`, OddsPapi `marketName` (or `str(marketId)`), SharpSports `Market.name` |
| `provider_selection` | `String` | OpticOdds `selection`/`name`, OddsPapi `outcomeName`, SharpSports `position` |
| `provider_odd_id` | `String` | OpticOdds odd `id`, OddsPapi `oddsId`, SharpSports `"<MRKT_id>|<abbr>|<line>"` |
| `player_id` | `Nullable(String)` | **provider-native** player id |
| `team_id` | `Nullable(String)` | **provider-native** team id |
| `event_kind` | `LowCardinality(String)` | `update` / `lock` / `snapshot` |
| `grouping_key` | `Nullable(String)` | OpticOdds `grouping_key` |
| `extra` | `String CODEC(ZSTD(3))` | JSON: OpticOdds `{is_live, source_ids}`; OddsPapi `{bookmakerMarketId, bookmakerOutcomeId}`; SharpSports `{live, implied, market_selection_id}` |

**`u3.order_book_levels`** — `ENGINE = MergeTree PARTITION BY toDate(recv_ts) ORDER BY (fixture_id, book_id, venue_market_id, selection, side, recv_ns, level) TTL … 180 DAY`: `recv_ns UInt64, recv_ts DateTime64(3) MATERIALIZED, provider LowCardinality(String), book_id LowCardinality(String), fixture_id String, market LowCardinality(String), period LowCardinality(String), selection String, venue_market_id String, side LowCardinality(String) (back|lay|bid|ask), level UInt8, price Float64, size Nullable(Float64), source_ts_ms Nullable(Int64), provider_odd_id String`.

**`u3.fixture_xref`** — `ENGINE = ReplacingMergeTree(updated_ns) ORDER BY fixture_id`: `fixture_id String, sport LowCardinality(String), league LowCardinality(String), start_time_ms Nullable(Int64), home Nullable(String), away Nullable(String), status Nullable(String), opticodds_id Nullable(String), opticodds_game_id Nullable(String), oddspapi_id Nullable(String), sharpsports_id Nullable(String), betradar_id Nullable(String), pinnacle_id Nullable(String), statsperform_id Nullable(String), sportradar_id Nullable(String), the_odds_api_id Nullable(String), home_rot Nullable(Int32), away_rot Nullable(Int32), updated_ns UInt64` — populated from `FixtureRef.row()` (`FixtureRegistry` is the in-memory twin).

**`u3.quotes_latest`** — `MATERIALIZED VIEW … ENGINE = ReplacingMergeTree(recv_ns) ORDER BY (fixture_id, market, period, selection, line, book_id)` selecting `recv_ns, provider, book_id, fixture_id, market, period, selection, line, price_dec, price_us, is_main, active, limit_max, source_ts_ms, event_kind` — the "board".

**`u3.quote_latency`** — `VIEW`: `provider, book_id, toStartOfMinute(recv_ts) AS minute, quantile(0.5)(recv_ns / 1e6 - source_ts_ms) AS p50_ms, quantile(0.99)(…) AS p99_ms, count() AS n` where `source_ts_ms IS NOT NULL`.

Canonical Python records **[CODE]** (`u3ingest/canonical/models.py`): `Quote` (same fields as `u3.quotes` minus `recv_ts`), `OrderBookLevel`, `FixtureRef` (same fields as `u3.fixture_xref`); `Quote.row()` / `FixtureRef.row()` produce the insert dicts; `ClickHouseSink` inserts with `async_insert=1`.

### 3.2 Raw archive layout (implemented)

`u3ingest/sinks/raw.py`: `<U3_RAW_DIR>/<provider>/<stream>/dt=YYYY-MM-DD/hour=HH/<stream>-<process_start_ms>.jsonl.gz`; each line `{"recv_ns": int, "provider": str, "stream": str, "seq": int, "meta": {...}, "body": <provider payload>}`. Streams in use: `opticodds/sse-odds-<sport>`, `opticodds/sse-prediction-markets-<…>`, `oddspapi/ws-<channels>`, `<provider>/snapshot-<league|sports>`, `bootstrap/registries` (meta `{provider, endpoint, league|sportId}` for `/fixtures/active`, `/fixtures`, `/markets`, `/events`), `sharpsports/prices-<league>`. `u3ingest/sinks/gcs.py` uploads closed hourly files to `gs://<bucket>/raw/...` mirroring the local path (`.gcs_manifest.jsonl` records uploads; current hour skipped). `u3ingest/replay.py` rebuilds `quotes`/`order_book_levels` (Parquet/DuckDB) from the archive by merging files on `recv_ns` and re-running the bootstrap files first.

Planned additions to `meta` per stream **[GAP]**: OpticOdds SSE `{event, id}` already; add the redacted request URL and `x-ratelimit-*` headers on REST snapshots; OddsPapi WS already stores `{channel, type, ts, entryId, raw_len}` plus control frames (`login_ok` without `apiKey`).

Retention policy (raw is the system of record; derived tables are rebuildable via `u3-ingest replay`):

| Layer | Path / table | Retention | Rationale |
|---|---|---|---|
| Raw stream archive | `<provider>/<stream>/dt=…/hour=…/*.jsonl.gz` → `gs://<bucket>/raw/…` | permanent | provider history windows are short: OpticOdds tick history ~57–60 days (**[LIVE]**, docs say 2 months) and OLV/CLV ≥ 1 year; OddsPapi odds history/CLV ≈ 220–230 days, settlement ≥ 1 year; SharpSports `/prices` is live-only (past events return `markets: []`) with OHLC history at a 5-minute floor |
| Bootstrap registries | `bootstrap/registries/…` (`/fixtures/active`, `/fixtures`, `/markets`, `/events`) | permanent | replays need the id crosswalk as of that day |
| `u3.quotes` | ClickHouse | 400 days (TTL) | one full season + lookback |
| `u3.order_book_levels` | ClickHouse | 180 days (TTL) | depth is bulky (1.3 M levels per 75 s at probe rates) |
| `u3.fixture_xref` and planned dimensions | ClickHouse | permanent | small |

### 3.3 Planned tables (not yet in `schemas/clickhouse.sql`)

Types are ClickHouse. Every dimension keeps `first_seen_ns UInt64`, `updated_ns UInt64` and uses `ReplacingMergeTree(updated_ns)`; provider-native ids are always `String`.

**`sports`** — `ORDER BY sport`: `sport LowCardinality(String)` (OpticOdds slug), `opticodds_id String`, `opticodds_numerical_id Nullable(Int32)`, `oddspapi_sport_id Nullable(Int32)`, `sharpsports_sport_id Nullable(String)` (`SPRT_*`), `name String`.

**`leagues`** — `ORDER BY (sport, league)`: `sport`, `league LowCardinality(String)` (OpticOdds slug), `opticodds_numerical_id Nullable(Int32)`, `opticodds_region Nullable(String)`, `oddspapi_tournament_id Nullable(Int32)`, `oddspapi_category_name Nullable(String)`, `sharpsports_league_id Nullable(String)` (`LGUE_*`), `sharpsports_abbr Nullable(String)`, `sharpsports_sportradar_id Nullable(String)`, `sharpsports_sportsdataio_id Nullable(String)`, `name String`.

**`fixtures`** — `ORDER BY (sport, league, start_time_ms, fixture_id)`: `fixture_id String`, `sport`, `league`, `start_time_ms Int64`, `true_start_ms Nullable(Int64)`, `true_end_ms Nullable(Int64)`, `status LowCardinality(String)` (canonical: `scheduled|live|completed|cancelled|suspended|delayed`), `home_team_id Nullable(String)`, `away_team_id Nullable(String)`, `home_name String`, `away_name String`, `venue_name Nullable(String)`, `venue_neutral Nullable(Bool)`, `season_year Nullable(String)`, `season_type Nullable(String)`, `season_week Nullable(String)`, `home_starter_id Nullable(String)`, `away_starter_id Nullable(String)`, `oddspapi_expected_periods Nullable(Int8)`, `oddspapi_period_length Nullable(Int8)`. (`fixture_xref` stays the id crosswalk; add `oddspapi_betgenius_id`, `oddspapi_flashscore_id`, `oddspapi_sofascore_id`, `oddspapi_mollybet_id`, `sharpsports_sportsdataio_id`, `resolution_method LowCardinality(String)` ∈ `opticoddsId|oddsjamId|team_time|rotation|book_native|manual`, `resolution_score Float32`.)

**`teams`** — `ORDER BY (sport, league, team_id)`: `team_id String` (OpticOdds id), `base_id Nullable(Int32)`, `numerical_id Nullable(Int32)`, `name String`, `abbreviation Nullable(String)`, `city Nullable(String)`, `conference Nullable(String)`, `division Nullable(String)`, `statsperform_id Nullable(String)`, `is_active Nullable(Bool)`.

**`team_xref`** — `ORDER BY (provider, provider_team_id)`: `provider LowCardinality(String)`, `provider_team_id String` (OddsPapi `participantId`, SharpSports `TEAM_*`), `team_id String`, `provider_name String`, `provider_abbr Nullable(String)`, `sharpsports_sportradar_id Nullable(String)`, `sharpsports_sportsdataio_id Nullable(String)`, `rotation_number Nullable(Int32)`, `method LowCardinality(String)` (`oddsjamId|name|rotation|manual`), `score Float32`.

**`players`** — `ORDER BY (sport, league, player_id)`: `player_id String` (OpticOdds id), `base_id Nullable(Int32)`, `name String`, `first_name`, `last_name`, `position Nullable(String)`, `number Nullable(Int16)`, `team_id Nullable(String)`, `statsperform_id Nullable(String)`, `is_active Nullable(Bool)`.

**`player_xref`** — `ORDER BY (provider, provider_player_id)`: `provider`, `provider_player_id String` (OddsPapi `playerId`, SharpSports `PLYR_*`), `player_id String`, `provider_name String` (OddsPapi "Last, First"), `sharpsports_oddsjam_id Nullable(String)`, `sharpsports_sportradar_id Nullable(String)`, `sharpsports_sportsdataio_id Nullable(String)`, `method`, `score`.

**`books`** — `ORDER BY book_id`: `book_id LowCardinality(String)`, `name String`, `kind LowCardinality(String)` (`retail|sharp|offshore|exchange|prediction_market|dfs`), `is_exchange Bool`, `two_sided Bool`, `limit_currency Nullable(String)`, `opticodds_is_onshore Nullable(Bool)`.

**`book_xref`** — `ORDER BY (provider, provider_book)`: `provider`, `provider_book String` (OpticOdds `id`, OddsPapi `slug`, SharpSports `abbr`), `provider_book_id Nullable(String)` (SharpSports `BOOK_*`), `provider_name String`, `book_id`, `variant LowCardinality(String)` (`main|lay|usa|uk|pick2|…`), `active Nullable(Bool)` (OpticOdds `is_active` / OddsPapi `active` / SharpSports `status='active'`), `prices Nullable(Bool)` (SharpSports `oddsFeedActive`), `ws_live Nullable(Bool)`, `max_delay_pregame_s Nullable(Float32)`, `max_delay_live_s Nullable(Float32)`, `max_delay_main_s Nullable(Float32)`, `stale_threshold_s Nullable(Float32)`, `player_props Nullable(Bool)`.

**`markets`** — `ORDER BY (market, period)`: `market LowCardinality(String)`, `period LowCardinality(String)`, `family LowCardinality(String)` (`moneyline|3way|spread|total|team_total|player|team_prop|other|future|prediction`), `metric Nullable(String)`, `n_way Nullable(Int8)`, `has_line Bool`, `subject LowCardinality(String)` (`match|team|player`).

**`market_xref`** — `ORDER BY (provider, provider_market_key)`: `provider`, `provider_market_key String` (OpticOdds `market_id`; OddsPapi `marketId` as string; SharpSports `MKT_*`), `provider_market_name String`, `provider_market_type Nullable(String)` (OpticOdds `market_type_id`; OddsPapi `marketType`; SharpSports `type|proposition`), `provider_period Nullable(String)` (OddsPapi `period`; SharpSports `segmentId`), `provider_line Nullable(Float64)` (OddsPapi `handicap`), `provider_metric Nullable(String)` (SharpSports `metric.id`), `oddsjam_market_key Nullable(String)` (SharpSports `Market.oddsjamId`, joins to OpticOdds `market_id`), `sportradar_market_id Nullable(String)`, `the_odds_api_market_key Nullable(String)`, `market`, `period`, `method`, `reviewed Bool`.

**`quote_snapshots`** — periodic full-board captures (REST `/fixtures/odds`, `/fixtures/odds/main`, `/prices`): same columns as `quotes` plus `snapshot_id String` (raw archive `seq`), `endpoint LowCardinality(String)`; `ORDER BY (snapshot_id, fixture_id, market, period, selection, book_id)`. Today snapshots are written into `quotes` with `event_kind='snapshot'` **[CODE]**.

**`book_status`** — OddsPapi `bookmakers` channel and `/bookmakers` health: `recv_ns`, `provider`, `book_id`, `fixture_id Nullable(String)`, `has_odds Nullable(Bool)`, `stale_odds Nullable(Bool)`, `suspended Nullable(Bool)`, `participants_rotated Nullable(Bool)`, `bookmaker_fixture_id Nullable(String)`, `last_odds_at_ms Nullable(Int64)`, `stale_odds_since_ms Nullable(Int64)`, `updated_at_ms Nullable(Int64)`; also OpticOdds `/sportsbooks/last-polled` rows (`fixture_id`, `book_id`, `polled_at_ms`).

**`results`** — `ORDER BY (fixture_id, recv_ns)`: `fixture_id`, `provider`, `status`, `home_total Nullable(Float32)`, `away_total Nullable(Float32)`, `periods String` (JSON of OpticOdds `result.scores.{home,away}.periods` / OddsPapi `scores.{period}` map), `in_play String` (JSON: OpticOdds `in_play_data{period,period_number,clock,last_play}`; OddsPapi `clock{currentPeriod,currentTime,remainingTime,remainingTimeInPeriod,stopped}`), `source_ts_ms`.

**`settlements`** — `ORDER BY (fixture_id, market, period, selection, line, provider, recv_ns)`: canonical key + `provider`, `result LowCardinality(String)` (canonical `win|lose|push|half_win|half_lose|void|pending`), `provider_result String` (OpticOdds `/grader/odds` `Won|Lost|Refunded|Half Won|Half Lost|Pending`; OddsPapi `/fixtures/settlement` `WIN|LOSE|PUSH|HALFWIN|HALFLOSS|CANCELLED|UNDECIDED`), `margin Nullable(Float64)`, `reason Nullable(String)` (`MISSING_PERIODS`, `REQUIRES_NON_SCORE_STATS`), `oddspapi_outcome_id Nullable(Int64)`, `oddspapi_player_id Nullable(Int64)`.

**`clv`** — `ORDER BY (fixture_id, book_id, market, period, selection, line)`: canonical key + `olv_price_dec`, `olv_ts_ms`, `olv_line`, `clv_price_dec`, `clv_ts_ms`, `clv_line`, `clv_active Nullable(Bool)`, `provider` (OpticOdds `/fixtures/odds/historical` `olv{price,points}`/`clv{price,points}`; OddsPapi `/fixtures/odds/clv` `olv`/`clv` `PricePoint`s), `provider_odd_id`.

**`injuries`** — `ORDER BY (sport, league, player_id, recv_ns)`: `provider`, `player_id`, `team_id`, `status String` (OpticOdds `status` `out|Day-To-Day|10-Day IL|…`, `type` (`Personal`); SharpSports free text `"Questionable - Knee"`), `designation Nullable(String)`, `description Nullable(String)`, `fixture_id Nullable(String)`, `played Nullable(Bool)` (SharpSports), `source_ts_ms`.

**`player_game_stats`** / **`team_game_stats`** — `ORDER BY (player_id|team_id, fixture_id, period, metric)`: `provider`, `fixture_id`, `period LowCardinality(String)`, `metric LowCardinality(String)` (OpticOdds stat keys from `/fixtures/player-results` `stats[{period, stats{}}]`; SharpSports `METR_*` from `/players/{id}/historicData` `stats[{metric{id,name},value}]`), `value Float64`, `game_date Date`.

### 3.4 ClickHouse engine / ordering notes

- `quotes`: keep `MergeTree` (append-only ledger); consider adding `line` to the ORDER BY after `selection` (alternate-line ladders are queried by line) and a skipping index on `provider_odd_id`. Partition by day is right for the 400-day TTL; expect O(10⁵) rows/min in season (75 s live run: 381,188 quotes + 1,311,005 order-book levels **[LIVE]**).
- `order_book_levels`: consider `TTL` 60–90 days and a `SummingMergeTree`-free design (levels are replaced, not summed).
- Dimensions/xrefs: `ReplacingMergeTree(updated_ns)` with `FINAL` in reads, or a `latest` MV.
- Board queries: `quotes_latest` must include `provider` in the ORDER BY if two providers quote the same book (they do: DraftKings via OpticOdds, OddsPapi and SharpSports) — today the later `recv_ns` wins regardless of provider **[GAP]**; either key by `(…, book_id, provider)` or pick a preferred provider per book in `book_xref`.
- Latency views: extend `quote_latency` with `gateway_ts_ms` deltas (`recv − gateway`, `gateway − source`) per provider.

---

## 4. Mapping QA

### 4.1 Coverage metrics (compute continuously; store in a `mapping_metrics` table keyed by `minute, provider, league, metric`)

| Metric | Definition (SQL sketch on the implemented tables) | Target / observed |
|---|---|---|
| Fixture resolution rate | `countIf(fixture_id NOT LIKE '%:%') / count()` from `fixture_xref` grouped by `oddspapi_id IS NOT NULL`, `sharpsports_id IS NOT NULL` | OddsPapi→OpticOdds ≥ 95 % for fixtures with OpticOdds odds (window: MLB 100 %, EPL 100 %, NCAAF 91 %); SharpSports ≥ 90 % (MLB 100 %, EPL 100 %, NCAAF 91 %) |
| Fixture join method mix | `resolution_method` counts (planned column; today: `opticodds_game_id IS NOT NULL` ⇒ id join, else fuzzy) | fuzzy share < 20 %; alarm when a league's id-join rate drops (e.g. SharpSports EPL/NCAAF have no `oddsjamId`) |
| Duplicate canonical ids | `SELECT opticodds_id, count() FROM fixture_xref WHERE opticodds_id != '' GROUP BY 1 HAVING count() > 1`; same for `oddspapi_id`, `sharpsports_id` | 0 |
| Start-time consistency | `abs(start_time_ms(provider A) − start_time_ms(provider B))` per matched pair | window: max 0 s, `>60 s` count 0 |
| Book resolution | `countIf(book_id LIKE '%:%')` in `quotes` per provider, and `BookRegistry.unknown` (logged as `unknown_books` by the pipeline reporter **[CODE]**) | 0 unknown for entitled books; today `oddspapi:sx_bet`, `oddspapi:3et`, … and `opticodds:robinhood`, … are expected until §1.6 seeds land |
| Market canonicalization | `countIf(market LIKE 'other:%') / count()` per provider, plus distinct `other:` keys ordered by volume | `other:` share < 10 % of volume; every `other:` key with > 1 % volume reviewed |
| Selection canonicalization | `countIf(selection LIKE 'other:%')`; `countIf(selection IN ('home','away') AND provider = 'sharpsports')` sanity per league | < 5 % |
| Cross-provider key overlap | per fixture: `uniqExact((market, period, selection, line))` present in ≥ 2 providers / present in any | rising over time; per-market breakdown reveals taxonomy misalignments (e.g. soccer `moneyline` vs `3way`) |
| Cross-provider price agreement | for the same `(book_id, fixture_id, market, period, selection, line)` quoted by two providers within 5 s: `abs(price_dec_A − price_dec_B)` | median 0; outliers flag wrong sides (spread sign, `participantsRotated`) |
| Team-name fuzzy quality | share of `_fuzzy` hits that resolved via team-pair-only fallback (league keys differed) | monitor; move to `team_xref` |
| Player xref coverage | `count(player_xref)` / distinct `quotes.player_id` per provider (planned) | measure; SharpSports `oddsjamId` exact-join rate first |
| Freshness | `quote_latency.p99_ms` per `provider, book_id`; OddsPapi `now − changedAt` vs `maxDelay*InSec`; OpticOdds `/sportsbooks/last-polled` age | alarm > 5 s pregame / > 2 s live for streamed books |
| Stale-book minutes | minutes with OddsPapi `staleOdds = true` per book (planned `book_status`) | per-book reliability ranking |

### 4.2 Unmapped-entity queues

| Queue | Producer **[CODE]** today | Persisted where (planned) | Row content |
|---|---|---|---|
| Unresolved fixtures | `FixtureRegistry.unresolved` dict keyed `"<league>|<home>|<away>|<start_ms>"` with hit counts; `report["unresolved_fuzzy"]` at bootstrap; canonical ids `oddspapi:<id>` / `sharpsports:<id>` in `quotes.fixture_id` | `mapping_queue` (`kind='fixture'`, `provider`, `provider_id`, `league`, `home`, `away`, `start_time_ms`, `candidates String` JSON, `first_seen_ns`, `status` ∈ `open|resolved|ignored`, `resolved_to`, `resolved_by`) | nearest OpticOdds candidates by start time (±6 h) with name similarity |
| Unknown books | `BookRegistry.unknown[(provider, slug)]` counter; `quotes.book_id LIKE '%:%'` | `mapping_queue` (`kind='book'`) | provider slug, display name, first/last seen, quote volume |
| Unmapped markets | `quotes.market LIKE 'other:%'` with `provider_market` | `mapping_queue` (`kind='market'`) | provider market key/name, sample selections, volume |
| Unmapped selections | `quotes.selection LIKE 'other:%'` | `mapping_queue` (`kind='selection'`) | provider selection text, market, examples |
| Unmatched teams | (none today) | `mapping_queue` (`kind='team'`) | OddsPapi `participantId`/`participantName`/`participantAbbr`, SharpSports `TEAM_` without `oddsjamId` hit |
| Unmatched players | (none today) | `mapping_queue` (`kind='player'`) | OddsPapi `playerId`/`playerName`, SharpSports `PLYR_` with unmatched `oddsjamId` |

### 4.3 Resolution procedures

1. **Fixtures.** Nightly and on every bootstrap: re-run steps 1–3 of §1.3.2 against the persisted `fixture_xref`; for `open` queue rows, propose candidates by (league, |Δstart| ≤ 6 h, `norm_team` token overlap ≥ 0.5) and, when both sides expose rotation numbers, auto-resolve on an unordered rotation-pair match. Manual resolution writes `fixture_xref` with `resolution_method='manual'`; never merge two OpticOdds ids into one canonical id — if OpticOdds has duplicates (placeholder permutations), keep the fixture whose `status != 'cancelled'` and low rotation numbers.
2. **Books.** On every bootstrap persist the three live catalogues (`/sportsbooks`, `/bookmakers`, `/books` + `/books?status=unsupported`) to `book_xref`; a new provider slug creates an `open` queue row with a suggested canonical id from `BookRegistry.normalize()`; state clones / payout variants (`betrivers_new_york_`, `draftkings_pick_6_`, `prizepicks_5_or_6_pick_flex_`) map to the parent book with `variant` set, lay-side ids (`betfair_exchange_lay_`) keep their own canonical id.
3. **Markets.** Weekly: load OpticOdds `GET /markets` (+ `/market-types`), OddsPapi `GET /markets?sportId=` (all six sports), SharpSports `GET /markets` (paged, `pageSize=1000`) into `market_xref`; auto-map by (a) SharpSports `Market.oddsjamId` == OpticOdds `market_id`, (b) OddsPapi `marketType`+`period` table, (c) name grammar; anything landing in `other:` with volume goes to the queue. Store `handicap`/segment/metric so alternate lines and periods are exact.
4. **Teams.** Bootstrap `teams` from OpticOdds `/teams?league=…&include_statsperform_id=true`; join SharpSports `/teams?league=LGUE_*` on `oddsjamId` (expected 100 % for US majors); map OddsPapi `participantId` via name/abbr within league, confirmed by the fixture join (participants of an id-joined fixture pair are the same two teams — derive `team_xref` rows from matched fixtures, which needs no fuzzy names at all).
5. **Players.** Same derivation trick: for an id-joined fixture, OddsPapi player-prop quotes (`playerId`, `playerName`) and OpticOdds quotes (`player_id`, `selection`) on the same canonical market/line can be paired by name within the fixture; SharpSports via `Player.oddsjamId`. Persist to `player_xref` with `method`.
6. **Regression guard.** A mapping change is applied by `replay` over the raw archive for the affected day and compared (`quotes` row counts per `market`/`selection`, `other:` share) before it is promoted.

### 4.4 SLIs and alarms for the mapping layer

| SLI | Source | Alarm |
|---|---|---|
| `fixture_unresolved_ratio` per provider/league | `fixture_xref` (`fixture_id LIKE '<provider>:%'`) | > 10 % for a league where OpticOdds has fixtures with odds |
| `fixture_join_drift` | daily diff of `opticodds_id` per `oddspapi_id` | any change (an OddsPapi fixture re-pointing to another OpticOdds id) |
| `book_unknown_quotes` | pipeline reporter `unknown_books` **[CODE]** / `quotes.book_id LIKE '%:%'` | > 0 for a book that is in the entitled catalogue |
| `market_other_share` | `quotes.market LIKE 'other:%'` by volume | > 10 % or a new `other:` key above 1 % |
| `selection_other_share` | `quotes.selection LIKE 'other:%'` | > 5 % on `moneyline|3way|spread|total|team_total` |
| `cross_provider_price_disagreement` | same canonical key + `book_id`, two providers, ≤ 5 s apart, `abs(price_dec_A − price_dec_B) > 0.02` | > 1 % of comparable pairs (indicates side/sign mapping errors) |
| `quote_age_p99_ms` per provider/book | `u3.quote_latency` | > 5,000 ms pregame / > 2,000 ms live for `websocketLive` books |
| `book_stale_minutes` | planned `book_status` (`staleOdds`, `lastOddsAt`, OpticOdds `last-polled`) | any streamed book stale > `staleThresholdSec` |
| `catalogue_drift` | daily diff of `/sportsbooks`, `/bookmakers`, `/books` vs `book_xref` | new/removed ids ⇒ queue row |

---

## 5. Known gaps and ambiguities (with operational resolution)

| # | Gap / ambiguity | Evidence | Resolution |
|---|---|---|---|
| 1 | `registry.BOOKS` contains OddsPapi slugs that are not in the 31 entitled slugs (`hardrock`, `thescore`, `novig`, `sporttrade`, `prizepicks`, `underdog`, `fanatics`, `betfair`) and misses live ones (`betfair-ex`, `sx.bet`, `bovada.lv`, `betus`, `betparx`, `ballybet`, `borgata`, `3et`, `198bet`, `4casters`, `duel`, `kaiyun`, `paradisewager`, `punter.io`, `sharpbet`, `singbet`, `vertex`) | `samples/oddspapi/bookmakers.json` | seed `BOOKS` from the live catalogues (§1.6 table); fix `betfair` → `betfair-ex` |
| 2 | OpticOdds ids with trailing underscore (`polymarket_usa_`, `betfair_exchange_lay_`) are matched only when the display name normalizes to the same string; `"Polymarket (USA)"` → `polymarket_usa` ≠ `polymarket_usa_` | `BookRegistry.normalize` strips trailing `_` | resolve OpticOdds books on `sportsbook_id` when present (SSE) and add display-name aliases to `BOOKS` |
| 3 | Team-total and player-prop selection keys embed provider-native ids (`team:home:over` vs `team:77CBFB371ED9:over` vs `team:TEAM_…:over`; `player:<int>` vs `player:<hex>` vs `player:PLYR_…`) | `normalize.py` for the three providers | route through `team_xref`/`player_xref` in the normalizers; until then cross-provider comparison is limited to match-level markets |
| 4 | OpticOdds `selection_line` values `yes`/`no`/`odd`/`even`/`exact`/`"3:1"` are not folded into `selection` | `OpticOddsNormalizer.quote` only handles `over`/`under` | extend `canon_selection` to accept `selection_line` explicitly |
| 5 | OddsPapi live `period` keys (`fulltime`, `p1`, `p2`, `result`, `null`) are not in `_OP_PERIOD` (which expects `1st-half`, `regular-time`, …) and pass through raw | `samples/oddspapi/markets_sport10.json` | map `result→full`, `fulltime→reg`, `p1/p2→1h/2h` (soccer, halves) — but `p1..p4` are quarters in basketball/football and periods in hockey: derive from `sport.sportId` + `expectedPeriods`/`periodLength` |
| 6 | Soccer match-result: OpticOdds `moneyline` (3 selections incl. `Draw`) maps to `moneyline`, OddsPapi `1x2` maps to `3way`, SharpSports has both `Moneyline` and `3-way` | side-by-side EPL sample | define `3way` = any market whose selection set includes `draw`; post-process OpticOdds/SharpSports soccer `moneyline` to `3way` when a `draw` selection exists on the same `grouping_key`/`MarketOffer` |
| 7 | OddsPapi `result` (incl. OT) vs `fulltime` (regulation) both currently map to `full`/raw; OpticOdds distinguishes with `(Incl. OT)` name suffixes; SharpSports uses `Bet.segmentDetail` only on bets | docs | canonical `period` `full` = including OT, `reg` = regulation; add explicit rules per provider |
| 8 | `quotes_latest` keyed without `provider`: DraftKings quoted by three providers overwrites itself | `schemas/clickhouse.sql` | add `provider` to the MV ORDER BY or a `preferred_provider` per book |
| 9 | `order_book_levels.price` for OpticOdds sports exchanges is stored in the requested odds format (American in our runs) while the model comment says decimal | `OpticOddsNormalizer.quote` | convert with `american_to_decimal` when `odds_format` is AMERICAN, or request `odds_format=DECIMAL` on exchange books |
| 10 | OddsPapi `meta.availableToBack` (Betfair) is not parsed; OddsPapi `limitCurrency` and `/currencies` not applied to `limit_max` | `OddsPapiNormalizer.quotes` | add an adapter keyed by slug; store `limit_currency` in `book_xref` and normalize to USD |
| 11 | OddsPapi per-(fixture, book) gates `staleOdds`/`suspended`/`hasOdds` are archived but not applied to `active` | `note_bookmakers` keeps only `participantsRotated` | keep a `(fixtureId, bookmaker)` gate map from the `bookmakers` channel and set `active=false` / emit `event_kind='lock'` transitions |
| 12 | SharpSports quotes have no timestamps; `/prices?league=` polls are 2–7 s and multi-MB; no suspension flag | `reference__prices.md`, probe | poll per `eventId` (0.3 s) for live events; treat absence-since-last-poll as suspension; keep `source_ts_ms = NULL` and never include SharpSports in latency SLIs |
| 13 | OpticOdds `last_entry_id` replay does not work; OddsPapi `odds` may not be in `replayChannels`; PM stream has no replay | probes | on every reconnect: REST re-hydration (`/fixtures/odds` ≤ 5 fixtures × ≤ 5 books; OddsPapi `/fixtures/odds/main?fixtureIds=…&since=`), mark a `stream_gap` row |
| 14 | Rotation-number and book-native id joins (§1.3.2 steps 4–5) unverified; `fliff` `bookmakerFixtureId` looks like an OpticOdds id | samples | run a one-off join over a full slate; if `bookmakers.fliff.bookmakerFixtureId == externalProviders.opticoddsId` holds, it is a second exact OpticOdds key |
| 15 | Betradar (`betradarId` int) vs Sportradar UUID (`sportradarId`) vs Stats Perform (`statsperform_id`) cannot be joined | §1.3.1 | keep as reference columns; revisit if a Sportradar/Opta crosswalk is licensed |
| 16 | OddsPapi `opticoddsId` coverage is bounded by OpticOdds' own universe (2,593/19,954 fixtures in the 3-day window; 149/1,223 baseball at bootstrap) — OddsPapi-only fixtures keep `oddspapi:<id>` ids forever | cross probe, README | fine for trading (no OpticOdds odds ⇒ no cross-provider edge), but downstream must not assume canonical ids are always OpticOdds ids |
| 17 | SharpSports lists whole seasons (EPL 360 events vs OpticOdds 20 active) and futures "events" with `startTime: null` | README, `ss_events.json` | skip events with `startTime IS NULL` from fixture resolution; register them as futures containers |
| 18 | SharpSports `bs` is `theScore` live but "ESPN BET" in docs; no OpticOdds `espn_bet` id exists | `books_active.json`, `sportsbooks.json` | canonical `thescore`; alias `espn_bet` → `thescore` in `book_xref` |
| 19 | Pinnacle in SharpSports is `status: unsupported` yet `oddsFeedActive: true` (`pn`, `BOOK_f6162b9d2dfc4403941994e7c045185d`) and `/books` default filter hides it | probe | bootstrap must call `/books?status=unsupported` too |
| 20 | Sport/league vocabulary in `fixture_xref.sport/league` mixes OpticOdds slugs, OddsPapi ints and SharpSports strings | `FixtureRegistry.add_*` | populate `sports`/`leagues` and normalize at insert |
| 21 | Non-sport prediction markets exist only on OpticOdds (`/stream/prediction-markets`, `canonical_id` always `""` on the stream; REST canonical events only for ≥ 2-platform matches) | oo-prediction-markets notes | canonical `fixture_id = "pm:<platform>:<source_market_id>"` as implemented in `pm_snapshot_levels`; join Kalshi↔Polymarket client-side via `/prediction-markets/canonical-events` `canonical_market_id` keyed on `source_market_id` |
| 22 | OpticOdds `limits` key name (`max` vs `max_stake`) and REST vs SSE odd-id casing differ across docs; live shows `max` and lowercase | samples | keep both readers; never join on raw odd ids across REST/SSE — rebuild the composite key |
| 23 | SharpSports moneyline `line` `0.0` is stored as `0.0` rather than `NULL`, so `(…, line)` keys differ from OpticOdds/OddsPapi (`NULL`) | `SharpSportsNormalizer.quotes` | map `line = NULL` when `proposition ∈ {moneyline, 3-way}` or `Market.name` has no line |
| 24 | OpticOdds `sport.numerical_id`/`league.numerical_id` inconsistent across pages (nfl 9 vs 367) | docs | never key on numerical ids |

---

## Appendix A — implementation cross-reference

| Concern | File / symbol **[CODE]** |
|---|---|
| Canonical records | `u3ingest/canonical/models.py`: `Quote`, `OrderBookLevel`, `FixtureRef`, `CANON_PERIODS`, `american_to_decimal`, `decimal_to_american` |
| Market / period / selection keys | `u3ingest/canonical/markets.py`: `PERIOD_PATTERNS`, `split_period`, `_ALIAS`, `_PROP_METRIC`, `_TEAM_PROP`, `canon_market_from_name`, `_OP_TYPE`, `_OP_PERIOD`, `canon_market_oddspapi`, `canon_selection`, `slug` |
| Book registry | `u3ingest/mapping/registry.py`: `BOOKS`, `BookRegistry.resolve/normalize/unknown` |
| Fixture registry | `u3ingest/mapping/registry.py`: `FixtureRegistry.add_opticodds/add_oddspapi/add_sharpsports/_fuzzy/canonical_for`, `norm_team`, `_iso_ms` |
| OpticOdds normalization | `u3ingest/providers/opticodds/normalize.py`: `OpticOddsNormalizer.remember_fixture/quotes_from_fixture_rows/quotes_from_sse/quote/pm_snapshot_levels` |
| OddsPapi normalization | `u3ingest/providers/oddspapi/normalize.py`: `MarketDict`, `OddsPapiNormalizer.note_bookmakers/quotes` |
| SharpSports normalization | `u3ingest/providers/sharpsports/normalize.py`: `SharpSportsNormalizer.remember_event/quotes` |
| Bootstrap and streams | `u3ingest/pipeline.py` (`bootstrap`: OpticOdds `/fixtures/active` per league, OddsPapi `/markets` + `/fixtures?sportId&startTimeFrom=now-6h`, SharpSports `/events?league&upcoming=true`; streams: OpticOdds `/stream/odds/{sport}`, OddsPapi WS `odds`+`bookmakers`+`fixtures`, SharpSports `/prices?league=` poll) |
| Raw archive / GCS / replay | `u3ingest/sinks/raw.py`, `u3ingest/sinks/gcs.py`, `u3ingest/replay.py` |
| ClickHouse | `schemas/clickhouse.sql`, `u3ingest/sinks/clickhouse.py` (`apply_schema`, batched `insert`) |
| Evidence | `docs/research/oddspapi.md`, `docs/research/sharpsports.md`, `docs/research/README.md`; scratchpad `research/probes/cross.md`, `samples/cross/{fixture_join,ss_join,books,side_by_side,oo_fixtures,op_fixtures,ss_events}.json` |

## Appendix B — worked example (EPL, Ipswich Town FC v Liverpool FC, 2026-09-04T19:00Z)

| Provider | Fixture id | Home / away | Rotation | Book-native ids |
|---|---|---|---|---|
| OpticOdds | `2026090552B5D9A7` (`game_id` `42573-28098-2026-09-04`, `numerical_id` 944216) | `77CBFB371ED9` Ipswich Town FC / `F799E43513D4` Liverpool FC (`base_id` 3769 / 4245) | 810052 / 200081 | Kalshi `source_ids.market_id` `KXEPL1HTOTAL-26SEP04IPSLFC-3` |
| OddsPapi | `id1000001772221244` (`externalProviders.opticoddsId` = `2026090552B5D9A7`, `betradarId` 72221244, `pinnacleId` 1634444777, `flashscoreId` `CIuslOyP`, `sofascoreId` 16363261, `lsportsId` 19867148, `mollybetId` `2026-09-04,43,49`) | participant1 32 Ipswich Town (`IPS`) / participant2 44 Liverpool FC (`LFC`) | 792 / 793 | Kalshi `bookmakerMarketId` `KXEPLTOTAL-26SEP04IPSLFC`, `bookmakerOutcomeId` `KXEPLTOTAL-26SEP04IPSLFC-3:yes`; DraftKings `bookmakerMarketId` `3_86020416`, `bookmakerOutcomeId` `0OU86020416O250_1`, `betslip` `https://sportsbook.draftkings.com/event/34572322?…` |
| SharpSports | `EVNT_b9615f005d8b4dcd970c97596436597a` (`oddsjamId` null → resolved by team+time) | `TEAM_fa74a3321920430ea6f665ce1d88bac9` Ipswich Town FC / `TEAM_1caf3f7d7db545adb693b783b37f3ea5` Liverpool FC | — | BetRivers `bookIds` `{eventId: 1028072837, marketId: 2683816314, selectionId: 4309324387}` |

Same selection across feeds (full-time total goals, Over 3.5, Pinnacle):

| Provider | Native row | Canonical |
|---|---|---|
| OpticOdds | `id` `42573-28098-2026-09-04:pinnacle:total_goals:over_3_5`, `market` `Total Goals`, `selection_line` `over`, `points` 3.5, `price` 120, `is_main` (per row), `limits.max` (per row), `timestamp` 1788423449.84 | `book_id=pinnacle, market=total, period=full, selection=over, line=3.5, price_us=120, price_dec=2.2, source_ts_ms=1788423449842` |
| OddsPapi | `oddsId` `id1000001772221244:pinnacle:101030:0` (marketId 101030 = `totals`/`fulltime`/handicap 3.5 → outcome `Over`), `price` 2.22, `mainLine` true, `limit` 50.0, `changedAt` 1788375642620, `bookmakerChangedAt` 1788375642127 | `book_id=pinnacle, market=total, period=<raw 'fulltime' today [GAP 5]>, selection=over, line=3.5, price_dec=2.22, limit_max=50.0, source_ts_ms=1788375642127, gateway_ts_ms=<ws ts>` |
| SharpSports | Pinnacle is not offered on this EPL event (books present: `mg, fd, br, dk, hr`); for `Total` / `Over` at `br`: `{line: 2.5, odds: 155, main: false, live: false, ev: null}` | `book_id=betrivers, market=total, period=full, selection=over, line=2.5, price_us=155, source_ts_ms=NULL, event_kind=snapshot` |

## Appendix C — bootstrap sequence and ingestion universe **[CODE]**

`u3ingest/pipeline.py` `Pipeline.bootstrap()` runs, in order, and archives every response under `bootstrap/registries`:

| Step | Call | What it feeds | Observed at the 75 s live run **[LIVE]** |
|---|---|---|---|
| 1 | OpticOdds `GET /fixtures/active?league=<id>` per configured league (`OpticOddsClient.fixtures_active`, paginated; `include_statsperform_id` is passed by the client) | `OpticOddsNormalizer.remember_fixture` → `FixtureRegistry.add_opticodds` (canonical ids, home/away context, rotation numbers, `statsperform_id`) | MLB 82 + EPL 20 active fixtures |
| 2 | OddsPapi `GET /markets?sportId=<id>` then `GET /fixtures?sportId=<id>&startTimeFrom=now−6h` per configured sport | `MarketDict` (outcome → market/handicap/period), `FixtureRegistry.add_oddspapi` (join on `externalProviders.opticoddsId`, else fuzzy), `note_bookmakers` (`participantsRotated`) | 1,223 baseball / 14,774 soccer fixtures; 149 / 1,940 carry `opticoddsId` |
| 3 | SharpSports `GET /events?league=<abbr>&upcoming=true` per configured league | `SharpSportsNormalizer.remember_event` → `FixtureRegistry.add_sharpsports` (join on `oddsjamId == game_id`, else fuzzy) | MLB 347 events (308 joined), EPL 360 (30 joined — SharpSports lists the whole season) |
| report | `report["unresolved_fuzzy"]`, `report["fixtures"]`, per-league counts | logged; not persisted yet **[GAP]** | — |

Streams after bootstrap: OpticOdds `GET /stream/odds/{sport}` (≤ 5 `sportsbook` per connection, `include_fixture_updates` not enabled), OddsPapi WS login with `channels=[odds, bookmakers, fixtures]` (`fixtures` payloads refresh the registry via `add_oddspapi`), SharpSports `GET /prices?league=` polled every `--poll` seconds (default 30). Live totals for the 75 s run: 381,188 canonical quotes (OddsPapi 183,754 · OpticOdds 124,002 · SharpSports 73,432), 1,311,005 order-book levels, 105,128 raw messages, 0 normalization errors.

Universe configuration is a dict `sport → (opticodds league ids, oddspapi sportId, sharpsports league abbrs)`; the OpticOdds and SharpSports league lists are zipped positionally, so they must be kept in the same order. Planned: derive the universe from the `leagues` dimension (§3.3) instead of code.

