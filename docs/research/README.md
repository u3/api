# Provider research

Definitive engineering specs derived from reading every page of each vendor's documentation (342 pages mirrored, read front to back by 17 reader passes) and from live probes with our trial keys (~1,300 saved raw samples).

- `opticodds.md` — OpticOdds v3 REST + SSE + prediction markets
- `oddspapi.md` — OddsPapi v5 REST + WebSocket gateway
- `sharpsports.md` — SharpSports betPrices, historicData, betSync
- `cross-provider-mapping.md` — identity resolution, canonical schema, mapping QA

Live join probe (2026-09-03): OpticOdds↔OddsPapi fixtures join on `externalProviders.opticoddsId` (MLB 40/40, EPL 8/8, NCAAF 114/125; start times identical). SharpSports events join on `oddsjamId == OpticOdds game_id` (MLB 37/40) with team-name+start-time fallback (MLB 3/40, EPL 8/8, NCAAF 73/87). Books present in all three feeds: betmgm, betrivers, draftkings, fanduel, kalshi, polymarket.
