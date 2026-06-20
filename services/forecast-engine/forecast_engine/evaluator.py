"""
Accuracy evaluator — compares past forecasts against actual metric values
and writes accuracy_score back into server_forecasts.

This is the learning feedback loop: each time we evaluate a forecast we build
a historical record that the worker uses to inform LLM confidence on future
predictions for the same server/metric.
"""

from __future__ import annotations

import json
import logging

import asyncpg

log = logging.getLogger(__name__)


async def evaluate_past_forecasts(pool: asyncpg.Pool) -> int:
    """Score all forecasts whose horizon has elapsed but haven't been evaluated yet.
    Returns the count of forecasts scored in this run.
    """
    rows = await pool.fetch(
        """
        SELECT id, org_id, server_id, metric_name,
               forecasted_at, horizon_hours, forecast_points
        FROM server_forecasts
        WHERE evaluated_at IS NULL
          AND forecasted_at + (horizon_hours || ' hours')::interval < now()
        ORDER BY forecasted_at ASC
        LIMIT 50
        """
    )

    evaluated = 0
    for row in rows:
        try:
            await _evaluate_one(pool, row)
            evaluated += 1
        except Exception as exc:
            log.warning("Failed to evaluate forecast %s: %s", row["id"], exc)

    if evaluated:
        log.info("Evaluated %d past forecast(s)", evaluated)
    return evaluated


async def _evaluate_one(pool: asyncpg.Pool, row) -> None:
    forecast_start = row["forecasted_at"]
    horizon = row["horizon_hours"]

    actuals = await pool.fetch(
        """
        SELECT time_bucket('1 hour', time) AS hour, avg(value) AS avg_val
        FROM metrics
        WHERE org_id      = $1::uuid
          AND server_id   = $2::uuid
          AND metric_name = $3
          AND time >= $4
          AND time  < $4 + ($5 || ' hours')::interval
        GROUP BY 1
        ORDER BY 1 ASC
        """,
        row["org_id"],
        row["server_id"],
        row["metric_name"],
        forecast_start,
        str(horizon),
    )

    if not actuals:
        # No actual data for this window — mark evaluated but leave scores NULL
        await pool.execute(
            "UPDATE server_forecasts SET evaluated_at = now() WHERE id = $1",
            row["id"],
        )
        return

    raw = row["forecast_points"]
    points: list[dict] = raw if isinstance(raw, list) else json.loads(raw)

    predicted_map = {p["hour"] - 1: float(p["predicted"]) for p in points}

    errors = []
    for i, actual_row in enumerate(actuals):
        if i in predicted_map:
            errors.append(abs(predicted_map[i] - float(actual_row["avg_val"])))

    if not errors:
        await pool.execute(
            "UPDATE server_forecasts SET evaluated_at = now() WHERE id = $1",
            row["id"],
        )
        return

    mae = sum(errors) / len(errors)
    # Metrics are 0–1 fractions; normalise against 0.5 (50 percentage points) as max error
    accuracy_score = max(0.0, min(1.0, 1.0 - mae / 0.5))

    await pool.execute(
        """
        UPDATE server_forecasts
        SET evaluated_at   = now(),
            actual_mae     = $1,
            accuracy_score = $2
        WHERE id = $3
        """,
        mae,
        accuracy_score,
        row["id"],
    )

    log.info(
        "Forecast %s evaluated: metric=%s MAE=%.4f accuracy=%.1f%%",
        row["id"],
        row["metric_name"],
        mae,
        accuracy_score * 100,
    )
