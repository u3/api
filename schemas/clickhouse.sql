-- u3 canonical hot store (ClickHouse). Raw provider payloads live in the object-store archive; these tables are derived.
CREATE DATABASE IF NOT EXISTS u3;

CREATE TABLE IF NOT EXISTS u3.quotes (
    recv_ns            UInt64,
    recv_ts            DateTime64(3) MATERIALIZED toDateTime64(recv_ns / 1e9, 3),
    provider           LowCardinality(String),
    book_id            LowCardinality(String),
    provider_book      LowCardinality(String),
    fixture_id         String,
    provider_fixture_id String,
    market             LowCardinality(String),
    period             LowCardinality(String),
    selection          String,
    line               Nullable(Float64),
    price_dec          Nullable(Float64),
    price_us           Nullable(Int32),
    is_main            Nullable(Bool),
    active             Bool,
    limit_max          Nullable(Float64),
    source_ts_ms       Nullable(Int64),
    gateway_ts_ms      Nullable(Int64),
    provider_market    String,
    provider_selection String,
    provider_odd_id    String,
    player_id          Nullable(String),
    team_id            Nullable(String),
    event_kind         LowCardinality(String),
    grouping_key       Nullable(String),
    extra              String CODEC(ZSTD(3))
) ENGINE = MergeTree
PARTITION BY toDate(recv_ts)
ORDER BY (fixture_id, market, period, selection, book_id, recv_ns)
TTL toDate(recv_ts) + INTERVAL 400 DAY
SETTINGS index_granularity = 8192;

CREATE TABLE IF NOT EXISTS u3.order_book_levels (
    recv_ns UInt64, recv_ts DateTime64(3) MATERIALIZED toDateTime64(recv_ns / 1e9, 3),
    provider LowCardinality(String), book_id LowCardinality(String), fixture_id String, market LowCardinality(String), period LowCardinality(String),
    selection String, venue_market_id String, side LowCardinality(String), level UInt8, price Float64, size Nullable(Float64),
    source_ts_ms Nullable(Int64), provider_odd_id String
) ENGINE = MergeTree PARTITION BY toDate(recv_ts) ORDER BY (fixture_id, book_id, venue_market_id, selection, side, recv_ns, level)
TTL toDate(recv_ts) + INTERVAL 180 DAY;

CREATE TABLE IF NOT EXISTS u3.fixture_xref (
    fixture_id String, sport LowCardinality(String), league LowCardinality(String), start_time_ms Nullable(Int64), home Nullable(String), away Nullable(String),
    status Nullable(String), opticodds_id Nullable(String), opticodds_game_id Nullable(String), oddspapi_id Nullable(String), sharpsports_id Nullable(String),
    betradar_id Nullable(String), pinnacle_id Nullable(String), statsperform_id Nullable(String), sportradar_id Nullable(String), the_odds_api_id Nullable(String),
    home_rot Nullable(Int32), away_rot Nullable(Int32), updated_ns UInt64
) ENGINE = ReplacingMergeTree(updated_ns) ORDER BY fixture_id;

-- latest quote per (fixture, market, period, selection, line, book): the "board"
CREATE MATERIALIZED VIEW IF NOT EXISTS u3.quotes_latest
ENGINE = ReplacingMergeTree(recv_ns) ORDER BY (fixture_id, market, period, selection, line, book_id)
AS SELECT recv_ns, provider, book_id, fixture_id, market, period, selection, line, price_dec, price_us, is_main, active, limit_max, source_ts_ms, event_kind
FROM u3.quotes;

-- ingestion latency: our receive time minus the book's own change time (OpticOdds odd.timestamp / OddsPapi bookmakerChangedAt)
CREATE VIEW IF NOT EXISTS u3.quote_latency AS
SELECT provider, book_id, toStartOfMinute(recv_ts) AS minute,
       quantile(0.5)(recv_ns / 1e6 - source_ts_ms) AS p50_ms, quantile(0.99)(recv_ns / 1e6 - source_ts_ms) AS p99_ms, count() AS n
FROM u3.quotes WHERE source_ts_ms IS NOT NULL GROUP BY provider, book_id, minute;
