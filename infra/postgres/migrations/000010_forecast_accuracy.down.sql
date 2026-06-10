DROP INDEX IF EXISTS idx_forecasts_unevaluated;

ALTER TABLE server_forecasts
    DROP COLUMN IF EXISTS evaluated_at,
    DROP COLUMN IF EXISTS actual_mae,
    DROP COLUMN IF EXISTS accuracy_score,
    DROP COLUMN IF EXISTS nats_published;
