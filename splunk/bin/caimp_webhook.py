"""
CAIMP custom alert action — called by Splunk when an anomaly search fires.
Packages the result row as JSON and POSTs to the AI Orchestrator webhook.

Installation:
  Copy splunk/bin/ to $SPLUNK_HOME/etc/apps/caimp/bin/
  Copy splunk/alert_actions.conf to $SPLUNK_HOME/etc/apps/caimp/default/
  Restart Splunk.
"""
import json
import logging
import sys
import urllib.request
import urllib.error
from uuid import uuid4

logging.basicConfig(
    filename="/var/log/splunk/caimp_webhook.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# Maps search name keywords → canonical metric name
_METRIC_MAP = {
    "CPU":     "system.cpu.utilization",
    "Memory":  "system.memory.utilization",
    "Disk":    "system.disk.utilization",
    "Network": "system.network.io.bytes_recv",
}

# Maps result field names → numeric value (first match wins)
_VALUE_FIELDS = ["cpu_pct", "mem_pct", "disk_pct", "net_bytes", "value"]


def _infer_metric(search_name: str, row: dict) -> str:
    for keyword, metric in _METRIC_MAP.items():
        if keyword in search_name:
            return metric
    return row.get("metric_name", "unknown")


def _extract_value(row: dict) -> float:
    for field in _VALUE_FIELDS:
        if row.get(field) not in (None, ""):
            try:
                return float(row[field])
            except (ValueError, TypeError):
                pass
    return 0.0


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:
        log.error(f"Failed to parse stdin: {exc}")
        return 1

    config  = payload.get("configuration", {})
    row     = payload.get("result", {})

    endpoint    = config.get("endpoint", "http://ai-orchestrator:8010/webhook/anomaly")
    search_name = config.get("search_name", "")

    metric_name  = _infer_metric(search_name, row)
    value        = _extract_value(row)
    anomaly_type = row.get("anomaly_type", "unknown")
    severity     = row.get("severity", "medium")
    host         = row.get("host", "")
    org_id       = row.get("org_id", "")
    timestamp    = row.get("_time", "")
    score        = float(row.get("score", 0) or 0)

    if not host or not org_id:
        log.warning(f"Missing host or org_id in result row — skipping. row={row}")
        return 0

    anomaly = {
        "anomaly_id":         str(uuid4()),
        "timestamp":          timestamp,
        "host":               host,
        "org_id":             org_id,
        "metric_name":        metric_name,
        "anomaly_type":       anomaly_type,
        "severity":           severity,
        "value":              value,
        "score":              score,
        "splunk_search_name": search_name,
    }

    data = json.dumps(anomaly).encode("utf-8")
    req  = urllib.request.Request(
        endpoint,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            body   = resp.read(200).decode("utf-8", errors="replace")
            log.info(
                f"Webhook OK {status} | host={host} type={anomaly_type} "
                f"severity={severity} value={value:.1f} | response={body}"
            )
            return 0
    except urllib.error.HTTPError as exc:
        log.error(f"Webhook HTTP error {exc.code}: {exc.read(200).decode('utf-8', errors='replace')}")
        return 1
    except urllib.error.URLError as exc:
        log.error(f"Webhook connection error: {exc.reason} — is ai-orchestrator running?")
        return 1
    except Exception as exc:
        log.error(f"Webhook unexpected error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
