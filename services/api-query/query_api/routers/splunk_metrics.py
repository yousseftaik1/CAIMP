"""
Splunk metrics router — `GET /metrics/splunk`

Queries Splunk mstats instead of TimescaleDB, auto-selecting the right
summary index based on the requested time range. Returns the same
MetricPoint shape as the TimescaleDB metrics router so the frontend
can use either backend transparently.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..auth import get_current_user
from ..cache import get_cached, set_cached

router = APIRouter(prefix="/metrics/splunk", tags=["splunk-metrics"])

# Injected by main.py on startup (None when Splunk is not configured)
splunk_client = None


class MetricPoint(BaseModel):
    time: datetime
    metric_name: str
    value: float


class LiveMetricPoint(BaseModel):
    metric: str
    value: float | None
    age_seconds: int


@router.get("", response_model=list[MetricPoint])
async def query_splunk_metrics(
    host: str,
    metric_name: str,
    from_time: datetime | None = Query(default=None),
    to_time: datetime | None = Query(default=None),
    user=Depends(get_current_user),
):
    """
    Query Splunk mstats for a host+metric combination.

    The index and bucket span are chosen automatically from the requested
    time range using the same tier logic as the AI Orchestrator context
    builder:
      ≤ 1 h   → caimp_metrics        1-min buckets
      ≤ 12 h  → caimp_metrics        5-min buckets
      ≤ 72 h  → caimp_metrics_5m     5-min buckets
      ≤ 30 d  → caimp_metrics_1h     1-hour buckets
      > 30 d  → caimp_metrics_1d     1-day buckets
    """
    if splunk_client is None:
        raise HTTPException(
            status_code=503,
            detail="Splunk is not configured on this server",
        )

    now = datetime.now(tz=timezone.utc)
    t_to = to_time or now
    t_from = from_time or (now - timedelta(hours=1))

    cache_key_args = dict(
        host=host,
        metric_name=metric_name,
        from_time=t_from,
        to_time=t_to,
    )
    cached = await get_cached("splunk_metrics", **cache_key_args)
    if cached:
        return cached

    hours = (t_to - t_from).total_seconds() / 3600
    from ..splunk import select_index_and_span

    index, span = select_index_and_span(hours)

    # Splunk earliest/latest as relative or ISO strings
    earliest = t_from.strftime("%Y-%m-%dT%H:%M:%S")
    latest = t_to.strftime("%Y-%m-%dT%H:%M:%S")

    rows = await splunk_client.query_metrics(
        metric_name=metric_name,
        host=host,
        org_id=user.org_id,
        index=index,
        span=span,
        earliest=earliest,
        latest=latest,
    )

    result = [
        {"time": r["time"], "metric_name": metric_name, "value": r["value"]}
        for r in rows
    ]

    # Cache recent data for 30 s, historical for 5 min
    ttl = 30 if (now - t_to).total_seconds() < 300 else 300
    await set_cached(result, "splunk_metrics", ttl_seconds=ttl, **cache_key_args)
    return result


@router.get("/live", response_model=LiveMetricPoint)
async def live_metric(
    server_id: str,
    metric_name: str,
    user=Depends(get_current_user),
):
    """
    Return the most-recent metric value written to Redis by the HEC bridge.

    The HEC bridge sets TTL=90 s on every key after a successful HEC POST.
    age_seconds is inferred from the remaining TTL (age = 90 - ttl_remaining).
    Returns null value with age_seconds=999 when no data arrived in the last 90 s.
    """
    from ..cache import _redis

    key = f"live:{user.org_id}:{server_id}:{metric_name}"

    async with _redis.pipeline(transaction=False) as pipe:
        pipe.get(key)
        pipe.ttl(key)
        raw_val, ttl = await pipe.execute()

    if raw_val is None:
        return {"metric": metric_name, "value": None, "age_seconds": 999}

    try:
        value = float(raw_val)
    except (ValueError, TypeError):
        return {"metric": metric_name, "value": None, "age_seconds": 999}

    # ttl == -2: key vanished between GET and TTL; -1: persisted key (no expiry)
    age = max(0, 90 - ttl) if ttl >= 0 else 999
    return {"metric": metric_name, "value": value, "age_seconds": age}


@router.get("/status")
async def splunk_status(user=Depends(get_current_user)):
    """Return whether the Splunk backend is reachable."""
    return {"configured": splunk_client is not None}
