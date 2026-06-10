# Splunk Configuration — CAIMP

This directory contains all Splunk configuration files for the CAIMP
Splunk + LLM Anomaly Detection module.

---

## Installation Order

Follow this order exactly. Each step must complete before the next.

### Step 1 — Copy config files to Splunk

Copy the following files to `$SPLUNK_HOME/etc/system/local/` on your
Splunk indexer (or Search Head if single-instance):

```
splunk/props.conf       → $SPLUNK_HOME/etc/system/local/props.conf
splunk/transforms.conf  → $SPLUNK_HOME/etc/system/local/transforms.conf
splunk/indexes.conf     → $SPLUNK_HOME/etc/system/local/indexes.conf
splunk/inputs.conf      → $SPLUNK_HOME/etc/system/local/inputs.conf
```

> If any of these files already exist in `local/`, merge the stanzas —
> do not overwrite the entire file.

**Indexes created by `indexes.conf`:**

| Index | Type | Retention | Purpose |
|-------|------|-----------|---------|
| `caimp_metrics` | metric | 7 days raw | Raw metric events from agents |
| `caimp_logs` | event | 90 days | Application and system logs |
| `caimp_anomalies` | event | 90 days | MLTK anomaly scores |
| `caimp_ai` | event | 90 days | AI explanation writebacks |
| `caimp_metrics_5m` | event | 90 days | 5-minute rollup summary |
| `caimp_metrics_1h` | event | 1 year | 1-hour rollup summary |
| `caimp_metrics_1d` | event | 3 years | 1-day rollup summary |

### Step 2 — Restart Splunk

```bash
$SPLUNK_HOME/bin/splunk restart
```

Wait for Splunk to report "Splunk started" before continuing.

### Step 3 — Create HEC tokens

1. Open Splunk Web → **Settings → Data Inputs → HTTP Event Collector**
2. Create three tokens:

   | Token name          | Allowed index    | Sourcetype          |
   |---------------------|-----------------|---------------------|
   | `caimp_metrics`     | `caimp_metrics` | `caimp:metrics`     |
   | `caimp_logs`        | `caimp_logs`    | `caimp:logs`        |
   | `caimp_ai`          | `caimp_ai`      | `caimp:ai_explanation` |

3. Paste each token value into `inputs.conf` replacing
   `<REPLACE_WITH_HEC_TOKEN_*>` placeholders.
4. Copy the updated `inputs.conf` back to Splunk and restart again.

### Step 4 — Verify HEC is healthy

```bash
curl -k https://<splunk-host>:8088/services/collector/health
```

Expected response:
```json
{"text":"HEC is healthy","code":17}
```

### Step 5 — Verify metric schema

After ingesting at least one metric event through the HEC Bridge, run
this SPL in Splunk Web:

```spl
| mstats avg(_value) WHERE index=caimp_metrics | head 1
```

- **Rows returned** → schema is correct, `mstats` can read the index.
- **Empty result** → check that `props.conf` sourcetype matches
  `caimp:metrics` and restart Splunk indexers.

---

## KV Store setup (baselines)

Required for the AI Orchestrator context builder. The `caimp_baselines`
lookup table holds 24-hour rolling statistics per host+metric so the AI
orchestrator can read them instantly via REST without running a full SPL search.

### 1 — Copy collections.conf

```bash
cp splunk/collections.conf $SPLUNK_HOME/etc/apps/search/metadata/collections.conf
```

> If a `collections.conf` already exists there, **merge** the `[caimp_baselines]`
> stanza — do not overwrite.

### 2 — Restart Splunk

```bash
$SPLUNK_HOME/bin/splunk restart
```

### 3 — Deploy the baseline compute search

The `CAIMP - 24h Baseline Compute` search is already included in
`rollup_searches.conf` (Step 3). It runs every 5 minutes and writes
rolling 24-hour statistics into the `caimp_baselines` KV Store lookup:

| Field | Description |
|-------|-------------|
| `host` | Server hostname |
| `org_id` | Tenant org UUID |
| `metric_name` | e.g. `system.cpu.utilization` |
| `avg_val` | 24h mean |
| `stddev_val` | 24h standard deviation |
| `min_val` / `max_val` | 24h range |
| `p5_val` / `p95_val` | 5th and 95th percentile |
| `computed_at` | Unix epoch of last compute |

### 4 — Verify (after 30+ minutes of metric ingestion)

```spl
| inputlookup caimp_baselines | head 5
```

Should return rows with all stat fields populated per `host` + `metric_name`.

**Reading baselines from the AI Orchestrator (Python):**
```python
results = await splunk.run_search_oneshot(
    '| inputlookup caimp_baselines WHERE host="web-01" metric_name="system.cpu.utilization" | head 1'
)
# returns: {"avg_val": 45.2, "stddev_val": 8.1, "p95_val": 78.3, ...}
```

---

## Rollup scheduled searches

Copy `splunk/rollup_searches.conf` to Splunk:

```
splunk/rollup_searches.conf → $SPLUNK_HOME/etc/system/local/savedsearches.conf
```

> If `savedsearches.conf` already exists, **merge** the stanzas — do not overwrite.

**Schedule summary:**

| Search | Runs | Reads from | Writes to |
|--------|------|------------|-----------|
| `CAIMP - 5-Minute Metric Rollup` | Every 5 min | `caimp_metrics` (raw) | `caimp_metrics_5m` |
| `CAIMP - 1-Hour Metric Rollup` | Every hour at :05 | `caimp_metrics` (raw) | `caimp_metrics_1h` |
| `CAIMP - 1-Day Metric Rollup` | Daily at 01:00 UTC | `caimp_metrics` (raw) | `caimp_metrics_1d` |

**Verify after one cron cycle (5+ minutes of data ingested):**

```spl
search index=caimp_metrics_5m | head 5
```

Should return rows with `avg_val`, `max_val`, `min_val`, `tier="5m"` fields.

---

## Custom alert action (Step 8)

The `caimp_webhook` alert action is what Splunk calls when an anomaly search
fires. It packages the result row as JSON and POSTs to the AI Orchestrator.

### Installation

```bash
# 1. Create the CAIMP app directory
mkdir -p $SPLUNK_HOME/etc/apps/caimp/bin
mkdir -p $SPLUNK_HOME/etc/apps/caimp/default
mkdir -p $SPLUNK_HOME/etc/apps/caimp/metadata

# 2. Copy files
cp splunk/bin/caimp_webhook.py   $SPLUNK_HOME/etc/apps/caimp/bin/
cp splunk/alert_actions.conf     $SPLUNK_HOME/etc/apps/caimp/default/
cp splunk/metadata/default.meta  $SPLUNK_HOME/etc/apps/caimp/metadata/

# 3. Restart Splunk
$SPLUNK_HOME/bin/splunk restart
```

### Verify (manual test)

```bash
echo '{
  "configuration": {
    "endpoint": "http://ai-orchestrator:8010/webhook/anomaly",
    "search_name": "CAIMP - CPU Anomaly Detection"
  },
  "result": {
    "host": "web-01",
    "org_id": "00000000-0000-0000-0000-000000000001",
    "cpu_pct": "97.3",
    "score": "0.0012",
    "anomaly_type": "cpu_saturation",
    "severity": "critical",
    "_time": "2026-05-20T10:00:00Z"
  }
}' | python splunk/bin/caimp_webhook.py
```

Exit code `0` = webhook delivered. Exit code `1` = delivery failed (check
`/var/log/splunk/caimp_webhook.log` on the Splunk server).

### What it sends to the AI Orchestrator

```json
{
  "anomaly_id": "<uuid>",
  "timestamp": "2026-05-20T10:00:00Z",
  "host": "web-01",
  "org_id": "00000000-0000-0000-0000-000000000001",
  "metric_name": "system.cpu.utilization",
  "anomaly_type": "cpu_saturation",
  "severity": "critical",
  "value": 97.3,
  "score": 0.0012,
  "splunk_search_name": "CAIMP - CPU Anomaly Detection"
}
```

---

## Anomaly detection searches (Step 7)

Four scoring searches are added to `savedsearches.conf` alongside the training
searches from Step 6. They run continuously and fire the `caimp_webhook` alert
action when anomalies are detected.

**Prerequisite:** MLTK models must be trained (Step 6) before enabling the CPU
and Memory searches. Disk and Network searches have no model dependency.

| Search | Method | Runs | Fires when |
|--------|--------|------|------------|
| `CAIMP - CPU Anomaly Detection` | MLTK `DensityFunction` | Every 1 min | `IsOutlier=1` or cpu > 95% |
| `CAIMP - Memory Anomaly Detection` | MLTK `DensityFunction` | Every 1 min | `IsOutlier=1` or mem > 90% |
| `CAIMP - Disk Anomaly Detection` | Threshold only | Every 5 min | disk > 85% |
| `CAIMP - Network Traffic Forecast` | `StateSpaceForecast` | Every 5 min | Outside 95% CI |

All searches POST to `http://ai-orchestrator:8010/webhook/anomaly` via
the `caimp_webhook` custom alert action (configured in Step 8).

**To enable after deploying savedsearches.conf:**
```bash
# Merge and restart Splunk
cat splunk/savedsearches.conf >> $SPLUNK_HOME/etc/system/local/savedsearches.conf
$SPLUNK_HOME/bin/splunk restart
```

**Verify searches are scheduled:**
```spl
| rest /services/saved/searches
| search title="CAIMP -*"
| table title, cron_schedule, next_scheduled_time, disabled
```

---

## MLTK model training (Step 6)

**Prerequisite:** 7+ days of metric data must exist in `caimp_metrics` before training.
With less data the `DensityFunction` model will have poor baseline coverage.

### 1 — Copy savedsearches.conf

```bash
# Merge into existing file — do not overwrite
cat splunk/savedsearches.conf >> $SPLUNK_HOME/etc/system/local/savedsearches.conf
$SPLUNK_HOME/bin/splunk restart
```

### 2 — Run training searches manually (first deploy only)

In Splunk Web → **Settings → Searches, Reports & Alerts**:

1. Find **CAIMP - Train CPU Density Model** → click **Run**
   Wait for job to complete (~1–3 min depending on data volume).
2. Find **CAIMP - Train Memory Density Model** → click **Run**

After that the weekly schedule (Sunday 02:00 / 03:00 UTC) keeps models current.

### 3 — Verify models exist

```spl
| rest /services/saved/searches | search title="CAIMP - Train*" | table title, next_scheduled_time
```

To confirm a model was saved successfully:
```spl
| summary app:cpu_density_model
```
Should return model metadata. If empty: re-run the training search.

### Training schedule

| Model | Search | Schedule |
|-------|--------|----------|
| `app:cpu_density_model` | CAIMP - Train CPU Density Model | Sundays 02:00 UTC |
| `app:mem_density_model` | CAIMP - Train Memory Density Model | Sundays 03:00 UTC |

---

## File reference

| File | Purpose |
|------|---------|
| `props.conf` | Metric schema binding for `caimp:metrics` sourcetype |
| `transforms.conf` | Dimension/measure field declaration for `mstats` |
| `indexes.conf` | All CAIMP indexes (raw + rollup tiers) |
| `inputs.conf` | HEC token configuration |
| `collections.conf` | KV Store schema for baseline statistics |
| `savedsearches.conf` | MLTK detection + rollup scheduled searches |
| `rollup_searches.conf` | 5m / 1h / 1d rollup SPL |
| `alert_actions.conf` | Custom alert action definition |
| `bin/caimp_webhook.py` | Alert action script (POST anomaly to AI orchestrator) |
