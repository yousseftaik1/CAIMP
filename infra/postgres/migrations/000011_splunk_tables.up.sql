-- Splunk + AI Orchestrator tables (Step 17).
--
-- Five new tables:
--   splunk_incidents        — anomaly events received from Splunk webhooks
--   splunk_ai_explanations  — LLM-generated root-cause explanations
--   ai_feedback             — operator thumbs-up/down on explanations
--   org_config              — per-org cloud LLM opt-in and credentials
--   runbooks                — operator-written diagnosis guides with RAG embeddings
--
-- All multi-tenant tables carry org_id and get tenant_isolation RLS policies.

-- ---------------------------------------------------------------------------
-- splunk_incidents
-- ---------------------------------------------------------------------------
CREATE TABLE splunk_incidents (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    host            TEXT        NOT NULL,
    metric_name     TEXT        NOT NULL,
    anomaly_type    TEXT        NOT NULL,
    severity        TEXT        NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    value           FLOAT       NOT NULL DEFAULT 0,
    mltk_score      FLOAT,
    splunk_search   TEXT,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_splunk_incidents_org         ON splunk_incidents (org_id, detected_at DESC);
CREATE INDEX idx_splunk_incidents_host        ON splunk_incidents (org_id, host, detected_at DESC);
CREATE INDEX idx_splunk_incidents_type        ON splunk_incidents (org_id, anomaly_type);
CREATE INDEX idx_splunk_incidents_severity    ON splunk_incidents (org_id, severity) WHERE severity IN ('high', 'critical');

ALTER TABLE splunk_incidents ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON splunk_incidents USING (org_id = current_org_id());

GRANT ALL ON splunk_incidents TO caimp_service;

-- ---------------------------------------------------------------------------
-- splunk_ai_explanations
-- ---------------------------------------------------------------------------
CREATE TABLE splunk_ai_explanations (
    id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id          UUID        NOT NULL REFERENCES splunk_incidents(id) ON DELETE CASCADE,
    org_id               UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    status               TEXT        NOT NULL DEFAULT 'pending'
                                     CHECK (status IN ('pending', 'complete', 'error')),
    severity             TEXT        CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    explanation          TEXT,
    root_cause           TEXT,
    recommended_action   TEXT,
    evidence_spl_queries JSONB,
    confidence           TEXT        CHECK (confidence IN ('low', 'medium', 'high')),
    llm_provider         TEXT,
    error_message        TEXT,
    completed_at         TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_splunk_expl_incident  ON splunk_ai_explanations (incident_id);
CREATE INDEX idx_splunk_expl_org       ON splunk_ai_explanations (org_id, created_at DESC);
CREATE INDEX idx_splunk_expl_status    ON splunk_ai_explanations (org_id, status) WHERE status != 'complete';

ALTER TABLE splunk_ai_explanations ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON splunk_ai_explanations USING (org_id = current_org_id());

GRANT ALL ON splunk_ai_explanations TO caimp_service;

-- ---------------------------------------------------------------------------
-- ai_feedback
-- ---------------------------------------------------------------------------
CREATE TABLE ai_feedback (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    explanation_id  UUID        NOT NULL REFERENCES splunk_ai_explanations(id) ON DELETE CASCADE,
    org_id          UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id         UUID        REFERENCES users(id) ON DELETE SET NULL,
    rating          SMALLINT    NOT NULL CHECK (rating IN (-1, 0, 1)),
    comment         TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_ai_feedback_explanation ON ai_feedback (explanation_id);
CREATE INDEX idx_ai_feedback_org         ON ai_feedback (org_id, created_at DESC);

ALTER TABLE ai_feedback ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON ai_feedback USING (org_id = current_org_id());

GRANT ALL ON ai_feedback TO caimp_service;

-- ---------------------------------------------------------------------------
-- org_config
-- ---------------------------------------------------------------------------
CREATE TABLE org_config (
    org_id              UUID    PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
    use_cloud_llm       BOOLEAN NOT NULL DEFAULT false,
    anthropic_api_key   TEXT,
    splunk_host         TEXT,
    splunk_username     TEXT,
    -- password is AES-256-GCM encrypted at the application layer before storage
    splunk_password_enc TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE org_config ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON org_config USING (org_id = current_org_id());

GRANT ALL ON org_config TO caimp_service;

-- ---------------------------------------------------------------------------
-- runbooks
-- ---------------------------------------------------------------------------
CREATE TABLE runbooks (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    title           TEXT        NOT NULL,
    anomaly_type    TEXT        NOT NULL,
    content         TEXT        NOT NULL,
    -- nomic-embed-text 768-dim vector for RAG similarity search
    embedding       VECTOR(768),
    created_by      UUID        REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- HNSW cosine index mirrors the pattern used in rag_documents
CREATE INDEX idx_runbooks_hnsw    ON runbooks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
CREATE INDEX idx_runbooks_org     ON runbooks (org_id, anomaly_type);

ALTER TABLE runbooks ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON runbooks USING (org_id = current_org_id());

GRANT ALL ON runbooks TO caimp_service;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO caimp_service;
