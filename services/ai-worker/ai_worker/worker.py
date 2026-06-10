from __future__ import annotations

import asyncio
import json
import logging

import nats.errors
import redis.asyncio as aioredis
from prometheus_client import Counter, Histogram

from nats_client.client import NatsClient
from nats_client.models import AnomalyEvent, ExplanationReady, Streams, Subjects

from .config import settings
from .db import get_pool
from .ollama_client import generate
from .prompt_builder import build_prompt
from .rag import retrieve_similar, store_incident

log = logging.getLogger(__name__)

_processed = Counter("ai_worker_events_total", "Events processed", ["status"])
_duration = Histogram("ai_worker_llm_seconds", "LLM call duration in seconds")

_DEDUP_TTL = 3600  # skip re-processing the same incident for 1 hour
_FETCH_BATCH = 10


def _fallback_explanation(event) -> tuple[str, str, str]:
    """Generate a readable templated explanation when the LLM is unavailable."""
    ml_map = {
        "system.cpu.utilization":        "CPU",
        "system.memory.utilization":     "memory (RAM)",
        "system.filesystem.utilization": "disk space",
    }
    ml      = ml_map.get(event.metric_name, event.metric_name.split(".")[-1])
    val_pct = f"{event.value * 100:.0f}%" if event.value <= 1.0 else f"{event.value:.0f}%"

    if event.severity == "critical":
        explanation = (
            f"Your server's {ml} usage has reached {val_pct} — this is critically high "
            f"and may cause slowdowns or crashes if not addressed immediately."
        )
        root_cause = (
            f"A sudden spike or sustained high {ml} usage was detected at {val_pct}. "
            f"Likely caused by a runaway process, a traffic surge, or a memory/disk leak."
        )
        recommended_action = (
            f"Immediately check which process is consuming the most {ml} (use top/htop or "
            f"your cloud provider's metrics). Kill or restart the offending process if safe to do so."
        )
    else:
        explanation = (
            f"Your server's {ml} usage is at {val_pct}, which is above the normal threshold. "
            f"It is not critical yet, but worth investigating before it gets worse."
        )
        root_cause = (
            f"Elevated {ml} usage at {val_pct}. This may be temporary (batch job, cron task) "
            f"or indicate a slow-growing leak or increasing demand."
        )
        recommended_action = (
            f"Monitor {ml} usage over the next 15 minutes. If it keeps rising, "
            f"identify the top consumers and consider scaling or restarting the affected service."
        )
    return explanation, root_cause, recommended_action


async def _process_one(
    event: AnomalyEvent,
    pool,
    redis: aioredis.Redis,
    nc: NatsClient,
) -> None:
    dedup_key = f"ai:processed:{event.incident_id}"
    if await redis.exists(dedup_key):
        log.debug("Duplicate incident %s — skipping", event.incident_id)
        _processed.labels(status="skipped").inc()
        return

    # Metric history for context
    history_rows = await pool.fetch(
        "SELECT time, value FROM metrics "
        "WHERE org_id = $1::uuid AND server_id = $2::uuid AND metric_name = $3 "
        "AND time > now() - INTERVAL '30 minutes' "
        "ORDER BY time DESC LIMIT 60",
        event.org_id, event.server_id, event.metric_name,
    )
    history = [{"time": str(r["time"]), "value": r["value"]} for r in history_rows]

    # RAG context
    query_text = (
        f"{event.metric_name} anomaly {event.detector} severity:{event.severity} "
        f"value:{event.value:.4f}"
    )
    rag_docs = await retrieve_similar(pool, event.org_id, query_text)

    # LLM call
    prompt = build_prompt(event.model_dump(mode="json"), history, rag_docs)
    explanation = root_cause = recommended_action = None
    confidence = "low"

    with _duration.time():
        try:
            raw = await generate(prompt)
            parsed = json.loads(raw)
            explanation = parsed.get("explanation", "")[:2000]
            root_cause = (parsed.get("root_cause") or "")[:1000] or None
            recommended_action = (parsed.get("recommended_action") or "")[:1000] or None
            raw_conf = parsed.get("confidence", "low")
            confidence = raw_conf if raw_conf in ("low", "medium", "high") else "low"
        except Exception as exc:
            log.warning("LLM failed for incident %s: %s", event.incident_id, exc)
            explanation, root_cause, recommended_action = _fallback_explanation(event)

    # Persist explanation
    await pool.execute(
        """INSERT INTO ai_explanations
               (org_id, server_id, incident_id, anomaly_type, severity,
                explanation, root_cause, recommended_action, confidence, model)
           VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10)""",
        event.org_id, event.server_id, event.incident_id,
        event.metric_name, event.severity,
        explanation, root_cause, recommended_action, confidence,
        settings.llm_model,
    )

    # Index in RAG
    rag_content = (
        f"Metric: {event.metric_name}, Value: {event.value:.4f}, "
        f"Severity: {event.severity}. Root cause: {root_cause or 'unknown'}. "
        f"{explanation or ''}"
    )
    await store_incident(pool, event.org_id, event.incident_id, rag_content)

    # Publish result
    ready = ExplanationReady(
        incident_id=event.incident_id,
        org_id=event.org_id,
        server_id=event.server_id,
        severity=event.severity,
        explanation=explanation or "",
        root_cause=root_cause,
        recommended_action=recommended_action,
        confidence=confidence,
        model=settings.llm_model,
    )
    subject = Subjects.explanation_ready(event.org_id, event.incident_id)
    await nc.publish(subject, ready)

    await redis.setex(dedup_key, _DEDUP_TTL, "1")
    _processed.labels(status="ok").inc()
    log.info(
        "Explained incident=%s server=%s confidence=%s",
        event.incident_id, event.server_id, confidence,
    )


async def run(nc: NatsClient) -> None:
    pool = get_pool()
    redis = aioredis.from_url(
        settings.redis_url,
        password=settings.redis_password or None,
        decode_responses=True,
    )

    psub = await nc.subscribe(
        stream=Streams.ANOMALIES,
        consumer_name="ai-worker",
        subject_filter="anomaly.detected.>",
    )

    sem = asyncio.Semaphore(settings.worker_concurrency)
    log.info("AI worker started (concurrency=%d)", settings.worker_concurrency)

    async def handle(msg):
        async with sem:
            try:
                event = AnomalyEvent.model_validate_json(msg.data)
                await _process_one(event, pool, redis, nc)
                await msg.ack()
            except Exception as exc:
                log.error("Error processing message: %s", exc, exc_info=True)
                _processed.labels(status="error").inc()
                await msg.nak()

    while True:
        try:
            msgs = await psub.fetch(_FETCH_BATCH, timeout=5)
        except nats.errors.TimeoutError:
            continue
        except Exception as exc:
            log.error("Fetch error: %s", exc)
            await asyncio.sleep(1)
            continue

        await asyncio.gather(*[handle(m) for m in msgs])

    await redis.aclose()
