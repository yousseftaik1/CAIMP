"""
Context Builder — fires 5 SPL queries in parallel to Splunk before calling
the LLM. All queries run concurrently with asyncio.gather(); total time is
max(individual query times), typically 2–5 seconds.

Query selection uses the tier auto-select logic so dashboards and context
queries always hit the fastest available index for the requested time range.
"""
from __future__ import annotations

import asyncio
import logging

from splunk_client import SplunkClient

log = logging.getLogger(__name__)


# ── index / span auto-selection ───────────────────────────────────────────────

def select_index_and_span(hours: float) -> tuple[str, str]:
    """
    Choose the right summary index and bucket span for a given time range.
    Raw index is used for short ranges; rollup indexes for longer ranges.
    """
    if hours <= 1:
        return "caimp_metrics", "1m"
    elif hours <= 12:
        return "caimp_metrics", "5m"
    elif hours <= 72:
        return "caimp_metrics_5m", "5m"
    elif hours <= 720:
        return "caimp_metrics_1h", "1h"
    else:
        return "caimp_metrics_1d", "1d"


def _val_field(index: str) -> str:
    """avg(_value) for raw index, avg(avg_val) for summary indexes."""
    return "_value" if index == "caimp_metrics" else "avg_val"


# ── context queries ───────────────────────────────────────────────────────────

def _build_queries(anomaly: dict) -> dict[str, tuple[str, str, str]]:
    """
    Returns {name: (spl, earliest, latest)} for each context query.
    Parameterised on the anomaly dict so values are safely interpolated.
    """
    host    = anomaly["host"]
    metric  = anomaly["metric_name"]
    org_id  = anomaly["org_id"]

    # Short-trend: raw index, 1-minute buckets, last 1 hour
    short_index, short_span = select_index_and_span(1)
    vf = _val_field(short_index)

    # Medium-trend: 5-minute summary, last 24 hours
    med_index, med_span = select_index_and_span(24)
    vf_med = _val_field(med_index)

    return {
        "metric_trend": (
            f"| mstats avg({vf}) as val "
            f"  WHERE index={short_index} "
            f"  metric_name={metric} host={host} org_id={org_id} "
            f"  span={short_span} "
            f"| eval _time=strftime(_time, \"%H:%M\") "
            f"| table _time, val",
            "-1h", "now",
        ),
        "correlated_metrics": (
            f"| mstats avg({vf}) as val "
            f"  WHERE index={short_index} "
            f"  (metric_name=system.cpu.utilization OR "
            f"   metric_name=system.memory.utilization OR "
            f"   metric_name=system.disk.utilization) "
            f"  host={host} span={short_span} "
            f"| timechart span={short_span} avg(val) by metric_name "
            f"| head 30",
            "-30m", "now",
        ),
        "error_logs": (
            f'search index=caimp_logs host={host} '
            f'(log_level=ERROR OR log_level=CRITICAL OR "ERROR" OR "Exception") '
            f'| table _time, log_level, message '
            f'| head 30',
            "-1h", "now",
        ),
        "past_anomalies": (
            f"search index=caimp_anomalies host={host} "
            f"| table _time, anomaly_type, severity, metric_name "
            f"| head 10",
            "-7d", "now",
        ),
        "ai_history": (
            f"search index=caimp_ai host={host} "
            f"| table _time, anomaly_type, root_cause, confidence "
            f"| head 5",
            "-30d", "now",
        ),
    }


# ── result formatting ─────────────────────────────────────────────────────────

def _rows_to_text(rows: list[dict], max_rows: int = 20) -> str:
    """Format a list of Splunk result dicts as a plain-text table for the LLM."""
    if not rows:
        return "  (no data)"
    headers = list(rows[0].keys())
    lines   = ["  " + " | ".join(headers)]
    for row in rows[:max_rows]:
        lines.append("  " + " | ".join(str(row.get(h, "")) for h in headers))
    return "\n".join(lines)


# ── main entry point ──────────────────────────────────────────────────────────

async def build_context(anomaly: dict, splunk: SplunkClient | None) -> dict:
    """
    Fire all 5 context queries concurrently.
    Returns a dict with *_text keys ready to be interpolated into the prompt.
    If splunk is None (not configured), returns empty strings for all sections.
    """
    empty = {
        "metric_trend_text":       "  (Splunk not configured)",
        "correlated_metrics_text": "  (Splunk not configured)",
        "error_logs_text":         "  (Splunk not configured)",
        "past_anomalies_text":     "  (Splunk not configured)",
        "ai_history_text":         "  (Splunk not configured)",
        "context_queries":         [],
    }
    if splunk is None:
        return empty

    queries = _build_queries(anomaly)

    async def safe_query(name: str, spl: str,
                         earliest: str, latest: str) -> tuple[str, list[dict]]:
        try:
            rows = await splunk.run_search_oneshot(
                spl, earliest=earliest, latest=latest
            )
            return name, rows
        except Exception as exc:
            log.warning(f"Context query '{name}' failed: {exc}")
            return name, []

    results = await asyncio.gather(
        *[safe_query(name, spl, earliest, latest)
          for name, (spl, earliest, latest) in queries.items()]
    )
    result_map = dict(results)

    return {
        "metric_trend_text":       _rows_to_text(result_map["metric_trend"]),
        "correlated_metrics_text": _rows_to_text(result_map["correlated_metrics"]),
        "error_logs_text":         _rows_to_text(result_map["error_logs"]),
        "past_anomalies_text":     _rows_to_text(result_map["past_anomalies"]),
        "ai_history_text":         _rows_to_text(result_map["ai_history"]),
        "context_queries":         list(queries.keys()),
    }
