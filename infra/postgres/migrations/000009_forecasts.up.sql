CREATE TABLE server_forecasts (
    id                 UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id             UUID        NOT NULL,
    server_id          UUID        NOT NULL,
    metric_name        TEXT        NOT NULL,
    forecasted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    horizon_hours      INT         NOT NULL DEFAULT 24,
    -- [{t, predicted, lower, upper}] at hourly resolution
    forecast_points    JSONB       NOT NULL DEFAULT '[]',
    -- Hours until metric first crosses critical_threshold; NULL = never in horizon
    time_to_critical   FLOAT,
    critical_threshold FLOAT       NOT NULL DEFAULT 0.9,
    -- Metric units per hour; positive = rising
    trend_slope        FLOAT,
    ml_model           TEXT        NOT NULL DEFAULT 'holt_linear',
    llm_narrative      TEXT,
    llm_confidence     TEXT        CHECK (llm_confidence IN ('low', 'medium', 'high'))
);

CREATE INDEX idx_forecasts_server_metric
    ON server_forecasts (server_id, metric_name, forecasted_at DESC);

GRANT ALL ON server_forecasts TO caimp_service;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO caimp_service;
