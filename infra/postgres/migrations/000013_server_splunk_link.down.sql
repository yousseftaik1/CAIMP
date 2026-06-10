DROP VIEW  IF EXISTS v_server_splunk_health;
DROP INDEX IF EXISTS idx_servers_splunk_host;
ALTER TABLE servers DROP COLUMN IF EXISTS splunk_host;
