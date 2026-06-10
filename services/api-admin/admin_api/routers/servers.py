from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..auth import get_current_user, require_admin
from ..db import get_tenant_conn

router = APIRouter(prefix="/servers", tags=["servers"])


class ServerCreate(BaseModel):
    name: str
    hostname: str
    ip_address: str | None = None
    role: str = "generic"
    labels: dict = {}


class ServerResponse(BaseModel):
    id: str
    org_id: str
    name: str
    hostname: str
    status: str
    agent_version: str | None
    last_heartbeat: datetime | None
    created_at: datetime


class EnrollmentTokenResponse(BaseModel):
    token: str
    server_id: str
    expires_at: datetime


@router.get("", response_model=list[ServerResponse])
async def list_servers(user=Depends(get_current_user)):
    async with get_tenant_conn(user.org_id) as conn:
        rows = await conn.fetch(
            "SELECT id, org_id, name, hostname, status, agent_version, last_heartbeat, created_at "
            "FROM servers ORDER BY created_at DESC"
        )
    return [
        ServerResponse(
            id=str(r["id"]), org_id=str(r["org_id"]),
            name=r["name"], hostname=r["hostname"],
            status=r["status"], agent_version=r["agent_version"],
            last_heartbeat=r["last_heartbeat"], created_at=r["created_at"],
        )
        for r in rows
    ]


@router.post("", response_model=ServerResponse, status_code=status.HTTP_201_CREATED)
async def register_server(body: ServerCreate, user=Depends(require_admin)):
    async with get_tenant_conn(user.org_id) as conn:
        row = await conn.fetchrow(
            "INSERT INTO servers (org_id, name, hostname, ip_address, role, labels) "
            "VALUES ($1::uuid, $2, $3, $4::inet, $5, $6::jsonb) "
            "RETURNING id, org_id, name, hostname, status, agent_version, last_heartbeat, created_at",
            user.org_id, body.name, body.hostname,
            body.ip_address, body.role, json.dumps(body.labels),
        )
    return ServerResponse(
        id=str(row["id"]), org_id=str(row["org_id"]),
        name=row["name"], hostname=row["hostname"],
        status=row["status"], agent_version=row["agent_version"],
        last_heartbeat=row["last_heartbeat"], created_at=row["created_at"],
    )


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server(server_id: str, user=Depends(require_admin)):
    async with get_tenant_conn(user.org_id) as conn:
        result = await conn.execute("DELETE FROM servers WHERE id = $1::uuid", server_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.post("/{server_id}/enrollment-token", response_model=EnrollmentTokenResponse)
async def generate_enrollment_token(server_id: str, user=Depends(require_admin)):
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(tz=timezone.utc) + timedelta(hours=24)
    async with get_tenant_conn(user.org_id) as conn:
        srv = await conn.fetchrow("SELECT id FROM servers WHERE id = $1::uuid", server_id)
        if not srv:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
        await conn.execute(
            "INSERT INTO enrollment_tokens (token, server_id, org_id, expires_at) "
            "VALUES ($1, $2::uuid, $3::uuid, $4)",
            token, server_id, user.org_id, expires_at,
        )
    return EnrollmentTokenResponse(token=token, server_id=server_id, expires_at=expires_at)
