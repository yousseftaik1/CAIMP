from __future__ import annotations

import json
import logging

from nats_client.client import NatsClient

from .hub import hub

log = logging.getLogger(__name__)


def _org_from_anomaly_subject(subject: str) -> str | None:
    # anomaly.detected.{org_id}.{severity}
    parts = subject.split(".")
    return parts[2] if len(parts) >= 4 else None


def _org_from_explanation_subject(subject: str) -> str | None:
    # ai.explanation.ready.{org_id}.{incident_id}
    parts = subject.split(".")
    return parts[3] if len(parts) >= 5 else None


async def start_fanout(nc: NatsClient) -> None:
    """
    Subscribe to live NATS subjects and fan-out to WebSocket clients.
    Uses core NATS subscriptions (not JetStream pull) for ephemeral delivery.
    JetStream-published messages are also received by core subscribers.
    """

    async def on_anomaly(msg) -> None:
        org_id = _org_from_anomaly_subject(msg.subject)
        if not org_id:
            return
        try:
            payload = json.loads(msg.data)
            payload["_event"] = "anomaly"
            await hub.broadcast(org_id, payload)
        except Exception as exc:
            log.debug("Anomaly fanout error: %s", exc)

    async def on_explanation(msg) -> None:
        org_id = _org_from_explanation_subject(msg.subject)
        if not org_id:
            return
        try:
            payload = json.loads(msg.data)
            payload["_event"] = "explanation"
            await hub.broadcast(org_id, payload)
        except Exception as exc:
            log.debug("Explanation fanout error: %s", exc)

    await nc.nc.subscribe("anomaly.detected.>", cb=on_anomaly)
    await nc.nc.subscribe("ai.explanation.ready.>", cb=on_explanation)

    log.info("NATS fanout subscriptions active")
