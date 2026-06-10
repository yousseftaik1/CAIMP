ALTER TABLE anomaly_events DROP COLUMN IF EXISTS incident_id;

ALTER TABLE anomaly_events DROP CONSTRAINT IF EXISTS anomaly_events_detector_check;
ALTER TABLE anomaly_events ADD CONSTRAINT anomaly_events_detector_check
    CHECK (detector IN ('static', 'rate_of_change', 'zscore'));

ALTER TABLE ai_explanations DROP CONSTRAINT IF EXISTS ai_explanations_severity_check;
ALTER TABLE ai_explanations ADD CONSTRAINT ai_explanations_severity_check
    CHECK (severity IN ('low', 'medium', 'high', 'critical'));
