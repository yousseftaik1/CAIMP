-- Drop Splunk + AI Orchestrator tables in reverse FK dependency order.
DROP TABLE IF EXISTS ai_feedback;
DROP TABLE IF EXISTS splunk_ai_explanations;
DROP TABLE IF EXISTS splunk_incidents;
DROP TABLE IF EXISTS runbooks;
DROP TABLE IF EXISTS org_config;
