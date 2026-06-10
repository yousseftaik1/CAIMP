ALTER TABLE anomaly_events    DISABLE ROW LEVEL SECURITY;
ALTER TABLE rag_documents     DISABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log         DISABLE ROW LEVEL SECURITY;
ALTER TABLE ai_explanations   DISABLE ROW LEVEL SECURITY;
ALTER TABLE notifications     DISABLE ROW LEVEL SECURITY;
ALTER TABLE alert_rules       DISABLE ROW LEVEL SECURITY;
ALTER TABLE enrollment_tokens DISABLE ROW LEVEL SECURITY;
ALTER TABLE revoked_agents    DISABLE ROW LEVEL SECURITY;
ALTER TABLE agent_certs       DISABLE ROW LEVEL SECURITY;
ALTER TABLE servers           DISABLE ROW LEVEL SECURITY;
ALTER TABLE users             DISABLE ROW LEVEL SECURITY;
ALTER TABLE organizations     DISABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation ON anomaly_events;
DROP POLICY IF EXISTS tenant_isolation ON rag_documents;
DROP POLICY IF EXISTS tenant_isolation ON audit_log;
DROP POLICY IF EXISTS tenant_isolation ON ai_explanations;
DROP POLICY IF EXISTS tenant_isolation ON notifications;
DROP POLICY IF EXISTS tenant_isolation ON alert_rules;
DROP POLICY IF EXISTS tenant_isolation ON enrollment_tokens;
DROP POLICY IF EXISTS tenant_isolation ON revoked_agents;
DROP POLICY IF EXISTS tenant_isolation ON agent_certs;
DROP POLICY IF EXISTS tenant_isolation ON servers;
DROP POLICY IF EXISTS tenant_isolation ON users;
DROP POLICY IF EXISTS tenant_isolation ON organizations;

DROP FUNCTION IF EXISTS current_org_id();
DROP ROLE IF EXISTS caimp_service;
