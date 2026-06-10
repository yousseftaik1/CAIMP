-- Data retention policies.
--   raw metrics     : 90 days
--   5-min aggregate : 1 year
--   1-hour aggregate: indefinite (no policy)
--   1-day aggregate : indefinite (no policy)

SELECT add_retention_policy('metrics', INTERVAL '90 days');
SELECT add_retention_policy('metrics_5m', INTERVAL '1 year');

-- Compression: compress chunks older than 7 days on the raw table
ALTER TABLE metrics SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'org_id, server_id, metric_name',
    timescaledb.compress_orderby   = 'time DESC'
);

SELECT add_compression_policy('metrics', INTERVAL '7 days');

-- Compress 5-min aggregate older than 30 days
ALTER MATERIALIZED VIEW metrics_5m SET (timescaledb.compress = true);
SELECT add_compression_policy('metrics_5m', INTERVAL '30 days');
