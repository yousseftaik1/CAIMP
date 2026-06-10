-- Add alert_channels (Slack webhook URL, PagerDuty routing key) and
-- auto_remediate flag to org_config.  Both were omitted from migration 011.

ALTER TABLE org_config
    ADD COLUMN IF NOT EXISTS alert_channels  JSONB    NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS auto_remediate  BOOLEAN  NOT NULL DEFAULT false;

-- Ensure the default-org seed row has an explicit empty dict
UPDATE org_config SET alert_channels = '{}' WHERE alert_channels IS NULL;
