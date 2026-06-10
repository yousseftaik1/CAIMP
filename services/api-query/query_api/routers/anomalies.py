from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..auth import get_current_user
from ..db import get_tenant_conn

router = APIRouter(prefix="/anomalies", tags=["anomalies"])


class AnomalyResponse(BaseModel):
    id: str
    time: datetime
    server_id: str
    metric_name: str
    value: float
    threshold: float | None
    detector: str
    severity: str


@router.get("", response_model=list[AnomalyResponse])
async def list_anomalies(
    server_id: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    detector: str | None = Query(default=None),
    from_time: datetime | None = Query(default=None),
    to_time: datetime | None = Query(default=None),
    limit: int = Query(default=100, le=1000),
    user=Depends(get_current_user),
):
    now = datetime.now(tz=timezone.utc)
    t_to = to_time or now
    t_from = from_time or (now - timedelta(hours=24))

    filters = ["org_id = $1::uuid", "time >= $2", "time <= $3"]
    params: list = [user.org_id, t_from, t_to]

    if server_id:
        params.append(server_id)
        filters.append(f"server_id = ${len(params)}::uuid")
    if severity:
        params.append(severity)
        filters.append(f"severity = ${len(params)}")
    if detector:
        params.append(detector)
        filters.append(f"detector = ${len(params)}")

    params.append(limit)
    where = " AND ".join(filters)
    q = (
        f"SELECT id, time, server_id, metric_name, value, threshold, detector, severity "
        f"FROM anomaly_events WHERE {where} "
        f"ORDER BY time DESC LIMIT ${len(params)}"
    )

    async with get_tenant_conn(user.org_id) as conn:
        rows = await conn.fetch(q, *params)

    return [
        AnomalyResponse(
            id=str(r["id"]),
            time=r["time"],
            server_id=str(r["server_id"]),
            metric_name=r["metric_name"],
            value=r["value"],
            threshold=r["threshold"],
            detector=r["detector"],
            severity=r["severity"],
        )
        for r in rows
    ]
