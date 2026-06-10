from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..auth import get_current_user
from ..cache import get_cached, set_cached
from ..db import get_tenant_conn

router = APIRouter(prefix="/metrics", tags=["metrics"])

_VALID_INTERVALS = {"1m", "5m", "15m", "1h", "6h", "1d"}
_INTERVAL_SQL = {
    "1m": "1 minute", "5m": "5 minutes", "15m": "15 minutes",
    "1h": "1 hour", "6h": "6 hours", "1d": "1 day",
}


class MetricPoint(BaseModel):
    time: datetime
    metric_name: str
    value: float
    avg: float | None = None
    max: float | None = None
    min: float | None = None


class LatestMetric(BaseModel):
    server_id: str
    metric_name: str
    value: float
    time: datetime


@router.get("", response_model=list[MetricPoint])
async def query_metrics(
    server_id: str,
    metric_name: str,
    from_time: datetime | None = Query(default=None),
    to_time: datetime | None = Query(default=None),
    interval: str = Query(default="5m"),
    agg: Literal["avg", "max", "min", "none"] = Query(default="avg"),
    user=Depends(get_current_user),
):
    if interval not in _VALID_INTERVALS:
        interval = "5m"

    now = datetime.now(tz=timezone.utc)
    t_to = to_time or now
    t_from = from_time or (now - timedelta(hours=1))

    cached = await get_cached(
        "metrics", server_id=server_id, metric_name=metric_name,
        from_time=t_from, to_time=t_to, interval=interval, agg=agg,
    )
    if cached:
        return cached

    if agg == "none":
        q = (
            "SELECT time, metric_name, value FROM metrics "
            "WHERE org_id = $1::uuid AND server_id = $2::uuid AND metric_name = $3 "
            "AND time >= $4 AND time <= $5 "
            "ORDER BY time DESC LIMIT 5000"
        )
        async with get_tenant_conn(user.org_id) as conn:
            rows = await conn.fetch(q, user.org_id, server_id, metric_name, t_from, t_to)
        result = [{"time": r["time"], "metric_name": r["metric_name"], "value": r["value"]} for r in rows]
    else:
        bucket_expr = f"time_bucket('{_INTERVAL_SQL[interval]}', time)"
        q = (
            f"SELECT {bucket_expr} AS time, metric_name, "
            "avg(value) AS avg, max(value) AS max, min(value) AS min "
            "FROM metrics "
            "WHERE org_id = $1::uuid AND server_id = $2::uuid AND metric_name = $3 "
            "AND time >= $4 AND time <= $5 "
            f"GROUP BY {bucket_expr}, metric_name "
            "ORDER BY time DESC"
        )
        async with get_tenant_conn(user.org_id) as conn:
            rows = await conn.fetch(q, user.org_id, server_id, metric_name, t_from, t_to)
        result = [
            {"time": r["time"], "metric_name": r["metric_name"],
             "value": r[agg], "avg": r["avg"], "max": r["max"], "min": r["min"]}
            for r in rows
        ]

    ttl = 30 if (now - t_to).total_seconds() < 300 else 300
    await set_cached(result, "metrics", ttl_seconds=ttl,
                     server_id=server_id, metric_name=metric_name,
                     from_time=t_from, to_time=t_to, interval=interval, agg=agg)
    return result


@router.get("/latest", response_model=list[LatestMetric])
async def latest_metrics(
    server_id: str | None = Query(default=None),
    user=Depends(get_current_user),
):
    """Latest value per metric per server for the org (or a specific server)."""
    cached = await get_cached("latest", org_id=user.org_id, server_id=server_id)
    if cached:
        return cached

    if server_id:
        q = (
            "SELECT DISTINCT ON (metric_name) server_id, metric_name, value, time "
            "FROM metrics WHERE org_id = $1::uuid AND server_id = $2::uuid "
            "ORDER BY metric_name, time DESC"
        )
        async with get_tenant_conn(user.org_id) as conn:
            rows = await conn.fetch(q, user.org_id, server_id)
    else:
        q = (
            "SELECT DISTINCT ON (server_id, metric_name) server_id, metric_name, value, time "
            "FROM metrics WHERE org_id = $1::uuid "
            "ORDER BY server_id, metric_name, time DESC"
        )
        async with get_tenant_conn(user.org_id) as conn:
            rows = await conn.fetch(q, user.org_id)

    result = [
        {"server_id": str(r["server_id"]), "metric_name": r["metric_name"],
         "value": r["value"], "time": r["time"]}
        for r in rows
    ]
    await set_cached(result, "latest", ttl_seconds=15, org_id=user.org_id, server_id=server_id)
    return result
