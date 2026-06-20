from __future__ import annotations

import asyncio
import json
import logging

import redis.asyncio as aioredis

from nats_client.client import NatsClient
from nats_client.models import ForecastCritical, Subjects

from .config import settings
from .evaluator import evaluate_past_forecasts
from .forecaster import forecast_metric
from .ollama_client import generate_narrative

log = logging.getLogger(__name__)

_CRITICAL_WINDOW_HOURS = 6.0
_FORECAST_METRICS = ["cpu_percent", "memory_percent", "disk_percent"]
_HISTORY_HOURS = 72


async def _forecast_one(
    pool,
    redis: aioredis.Redis,
    nc: NatsClient,
    org_id: str,
    server_id: str,
    metric_name: str,
) -> None:
    history_rows = await pool.fetch(
        """
        SELECT time_bucket('1 hour', time) AS hour, avg(value) AS avg_val
        FROM metrics
        WHERE org_id      = $1::uuid
          AND server_id   = $2::uuid
          AND metric_name = $3
          AND time > now() - ($4 || ' hours')::interval
        GROUP BY 1
        ORDER BY 1 ASC
        """,
        org_id,
        server_id,
        metric_name,
        str(_HISTORY_HOURS),
    )

    values = [float(r["avg_val"]) for r in history_rows]
    if len(values) < settings.min_data_points:
        log.debug(
            "Skipping %s/%s — %d hourly points (need %d)",
            server_id,
            metric_name,
            len(values),
            settings.min_data_points,
        )
        return

    result = forecast_metric(
        values, settings.forecast_horizon_hours, settings.critical_threshold
    )
    if not result.points:
        return

    # Query past accuracy for this server/metric (the learning feedback input)
    past_accuracy: float | None = await pool.fetchval(
        """
        SELECT avg(accuracy_score)
        FROM server_forecasts
        WHERE server_id   = $1::uuid
          AND metric_name = $2
          AND accuracy_score IS NOT NULL
          AND forecasted_at > now() - INTERVAL '7 days'
        """,
        server_id,
        metric_name,
    )

    narrative, llm_confidence = await generate_narrative(
        metric_name=metric_name,
        server_id=server_id,
        values=values,
        result=result,
        critical_threshold=settings.critical_threshold,
        past_accuracy=past_accuracy,
    )

    row = await pool.fetchrow(
        """
        INSERT INTO server_forecasts (
            org_id, server_id, metric_name, horizon_hours,
            forecast_points, time_to_critical, critical_threshold,
            trend_slope, ml_model, llm_narrative, llm_confidence
        ) VALUES ($1::uuid, $2::uuid, $3, $4, $5::jsonb, $6, $7, $8, $9, $10, $11)
        RETURNING id
        """,
        org_id,
        server_id,
        metric_name,
        settings.forecast_horizon_hours,
        json.dumps(result.points),
        result.time_to_critical,
        settings.critical_threshold,
        result.trend_slope,
        "holt_linear",
        narrative,
        llm_confidence,
    )
    forecast_id = str(row["id"])

    if (
        result.time_to_critical is not None
        and result.time_to_critical <= _CRITICAL_WINDOW_HOURS
    ):
        event = ForecastCritical(
            forecast_id=forecast_id,
            org_id=org_id,
            server_id=server_id,
            metric_name=metric_name,
            time_to_critical=result.time_to_critical,
            current_trend_slope=result.trend_slope,
            critical_threshold=settings.critical_threshold,
            llm_narrative=narrative,
            llm_confidence=llm_confidence,
        )
        subject = Subjects.forecast_critical(org_id, server_id)
        try:
            await nc.publish(subject, event)
            await pool.execute(
                "UPDATE server_forecasts SET nats_published = true WHERE id = $1",
                row["id"],
            )
        except Exception as exc:
            log.warning("Failed to publish forecast event for %s: %s", server_id, exc)

        log.warning(
            "CRITICAL FORECAST server=%s metric=%s ttc=%.1fh trend=%+.4f",
            server_id,
            metric_name,
            result.time_to_critical,
            result.trend_slope,
        )
    else:
        log.info(
            "Forecast saved server=%s metric=%s trend=%+.4f ttc=%s accuracy_ctx=%s",
            server_id,
            metric_name,
            result.trend_slope,
            f"{result.time_to_critical:.1f}h" if result.time_to_critical else "none",
            f"{past_accuracy * 100:.0f}%"
            if past_accuracy is not None
            else "no-history",
        )


async def _run_all_forecasts(pool, redis: aioredis.Redis, nc: NatsClient) -> None:
    active = await pool.fetch(
        """
        SELECT DISTINCT org_id, server_id, metric_name
        FROM metrics
        WHERE time > now() - INTERVAL '6 hours'
          AND metric_name = ANY($1::text[])
        """,
        _FORECAST_METRICS,
    )

    log.info("Running forecasts for %d server-metric pair(s)", len(active))

    for row in active:
        org_id = str(row["org_id"])
        server_id = str(row["server_id"])
        metric = row["metric_name"]

        dedup_key = f"forecast:interval:{server_id}:{metric}"
        if await redis.exists(dedup_key):
            continue

        try:
            await _forecast_one(pool, redis, nc, org_id, server_id, metric)
        except Exception as exc:
            log.error(
                "Forecast error server=%s metric=%s: %s",
                server_id,
                metric,
                exc,
                exc_info=True,
            )

        ttl = max(60, (settings.forecast_interval_minutes - 2) * 60)
        await redis.setex(dedup_key, ttl, "1")


async def run(pool, nc: NatsClient) -> None:
    redis = aioredis.from_url(
        settings.redis_url,
        password=settings.redis_password or None,
        decode_responses=True,
    )

    async def forecast_loop() -> None:
        while True:
            try:
                await _run_all_forecasts(pool, redis, nc)
            except Exception as exc:
                log.error("Forecast loop error: %s", exc, exc_info=True)
            await asyncio.sleep(settings.forecast_interval_minutes * 60)

    async def evaluate_loop() -> None:
        # Offset by one interval + 60s so evaluator doesn't compete with the first forecast run
        await asyncio.sleep(settings.forecast_interval_minutes * 60 + 60)
        while True:
            try:
                await evaluate_past_forecasts(pool)
            except Exception as exc:
                log.error("Evaluate loop error: %s", exc, exc_info=True)
            await asyncio.sleep(settings.forecast_interval_minutes * 60 * 2)

    log.info(
        "Forecast engine started  interval=%dm  horizon=%dh  threshold=%.0f%%",
        settings.forecast_interval_minutes,
        settings.forecast_horizon_hours,
        settings.critical_threshold * 100,
    )

    try:
        await asyncio.gather(forecast_loop(), evaluate_loop())
    finally:
        await redis.aclose()
