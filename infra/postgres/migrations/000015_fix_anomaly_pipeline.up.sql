-- Fix anomaly event pipeline: link anomaly_events to ai_explanations and fix constraints.

-- 1. Add incident_id column so anomaly_events can be joined with ai_explanations
ALTER TABLE anomaly_events ADD COLUMN IF NOT EXISTS incident_id TEXT;
CREATE INDEX IF NOT EXISTS idx_anomaly_events_incident
    ON anomaly_events (incident_id) WHERE incident_id IS NOT NULL;

-- 2. Allow 'threshold' detector name (Go telemetry-writer emits this; 'static' is the old name)
ALTER TABLE anomaly_events DROP CONSTRAINT IF EXISTS anomaly_events_detector_check;
ALTER TABLE anomaly_events ADD CONSTRAINT anomaly_events_detector_check
    CHECK (detector IN ('threshold', 'static', 'rate_of_change', 'zscore'));

-- 3. Allow 'warning' severity in ai_explanations (Go detector emits 'warning', not 'medium')
ALTER TABLE ai_explanations DROP CONSTRAINT IF EXISTS ai_explanations_severity_check;
ALTER TABLE ai_explanations ADD CONSTRAINT ai_explanations_severity_check
    CHECK (severity IN ('low', 'medium', 'high', 'warning', 'critical'));
