from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..auth import get_current_user
from ..db import get_tenant_conn

router = APIRouter(prefix="/forecasts", tags=["forecasts"])


class ForecastPoint(BaseModel):
    hour: int
    predicted: float
    lower: float
    upper: float


class ForecastResponse(BaseModel):
    id: str
    server_id: str
    metric_name: str
    forecasted_at: datetime
    horizon_hours: int
    trend_slope: float | None
    time_to_critical: float | None
    critical_threshold: float
    ml_model: str
    llm_narrative: str | None
    llm_confidence: str | None
    accuracy_score: float | None
    points: list[ForecastPoint]


@router.get("", response_model=list[ForecastResponse])
async def list_forecasts(
    server_id: str | None = Query(default=None),
    metric_name: str | None = Query(default=None),
    limit: int = Query(default=20, le=100),
    user=Depends(get_current_user),
):
    """Latest forecast per (server_id, metric_name) for the caller's org."""
    filters = ["org_id = $1::uuid"]
    params: list = [user.org_id]

    if server_id:
        params.append(server_id)
        filters.append(f"server_id = ${len(params)}::uuid")
    if metric_name:
        params.append(metric_name)
        filters.append(f"metric_name = ${len(params)}")

    params.append(limit)
    where = " AND ".join(filters)

    q = (
        f"SELECT DISTINCT ON (server_id, metric_name) "
        f"id, server_id, metric_name, forecasted_at, horizon_hours, "
        f"trend_slope, time_to_critical, critical_threshold, ml_model, "
        f"llm_narrative, llm_confidence, accuracy_score, forecast_points "
        f"FROM server_forecasts WHERE {where} "
        f"ORDER BY server_id, metric_name, forecasted_at DESC "
        f"LIMIT ${len(params)}"
    )

    async with get_tenant_conn(user.org_id) as conn:
        rows = await conn.fetch(q, *params)

    results = []
    for r in rows:
        raw = r["forecast_points"] or []
        if isinstance(raw, str):
            raw = json.loads(raw)
        points = [ForecastPoint(**p) for p in raw]

        results.append(
            ForecastResponse(
                id=str(r["id"]),
                server_id=str(r["server_id"]),
                metric_name=r["metric_name"],
                forecasted_at=r["forecasted_at"],
                horizon_hours=r["horizon_hours"],
                trend_slope=r["trend_slope"],
                time_to_critical=r["time_to_critical"],
                critical_threshold=r["critical_threshold"],
                ml_model=r["ml_model"],
                llm_narrative=r["llm_narrative"],
                llm_confidence=r["llm_confidence"],
                accuracy_score=r["accuracy_score"],
                points=points,
            )
        )
    return results
