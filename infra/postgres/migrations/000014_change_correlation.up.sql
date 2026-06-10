-- Migration 000014: Change correlation tables
--
-- Adds two new tables to power the Change Correlation Engine:
--   1. change_events   — timestamped record of every change on a server
--                        (deployments, config changes, restarts, packages, cron, SSH)
--   2. root_cause_analyses — correlation-engine output: ranked changes + LLM narrative

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. change_events
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS change_events (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    server_id    UUID        REFERENCES servers(id) ON DELETE SET NULL,
    occurred_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    change_type  TEXT        NOT NULL,
    -- 'deployment' | 'config' | 'restart' | 'package' | 'cron' | 'ssh_login' | 'docker_pull'
    source       TEXT        NOT NULL,
    -- 'github_webhook' | 'gitlab_webhook' | 'agent' | 'docker_events' | 'manual'
    actor        TEXT,                        -- user or system that triggered the change
    description  TEXT,                        -- human-readable summary
    payload      JSONB       NOT NULL DEFAULT '{}',
    git_sha      TEXT,
    image_sha    TEXT
);

SELECT create_hypertable('change_events', 'occurred_at', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_change_server_time
    ON change_events (server_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_change_org_time
    ON change_events (org_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_change_type
    ON change_events (org_id, change_type, occurred_at DESC);

-- Row-level security: tenant isolation
ALTER TABLE change_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON change_events
    USING (org_id = current_org_id());

GRANT ALL ON change_events TO caimp_service;

COMMENT ON TABLE  change_events                IS 'Every recorded change on a monitored server — deployments, config, restarts, packages, cron jobs, SSH sessions.';
COMMENT ON COLUMN change_events.change_type    IS 'Category: deployment | config | restart | package | cron | ssh_login | docker_pull';
COMMENT ON COLUMN change_events.source         IS 'How this event was captured: github_webhook | gitlab_webhook | agent | docker_events | manual';


-- ─────────────────────────────────────────────────────────────────────────────
-- 2. root_cause_analyses
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS root_cause_analyses (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    anomaly_event_id    UUID        REFERENCES anomaly_events(id) ON DELETE SET NULL,
    server_id           UUID        REFERENCES servers(id) ON DELETE SET NULL,
    likely_cause        TEXT        NOT NULL,         -- one-sentence cause label
    confidence          NUMERIC(4,3) NOT NULL DEFAULT 0,  -- 0.000–1.000
    correlated_changes  JSONB       NOT NULL DEFAULT '[]', -- ranked [{change_id, type, description, score}]
    narrative           TEXT        NOT NULL,         -- LLM plain-English output
    recommended_actions JSONB       NOT NULL DEFAULT '[]', -- [{priority, action, reason}]
    window_start        TIMESTAMPTZ,
    window_end          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rca_anomaly
    ON root_cause_analyses (anomaly_event_id);

CREATE INDEX IF NOT EXISTS idx_rca_server_time
    ON root_cause_analyses (server_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_rca_org_time
    ON root_cause_analyses (org_id, created_at DESC);

ALTER TABLE root_cause_analyses ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON root_cause_analyses
    USING (org_id = current_org_id());

GRANT ALL ON root_cause_analyses TO caimp_service;

COMMENT ON TABLE  root_cause_analyses                   IS 'Correlation engine output: which recent change most likely caused an anomaly, with LLM narrative and ordered fix steps.';
COMMENT ON COLUMN root_cause_analyses.confidence        IS 'Score 0–1: how strongly the correlated changes explain the anomaly.';
COMMENT ON COLUMN root_cause_analyses.correlated_changes IS 'JSON array of ranked changes [{change_id, change_type, description, score, occurred_at}].';
COMMENT ON COLUMN root_cause_analyses.recommended_actions IS 'Ordered fix steps [{priority, action, reason}].';
