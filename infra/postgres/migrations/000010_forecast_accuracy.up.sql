-- Accuracy tracking for the forecast learning feedback loop
ALTER TABLE server_forecasts
    ADD COLUMN IF NOT EXISTS evaluated_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS actual_mae     FLOAT,
    ADD COLUMN IF NOT EXISTS accuracy_score FLOAT CHECK (accuracy_score >= 0 AND accuracy_score <= 1),
    ADD COLUMN IF NOT EXISTS nats_published BOOLEAN NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_forecasts_unevaluated
    ON server_forecasts (forecasted_at)
    WHERE evaluated_at IS NULL;
