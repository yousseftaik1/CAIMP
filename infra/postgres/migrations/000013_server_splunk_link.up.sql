-- TASK-S14: Link servers to Splunk incident data.
--
-- Changes:
--   1. Add nullable `splunk_host` column to `servers` — lets operators map a
--      registered server to a different Splunk host name when they differ
--      (e.g. server.hostname = "web-01.internal", Splunk host = "web-01").
--      When NULL the join falls back to `servers.hostname`.
--   2. Create view `v_server_splunk_health` — aggregates Splunk incident counts
--      and latest AI explanation status per server for the last 24 h.
--      Used by `GET /servers/{id}/splunk` in the Query API.

ALTER TABLE servers
    ADD COLUMN IF NOT EXISTS splunk_host TEXT;

COMMENT ON COLUMN servers.splunk_host IS
    'Override Splunk host name for this server. NULL = use hostname column.';

-- Index so the view join is fast even for orgs with many servers.
CREATE INDEX IF NOT EXISTS idx_servers_splunk_host
    ON servers (org_id, splunk_host)
    WHERE splunk_host IS NOT NULL;

-- ---------------------------------------------------------------------------
-- v_server_splunk_health
-- Joined view: servers → splunk_incidents → splunk_ai_explanations (latest).
-- RLS is enforced on the underlying tables; this view inherits it.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_server_splunk_health AS
SELECT
    s.id                                        AS server_id,
    s.org_id,
    s.name                                      AS server_name,
    s.hostname,
    COALESCE(s.splunk_host, s.hostname)         AS effective_splunk_host,

    COUNT(si.id)                                AS total_incidents_24h,
    COUNT(si.id) FILTER (WHERE si.severity IN ('high', 'critical'))
                                                AS critical_incidents_24h,
    MAX(si.detected_at)                         AS last_incident_at,

    -- Most recent complete explanation
    (
        SELECT sae.status
        FROM   splunk_incidents si2
        JOIN   splunk_ai_explanations sae ON sae.incident_id = si2.id
        WHERE  si2.org_id = s.org_id
          AND  si2.host = COALESCE(s.splunk_host, s.hostname)
          AND  sae.status = 'complete'
        ORDER  BY si2.detected_at DESC
        LIMIT  1
    )                                           AS last_explanation_status,

    (
        SELECT sae.severity
        FROM   splunk_incidents si2
        JOIN   splunk_ai_explanations sae ON sae.incident_id = si2.id
        WHERE  si2.org_id = s.org_id
          AND  si2.host = COALESCE(s.splunk_host, s.hostname)
          AND  sae.status = 'complete'
        ORDER  BY si2.detected_at DESC
        LIMIT  1
    )                                           AS last_explanation_severity

FROM  servers s
LEFT  JOIN splunk_incidents si
      ON  si.org_id = s.org_id
      AND si.host   = COALESCE(s.splunk_host, s.hostname)
      AND si.detected_at >= now() - INTERVAL '24 hours'
GROUP BY s.id, s.org_id, s.name, s.hostname, s.splunk_host;

GRANT SELECT ON v_server_splunk_health TO caimp_service;
