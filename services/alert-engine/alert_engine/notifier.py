from __future__ import annotations

import json
import logging

import asyncpg
import httpx

log = logging.getLogger(__name__)


async def fire_notification(
    pool: asyncpg.Pool,
    org_id: str,
    server_id: str | None,
    alert_rule_id: str,
    severity: str,
    message: str,
    channels: list[dict],
) -> None:
    """Persist notification to DB and dispatch to configured channels."""
    await pool.execute(
        """INSERT INTO notifications
               (org_id, server_id, alert_rule_id, severity, message, channel)
           VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6)""",
        org_id,
        server_id,
        alert_rule_id,
        severity,
        message,
        json.dumps(channels),
    )

    for ch in channels:
        ch_type = ch.get("type", "log")
        if ch_type == "webhook":
            await _send_webhook(ch.get("url", ""), org_id, server_id, message, severity)
        else:
            log.warning(
                "ALERT fired | org=%s server=%s severity=%s message=%s",
                org_id,
                server_id,
                severity,
                message,
            )


async def _send_webhook(
    url: str,
    org_id: str,
    server_id: str | None,
    message: str,
    severity: str,
) -> None:
    if not url:
        return
    payload = {
        "org_id": org_id,
        "server_id": server_id,
        "message": message,
        "severity": severity,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            log.debug("Webhook delivered to %s (status=%d)", url, resp.status_code)
    except Exception as exc:
        log.warning("Webhook delivery failed to %s: %s", url, exc)
