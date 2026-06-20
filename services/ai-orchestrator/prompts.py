"""
Prompt templates for the AI Orchestrator (Splunk anomaly pipeline).

Target audience: startup developers without DevOps background.
The LLM should explain incidents like a senior engineer talking to a first-time
server owner — honest, direct, jargon-free, and always ending with a concrete action.
"""

from __future__ import annotations

# ── Anomaly type metadata ─────────────────────────────────────────────────────

ANOMALY_TYPE_LABELS: dict[str, tuple[str, str, str]] = {
    "cpu_saturation": ("CPU spike", "system.cpu.utilization", "cpu_pct"),
    "memory_pressure": ("memory problem", "system.memory.utilization", "mem_pct"),
    "disk_fill": ("disk running full", "system.disk.utilization", "disk_pct"),
    "network_anomaly": (
        "unusual network activity",
        "system.network.io.bytes_recv",
        "net_bytes",
    ),
    "security_event": ("possible security issue", "various", "value"),
}

# ── Plain-language focus hints ────────────────────────────────────────────────

_FOCUS_HINTS: dict[str, str] = {
    "cpu_saturation": (
        "The most common causes for a non-DevOps team are: "
        "a background job that got stuck, a recent code deployment that has a performance bug, "
        "or too many users hitting the server at once. "
        "Avoid suggesting obscure Linux kernel tuning — stick to things a developer can actually fix."
    ),
    "memory_pressure": (
        "The most common causes for a small team are: "
        "a memory leak in a recent deployment, a process that didn't clean up after itself, "
        "or a database that is caching too much data. "
        "Explain memory in terms they understand — e.g. 'your app is holding onto data it should have released'."
    ),
    "disk_fill": (
        "The most common causes for a small team are: "
        "old log files that were never cleaned up, database backups piling up, "
        "or uploaded files that nobody deleted. "
        "Give them a specific command or folder to check — don't just say 'free up disk space'."
    ),
    "network_anomaly": (
        "This could be a traffic spike (lots of real users), a DDoS attack, or a misconfigured service "
        "sending data in a loop. Help them figure out which one it is based on the evidence provided."
    ),
    "security_event": (
        "Be careful not to cause panic. Explain what you see, what it might mean, "
        "and what the first investigative step is. Don't speculate about breaches without evidence."
    ),
}

_DEFAULT_FOCUS = (
    "Identify the most likely operational cause based on the evidence. "
    "Explain it like you're talking to a developer who manages their own server "
    "but has never used a monitoring tool before."
)

# ── Output schema ─────────────────────────────────────────────────────────────

OUTPUT_SCHEMA = """\
You are speaking to a startup developer who has no DevOps background. They have a small server, \
no monitoring team, and just want to know: what happened, why, and what to do.

Avoid jargon. If you must use a technical term, define it in one sentence.
Keep the total response under 200 words.

Respond ONLY with this JSON object — no preamble, no markdown fences, no extra keys:
{
  "severity": "critical|high|medium|low",
  "explanation": "2-3 plain sentences: what is happening right now on the server",
  "root_cause": "The most likely specific reason this happened — be concrete, not generic",
  "recommended_action": "The single most important thing they should do right now",
  "evidence_spl_queries": [
    "One SPL query they can run to verify the root cause",
    "One SPL query to confirm the fix worked"
  ],
  "confidence": "high|medium|low"
}"""


# ── Prompt assembly ───────────────────────────────────────────────────────────


def build_prompt(anomaly: dict, context: dict, rag: dict) -> str:
    atype = anomaly.get("anomaly_type", "unknown")
    label, _, _ = ANOMALY_TYPE_LABELS.get(
        atype, ("infrastructure problem", "unknown", "value")
    )
    focus = _FOCUS_HINTS.get(atype, _DEFAULT_FOCUS)
    value = anomaly.get("value", 0)
    score = anomaly.get("score", 0)
    host = anomaly.get("host", "your server")

    return f"""\
A small team's server just triggered a {label} alert. \
Your job is to explain what happened and what the developer should do — in plain English.

{focus}

=== WHAT TRIGGERED THIS ALERT ===
Server:     {host}
Metric:     {anomaly.get("metric_name", "unknown")} = {value:.1f}%
Severity:   {anomaly.get("severity", "unknown").upper()}
Detected:   {anomaly.get("timestamp", "unknown")}
MLTK score: {score:.4f}  (lower = more anomalous)
Type:       {atype}

=== WHAT THE METRIC HAS BEEN DOING (last 60 minutes) ===
{context.get("metric_trend_text", "  (data unavailable)")}

=== OTHER METRICS AT THE SAME TIME (CPU + memory + disk) ===
{context.get("correlated_metrics_text", "  (data unavailable)")}

=== ERROR MESSAGES FROM THE SERVER (last 1 hour) ===
{context.get("error_logs_text", "  (none found)")}

=== PREVIOUS PROBLEMS ON THIS SERVER (last 7 days) ===
{context.get("past_anomalies_text", "  (none recorded)")}

=== WHAT THE AI SAID LAST TIME SOMETHING SIMILAR HAPPENED ===
{context.get("ai_history_text", "  (no history)")}

=== SIMILAR INCIDENTS FROM THE TEAM'S KNOWLEDGE BASE ===
{rag.get("similar_incidents_text", "  (none)")}

=== FIX GUIDES (runbooks) ===
{rag.get("runbook_text", "  (none)")}

{OUTPUT_SCHEMA}"""


if __name__ == "__main__":
    _test = {
        "host": "web-01",
        "metric_name": "system.cpu.utilization",
        "value": 97.3,
        "score": 0.0012,
        "timestamp": "2026-05-20T10:00:00Z",
        "severity": "critical",
        "anomaly_type": "cpu_saturation",
        "org_id": "00000000-0000-0000-0000-000000000001",
    }
    _ctx = {
        "metric_trend_text": "  09:50 | 22%\n  09:55 | 45%\n  10:00 | 97%",
        "correlated_metrics_text": "  10:00 | cpu=97% | mem=62% | disk=45%",
        "error_logs_text": "  10:00 | ERROR | Process python3 consuming 94% CPU",
        "past_anomalies_text": "  2026-05-19 | cpu_saturation | warning",
        "ai_history_text": "(none)",
    }
    _rag = {"similar_incidents_text": "(none)", "runbook_text": "(none)"}
    print(build_prompt(_test, _ctx, _rag))
