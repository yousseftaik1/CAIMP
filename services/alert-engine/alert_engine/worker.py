from __future__ import annotations

import asyncio
import json
import logging

import nats.errors
import redis.asyncio as aioredis
from prometheus_client import Counter

from nats_client.client import NatsClient
from nats_client.models import AnomalyEvent, Streams

from .config import settings
from .db import get_pool
from .notifier import fire_notification
from .rule_evaluator import RuleEvaluator

log = logging.getLogger(__name__)

_metric_signals = Counter(
    "alert_engine_metric_signals_total", "Metric batch signals processed"
)
_anomaly_persisted = Counter(
    "alert_engine_anomalies_persisted_total", "Anomaly events persisted"
)
_alerts_fired = Counter(
    "alert_engine_alerts_fired_total", "Alert rule firings", ["rule_type"]
)
_anomaly_suppressed = Counter(
    "alert_engine_anomalies_suppressed_total", "Anomalies suppressed by dedup"
)

_FETCH_BATCH = 20


async def _handle_metric_signal(msg_data: bytes, evaluator: RuleEvaluator) -> None:
    """Process a metric.received signal — evaluate threshold rules."""
    try:
        payload = json.loads(msg_data)
    except json.JSONDecodeError:
        return

    org_id = payload.get("org_id")
    server_id = payload.get("server_id")
    if not org_id or not server_id:
        return

    fired = await evaluator.evaluate_batch(org_id, server_id)
    pool = get_pool()

    for item in fired:
        rule = item["rule"]
        severity = "warning" if item["value"] < item["threshold"] * 1.1 else "critical"
        message = (
            f"Rule '{rule['name']}' fired: {item['metric_name']}={item['value']:.4f} "
            f"(threshold {rule['condition_json'].get('operator', '>')} {item['threshold']})"
        )
        await fire_notification(
            pool=pool,
            org_id=org_id,
            server_id=server_id,
            alert_rule_id=rule["id"],
            severity=severity,
            message=message,
            channels=rule["notification_channels"],
        )
        _alerts_fired.labels(rule_type=rule["rule_type"]).inc()
        log.info(
            "Alert fired | rule=%s org=%s server=%s", rule["name"], org_id, server_id
        )

    _metric_signals.inc()


_DEDUP_TTL_SECONDS = 15 * 60  # 15 minutes
_BURST_WINDOW_SECONDS = 60  # collapse burst if 3+ different metrics in 60s
_BURST_THRESHOLD = 3


async def _is_duplicate(redis: aioredis.Redis, event: AnomalyEvent) -> bool:
    """
    Return True if an identical anomaly (same server + metric + detector) fired
    within the last 15 minutes. Also track burst detection for multi-symptom collapse.
    """
    dedup_key = (
        f"dedup:{event.org_id}:{event.server_id}:{event.metric_name}:{event.detector}"
    )
    # NX = only set if not exists; returns None if key already exists (duplicate)
    result = await redis.set(dedup_key, "1", ex=_DEDUP_TTL_SECONDS, nx=True)
    if result is None:
        _anomaly_suppressed.inc()
        log.debug(
            "Anomaly suppressed (dedup): server=%s metric=%s",
            event.server_id,
            event.metric_name,
        )
        return True

    # Burst tracking: count distinct metrics firing on this server in the burst window
    burst_key = f"burst:{event.org_id}:{event.server_id}"
    await redis.sadd(burst_key, event.metric_name)
    await redis.expire(burst_key, _BURST_WINDOW_SECONDS)
    burst_count = await redis.scard(burst_key)

    if burst_count >= _BURST_THRESHOLD:
        log.info(
            "Anomaly burst detected on server=%s — %d metrics firing within %ds",
            event.server_id,
            burst_count,
            _BURST_WINDOW_SECONDS,
        )

    return False


async def _handle_anomaly(msg_data: bytes, redis: aioredis.Redis | None = None) -> None:
    """Persist an anomaly event to the anomaly_events table, with deduplication."""
    try:
        event = AnomalyEvent.model_validate_json(msg_data)
    except Exception as exc:
        log.warning("Invalid anomaly payload: %s", exc)
        return

    # Dedup: skip if same anomaly fired recently
    if redis and await _is_duplicate(redis, event):
        return

    pool = get_pool()
    await pool.execute(
        """INSERT INTO anomaly_events
               (org_id, server_id, metric_name, value, threshold, detector, severity)
           VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7)
           ON CONFLICT DO NOTHING""",
        event.org_id,
        event.server_id,
        event.metric_name,
        event.value,
        event.threshold,
        event.detector,
        event.severity,
    )
    _anomaly_persisted.inc()
    log.debug("Anomaly persisted: incident=%s", event.incident_id)


async def _run_consumer(
    nc: NatsClient,
    stream: str,
    consumer_name: str,
    subject_filter: str,
    handler,
) -> None:
    psub = await nc.subscribe(
        stream=stream,
        consumer_name=consumer_name,
        subject_filter=subject_filter,
    )
    log.info("Consumer '%s' on %s ready", consumer_name, subject_filter)

    while True:
        try:
            msgs = await psub.fetch(_FETCH_BATCH, timeout=5)
        except nats.errors.TimeoutError:
            continue
        except Exception as exc:
            log.error("Fetch error on %s: %s", consumer_name, exc)
            await asyncio.sleep(1)
            continue

        for msg in msgs:
            try:
                await handler(msg.data)
                await msg.ack()
            except Exception as exc:
                log.error("Handler error on %s: %s", consumer_name, exc, exc_info=True)
                await msg.nak()


async def run(nc: NatsClient) -> None:
    pool = get_pool()
    redis = aioredis.from_url(
        settings.redis_url,
        password=settings.redis_password or None,
        decode_responses=True,
    )
    evaluator = RuleEvaluator(pool, redis)

    log.info("Alert Engine started")

    await asyncio.gather(
        _run_consumer(
            nc,
            Streams.METRICS,
            "alert-engine-metrics",
            "metric.received.>",
            lambda data: _handle_metric_signal(data, evaluator),
        ),
        _run_consumer(
            nc,
            Streams.ANOMALIES,
            "alert-engine-anomalies",
            "anomaly.detected.>",
            lambda data: _handle_anomaly(data, redis),
        ),
    )

    await redis.aclose()
