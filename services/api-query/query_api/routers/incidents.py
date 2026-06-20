"""
Native anomaly incident + runbook endpoints.

Incidents show anomaly_events joined with ai_explanations — no Splunk required.

Routes:
  GET  /incidents                — paginated list with filters
  GET  /incidents/stats          — severity counts + pending AI analysis
  GET  /incidents/{id}           — full anomaly detail + AI explanation
  POST /incidents/{id}/feedback  — operator thumbs-up/down on the AI output
  DELETE /runbooks/{id}          — delete runbook

Runbooks:
  GET  /runbooks
  GET  /runbooks/{id}
  POST /runbooks
  PUT  /runbooks/{id}
  DELETE /runbooks/{id}
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..auth import get_current_user
from ..cache import get_cached, set_cached
from ..config import settings
from ..db import get_tenant_conn

log = logging.getLogger(__name__)
router = APIRouter(tags=["incidents"])


# ── Response models ───────────────────────────────────────────────────────────


class AIExplanation(BaseModel):
    id: str
    explanation: str | None
    root_cause: str | None
    recommended_action: str | None
    confidence: str | None
    model: str | None
    created_at: str | None


class IncidentSummary(BaseModel):
    id: str
    server_id: str
    server_name: str
    metric_name: str
    value: float
    threshold: float | None
    detector: str
    severity: str
    time: str
    ai_status: str  # 'complete' | 'pending' | 'none'
    ai_severity: str | None


class IncidentDetail(BaseModel):
    id: str
    server_id: str
    server_name: str
    metric_name: str
    value: float
    threshold: float | None
    detector: str
    severity: str
    time: str
    explanation: AIExplanation | None


class IncidentStats(BaseModel):
    total: int
    critical: int
    warning: int
    with_ai_explanation: int
    pending_ai: int


class FeedbackRequest(BaseModel):
    rating: int  # -1 | 0 | 1
    comment: str = ""


# ── Runbook models ────────────────────────────────────────────────────────────


class RunbookSummary(BaseModel):
    id: str
    title: str
    anomaly_type: str
    created_at: str
    updated_at: str
    has_embedding: bool


class RunbookDetail(BaseModel):
    id: str
    title: str
    anomaly_type: str
    content: str
    created_by: str | None
    created_at: str
    updated_at: str
    has_embedding: bool


class RunbookCreate(BaseModel):
    title: str
    anomaly_type: str
    content: str


class RunbookUpdate(BaseModel):
    title: str | None = None
    anomaly_type: str | None = None
    content: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

_METRIC_LABELS = {
    "cpu_percent": "CPU",
    "memory_percent": "Memory",
    "disk_percent": "Disk",
    "system.cpu.utilization": "CPU",
    "system.memory.utilization": "Memory",
    "system.filesystem.utilization": "Disk",
}


def _label(name: str) -> str:
    return _METRIC_LABELS.get(name, name)


# ── Incident endpoints ────────────────────────────────────────────────────────


@router.get("/incidents", response_model=list[IncidentSummary])
async def list_incidents(
    server_id: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    from_time: datetime | None = Query(default=None),
    to_time: datetime | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    user=Depends(get_current_user),
):
    now = datetime.now(tz=timezone.utc)
    t_to = to_time or now
    t_from = from_time or (now - timedelta(hours=24))

    async with get_tenant_conn(user.org_id) as conn:
        params: list = [user.org_id, t_from, t_to, limit]
        where = "ae.org_id = $1::uuid AND ae.time >= $2 AND ae.time <= $3"
        if server_id:
            params.insert(-1, server_id)
            where += f" AND ae.server_id = ${len(params) - 1}::uuid"
        if severity:
            params.insert(-1, severity)
            where += f" AND ae.severity = ${len(params) - 1}"

        rows = await conn.fetch(
            f"""
            SELECT
                ae.id::text,
                ae.server_id::text,
                s.name        AS server_name,
                ae.metric_name,
                ae.value,
                ae.threshold,
                ae.detector,
                ae.severity,
                ae.time,
                ax.id::text   AS ai_id,
                ax.severity   AS ai_severity,
                ax.explanation
            FROM   anomaly_events ae
            LEFT   JOIN servers s
                   ON s.id = ae.server_id
            LEFT   JOIN ai_explanations ax
                   ON ax.incident_id = ae.incident_id
                  AND ax.org_id = ae.org_id
            WHERE  {where}
            ORDER  BY ae.time DESC
            LIMIT  ${len(params)}
        """,
            *params,
        )

    result = []
    for r in rows:
        ai_status = "none"
        if r["ai_id"]:
            ai_status = "complete" if r["explanation"] else "pending"
        result.append(
            IncidentSummary(
                id=r["id"],
                server_id=r["server_id"],
                server_name=r["server_name"] or r["server_id"],
                metric_name=_label(r["metric_name"]),
                value=round(float(r["value"]) * 100, 1)
                if float(r["value"]) <= 1.0
                else round(float(r["value"]), 1),
                threshold=float(r["threshold"]) if r["threshold"] is not None else None,
                detector=r["detector"],
                severity=r["severity"],
                time=r["time"].isoformat(),
                ai_status=ai_status,
                ai_severity=r["ai_severity"],
            )
        )
    return result


@router.get("/incidents/stats", response_model=IncidentStats)
async def incident_stats(user=Depends(get_current_user)):
    cache_key = f"incident_stats:{user.org_id}"
    cached = await get_cached(cache_key)
    if cached:
        return IncidentStats(**json.loads(cached))

    since = datetime.now(tz=timezone.utc) - timedelta(hours=24)
    async with get_tenant_conn(user.org_id) as conn:
        row = await conn.fetchrow(
            """
            SELECT
                count(*)                                       AS total,
                count(*) FILTER (WHERE ae.severity = 'critical') AS critical,
                count(*) FILTER (WHERE ae.severity = 'warning')  AS warning,
                count(*) FILTER (WHERE ax.id IS NOT NULL
                    AND ax.explanation IS NOT NULL)            AS with_ai,
                count(*) FILTER (WHERE ax.id IS NOT NULL
                    AND ax.explanation IS NULL)                AS pending_ai
            FROM anomaly_events ae
            LEFT JOIN ai_explanations ax
                   ON ax.incident_id = ae.id::text
                  AND ax.org_id = ae.org_id
            WHERE ae.org_id = $1::uuid AND ae.time >= $2
        """,
            user.org_id,
            since,
        )

    stats = IncidentStats(
        total=row["total"] or 0,
        critical=row["critical"] or 0,
        warning=row["warning"] or 0,
        with_ai_explanation=row["with_ai"] or 0,
        pending_ai=row["pending_ai"] or 0,
    )
    await set_cached(cache_key, stats.model_dump_json(), ttl=30)
    return stats


@router.get("/incidents/{incident_id}", response_model=IncidentDetail)
async def get_incident(incident_id: str, user=Depends(get_current_user)):
    async with get_tenant_conn(user.org_id) as conn:
        row = await conn.fetchrow(
            """
            SELECT
                ae.id::text,
                ae.server_id::text,
                s.name          AS server_name,
                ae.metric_name,
                ae.value,
                ae.threshold,
                ae.detector,
                ae.severity,
                ae.time,
                ax.id::text     AS ai_id,
                ax.explanation,
                ax.root_cause,
                ax.recommended_action,
                ax.confidence,
                ax.model,
                ax.created_at   AS ai_created_at
            FROM   anomaly_events ae
            LEFT   JOIN servers s   ON s.id = ae.server_id
            LEFT   JOIN ai_explanations ax
                   ON ax.incident_id = ae.id::text AND ax.org_id = ae.org_id
            WHERE  ae.org_id = $1::uuid AND ae.id = $2::uuid
        """,
            user.org_id,
            incident_id,
        )

    if not row:
        raise HTTPException(status_code=404, detail="Incident not found")

    ai = None
    if row["ai_id"]:
        ai = AIExplanation(
            id=row["ai_id"],
            explanation=row["explanation"],
            root_cause=row["root_cause"],
            recommended_action=row["recommended_action"],
            confidence=row["confidence"],
            model=row["model"],
            created_at=row["ai_created_at"].isoformat()
            if row["ai_created_at"]
            else None,
        )

    v = float(row["value"])
    return IncidentDetail(
        id=row["id"],
        server_id=row["server_id"],
        server_name=row["server_name"] or row["server_id"],
        metric_name=_label(row["metric_name"]),
        value=round(v * 100, 1) if v <= 1.0 else round(v, 1),
        threshold=float(row["threshold"]) if row["threshold"] is not None else None,
        detector=row["detector"],
        severity=row["severity"],
        time=row["time"].isoformat(),
        explanation=ai,
    )


@router.post("/incidents/{incident_id}/feedback", status_code=204)
async def submit_feedback(
    incident_id: str,
    body: FeedbackRequest,
    user=Depends(get_current_user),
):
    async with get_tenant_conn(user.org_id) as conn:
        ai = await conn.fetchrow(
            "SELECT id FROM ai_explanations WHERE incident_id=$1 AND org_id=$2::uuid",
            incident_id,
            user.org_id,
        )
        if not ai:
            raise HTTPException(
                status_code=404, detail="No AI explanation for this incident"
            )
        await conn.execute(
            """INSERT INTO ai_feedback (explanation_id, org_id, rating, comment)
               VALUES ($1::uuid, $2::uuid, $3, $4)
               ON CONFLICT DO NOTHING""",
            ai["id"],
            user.org_id,
            body.rating,
            body.comment,
        )


# ── Runbook endpoints ─────────────────────────────────────────────────────────


@router.get("/runbooks", response_model=list[RunbookSummary])
async def list_runbooks(
    anomaly_type: str | None = Query(default=None),
    user=Depends(get_current_user),
):
    async with get_tenant_conn(user.org_id) as conn:
        q = "SELECT id, title, anomaly_type, created_at, updated_at, (embedding IS NOT NULL) AS has_embedding FROM runbooks WHERE org_id=$1::uuid"
        params: list = [user.org_id]
        if anomaly_type:
            q += " AND anomaly_type=$2"
            params.append(anomaly_type)
        q += " ORDER BY updated_at DESC"
        rows = await conn.fetch(q, *params)
    return [
        RunbookSummary(
            id=str(r["id"]),
            title=r["title"],
            anomaly_type=r["anomaly_type"],
            created_at=r["created_at"].isoformat(),
            updated_at=r["updated_at"].isoformat(),
            has_embedding=r["has_embedding"],
        )
        for r in rows
    ]


@router.get("/runbooks/{runbook_id}", response_model=RunbookDetail)
async def get_runbook(runbook_id: str, user=Depends(get_current_user)):
    async with get_tenant_conn(user.org_id) as conn:
        r = await conn.fetchrow(
            "SELECT id, title, anomaly_type, content, created_by, created_at, updated_at, (embedding IS NOT NULL) AS has_embedding FROM runbooks WHERE org_id=$1::uuid AND id=$2::uuid",
            user.org_id,
            runbook_id,
        )
    if not r:
        raise HTTPException(status_code=404, detail="Runbook not found")
    return RunbookDetail(
        id=str(r["id"]),
        title=r["title"],
        anomaly_type=r["anomaly_type"],
        content=r["content"],
        created_by=str(r["created_by"]) if r["created_by"] else None,
        created_at=r["created_at"].isoformat(),
        updated_at=r["updated_at"].isoformat(),
        has_embedding=r["has_embedding"],
    )


async def _embed(text: str) -> list[float] | None:
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.post(
                f"{settings.ollama_url}/api/embeddings",
                json={"model": settings.ollama_embed_model, "prompt": text},
            )
            resp.raise_for_status()
            return resp.json().get("embedding")
    except Exception as exc:
        log.warning("Embedding failed: %s", exc)
        return None


@router.post("/runbooks", response_model=RunbookDetail, status_code=201)
async def create_runbook(body: RunbookCreate, user=Depends(get_current_user)):
    embedding = await _embed(f"{body.title}\n{body.anomaly_type}\n{body.content}")
    async with get_tenant_conn(user.org_id) as conn:
        r = await conn.fetchrow(
            """INSERT INTO runbooks (org_id, title, anomaly_type, content, embedding)
               VALUES ($1::uuid, $2, $3, $4, $5::vector)
               RETURNING id, title, anomaly_type, content, created_by, created_at, updated_at,
                         (embedding IS NOT NULL) AS has_embedding""",
            user.org_id,
            body.title,
            body.anomaly_type,
            body.content,
            str(embedding) if embedding else None,
        )
    return RunbookDetail(
        id=str(r["id"]),
        title=r["title"],
        anomaly_type=r["anomaly_type"],
        content=r["content"],
        created_by=None,
        created_at=r["created_at"].isoformat(),
        updated_at=r["updated_at"].isoformat(),
        has_embedding=r["has_embedding"],
    )


@router.put("/runbooks/{runbook_id}", response_model=RunbookDetail)
async def update_runbook(
    runbook_id: str, body: RunbookUpdate, user=Depends(get_current_user)
):
    async with get_tenant_conn(user.org_id) as conn:
        existing = await conn.fetchrow(
            "SELECT * FROM runbooks WHERE org_id=$1::uuid AND id=$2::uuid",
            user.org_id,
            runbook_id,
        )
        if not existing:
            raise HTTPException(status_code=404, detail="Runbook not found")

        new_title = body.title or existing["title"]
        new_type = body.anomaly_type or existing["anomaly_type"]
        new_content = body.content or existing["content"]

        embedding = await _embed(f"{new_title}\n{new_type}\n{new_content}")

        r = await conn.fetchrow(
            """UPDATE runbooks SET title=$1, anomaly_type=$2, content=$3, embedding=$4::vector,
               updated_at=now()
               WHERE id=$5::uuid AND org_id=$6::uuid
               RETURNING id, title, anomaly_type, content, created_by, created_at, updated_at,
                         (embedding IS NOT NULL) AS has_embedding""",
            new_title,
            new_type,
            new_content,
            str(embedding) if embedding else None,
            runbook_id,
            user.org_id,
        )
    return RunbookDetail(
        id=str(r["id"]),
        title=r["title"],
        anomaly_type=r["anomaly_type"],
        content=r["content"],
        created_by=str(r["created_by"]) if r["created_by"] else None,
        created_at=r["created_at"].isoformat(),
        updated_at=r["updated_at"].isoformat(),
        has_embedding=r["has_embedding"],
    )


@router.delete("/runbooks/{runbook_id}", status_code=204)
async def delete_runbook(runbook_id: str, user=Depends(get_current_user)):
    async with get_tenant_conn(user.org_id) as conn:
        result = await conn.execute(
            "DELETE FROM runbooks WHERE id=$1::uuid AND org_id=$2::uuid",
            runbook_id,
            user.org_id,
        )
        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="Runbook not found")
