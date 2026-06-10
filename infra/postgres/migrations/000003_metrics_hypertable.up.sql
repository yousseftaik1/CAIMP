-- Time-series metrics table (TimescaleDB hypertable).
-- Partitioned by time (1-day chunks) + space (org_id) for tenant isolation.

CREATE TABLE metrics (
    time            TIMESTAMPTZ     NOT NULL,
    org_id          UUID            NOT NULL,
    server_id       UUID            NOT NULL,
    metric_name     TEXT            NOT NULL,
    labels          JSONB           NOT NULL DEFAULT '{}',
    value           DOUBLE PRECISION NOT NULL
);

-- Convert to hypertable, partition by time with 1-day chunks
SELECT create_hypertable(
    'metrics',
    'time',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => true
);

-- Space partition on org_id for better multi-tenant isolation (4 partitions)
SELECT add_dimension('metrics', 'org_id', number_partitions => 4);

-- Primary access pattern: per-server time range
CREATE INDEX ON metrics (org_id, server_id, metric_name, time DESC);
-- Secondary: cardinality queries
CREATE INDEX ON metrics (org_id, metric_name);

-- Anomaly events (lightweight, non-time-series)
CREATE TABLE anomaly_events (
    id              UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    time            TIMESTAMPTZ     NOT NULL DEFAULT now(),
    org_id          UUID            NOT NULL,
    server_id       UUID            NOT NULL,
    metric_name     TEXT            NOT NULL,
    value           DOUBLE PRECISION NOT NULL,
    threshold       DOUBLE PRECISION,
    detector        TEXT            NOT NULL CHECK (detector IN ('static', 'rate_of_change', 'zscore')),
    severity        TEXT            NOT NULL CHECK (severity IN ('warning', 'critical')),
    nats_message_id TEXT,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX ON anomaly_events (org_id, time DESC);
CREATE INDEX ON anomaly_events (server_id, time DESC);
