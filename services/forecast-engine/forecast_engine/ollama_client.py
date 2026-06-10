from __future__ import annotations

import json
import logging

import httpx

from .config import settings
from .forecaster import ForecastResult

log = logging.getLogger(__name__)

_GENERATE_TIMEOUT = 120.0


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _pt(points: list[dict], hour: int) -> str:
    if len(points) >= hour:
        return _pct(points[hour - 1]["predicted"])
    return "N/A"


async def generate_narrative(
    metric_name: str,
    server_id: str,
    values: list[float],
    result: ForecastResult,
    critical_threshold: float = 0.9,
    past_accuracy: float | None = None,
) -> tuple[str, str]:
    """Return (narrative, llm_confidence). Falls back to a rule-based summary on error."""
    current = values[-1] if values else 0.0

    if result.trend_slope > 0.005:
        direction = "rising"
    elif result.trend_slope < -0.005:
        direction = "falling"
    else:
        direction = "stable"

    critical_clause = ""
    if result.time_to_critical is not None:
        ttc = int(result.time_to_critical)
        critical_clause = (
            f" CRITICAL: expected to breach {_pct(critical_threshold)} in ~{ttc} hour(s)."
        )

    accuracy_clause = ""
    if past_accuracy is not None:
        accuracy_clause = (
            f" Historical 7-day forecast accuracy for this metric: {past_accuracy * 100:.0f}%."
        )

    prompt = (
        "You are a predictive monitoring AI. Summarise the following metric forecast.\n\n"
        f"Metric: {metric_name}\n"
        f"Server: {server_id}\n"
        f"Current value: {_pct(current)}\n"
        f"Trend: {direction} ({result.trend_slope:+.4f} units/hour)\n"
        f"Forecast: +6h={_pt(result.points, 6)}  +12h={_pt(result.points, 12)}  +24h={_pt(result.points, 24)}"
        f"{critical_clause}{accuracy_clause}\n\n"
        "Respond ONLY with this JSON and nothing else:\n"
        '{"narrative": "<2-3 sentence forecast summary for ops>", '
        '"confidence": "low|medium|high", '
        '"recommendation": "<one-line action or \'Continue monitoring\'>"}'
    )

    try:
        async with httpx.AsyncClient(
            base_url=settings.ollama_base_url, timeout=_GENERATE_TIMEOUT
        ) as client:
            resp = await client.post(
                "/api/generate",
                json={
                    "model": settings.llm_model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.1, "num_predict": 256},
                },
            )
            resp.raise_for_status()
            raw = resp.json()["response"]

        parsed     = json.loads(raw)
        narrative  = (parsed.get("narrative") or "").strip()[:1000]
        confidence = parsed.get("confidence", result.confidence)
        if confidence not in ("low", "medium", "high"):
            confidence = result.confidence
        if not narrative:
            raise ValueError("empty narrative from LLM")
        return narrative, confidence

    except Exception as exc:
        log.warning("LLM narrative failed for %s/%s: %s", server_id, metric_name, exc)
        return _fallback(metric_name, current, direction, result, critical_threshold), result.confidence


def _fallback(
    metric_name: str,
    current: float,
    direction: str,
    result: ForecastResult,
    critical_threshold: float,
) -> str:
    msg = f"{metric_name} is {_pct(current)} and trending {direction}."
    if result.time_to_critical is not None:
        msg += f" Expected to breach {_pct(critical_threshold)} in ~{int(result.time_to_critical)} hour(s)."
    elif direction == "stable":
        msg += " No threshold breach expected within the 24-hour horizon."
    return msg


async def is_ready() -> bool:
    try:
        async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=5.0) as client:
            resp = await client.get("/")
            return resp.status_code == 200
    except Exception:
        return False
