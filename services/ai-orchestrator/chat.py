"""
Conversational chat — intent classification, context gathering, and
token-by-token SSE streaming from Ollama.

Intents (evaluated in order):
  host_query    — message names a server → recent anomalies + last AI explanation
  anomaly_query — message contains a UUID or anomaly keywords → stored explanation
  runbook_query — "how do I fix / troubleshoot" → RAG runbook lookup
  general       — everything else → plain LLM answer
"""

from __future__ import annotations

import logging
import re
from typing import AsyncGenerator

import asyncpg
import httpx

log = logging.getLogger(__name__)

_HOST_PATTERN = re.compile(
    r"\b([\w-]+-\d+|[\w-]+\.(local|prod|dev|stg|internal))\b", re.I
)
_UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
)
_ANOMALY_KEYWORDS = re.compile(
    r"\b(incident|anomaly|alert|explanation|explain|what happened)\b", re.I
)
_RUNBOOK_KEYWORDS = re.compile(
    r"\b(how|fix|resolve|troubleshoot|diagnose|steps|runbook|remediat)\b", re.I
)


def classify_intent(message: str, host_hint: str | None) -> tuple[str, dict]:
    entities: dict = {}

    # Host query
    host_match = _HOST_PATTERN.search(message)
    if host_match or host_hint:
        entities["host"] = host_match.group(1) if host_match else host_hint
        return "host_query", entities

    # Anomaly / incident query
    uuid_match = _UUID_PATTERN.search(message)
    if uuid_match:
        entities["incident_id"] = uuid_match.group(0)
        return "anomaly_query", entities
    if _ANOMALY_KEYWORDS.search(message):
        return "anomaly_query", entities

    # Runbook query
    if _RUNBOOK_KEYWORDS.search(message):
        return "runbook_query", entities

    return "general", entities


async def gather_chat_context(
    intent: str,
    entities: dict,
    org_id: str,
    db: asyncpg.Pool | None,
    splunk=None,  # kept for signature compatibility, ignored
) -> str:
    if not db or not org_id:
        return ""

    try:
        async with db.acquire() as conn:
            await conn.execute("SET ROLE caimp_service")
            await conn.execute(f"SET app.current_org_id = '{org_id}'")

            if intent == "host_query":
                host = entities.get("host", "")
                rows = await conn.fetch(
                    """
                    SELECT ae.time, ae.metric_name, ae.severity, ae.value,
                           ax.explanation, ax.recommended_action
                    FROM   anomaly_events ae
                    LEFT   JOIN ai_explanations ax
                               ON ax.incident_id = ae.incident_id AND ax.org_id = ae.org_id
                    JOIN   servers s ON s.id = ae.server_id
                    WHERE  ae.org_id = $1::uuid
                      AND  (s.hostname ILIKE $2 OR s.name ILIKE $2)
                    ORDER  BY ae.time DESC LIMIT 5
                """,
                    org_id,
                    f"%{host}%",
                )
                if not rows:
                    return f"No recent anomalies found for server matching '{host}'."
                lines = [f"Recent anomalies on {host}:"]
                for r in rows:
                    lines.append(
                        f"  [{r['time'].strftime('%H:%M')}] {r['metric_name']} "
                        f"— {r['severity']} ({r['value']:.1%})"
                    )
                    if r["explanation"]:
                        lines.append(f"    AI: {r['explanation'][:200]}")
                return "\n".join(lines)

            elif intent == "anomaly_query":
                incident_id = entities.get("incident_id")
                if incident_id:
                    row = await conn.fetchrow(
                        """
                        SELECT ae.metric_name, ae.severity, ae.value, ae.time,
                               ax.explanation, ax.root_cause, ax.recommended_action
                        FROM   anomaly_events ae
                        LEFT   JOIN ai_explanations ax
                                   ON ax.incident_id = ae.incident_id AND ax.org_id = ae.org_id
                        WHERE  ae.org_id = $1::uuid AND ae.id = $2::uuid
                    """,
                        org_id,
                        incident_id,
                    )
                    if row and row["explanation"]:
                        return (
                            f"Anomaly {incident_id[:8]}…: {row['metric_name']} "
                            f"at {row['value']:.1%} ({row['severity']})\n"
                            f"Explanation: {row['explanation']}\n"
                            f"Root cause: {row['root_cause'] or 'unknown'}\n"
                            f"Action: {row['recommended_action'] or 'none'}"
                        )
                # Fall back to recent anomalies
                rows = await conn.fetch(
                    """
                    SELECT ae.time, ae.metric_name, ae.severity, s.name AS server
                    FROM   anomaly_events ae
                    JOIN   servers s ON s.id = ae.server_id
                    WHERE  ae.org_id = $1::uuid
                    ORDER  BY ae.time DESC LIMIT 5
                """,
                    org_id,
                )
                if not rows:
                    return "No anomalies found in the last 24 hours."
                return "Recent anomalies:\n" + "\n".join(
                    f"  {r['server']}: {r['metric_name']} — {r['severity']} at {r['time'].strftime('%H:%M')}"
                    for r in rows
                )

            elif intent == "runbook_query":
                rows = await conn.fetch(
                    """
                    SELECT title, anomaly_type, content
                    FROM   runbooks
                    WHERE  org_id = $1::uuid
                    ORDER  BY updated_at DESC LIMIT 3
                """,
                    org_id,
                )
                if not rows:
                    return "No runbooks found. Create some in the Runbooks section."
                return "Relevant runbooks:\n" + "\n\n".join(
                    f"[{r['anomaly_type']}] {r['title']}:\n{r['content'][:400]}"
                    for r in rows
                )
    except Exception as exc:
        log.warning("Context gathering failed: %s", exc)

    return ""


def build_chat_prompt(
    message: str,
    history: list[dict],
    context: str,
    intent: str,
) -> str:
    system = (
        "You are CAIMP's AI assistant for server monitoring. Be concise and direct."
    )
    if context:
        system += f"\nContext:\n{context[:600]}"

    hist = ""
    for turn in history[-2:]:
        role = turn.get("role", "user")
        hist += f"\n{role.capitalize()}: {turn.get('content', '')[:200]}"

    return f"{system}\n{hist}\nUser: {message}\nAssistant:"


async def stream_ollama(
    prompt: str,
    http: httpx.AsyncClient,
    ollama_url: str,
    model: str,
) -> AsyncGenerator[str, None]:
    try:
        async with http.stream(
            "POST",
            f"{ollama_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": True,
                "options": {"num_ctx": 512, "num_predict": 200, "temperature": 0.3},
            },
            timeout=None,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                import json as _json

                try:
                    data = _json.loads(line)
                    if token := data.get("response"):
                        yield token
                    if data.get("done"):
                        break
                except Exception:
                    continue
    except Exception as exc:
        log.error("Ollama streaming error: %s", exc)
        yield f"\n[Error contacting LLM: {exc}]"
