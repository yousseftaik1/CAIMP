"""
CAIMP Correlation Engine — port 9095

Subscribes to NATS anomaly.detected.> events.
For each anomaly, queries change_events in the T-30min window before it,
scores each change by temporal proximity and type weight, calls Ollama for a
plain-English narrative, saves root_cause_analyses, and publishes
rootcause.ready.{org_id} to NATS so the WS Gateway pushes it to the browser.

This is the "What changed before this broke?" engine — the core of the pivot.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import sys
from datetime import datetime, timedelta, timezone

import asyncpg
import httpx
import nats
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("correlation-engine")

DATABASE_URL  = os.getenv("DATABASE_URL", "")
NATS_URL      = os.getenv("NATS_URL", "nats://nats:4222")
NATS_USER     = os.getenv("NATS_USER", "caimp")
NATS_PASSWORD = os.getenv("NATS_PASSWORD", "")
OLLAMA_URL    = os.getenv("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL  = os.getenv("OLLAMA_LLM_MODEL", "llama3.1:8b-instruct-q4_K_M")
METRICS_PORT  = int(os.getenv("METRICS_PORT", "9095"))
PORT          = int(os.getenv("PORT", "9095"))

# How many minutes before anomaly to search for changes
LOOKBACK_MINUTES = int(os.getenv("LOOKBACK_MINUTES", "30"))

# Change type weights (higher = more likely to cause anomalies)
_TYPE_WEIGHT = {
    "deployment":  1.0,
    "config":      0.9,
    "package":     0.8,
    "docker_pull": 0.75,
    "restart":     0.7,
    "cron":        0.5,
    "ssh_login":   0.3,
}

app = FastAPI(title="CAIMP Correlation Engine", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_pool: asyncpg.Pool | None = None
_nc = None
_js = None
_http: httpx.AsyncClient | None = None


# ── Lifecycle ─────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    global _pool, _nc, _js, _http
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=8)
    log.info("PostgreSQL pool ready")
    _http = httpx.AsyncClient(timeout=120)
    creds = {}
    if NATS_USER and NATS_PASSWORD:
        creds = {"user": NATS_USER, "password": NATS_PASSWORD}
    try:
        _nc = await nats.connect(NATS_URL, **creds, connect_timeout=10)
        _js = _nc.jetstream()
        log.info("NATS connected")
        asyncio.create_task(_consume_anomalies())
    except Exception as exc:
        log.warning("NATS unavailable (%s) — correlation loop will not start", exc)


@app.on_event("shutdown")
async def shutdown():
    if _pool:  await _pool.close()
    if _http:  await _http.aclose()
    if _nc and not _nc.is_closed:  await _nc.drain()


@app.get("/health")
def health():
    return {"status": "ok", "service": "correlation-engine"}


# ── Scoring ───────────────────────────────────────────────────────────────────

def _temporal_score(minutes_before: float) -> float:
    """Exponential decay: change 0 min before = 1.0; 30 min before ≈ 0.05."""
    return math.exp(-0.1 * max(0, minutes_before))


def _score_change(change: dict, anomaly_time: datetime) -> float:
    occurred_at = change["occurred_at"]
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    minutes_before = (anomaly_time - occurred_at).total_seconds() / 60
    if minutes_before < 0:
        return 0.0   # change happened after anomaly
    type_weight = _TYPE_WEIGHT.get(change["change_type"], 0.5)
    return _temporal_score(minutes_before) * type_weight


# ── LLM narrative ─────────────────────────────────────────────────────────────

async def _build_narrative(anomaly: dict, ranked_changes: list[dict]) -> tuple[str, list[dict]]:
    """Call Ollama to produce a plain-English root-cause narrative."""
    if not ranked_changes:
        narrative = (
            f"No changes were recorded in the 30 minutes before this incident. "
            f"The {anomaly.get('metric_name','metric')} spike on "
            f"{anomaly.get('server_name', anomaly.get('server_id','this server'))} "
            f"may be caused by a gradual load increase or an event not yet tracked "
            f"by CAIMP's change tracker."
        )
        actions = [{"priority": 1, "action": "Check running processes for unexpected CPU/memory spikes",
                    "reason": "No deployment or config change found to explain this"}]
        return narrative, actions

    changes_text = "\n".join(
        f"  {i+1}. [{c['change_type'].upper()}] {c['description'] or c['change_type']} "
        f"(~{int(c.get('minutes_before', 0))} min before the incident, score {c['score']:.2f})"
        for i, c in enumerate(ranked_changes[:3])
    )

    metric    = anomaly.get("metric_name", "a metric").replace("system.", "").replace(".", " ")
    value     = anomaly.get("value", 0)
    server    = anomaly.get("server_name", anomaly.get("server_id", "your server"))
    severity  = anomaly.get("severity", "warning")

    prompt = f"""You are helping a small startup developer (no DevOps background) understand what caused an infrastructure problem.

The server "{server}" reported a {severity} alert: {metric} spiked to {value:.1f}%.

In the {LOOKBACK_MINUTES} minutes before this happened, these changes were recorded:
{changes_text}

Based on these changes, explain in 2-3 plain sentences:
1. What most likely caused this problem
2. How confident you are and why
3. The single most important thing the developer should do right now

Avoid technical jargon. If you must use a technical term, explain it in plain language.
Keep your answer under 100 words.

Then provide 1-3 specific fix steps as a JSON array at the end, like:
ACTIONS:
[{{"priority": 1, "action": "specific action here", "reason": "why this helps"}}]"""

    try:
        resp = await _http.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
                  "format": None, "temperature": 0.3, "num_predict": 400},
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "")
        # Split narrative from actions
        if "ACTIONS:" in raw:
            parts    = raw.split("ACTIONS:", 1)
            narrative = parts[0].strip()
            try:
                actions = json.loads(parts[1].strip())
                if not isinstance(actions, list):
                    actions = []
            except Exception:
                actions = []
        else:
            narrative = raw.strip()
            actions   = []

        if not actions:
            top = ranked_changes[0]
            actions = [{
                "priority": 1,
                "action": f"Investigate the {top['change_type']} that happened "
                          f"~{int(top.get('minutes_before', 0))} minutes before the incident",
                "reason": top.get("description") or "Most temporally correlated change",
            }]
        return narrative, actions

    except Exception as exc:
        log.error("Ollama call failed: %s", exc)
        top = ranked_changes[0]
        narrative = (
            f"A {top['change_type']} occurred about {int(top.get('minutes_before', 0))} minutes "
            f"before the incident — this is the most likely cause. "
            f"Review {top.get('description') or 'the recent change'} and check whether it "
            f"introduced a performance regression."
        )
        actions = [{
            "priority": 1,
            "action": f"Review the {top['change_type']}: {top.get('description') or 'recent change'}",
            "reason": "Temporally closest change to the incident",
        }]
        return narrative, actions


# ── Core correlation ──────────────────────────────────────────────────────────

async def _correlate(anomaly: dict) -> None:
    org_id    = anomaly.get("org_id")
    server_id = anomaly.get("server_id")
    anomaly_id = anomaly.get("id")

    if not org_id:
        log.warning("Anomaly has no org_id, skipping")
        return

    anomaly_time_raw = anomaly.get("timestamp") or anomaly.get("time") or anomaly.get("detected_at")
    if anomaly_time_raw:
        if isinstance(anomaly_time_raw, str):
            anomaly_time = datetime.fromisoformat(anomaly_time_raw.replace("Z", "+00:00"))
        else:
            anomaly_time = anomaly_time_raw
    else:
        anomaly_time = datetime.now(tz=timezone.utc)

    window_start = anomaly_time - timedelta(minutes=LOOKBACK_MINUTES)
    window_end   = anomaly_time

    # Fetch candidate changes in window
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, change_type, source, actor, description, occurred_at, payload
            FROM   change_events
            WHERE  org_id = $1::uuid
              AND  occurred_at >= $2
              AND  occurred_at <= $3
              AND  ($4::uuid IS NULL OR server_id = $4::uuid)
            ORDER  BY occurred_at DESC
            LIMIT  20
            """,
            org_id, window_start, window_end, server_id,
        )

    if not rows:
        log.info("No change_events found for anomaly %s in %s min window", anomaly_id, LOOKBACK_MINUTES)

    # Score each candidate
    scored = []
    for r in rows:
        minutes_before = (anomaly_time - r["occurred_at"].replace(tzinfo=timezone.utc)).total_seconds() / 60
        score = _score_change(dict(r), anomaly_time)
        scored.append({
            "change_id":    str(r["id"]),
            "change_type":  r["change_type"],
            "description":  r["description"],
            "actor":        r["actor"],
            "occurred_at":  r["occurred_at"].isoformat(),
            "minutes_before": round(minutes_before, 1),
            "score":        round(score, 4),
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    top_changes = scored[:3]

    confidence = top_changes[0]["score"] if top_changes else 0.0
    likely_cause = (
        f"{top_changes[0]['change_type'].capitalize()}: {top_changes[0]['description'] or 'recent change'}"
        if top_changes else "No correlated changes found"
    )

    # Get LLM narrative
    narrative, actions = await _build_narrative(anomaly, top_changes)

    # Save root_cause_analysis
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO root_cause_analyses
              (org_id, anomaly_event_id, server_id, likely_cause, confidence,
               correlated_changes, narrative, recommended_actions, window_start, window_end)
            VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6, $7, $8, $9, $10)
            RETURNING id
            """,
            org_id,
            anomaly_id,
            server_id,
            likely_cause,
            float(confidence),
            json.dumps(top_changes),
            narrative,
            json.dumps(actions),
            window_start,
            window_end,
        )
    rca_id = str(row["id"])
    log.info("root_cause_analysis[%s] confidence=%.3f cause=%s", rca_id, confidence, likely_cause)

    # Publish to NATS
    if _js:
        try:
            msg = json.dumps({
                "id":          rca_id,
                "org_id":      org_id,
                "server_id":   server_id,
                "anomaly_id":  anomaly_id,
                "likely_cause": likely_cause,
                "confidence":  float(confidence),
                "narrative":   narrative,
                "actions":     actions,
            }).encode()
            await _js.publish(f"rootcause.ready.{org_id}", msg)
        except Exception as exc:
            log.warning("NATS publish failed: %s", exc)


# ── NATS consumer ─────────────────────────────────────────────────────────────

async def _consume_anomalies() -> None:
    log.info("Starting NATS anomaly consumer")
    try:
        sub = await _js.subscribe(
            "anomaly.detected.>",
            durable="correlation-engine",
            stream="ANOMALIES",
        )
    except Exception as exc:
        log.error("Failed to subscribe to ANOMALIES stream: %s", exc)
        return

    async for msg in sub.messages:
        try:
            anomaly = json.loads(msg.data.decode())
            await _correlate(anomaly)
            await msg.ack()
        except Exception as exc:
            log.error("Failed to process anomaly message: %s", exc)
            await msg.nak()


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, log_level="info")
