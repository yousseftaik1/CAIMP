"""
Holt-Winters double exponential smoothing (linear trend model).
Pure NumPy — no external ML dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class ForecastResult:
    points: list[dict]              # [{hour, predicted, lower, upper}]
    trend_slope: float              # units/hour; positive = rising
    time_to_critical: float | None  # hours until first threshold breach; None = never
    confidence: str                 # low | medium | high


_ALPHA = 0.3   # level smoothing
_BETA  = 0.1   # trend smoothing


def _holt_linear(
    values: np.ndarray,
    horizon: int,
    alpha: float = _ALPHA,
    beta: float  = _BETA,
) -> tuple[np.ndarray, float, np.ndarray]:
    """Double exponential smoothing. Returns (forecasts, final_trend, fitted)."""
    n = len(values)
    level = float(values[0])
    trend = float((values[-1] - values[0]) / max(n - 1, 1))

    fitted = np.empty(n)
    for t in range(n):
        fitted[t] = level + trend
        if t < n - 1:
            prev_level = level
            level = alpha * float(values[t]) + (1.0 - alpha) * (level + trend)
            trend = beta * (level - prev_level) + (1.0 - beta) * trend

    forecasts = np.array([level + (h + 1) * trend for h in range(horizon)])
    return forecasts, trend, fitted


def forecast_metric(
    values: list[float],
    horizon_hours: int,
    critical_threshold: float,
) -> ForecastResult:
    if not values:
        return ForecastResult(points=[], trend_slope=0.0, time_to_critical=None, confidence="low")

    arr = np.clip(np.array(values, dtype=float), 0.0, None)
    n   = len(arr)

    if n < 2:
        last = float(arr[-1])
        pts  = [
            {"hour": h + 1, "predicted": round(last, 4), "lower": round(last, 4), "upper": round(last, 4)}
            for h in range(horizon_hours)
        ]
        return ForecastResult(pts, trend_slope=0.0, time_to_critical=None, confidence="low")

    forecasts, final_trend, fitted = _holt_linear(arr, horizon_hours)

    # ±1.28σ confidence interval (≈80% coverage)
    residuals = arr - fitted
    sigma     = float(np.std(residuals))
    ci_half   = 1.28 * sigma

    points = [
        {
            "hour":      h + 1,
            "predicted": round(float(np.clip(forecasts[h], 0.0, None)), 4),
            "lower":     round(float(np.clip(forecasts[h] - ci_half, 0.0, None)), 4),
            "upper":     round(float(np.clip(forecasts[h] + ci_half, 0.0, None)), 4),
        }
        for h in range(horizon_hours)
    ]

    time_to_critical: float | None = None
    for h in range(horizon_hours):
        if forecasts[h] >= critical_threshold:
            time_to_critical = float(h + 1)
            break

    confidence = "high" if n >= 48 else ("medium" if n >= 24 else "low")

    return ForecastResult(
        points=points,
        trend_slope=round(float(final_trend), 6),
        time_to_critical=time_to_critical,
        confidence=confidence,
    )
