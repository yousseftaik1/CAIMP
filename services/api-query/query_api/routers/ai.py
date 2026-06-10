from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..auth import get_current_user
from ..db import get_tenant_conn

router = APIRouter(prefix="/ai", tags=["ai"])


class ExplanationResponse(BaseModel):
    id: str
    server_id: str
    incident_id: str
    anomaly_type: str
    severity: str
    explanation: str
    root_cause: str | None
    recommended_action: str | None
    confidence: str
    model: str
    created_at: datetime


@router.get("/explanations", response_model=list[ExplanationResponse])
async def list_explanations(
    server_id: str | None = Query(default=None),
    incident_id: str | None = Query(default=None),
    limit: int = Query(default=20, le=200),
    user=Depends(get_current_user),
):
    filters = ["org_id = $1::uuid"]
    params: list = [user.org_id]

    if server_id:
        params.append(server_id)
        filters.append(f"server_id = ${len(params)}::uuid")
    if incident_id:
        params.append(incident_id)
        filters.append(f"incident_id = ${len(params)}")

    params.append(limit)
    where = " AND ".join(filters)
    q = (
        f"SELECT id, server_id, incident_id, anomaly_type, severity, explanation, "
        f"root_cause, recommended_action, confidence, model, created_at "
        f"FROM ai_explanations WHERE {where} "
        f"ORDER BY created_at DESC LIMIT ${len(params)}"
    )

    async with get_tenant_conn(user.org_id) as conn:
        rows = await conn.fetch(q, *params)

    return [
        ExplanationResponse(
            id=str(r["id"]),
            server_id=str(r["server_id"]),
            incident_id=r["incident_id"],
            anomaly_type=r["anomaly_type"],
            severity=r["severity"],
            explanation=r["explanation"],
            root_cause=r["root_cause"],
            recommended_action=r["recommended_action"],
            confidence=r["confidence"],
            model=r["model"],
            created_at=r["created_at"],
        )
        for r in rows
    ]
