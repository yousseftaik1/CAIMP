ALTER TABLE org_config
    DROP COLUMN IF EXISTS alert_channels,
    DROP COLUMN IF EXISTS auto_remediate;
