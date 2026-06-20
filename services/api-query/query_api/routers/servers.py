from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..auth import get_current_user
from ..cache import get_cached, set_cached
from ..db import get_tenant_conn

router = APIRouter(prefix="/servers", tags=["servers"])


class ServerStatus(BaseModel):
    id: str
    name: str
    hostname: str
    status: str
    agent_version: str | None
    last_heartbeat: datetime | None


class ServerSummary(BaseModel):
    id: str
    name: str
    hostname: str
    status: str
    cpu_pct: float | None
    ram_pct: float | None
    disk_pct: float | None
    anomaly_count_24h: int


@router.get("", response_model=list[ServerStatus])
async def list_servers(user=Depends(get_current_user)):
    async with get_tenant_conn(user.org_id) as conn:
        rows = await conn.fetch(
            "SELECT id, name, hostname, status, agent_version, last_heartbeat "
            "FROM servers ORDER BY name"
        )
    return [
        ServerStatus(
            id=str(r["id"]),
            name=r["name"],
            hostname=r["hostname"],
            status=r["status"],
            agent_version=r["agent_version"],
            last_heartbeat=r["last_heartbeat"],
        )
        for r in rows
    ]


@router.get("/{server_id}/summary", response_model=ServerSummary)
async def server_summary(server_id: str, user=Depends(get_current_user)):
    cached = await get_cached("srv_summary", org_id=user.org_id, server_id=server_id)
    if cached:
        return cached

    now = datetime.now(tz=timezone.utc)
    since_5m = now - timedelta(minutes=5)
    since_24h = now - timedelta(hours=24)

    async with get_tenant_conn(user.org_id) as conn:
        srv = await conn.fetchrow(
            "SELECT id, name, hostname, status FROM servers WHERE id = $1::uuid",
            server_id,
        )
        if not srv:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

        metric_rows = await conn.fetch(
            "SELECT DISTINCT ON (metric_name) metric_name, value FROM metrics "
            "WHERE org_id = $1::uuid AND server_id = $2::uuid "
            "AND metric_name = ANY($3) AND time >= $4 "
            "ORDER BY metric_name, time DESC",
            user.org_id,
            server_id,
            [
                "system.cpu.utilization",
                "system.memory.utilization",
                "system.filesystem.utilization",
            ],
            since_5m,
        )
        metrics_map = {r["metric_name"]: r["value"] for r in metric_rows}

        anomaly_count = await conn.fetchval(
            "SELECT count(*) FROM anomaly_events "
            "WHERE org_id = $1::uuid AND server_id = $2::uuid AND time >= $3",
            user.org_id,
            server_id,
            since_24h,
        )

    result = {
        "id": str(srv["id"]),
        "name": srv["name"],
        "hostname": srv["hostname"],
        "status": srv["status"],
        "cpu_pct": round(metrics_map.get("system.cpu.utilization", 0) * 100, 1),
        "ram_pct": round(metrics_map.get("system.memory.utilization", 0) * 100, 1),
        "disk_pct": round(metrics_map.get("system.filesystem.utilization", 0) * 100, 1),
        "anomaly_count_24h": anomaly_count or 0,
    }
    await set_cached(
        result, "srv_summary", ttl_seconds=30, org_id=user.org_id, server_id=server_id
    )
    return result
