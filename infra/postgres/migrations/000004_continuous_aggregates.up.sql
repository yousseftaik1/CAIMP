-- Continuous aggregates for dashboard resolutions: 5-min, 1-hour, 1-day.
-- These are materialised automatically by TimescaleDB background workers.

-- 5-minute rollup
CREATE MATERIALIZED VIEW metrics_5m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('5 minutes', time)  AS bucket,
    org_id,
    server_id,
    metric_name,
    avg(value)                      AS avg_val,
    max(value)                      AS max_val,
    min(value)                      AS min_val,
    count(*)                        AS sample_count
FROM metrics
GROUP BY bucket, org_id, server_id, metric_name
WITH NO DATA;

-- Refresh policy: keep the 5-min aggregate up to date every 5 minutes
-- window must be >= 2 × bucket_width (2 × 5 min = 10 min); using 25 min to be safe
SELECT add_continuous_aggregate_policy(
    'metrics_5m',
    start_offset => INTERVAL '30 minutes',
    end_offset   => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '5 minutes'
);

-- 1-hour rollup (built on top of raw table for accuracy)
CREATE MATERIALIZED VIEW metrics_1h
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time)     AS bucket,
    org_id,
    server_id,
    metric_name,
    avg(value)                      AS avg_val,
    max(value)                      AS max_val,
    min(value)                      AS min_val,
    stddev(value)                   AS stddev_val,
    count(*)                        AS sample_count
FROM metrics
GROUP BY bucket, org_id, server_id, metric_name
WITH NO DATA;

-- window must be >= 2 × 1 h = 2 h; using 2.5 h
SELECT add_continuous_aggregate_policy(
    'metrics_1h',
    start_offset => INTERVAL '3 hours',
    end_offset   => INTERVAL '30 minutes',
    schedule_interval => INTERVAL '30 minutes'
);

-- 1-day rollup
CREATE MATERIALIZED VIEW metrics_1d
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time)      AS bucket,
    org_id,
    server_id,
    metric_name,
    avg(value)                      AS avg_val,
    max(value)                      AS max_val,
    min(value)                      AS min_val,
    stddev(value)                   AS stddev_val,
    count(*)                        AS sample_count
FROM metrics
GROUP BY bucket, org_id, server_id, metric_name
WITH NO DATA;

-- window must be >= 2 × 1 day = 2 days; using 2 days 18 hours
SELECT add_continuous_aggregate_policy(
    'metrics_1d',
    start_offset => INTERVAL '3 days',
    end_offset   => INTERVAL '6 hours',
    schedule_interval => INTERVAL '1 hour'
);
