# Provider research

Definitive engineering specs derived from reading every page of each vendor's documentation (342 pages mirrored, read front to back by 17 reader passes) and from live probes with our trial keys (~1,300 saved raw samples).

- `opticodds.md` — OpticOdds v3 REST + SSE + prediction markets
- `oddspapi.md` — OddsPapi v5 REST + WebSocket gateway
- `sharpsports.md` — SharpSports betPrices, historicData, betSync
- `cross-provider-mapping.md` — identity resolution, canonical schema, mapping QA

Live join probe (2026-09-03): OpticOdds↔OddsPapi fixtures join on `externalProviders.opticoddsId` (MLB 40/40, EPL 8/8, NCAAF 114/125; start times identical). SharpSports events join on `oddsjamId == OpticOdds game_id` (MLB 37/40) with team-name+start-time fallback (MLB 3/40, EPL 8/8, NCAAF 73/87). Books present in all three feeds: betmgm, betrivers, draftkings, fanduel, kalshi, polymarket.

## Live verification (2026-09-03, 75 s run, `u3-ingest run --sports baseball,soccer --seconds 75`)

| metric | value |
|---|---|
| canonical quotes | 381,188 (OddsPapi 183,754 · OpticOdds 124,002 · SharpSports 73,432) |
| order-book levels (Kalshi/Polymarket/exchanges) | 1,311,005 |
| raw messages archived | 105,128 (52 MB gzip JSONL) |
| normalization errors | 0 |
| bootstrap | OpticOdds MLB 82 + EPL 20 active fixtures; OddsPapi 1,223 baseball / 14,774 soccer fixtures (149 / 1,940 carry `opticoddsId`); SharpSports MLB 347 events (308 joined), EPL 360 (30 joined: SharpSports lists the whole season, OpticOdds only fixtures with odds) |
