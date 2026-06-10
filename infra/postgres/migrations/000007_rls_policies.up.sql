-- Row-Level Security policies for every multi-tenant table.
--
-- The API sets caimp.current_org_id per connection from the verified JWT:
--   SET LOCAL caimp.current_org_id = '<uuid>';
--
-- A missed WHERE clause returns zero rows instead of leaking data.

-- Helper function to read the current org from session config
CREATE OR REPLACE FUNCTION current_org_id() RETURNS UUID
    LANGUAGE sql STABLE SECURITY DEFINER AS
$$
    SELECT current_setting('caimp.current_org_id', true)::uuid;
$$;

-- ---------------------------------------------------------------------------
-- organizations
-- ---------------------------------------------------------------------------
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON organizations
    USING (id = current_org_id());

-- ---------------------------------------------------------------------------
-- users
-- ---------------------------------------------------------------------------
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON users
    USING (org_id = current_org_id());

-- ---------------------------------------------------------------------------
-- servers
-- ---------------------------------------------------------------------------
ALTER TABLE servers ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON servers
    USING (org_id = current_org_id());

-- ---------------------------------------------------------------------------
-- agent_certs
-- ---------------------------------------------------------------------------
ALTER TABLE agent_certs ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON agent_certs
    USING (org_id = current_org_id());

-- ---------------------------------------------------------------------------
-- revoked_agents
-- ---------------------------------------------------------------------------
ALTER TABLE revoked_agents ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON revoked_agents
    USING (org_id = current_org_id());

-- ---------------------------------------------------------------------------
-- enrollment_tokens
-- ---------------------------------------------------------------------------
ALTER TABLE enrollment_tokens ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON enrollment_tokens
    USING (org_id = current_org_id());

-- ---------------------------------------------------------------------------
-- alert_rules
-- ---------------------------------------------------------------------------
ALTER TABLE alert_rules ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON alert_rules
    USING (org_id = current_org_id());

-- ---------------------------------------------------------------------------
-- notifications
-- ---------------------------------------------------------------------------
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON notifications
    USING (org_id = current_org_id());

-- ---------------------------------------------------------------------------
-- ai_explanations
-- ---------------------------------------------------------------------------
ALTER TABLE ai_explanations ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON ai_explanations
    USING (org_id = current_org_id());

-- ---------------------------------------------------------------------------
-- audit_log
-- ---------------------------------------------------------------------------
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON audit_log
    USING (org_id = current_org_id());

-- ---------------------------------------------------------------------------
-- rag_documents
-- ---------------------------------------------------------------------------
ALTER TABLE rag_documents ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON rag_documents
    USING (org_id = current_org_id());

-- ---------------------------------------------------------------------------
-- anomaly_events
-- ---------------------------------------------------------------------------
ALTER TABLE anomaly_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON anomaly_events
    USING (org_id = current_org_id());

-- ---------------------------------------------------------------------------
-- Super-user / service bypass role
-- Services that need to write across orgs (Telemetry Writer, Alert Engine)
-- use this role and bypass RLS explicitly.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'caimp_service') THEN
        CREATE ROLE caimp_service;
    END IF;
END$$;

-- Grant bypass RLS only to the service role, not the app user
ALTER ROLE caimp_service BYPASSRLS;

-- Grant the service role to the default caimp user so services can SET ROLE
GRANT caimp_service TO caimp;

-- caimp_service also needs object-level access on all tables/sequences
-- (BYPASSRLS skips row policies but not object-level grants)
GRANT ALL ON ALL TABLES IN SCHEMA public TO caimp_service;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO caimp_service;
