from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..auth import get_current_user, require_admin
from ..db import get_conn

router = APIRouter(prefix="/orgs", tags=["organizations"])


class OrgCreate(BaseModel):
    name: str
    plan: str = "free"


class OrgResponse(BaseModel):
    id: str
    name: str
    plan: str
    created_at: datetime


@router.get("", response_model=list[OrgResponse])
async def list_orgs(user=Depends(require_admin)):
    async with get_conn() as conn:
        rows = await conn.fetch(
            "SELECT id, name, plan, created_at FROM organizations ORDER BY created_at DESC"
        )
    return [OrgResponse(id=str(r["id"]), name=r["name"], plan=r["plan"], created_at=r["created_at"]) for r in rows]


@router.post("", response_model=OrgResponse, status_code=status.HTTP_201_CREATED)
async def create_org(body: OrgCreate, user=Depends(require_admin)):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "INSERT INTO organizations (name, plan) VALUES ($1, $2) RETURNING id, name, plan, created_at",
            body.name, body.plan,
        )
    return OrgResponse(id=str(row["id"]), name=row["name"], plan=row["plan"], created_at=row["created_at"])


@router.get("/{org_id}", response_model=OrgResponse)
async def get_org(org_id: str, user=Depends(get_current_user)):
    if user.role != "admin" and user.org_id != org_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, plan, created_at FROM organizations WHERE id = $1::uuid", org_id
        )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Org not found")
    return OrgResponse(id=str(row["id"]), name=row["name"], plan=row["plan"], created_at=row["created_at"])


@router.patch("/{org_id}", response_model=OrgResponse)
async def update_org(org_id: str, body: OrgCreate, user=Depends(require_admin)):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "UPDATE organizations SET name=$1, plan=$2, updated_at=now() WHERE id=$3::uuid "
            "RETURNING id, name, plan, created_at",
            body.name, body.plan, org_id,
        )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return OrgResponse(id=str(row["id"]), name=row["name"], plan=row["plan"], created_at=row["created_at"])


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_org(org_id: str, user=Depends(require_admin)):
    async with get_conn() as conn:
        result = await conn.execute("DELETE FROM organizations WHERE id = $1::uuid", org_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
