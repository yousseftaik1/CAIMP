-- =============================================================================
-- CAIMP v2 — Demo Data Seed
-- Populates the dashboard with realistic data: servers, incidents, AI analyses,
-- metrics time-series, anomaly events, and runbooks.
--
-- Run: docker exec -i caimp-postgres psql -U caimp -d caimp < scripts/seed_demo.sql
-- =============================================================================

SET ROLE caimp_service;

-- ── 1. Bring existing demo-server-01 online ───────────────────────────────────
UPDATE servers SET
    status = 'online',
    last_heartbeat = now() - interval '90 seconds',
    ip_address = '10.0.1.11',
    agent_version = 'v2.1.0',
    labels = '{"env":"prod","tier":"app","region":"us-east-1"}'
WHERE id = '00000000-0000-0000-0000-000000000011';

-- ── 2. Additional demo servers ────────────────────────────────────────────────
INSERT INTO servers (id, org_id, name, hostname, ip_address, role, status, last_heartbeat, agent_version, labels) VALUES
    ('00000000-0000-0000-0000-000000000012',
     '00000000-0000-0000-0000-000000000001',
     'web-server-01', 'web-01.prod.local', '10.0.1.12',
     'web', 'online', now() - interval '2 minutes', 'v2.1.0',
     '{"env":"prod","tier":"frontend","region":"us-east-1"}'),

    ('00000000-0000-0000-0000-000000000013',
     '00000000-0000-0000-0000-000000000001',
     'db-primary', 'db-01.prod.local', '10.0.1.13',
     'database', 'online', now() - interval '45 seconds', 'v2.1.0',
     '{"env":"prod","tier":"data","region":"us-east-1"}'),

    ('00000000-0000-0000-0000-000000000014',
     '00000000-0000-0000-0000-000000000001',
     'worker-01', 'worker-01.prod.local', '10.0.1.14',
     'worker', 'degraded', now() - interval '28 minutes', 'v2.0.9',
     '{"env":"prod","tier":"processing","region":"us-east-1"}'),

    ('00000000-0000-0000-0000-000000000015',
     '00000000-0000-0000-0000-000000000001',
     'cache-01', 'cache-01.prod.local', '10.0.1.15',
     'cache', 'online', now() - interval '3 minutes', 'v2.1.0',
     '{"env":"prod","tier":"cache","region":"us-east-1"}'),

    ('00000000-0000-0000-0000-000000000016',
     '00000000-0000-0000-0000-000000000001',
     'api-gateway', 'api-gw.prod.local', '10.0.1.16',
     'gateway', 'offline', now() - interval '2 hours 4 minutes', 'v2.0.8',
     '{"env":"prod","tier":"gateway","region":"us-east-1"}')
ON CONFLICT (org_id, hostname) DO UPDATE SET
    status         = EXCLUDED.status,
    last_heartbeat = EXCLUDED.last_heartbeat,
    ip_address     = EXCLUDED.ip_address,
    agent_version  = EXCLUDED.agent_version,
    labels         = EXCLUDED.labels;

-- ── 3. Incidents + AI explanations (20 incidents) ────────────────────────────
-- Each block: INSERT incident → INSERT explanation referencing its id via CTE.

-- 3-01  CRITICAL cpu_saturation web-01 (2h ago)
WITH i AS (INSERT INTO splunk_incidents (org_id, host, metric_name, anomaly_type, severity, value, mltk_score, splunk_search, detected_at)
  VALUES ('00000000-0000-0000-0000-000000000001','web-01.prod.local','system.cpu.utilization','cpu_saturation','critical',0.97,9.8,'CAIMP_CPU_MLTK_Alert',now()-interval'2 hours') RETURNING id)
INSERT INTO splunk_ai_explanations (incident_id,org_id,status,severity,explanation,root_cause,recommended_action,evidence_spl_queries,confidence,llm_provider,completed_at)
SELECT id,'00000000-0000-0000-0000-000000000001','complete','critical',
  'CPU utilization on web-01.prod.local reached 97% for 15 minutes at ~2h ago, scoring 9.8 on the MLTK anomaly model (baseline 35±18%). Request volume was 340% above normal in the 8 minutes preceding the event.',
  'A viral post triggered a traffic surge to /api/v1/products. The endpoint performs N+1 database queries without caching, causing unbounded CPU growth. Worker thread pool exhausted, queuing requests.',
  'Immediate: add 2 web-tier instances. Short-term: add 60-second response cache for /api/v1/products. Long-term: fix N+1 query pattern and add connection pooling.',
  '["index=web_access status=200 earliest=-4h | timechart span=1m count","index=metrics metric_name=system.cpu.utilization host=web-01.prod.local earliest=-4h | timechart span=1m avg(value)"]'::jsonb,
  'high','ollama/llama3.1:8b-instruct-q4_K_M',now()-interval'1 hour 55 minutes'
FROM i;

-- 3-02  CRITICAL process_crash worker-01 (5h ago)
WITH i AS (INSERT INTO splunk_incidents (org_id, host, metric_name, anomaly_type, severity, value, mltk_score, splunk_search, detected_at)
  VALUES ('00000000-0000-0000-0000-000000000001','worker-01.prod.local','process.crash_count','process_crash','critical',1,9.5,'CAIMP_Process_MLTK',now()-interval'5 hours') RETURNING id)
INSERT INTO splunk_ai_explanations (incident_id,org_id,status,severity,explanation,root_cause,recommended_action,evidence_spl_queries,confidence,llm_provider,completed_at)
SELECT id,'00000000-0000-0000-0000-000000000001','complete','critical',
  'The task-queue consumer process on worker-01.prod.local crashed 3 times within a 2-minute window, triggering a supervisor restart loop. MLTK score 9.5 (vs baseline near 0). Service was unavailable for ~8 minutes.',
  'A malformed job payload containing a null nested key caused an unhandled NullPointerException in the JSON deserializer. The dead-letter queue was not configured, so the same payload was retried on each restart.',
  'Immediate: remove the malformed payload from the queue (see SPL query). Short-term: add DLQ after 3 retries. Long-term: add schema validation at job enqueue time.',
  '["index=worker source=/var/log/worker/worker.log level=ERROR earliest=-6h | head 50","index=queue host=worker-01.prod.local job_status=failed | stats count by job_type"]'::jsonb,
  'high','ollama/llama3.1:8b-instruct-q4_K_M',now()-interval'4 hours 52 minutes'
FROM i;

-- 3-03  CRITICAL memory_leak db-01 (3h ago)
WITH i AS (INSERT INTO splunk_incidents (org_id, host, metric_name, anomaly_type, severity, value, mltk_score, splunk_search, detected_at)
  VALUES ('00000000-0000-0000-0000-000000000001','db-01.prod.local','system.memory.utilization','memory_leak','critical',0.94,9.1,'CAIMP_RAM_MLTK_Alert',now()-interval'3 hours') RETURNING id)
INSERT INTO splunk_ai_explanations (incident_id,org_id,status,severity,explanation,root_cause,recommended_action,evidence_spl_queries,confidence,llm_provider,completed_at)
SELECT id,'00000000-0000-0000-0000-000000000001','complete','critical',
  'Memory on db-01.prod.local climbed linearly from 52% to 94% over 90 minutes. PostgreSQL shared_buffers are stable; growth is isolated to the application connection pool process (pid 4821).',
  'A long-running analytics query (query_id: 8f3a9c) was not cancelled after its client disconnected. It held a cursor open, preventing memory from being freed. pg_cancel_backend was not called by the connection pool on timeout.',
  'Immediate: run SELECT pg_cancel_backend(4821) on db-01. Short-term: set idle_in_transaction_session_timeout=60000 in postgresql.conf. Long-term: audit all analytics queries for missing LIMIT clauses.',
  '["index=postgres source=/var/log/postgresql/postgresql.log query_id=8f3a9c earliest=-4h","index=metrics host=db-01.prod.local metric_name=system.memory.utilization | timechart span=5m avg(value)"]'::jsonb,
  'high','ollama/llama3.1:8b-instruct-q4_K_M',now()-interval'2 hours 52 minutes'
FROM i;

-- 3-04  CRITICAL api-gateway offline (2h ago) — pending explanation
WITH i AS (INSERT INTO splunk_incidents (org_id, host, metric_name, anomaly_type, severity, value, mltk_score, splunk_search, detected_at)
  VALUES ('00000000-0000-0000-0000-000000000001','api-gw.prod.local','service.availability','process_crash','critical',0,9.9,'CAIMP_Avail_MLTK',now()-interval'2 hours 5 minutes') RETURNING id)
INSERT INTO splunk_ai_explanations (incident_id,org_id,status,severity,confidence,llm_provider)
SELECT id,'00000000-0000-0000-0000-000000000001','pending','critical','high','ollama/llama3.1:8b-instruct-q4_K_M'
FROM i;

-- 3-05  HIGH cpu_saturation worker-01 (6h ago)
WITH i AS (INSERT INTO splunk_incidents (org_id, host, metric_name, anomaly_type, severity, value, mltk_score, splunk_search, detected_at)
  VALUES ('00000000-0000-0000-0000-000000000001','worker-01.prod.local','system.cpu.utilization','cpu_saturation','high',0.89,7.6,'CAIMP_CPU_MLTK_Alert',now()-interval'6 hours') RETURNING id)
INSERT INTO splunk_ai_explanations (incident_id,org_id,status,severity,explanation,root_cause,recommended_action,evidence_spl_queries,confidence,llm_provider,completed_at)
SELECT id,'00000000-0000-0000-0000-000000000001','complete','high',
  'CPU on worker-01.prod.local spiked to 89% (score 7.6) during the nightly batch job window. Duration: 22 minutes. No service impact observed — all SLAs met.',
  'The overnight report generation job processed 3.2M records in a single batch instead of the expected 200K. A data pipeline misconfiguration duplicated 16 days of records into the job queue.',
  'Immediate: no action required — job completed successfully. Short-term: add record-count validation before batch jobs start. Long-term: implement incremental processing with checkpoints.',
  '["index=jobs host=worker-01.prod.local job_type=report_generation earliest=-8h | stats sum(records_processed) by job_id"]'::jsonb,
  'high','ollama/llama3.1:8b-instruct-q4_K_M',now()-interval'5 hours 40 minutes'
FROM i;

-- 3-06  HIGH disk_pressure db-01 (4h ago)
WITH i AS (INSERT INTO splunk_incidents (org_id, host, metric_name, anomaly_type, severity, value, mltk_score, splunk_search, detected_at)
  VALUES ('00000000-0000-0000-0000-000000000001','db-01.prod.local','system.disk.utilization','disk_pressure','high',0.88,7.2,'CAIMP_Disk_MLTK_Alert',now()-interval'4 hours') RETURNING id)
INSERT INTO splunk_ai_explanations (incident_id,org_id,status,severity,explanation,root_cause,recommended_action,evidence_spl_queries,confidence,llm_provider,completed_at)
SELECT id,'00000000-0000-0000-0000-000000000001','complete','high',
  'Disk utilization on db-01.prod.local /var/lib/postgresql reached 88% (MLTK score 7.2). Growth rate is 0.3% per hour. At current trajectory, disk will be full in ~40 hours.',
  'WAL archiving was paused 3 days ago during a network maintenance window and never re-enabled. WAL segments are accumulating in pg_wal/ instead of being shipped to the archive.',
  'Immediate: re-enable WAL archiving with archive_command configured. Run pg_switch_wal() to flush current segment. Short-term: set up disk space alerting at 75% threshold.',
  '["index=postgres source=/var/log/postgresql/postgresql.log archive_status earliest=-4d | stats count by archive_status","index=metrics host=db-01.prod.local metric_name=system.disk.utilization | timechart span=1h avg(value)"]'::jsonb,
  'high','ollama/llama3.1:8b-instruct-q4_K_M',now()-interval'3 hours 45 minutes'
FROM i;

-- 3-07  HIGH memory_leak demo-server-01 (1 day ago)
WITH i AS (INSERT INTO splunk_incidents (org_id, host, metric_name, anomaly_type, severity, value, mltk_score, splunk_search, detected_at)
  VALUES ('00000000-0000-0000-0000-000000000001','demo-server-01.local','system.memory.utilization','memory_leak','high',0.82,7.0,'CAIMP_RAM_MLTK_Alert',now()-interval'1 day') RETURNING id)
INSERT INTO splunk_ai_explanations (incident_id,org_id,status,severity,explanation,root_cause,recommended_action,evidence_spl_queries,confidence,llm_provider,completed_at)
SELECT id,'00000000-0000-0000-0000-000000000001','complete','high',
  'Memory on demo-server-01.local grew from 45% to 82% over 6 hours. Java heap on the application server shows continuous growth without GC recovery cycles.',
  'A newly deployed feature (v1.8.2) introduced an unbounded in-memory cache for session objects. The LRU eviction policy was accidentally disabled by a configuration override in production.',
  'Immediate: restart the application service to reclaim memory (graceful restart preserves active sessions). Short-term: roll back the session cache configuration change in /etc/app/config.yaml. Long-term: add heap memory alerting and automated heap dump collection.',
  '["index=app_logs host=demo-server-01.local level=WARN message=*GC* earliest=-26h | timechart span=30m count","index=metrics host=demo-server-01.local metric_name=system.memory.utilization | timechart span=15m avg(value)"]'::jsonb,
  'high','ollama/llama3.1:8b-instruct-q4_K_M',now()-interval'23 hours 50 minutes'
FROM i;

-- 3-08  HIGH network_anomaly web-01 (12h ago)
WITH i AS (INSERT INTO splunk_incidents (org_id, host, metric_name, anomaly_type, severity, value, mltk_score, splunk_search, detected_at)
  VALUES ('00000000-0000-0000-0000-000000000001','web-01.prod.local','network.packet_loss_pct','network_anomaly','high',0.12,7.4,'CAIMP_Net_MLTK_Alert',now()-interval'12 hours') RETURNING id)
INSERT INTO splunk_ai_explanations (incident_id,org_id,status,severity,explanation,root_cause,recommended_action,evidence_spl_queries,confidence,llm_provider,completed_at)
SELECT id,'00000000-0000-0000-0000-000000000001','complete','high',
  'Packet loss on web-01.prod.local reached 12% (MLTK score 7.4). RTT to upstream load balancer increased from 0.8ms to 18ms during a 35-minute window. Error rate on downstream services spiked to 4.2%.',
  'A firmware update on the top-of-rack switch TOR-02 introduced a regression in the QoS queuing policy, causing packet drops under sustained traffic above 4 Gbps.',
  'Immediate: roll back TOR-02 firmware to v7.4.3 (current: v7.5.1). Failover web-01 traffic to standby NIC bond. Short-term: test firmware updates in staging network before production.',
  '["index=netflow src=10.0.1.12 earliest=-13h | timechart span=5m avg(bytes) avg(packets)","index=syslogs host=TOR-02 earliest=-14h | search *queue*drop*"]'::jsonb,
  'medium','ollama/llama3.1:8b-instruct-q4_K_M',now()-interval'11 hours 45 minutes'
FROM i;

-- 3-09  HIGH io_wait db-01 (8h ago)
WITH i AS (INSERT INTO splunk_incidents (org_id, host, metric_name, anomaly_type, severity, value, mltk_score, splunk_search, detected_at)
  VALUES ('00000000-0000-0000-0000-000000000001','db-01.prod.local','system.io_wait_pct','io_wait','high',0.41,7.9,'CAIMP_IOWait_MLTK',now()-interval'8 hours') RETURNING id)
INSERT INTO splunk_ai_explanations (incident_id,org_id,status,severity,explanation,root_cause,recommended_action,evidence_spl_queries,confidence,llm_provider,completed_at)
SELECT id,'00000000-0000-0000-0000-000000000001','complete','high',
  'I/O wait on db-01.prod.local reached 41% (MLTK score 7.9). PostgreSQL checkpoint activity spiked with avg checkpoint duration of 43s vs baseline of 2.1s. Query latency P99 degraded from 12ms to 890ms.',
  'An ad-hoc analytics query performing a full sequential scan of the events table (180GB) was run by a data analyst directly on the production primary. The scan saturated disk I/O bandwidth.',
  'Immediate: terminate the long-running query (SELECT pg_cancel_backend). Short-term: create a read replica for analytics workloads. Long-term: implement query governance — require EXPLAIN analysis before running scans on tables >10GB.',
  '["index=postgres source=pg_stat_activity state=active query=*events* earliest=-9h","index=metrics host=db-01.prod.local metric_name=system.io_wait_pct | timechart span=5m avg(value)"]'::jsonb,
  'high','ollama/llama3.1:8b-instruct-q4_K_M',now()-interval'7 hours 48 minutes'
FROM i;

-- 3-10  HIGH cpu_saturation db-01 (5 days ago)
WITH i AS (INSERT INTO splunk_incidents (org_id, host, metric_name, anomaly_type, severity, value, mltk_score, splunk_search, detected_at)
  VALUES ('00000000-0000-0000-0000-000000000001','db-01.prod.local','system.cpu.utilization','cpu_saturation','high',0.91,8.1,'CAIMP_CPU_MLTK_Alert',now()-interval'5 days 2 hours') RETURNING id)
INSERT INTO splunk_ai_explanations (incident_id,org_id,status,severity,explanation,root_cause,recommended_action,evidence_spl_queries,confidence,llm_provider,completed_at)
SELECT id,'00000000-0000-0000-0000-000000000001','complete','high',
  'Database CPU hit 91% for 18 minutes, causing query queue depth to reach 340 concurrent connections. Autovacuum ran on 3 large tables simultaneously.',
  'Three large tables crossed the autovacuum threshold simultaneously after a high-write batch import. The default autovacuum_max_workers=3 meant all workers were consumed, blocking routine queries.',
  'Immediate: increase autovacuum_max_workers to 5 and restart PostgreSQL. Short-term: schedule large imports during off-peak hours. Long-term: tune per-table autovacuum settings for high-write tables.',
  '["index=postgres source=pg_stat_activity wait_event_type=Lock earliest=-5d5h | stats count by query","index=postgres source=pg_stat_activity application_name=autovacuum earliest=-5d5h | timechart span=5m count"]'::jsonb,
  'high','ollama/llama3.1:8b-instruct-q4_K_M',now()-interval'5 days 1 hour 42 minutes'
FROM i;

-- 3-11  MEDIUM io_wait worker-01 (3 days ago)
WITH i AS (INSERT INTO splunk_incidents (org_id, host, metric_name, anomaly_type, severity, value, mltk_score, splunk_search, detected_at)
  VALUES ('00000000-0000-0000-0000-000000000001','worker-01.prod.local','system.io_wait_pct','io_wait','medium',0.29,5.3,'CAIMP_IOWait_MLTK',now()-interval'3 days 4 hours') RETURNING id)
INSERT INTO splunk_ai_explanations (incident_id,org_id,status,severity,explanation,root_cause,recommended_action,evidence_spl_queries,confidence,llm_provider,completed_at)
SELECT id,'00000000-0000-0000-0000-000000000001','complete','medium',
  'I/O wait on worker-01.prod.local reached 29% during log rotation. Duration was short (8 minutes). No customer-facing impact detected.',
  'Daily log rotation script compressed 22GB of log files synchronously while the worker was under normal load. The compression process and worker I/O competed for the same disk subsystem.',
  'Move log rotation to a dedicated mount point or add ionice scheduling (ionice -c 3) to the logrotate invocation to limit its I/O priority.',
  '["index=syslog host=worker-01.prod.local source=/var/log/syslog message=*logrotate* earliest=-3d5h"]'::jsonb,
  'medium','ollama/llama3.1:8b-instruct-q4_K_M',now()-interval'3 days 3 hours 51 minutes'
FROM i;

-- 3-12  MEDIUM network_anomaly cache-01 (2 days ago)
WITH i AS (INSERT INTO splunk_incidents (org_id, host, metric_name, anomaly_type, severity, value, mltk_score, splunk_search, detected_at)
  VALUES ('00000000-0000-0000-0000-000000000001','cache-01.prod.local','network.retransmit_rate','network_anomaly','medium',0.067,5.8,'CAIMP_Net_MLTK_Alert',now()-interval'2 days 6 hours') RETURNING id)
INSERT INTO splunk_ai_explanations (incident_id,org_id,status,severity,explanation,root_cause,recommended_action,evidence_spl_queries,confidence,llm_provider,completed_at)
SELECT id,'00000000-0000-0000-0000-000000000001','complete','medium',
  'TCP retransmit rate on cache-01.prod.local reached 6.7% (baseline <0.5%). Redis command latency P99 increased from 0.3ms to 4.2ms for a 25-minute window.',
  'A misconfigured network security group rule was temporarily applied during an audit, reducing MTU from 1500 to 576 bytes on the cache subnet. This caused excessive TCP fragmentation.',
  'The misconfigured rule was already reverted during the incident window. Verify MTU settings are restored: ip link show. Add MTU monitoring to standard network health checks.',
  '["index=netflow src=10.0.1.15 earliest=-2d7h | timechart span=5m avg(retransmits)"]'::jsonb,
  'medium','ollama/llama3.1:8b-instruct-q4_K_M',now()-interval'2 days 5 hours 38 minutes'
FROM i;

-- 3-13  MEDIUM disk_pressure demo-server-01 (2 days ago)
WITH i AS (INSERT INTO splunk_incidents (org_id, host, metric_name, anomaly_type, severity, value, mltk_score, splunk_search, detected_at)
  VALUES ('00000000-0000-0000-0000-000000000001','demo-server-01.local','system.disk.utilization','disk_pressure','medium',0.78,5.1,'CAIMP_Disk_MLTK_Alert',now()-interval'2 days 8 hours') RETURNING id)
INSERT INTO splunk_ai_explanations (incident_id,org_id,status,severity,explanation,root_cause,recommended_action,evidence_spl_queries,confidence,llm_provider,completed_at)
SELECT id,'00000000-0000-0000-0000-000000000001','complete','medium',
  'Disk utilization on /opt/app on demo-server-01.local reached 78% (score 5.1). Growth trajectory was 1.2% per day, placing the 90% alert threshold ~10 days away.',
  'Application debug logging was left enabled after a troubleshooting session 8 days prior. Log rotation max_size was set to 500MB but postrotate compression was broken, leaving uncompressed 2.1GB log files.',
  'Immediate: run logrotate -f /etc/logrotate.d/app to force rotation. Disable DEBUG logging: set LOG_LEVEL=INFO. Short-term: fix logrotate postrotate script; verify with logrotate --debug.',
  '["index=syslog host=demo-server-01.local source=/var/log/syslog message=*logrotate* earliest=-10d | head 20"]'::jsonb,
  'medium','ollama/llama3.1:8b-instruct-q4_K_M',now()-interval'2 days 7 hours 42 minutes'
FROM i;

-- 3-14  MEDIUM memory_leak worker-01 (3 days ago)
WITH i AS (INSERT INTO splunk_incidents (org_id, host, metric_name, anomaly_type, severity, value, mltk_score, splunk_search, detected_at)
  VALUES ('00000000-0000-0000-0000-000000000001','worker-01.prod.local','system.memory.utilization','memory_leak','medium',0.73,5.6,'CAIMP_RAM_MLTK_Alert',now()-interval'3 days 12 hours') RETURNING id)
INSERT INTO splunk_ai_explanations (incident_id,org_id,status,severity,explanation,root_cause,recommended_action,evidence_spl_queries,confidence,llm_provider,completed_at)
SELECT id,'00000000-0000-0000-0000-000000000001','complete','medium',
  'Memory on worker-01.prod.local grew from 42% to 73% over 8 hours. Growth halted after scheduler restart but root cause was not resolved.',
  'The task scheduler held references to completed job result objects in a global results cache. The cache had no TTL configured, accumulating results indefinitely.',
  'Configure TTL=3600 on the results cache. Consider using a Redis-backed cache instead of in-memory to avoid this class of leak.',
  '["index=worker host=worker-01.prod.local source=/var/log/worker/scheduler.log message=*cache* earliest=-3d13h | stats count by message_type"]'::jsonb,
  'medium','ollama/llama3.1:8b-instruct-q4_K_M',now()-interval'3 days 11 hours 28 minutes'
FROM i;

-- 3-15  MEDIUM cpu_saturation cache-01 (4 days ago)
WITH i AS (INSERT INTO splunk_incidents (org_id, host, metric_name, anomaly_type, severity, value, mltk_score, splunk_search, detected_at)
  VALUES ('00000000-0000-0000-0000-000000000001','cache-01.prod.local','system.cpu.utilization','cpu_saturation','medium',0.76,5.4,'CAIMP_CPU_MLTK_Alert',now()-interval'4 days 3 hours') RETURNING id)
INSERT INTO splunk_ai_explanations (incident_id,org_id,status,severity,explanation,root_cause,recommended_action,evidence_spl_queries,confidence,llm_provider,completed_at)
SELECT id,'00000000-0000-0000-0000-000000000001','complete','medium',
  'Redis CPU on cache-01.prod.local reached 76% for 12 minutes. SLOWLOG showed 340 commands >100ms during the window.',
  'A missing index on the sessions key pattern caused Redis to perform O(N) KEYS scans during session cleanup. The cleanup job runs every 4 hours.',
  'Replace KEYS session:* with SCAN-based iteration in the session cleanup job. Add a TTL to session keys to eliminate the need for periodic cleanup.',
  '["index=redis host=cache-01.prod.local slowlog_duration=>100 earliest=-4d4h | stats count avg(duration) by command"]'::jsonb,
  'medium','ollama/llama3.1:8b-instruct-q4_K_M',now()-interval'4 days 2 hours 46 minutes'
FROM i;

-- 3-16  MEDIUM io_wait api-gateway (4 days ago)
WITH i AS (INSERT INTO splunk_incidents (org_id, host, metric_name, anomaly_type, severity, value, mltk_score, splunk_search, detected_at)
  VALUES ('00000000-0000-0000-0000-000000000001','api-gw.prod.local','system.io_wait_pct','io_wait','medium',0.25,5.0,'CAIMP_IOWait_MLTK',now()-interval'4 days 7 hours') RETURNING id)
INSERT INTO splunk_ai_explanations (incident_id,org_id,status,severity,explanation,root_cause,recommended_action,evidence_spl_queries,confidence,llm_provider,completed_at)
SELECT id,'00000000-0000-0000-0000-000000000001','complete','medium',
  'I/O wait on api-gw.prod.local reached 25% during an access log flush spike. Duration: 5 minutes. No external impact.',
  'NGINX access log buffer was set to zero (unbuffered), causing a write syscall for every request. Under 12K RPS, this created significant I/O contention.',
  'Set access_log_buffer in nginx.conf: access_log /var/log/nginx/access.log main buffer=32k flush=5s. Also consider offloading access logs to a remote syslog server.',
  '["index=syslog host=api-gw.prod.local source=nginx.access earliest=-4d8h | timechart span=1m count"]'::jsonb,
  'medium','ollama/llama3.1:8b-instruct-q4_K_M',now()-interval'4 days 6 hours 52 minutes'
FROM i;

-- 3-17  LOW disk_pressure web-01 (5 days ago)
WITH i AS (INSERT INTO splunk_incidents (org_id, host, metric_name, anomaly_type, severity, value, mltk_score, splunk_search, detected_at)
  VALUES ('00000000-0000-0000-0000-000000000001','web-01.prod.local','system.disk.utilization','disk_pressure','low',0.68,3.2,'CAIMP_Disk_MLTK_Alert',now()-interval'5 days 1 hour') RETURNING id)
INSERT INTO splunk_ai_explanations (incident_id,org_id,status,severity,explanation,root_cause,recommended_action,evidence_spl_queries,confidence,llm_provider,completed_at)
SELECT id,'00000000-0000-0000-0000-000000000001','complete','low',
  'Disk at 68% on /var/cache/nginx — slightly above normal trending. No immediate action required.',
  'Nginx proxy cache grew beyond configured limits due to a missing cache_max_size directive in the vhost configuration added last week.',
  'Add proxy_cache_max_size 2g to the new vhost configuration block. Run nginx -s reload to apply.',
  '["index=metrics host=web-01.prod.local metric_name=system.disk.utilization | timechart span=1h avg(value)"]'::jsonb,
  'high','ollama/llama3.1:8b-instruct-q4_K_M',now()-interval'5 days 45 minutes'
FROM i;

-- 3-18  LOW network_anomaly demo-server-01 (6 days ago)
WITH i AS (INSERT INTO splunk_incidents (org_id, host, metric_name, anomaly_type, severity, value, mltk_score, splunk_search, detected_at)
  VALUES ('00000000-0000-0000-0000-000000000001','demo-server-01.local','network.latency_ms','network_anomaly','low',42.1,3.5,'CAIMP_Net_MLTK_Alert',now()-interval'6 days 2 hours') RETURNING id)
INSERT INTO splunk_ai_explanations (incident_id,org_id,status,severity,explanation,root_cause,recommended_action,evidence_spl_queries,confidence,llm_provider,completed_at)
SELECT id,'00000000-0000-0000-0000-000000000001','complete','low',
  'Network latency from demo-server-01.local to the internal gateway briefly spiked to 42ms (baseline 1.2ms) for 3 minutes. Self-resolved.',
  'Transient network congestion on the upstream switch during a scheduled backup window. The backup traffic briefly competed with production traffic on the same uplink.',
  'No immediate action required. Consider scheduling backups to use a dedicated backup VLAN to prevent bandwidth contention.',
  '["index=netflow src=10.0.1.11 earliest=-6d3h | timechart span=1m avg(latency_ms)"]'::jsonb,
  'medium','ollama/llama3.1:8b-instruct-q4_K_M',now()-interval'6 days 1 hour 48 minutes'
FROM i;

-- 3-19  LOW memory_leak cache-01 (6 days ago)
WITH i AS (INSERT INTO splunk_incidents (org_id, host, metric_name, anomaly_type, severity, value, mltk_score, splunk_search, detected_at)
  VALUES ('00000000-0000-0000-0000-000000000001','cache-01.prod.local','system.memory.utilization','memory_leak','low',0.62,3.1,'CAIMP_RAM_MLTK_Alert',now()-interval'6 days 5 hours') RETURNING id)
INSERT INTO splunk_ai_explanations (incident_id,org_id,status,severity,explanation,root_cause,recommended_action,evidence_spl_queries,confidence,llm_provider,completed_at)
SELECT id,'00000000-0000-0000-0000-000000000001','complete','low',
  'Redis memory at 62%, slightly above the 90-day seasonal average of 48%. Growth rate suggests no immediate risk.',
  'Normal seasonal increase in active user sessions preceding the weekend. Redis maxmemory policy is allkeys-lru so eviction will handle it automatically.',
  'No action required. Monitor through the weekend. If memory exceeds 75%, consider increasing Redis maxmemory allocation.',
  '["index=metrics host=cache-01.prod.local metric_name=system.memory.utilization earliest=-6d6h | timechart span=1h avg(value)"]'::jsonb,
  'high','ollama/llama3.1:8b-instruct-q4_K_M',now()-interval'6 days 4 hours 55 minutes'
FROM i;

-- 3-20  LOW cpu_saturation demo-server-01 (7 days ago)
WITH i AS (INSERT INTO splunk_incidents (org_id, host, metric_name, anomaly_type, severity, value, mltk_score, splunk_search, detected_at)
  VALUES ('00000000-0000-0000-0000-000000000001','demo-server-01.local','system.cpu.utilization','cpu_saturation','low',0.71,3.8,'CAIMP_CPU_MLTK_Alert',now()-interval'7 days 3 hours') RETURNING id)
INSERT INTO splunk_ai_explanations (incident_id,org_id,status,severity,explanation,root_cause,recommended_action,evidence_spl_queries,confidence,llm_provider,completed_at)
SELECT id,'00000000-0000-0000-0000-000000000001','complete','low',
  'CPU briefly hit 71% on demo-server-01.local for 6 minutes. Self-resolved. MLTK score 3.8 — borderline anomaly.',
  'Weekly package update check (apt-get update) ran concurrently with a scheduled health check script. Combined, they briefly pushed CPU above the baseline.',
  'Stagger the package update cron job to run 30 minutes after the health check script to avoid CPU spikes. Consider running with nice -n 10.',
  '["index=syslog host=demo-server-01.local source=/var/log/syslog message=*apt* earliest=-7d4h | head 20"]'::jsonb,
  'medium','ollama/llama3.1:8b-instruct-q4_K_M',now()-interval'7 days 2 hours 44 minutes'
FROM i;

-- ── 4. Anomaly events (matches incidents + standalone) ────────────────────────
INSERT INTO anomaly_events (time, org_id, server_id, metric_name, value, threshold, detector, severity) VALUES
    (now()-interval'2 hours',    '00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000012','system.cpu.utilization',0.97,0.90,'static','critical'),
    (now()-interval'3 hours',    '00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000013','system.memory.utilization',0.94,0.85,'zscore','critical'),
    (now()-interval'4 hours',    '00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000013','system.disk.utilization',0.88,0.80,'static','critical'),
    (now()-interval'5 hours',    '00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000014','process.crash_count',1,0,'rate_of_change','critical'),
    (now()-interval'6 hours',    '00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000014','system.cpu.utilization',0.89,0.85,'zscore','critical'),
    (now()-interval'8 hours',    '00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000013','system.io_wait_pct',0.41,0.30,'zscore','critical'),
    (now()-interval'12 hours',   '00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000012','network.packet_loss_pct',0.12,0.05,'static','critical'),
    (now()-interval'1 day',      '00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000011','system.memory.utilization',0.82,0.80,'zscore','critical'),
    (now()-interval'2 days',     '00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000015','network.retransmit_rate',0.067,0.02,'rate_of_change','warning'),
    (now()-interval'3 days',     '00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000014','system.io_wait_pct',0.29,0.25,'static','warning'),
    (now()-interval'3 days 6 hours','00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000014','system.memory.utilization',0.73,0.70,'zscore','warning'),
    (now()-interval'4 days',     '00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000015','system.cpu.utilization',0.76,0.75,'static','warning'),
    (now()-interval'5 days',     '00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000013','system.cpu.utilization',0.91,0.85,'zscore','critical'),
    (now()-interval'6 days',     '00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000011','system.memory.utilization',0.62,0.60,'static','warning'),
    (now()-interval'7 days',     '00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000011','system.cpu.utilization',0.71,0.70,'static','warning');

-- ── 5. Metrics time-series (7 days, 15-min intervals) ────────────────────────
-- demo-server-01 — CPU (normal 20-40% with spikes at anomaly times)
INSERT INTO metrics (time, org_id, server_id, metric_name, labels, value)
SELECT
    ts,
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000011',
    'system.cpu.utilization',
    '{"host":"demo-server-01.local"}',
    CASE
        WHEN ts BETWEEN now()-interval'7 days 3 hours 15 minutes' AND now()-interval'7 days 2 hours 45 minutes' THEN 0.68 + random()*0.06
        WHEN ts BETWEEN now()-interval'1 day 15 minutes' AND now()-interval'23 hours 45 minutes' THEN 0.55 + random()*0.10
        ELSE 0.18 + random()*0.22 + sin(extract(epoch from ts)/3600)*0.04
    END
FROM generate_series(now()-interval'7 days', now(), interval'15 minutes') ts
ON CONFLICT DO NOTHING;

-- demo-server-01 — Memory
INSERT INTO metrics (time, org_id, server_id, metric_name, labels, value)
SELECT ts,
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000011',
    'system.memory.utilization',
    '{"host":"demo-server-01.local"}',
    CASE
        WHEN ts BETWEEN now()-interval'1 day 6 hours' AND now()-interval'23 hours' THEN 0.45 + (extract(epoch from (ts-(now()-interval'1 day 6 hours')))/3600)*0.063
        ELSE 0.40 + random()*0.12
    END
FROM generate_series(now()-interval'7 days', now(), interval'15 minutes') ts
ON CONFLICT DO NOTHING;

-- demo-server-01 — Disk
INSERT INTO metrics (time, org_id, server_id, metric_name, labels, value)
SELECT ts,
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000011',
    'system.filesystem.utilization',
    '{"host":"demo-server-01.local"}',
    0.52 + (extract(epoch from (ts-(now()-interval'7 days')))/604800)*0.12 + random()*0.02
FROM generate_series(now()-interval'7 days', now(), interval'15 minutes') ts
ON CONFLICT DO NOTHING;

-- web-server-01 — CPU (traffic spike 2h ago)
INSERT INTO metrics (time, org_id, server_id, metric_name, labels, value)
SELECT ts,
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000012',
    'system.cpu.utilization',
    '{"host":"web-01.prod.local"}',
    CASE
        WHEN ts BETWEEN now()-interval'2 hours 15 minutes' AND now()-interval'1 hour 45 minutes' THEN 0.88 + random()*0.10
        WHEN ts BETWEEN now()-interval'12 hours 15 minutes' AND now()-interval'11 hours 30 minutes' THEN 0.62 + random()*0.12
        ELSE 0.25 + random()*0.18 + sin(extract(epoch from ts)/7200)*0.06
    END
FROM generate_series(now()-interval'7 days', now(), interval'15 minutes') ts
ON CONFLICT DO NOTHING;

-- web-server-01 — Memory
INSERT INTO metrics (time, org_id, server_id, metric_name, labels, value)
SELECT ts,
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000012',
    'system.memory.utilization',
    '{"host":"web-01.prod.local"}',
    0.45 + random()*0.15
FROM generate_series(now()-interval'7 days', now(), interval'15 minutes') ts
ON CONFLICT DO NOTHING;

-- web-server-01 — Disk
INSERT INTO metrics (time, org_id, server_id, metric_name, labels, value)
SELECT ts,
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000012',
    'system.filesystem.utilization',
    '{"host":"web-01.prod.local"}',
    CASE
        WHEN ts BETWEEN now()-interval'5 days 1 hour 15 minutes' AND now()-interval'4 days 22 hours' THEN 0.67 + random()*0.03
        ELSE 0.55 + random()*0.06
    END
FROM generate_series(now()-interval'7 days', now(), interval'15 minutes') ts
ON CONFLICT DO NOTHING;

-- db-primary — CPU
INSERT INTO metrics (time, org_id, server_id, metric_name, labels, value)
SELECT ts,
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000013',
    'system.cpu.utilization',
    '{"host":"db-01.prod.local"}',
    CASE
        WHEN ts BETWEEN now()-interval'3 hours 15 minutes' AND now()-interval'2 hours 45 minutes' THEN 0.82 + random()*0.12
        WHEN ts BETWEEN now()-interval'8 hours 15 minutes' AND now()-interval'7 hours 30 minutes' THEN 0.73 + random()*0.10
        WHEN ts BETWEEN now()-interval'5 days 2 hours 15 minutes' AND now()-interval'5 days 1 hour 30 minutes' THEN 0.87 + random()*0.06
        ELSE 0.30 + random()*0.18
    END
FROM generate_series(now()-interval'7 days', now(), interval'15 minutes') ts
ON CONFLICT DO NOTHING;

-- db-primary — Memory (gradual climb)
INSERT INTO metrics (time, org_id, server_id, metric_name, labels, value)
SELECT ts,
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000013',
    'system.memory.utilization',
    '{"host":"db-01.prod.local"}',
    CASE
        WHEN ts BETWEEN now()-interval'4 hours 30 minutes' AND now()-interval'2 hours 30 minutes'
            THEN 0.52 + (extract(epoch from (ts-(now()-interval'4 hours 30 minutes')))/7200)*0.44
        WHEN ts > now()-interval'2 hours 30 minutes' THEN 0.54 + random()*0.08
        ELSE 0.50 + random()*0.08
    END
FROM generate_series(now()-interval'7 days', now(), interval'15 minutes') ts
ON CONFLICT DO NOTHING;

-- db-primary — Disk (climbing)
INSERT INTO metrics (time, org_id, server_id, metric_name, labels, value)
SELECT ts,
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000013',
    'system.filesystem.utilization',
    '{"host":"db-01.prod.local"}',
    0.68 + (extract(epoch from (ts-(now()-interval'7 days')))/604800)*0.22 + random()*0.01
FROM generate_series(now()-interval'7 days', now(), interval'15 minutes') ts
ON CONFLICT DO NOTHING;

-- worker-01 — CPU (batch job spikes + degraded state)
INSERT INTO metrics (time, org_id, server_id, metric_name, labels, value)
SELECT ts,
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000014',
    'system.cpu.utilization',
    '{"host":"worker-01.prod.local"}',
    CASE
        WHEN ts BETWEEN now()-interval'6 hours 15 minutes' AND now()-interval'5 hours 30 minutes' THEN 0.83 + random()*0.09
        WHEN ts > now()-interval'30 minutes' THEN 0.68 + random()*0.12
        ELSE 0.35 + random()*0.20
    END
FROM generate_series(now()-interval'7 days', now(), interval'15 minutes') ts
ON CONFLICT DO NOTHING;

-- cache-01 — CPU + Memory
INSERT INTO metrics (time, org_id, server_id, metric_name, labels, value)
SELECT ts,
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000015',
    'system.cpu.utilization',
    '{"host":"cache-01.prod.local"}',
    CASE
        WHEN ts BETWEEN now()-interval'4 days 3 hours 15 minutes' AND now()-interval'4 days 2 hours 45 minutes' THEN 0.73 + random()*0.06
        ELSE 0.08 + random()*0.12
    END
FROM generate_series(now()-interval'7 days', now(), interval'15 minutes') ts
ON CONFLICT DO NOTHING;

INSERT INTO metrics (time, org_id, server_id, metric_name, labels, value)
SELECT ts,
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000015',
    'system.memory.utilization',
    '{"host":"cache-01.prod.local"}',
    0.48 + random()*0.16 + sin(extract(epoch from ts)/86400)*0.08
FROM generate_series(now()-interval'7 days', now(), interval'15 minutes') ts
ON CONFLICT DO NOTHING;

-- ── 6. Runbooks ───────────────────────────────────────────────────────────────
INSERT INTO runbooks (org_id, title, anomaly_type, content, created_by) VALUES

('00000000-0000-0000-0000-000000000001',
 'CPU Saturation — Diagnosis and Remediation',
 'cpu_saturation',
 E'## Symptoms\nCPU utilization sustained above 85% for more than 5 minutes. MLTK anomaly score >7.0. Query latency degradation or request queuing.\n\n## Quick Triage\n```bash\n# Top processes by CPU\ntop -b -n1 | head -20\nps aux --sort=-%cpu | head -10\n\n# Check recent deployments\njournal -u app.service --since -2h | grep -i deploy\n\n# Check cron jobs\ncrontab -l; systemctl list-timers --all\n```\n\n## Common Root Causes\n1. **Traffic spike**: Check load balancer metrics for request volume surge\n2. **Batch job overlap**: Review cron schedule for concurrent heavy jobs\n3. **Memory pressure causing swap thrashing**: Check swap usage\n4. **Bug in new deployment**: Correlate with recent releases\n\n## Remediation\n1. **Immediate**: Identify top CPU consumer and assess if it can be killed/restricted\n2. **Short-term**: Scale horizontally if load is legitimate\n3. **Long-term**: Profile the application and optimize hot paths',
 '00000000-0000-0000-0000-000000000002'),

('00000000-0000-0000-0000-000000000001',
 'Memory Leak — Identification and Containment',
 'memory_leak',
 E'## Symptoms\nMemory utilization growing monotonically without GC recovery. Linear growth pattern over hours. Process RSS increasing without corresponding workload increase.\n\n## Quick Triage\n```bash\n# Memory by process\nps aux --sort=-%mem | head -10\n\n# Java heap (if applicable)\njmap -heap <PID>\njcmd <PID> VM.native_memory\n\n# Check for file descriptor leaks\nls /proc/<PID>/fd | wc -l\n\n# Recent deployments\ngit log --oneline -10\n```\n\n## Common Root Causes\n1. **Unbounded cache**: No TTL or max-size on in-memory cache\n2. **Connection pool not releasing**: DB/Redis connections held open\n3. **Event listener accumulation**: Listeners added but never removed\n4. **Large object retention**: GC roots preventing collection\n\n## Remediation\n1. **Immediate**: Graceful restart (preserves active connections)\n2. **Short-term**: Enable heap dump on OOM: -XX:+HeapDumpOnOutOfMemoryError\n3. **Long-term**: Add memory leak detection to CI pipeline (e.g., LeakCanary)',
 '00000000-0000-0000-0000-000000000002'),

('00000000-0000-0000-0000-000000000001',
 'Disk Pressure — Recovery Procedures',
 'disk_pressure',
 E'## Symptoms\nDisk utilization above 75%. Growth trajectory approaching 90% threshold. Possible write failures or PostgreSQL PANIC if disk fills completely.\n\n## Immediate Actions (if >85%)\n```bash\n# Find top disk consumers\ndu -sh /* 2>/dev/null | sort -rh | head -20\ndu -sh /var/log/* | sort -rh | head -10\n\n# Large files\nfind / -type f -size +500M 2>/dev/null\n\n# Truncate logs safely\ntruncate -s 0 /var/log/app/app.log\n\n# Force logrotate\nlogrotate -f /etc/logrotate.conf\n```\n\n## PostgreSQL-specific\n```sql\n-- Check WAL accumulation\nSELECT pg_size_pretty(sum(size)) FROM pg_ls_waldir();\n\n-- Re-enable archiving\nALTER SYSTEM SET archive_command = ''cp %p /archive/%f'';\nSELECT pg_reload_conf();\nSELECT pg_switch_wal();\n```\n\n## Long-term\n- Set up disk space alerting at 70% (warn) and 80% (critical)\n- Implement automated log rotation validation\n- Consider log forwarding to centralized logging (Splunk/ELK)',
 '00000000-0000-0000-0000-000000000002'),

('00000000-0000-0000-0000-000000000001',
 'Network Anomaly — Packet Loss and Latency',
 'network_anomaly',
 E'## Symptoms\nPacket loss >1% or latency spike >3x baseline. TCP retransmit rate elevated. Downstream service error rates increasing.\n\n## Quick Triage\n```bash\n# Packet loss test\nping -c 100 -i 0.1 <gateway_ip> | tail -5\n\n# MTU check\nip link show | grep mtu\npathping <destination>\n\n# Interface errors\nip -s link show eth0\n\n# TCP retransmits\nnetstat -s | grep retransmit\nss -s\n```\n\n## Common Root Causes\n1. **Switch firmware bug**: Check switch release notes for known issues\n2. **MTU mismatch**: Jumbo frames misconfigured after network change\n3. **NIC hardware failure**: Check dmesg for NIC errors\n4. **Bandwidth saturation**: Check interface utilization metrics\n5. **Security group change**: Verify no new rules dropped during incident window\n\n## Remediation\n1. **Failover**: If bonded NICs, disable the affected interface\n2. **Switch**: Roll back recent firmware changes\n3. **MTU**: Restore to 1500 (standard) or 9000 (jumbo, if configured)',
 '00000000-0000-0000-0000-000000000002'),

('00000000-0000-0000-0000-000000000001',
 'Process Crash — Triage and Recovery',
 'process_crash',
 E'## Symptoms\nSupervisor restart loop. Service unavailability. Repeated crash entries in systemd journal or process supervisor logs.\n\n## Quick Triage\n```bash\n# Systemd service status\nsystemctl status app.service\njournalctl -u app.service --since -1h | tail -50\n\n# Core dump check\nls -la /var/crash/ /tmp/core* 2>/dev/null\n\n# OOM kill check\ndmesg | grep -i "oom\\|killed"\njournalctl -k | grep -i oom\n\n# Check for bad payloads in queue\n# (adjust queue tool as appropriate)\nredis-cli lrange dead_letter_queue 0 5\n```\n\n## Dead Letter Queue Handling\nIf crash is caused by a malformed job:\n```bash\n# Inspect the failing payload\nredis-cli lrange dlq:failed_jobs 0 0\n\n# Move to quarantine for analysis\nredis-cli lmove dlq:failed_jobs quarantine:jobs LEFT LEFT\n\n# Restart service after removing bad payload\nsystemctl restart app.service\n```\n\n## Preventing Recurrence\n1. Add schema validation at job enqueue with reject-on-invalid policy\n2. Configure DLQ with max-retry=3 before quarantine\n3. Add crash alerting with automatic core dump collection\n4. Implement canary deployments to catch crashes before full rollout',
 '00000000-0000-0000-0000-000000000002')

ON CONFLICT DO NOTHING;

-- ── 7. Notifications (shows recent alert activity) ────────────────────────────
INSERT INTO notifications (org_id, server_id, severity, message, channel, fired_at) VALUES
    ('00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000012','critical','CPU saturation on web-01.prod.local: 97% (MLTK score 9.8)','webhook',now()-interval'2 hours'),
    ('00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000013','critical','Memory leak on db-01.prod.local: 94% utilization','webhook',now()-interval'3 hours'),
    ('00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000013','critical','Disk pressure on db-01.prod.local: WAL accumulation detected','webhook',now()-interval'4 hours'),
    ('00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000014','critical','Process crash loop on worker-01.prod.local (3 restarts in 2min)','webhook',now()-interval'5 hours'),
    ('00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000014','critical','CPU spike on worker-01.prod.local: 89% during batch job','webhook',now()-interval'6 hours'),
    ('00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000012','warning','Network packet loss on web-01.prod.local: 12% (TOR-02 firmware)','webhook',now()-interval'12 hours'),
    ('00000000-0000-0000-0000-000000000001','00000000-0000-0000-0000-000000000011','warning','Memory anomaly on demo-server-01.local: session cache leak','webhook',now()-interval'1 day');

-- ── 8. Server Forecasts (Holt-Winters predictions for the Forecasts page) ───────
-- One row per (server, metric) — 24-hour horizon with confidence bands.
-- Forecast points generated via generate_series; slopes set to produce realistic
-- time_to_critical values so the UI shows a meaningful mix of health levels.
--
-- Health outcomes:
--   demo-server-01 → HEALTHY   (all metrics stable)
--   web-server-01  → AT RISK   (CPU trending up, breach in ~22h)
--   db-primary     → CRITICAL  (disk breach in ~5h, RAM breach in ~12h)
--   worker-01      → AT RISK   (CPU + RAM elevated, breach in ~18-23h)
--   cache-01       → HEALTHY   (Redis low utilisation)

WITH params (sid, metric, base, slope, sigma, ttc, narrative, conf) AS (VALUES
  -- demo-server-01 (HEALTHY)
  ('00000000-0000-0000-0000-000000000011'::uuid, 'cpu_percent',    0.26::float, 0.0010::float, 0.030::float, NULL::float,
   'CPU on demo-server-01 is stable at ~26% with a gentle positive trend (+0.1%/h). No threshold breach expected in the 24-hour window. Model confidence is high based on a consistent 7-day baseline.', 'high'::text),

  ('00000000-0000-0000-0000-000000000011'::uuid, 'memory_percent', 0.46::float, 0.0005::float, 0.040::float, NULL::float,
   'Memory on demo-server-01 is steady at ~46%. Minimal drift detected. No memory leak patterns. Expected to remain well below the 90% threshold throughout the forecast horizon.', 'high'::text),

  ('00000000-0000-0000-0000-000000000011'::uuid, 'disk_percent',   0.60::float, 0.0015::float, 0.020::float, NULL::float,
   'Disk on demo-server-01 is at 60% with slow growth (+0.15%/h), consistent with normal log accumulation. At this rate the 90% threshold would be reached in ~200 hours. A weekly cleanup cron job is recommended.', 'high'::text),

  -- web-server-01 (AT RISK — CPU trending up post-spike)
  ('00000000-0000-0000-0000-000000000012'::uuid, 'cpu_percent',    0.64::float, 0.0120::float, 0.050::float, 21.7::float,
   'CPU on web-01.prod.local is elevated at 64% with an accelerating trend (+1.2%/h). The Holt-Winters model forecasts the 90% threshold will be breached in approximately 21.7 hours if the current load pattern continues. This is likely residual from the earlier traffic surge — monitor closely and pre-scale if request volume remains elevated.', 'high'::text),

  ('00000000-0000-0000-0000-000000000012'::uuid, 'memory_percent', 0.51::float, 0.0010::float, 0.040::float, NULL::float,
   'Memory on web-01.prod.local is at 51%, stable with minimal growth. No immediate concern. If the expected CPU spike materialises with high request volume, memory pressure may increase due to in-flight request state.', 'medium'::text),

  ('00000000-0000-0000-0000-000000000012'::uuid, 'disk_percent',   0.57::float, 0.0010::float, 0.020::float, NULL::float,
   'Disk on web-01.prod.local is at 57% with slow growth. No breach expected within the 24-hour forecast window. Normal nginx access log accumulation pattern.', 'high'::text),

  -- db-primary (CRITICAL — disk filling, RAM rising)
  ('00000000-0000-0000-0000-000000000013'::uuid, 'cpu_percent',    0.44::float, 0.0020::float, 0.040::float, NULL::float,
   'CPU on db-01.prod.local is at 44%, stable since the autovacuum incident was resolved. Minor positive trend from routine WAL write activity. No threshold breach within the forecast window.', 'high'::text),

  ('00000000-0000-0000-0000-000000000013'::uuid, 'memory_percent', 0.71::float, 0.0160::float, 0.050::float, 11.9::float,
   'Memory on db-01.prod.local is at 71% and rising at 1.6%/h. The analytics query cancellation did not fully resolve the underlying growth pattern. The Holt-Winters model forecasts the 90% threshold will be breached in approximately 11.9 hours. Intervention required: confirm idle_in_transaction_session_timeout is set and verify no other long-running cursors are open.', 'high'::text),

  ('00000000-0000-0000-0000-000000000013'::uuid, 'disk_percent',   0.87::float, 0.0060::float, 0.015::float, 5.0::float,
   'CRITICAL: Disk on db-01.prod.local is at 87% and rising at 0.6%/h. WAL archiving re-enablement has not yet taken full effect — pg_wal/ continues to accumulate segments. The 90% threshold is projected to be breached in approximately 5 hours. Immediate action required: verify archive_command is executing (check pg_stat_archiver), confirm pg_switch_wal() was called, and consider manual WAL cleanup if archiving is still stalled.', 'high'::text),

  -- worker-01 (AT RISK — CPU + RAM elevated, degraded state)
  ('00000000-0000-0000-0000-000000000014'::uuid, 'cpu_percent',    0.67::float, 0.0100::float, 0.050::float, 23.0::float,
   'CPU on worker-01.prod.local remains elevated at 67% in degraded state with a trend of +1.0%/h. The background processing issue has not been fully resolved. Threshold breach is expected in approximately 23 hours if workload is not reduced. Consider reducing AI_WORKER_CONCURRENCY from 2 to 1 temporarily.', 'medium'::text),

  ('00000000-0000-0000-0000-000000000014'::uuid, 'memory_percent', 0.73::float, 0.0090::float, 0.040::float, 18.9::float,
   'Memory on worker-01.prod.local is at 73% with growth of 0.9%/h. The results cache TTL fix has slowed but not stopped the leak. Current trajectory forecasts threshold breach in approximately 18.9 hours. Deploy the cache TTL configuration fix and restart the scheduler to reclaim memory.', 'medium'::text),

  ('00000000-0000-0000-0000-000000000014'::uuid, 'disk_percent',   0.44::float, 0.0010::float, 0.030::float, NULL::float,
   'Disk on worker-01.prod.local is stable at 44%. No growth pattern of concern. Not a factor in the current degraded state.', 'high'::text),

  -- cache-01 (HEALTHY)
  ('00000000-0000-0000-0000-000000000015'::uuid, 'cpu_percent',    0.11::float,-0.0005::float, 0.025::float, NULL::float,
   'CPU on cache-01.prod.local is very low at ~11% with a slight negative trend. Redis is operating efficiently following the KEYS → SCAN migration. No concerns within the forecast window.', 'high'::text),

  ('00000000-0000-0000-0000-000000000015'::uuid, 'memory_percent', 0.54::float, 0.0020::float, 0.040::float, NULL::float,
   'Redis memory on cache-01.prod.local is at 54% with slow growth (+0.2%/h), consistent with normal weekend session accumulation. The allkeys-lru eviction policy will handle load increases automatically. No breach predicted within 24 hours.', 'high'::text),

  ('00000000-0000-0000-0000-000000000015'::uuid, 'disk_percent',   0.39::float, 0.0008::float, 0.015::float, NULL::float,
   'Disk on cache-01.prod.local is at 39%, growing very slowly. No concerns within the forecast window.', 'high'::text)
),
with_points AS (
  SELECT
    p.*,
    (
      SELECT jsonb_agg(jsonb_build_object(
        'hour',      h,
        'predicted', round(LEAST(1.0, GREATEST(0, p.base + h * p.slope         ))::numeric, 4)::float,
        'lower',     round(LEAST(1.0, GREATEST(0, p.base + h * p.slope - p.sigma))::numeric, 4)::float,
        'upper',     round(LEAST(1.0,             p.base + h * p.slope + p.sigma)::numeric, 4)::float
      ) ORDER BY h)
      FROM generate_series(1, 24) h
    ) AS pts
  FROM params p
)
INSERT INTO server_forecasts
  (org_id, server_id, metric_name, horizon_hours, forecast_points,
   time_to_critical, critical_threshold, trend_slope, ml_model,
   llm_narrative, llm_confidence)
SELECT
  '00000000-0000-0000-0000-000000000001'::uuid,
  w.sid, w.metric, 24, w.pts,
  w.ttc, 0.9, w.slope, 'holt_linear',
  w.narrative, w.conf
FROM with_points w;

RESET ROLE;

\echo ''
\echo '✓ Demo data seeded successfully!'
\echo '  Servers:       6 (5 online, 1 degraded, 1 offline)'
\echo '  Incidents:    20 (4 critical, 6 high, 7 medium, 3 low)'
\echo '  AI analyses:  19 complete, 1 pending'
\echo '  Metrics:   ~10k rows (7 days × 15-min intervals × 5 servers × 3 metrics)'
\echo '  Forecasts:    15 rows (5 servers × 3 metrics: CRITICAL/AT RISK/HEALTHY mix)'
\echo '  Runbooks:      5'
\echo '  Notifications: 7'
