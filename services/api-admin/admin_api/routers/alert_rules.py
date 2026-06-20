from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..auth import get_current_user, require_admin
from ..db import get_tenant_conn

router = APIRouter(prefix="/alert-rules", tags=["alert-rules"])


class AlertRuleCreate(BaseModel):
    name: str
    rule_type: str = "threshold"
    condition_json: dict
    notification_channels: list = []
    cooldown_minutes: int = 15
    enabled: bool = True


class AlertRuleResponse(BaseModel):
    id: str
    name: str
    rule_type: str
    condition_json: dict
    notification_channels: list
    cooldown_minutes: int
    enabled: bool
    created_at: datetime


def _row_to_resp(r) -> AlertRuleResponse:
    return AlertRuleResponse(
        id=str(r["id"]),
        name=r["name"],
        rule_type=r["rule_type"],
        condition_json=dict(r["condition_json"]),
        notification_channels=list(r["notification_channels"]),
        cooldown_minutes=r["cooldown_minutes"],
        enabled=r["enabled"],
        created_at=r["created_at"],
    )


@router.get("", response_model=list[AlertRuleResponse])
async def list_alert_rules(user=Depends(get_current_user)):
    async with get_tenant_conn(user.org_id) as conn:
        rows = await conn.fetch(
            "SELECT id, name, rule_type, condition_json, notification_channels, "
            "cooldown_minutes, enabled, created_at FROM alert_rules ORDER BY created_at DESC"
        )
    return [_row_to_resp(r) for r in rows]


@router.post("", response_model=AlertRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_alert_rule(body: AlertRuleCreate, user=Depends(require_admin)):
    async with get_tenant_conn(user.org_id) as conn:
        row = await conn.fetchrow(
            "INSERT INTO alert_rules "
            "(org_id, name, rule_type, condition_json, notification_channels, cooldown_minutes, enabled, created_by) "
            "VALUES ($1::uuid, $2, $3, $4::jsonb, $5::jsonb, $6, $7, $8::uuid) "
            "RETURNING id, name, rule_type, condition_json, notification_channels, cooldown_minutes, enabled, created_at",
            user.org_id,
            body.name,
            body.rule_type,
            json.dumps(body.condition_json),
            json.dumps(body.notification_channels),
            body.cooldown_minutes,
            body.enabled,
            user.sub,
        )
    return _row_to_resp(row)


@router.patch("/{rule_id}", response_model=AlertRuleResponse)
async def update_alert_rule(
    rule_id: str, body: AlertRuleCreate, user=Depends(require_admin)
):
    async with get_tenant_conn(user.org_id) as conn:
        row = await conn.fetchrow(
            "UPDATE alert_rules SET name=$1, condition_json=$2::jsonb, "
            "notification_channels=$3::jsonb, cooldown_minutes=$4, enabled=$5, updated_at=now() "
            "WHERE id=$6::uuid "
            "RETURNING id, name, rule_type, condition_json, notification_channels, cooldown_minutes, enabled, created_at",
            body.name,
            json.dumps(body.condition_json),
            json.dumps(body.notification_channels),
            body.cooldown_minutes,
            body.enabled,
            rule_id,
        )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _row_to_resp(row)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_rule(rule_id: str, user=Depends(require_admin)):
    async with get_tenant_conn(user.org_id) as conn:
        result = await conn.execute(
            "DELETE FROM alert_rules WHERE id = $1::uuid", rule_id
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
